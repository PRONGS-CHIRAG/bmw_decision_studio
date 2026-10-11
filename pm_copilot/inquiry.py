"""Inquiry agent: understand a PM's question, ask for what is missing, then run the
analysis as a sequence of visible stages - each with its numbers, formulas, the rule
that fired and an activity-feed event. No LLM: dictionaries + the trained review model.

Stages: question -> filter -> read (AI model) -> compute -> decide -> recommend
"""
from __future__ import annotations

import re

from . import model as rim
from . import taxonomy as tx
from .brief import feature_brief
from .config import DEFAULT_HORIZON, DERIVATIVES, MIN_REGION_BASE, PRIOR_STRENGTH, REGION_NAMES, REGIONS
from .requirements import score_feature
from .store import Data

# --------------------------------------------------------------------------- dictionaries
VEHICLES = {
    "F70": r"\b(?:1\s?series|1er|one series|f70|m135i?|118i?|120i?|120d|1 serie)\b",
    "G60": r"\b(?:5\s?series|5er|five series|g60|g68|i5|520[id]?|530e|540d|550e|5 serie)\b",
    "G70": r"\b(?:7\s?series|7er|seven series|g70|i7|740[id]?|750e|760e?|7 serie)\b",
}
MARKETS = {
    "CN": r"\b(?:china|chinese|prc)\b",
    "EU": r"\b(?:europe|european|eu|germany|german|uk|britain|british|france|french|sweden|swedish|nordics?|scandinavia\w*|spain|italy)\b",
    "US": r"\b(?:usa|america|american|united states|north america)\b|\bUS\b",
    "RoW": r"\b(?:japan|japanese|korea|korean|canada|canadian|australia|australian|rest of (?:the )?world|row)\b",
}
POWERTRAINS = {"BEV": r"\b(?:electric|ev|bev|battery[- ]electric)\b", "PHEV": r"\b(?:plug-?in|phev|hybrid)\b",
               "ICE": r"\b(?:petrol|diesel|gasoline|combustion|ice)\b"}
INTENTS = [  # first match wins; 'full' when nothing matches
    ("rivals", r"competitor|rival|tesla|mercedes|audi|lexus|\bnio\b|\bbyd\b|xpeng|benchmark|compare|versus|\bvs\b"),
    ("materials", r"material|leather|alcantara|\bwood|plastic|\btrim\b|fabric|veganza|carbon"),
    ("cars", r"how many cars|\bsell|sales|units|volume|revenue|lose|\bwin\b|at stake|business"),
    ("markets", r"which market|which region|which countr|\bwhere\b|regions|markets|variant|region[- ]specific"),
    ("issues", r"complain|complaint|problem|issue|wrong|broken|annoy|hate|fail"),
    ("have", r"\bshould\b|worth|important|\bkeep\b|\bdrop\b|remove|must[- ]have|have it|offer it|add it|standard"),
    ("need", r"how much|demand|how many (?:people|customers)|\bwant|ask(?:ing)? for|\bneed"),
]
INTENT_LABEL = {"full": "Full assessment", "need": "How much is it needed?", "have": "Have it or not?",
                "markets": "Which markets?", "materials": "Which materials?", "cars": "How many cars are at stake?",
                "issues": "What do customers complain about?", "rivals": "How do competitors compare?"}
STAGES = [("question", "Question"), ("filter", "Filter data"), ("read", "AI reads reviews"),
          ("compute", "Compute"), ("decide", "Decide"), ("recommend", "Recommend")]


def _find(patterns: dict, text: str) -> tuple[str | None, str | None]:
    for key, rx in patterns.items():
        m = re.search(rx, text, 0 if key == "US" else re.I)
        if m:
            return key, m.group(0)
    return None, None


# --------------------------------------------------------------------------- feature candidates
def feature_candidates(text: str, model: rim.ReviewModel | None) -> list[dict]:
    """Rank catalog features and model components for the question text."""
    tl = text.lower()
    comp_p = {c["label"]: c["p"] for c in model.top(text, "component", 12)} if model else {}
    cands = []
    for f in tx.FEATURES:
        hits = [s for s in (f.label.lower(),) + f.synonyms if len(s) > 2 and re.search(rf"\b{re.escape(s)}", tl)]
        text_score = min(1.0, max((len(h) for h in hits), default=0) / 14)
        mp = max((comp_p.get(c, 0.0) for c in f.components), default=0.0)
        score = 0.65 * text_score + 0.35 * mp
        if score > 0.12:
            cands.append({"value": f.label, "label": f.label, "score": round(score, 3), "key": f.key,
                          "category": tx.domain_of(f.components[0]) if f.components else "",
                          "evidence": (f"matched words: {', '.join(hits[:3])}" if hits else "no word match")
                                      + f"; model p={mp:.2f}", "text_score": round(text_score, 2),
                          "model_p": round(mp, 2)})
    in_catalog = {c for f in tx.FEATURES for c in f.components}
    for comp, p in comp_p.items():
        if comp not in in_catalog and p >= 0.2:
            cands.append({"value": f"component: {comp}", "label": comp, "score": round(0.35 * p + 0.1, 3),
                          "key": f"component:{comp}", "category": tx.domain_of(comp),
                          "evidence": f"review model p={p:.2f}", "text_score": 0.0, "model_p": round(p, 2)})
    return sorted(cands, key=lambda c: -c["score"])


