"""Feature-idea decision engine: one PM question in, a traceable per-market answer out.

    idea text -> matched VFC features (alias / name / text classifier, PM confirms)
              -> per (model, market) cell: four evidence signals in [0, 1]
              -> weighted score -> Prioritise / Consider / Low priority
              -> action type from the DE price list (fix, make standard, introduce)

Signals (each cites its source rows; a missing signal is shown, never imputed)
    complaints  channel-adjusted complaint verdict of the feature in that model + market
    breadth     how many of the model's customers raise the feature at all (percentile)
    requests    channel-adjusted request index ('Wants') in that model + market
    survey      how weak the matching survey attribute is in that model + market (percentile)

Weights, market multipliers and thresholds are policy, not data: they live in
DEFAULT_POLICY, are returned with every result and hashed, so two PMs with the
same policy and data get the same answer and an override is visible.
"""

import copy
import hashlib
import json
import re

import numpy as np
import pandas as pd

from . import config, scoring, taxonomy
from .verdict import load_catalog, load_context

MARKETS = ["EU", "US", "CN", "RoW"]
MARKET_NAMES = {"EU": "Europe", "US": "United States", "CN": "China", "RoW": "Rest of world"}
SALES_GROUP = {"F70": "F70", "G60": "G60_G68", "G70": "G70"}
CN_SURVEY_MODEL = {"G60": "G68", "G70": "G70"}       # the CN survey covers the long-wheelbase G68, not G60

DEFAULT_POLICY = {
    "version": "1.0",
    "weights": {"complaints": 0.4, "breadth": 0.2, "requests": 0.2, "survey": 0.2},
    "market_multipliers": {"EU": 1.0, "US": 1.0, "CN": 1.0, "RoW": 1.0},
    "volume_year": 2025,
    "thresholds": {"prioritise": 0.6, "consider": 0.35, "min_coverage": 0.5},
    "borrowing": {"enabled": True, "discount": 0.5, "into_cn": False},
    # Fixed mappings from evidence to signal points (not editable in the UI, but hashed and shown)
    "scoring": {
        "complaint_points": {"Bad": 1.0, "Leaning bad": 0.67, "Mixed": 0.33, "Leaning good": 0.0, "Good": 0.0},
        "request_points": {"requested": 1.0, "index_at_least": config.LEAN_BAD_INDEX, "elevated": 0.5, "otherwise": 0.0},
        "min_comments_for_signal": config.MIN_MENTIONS_FOR_VERDICT,
        "survey_weakness": "(rank - 1) / (attributes - 1); rank 1 = best-rated attribute of that series in that market",
        "breadth": "percentile of the feature's comment count among the series' features (all markets)",
    },
    "rationale": {
        "weights": "Complaints weigh twice as much as requests (PM guidance: complaints and defects outrank "
                   "wish-list features). Breadth rewards features many customers raise over niche ones.",
        "market_multipliers": "1.0 = market weighted by its sales volume. Raise a market to emphasise it "
                              "(e.g. a regional strategy); lower to de-emphasise.",
        "thresholds": "A cell needs at least half of the weighted evidence present to get a recommendation.",
        "borrowing": "When a model + market has fewer than 8 comments on the feature, the model's verdict over "
                     "all markets is used at a discounted weight and labelled 'borrowed'. China has no customer "
                     "feedback in the data and configurations differ by market, so it does not borrow by default.",
    },
}
SIGNALS = ["complaints", "breadth", "requests", "survey"]


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def data_fingerprint() -> dict:
    """Content hash of every raw input file, so a decision can be tied to the exact data."""
    files = sorted(config.RAW_DIR.glob("*"))
    h = hashlib.sha256()
    listing = []
    for f in files:
        if f.is_file():
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            h.update(f.name.encode() + digest.encode())
            listing.append({"file": f.name, "sha256": digest[:12], "bytes": f.stat().st_size})
    return {"hash": h.hexdigest()[:12], "files": listing}


def policy_hash(policy: dict) -> str:
    """Hash of everything that changes a score: weights, multipliers, thresholds, year, borrowing, scoring, version."""
    return _hash({k: policy[k] for k in ("version", "weights", "market_multipliers", "thresholds", "volume_year",
                                         "borrowing", "scoring")})


