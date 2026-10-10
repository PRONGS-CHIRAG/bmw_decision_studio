"""Derive, score and persist requirement candidates.

For every vehicle x component the pipeline proposes up to three requirements:
  FIX     - complaints (defects, hard to use) about something the car has
  ADD     - requests / unmet needs
  PROTECT - strong praise the successor must not lose
A PM can add FEATURE requirements from the Feature Explorer. All of them carry the
deliverable fields: id, description, linked findings + sources, score + rationale,
evidence level, assumptions/uncertainties, regional strategy and decision status.
"""
from __future__ import annotations

import csv
import json
import re

import pandas as pd

from . import db, research, scoring
from . import taxonomy as tx
from .brief import _quotes, _select, resolve
from .config import (DEFAULT_HORIZON, DERIVATIVES, EXPORT_DIR, MIN_FINDINGS, PROTECT_MIN_PRAISE_SHARE,
                     PROTECT_PRAISE_WEIGHT, REGION_NAMES, REGIONS, WEIGHTS_VERSION)
from .store import Data

TYPE_SIGNALS = {"FIX": ("defect", "usability"), "ADD": ("request",), "PROTECT": ("praise",)}


def _vehicle_context(data: Data, derivative: str, horizon: str) -> dict:
    """Per-vehicle denominators, computed once per data load."""
    cache = data.__dict__.setdefault("_vehicle_ctx", {})
    if (derivative, horizon) not in cache:
        cache[(derivative, horizon)] = {
            "vehicle_n": int(data.scope(derivative)["verbatim_id"].nunique()),
            "base": data.verbatim_base(derivative), "volumes": data.volumes(derivative, horizon)}
    return cache[(derivative, horizon)]


def _clean(component: str) -> str:
    return re.sub(r",? overall technology$", "", component).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", _clean(text).upper()).strip("-")[:40]


# Issue (VFC level 3) -> (short goal for the title, goal sentence for the description)
ISSUE_GOALS = {
    "malfunction": ("eliminate malfunctions", "work reliably, without malfunctions"),
    "damage": ("prevent damage", "be robust against damage and wear"),
    "noise": ("eliminate noise", "operate quietly"),
    "wind noise": ("reduce wind noise", "keep wind noise at a premium level"),
    "vibration, oscillation": ("eliminate vibration", "run without vibration"),
    "not user-friendly": ("make it easier to use", "be easy and intuitive to use"),
    "insufficient storage space": ("provide more usable space", "offer enough usable space for everyday items"),
    "size not user friendly": ("fix size and ergonomics", "be sized and placed for easy use"),
    "not comfortable": ("make it more comfortable", "be comfortable over long journeys"),
    "ergonomics do not appeal": ("improve ergonomics", "fit customers' ergonomic expectations"),
    "range, not ok": ("improve real-world range", "deliver real-world range customers can rely on"),
    "information / accuracy insufficient": ("make information accurate", "show accurate, sufficient information"),
    "connection fault": ("make connections reliable", "connect reliably every time"),
    "drive power/driving performance not ok": ("improve performance", "deliver the expected driving performance"),
    "effect, power not ok": ("make it more effective", "deliver a noticeable, effective result"),
    "dirty contamination": ("keep it clean", "stay clean and easy to keep clean"),
    "battery discharge": ("prevent battery drain", "not drain the battery"),
    "fuel / power consumption too high": ("reduce consumption", "keep consumption low"),
    "warning / notification active": ("stop false warnings", "warn only when it matters"),
    "view/restricted panoramic view": ("improve visibility", "give a clear, unobstructed view"),
}


def _goal(issue: str, defect_led: bool) -> tuple[str, str]:
    default = ("eliminate failures", "work reliably") if defect_led else         ("make it easier to use", "be easy and intuitive to use")
    return ISSUE_GOALS.get(issue.lower(), default)


def _quote_rx(component: str | None, feature: tx.Feature | None) -> str | None:
    words = list(feature.synonyms) if feature else []
    if component:
        words += [w for w in re.findall(r"[A-Za-z][a-z]{3,}", _clean(component)) if w.lower() not in ("vehicle",)]
    return "|".join(re.escape(w) for w in words) or None


def feature_for_component(component: str) -> tx.Feature | None:
    return next((f for f in tx.FEATURES if component in f.components), None)


