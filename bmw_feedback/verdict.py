"""PM-facing verdict cards: 'is this feature good or bad, and why?'

Two entry points:
    feature_card(name)  -> verdict for a feature that already has feedback
    text_card(comment)  -> classify a new comment, then show the verdict for
                           the feature(s) it is about
"""

import difflib
import re

import pandas as pd

from . import config, scoring

ALIASES = {
    "hud": "Head-Up Display", "head up": "Head-Up Display", "carplay": "Apple CarPlay",
    "android": "Android Auto", "idrive": "Operating concept, operating system",
    "infotainment": "ConnectedDrive and Infotainment, overall technology", "screen": "Touch screen, operation",
    "touchscreen": "Touch screen, operation", "ac": "Vehicle, climatization", "climate": "Vehicle, climatization",
    "air conditioning": "Vehicle, climatization", "hvac": "Vehicle, climatization", "sunroof": "Panorama glass roof",
    "panoramic roof": "Panorama glass roof", "range": "Electric Range", "charging": "Charge high-voltage battery",
    "key": "Vehicle key", "start stop": "Automatic engine start-stop function (MSA)",
    "start-stop": "Automatic engine start-stop function (MSA)", "ipa": "Intelligent Personal Assistant",
    "voice assistant": "Intelligent Personal Assistant", "app": "My BMW App / MINI App",
    "my bmw app": "My BMW App / MINI App", "esim": "Personal eSIM", "cruise control": "(Active) cruise control",
    "acc": "(Active) cruise control", "parking": "Parking Assistant", "camera": "Rear view camera",
    "wireless charging": "Mobile device, wireless charging", "sound system": "Audio mode, sound",
    "speakers": "Audio mode, sound", "massage": "Seat massage", "doors": "Door, open / close",
    "automatic doors": "Automatic doors", "trunk": "Trunk lid, open / close", "boot": "Luggage compartment",
    "gearbox": "Transmission", "brakes": "Braking", "seats": "Seats", "ota": "Remote Software Upgrade/RSU",
    "software update": "Remote Software Upgrade/RSU", "manual": "Owner's Manual",
}


class Context:
    """Everything a verdict needs, computed once."""

    def __init__(self, labels: pd.DataFrame, comments: pd.DataFrame, survey_us_summary=None, catalog=None):
        self.labels, self.comments = labels, comments
        self.features = scoring.score(labels).set_index("feature")
        self.domains = scoring.score(labels, group_keys=("domain",), prior_keys=()).set_index("domain")
        self.by_model = scoring.score(labels, group_keys=("feature", "model")).set_index(["feature", "model"])
        self.by_engine = scoring.score(labels, group_keys=("feature", "engine")).set_index(["feature", "engine"])
        self.survey = (scoring.survey_crosscheck(survey_us_summary) if survey_us_summary is not None
                       else pd.DataFrame())
        self.catalog = catalog or {}

    # ------------------------------------------------------------ lookup
    def resolve(self, query: str):
        """Map a free-form feature query to a VFC feature name (or None)."""
        names = list(self.features.index)
        q = query.strip().lower()
        if q in ALIASES:
            return ALIASES[q]
        exact = [n for n in names if n.lower() == q]
        if exact:
            return exact[0]
        contains = [n for n in names if q in n.lower()]
        if contains:
            return max(contains, key=lambda n: self.features.loc[n, "n_comments"])
        close = difflib.get_close_matches(q, [n.lower() for n in names], n=1, cutoff=0.6)
        if close:
            return next(n for n in names if n.lower() == close[0])
        return None

    # ------------------------------------------------------------ card
    def feature_card(self, feature: str) -> dict:
        row = self.features.loc[feature]
        domain = row["domain"]
        dom = self.domains.loc[domain]
        card = {
            "feature": feature, "domain": domain, "verdict": row["verdict"], "confidence": row["confidence"],
            "n_comments": int(row["n_comments"]), "is_umbrella_label": bool(row["is_umbrella"]),
            "requested": bool(row["requested"]), "bad_kind": scoring.bad_kind(row),
            "complaint_index": _ci(row, "negative"), "praise_index": _ci(row, "positive"),
            "request_index": _ci(row, "request"),
            "adjusted_mix": {c: round(float(row[f"adj_share_{c}"]), 3) for c in scoring.SENTIMENTS},
            "raw_mix": {c: round(float(row[f"raw_share_{c}"]), 3) for c in scoring.SENTIMENTS},
            "domain_verdict": dom["verdict"], "domain_complaint_index": round(float(dom["index_negative"]), 2),
            "reasons": scoring.reason_breakdown(self.labels, feature),
            "quotes": scoring.representative_quotes(self.labels, self.comments, feature),
            "by_model": _breakdown(self.by_model, feature), "by_engine": _breakdown(self.by_engine, feature),
            "survey": self._survey(feature), "options": self._options(feature), "specs": self._specs(feature),
        }
        card["summary"] = summary_sentence(card)
        return card

    def _survey(self, feature):
        if self.survey.empty:
            return []
        s = self.survey[self.survey["feature"] == feature]
        return [{"attribute": r.survey_attribute, "model": r.model, "top2_box": round(r.top2_box, 3),
                 "bottom3_box": round(r.bottom3_box, 3)} for r in s.itertuples()]

    def _options(self, feature):
        """Price-list fitment per model (DE price list, July 2026, EUR) with the linked items."""
        summary = self.catalog.get("feature_fitment_summary")
        links = self.catalog.get("feature_option_links")
        if summary is None or links is None:
            return []
        out = []
        for r in summary[summary["feature"] == feature].itertuples():
            lk = links[(links["feature"] == feature) & (links["model"] == r.model)]
            out.append({"model": r.model, "tier": r.tier, "n_variants": int(r.n_variants),
                        "n_standard": int(r.n_standard), "n_optional": int(r.n_optional),
                        "price_min_eur": _f(r.price_min_eur), "price_max_eur": _f(r.price_max_eur),
                        "price_pct_of_base": _f(r.price_pct_of_base),
                        "price_item": None if pd.isna(r.price_item) else r.price_item,
                        "price_via_package": None if pd.isna(r.price_via_package) else bool(r.price_via_package),
                        "items": [{"name": x.option_name, "sa_code": None if pd.isna(x.sa_code) else x.sa_code,
                                   "page": int(x.page), "page_type": x.page_type,
                                   "matched_keyword": x.matched_keyword, "matched_in": x.matched_in,
                                   "matched_text": x.matched_text} for x in lk.itertuples()]})
        return out

    def _specs(self, feature):
        specs = self.catalog.get("feature_specs")
        if specs is None:
            return []
        s = specs[specs["feature"] == feature]
        return [{"model": r.model, "variant": r.variant, "attribute": r.attribute, "value": r.value,
                 "page": int(r.page)} for r in s.itertuples()]