def merge_policy(overrides: dict | None) -> dict:
    policy = copy.deepcopy(DEFAULT_POLICY)
    for key in ("weights", "market_multipliers", "thresholds"):
        for k, v in ((overrides or {}).get(key) or {}).items():
            if k in policy[key] and v is not None:
                policy[key][k] = float(v)
    b = (overrides or {}).get("borrowing") or {}
    if "enabled" in b:
        policy["borrowing"]["enabled"] = bool(b["enabled"])
    if "into_cn" in b:
        policy["borrowing"]["into_cn"] = bool(b["into_cn"])
    if b.get("discount") is not None:
        policy["borrowing"]["discount"] = min(max(float(b["discount"]), 0.0), 1.0)
    if (overrides or {}).get("volume_year") in (2024, 2025, 2030):
        policy["volume_year"] = int(overrides["volume_year"])
    return policy


class DecisionEngine:
    def __init__(self, ctx=None):
        self.ctx = ctx or load_context()
        p = config.PROCESSED_DIR
        self.catalog = self.ctx.catalog or load_catalog()
        self.sales = pd.read_csv(p / "sales.csv")
        self.survey_eu_cn = pd.read_csv(p / "survey_cn_eu.csv")
        self.survey_us = pd.read_csv(p / "survey_us_summary.csv")
        self.cells = scoring.score(self.ctx.labels, group_keys=("feature", "model", "market")).set_index(
            ["feature", "model", "market"])
        self.units = scoring.feature_units(self.ctx.labels)
        self.breadth_table = self._breadth_table()
        self._survey_rank = self._survey_ranks()
        self.fingerprint = data_fingerprint()

    # ------------------------------------------------------------------ evidence tables
    def _breadth_table(self) -> pd.DataFrame:
        """Per model: comments mentioning each feature, and its percentile among the model's features."""
        u = self.units.drop_duplicates(["comment_id", "feature"])
        counts = u.groupby(["model", "feature"])["comment_id"].nunique().rename("n").reset_index()
        totals = self.ctx.labels.drop_duplicates("comment_id").groupby("model")["comment_id"].nunique()
        counts["model_comments"] = counts["model"].map(totals)
        counts["share"] = counts["n"] / counts["model_comments"]
        counts["percentile"] = counts.groupby("model")["n"].rank(pct=True, method="max")
        counts["n_features"] = counts.groupby("model")["feature"].transform("size")
        return counts.set_index(["model", "feature"])

    def _survey_ranks(self) -> dict:
        """(market, survey_model) -> attribute table with rank 1 = best-rated attribute."""
        out = {}
        s = self.survey_eu_cn[self.survey_eu_cn["attribute"] != "Overall product satisfaction"]
        for (market, model), g in s.groupby(["market", "model"]):
            g = g.assign(rank=g["mean"].rank(ascending=False, method="min"), n=len(g),
                         overall_mean=g["mean"].mean())
            out[(market, model)] = g.set_index("attribute")
        for model, g in self.survey_us.groupby("model"):
            g = g.assign(rank=g["top2_box"].rank(ascending=False, method="min"), n=len(g),
                         overall_top2=g["top2_box"].mean())
            out[("US", model)] = g.set_index("attribute")
        return out

    # ------------------------------------------------------------------ idea -> features
    def resolve_idea(self, idea: str, top_k: int = 6) -> dict:
        from .classifier import predict
        matches = {}
        for m in self._name_matches(idea):
            matches[m["feature"]] = m
        pred = predict([idea])[0]
        for f, p in predict([idea], top_k=top_k)[0]["feature"]:
            if f not in matches and f in self.ctx.features.index:
                matches[f] = {"feature": f, "score": float(p), "how": "text classifier"}
        ranked = sorted(matches.values(), key=lambda m: -m["score"])
        for m in ranked:
            row = self.ctx.features.loc[m["feature"]]
            m.update(domain=row["domain"], n_comments=int(row["n_comments"]), verdict=row["verdict"],
                     umbrella=bool(row["is_umbrella"]))
        top = ranked[0]["score"] if ranked else 0
        status = "direct" if top >= 0.5 else "related" if top >= 0.15 else "none"
        return {"idea": idea, "status": status, "matches": ranked,
                "suggested": [m["feature"] for m in ranked if m["score"] >= 0.5][:2],
                "predicted_domains": [{"domain": d, "score": float(s)} for d, s in pred["domain"]],
                "predicted_feedback_type": [{"type": t, "score": float(s)} for t, s in pred["feedback_type"]]}

    def _name_matches(self, idea: str) -> list:
        """Alias, exact and substring matches score 1.0; fuzzy name matches score their similarity."""
        import difflib
        q = re.sub(r"\s+", " ", idea.strip().lower())
        if not q:
            return []
        names = list(self.ctx.features.index)
        aliases = _aliases()
        out = []
        if q in aliases:
            out.append({"feature": aliases[q], "score": 1.0, "how": "alias"})
        for n in names:
            nl = n.lower()
            if nl == q or (len(q) >= 4 and q in nl):
                out.append({"feature": n, "score": 1.0, "how": "feature name"})
        for alias, target in aliases.items():
            if len(alias) >= 4 and re.search(rf"\b{re.escape(alias)}\b", q) and q not in aliases:
                out.append({"feature": target, "score": 0.9, "how": f"alias '{alias}' in idea"})
        if not out:
            for n in names:
                ratio = difflib.SequenceMatcher(None, q, n.lower()).ratio()
                if ratio >= 0.8:
                    out.append({"feature": n, "score": round(ratio, 2), "how": "fuzzy name"})
        seen, unique = set(), []
        for m in sorted(out, key=lambda m: -m["score"]):
            if m["feature"] not in seen and m["feature"] in self.ctx.features.index:
                seen.add(m["feature"])
                unique.append(m)
        return unique

    # ------------------------------------------------------------------ signals
    def _sales(self, model, market, year):
        s = self.sales[(self.sales["model_group"] == SALES_GROUP[model]) & (self.sales["market_code"] == market)]
        vol = {int(r.year): float(r.volume) for r in s.itertuples()}
        return vol

    def _feedback_row(self, feature, model, market, policy):
        """(row, level) for the feature in model + market, or the model's all-market row if borrowing."""
        key = (feature, model, market)
        row = self.cells.loc[key] if key in self.cells.index else None
        n = int(row["n_comments"]) if row is not None else 0
        min_n = policy["scoring"]["min_comments_for_signal"]
        if n >= min_n:
            return row, "market", n
        b = policy["borrowing"]
        if b["enabled"] and (market != "CN" or b["into_cn"]) and (feature, model) in self.ctx.by_model.index:
            m = self.ctx.by_model.loc[(feature, model)]
            if m["n_comments"] >= min_n:
                return m, "borrowed", n
        return row, "none", n

    def _complaints(self, feature, model, market, policy):
        r, level, n_market = self._feedback_row(feature, model, market, policy)
        if r is None:
            return {"score": None, "status": f"no comments in {model} {market}", "n_comments": 0}
        ev = {"n_comments": int(r["n_comments"]), "n_comments_market": n_market, "level": level,
              "verdict": r["verdict"], "complaint_index": round(float(r["index_negative"]), 2),
              "ci_low": round(float(r["ci_low_negative"]), 2), "ci_high": round(float(min(r["ci_high_negative"], 99)), 2),
              "observed": int(r["obs_negative"]), "expected": round(float(r["exp_negative"]), 1)}
        if level == "none":
            return {**ev, "score": None,
                    "status": f"only {n_market} comments in {model} {market} "
                              f"(<{policy['scoring']['min_comments_for_signal']})"}
        status = "ok" if level == "market" else f"borrowed from {model} all markets ({n_market} in {market})"
        return {**ev, "score": policy["scoring"]["complaint_points"][r["verdict"]], "status": status}

    def _requests(self, feature, model, market, policy):
        r, level, n_market = self._feedback_row(feature, model, market, policy)
        if r is None:
            return {"score": None, "status": f"no comments in {model} {market}", "n_comments": 0}
        ev = {"n_comments": int(r["n_comments"]), "n_comments_market": n_market, "level": level,
              "request_index": round(float(r["index_request"]), 2), "ci_low": round(float(r["ci_low_request"]), 2),
              "observed": int(r["obs_request"]), "expected": round(float(r["exp_request"]), 1),
              "requested": bool(r["requested"])}
        if level == "none":
            return {**ev, "score": None, "status": f"only {n_market} comments in {model} {market}"}
        rp = policy["scoring"]["request_points"]
        score = (rp["requested"] if r["requested"] else rp["elevated"] if r["index_request"] >= rp["index_at_least"]
                 else rp["otherwise"])
        status = "ok" if level == "market" else f"borrowed from {model} all markets ({n_market} in {market})"
        return {**ev, "score": score, "status": status}

    def _breadth(self, feature, model, market, policy):
        b = policy["borrowing"]
        if market == "CN" and not (b["enabled"] and b["into_cn"]):
            return {"score": None, "status": "no customer feedback from China in the data"}
        if model not in self.breadth_table.index.get_level_values(0):
            return {"score": None, "status": "no feedback for this model"}
        if (model, feature) not in self.breadth_table.index:
            return {"score": 0.0, "status": "ok", "n_comments": 0,
                    "model_comments": int(self.breadth_table.loc[model]["model_comments"].iloc[0])}
        r = self.breadth_table.loc[(model, feature)]
        return {"score": round(float(r["percentile"]), 3), "status": "ok", "n_comments": int(r["n"]),
                "model_comments": int(r["model_comments"]), "share": round(float(r["share"]), 4),
                "rank_among_features": int(r["n_features"] - round(r["percentile"] * r["n_features"]) + 1),
                "n_features": int(r["n_features"])}

    def _survey(self, feature, model, market):
        if market == "CN":
            smodel, sheet = CN_SURVEY_MODEL.get(model), "CN_EU_2025 (China)"
        elif market == "EU":
            smodel, sheet = model, "CN_EU_2025 (EU)"
        elif market == "US":
            smodel, sheet = model, "US_2025"
        else:
            return {"score": None, "status": "no survey for Rest of World"}
        table = self._survey_rank.get((market, smodel))
        if table is None:
            return {"score": None, "status": f"no {market} survey for {model}"}
        mapping = taxonomy.US_SURVEY_TO_FEATURES if market == "US" else taxonomy.CN_EU_SURVEY_TO_FEATURES
        attrs = [a for a, fs in mapping.items() if feature in fs and a in table.index]
        if not attrs:
            return {"score": None, "status": "no matching survey attribute", "survey_model": smodel}
        rows = []
        for a in attrs:
            r = table.loc[a]
            weakness = (r["rank"] - 1) / (r["n"] - 1)
            row = {"attribute": a, "rank": int(r["rank"]), "of": int(r["n"]), "weakness": round(float(weakness), 3)}
            if market == "US":
                row.update(top2_box=round(float(r["top2_box"]), 3), bottom3_box=round(float(r["bottom3_box"]), 3),
                           model_mean_top2=round(float(r["overall_top2"]), 3))
            else:
                row.update(mean=round(float(r["mean"]), 2), model_mean=round(float(r["overall_mean"]), 2))
            rows.append(row)
        return {"score": round(float(np.mean([r["weakness"] for r in rows])), 3), "status": "ok",
                "sheet": sheet, "survey_model": smodel, "attributes": rows,
                "note": "CN survey covers the G68 (5 Series long wheelbase), not the G60" if smodel == "G68" else None}

    def _fitment(self, feature, model):
        summary = self.catalog.get("feature_fitment_summary")
        links = self.catalog.get("feature_option_links")
        if summary is None:
            return None
        s = summary[(summary["feature"] == feature) & (summary["model"] == model)]
        lk = links[(links["feature"] == feature) & (links["model"] == model)]
        listed_on = sorted(set(summary.loc[summary["feature"] == feature, "model"]) - {model})
        if s.empty:
            linked = feature in set(links["feature"])
            return {"tier": "not_listed" if linked else "no_link", "items": [], "listed_on": listed_on}
        r = s.iloc[0]
        return {"tier": r["tier"], "listed_on": listed_on, "n_variants": int(r["n_variants"]),
                "n_standard": int(r["n_standard"]),
                "n_optional": int(r["n_optional"]), "price_min_eur": _num(r["price_min_eur"]),
                "price_item": None if pd.isna(r["price_item"]) else r["price_item"],
                "price_via_package": None if pd.isna(r["price_via_package"]) else bool(r["price_via_package"]),
                "price_max_eur": _num(r["price_max_eur"]), "price_pct_of_base": _num(r["price_pct_of_base"]),
                "items": [{"name": x.option_name, "sa_code": None if pd.isna(x.sa_code) else x.sa_code,
                           "page": int(x.page), "matched_keyword": x.matched_keyword, "matched_in": x.matched_in}
                          for x in lk.itertuples()]}

    def _quotes(self, feature, model, market, n=2):
        lab = self.ctx.labels[(self.ctx.labels["feature"] == feature) & (self.ctx.labels["model"] == model)
                              & (self.ctx.labels["market"] == market)].drop_duplicates(["comment_id", "sentiment"])
        ids = sorted(lab["comment_id"].unique().tolist())
        merged = lab.merge(self.ctx.comments[["comment_id", "text", "n_labels", "n_words"]], on="comment_id")
        merged = merged[merged["n_words"] >= 6].assign(len_pen=lambda d: (d["text"].str.len() - 140).abs())
        merged = merged.sort_values(["n_labels", "len_pen"])
        quotes = [{"comment_id": r.comment_id, "sentiment": r.sentiment, "feedback_type": r.feedback_type,
                   "source": r.source, "country": r.country, "reason": r.reason, "text": r.text[:320]}
                  for r in merged.drop_duplicates("sentiment").head(n).itertuples()]
        return ids, quotes

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, idea: str = "", features=None, policy_overrides=None, models=None, markets=None) -> dict:
        policy = merge_policy(policy_overrides)
        resolution = self.resolve_idea(idea) if idea else None
        chosen = [f for f in (features or (resolution["suggested"] if resolution else [])) if f in self.ctx.features.index]
        models = [m for m in (models or config.MODELS) if m in config.MODELS]
        markets = [m for m in (markets or MARKETS) if m in MARKETS]
        result = {"idea": idea, "resolution": resolution, "features": [], "policy": policy,
                  "policy_hash": policy_hash(policy),
                  "data_hash": self.fingerprint["hash"], "models": models, "markets": markets}
        if not chosen:
            result["status"] = "no_direct_evidence" if resolution else "no_features"
            result["headline"] = (f"No feature in the feedback data matches '{idea}' directly. Related features "
                                  "are listed with their match scores; select one to evaluate it, or treat the "
                                  "idea as new (no customer evidence in this data).") if resolution else ""
            return result
        result["status"] = "ok"
        for feature in chosen:
            result["features"].append(self._evaluate_feature(feature, policy, models, markets))
        return result

    def _evaluate_feature(self, feature, policy, models, markets) -> dict:
        w = policy["weights"]
        th = policy["thresholds"]
        row = self.ctx.features.loc[feature]
        cells = []
        for model in models:
            fit = self._fitment(feature, model)
            for market in markets:
                vol = self._sales(model, market, policy["volume_year"])
                volume = vol.get(policy["volume_year"], 0.0)
                cell = {"model": model, "model_name": config.MODEL_NAMES[model], "market": market,
                        "market_name": MARKET_NAMES[market], "sales": vol, "volume": volume,
                        "sales_note": "5 Series volumes include the G68 long wheelbase" if model == "G60" else None}
                if sum(vol.values()) == 0:
                    cells.append({**cell, "recommendation": "Not sold", "score": None, "coverage": 0.0,
                                  "signals": {}, "reasons": [f"{model} has zero sales volume in {market} "
                                                             f"in sales_volumes.xlsx (2024, 2025, 2030)."],
                                  "action": None, "evidence": {}})
                    continue
                signals = {"complaints": self._complaints(feature, model, market, policy),
                           "breadth": self._breadth(feature, model, market, policy),
                           "requests": self._requests(feature, model, market, policy),
                           "survey": self._survey(feature, model, market)}
                disc = policy["borrowing"]["discount"]
                eff = {k: w[k] * (disc if signals[k].get("level") == "borrowed" else 1.0) for k in SIGNALS}
                avail = [k for k in SIGNALS if signals[k].get("score") is not None]
                total_w = sum(w[k] for k in SIGNALS)
                avail_w = sum(eff[k] for k in avail)
                coverage = avail_w / total_w if total_w else 0
                score = sum(eff[k] * signals[k]["score"] for k in avail) / avail_w if avail_w else None
                for k in SIGNALS:
                    signals[k]["weight"] = w[k]
                    signals[k]["effective_weight"] = round(eff[k], 4)
                    signals[k]["contribution"] = (round(eff[k] * signals[k]["score"] / avail_w, 4)
                                                  if k in avail and avail_w else None)
                if coverage < th["min_coverage"] or score is None:
                    rec = "Insufficient evidence"
                elif score >= th["prioritise"]:
                    rec = "Prioritise"
                elif score >= th["consider"]:
                    rec = "Consider"
                else:
                    rec = "Low priority"
                ids, quotes = self._quotes(feature, model, market)
                cell.update(signals=signals, score=None if score is None else round(score, 3),
                            coverage=round(coverage, 3), recommendation=rec,
                            market_weight=volume * policy["market_multipliers"][market],
                            action=_action(signals, fit, market),
                            reasons=_reasons(feature, model, market, signals, rec, coverage),
                            evidence={"comment_ids": ids[:40], "n_comment_ids": len(ids), "quotes": quotes})
                cells.append(cell)
        rollup = _rollup(cells, models)
        ladder = [{"model": m, **(self._fitment(feature, m) or {})} for m in config.MODELS]
        specs = self.catalog.get("feature_specs")
        spec_rows = [] if specs is None else [
            {"model": r.model, "variant": r.variant, "attribute": r.attribute, "value": r.value, "page": int(r.page)}
            for r in specs[specs["feature"] == feature].itertuples()]
        out = {"feature": feature, "domain": row["domain"], "umbrella": bool(row["is_umbrella"]),
               "overall": {"verdict": row["verdict"], "confidence": row["confidence"],
                           "n_comments": int(row["n_comments"]),
                           "complaint_index": round(float(row["index_negative"]), 2),
                           "ci_low": round(float(row["ci_low_negative"]), 2),
                           "ci_high": round(float(min(row["ci_high_negative"], 99)), 2),
                           "request_index": round(float(row["index_request"]), 2),
                           "praise_index": round(float(row["index_positive"]), 2)},
               "cells": cells, "rollup": rollup, "price_ladder": ladder, "specs": spec_rows}
        out["headline"] = _headline(feature, cells, rollup)
        return out