def _top_issues(sub: pd.DataFrame, n: int = 4) -> list[dict]:
    s = sub.drop_duplicates(["verbatim_id", "issue"]).groupby("issue")["verbatim_id"].nunique()
    return [{"issue": k, "verbatims": int(v)} for k, v in s.sort_values(ascending=False).head(n).items()]


def _short_request(sub: pd.DataFrame) -> str:
    req = sub[sub["signal"] == "request"].drop_duplicates("verbatim_id")
    if req.empty:
        return ""
    t = req.assign(_l=req["text"].str.len()).query("_l > 25").sort_values("_l")
    return t["text"].iloc[0][:180] if not t.empty else ""


def make_requirement(data: Data, derivative: str, rtype: str, label: str, domain: str, sub: pd.DataFrame,
                     all_rows: pd.DataFrame, survey_prefixes, equipment_terms, horizon: str, key: str,
                     component: str | None = None, req_id: str | None = None, quote_rx: str | None = None) -> dict:
    vehicle = DERIVATIVES[derivative]["name"]
    direction = "high" if rtype == "PROTECT" else "low"
    ctx = _vehicle_context(data, derivative, horizon)
    vehicle_n, base, volumes = ctx["vehicle_n"], ctx["base"], ctx["volumes"]
    survey = data.survey_by_region(derivative, survey_prefixes)
    equipment = data.equipment_match(derivative, equipment_terms)

    sig = scoring.signal_summary(sub)
    allsig = scoring.signal_summary(all_rows)
    kano = scoring.kano_class(allsig["praise"], allsig["complaints"], allsig["request"], equipment["status"])
    counts = scoring.region_counts(sub)

    weighted = sig["praise"] * PROTECT_PRAISE_WEIGHT if rtype == "PROTECT" else (
        sig["weighted"] + (0.3 * sig["praise"] if rtype == "FEATURE" else 0))
    f_signal, n_signal = scoring.customer_signal_factor(weighted, vehicle_n)
    f_reach, reach_detail, n_reach = scoring.market_reach_factor(counts, base, volumes, survey, direction)
    f_survey, agrees, n_survey = scoring.survey_factor(survey, volumes, direction)
    comp_mentions = int(sub.loc[sub["competitors"] != "", "verbatim_id"].nunique())
    gap = research.research_gap(derivative, key)
    f_comp, n_comp = scoring.competitive_factor(comp_mentions, sig["verbatims"], gap)
    carry = data.offered_on_other_derivatives(derivative, equipment_terms) \
        if rtype in ("ADD", "FEATURE") and equipment["status"] in ("not in price list", "no equipment terms") else []
    prev = int(sub.loc[sub["mentions_previous_bmw"], "verbatim_id"].nunique())
    f_feas, n_feas = scoring.feasibility_factor(domain, carry, prev, sig["verbatims"])

    factors = {"customer_signal": round(f_signal, 3), "market_reach": round(f_reach, 3),
               "survey_gap": round(f_survey, 3), "competitive": round(f_comp, 3), "feasibility": round(f_feas, 3)}
    notes = {"customer_signal": n_signal, "market_reach": n_reach, "survey_gap": n_survey, "competitive": n_comp,
             "feasibility": n_feas}
    ev = scoring.evidence(sig["verbatims"], sub["source_kind"].nunique(), sub["country"].nunique(), agrees,
                          gap is not None)
    prio = scoring.priority(rtype, factors, ev["score"])

    prior = sum(counts.values()) / sum(base.values()) if sum(base.values()) else 0.0
    regions = {}
    for r in REGIONS:
        rate = scoring.shrunk_rate(counts[r], base[r], prior) if base[r] else None
        lift = rate / prior if rate is not None and prior else None
        rsub = sub[sub["region"] == r]
        regions[r] = {
            "name": REGION_NAMES[r], "verbatims": counts[r], "base": base[r], "volume": volumes[r],
            "presence": reach_detail[r]["presence"], "basis": reach_detail[r]["basis"],
            "survey_z": survey[r]["mean_z"] if r in survey else None,
            "recommendation": scoring.region_recommendation(
                r, counts[r], base[r], base[r] * prior, lift, kano["class"],
                int(rsub[rsub["signal"].isin(tx.COMPLAINT_SIGNALS)]["verbatim_id"].nunique()),
                survey.get(r), volumes[r], direction),
        }

    issues = _top_issues(sub)
    top = issues[0]["issue"] if issues else ""
    rate = sig["verbatims"] / vehicle_n * 1000 if vehicle_n else 0.0
    focus = [REGION_NAMES[r] for r in REGIONS if regions[r]["recommendation"]["level"] in ("high", "medium")]
    where = ", ".join(focus) or "the markets with evidence"
    name = _clean(label)
    attr = next((a["attribute"] for s in survey.values() for a in s["attributes"]), None)
    defect_led = sig["defect"] >= sig["usability"]

    if rtype == "FIX":
        short_goal, goal = _goal(top, defect_led)
        title = f"{name}: {short_goal} ({top.lower()})"
        description = (f"{name} must {goal} on the "
                       f"successor of the {vehicle}. {sig['verbatims']} customers report problems ({rate:.1f} per "
                       f"1,000 verbatims), led by '{top}'. Remove the root causes so that complaints fall by at least "
                       f"half, starting with {where}.")
        criteria = [f"Complaint rate for {name} <= {rate / 2:.1f} per 1,000 verbatims (today {rate:.1f}).",
                    *( [f"Customer-study attribute '{attr}' at or above this car's average in every surveyed market."]
                       if attr else []),
                    *( ["No 'serious' / 'very serious' quality-survey reports on this topic in the launch year."]
                       if (sub["severity"].str.contains("serious")).any() else [])]
    elif rtype in ("ADD", "FEATURE"):
        ask = top.replace("Customer request: ", "") if top else "this capability"
        quote = _short_request(sub)
        title = (f"{name}: deliver what customers ask for ({ask.lower()})" if rtype == "ADD"
                 else f"{name}: offer / improve in {where}")
        description = (f"Offer {name} in the form customers ask for on the successor of the {vehicle}. "
                       f"{sig['verbatims']} customers mention it ({sig['request']} explicit requests, "
                       f"{sig['complaints']} complaints, {sig['praise']} praise)"
                       + (f", e.g. \"{quote}\"" if quote else "") + f". Prioritise {where}; "
                       f"today's status (DE list): {equipment['status']}.")
        criteria = [f"Available in {where} at launch, as standard where the market recommendation says so.",
                    "Request rate for this topic halves versus today in post-launch feedback.",
                    "Customer clinic: at least 70 % of target customers say the solution meets their need."]
    else:  # PROTECT
        share = sig["praise"] / max(1, allsig["praise"] + allsig["complaints"])
        title = f"{name}: keep as a signature strength"
        description = (f"{name} is a strength of the {vehicle}: {sig['praise']} customers praise it "
                       f"({share:.0%} of opinions on it are positive), led by '{top}'. The successor must match or "
                       f"exceed today's execution; changes need a clinic check against the current car.")
        criteria = [f"Positive share of opinions on {name} stays >= {share:.0%}.",
                    *( [f"Customer-study attribute '{attr}' stays above this car's average."] if attr else [])]

    assumptions = []
    region_share = sub["region"].value_counts(normalize=True)
    if not region_share.empty and region_share.iloc[0] > 0.8:
        assumptions.append(f"{region_share.iloc[0]:.0%} of the evidence comes from {REGION_NAMES[region_share.index[0]]};"
                           f" other markets are inferred.")
    if volumes.get("CN") and base.get("CN", 0) == 0:
        assumptions.append("No China verbatims in the data: China relevance rests on the China customer study only.")
    assumptions.append(f"{horizon} planning volumes hold; sample of verbatims is representative of buyers.")
    assumptions.append("Customer-feedback classification (VFC) is correct; spot-check linked verbatims.")
    if rtype == "FIX":
        assumptions.append("Root causes are fixable within the successor programme (not yet confirmed by engineering).")
    if rtype in ("ADD", "FEATURE"):
        assumptions.append("Requests do not reveal willingness to pay; take rate unknown.")
    if agrees is False:
        assumptions.append("Uncertainty: the customer study contradicts the verbatims for this topic.")
    if gap is None:
        assumptions.append("Competitor benchmark not yet researched for this topic.")

    findings = sub.drop_duplicates("finding_id")
    files = sorted(findings["source_file"].unique())
    sources = [{"type": "BMW customer verbatims", "file": ", ".join(files), "count": int(len(findings)),
                "by_source": findings.groupby("source_kind")["verbatim_id"].nunique().to_dict()},
               {"type": "Sales plan", "file": "sales_volumes.xlsx", "sheet": DERIVATIVES[derivative]["sales_sheet"]}]
    if survey:
        sources.append({"type": "Customer study", "file": "F70_G60_G68_G70_customer_studies.xlsx",
                        "attributes": sorted({a["attribute"] for s in survey.values() for a in s["attributes"]})})
    if equipment["items"]:
        sources.append({"type": "Price list (DE)", "file": equipment["items"][0]["source"],
                        "items": [i["name"] for i in equipment["items"][:4]]})
    for rec in research.cached_research(derivative, key):
        sources.append({"type": "Web research", "file": f"research/{derivative}_{rec['region']}",
                        "urls": [u for c in rec["result"]["competitors"] for u in c["source_urls"]][:10]})

    return {
        "id": req_id or f"{derivative}-{rtype}-{_slug(label)}",
        "type": rtype, "derivative": derivative, "vehicle": vehicle, "component": component, "feature_key": key,
        "domain": domain, "zone": tx.zone_of(component or (sub["component"].mode().iloc[0] if not sub.empty else ""),
                                             domain if component else None), "title": title, "description": description, "acceptance_criteria": criteria,
        "kano": kano, "priority": prio, "priority_rationale": scoring.explain_priority(prio, factors, notes),
        "factors": factors, "factor_notes": notes, "evidence": ev,
        "evidence_summary": {"verbatims": sig["verbatims"], "findings": int(len(findings)),
                             "praise": sig["praise"], "complaints": sig["complaints"], "requests": sig["request"],
                             "per_1000": round(rate, 1)},
        "top_issues": issues, "regions": regions, "equipment_status": equipment["status"],
        "survey": survey, "sales": scoring.sales_scenario(kano["class"], counts, base, volumes),
        "linked_findings": findings["finding_id"].tolist()[:400], "quotes": _quotes(sub, quote_rx, per_signal=3),
        "sources": sources, "assumptions": assumptions, "horizon": horizon, "weights_version": WEIGHTS_VERSION,
    }