def _f(v):
    return None if v is None or pd.isna(v) else round(float(v), 2)


def _ci(row, c):
    return {"index": round(float(row[f"index_{c}"]), 2), "ci_low": round(float(row[f"ci_low_{c}"]), 2),
            "ci_high": round(float(row[f"ci_high_{c}"]), 2), "observed": int(row[f"obs_{c}"]),
            "expected": round(float(row[f"exp_{c}"]), 1)}


def _breakdown(table, feature):
    if feature not in table.index.get_level_values(0):
        return []
    sub = table.loc[feature]
    return [{"group": g, "n_comments": int(r["n_comments"]), "complaint_index": round(float(r["index_negative"]), 2),
             "verdict": r["verdict"]} for g, r in sub.iterrows()]


def summary_sentence(card: dict) -> str:
    """One deterministic paragraph a PM can paste into a ticket."""
    f, v, n = card["feature"], card["verdict"], card["n_comments"]
    ci = card["complaint_index"]
    if v == "Not enough data":
        return (f"{f} has only {n} comment(s): too few for a verdict. Its domain ({card['domain']}) is rated "
                f"'{card['domain_verdict']}' (complaint index {card['domain_complaint_index']}); use that as the prior.")
    pct = round((ci["index"] - 1) * 100)
    direction = f"{abs(pct)}% more" if pct > 0 else f"{abs(pct)}% fewer"
    text = (f"{f} is rated '{v.upper()}' ({card['confidence']} confidence, {n} comments). Customers raise "
            f"{direction} complaints than for comparable features from the same channels "
            f"(complaint index {ci['index']}, 95% CI {ci['ci_low']}-{ci['ci_high']}).")
    pos = card["reasons"]["positive"]["families"]
    neg = card["reasons"]["negative"]["families"]
    req = card["reasons"]["request"]["families"]
    if pos:
        text += f" Praise centres on: {', '.join(list(pos)[:2]).lower()}."
    if neg:
        text += f" Complaints are {card['bad_kind']}, mainly: {', '.join(list(neg)[:2]).lower()}."
    if card["requested"] and req:
        text += f" It is also an unmet need - customers ask for: {', '.join(list(req)[:2]).lower()}."
    if card["is_umbrella_label"]:
        text += " Note: this is an umbrella label; annotators file general praise here, so judge it at domain level."
    return text


