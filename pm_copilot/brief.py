"""Feature brief: a PM types a feature ("heated steering wheel") and gets one
evidence-linked answer to the questions they actually ask:

  1. How much is it needed?                      -> demand
  2. Is it more important to have it or not?     -> kano + have_vs_not
  3. Which markets want it / where does it not fit? -> regions (+ variant strategy)
  4. Which materials work?                       -> materials
  5. How many markets are affected?              -> markets_affected
  6. How many cars are at stake?                 -> sales
  7. What do customers complain about / ask for? -> issues, quotes
  8. How do competitors compare?                 -> competitors
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import pandas as pd

from . import research, scoring
from . import taxonomy as tx
from .config import DEFAULT_HORIZON, DERIVATIVES, MIN_REGION_BASE, REGION_NAMES, REGIONS
from .store import Data


@dataclass
class Resolution:
    query: str
    label: str
    key: str
    components: list[str]
    terms: list[str]
    equipment_terms: list[str] = field(default_factory=list)
    survey_prefixes: list[str] = field(default_factory=list)
    feature: tx.Feature | None = None
    note: str = ""
    alternatives: list[str] = field(default_factory=list)


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) > 2}


def resolve(query: str, data: Data) -> Resolution:
    q = query.strip()
    ql = q.lower()
    components = sorted(set(data.findings["component"]) - {"no_class_found"})

    if ql.startswith("component:"):
        name = q.split(":", 1)[1].strip()
        match = next((c for c in components if c.lower() == name.lower()), None)
        if match:
            return Resolution(q, match, "component:" + match, [match], [match.lower()],
                              survey_prefixes=tx.survey_prefixes_for(match),
                              note=f"Exact component '{match}' (customer-feedback classification).")

    def feature_score(f: tx.Feature) -> float:
        if ql in (f.key, f.label.lower()):
            return 1.0
        if any(ql == s or (len(ql) > 3 and (ql in s or s in ql)) for s in f.synonyms + (f.label.lower(),)):
            return 0.85
        qt, ft = _tokens(ql), _tokens(" ".join((f.label,) + f.synonyms))
        return len(qt & ft) / len(qt) * 0.7 if qt else 0.0

    ranked = sorted(((feature_score(f), f) for f in tx.FEATURES), key=lambda x: -x[0])
    best_score, best = ranked[0]
    alternatives = [f.label for s, f in ranked[1:4] if s >= 0.3]
    if best_score >= 0.5:
        return Resolution(q, best.label, best.key, list(best.components), list(best.synonyms),
                          list(best.equipment_terms),
                          list(best.survey) or sorted({p for c in best.components for p in tx.survey_prefixes_for(c)}),
                          best, f"Matched catalog feature '{best.label}': {len(best.components)} feedback "
                                f"component(s) + {len(best.synonyms)} text cues.", alternatives)

    # Ad-hoc: fuzzy-match the feedback components, search the text for the query itself.
    lower = {c.lower(): c for c in components}
    hits = [lower[c] for c in difflib.get_close_matches(ql, list(lower), n=3, cutoff=0.6)]
    hits += [c for c in components if _tokens(ql) and _tokens(ql) <= _tokens(c) and c not in hits]
    prefixes = sorted({p for c in hits for p in tx.survey_prefixes_for(c)})
    note = (f"No catalog feature matched; using component(s) {', '.join(hits)} and free-text search."
            if hits else "No catalog feature or component matched; free-text search only (lower confidence).")
    return Resolution(q, q, "adhoc:" + re.sub(r"[^a-z0-9]+", "_", ql).strip("_"), hits[:5], [ql], [], prefixes,
                      None, note, [f.label for s, f in ranked[:3] if s > 0])


def _select(data: Data, res: Resolution, derivative: str | None, powertrain: str | None):
    f = data.scope(derivative, powertrain)
    label = f["component"].isin(res.components)
    if res.feature and res.feature.component_text_filter:
        narrowed = label & f["text"].str.contains(res.feature.component_text_filter, case=False, regex=True)
        if f.loc[narrowed, "verbatim_id"].nunique() >= 3:
            label = narrowed
    labelled = f[label]
    rx = "|".join(re.escape(t) for t in res.terms)
    text_hit = f["text"].str.contains(rx, case=False, regex=True) if rx else pd.Series(False, index=f.index)
    text_only = f[text_hit & ~f["verbatim_id"].isin(labelled["verbatim_id"])].drop_duplicates("verbatim_id")
    return f, labelled, text_only


def _snippet(text: str, rx: str | None, width: int = 320) -> str:
    if len(text) <= width:
        return text
    m = re.search(rx, text, re.I) if rx else None
    start = max(0, (m.start() if m else 0) - width // 3)
    return ("..." if start else "") + text[start:start + width] + ("..." if start + width < len(text) else "")


def _quotes(rows: pd.DataFrame, rx: str | None, per_signal: int = 3) -> list[dict]:
    out = []
    order = {"defect": 0, "usability": 1, "request": 2, "praise": 3}
    for signal, grp in sorted(rows.groupby("signal"), key=lambda kv: order.get(kv[0], 9)):
        if signal == "none":
            continue
        grp = grp.drop_duplicates("verbatim_id").assign(_len=lambda d: d["text"].str.len())
        grp = grp.sort_values(["severity_mult", "_len"], ascending=[False, True])
        picked, kinds = [], set()
        for r in grp.itertuples():  # prefer different source types first
            if r.source_kind not in kinds or len(kinds) >= grp["source_kind"].nunique():
                picked.append(r)
                kinds.add(r.source_kind)
            if len(picked) >= per_signal:
                break
        out += [{"verbatim_id": r.verbatim_id, "finding_id": r.finding_id, "signal": signal, "issue": r.issue,
                 "country": r.country, "source": r.source_kind, "severity": r.severity, "derivative": r.derivative,
                 "text": _snippet(r.text, rx)} for r in picked]
    return out


def _materials(rows: pd.DataFrame, derivative_rows: pd.DataFrame, relevant: bool) -> dict:
    def tally(df: pd.DataFrame) -> list[dict]:
        df = df[df["materials"] != ""].drop_duplicates("verbatim_id")
        stats: dict[str, dict] = {}
        for r in df.itertuples():
            for mat in r.materials.split("|"):
                m = re.search(tx.MATERIALS[mat], r.text, re.I)
                sent = r.text[max(0, m.start() - 90): m.end() + 90] if m else r.text[:180]
                tone = "negative" if tx.MATERIAL_NEG.search(sent) else (
                    "positive" if tx.MATERIAL_POS.search(sent) else
                    {"praise": "positive", "defect": "negative", "usability": "negative"}.get(r.signal, "neutral"))
                s = stats.setdefault(mat, {"material": mat, "positive": 0, "negative": 0, "neutral": 0, "quotes": []})
                s[tone] += 1
                if len(s["quotes"]) < 2:
                    s["quotes"].append({"verbatim_id": r.verbatim_id, "tone": tone, "text": "..." + sent.strip() + "..."})
        out = list(stats.values())
        for s in out:
            n = s["positive"] + s["negative"] + s["neutral"]
            s["mentions"], s["net"] = n, s["positive"] - s["negative"]
        return sorted(out, key=lambda s: -s["mentions"])

    feature_level = tally(rows)
    vehicle_level = tally(derivative_rows) if relevant and sum(s["mentions"] for s in feature_level) < 5 else []
    return {"feature": feature_level, "vehicle": vehicle_level,
            "note": ("Few material mentions for this feature; vehicle-wide material sentiment shown as context."
                     if vehicle_level else ("" if feature_level else "No material mentions in the matched feedback."))}


def _offered_materials(data: Data, derivative: str | None) -> list[dict]:
    if not derivative:
        return []
    e = data.equipment[(data.equipment["derivative"] == derivative) & (data.equipment["kind"] == "colours_trims")]
    keep = e[e["section"].str.contains("Polster|Leder|Kunstleder|Interieurleisten|Lenkr", case=False, regex=True)
             | e["name"].str.contains("Leder|Veganza|Alcantara|Edelholz|Carbon|Alumin|Merino", case=False, regex=True)]
    return [{"name": r.name, "section": r.section, "price_eur": None if pd.isna(r.price_eur) else r.price_eur,
             "n_standard": int(r.n_standard), "n_optional": int(r.n_optional)} for r in keep.head(12).itertuples()]


def feature_brief(data: Data, query: str, derivative: str | None = None, horizon: str = DEFAULT_HORIZON,
                  powertrain: str | None = None, sensitivity: float | None = None) -> dict:
    res = resolve(query, data)
    scope, labelled, text_only = _select(data, res, derivative, powertrain)
    rx = "|".join(re.escape(t) for t in res.terms) or None
    derivs = [derivative] if derivative else list(DERIVATIVES)

    base = data.verbatim_base(derivative, powertrain)
    sig = scoring.signal_summary(labelled)
    inferred_requests = int(text_only["want_cue"].sum())
    all_rows = pd.concat([labelled, text_only])
    vehicle_n = int(scope["verbatim_id"].nunique())
    mention_n = int(all_rows["verbatim_id"].nunique())

    equipment = {d: data.equipment_match(d, res.equipment_terms) for d in derivs}
    status = equipment[derivative]["status"] if derivative else ""
    kano = scoring.kano_class(sig["praise"], sig["complaints"], sig["request"] + inferred_requests, status)
    have, have_not = scoring.HAVE_VS_NOT[kano["class"]]

    # Volumes and survey are per vehicle; with "all vehicles" they are summed / pooled.
    volumes = {r: sum(data.volumes(d, horizon)[r] for d in derivs) for r in REGIONS}
    survey = data.survey_by_region(derivative, res.survey_prefixes) if derivative else {}

    counts = scoring.region_counts(all_rows)
    prior = mention_n / vehicle_n if vehicle_n else 0.0
    regions = {}
    for r in REGIONS:
        rr = all_rows[all_rows["region"] == r]
        rs = scoring.signal_summary(labelled[labelled["region"] == r])
        rate = scoring.shrunk_rate(counts[r], base[r], prior) if base[r] >= MIN_REGION_BASE else None
        lift = rate / prior if rate is not None and prior else None
        rec = scoring.region_recommendation(r, counts[r], base[r], base[r] * prior, lift, kano["class"],
                                            rs["complaints"], survey.get(r), volumes[r])
        if res.feature and res.feature.climate:
            rec["context"] = tx.CLIMATE_HINTS[res.feature.climate]
        regions[r] = {
            "name": REGION_NAMES[r], "verbatim_base": base[r], "mentions": counts[r],
            "mention_rate_per_1000": round(counts[r] / base[r] * 1000, 1) if base[r] else None,
            "relative_index": None if lift is None else round(lift, 2),
            "praise": rs["praise"], "complaints": rs["complaints"],
            "requests": rs["request"] + int(text_only.loc[text_only["region"] == r, "want_cue"].sum()),
            "countries": rr.groupby("country")["verbatim_id"].nunique().sort_values(ascending=False).to_dict(),
            "survey": survey.get(r), "volume": volumes[r], "recommendation": rec,
        }

    affected_impl = [r for r in REGIONS if regions[r]["recommendation"]["level"] in ("high", "medium", "medium-low")]
    affected_not = [r for r in REGIONS if regions[r]["complaints"] + regions[r]["requests"] > 0
                    or (survey.get(r) and survey[r]["mean_z"] < -0.25)]
    countries = sorted(all_rows[all_rows["signal"] != "none"]["country"].unique().tolist())

    issues = (labelled[labelled["signal"].isin(tx.COMPLAINT_SIGNALS + ("request",))]
              .drop_duplicates(["verbatim_id", "issue"]).groupby(["signal", "issue"])["verbatim_id"].nunique()
              .reset_index(name="verbatims").sort_values("verbatims", ascending=False))
    by_component = (labelled.groupby(["component", "signal"])["verbatim_id"].nunique().unstack(fill_value=0)
                    .assign(total=lambda d: d.sum(axis=1)).sort_values("total", ascending=False).head(8))

    sales = scoring.sales_scenario(kano["class"], counts, base, volumes, sensitivity)
    ev = scoring.evidence(sig["verbatims"], labelled["source_kind"].nunique(), labelled["country"].nunique(),
                          (scoring.survey_factor(survey, volumes, "low")[1] if survey else None),
                          bool(derivative and research.cached_research(derivative, res.key)))

    feature_rows = data.scope(derivative, powertrain)
    return {
        "query": query, "resolution": {"label": res.label, "key": res.key, "note": res.note,
                                       "components": res.components, "text_terms": res.terms,
                                       "survey_attributes": res.survey_prefixes, "alternatives": res.alternatives},
        "scope": {"derivative": derivative, "vehicle": DERIVATIVES[derivative]["name"] if derivative else
                  "All vehicles", "horizon": horizon, "powertrain": powertrain or "all", "verbatims": vehicle_n},
        "demand": {
            "verbatims_mentioning": mention_n, "labelled": sig["verbatims"], "text_only": int(len(text_only)),
            "per_1000": round(mention_n / vehicle_n * 1000, 1) if vehicle_n else 0.0,
            "praise": sig["praise"], "complaints": sig["complaints"], "defects": sig["defect"],
            "usability": sig["usability"], "requests": sig["request"], "inferred_requests": inferred_requests,
            "headline": (f"{mention_n:,} of {vehicle_n:,} verbatims ({mention_n / vehicle_n * 1000 if vehicle_n else 0:.1f}"
                         f" per 1,000) mention {res.label.lower()}: {sig['praise']} praise, {sig['complaints']} "
                         f"complaints, {sig['request'] + inferred_requests} requests."),
        },
        "kano": kano, "have_vs_not": {"have": have, "not_have": have_not},
        "equipment": equipment, "specs": {d: data.specs_for(d) for d in derivs},
        "regions": regions,
        "markets_affected": {
            "if_implemented": {"regions": affected_impl, "volume": sum(volumes[r] for r in affected_impl)},
            "if_not_implemented": {"regions": affected_not, "volume": sum(volumes[r] for r in affected_not)},
            "countries_with_signal": countries,
        },
        "sales": sales,
        "issues": issues.head(12).to_dict("records"),
        "components": [{"component": c, **{k: int(v) for k, v in row.items()}} for c, row in by_component.iterrows()],
        "materials": {**_materials(all_rows, feature_rows, bool(res.feature and res.feature.material_relevant)),
                      "offered": _offered_materials(data, derivative)},
        "competitors": {
            "mentions": research.competitor_mentions(all_rows),
            "vehicle_mentions": research.competitor_mentions(feature_rows)[:6],
            "seed": research.seed_competitors(derivative) if derivative else {},
            "research": research.cached_research(derivative, res.key) if derivative else [],
        },
        "evidence": ev,
        "quotes": _quotes(labelled, rx) + [
            {"verbatim_id": r.verbatim_id, "finding_id": r.finding_id,
             "signal": "request (inferred)" if r.want_cue else "mention (unlabelled)", "issue": "text match",
             "country": r.country, "source": r.source_kind, "severity": r.severity, "derivative": r.derivative,
             "text": _snippet(r.text, rx)}
            for r in text_only.sort_values("want_cue", ascending=False).head(3).itertuples()],
        "label_sources": {"vfc": int(labelled.loc[labelled["label_source"] != "model", "verbatim_id"].nunique()),
                          "model": int(labelled.loc[labelled["label_source"] == "model", "verbatim_id"].nunique()),
                          "text": int(len(text_only))},
        "hierarchy": _hierarchy(labelled),
        "zones": (labelled[labelled["zone"] != ""]["zone"].value_counts().index.tolist()
                  or sorted({tx.zone_of(c) for c in res.components})),
        "previous_bmw_mentions": int(all_rows.drop_duplicates("verbatim_id")["mentions_previous_bmw"].sum()),
        "coverage_warning": _coverage_warning(base, volumes),
    }


def _hierarchy(rows: pd.DataFrame) -> list[dict]:
    """Category (L1) -> component (VFC L2) -> issue (VFC L3), counted in unique reviews."""
    rows = rows[rows["component"] != "no_class_found"]
    out = []
    for dom, d in rows.groupby("domain"):
        comps = []
        for comp, c in d.groupby("component"):
            issues = (c.groupby(["issue", "signal"])["verbatim_id"].nunique().sort_values(ascending=False))
            comps.append({"name": comp, "reviews": int(c["verbatim_id"].nunique()),
                          "issues": [{"name": i or "(unspecified)", "signal": sg, "reviews": int(n)}
                                     for (i, sg), n in issues.items()]})
        out.append({"name": dom, "reviews": int(d["verbatim_id"].nunique()),
                    "components": sorted(comps, key=lambda x: -x["reviews"])})
    return sorted(out, key=lambda x: -x["reviews"])


def _coverage_warning(base: dict[str, int], volumes: dict[str, int]) -> str:
    gaps = [REGION_NAMES[r] for r in REGIONS if volumes.get(r) and base.get(r, 0) < MIN_REGION_BASE]
    if not gaps:
        return ""
    return (f"No (or too few) customer verbatims for {', '.join(gaps)} although the car is sold there - those "
            f"markets rely on the customer study and external research.")