# ---------------------------------------------------------------------- helpers
def _aliases():
    from .verdict import ALIASES
    return ALIASES


def _num(v):
    return None if v is None or pd.isna(v) else round(float(v), 2)


def _action(signals, fit, market) -> dict | None:
    """What kind of move the evidence points to, using the DE price list (EU cells only)."""
    c, r = signals["complaints"].get("score"), signals["requests"].get("score")
    if fit is None:
        return None
    tier = fit["tier"]
    price = fit.get("price_min_eur")
    pct = fit.get("price_pct_of_base")
    scope = "DE price list (July 2026)" if market == "EU" else "DE price list for reference only - no price list for this market in the data"
    if market != "EU":
        return {"type": "Fitment unknown for this market", "tier": tier, "basis": scope}
    pkg = f" as part of {fit['price_item']}" if fit.get("price_via_package") else ""
    if c is not None and c >= 0.67 and tier in ("standard_all", "standard_some"):
        kind = "Fix the existing standard equipment (quality / usability)"
    elif c is not None and c >= 0.67 and tier == "optional":
        kind = f"Fix a paid option (customers pay from EUR {price:,.0f}{pkg})" if price else "Fix a paid option"
    elif r is not None and r >= 0.5 and tier == "optional":
        kind = (f"Consider making standard or cheaper (now from EUR {price:,.0f}{pkg}, {pct:.1f}% of base price)"
                if price and pct else "Consider making standard or cheaper")
    elif r is not None and r >= 0.5 and tier == "not_listed" and fit.get("listed_on"):
        kind = (f"Candidate to introduce on this series (listed on {', '.join(fit['listed_on'])}; no item in this "
                "series' price list matched the curated keywords)")
    elif tier in ("standard_all", "standard_some"):
        kind = "Already standard - monitor"
    elif tier == "optional":
        kind = "Available as an option - monitor take-up"
    elif tier == "not_listed":
        kind = "No item in this series' price list matched the curated keywords - monitor"
    else:
        kind = "No curated price-list link - monitor"
    return {"type": kind, "tier": tier, "basis": scope}


