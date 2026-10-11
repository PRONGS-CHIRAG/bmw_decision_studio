"""The prioritization logic. Every function returns its number *and* the reason,
so the UI, the export and the audit trail can show why a requirement ranks
where it does. All weights and thresholds live in config.py.

Factors (each 0..1), weighted per requirement type:
  customer_signal - severity-weighted verbatims per 1,000 verbatims of the vehicle (log-scaled)
  market_reach    - share of planned volume sold in markets where the topic shows up
  survey_gap      - is the linked customer-study attribute below (FIX/ADD) or above (PROTECT)
                    this car's average in that market? (volume-weighted z-score)
  competitive     - customers comparing with competitors + researched competitor gaps
  feasibility     - rough effort proxy (software vs. packaging) + carry-over from BMW portfolio
Score  = 100 * sum(w * factor) * (EVIDENCE_FLOOR + (1 - EVIDENCE_FLOOR) * evidence)
"""
from __future__ import annotations

import math

import pandas as pd

from . import taxonomy as tx
from .config import (DECISION_SENSITIVITY, EVIDENCE_FLOOR, EVIDENCE_LEVELS, MIN_REGION_BASE, PRIOR_STRENGTH,
                     PRIORITY_WEIGHTS, REGION_NAMES, REGIONS, SIGNAL_SATURATION_PER_1000, SIGNAL_WEIGHT, TIERS)

FACTOR_LABELS = {
    "customer_signal": "Customer signal", "market_reach": "Market reach", "survey_gap": "Survey corroboration",
    "competitive": "Competitive pressure", "feasibility": "Feasibility / effort",
}


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def shrunk_rate(count: float, base: float, prior_rate: float) -> float:
    """Empirical-Bayes rate: small samples are pulled toward the vehicle-wide rate."""
    return (count + PRIOR_STRENGTH * prior_rate) / (base + PRIOR_STRENGTH) if base + PRIOR_STRENGTH else 0.0


# --------------------------------------------------------------------------
# Counting
# --------------------------------------------------------------------------
def signal_summary(f: pd.DataFrame) -> dict:
    """Unique-verbatim counts per signal plus the severity-weighted intensity."""
    if f.empty:
        return {"verbatims": 0, "praise": 0, "defect": 0, "usability": 0, "request": 0, "complaints": 0,
                "weighted": 0.0}
    per = f.groupby(["verbatim_id", "signal"])["severity_mult"].max().reset_index()
    counts = per["signal"].value_counts().to_dict()
    weighted = float((per["signal"].map(SIGNAL_WEIGHT).fillna(0) * per["severity_mult"]).sum())
    complaints = per[per["signal"].isin(tx.COMPLAINT_SIGNALS)]["verbatim_id"].nunique()
    return {"verbatims": int(f["verbatim_id"].nunique()), "praise": int(counts.get("praise", 0)),
            "defect": int(counts.get("defect", 0)), "usability": int(counts.get("usability", 0)),
            "request": int(counts.get("request", 0)), "complaints": int(complaints), "weighted": round(weighted, 2)}


def region_counts(f: pd.DataFrame) -> dict[str, int]:
    c = f.groupby("region")["verbatim_id"].nunique().to_dict()
    return {r: int(c.get(r, 0)) for r in REGIONS}


# --------------------------------------------------------------------------
# Kano-style class (approximation from the mix of statements)
# --------------------------------------------------------------------------
def kano_class(praise: int, complaints: int, requests: int, offered_status: str = "") -> dict:
    """Kano-style class from the statement mix. Rules are checked top to bottom; the first that fires wins."""
    total = praise + complaints + requests
    opinions = praise + complaints
    cs = complaints / opinions if opinions else 0.0
    rs = requests / total if total else 0.0
    m = {"praise": praise, "complaints": complaints, "requests": requests, "complaint_share": round(cs, 3),
         "request_share": round(rs, 3)}
    rules = [
        ("Insufficient signal", total < 5, f"{total} classified statements < 5",
         f"Only {total} classified statements - too few to tell how customers value it."),
        ("Unmet need", rs >= 0.4 and offered_status != "standard on all variants",
         f"request share {rs:.0%} >= 40%", f"{rs:.0%} of statements are requests - customers ask for it (or for more of it)."),
        ("Must-be", cs >= 0.6, f"complaint share {cs:.0%} >= 60%",
         f"{cs:.0%} of opinions are complaints: customers mostly notice it when it fails or is hard to use. "
         f"A good version avoids dissatisfaction but rarely delights."),
        ("Attractive", cs <= 0.3 and praise >= 5, f"complaint share {cs:.0%} <= 30% and praise {praise} >= 5",
         f"{1 - cs:.0%} of opinions are praise: a delighter / differentiator. Having it pays off; lacking it is rarely punished."),
        ("Performance", True, "no earlier rule fired",
         f"Praise and complaints both scale with execution ({1 - cs:.0%} positive): the better it is, the more satisfied customers are."),
    ]
    path = []
    for name, fired, test, why in rules:
        path.append({"rule": name, "test": test, "fired": bool(fired)})
        if fired:
            return {"class": name, "why": why, "metrics": m, "path": path}
    return {"class": "Performance", "why": "", "metrics": m, "path": path}