def most_complained(data: Data, vehicle: str | None, n: int) -> list[tuple]:
    f = data.scope(vehicle)
    f = f[f["signal"].isin(tx.COMPLAINT_SIGNALS)]
    ranked = [(feat, int(f.loc[f["component"].isin(feat.components), "verbatim_id"].nunique())) for feat in tx.FEATURES]
    return sorted(ranked, key=lambda x: -x[1])[:n]


def parse(text: str, overrides: dict, data: Data) -> dict:
    model = rim.load()
    slots, missing, events = {}, [], []
    ev = lambda title, detail="", agent="parser": events.append({"agent": agent, "title": title, "detail": detail})

    # vehicle
    if overrides.get("vehicle") in DERIVATIVES:
        v = overrides["vehicle"]
        slots["vehicle"] = {"value": v, "label": DERIVATIVES[v]["name"], "source": "you picked it"}
    else:
        v, word = _find(VEHICLES, text)
        if v:
            slots["vehicle"] = {"value": v, "label": DERIVATIVES[v]["name"], "source": f"'{word}' in your question"}
            ev(f"Vehicle: {DERIVATIVES[v]['name']}", f"matched '{word}' in the vehicle dictionary")
        else:
            voices = data.findings.groupby("derivative")["verbatim_id"].nunique().to_dict()
            missing.append({"slot": "vehicle", "question": "Which car is this about?",
                            "options": [{"value": k, "label": d["name"], "detail": f"{k} · {voices.get(k, 0):,} reviews"}
                                        for k, d in DERIVATIVES.items()]})
            ev("Vehicle not stated", "asking you to pick one", "clarify")

    # feature
    cands = feature_candidates(text, model)
    if overrides.get("feature"):
        f = overrides["feature"]
        slots["feature"] = {"value": f, "label": f.replace("component: ", ""), "source": "you picked it"}
    else:
        best = cands[0] if cands else None
        second = cands[1]["score"] if len(cands) > 1 else 0.0
        if best and best["score"] >= 0.45 and best["score"] - second >= 0.08:
            slots["feature"] = {"value": best["value"], "label": best["label"], "source": best["evidence"],
                                "score": best["score"]}
            ev(f"Feature: {best['label']}", f"{best['evidence']} · combined score {best['score']:.2f}")
        else:
            strong = [c for c in cands if c["score"] >= 0.3][:4]
            veh = slots.get("vehicle", {}).get("value")
            options = [{"value": c["value"], "label": c["label"], "detail": f"{c['category']} · {c['evidence']}",
                        "score": c["score"]} for c in strong]
            for f, n in most_complained(data, veh, 8):
                if len(options) >= 6:
                    break
                if all(o["label"] != f.label for o in options):
                    options.append({"value": f.label, "label": f.label,
                                    "detail": f"{tx.domain_of(f.components[0])} · {n:,} complaining reviews"
                                              f"{' on this car' if veh else ''}"})
            missing.append({"slot": "feature", "question": "Which feature do you mean?" if strong else
                            "Which feature? (none named - these get the most complaints)", "options": options})
            ev("Feature ambiguous" if cands else "Feature not found",
               f"top candidates: {', '.join(c['label'] for c in cands[:3])}" if cands else "asking you", "clarify")

    # market (optional), powertrain (optional), intent
    m, word = overrides.get("market"), None
    if m is None:
        m, word = _find(MARKETS, text)
        if m:
            ev(f"Market: {REGION_NAMES[m]}", f"matched '{word}'")
    m_src = "you picked it" if overrides.get("market") else (f"'{word}' in your question" if m else "not stated - all markets")
    slots["market"] = {"value": m or "", "label": REGION_NAMES.get(m, "All markets"), "source": m_src}
    pt, word = overrides.get("powertrain"), None
    if pt is None:
        pt, word = _find(POWERTRAINS, text)
        if pt:
            ev(f"Powertrain: {pt}", f"matched '{word}'")
    slots["powertrain"] = {"value": pt or "", "label": pt or "All powertrains",
                           "source": f"'{word}' in your question" if pt and not overrides.get("powertrain") else
                           ("you picked it" if pt else "not stated - all")}
    intent = overrides.get("intent") or next((k for k, rx in INTENTS if re.search(rx, text, re.I)), "full")
    slots["intent"] = {"value": intent, "label": INTENT_LABEL[intent],
                       "source": "keywords in your question" if intent != "full" else "no specific question - full assessment"}
    ev(f"Question type: {INTENT_LABEL[intent]}", slots["intent"]["source"])
    return {"text": text, "slots": slots, "missing": missing, "candidates": cands[:5], "events": events,
            "ready": not missing}


