"""FastAPI backend for the PM cockpit. Run with `python -m pm_copilot serve`."""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, inquiry, requirements, research, scoring
from . import model as rim
from . import taxonomy as tx
from .brief import feature_brief, resolve
from .config import (DECISION_SENSITIVITY, DEFAULT_HORIZON, DERIVATIVES, EVIDENCE_LEVELS, FRONTEND_DIR, HORIZONS,
                     PRIORITY_WEIGHTS, REGION_NAMES, REGIONS, TIERS, WEIGHTS_VERSION)
from .store import DataNotBuilt, load
from .decision_api import router as decision_router

app = FastAPI(title="BMW Requirements Cockpit", version="1.0")
app.include_router(decision_router)


def _data():
    try:
        return load()
    except DataNotBuilt as exc:
        raise HTTPException(503, str(exc)) from exc


class Decision(BaseModel):
    status: str
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=3)


class Edit(BaseModel):
    changes: dict
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=3)


class Challenge(BaseModel):
    question: str = Field(min_length=3)
    actor: str = Field(min_length=1)


class FromFeature(BaseModel):
    query: str
    derivative: str
    actor: str = Field(min_length=1)
    rationale: str = ""
    horizon: str = DEFAULT_HORIZON


class Ask(BaseModel):
    text: str = Field(min_length=2)
    overrides: dict = {}
    horizon: str = DEFAULT_HORIZON
    sensitivity: float | None = None


class AnalyseText(BaseModel):
    text: str = Field(min_length=3)


class ResearchRequest(BaseModel):
    query: str
    derivative: str
    region: str
    actor: str = "pm"


@app.get("/api/meta")
def meta():
    data = _data()
    f = data.findings
    coverage = f.groupby(["derivative", "region"])["verbatim_id"].nunique().unstack(fill_value=0)
    return {
        "derivatives": {k: {"name": v["name"], "segment": v["segment"]} for k, v in DERIVATIVES.items()},
        "regions": {r: REGION_NAMES[r] for r in REGIONS}, "horizons": HORIZONS, "default_horizon": DEFAULT_HORIZON,
        "features": [{"key": x.key, "label": x.label, "zone": tx.FEATURE_ZONE[x.key]} for x in tx.FEATURES],
        "zones": tx.ZONES,
        "components": sorted(set(f["component"]) - {"no_class_found"}),
        "coverage": {d: {r: int(coverage.loc[d, r]) if d in coverage.index and r in coverage.columns else 0
                         for r in REGIONS} for d in DERIVATIVES},
        "volumes": {d: {h: data.volumes(d, h) for h in HORIZONS} for d in DERIVATIVES},
        "manifest": data.manifest,
        "logic": {"weights_version": WEIGHTS_VERSION, "weights": PRIORITY_WEIGHTS, "tiers": TIERS,
                  "evidence_levels": EVIDENCE_LEVELS, "decision_sensitivity": DECISION_SENSITIVITY},
        "ai_key_present": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
    }


@app.post("/api/ask")
def ask(body: Ask):
    """Inquiry agent: parse the question; if nothing is missing, run the staged analysis."""
    data = _data()
    parsed = inquiry.parse(body.text, body.overrides or {}, data)
    result = inquiry.run(parsed, data, body.horizon, body.sensitivity) if parsed["ready"] else None
    return {"parsed": parsed, "result": result}


@app.get("/api/taxonomy")
def taxonomy():
    """Category (L1) -> component (VFC L2) -> issue (VFC L3) with review counts."""
    f = _data().findings
    f = f[f["component"] != "no_class_found"]
    cats = []
    for dom, d in f.groupby("domain"):
        comps = []
        for comp, c in d.groupby("component"):
            iss = c.groupby(["issue", "signal"])["verbatim_id"].nunique().sort_values(ascending=False)
            comps.append({"name": comp, "reviews": int(c["verbatim_id"].nunique()),
                          "model_reviews": int(c.loc[c["label_source"] == "model", "verbatim_id"].nunique()),
                          "issues": [{"name": i or "(unspecified)", "signal": s, "reviews": int(n)} for (i, s), n in iss.items()]})
        cats.append({"name": dom, "reviews": int(d["verbatim_id"].nunique()),
                     "components": sorted(comps, key=lambda x: -x["reviews"])})
    return {"categories": sorted(cats, key=lambda x: -x["reviews"]),
            "unique": {"categories": len(cats), "components": int(f["component"].nunique()),
                       "issues": int(f.loc[f["issue"] != "", "issue"].nunique()),
                       "pairs": int((f["component"] + "|" + f["issue"]).nunique())}}


@app.get("/api/model")
def model_card():
    m = rim.load()
    if m is None:
        raise HTTPException(503, "Model not trained - run `python -m pm_copilot build`.")
    card = dict(m.card)
    card["metrics"] = {h: {k: v for k, v in met.items() if k != "per_class"} |
                       {"best": sorted(((c, x["f1"], x["support"]) for c, x in met["per_class"].items() if x["support"] >= 10),
                                       key=lambda t: -t[1])[:5],
                        "worst": sorted(((c, x["f1"], x["support"]) for c, x in met["per_class"].items() if x["support"] >= 10),
                                        key=lambda t: t[1])[:5]}
                       for h, met in m.card["metrics"].items()}
    return card