def build_candidates(data: Data, horizon: str = DEFAULT_HORIZON) -> list[dict]:
    out = []
    for derivative in DERIVATIVES:
        f = data.scope(derivative)
        usable = f[(f["scope_note"] == "") & (f["signal"] != "none")]
        for component, cf in usable.groupby("component"):
            feature = feature_for_component(component)
            allsig = scoring.signal_summary(cf)
            for rtype, signals in TYPE_SIGNALS.items():
                sub = cf[cf["signal"].isin(signals)]
                n = sub["verbatim_id"].nunique()
                if n < MIN_FINDINGS[rtype]:
                    continue
                if rtype == "PROTECT" and allsig["praise"] / max(1, allsig["praise"] + allsig["complaints"]) \
                        < PROTECT_MIN_PRAISE_SHARE:
                    continue
                out.append(make_requirement(
                    data, derivative, rtype, component, tx.domain_of(component), sub, cf,
                    tx.survey_prefixes_for(component), feature.equipment_terms if feature else (), horizon,
                    feature.key if feature else f"component:{component}", component,
                    quote_rx=_quote_rx(component, feature)))
    return out


def sync(data: Data, horizon: str = DEFAULT_HORIZON) -> dict:
    candidates = build_candidates(data, horizon)
    result = {"created": 0, "updated": 0, "unchanged": 0}
    with db.connect() as con:
        db.log(con, "pipeline", "system", "pipeline_run", rationale=json.dumps(
            {"weights_version": WEIGHTS_VERSION, "horizon": horizon, "manifest": data.manifest}, default=str))
        for req in candidates:
            result[db.upsert_computed(con, req)] += 1
        result["obsoleted"] = db.mark_obsolete(con, {r["id"] for r in candidates},
                                               {(d, t) for d in DERIVATIVES for t in TYPE_SIGNALS})
    result["candidates"] = len(candidates)
    return result