# --------------------------------------------------------------------------- answer
def verdict(b: dict) -> dict:
    d, k = b["demand"], b["kano"]["class"]
    req = d["requests"] + d["inferred_requests"]
    if d["verbatims_mentioning"] < 5:
        return {"key": "research", "label": "Research first", "tone": "neutral",
                "line": f"Only {d['verbatims_mentioning']} reviews mention it - not enough to decide."}
    return {"Must-be": {"key": "fix", "label": "Fix it", "tone": "danger",
                        "line": f"Customers expect it to work - {d['complaints']} complain about today's version."},
            "Unmet need": {"key": "add", "label": "Add it", "tone": "accent", "line": f"Customers ask for it - {req} requests."},
            "Attractive": {"key": "keep", "label": "Keep & promote", "tone": "success",
                           "line": f"A delighter - {d['praise']} customers praise it."},
            "Performance": {"key": "improve", "label": "Improve it", "tone": "warning",
                            "line": f"Better execution = happier customers ({d['praise']} praise vs {d['complaints']} complaints)."},
            }.get(k, {"key": "research", "label": "Research first", "tone": "neutral", "line": b["kano"]["why"]})


def _direct_answer(intent: str, b: dict, market: str) -> str:
    d = b["demand"]
    regs = b["regions"]
    focus = [market] if market else REGIONS
    if intent == "need":
        return d["headline"]
    if intent == "have":
        return f"{b['kano']['class']}: {b['have_vs_not']['have']} {b['have_vs_not']['not_have']}"
    if intent == "markets" or (market and intent == "full"):
        return " ".join(f"{REGION_NAMES[r]}: {regs[r]['recommendation']['label']} - {regs[r]['recommendation']['why']}"
                        for r in focus)
    if intent == "cars":
        s = b["sales"]
        if market:
            r = s["by_region"][market]
            return (f"In {REGION_NAMES[market]}: about {r['units_at_stake']:,} cars at stake out of {r['volume']:,} planned "
                    f"({r['customers_who_care']:,} customers care x {s['sensitivity']:.0%} decision sensitivity).")
        return (f"About {s['units_at_stake']:,} cars are at stake out of {s['exposure']:,} planned "
                f"({s['customers_who_care']:,} customers care x {s['sensitivity']:.0%} decision sensitivity).")
    if intent == "materials":
        mats = b["materials"]["feature"] or b["materials"]["vehicle"]
        if not mats:
            return "Customers rarely mention materials for this feature."
        best = max(mats, key=lambda x: x["net"])
        worst = min(mats, key=lambda x: x["net"])
        return (f"Most liked: {best['material']} (+{best['positive']}/-{best['negative']}). "
                f"Most criticised: {worst['material']} (+{worst['positive']}/-{worst['negative']}).")
    if intent == "issues":
        top = b["issues"][:3]
        return ("Top problems: " + "; ".join(f"{i['issue']} ({i['verbatims']})" for i in top)) if top else \
            "No classified complaints for this feature."
    if intent == "rivals":
        c = b["competitors"]["mentions"] or b["competitors"]["vehicle_mentions"]
        return (f"Customers compare most with {c[0]['brand']} ({c[0]['verbatims']} reviews)." if c
                else "Customers do not name rivals here - run web research for the market.")
    return verdict(b)["line"]