@app.post("/api/model/analyse")
def model_analyse(body: AnalyseText):
    m = rim.load()
    if m is None:
        raise HTTPException(503, "Model not trained - run `python -m pm_copilot build`.")
    out = m.analyse(body.text)
    out["explain"] = {h: m.explain(body.text, h, out[h][0]["label"]) for h in rim.HEADS}
    return out


def _mini(r: dict) -> dict:
    return {"id": r["id"], "title": r["title"], "type": r["type"], "status": r["status"], "zone": r.get("zone"),
            "tier": r["priority"]["tier"], "score": r["priority"]["score"], "evidence": r["evidence"]["level"]}


@app.get("/api/overview")
def overview(derivative: str, region: str | None = None, horizon: str = DEFAULT_HORIZON):
    """Everything the car map needs: per-zone signal + requirements, market pulse, KPIs."""
    if derivative not in DERIVATIVES:
        raise HTTPException(400, f"Unknown derivative {derivative}")
    data = _data()
    f = data.scope(derivative)
    if region:
        f = f[f["region"] == region]
    base_n = int(f["verbatim_id"].nunique())
    f = f[(f["signal"] != "none") & (f["zone"] != "")]
    all_reqs = requirements.list_requirements(derivative)
    reqs = [r for r in all_reqs if not region or r["regions"][region]["verbatims"] > 0
            or r["regions"][region]["recommendation"]["level"] in ("high", "medium")]
    zones = []
    for key, label in tx.ZONES.items():
        zf = f[f["zone"] == key]
        sig = scoring.signal_summary(zf)
        zr = [r for r in reqs if r.get("zone") == key]
        open_r = [r for r in zr if r["status"] in ("Proposed", "Changes requested")]
        tiers = {t: sum(1 for r in open_r if r["priority"]["tier"] == t) for t in ("P1", "P2", "P3")}
        issues = (zf[zf["signal"].isin(("defect", "usability", "request"))].drop_duplicates(["verbatim_id", "issue"])
                  .groupby(["component", "issue"])["verbatim_id"].nunique().sort_values(ascending=False).head(3))
        zones.append({
            "key": key, "label": label, "verbatims": sig["verbatims"], "praise": sig["praise"],
            "complaints": sig["complaints"], "requests": sig["request"],
            "per_1000": round(sig["verbatims"] / base_n * 1000, 1) if base_n else 0.0,
            "issues": [{"component": c, "issue": i, "verbatims": int(n)} for (c, i), n in issues.items()],
            "tiers": tiers, "top_tier": next((t for t in ("P1", "P2", "P3") if tiers[t]), None),
            "requirements": [_mini(r) for r in zr[:6]],
            "features": [{"key": x.key, "label": x.label} for x in tx.FEATURES if tx.FEATURE_ZONE[x.key] == key],
        })
    volumes = data.volumes(derivative, horizon)
    base = data.verbatim_base(derivative)
    allf = data.scope(derivative)
    allf = allf[(allf["zone"] != "") & allf["signal"].isin(("defect", "usability"))]
    markets = []
    for r in REGIONS:
        rf = allf[allf["region"] == r]
        top = rf.groupby("zone")["verbatim_id"].nunique().sort_values(ascending=False)
        rel = [x for x in all_reqs if x["priority"]["tier"] == "P1"
               and x["regions"][r]["recommendation"]["level"] in ("high", "medium")]
        markets.append({"region": r, "name": REGION_NAMES[r], "volume": volumes[r], "verbatims": base[r],
                        "covered": base[r] >= 30, "top_zone": top.index[0] if len(top) else None,
                        "top_zone_label": tx.ZONES.get(top.index[0]) if len(top) else None, "p1": len(rel)})
    count = lambda s: sum(1 for r in reqs if r["status"] == s)
    return {
        "vehicle": {"code": derivative, **{k: DERIVATIVES[derivative][k] for k in ("name", "segment")}},
        "region": region, "horizon": horizon,
        "kpis": {"verbatims": base_n, "open": count("Proposed") + count("Changes requested"),
                 "p1_open": sum(1 for r in reqs if r["priority"]["tier"] == "P1"
                                and r["status"] in ("Proposed", "Changes requested")),
                 "awaiting": count("Proposed"), "approved": count("Approved"), "rejected": count("Rejected"),
                 "changes": count("Changes requested"), "volume": sum(volumes.values()),
                 "markets_sold": sum(1 for v in volumes.values() if v)},
        "zones": zones, "markets": markets,
        "top_decisions": [_mini(r) for r in reqs if r["status"] == "Proposed"][:6],
    }


@app.get("/api/brief")
def brief(q: str, derivative: str | None = None, horizon: str = DEFAULT_HORIZON, powertrain: str | None = None,
          sensitivity: float | None = None):
    if derivative and derivative not in DERIVATIVES:
        raise HTTPException(400, f"Unknown derivative {derivative}")
    return feature_brief(_data(), q, derivative or None, horizon, powertrain or None, sensitivity)