def score_feature(data: Data, query: str, derivative: str, horizon: str = DEFAULT_HORIZON,
                  powertrain: str | None = None) -> dict | None:
    """The FEATURE requirement the pipeline would propose for this question (not stored)."""
    res = resolve(query, data)
    _, labelled, text_only = _select(data, res, derivative, powertrain)
    sub = pd.concat([labelled, text_only.assign(signal=text_only["want_cue"].map({True: "request", False: "none"}))])
    sub = sub[sub["signal"] != "none"]
    if sub.empty:
        return None
    domain = tx.domain_of(res.components[0]) if res.components else "Ownership & Other"
    return make_requirement(data, derivative, "FEATURE", res.label, domain, sub, sub, res.survey_prefixes,
                            res.equipment_terms, horizon, res.key, None, f"{derivative}-FEAT-{_slug(res.label)}",
                            quote_rx="|".join(re.escape(t) for t in res.terms))


def create_from_feature(data: Data, query: str, derivative: str, actor: str, rationale: str,
                        horizon: str = DEFAULT_HORIZON) -> dict:
    res = resolve(query, data)
    _, labelled, text_only = _select(data, res, derivative, None)
    sub = pd.concat([labelled, text_only.assign(signal=text_only["want_cue"].map({True: "request", False: "none"}))])
    sub = sub[sub["signal"] != "none"]
    if sub.empty:
        raise ValueError(f"No customer evidence for '{res.label}' on {derivative}; research it before creating "
                         f"a requirement.")
    domain = tx.domain_of(res.components[0]) if res.components else "Ownership & Other"
    req = make_requirement(data, derivative, "FEATURE", res.label, domain, sub, sub, res.survey_prefixes,
                           res.equipment_terms, horizon, res.key, None, f"{derivative}-FEAT-{_slug(res.label)}",
                           quote_rx="|".join(re.escape(t) for t in res.terms))
    with db.connect() as con:
        existed = db.get(con, req["id"]) is not None
        db.upsert_computed(con, req, actor=actor, actor_type="pm")
        if not existed:
            db.log(con, actor, "pm", "created_from_feature_brief", req["id"], rationale=rationale or
                   f"Created from Feature Explorer query '{query}'.")
        return db.effective(db.get(con, req["id"]))