def run(parsed: dict, data: Data, horizon: str = DEFAULT_HORIZON, sensitivity: float | None = None) -> dict:
    s = parsed["slots"]
    vehicle, feature = s["vehicle"]["value"], s["feature"]["value"]
    market, pt, intent = s["market"]["value"], s["powertrain"]["value"] or None, s["intent"]["value"]
    model = rim.load()
    b = feature_brief(data, feature, vehicle, horizon, pt, sensitivity)
    req = score_feature(data, feature, vehicle, horizon, pt)
    stages = {}

    # ---- question
    stages["question"] = {"slots": s, "resolution": b["resolution"], "candidates": parsed["candidates"],
                          "events": parsed["events"]}

    # ---- filter (data funnel)
    total = int(data.findings["verbatim_id"].nunique())
    veh = int(data.scope(vehicle)["verbatim_id"].nunique())
    scoped = b["scope"]["verbatims"]
    ls = b["label_sources"]
    funnel = [
        {"label": "All customer reviews", "reviews": total, "rule": "3 vehicles, 4 sources, 14 countries"},
        {"label": DERIVATIVES[vehicle]["name"], "reviews": veh, "rule": f"derivative == {vehicle}"},
    ]
    if pt:
        funnel.append({"label": f"{pt} only", "reviews": scoped, "rule": f"engine type == {pt}"})
    funnel.append({"label": f"Mention {b['resolution']['label']}", "reviews": b["demand"]["verbatims_mentioning"],
                   "rule": f"VFC label in {len(b['resolution']['components'])} component(s): {ls['vfc']} · "
                           f"AI-model label: {ls['model']} · free-text match: {ls['text']}"})
    if market:
        r = b["regions"][market]
        funnel.append({"label": f"in {REGION_NAMES[market]}", "reviews": r["mentions"],
                       "rule": f"country mapped to {market}; {r['verbatim_base']:,} reviews from this market in total"})
    stages["filter"] = {"funnel": funnel, "split": ls, "by_region": {k: {"mentions": v["mentions"],
                        "base": v["verbatim_base"]} for k, v in b["regions"].items()},
                        "events": [{"agent": "filter", "title": f"{f['label']}: {f['reviews']:,} reviews",
                                    "detail": f["rule"]} for f in funnel]}

    # ---- read (AI model)
    examples = []
    comps = set(b["resolution"]["components"])
    if model:
        # show reviews where the model itself finds the asked-about component
        pool = data.scope(vehicle)
        pool = pool[pool["component"].isin(comps) & (pool["signal"] != "none")].drop_duplicates("verbatim_id")
        pool = pool[pool["text"].str.len() < 700].head(20)
        scored = []
        for r in pool.itertuples():
            a = model.analyse(r.text)
            hits = [x for x in a["aspects"] if x["component"] in comps]
            scored.append((bool(hits), max((x["p"] for x in hits), default=0.0), r, a))
        scored.sort(key=lambda t: (not t[0], -t[1]))
        for has, _, r, a in scored[:3]:
            examples.append({"verbatim_id": r.verbatim_id, "country": r.country, "vfc": r.issue or r.component,
                             "vfc_signal": r.signal, "text": r.text[:420], "model_found_feature": has,
                             "aspects": sorted(a["aspects"], key=lambda x: x["component"] not in comps)[:3],
                             "category": a["category"][0], "signal": a["signal"][0]})
    card = model.card if model else {}
    d = b["demand"]
    stages["read"] = {"hierarchy": b["hierarchy"][:3], "feature_components": b["resolution"]["components"], "signals": {"praise": d["praise"], "complaints": d["complaints"],
                      "defects": d["defects"], "usability": d["usability"], "requests": d["requests"],
                      "inferred_requests": d["inferred_requests"]},
                      "examples": examples, "split": ls,
                      "model": {k: card.get("metrics", {}).get(k, {}).get("top1_accuracy") for k in rim.HEADS},
                      "events": [{"agent": "model", "title": f"Classified {d['labelled']} reviews into the taxonomy",
                                  "detail": " › ".join([b['hierarchy'][0]['name'], b['hierarchy'][0]['components'][0]['name']])
                                  if b["hierarchy"] else "no labelled reviews"},
                                 {"agent": "model", "title": f"{d['praise']} praise · {d['complaints']} complaints · "
                                                             f"{d['requests'] + d['inferred_requests']} requests",
                                  "detail": "signal head + VFC issue labels"}]
                      + ([{"agent": "model", "title": f"AI model added {ls['model']} reviews VFC had not labelled",
                           "detail": "sentence-level aspect extraction"}] if ls["model"] else [])}

    # ---- compute
    base = {k: v["verbatim_base"] for k, v in b["regions"].items()}
    counts = {k: v["mentions"] for k, v in b["regions"].items()}
    prior = d["verbatims_mentioning"] / scoped if scoped else 0
    markets = []
    for r in ([market] if market else REGIONS):
        n, nb = counts[r], base[r]
        shr = (n + PRIOR_STRENGTH * prior) / (nb + PRIOR_STRENGTH) if nb >= MIN_REGION_BASE else None
        markets.append({"region": r, "name": REGION_NAMES[r], "mentions": n, "base": nb,
                        "rate_per_1000": round(n / nb * 1000, 2) if nb else None,
                        "shrunk_formula": (f"({n} + {PRIOR_STRENGTH} × {prior:.4f}) / ({nb:,} + {PRIOR_STRENGTH}) = {shr:.4f}"
                                           if shr is not None else f"only {nb} reviews < {MIN_REGION_BASE}: not computed"),
                        "index": b["regions"][r]["relative_index"], "survey": b["regions"][r]["survey"],
                        "volume": b["regions"][r]["volume"],
                        "sales": b["sales"]["by_region"][r]})
    sa = b["sales"]
    stages["compute"] = {
        "rate": {"mentions": d["verbatims_mentioning"], "base": scoped, "per_1000": d["per_1000"],
                 "formula": f"{d['verbatims_mentioning']} / {scoped:,} × 1,000 = {d['per_1000']}"},
        "prior": round(prior, 5), "markets": markets,
        "sales": {"exposure": sa["exposure"], "customers_who_care": sa["customers_who_care"],
                  "units_at_stake": sa["units_at_stake"], "sensitivity": sa["sensitivity"],
                  "formula": f"Σ markets: volume × share who care × {sa['sensitivity']:.0%} = {sa['units_at_stake']:,} cars"},
        "events": [{"agent": "compute", "title": f"Mention rate {d['per_1000']} per 1,000 reviews",
                    "detail": f"{d['verbatims_mentioning']} / {scoped:,}"},
                   {"agent": "compute", "title": f"{sa['units_at_stake']:,} cars at stake",
                    "detail": f"of {sa['exposure']:,} planned · sensitivity {sa['sensitivity']:.0%}"}]}

    # ---- decide
    rules = {"kano": b["kano"], "markets": {r: b["regions"][r]["recommendation"] for r in ([market] if market else REGIONS)},
             "priority": None}
    if req:
        rules["priority"] = {"score": req["priority"]["score"], "tier": req["priority"]["tier"],
                             "raw": req["priority"]["raw"], "evidence_multiplier": req["priority"]["evidence_multiplier"],
                             "weights": req["priority"]["weights"], "contributions": req["priority"]["contributions"],
                             "factors": req["factors"], "notes": req["factor_notes"], "evidence": req["evidence"]}
    rules["events"] = [{"agent": "decide", "title": f"Kano rule → {b['kano']['class']}",
                        "detail": next(p["test"] for p in b["kano"]["path"] if p["fired"])}] + \
        [{"agent": "decide", "title": f"{REGION_NAMES[r]} → {rec['label']}", "detail": rec["path"][-1]["test"]}
         for r, rec in rules["markets"].items()] + \
        ([{"agent": "decide", "title": f"Priority {req['priority']['tier']} · score {req['priority']['score']}",
           "detail": f"evidence {req['evidence']['level']}"}] if req else [])
    stages["decide"] = rules

    # ---- recommend
    v = verdict(b)
    stages["recommend"] = {
        "verdict": v, "intent": intent, "intent_label": INTENT_LABEL[intent],
        "answer": _direct_answer(intent, b, market),
        "markets": {r: {"label": b["regions"][r]["recommendation"]["label"], "level": b["regions"][r]["recommendation"]["level"],
                        "why": b["regions"][r]["recommendation"]["why"], "volume": b["regions"][r]["volume"]}
                    for r in REGIONS},
        "key_numbers": {"per_1000": d["per_1000"], "complaints": d["complaints"],
                        "requests": d["requests"] + d["inferred_requests"], "praise": d["praise"],
                        "units_at_stake": sa["units_at_stake"]},
        "equipment": b["equipment"][vehicle]["status"],
        "materials": (b["materials"]["feature"] or b["materials"]["vehicle"])[:4],
        "rivals": (b["competitors"]["mentions"] or b["competitors"]["vehicle_mentions"])[:3],
        "quotes": b["quotes"][:4], "coverage_warning": b["coverage_warning"],
        "requirement": {"id": req["id"], "title": req["title"], "description": req["description"],
                        "acceptance_criteria": req["acceptance_criteria"], "assumptions": req["assumptions"]} if req else None,
        "events": [{"agent": "recommend", "title": f"{v['label']}", "detail": v["line"]}],
    }
    return {"query": {"vehicle": vehicle, "feature": feature, "market": market, "powertrain": pt, "intent": intent,
                      "horizon": horizon, "text": parsed["text"]},
            "stages": [{"id": k, "label": lbl, **stages[k]} for k, lbl in STAGES]}