def _reasons(feature, model, market, s, rec, coverage) -> list:
    out = []
    c = s["complaints"]
    if c.get("score") is not None and c.get("level") == "borrowed":
        out.append(f"Complaints: only {c['n_comments_market']} comments in {model} {market}; borrowed {model} "
                   f"all-market verdict '{c['verdict']}' (index {c['complaint_index']}, 95% CI {c['ci_low']}-"
                   f"{c['ci_high']}, {c['n_comments']} comments) at reduced weight.")
    elif c.get("score") is not None:
        out.append(f"Complaints: '{c['verdict']}' in {model} {market} (index {c['complaint_index']}, "
                   f"95% CI {c['ci_low']}-{c['ci_high']}, {c['n_comments']} comments).")
    else:
        out.append(f"Complaints: no verdict in {model} {market} ({c.get('status')}).")
    b = s["breadth"]
    if b.get("score") is not None:
        out.append(f"Breadth: {b.get('n_comments', 0)} of {b.get('model_comments', 0)} {model} comments "
                   f"(all markets) mention it, percentile {b['score']:.2f}.")
    else:
        out.append(f"Breadth: {b.get('status')}.")
    r = s["requests"]
    if r.get("score") is not None:
        src = " (borrowed, all markets)" if r.get("level") == "borrowed" else ""
        out.append(f"Requests{src}: index {r['request_index']}"
                   + (" - a significant unmet need." if r["requested"] else "."))
    sv = s["survey"]
    if sv.get("score") is not None:
        worst = max(sv["attributes"], key=lambda a: a["weakness"])
        out.append(f"Survey ({sv['sheet']}, {sv['survey_model']}): '{worst['attribute']}' ranks "
                   f"{worst['rank']} of {worst['of']} attributes.")
    else:
        out.append(f"Survey: {sv.get('status')}.")
    if rec == "Insufficient evidence":
        out.append(f"Only {coverage:.0%} of the weighted evidence is available here - no recommendation.")
    return out