def list_requirements(derivative: str | None = None, status: str | None = None,
                      rtype: str | None = None, region: str | None = None) -> list[dict]:
    with db.connect() as con:
        reqs = [db.effective(r) for r in db.all_rows(con)]
    if derivative:
        reqs = [r for r in reqs if r["derivative"] == derivative]
    if status:
        reqs = [r for r in reqs if r["status"] == status]
    elif status is None:
        reqs = [r for r in reqs if r["status"] != "Obsolete"]
    if rtype:
        reqs = [r for r in reqs if r["type"] == rtype]
    if region:
        reqs = [r for r in reqs if r["regions"][region]["recommendation"]["level"] in ("high", "medium")
                or r["regions"][region]["verbatims"] > 0]
    return sorted(reqs, key=lambda r: -r["priority"]["score"])


EXPORT_FIELDS = ["id", "status", "type", "derivative", "title", "description", "acceptance_criteria", "kano",
                 "priority_score", "priority_tier", "priority_rationale", "evidence_level", "evidence_reasons",
                 "linked_findings", "sources", "assumptions", "market_strategy", "updated_at"]


def export(derivative: str | None = None, fmt: str = "json") -> tuple[str, str]:
    rows = []
    for r in list_requirements(derivative):
        rows.append({
            "id": r["id"], "status": r["status"], "type": r["type"], "derivative": r["derivative"],
            "title": r["title"], "description": r["description"],
            "acceptance_criteria": r["acceptance_criteria"], "kano": r["kano"]["class"],
            "priority_score": r["priority"]["score"], "priority_tier": r["priority"]["tier"],
            "priority_rationale": r["priority_rationale"], "evidence_level": r["evidence"]["level"],
            "evidence_reasons": r["evidence"]["reasons"], "linked_findings": r["linked_findings"],
            "sources": r["sources"], "assumptions": r["assumptions"],
            "market_strategy": {k: v["recommendation"]["label"] for k, v in r["regions"].items()},
            "updated_at": r["updated_at"],
        })
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"requirements_{derivative or 'all'}.{fmt}"
    path = EXPORT_DIR / name
    if fmt == "csv":
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
            w.writeheader()
            for row in rows:
                w.writerow({k: "; ".join(map(str, v)) if isinstance(v, list) else
                            (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v) for k, v in row.items()})
    else:
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return str(path), name