def render_markdown(card: dict) -> str:
    """Human-readable card for the terminal."""
    lines = [f"## {card['feature']} -> {card['verdict']}",
             f"*{card['domain']}* | confidence: {card['confidence']} | {card['n_comments']} comments", "",
             card["summary"], ""]
    if card["verdict"] != "Not enough data":
        mix = card["adjusted_mix"]
        lines += [f"Channel-adjusted mix: {mix['positive']:.0%} praise, {mix['negative']:.0%} complaints, "
                  f"{mix['request']:.0%} requests (raw: {card['raw_mix']['positive']:.0%} / "
                  f"{card['raw_mix']['negative']:.0%} / {card['raw_mix']['request']:.0%})",
                  f"Indices (1.0 = as expected): complaints {card['complaint_index']['index']}, "
                  f"praise {card['praise_index']['index']}, requests {card['request_index']['index']}", ""]
    for c, title in [("positive", "Why customers like it"), ("negative", "Why customers complain"),
                     ("request", "What customers ask for")]:
        fam = card["reasons"][c]["families"]
        if fam:
            lines.append(f"**{title}:** " + "; ".join(f"{k} ({v})" for k, v in fam.items()))
    if card["by_model"]:
        lines.append("**By model:** " + " | ".join(
            f"{b['group']}: {b['verdict']} (idx {b['complaint_index']}, n={b['n_comments']})" for b in card["by_model"]))
    if card["by_engine"]:
        lines.append("**By engine:** " + " | ".join(
            f"{b['group']}: {b['verdict']} (idx {b['complaint_index']}, n={b['n_comments']})" for b in card["by_engine"]))
    if card["survey"]:
        lines.append("**US survey cross-check:** " + " | ".join(
            f"{s['attribute']} {s['model']}: top-2 {s['top2_box']:.0%}, bottom-3 {s['bottom3_box']:.1%}"
            for s in card["survey"]))
    if card["options"]:
        lines.append("**Price list (DE, July 2026):** " + " | ".join(
            f"{o['model']}: {o['tier'].replace('_', ' ')} (standard {o['n_standard']}/{o['n_variants']}, "
            f"optional {o['n_optional']}/{o['n_variants']} variants"
            + (f", from EUR {o['price_min_eur']:,.0f}" if o["price_min_eur"] else "") + ")"
            for o in card["options"]))
    lines.append("")
    marks = {"positive": "+", "negative": "-", "request": "?"}
    for c, qs in card["quotes"].items():
        for qd in qs:
            text = re.sub(r"\s+", " ", qd["text"])
            lines.append(f"  {marks[c]} \"{text[:240]}\" ({qd['model']}, {qd['source']}, {qd['reason']})")
    return "\n".join(lines)


def text_card(ctx: Context, comment: str, models=None) -> dict:
    """Classify a new comment and attach verdicts for the feature(s) it mentions."""
    from .classifier import predict
    pred = predict([comment], models=models)[0]
    features = [f for f, p in pred.get("feature", []) if f in ctx.features.index]
    return {"comment": comment, "prediction": pred,
            "cards": [ctx.feature_card(f) for f in features[:2]]}


def load_context() -> Context:
    """Load processed tables (run `build` first)."""
    p = config.PROCESSED_DIR
    labels = pd.read_csv(p / "labels.csv")
    comments = pd.read_csv(p / "comments.csv", keep_default_na=False, na_values=[""])   # keep texts like "None"
    comments[["text", "text_model"]] = comments[["text", "text_model"]].fillna("")
    for col in ["feedback_types", "sentiments", "domains", "features"]:
        comments[col] = comments[col].fillna("").apply(lambda s: [x for x in s.split("|") if x])
    survey = pd.read_csv(p / "survey_us_summary.csv") if (p / "survey_us_summary.csv").exists() else None
    return Context(labels, comments, survey, load_catalog())


CATALOG_TABLES = ["variants", "price_specs", "technical", "option_items", "fitment", "packages", "page_stats",
                  "feature_option_links", "feature_fitment", "feature_fitment_summary", "feature_fitment_by_engine",
                  "feature_specs"]


def load_catalog() -> dict:
    """Parsed price-list tables written by `build` (empty dict if not built)."""
    p = config.PROCESSED_DIR
    return {t: pd.read_csv(p / f"catalog_{t}.csv") for t in CATALOG_TABLES if (p / f"catalog_{t}.csv").exists()}