def _rollup(cells, models) -> dict:
    scored = [c for c in cells if c.get("score") is not None and c["recommendation"] not in
              ("Not sold", "Insufficient evidence")]
    weight = sum(c["market_weight"] for c in scored)
    total_weight = sum(c.get("market_weight", 0) for c in cells if c["recommendation"] != "Not sold")
    by_model = {}
    for m in models:
        mc = [c for c in scored if c["model"] == m]
        mw = sum(c["market_weight"] for c in mc)
        by_model[m] = {"score": round(sum(c["score"] * c["market_weight"] for c in mc) / mw, 3) if mw else None,
                       "markets": [c["market"] for c in mc]}
    return {"score": round(sum(c["score"] * c["market_weight"] for c in scored) / weight, 3) if weight else None,
            "evidence_volume_share": round(weight / total_weight, 3) if total_weight else 0.0,
            "by_model": by_model}


def _headline(feature, cells, rollup) -> str:
    groups = {}
    for c in cells:
        groups.setdefault(c["recommendation"], []).append(f"{c['model']} {c['market']}")
    order = ["Prioritise", "Consider", "Low priority", "Insufficient evidence", "Not sold"]
    parts = [f"{k}: {', '.join(groups[k])}" for k in order if k in groups]
    score = rollup["score"]
    lead = (f"{feature}: volume-weighted priority {score:.2f} over the markets with enough evidence "
            f"({rollup['evidence_volume_share']:.0%} of sales volume).") if score is not None else \
        f"{feature}: no market has enough evidence for a recommendation."
    return lead + " " + "; ".join(parts) + "."


# ---------------------------------------------------------------------- decision log
def log_path():
    return config.ROOT / "data" / "decisions.jsonl"


def record_decision(entry: dict) -> dict:
    """Append a PM decision (accept / override + rationale) with policy and data hashes."""
    required = {"pm", "idea", "feature", "decision", "rationale", "policy_hash", "data_hash"}
    missing = required - set(entry)
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")
    if entry["decision"] not in ("accept", "override"):
        raise ValueError("decision must be 'accept' or 'override'")
    if not re.search(r"\w", entry["rationale"] or ""):
        raise ValueError("a rationale is required")
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {**entry, "id": _hash([entry, pd.Timestamp.now("UTC").isoformat()]),
             "recorded_at": pd.Timestamp.now("UTC").isoformat()}
    with path.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def read_decisions() -> list:
    path = log_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()][::-1]