HAVE_VS_NOT = {
    "Must-be": ("Having it (done well): avoids dissatisfaction; little extra delight.",
                "Not having it / poor execution: direct dissatisfaction and complaints - high risk."),
    "Unmet need": ("Having it: closes a gap customers explicitly name - conquest and loyalty upside.",
                   "Not having it: the gap stays visible; requests continue, competitors with it gain."),
    "Performance": ("Having a better version: satisfaction rises with execution quality.",
                    "Not improving it: satisfaction stays where it is; competitors can outperform."),
    "Attractive": ("Having it: a differentiator that earns praise.",
                   "Not having it: low dissatisfaction risk, but a lost reason to choose BMW."),
    "Indifferent": ("Having it: little measurable effect.", "Not having it: little measurable effect."),
    "Insufficient signal": ("Not enough evidence to judge.", "Not enough evidence to judge - research before deciding."),
}


# --------------------------------------------------------------------------
# Factors
# --------------------------------------------------------------------------
def customer_signal_factor(weighted: float, vehicle_verbatims: int) -> tuple[float, str]:
    per_1000 = weighted / vehicle_verbatims * 1000 if vehicle_verbatims else 0.0
    value = clamp(math.log1p(per_1000) / math.log1p(SIGNAL_SATURATION_PER_1000))
    return value, f"{per_1000:.1f} severity-weighted mentions per 1,000 verbatims (saturates at " \
                  f"{SIGNAL_SATURATION_PER_1000:.0f})"


def survey_factor(survey: dict[str, dict], volumes: dict[str, int], direction: str) -> tuple[float, bool | None, str]:
    """direction 'low' = a below-average score supports the requirement (FIX/ADD);
    'high' = an above-average score supports it (PROTECT)."""
    if not survey:
        return 0.5, None, "No linked customer-study attribute - neutral 0.5."
    sign = -1 if direction == "low" else 1
    weights = {r: max(volumes.get(r, 0), 1) for r in survey}
    total = sum(weights.values())
    z = sum(survey[r]["mean_z"] * weights[r] for r in survey) / total
    value = clamp(0.5 + 0.25 * sign * z)
    agrees = True if sign * z > 0.25 else (False if sign * z < -0.25 else None)
    parts = ", ".join(f"{r} z={survey[r]['mean_z']:+.2f}" for r in survey)
    verdict = {True: "corroborates", False: "contradicts", None: "is neutral on"}[agrees]
    return value, agrees, f"Linked study attributes vs. this car's average ({parts}); volume-weighted z={z:+.2f} " \
                          f"{verdict} the verbatims."


def market_reach_factor(counts: dict[str, int], base: dict[str, int], volumes: dict[str, int],
                        survey: dict[str, dict], direction: str) -> tuple[float, dict[str, dict], str]:
    """Share of planned volume in markets where the topic is present. Covered markets use the
    shrunk mention rate relative to the vehicle-wide rate; uncovered markets fall back on the
    customer study (inferred) or a 0.25 assumption."""
    n_all, b_all = sum(counts.values()), sum(base.values())
    prior = n_all / b_all if b_all else 0.0
    detail, num, den = {}, 0.0, 0.0
    sign = -1 if direction == "low" else 1
    for r in REGIONS:
        v = volumes.get(r, 0)
        if base.get(r, 0) >= MIN_REGION_BASE:
            present = clamp(shrunk_rate(counts.get(r, 0), base[r], prior) / prior) if prior else 0.0
            how = f"{counts.get(r, 0)} of {base[r]} verbatims"
        elif r in survey:
            present = 0.6 if sign * survey[r]["mean_z"] > 0.25 else 0.3
            how = f"no verbatims - inferred from {REGION_NAMES[r]} customer study (z={survey[r]['mean_z']:+.2f})"
        else:
            present = 0.25
            how = "no BMW evidence - assumed partial relevance (0.25)"
        detail[r] = {"presence": round(present, 2), "volume": v, "basis": how,
                     "inferred": base.get(r, 0) < MIN_REGION_BASE}
        num += v * present
        den += v
    value = num / den if den else 0.0
    return value, detail, f"{value:.0%} of planned volume sits in markets where the topic is present"