@app.get("/api/requirements")
def list_requirements(derivative: str | None = None, status: str | None = None, type: str | None = None,
                      region: str | None = None):
    reqs = requirements.list_requirements(derivative or None, status or None, type or None, region or None)
    keys = ("id", "type", "derivative", "title", "status", "kano", "priority", "evidence", "evidence_summary",
            "domain", "zone", "component", "regions", "updated_at", "version")
    return [{k: r.get(k) for k in keys} for r in reqs]


@app.get("/api/requirements/{req_id}")
def get_requirement(req_id: str):
    with db.connect() as con:
        row = db.get(con, req_id)
        if row is None:
            raise HTTPException(404, "Requirement not found")
        req = db.effective(row)
        req["audit"] = db.audit(con, req_id)
    return req


@app.post("/api/requirements/{req_id}/decision")
def decide(req_id: str, body: Decision):
    with db.connect() as con:
        try:
            return db.decide(con, req_id, body.status, body.actor, body.rationale)
        except KeyError:
            raise HTTPException(404, "Requirement not found")
        except ValueError as exc:
            raise HTTPException(400, str(exc))


@app.patch("/api/requirements/{req_id}")
def edit(req_id: str, body: Edit):
    with db.connect() as con:
        try:
            return db.edit(con, req_id, body.changes, body.actor, body.rationale)
        except KeyError:
            raise HTTPException(404, "Requirement not found")
        except ValueError as exc:
            raise HTTPException(400, str(exc))


def _fallback_answer(req: dict) -> str:
    ev, prio = req["evidence"], req["priority"]
    lines = [f"Why it ranks here: {req['priority_rationale']}",
             f"Evidence ({ev['level']}, {ev['score']}): {', '.join(ev['reasons'])}.",
             "Known assumptions / uncertainties: " + " ".join(req["assumptions"])]
    if req["quotes"]:
        q = req["quotes"][0]
        lines.append(f"Strongest linked verbatim ({q['verbatim_id']}, {q['country']}): \"{q['text'][:200]}\"")
    weak = [k for k, v in req["factors"].items() if v < 0.35 and prio["weights"].get(k)]
    if weak:
        lines.append("Weak factors to probe: " + ", ".join(weak) + ".")
    lines.append("Suggested action: " + ("gather more evidence" if ev["level"] == "Low" else "keep"))
    return "\n".join(lines)


@app.post("/api/requirements/{req_id}/challenge")
def challenge(req_id: str, body: Challenge):
    with db.connect() as con:
        row = db.get(con, req_id)
        if row is None:
            raise HTTPException(404, "Requirement not found")
        req = db.effective(row)
        db.log(con, body.actor, "pm", "challenged", req_id, rationale=body.question)
    try:
        answer, responder, kind = research.answer_challenge(req, body.question), "claude", "ai"
    except research.AIUnavailable as exc:
        answer = _fallback_answer(req) + f"\n\n(Rule-based answer - AI unavailable: {exc})"
        responder, kind = "pipeline", "system"
    with db.connect() as con:
        db.log(con, responder, kind, "challenge_answered", req_id, rationale=answer)
    return {"answer": answer, "responder": responder}


@app.post("/api/requirements/from-feature")
def from_feature(body: FromFeature):
    try:
        return requirements.create_from_feature(_data(), body.query, body.derivative, body.actor, body.rationale,
                                                body.horizon)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/audit")
def audit(requirement_id: str | None = None, limit: int = 300):
    with db.connect() as con:
        return db.audit(con, requirement_id or None, limit)


@app.post("/api/research")
def run_research(body: ResearchRequest):
    data = _data()
    if body.derivative not in DERIVATIVES or body.region not in REGIONS:
        raise HTTPException(400, "Unknown derivative or region")
    b = feature_brief(data, body.query, body.derivative)
    reg = b["regions"][body.region]
    context = (f"- {b['demand']['headline']}\n- Kano-style class: {b['kano']['class']}\n"
               f"- Availability today (German price list): {b['equipment'][body.derivative]['status']}\n"
               f"- {REGION_NAMES[body.region]}: {reg['mentions']} of {reg['verbatim_base']} verbatims; "
               f"recommendation '{reg['recommendation']['label']}'; planned volume {reg['volume']:,}.")
    res = resolve(body.query, data)
    try:
        record = research.run_web_research(body.derivative, body.region, res.label, res.key, context)
    except research.AIUnavailable as exc:
        raise HTTPException(503, str(exc))
    with db.connect() as con:
        db.log(con, "claude", "ai", "web_research", None, "competitor_benchmark", None,
               {"derivative": body.derivative, "region": body.region, "feature": res.label,
                "competitor_ahead": record["result"]["competitor_ahead"],
                "sources": len(record["search_results"])},
               f"Requested by {body.actor}: {record['result']['summary'][:400]}")
    return record


@app.get("/api/export")
def export(derivative: str | None = None, format: str = "json"):
    if format not in ("json", "csv"):
        raise HTTPException(400, "format must be json or csv")
    path, name = requirements.export(derivative or None, format)
    return FileResponse(path, filename=name)


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