def competitive_factor(competitor_mentions: int, verbatims: int, research_gap: bool | None) -> tuple[float, str]:
    """Share of the topic's verbatims that compare with a rival (8 % saturates) + researched gap."""
    share = competitor_mentions / verbatims if verbatims else 0.0
    value = (0.6 * clamp(share / 0.08) if competitor_mentions >= 2 else 0.0) + (0.4 if research_gap else 0.0)
    note = f"{competitor_mentions} of {verbatims} verbatims compare with a competitor ({share:.0%})"
    if research_gap is None:
        note += "; competitor benchmark not yet researched"
    elif research_gap:
        note += "; web research found competitors ahead on this topic"
    else:
        note += "; web research found no competitor advantage"
    return clamp(value), note


def feasibility_factor(domain: str, carry_over: list[str], previous_bmw: int, verbatims: int) -> tuple[float, str]:
    value = tx.DOMAIN_FEASIBILITY.get(domain, 0.5)
    note = f"Domain '{domain}' effort proxy {value:.2f}"
    if carry_over:
        value = max(value, 0.85)
        note += f"; carry-over possible - already in the {', '.join(carry_over)} price list"
    if previous_bmw >= 2 and previous_bmw >= 0.1 * verbatims:
        value = max(value, 0.80)
        note += f"; {previous_bmw} customers point to a previous BMW that had it / did it better"
    return value, note


def evidence(n_verbatims: int, source_kinds: int, countries: int, survey_agrees: bool | None,
             external: bool) -> dict:
    parts = {
        "volume": 0.4 * clamp(n_verbatims / 30),
        "source_diversity": 0.2 * clamp((source_kinds - 1) / 2),
        "market_diversity": 0.1 if countries >= 2 else 0.0,
        "survey": 0.2 if survey_agrees else 0.0,
        "external": 0.1 if external else 0.0,
    }
    score = round(sum(parts.values()), 2)
    level = next(name for name, cut in EVIDENCE_LEVELS if score >= cut)
    reasons = [f"{n_verbatims} verbatims", f"{source_kinds} source type(s)", f"{countries} countr(y/ies)",
               {True: "survey corroborates", False: "survey contradicts", None: "no survey corroboration"}[survey_agrees],
               "external research attached" if external else "no external research"]
    return {"score": score, "level": level, "parts": {k: round(v, 2) for k, v in parts.items()}, "reasons": reasons}


def priority(req_type: str, factors: dict[str, float], evidence_score: float) -> dict:
    w = PRIORITY_WEIGHTS[req_type]
    contributions = {k: round(100 * w[k] * factors.get(k, 0.0), 1) for k in w}
    raw = sum(contributions.values())
    final = round(raw * (EVIDENCE_FLOOR + (1 - EVIDENCE_FLOOR) * evidence_score), 1)
    tier = next(name for name, cut in TIERS if final >= cut)
    return {"score": final, "raw": round(raw, 1), "tier": tier, "weights": w, "contributions": contributions,
            "evidence_multiplier": round(EVIDENCE_FLOOR + (1 - EVIDENCE_FLOOR) * evidence_score, 3)}


def explain_priority(p: dict, factors: dict, notes: dict) -> str:
    drivers = sorted(p["contributions"].items(), key=lambda kv: -kv[1])
    formula = " + ".join(f"{p['weights'][k]:.2f}x{factors[k]:.2f}" for k, _ in drivers if p["weights"][k])
    top = [f"{FACTOR_LABELS[k]} ({notes.get(k, '')})" for k, v in drivers[:2] if v > 0]
    return (f"{p['tier']} - score {p['score']} = 100 x ({formula}) x evidence adjustment {p['evidence_multiplier']}. "
            f"Main drivers: {'; '.join(top)}.")


# --------------------------------------------------------------------------
# Market view (brief + requirements)
# --------------------------------------------------------------------------
def _survey_only(survey: dict | None, direction: str, lead: str, path: list) -> dict:
    if survey:
        z = survey["mean_z"]
        weak = (z < -0.25) if direction == "low" else (z > 0.25)
        path.append({"test": f"linked survey z = {z:+.2f} {'< -0.25' if direction == 'low' else '> +0.25'}?", "result": weak})
        if weak:
            return {"label": "Likely relevant - validate", "level": "medium", "path": path,
                    "why": f"{lead}; linked study attributes {'below' if z < 0 else 'above'} this car's average "
                           f"here (z={z:+.2f})."}
        return {"label": "No clear signal - research", "level": "unknown", "path": path,
                "why": f"{lead}; study attributes near this car's average (z={z:+.2f})."}
    path.append({"test": "linked survey data for this market?", "result": False})
    return {"label": "No BMW evidence - research", "level": "unknown", "why": f"{lead}; no linked study data.",
            "path": path}


def region_recommendation(region: str, count: int, base: int, expected: float, lift: float | None, kano: str,
                          complaints: int, survey: dict | None, volume: int, direction: str = "low") -> dict:
    """Decision path per market. expected = mentions this market would show at the vehicle-wide rate;
    absence of mentions only counts as low relevance when the sample could have shown them (expected >= 3)."""
    path = [{"test": f"planned volume {volume:,} > 0?", "result": volume > 0}]
    if volume == 0:
        return {"label": "Not sold here", "level": "none", "why": "No planned volume in this market.", "path": path}
    path.append({"test": f"{base:,} reviews >= {MIN_REGION_BASE} (market covered)?", "result": base >= MIN_REGION_BASE})
    if base < MIN_REGION_BASE:
        return _survey_only(survey, direction, "No verbatims from this market", path)
    enough = not (count < 3 and expected < 3)
    path.append({"test": f"{count} mentions >= 3 or ~{expected:.1f} expected >= 3 (sample can judge)?", "result": enough})
    if not enough:
        return _survey_only(survey, direction, f"{count} of {base} verbatims - too few to judge "
                                               f"(~{expected:.1f} expected at the overall rate)", path)
    must = kano == "Must-be" and complaints >= 2
    path.append({"test": f"Must-be and {complaints} complaints >= 2?", "result": must})
    if must:
        return {"label": "Standard - fix execution", "level": "high", "path": path,
                "why": f"Basic expectation with {complaints} complaints here."}
    lift = lift or 0.0
    for cut, label, level, why in ((1.2, "Standard - high relevance", "high", f"Mentioned {lift:.1f}x as often as across all markets ({count} of {base})."),
                                   (0.8, "Standard or package", "medium", f"Average relevance (index {lift:.2f})."),
                                   (0.5, "Optional / package", "medium-low", f"Below-average relevance (index {lift:.2f}).")):
        path.append({"test": f"relevance index {lift:.2f} >= {cut}?", "result": lift >= cut})
        if lift >= cut:
            return {"label": label, "level": level, "why": why, "path": path}
    return {"label": "Low relevance - optional at most", "level": "low", "path": path,
            "why": f"Only {count} of {base} verbatims vs ~{expected:.0f} expected (index {lift:.2f})."}


def sales_scenario(kano: str, counts: dict[str, int], base: dict[str, int], volumes: dict[str, int],
                   sensitivity: float | None = None) -> dict:
    """Customers who care + units at stake. Exposure is fact (sales plan); the rest is an explicit,
    overridable assumption chain: units x share-who-talk-about-it x decision sensitivity."""
    s = DECISION_SENSITIVITY.get(kano, 0.0) if sensitivity is None else sensitivity
    n_all, b_all = sum(counts.values()), sum(base.values())
    prior = n_all / b_all if b_all else 0.0
    rows, totals = {}, {"exposure": 0, "engaged": 0.0, "at_stake": 0.0}
    for r in REGIONS:
        v = volumes.get(r, 0)
        covered = base.get(r, 0) >= MIN_REGION_BASE
        share = shrunk_rate(counts.get(r, 0), base.get(r, 0), prior) if covered else prior
        engaged = v * share
        rows[r] = {"volume": v, "share_who_care": round(share, 4), "customers_who_care": round(engaged),
                   "units_at_stake": round(engaged * s), "share_basis": "this market" if covered else
                   "vehicle-wide rate (market not covered by verbatims)"}
        totals["exposure"] += v
        totals["engaged"] += engaged
        totals["at_stake"] += engaged * s
    return {"sensitivity": s, "by_region": rows, "exposure": totals["exposure"],
            "customers_who_care": round(totals["engaged"]), "units_at_stake": round(totals["at_stake"]),
            "assumptions": [
                "Exposure = planned volume of the selected horizon (sales plan, fact).",
                "Share who care = share of verbatims mentioning the topic; assumes the sample is representative.",
                f"Decision sensitivity {s:.0%} = share of those customers whose purchase depends on it "
                f"(default for '{kano}', adjustable).",
                "If implemented, units at stake are protected / won; if not, they are at risk.",
            ]}
