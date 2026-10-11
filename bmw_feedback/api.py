"""HTTP API for the Product Decision Studio frontend.

    uvicorn bmw_feedback.api:app --port 8000        (or: python -m bmw_feedback serve)

Every endpoint reads the processed tables written by `build` / `train`; nothing
here computes a number that is not traceable to those tables or the raw files.
The built frontend (frontend/dist) is served from / when present.
"""

import json
import math
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, scoring, taxonomy
from .decision import DEFAULT_POLICY, MARKETS, DecisionEngine, PolicyError, read_decisions, record_decision

STATE = {}
FRONTEND = config.ROOT / "frontend" / "dist"


def jsonable(obj):
    """Recursively convert numpy / pandas values; NaN and inf become None."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if obj is pd.NA or obj is pd.NaT:
        return None
    return obj


def _records(df: pd.DataFrame) -> list:
    return jsonable(df.to_dict("records"))


@asynccontextmanager
async def lifespan(_app):
    from .agents.pipeline import Pipeline
    engine = DecisionEngine()
    STATE["engine"] = engine
    STATE["ctx"] = engine.ctx
    STATE["catalog"] = engine.catalog
    STATE["pipeline"] = pipe = Pipeline(engine)
    from .agents.competition import CompetitionService
    STATE["competition"] = CompetitionService(graph=pipe.g, llm_getter=lambda: STATE["pipeline"]._current_llm(),
                                              ctx=engine.ctx)
    yield


app = FastAPI(title="BMW Product Decision Studio API", lifespan=lifespan)


@app.exception_handler(PolicyError)
def _policy_error(_: Request, e: PolicyError):
    """A refused policy override (e.g. weights not summing to 1) is the caller's error, never a silent fix."""
    return JSONResponse(status_code=400, content={"detail": str(e)})


app.add_middleware(GZipMiddleware, minimum_size=4096)       # the entire-graph payload is ~2.6 MB raw


def _json(name):
    path = config.REPORTS_DIR / name
    return json.loads(path.read_text()) if path.exists() else None


# ---------------------------------------------------------------------- overview
@app.get("/api/overview")
def overview():
    ctx, engine = STATE["ctx"], STATE["engine"]
    quality = _json("data_quality.json") or {}
    feats = ctx.features
    specific = feats[~feats["is_umbrella"]]
    labelled = ctx.labels.drop_duplicates("comment_id")
    coverage = labelled.groupby(["model", "market"]).size().rename("comments").reset_index()
    cat = STATE["catalog"]
    return jsonable({
        "comments": quality.get("raw_unique_comments"),
        "labelled_comments": quality.get("comments_by_label_status", {}).get("labeled"),
        "features": int(len(feats)), "specific_features": int(len(specific)),
        "domains": len(taxonomy.DOMAINS),
        "verdicts_specific": specific["verdict"].value_counts().to_dict(),
        "feedback_coverage": _records(coverage),
        "catalog": {"variants": int(len(cat["variants"])), "items": int(len(cat["option_items"])),
                    "fitment_cells": int(len(cat["fitment"])), "technical_values": int(len(cat["technical"])),
                    "linked_features": int(cat["feature_option_links"]["feature"].nunique()),
                    "validation": quality.get("option_catalog")},
        "data": engine.fingerprint,
        "models": {m: config.MODEL_NAMES[m] for m in config.MODELS},
    })


# ---------------------------------------------------------------------- features
@app.get("/api/features")
def features():
    ctx = STATE["ctx"]
    f = ctx.features.reset_index()
    summary = STATE["catalog"].get("feature_fitment_summary")
    tiers = {} if summary is None else {(r.feature, r.model): r.tier for r in summary.itertuples()}
    rows = []
    for r in f.itertuples():
        rows.append({"feature": r.feature, "domain": r.domain, "umbrella": bool(r.is_umbrella),
                     "verdict": r.verdict, "confidence": r.confidence, "n_comments": int(r.n_comments),
                     "complaint_index": r.index_negative, "ci_low": r.ci_low_negative,
                     "ci_high": min(r.ci_high_negative, 99), "praise_index": r.index_positive,
                     "request_index": r.index_request, "requested": bool(r.requested),
                     "bad_kind": scoring.bad_kind(f.loc[r.Index]),
                     "fitment": {m: tiers.get((r.feature, m)) for m in config.MODELS}})
    return jsonable(rows)


@app.get("/api/features/{name:path}")
def feature(name: str):
    ctx = STATE["ctx"]
    if name not in ctx.features.index:
        resolved = ctx.resolve(name)
        if resolved is None:
            raise HTTPException(404, f"Unknown feature: {name}")
        name = resolved
    card = ctx.feature_card(name)
    engine = STATE["engine"]
    card["price_ladder"] = [{"model": m, **(engine._fitment(name, m) or {})} for m in config.MODELS]
    cells = engine.cells
    card["by_model_market"] = [
        {"model": m, "market": k, "n_comments": int(r["n_comments"]), "verdict": r["verdict"],
         "complaint_index": r["index_negative"], "request_index": r["index_request"]}
        for (f, m, k), r in cells.iterrows() if f == name] if name in cells.index.get_level_values(0) else []
    return jsonable(card)


# ---------------------------------------------------------------------- decision
class EvaluateRequest(BaseModel):
    idea: str = ""
    features: list[str] | None = None
    policy: dict | None = None
    models: list[str] | None = None
    markets: list[str] | None = None


@app.post("/api/resolve")
def resolve(req: EvaluateRequest):
    return jsonable(STATE["engine"].resolve_idea(req.idea))


@app.post("/api/evaluate")
def evaluate(req: EvaluateRequest):
    if not req.idea.strip() and not req.features:
        raise HTTPException(400, "Give an idea or a list of features.")
    return jsonable(STATE["engine"].evaluate(req.idea, req.features, req.policy, req.models, req.markets))


@app.get("/api/policy")
def policy():
    return jsonable({"default": DEFAULT_POLICY, "markets": MARKETS})


class DecisionRequest(BaseModel):
    pm: str = Field(min_length=1)
    idea: str
    feature: str
    decision: str
    rationale: str = Field(min_length=3)
    system_recommendation: dict | None = None
    policy: dict | None = None
    policy_hash: str
    data_hash: str


@app.get("/api/decisions")
def decisions():
    return jsonable(read_decisions())


@app.post("/api/decisions")
def add_decision(req: DecisionRequest):
    try:
        return jsonable(record_decision(req.model_dump()))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------- classify
class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1)
    model: str | None = None
    engine: str | None = None


@app.post("/api/classify")
def classify(req: ClassifyRequest):
    from .classifier import _tier_lookup, predict
    cat = STATE["catalog"]
    cars, lookup = None, None
    if req.model and req.engine:
        fit, var = cat["fitment"], cat["variants"]
        covered = set(map(tuple, fit[["model", "variant"]].drop_duplicates()
                          .merge(var[["model", "variant", "engine"]])[["model", "engine"]].drop_duplicates().values))
        lookup = _tier_lookup(cat["feature_fitment_by_engine"], covered)
        cars = [(req.model, req.engine)]
    pred = predict([req.text], cars=cars, fitment_lookup=lookup)[0]
    ctx = STATE["ctx"]
    cards = [ctx.feature_card(f) for f, _ in pred["feature"][:2] if f in ctx.features.index]
    return jsonable({"text": req.text, "prediction": pred, "cards": cards})


# ---------------------------------------------------------------------- price lists
@app.get("/api/catalog")
def catalog():
    cat = STATE["catalog"]
    v = cat["variants"]
    fit = cat["fitment"]
    covered = set(zip(fit["model"], fit["variant"]))
    out = []
    for m in config.MODELS:
        vm = v[v["model"] == m].copy()
        vm["in_equipment_tables"] = [(m, x) in covered for x in vm["variant"]]
        stats = cat["page_stats"][cat["page_stats"]["model"] == m]
        out.append({"model": m, "name": config.MODEL_NAMES[m], "file": config.OPTION_LIST_FILES[m].name,
                    "variants": _records(vm), "pages": _records(stats),
                    "items": int((cat["option_items"]["model"] == m).sum())})
    quality = _json("data_quality.json") or {}
    return jsonable({"models": out, "validation": quality.get("option_catalog")})


@app.get("/api/catalog/{model}/items")
def catalog_items(model: str, page_type: str | None = None):
    cat = STATE["catalog"]
    items = cat["option_items"][cat["option_items"]["model"] == model]
    if page_type:
        items = items[items["page_type"] == page_type]
    fit = cat["fitment"][cat["fitment"]["item_id"].isin(items["item_id"])]
    variants = cat["variants"][cat["variants"]["model"] == model]
    cols = [v for v in variants["variant"] if v in set(cat["fitment"].loc[cat["fitment"]["model"] == model, "variant"])]
    links = cat["feature_option_links"]
    linked = links.groupby("item_id")["feature"].apply(lambda s: sorted(set(s))).to_dict()
    rows = []
    for it in items.itertuples():
        f = fit[fit["item_id"] == it.item_id]
        cells = {}
        for r in f.itertuples():
            prev = cells.get(r.variant)
            cell = {"status": r.status, "price_eur": r.price_eur, "price_condition": r.price_condition}
            if prev is None or (prev["status"] != "standard" and (
                    r.status == "standard" or (r.price_eur or 1e12) < (prev["price_eur"] or 1e12))):
                cells[r.variant] = cell
        rows.append({"item_id": it.item_id, "page": it.page, "page_type": it.page_type, "section": it.section,
                     "name": it.name, "sa_code": it.sa_code, "description": it.description,
                     "contents": it.contents, "conditions": it.conditions, "cells": cells,
                     "linked_features": linked.get(it.item_id, [])})
    return jsonable({"model": model, "variants": cols, "items": rows})


@app.get("/api/catalog/{model}/technical")
def catalog_technical(model: str):
    cat = STATE["catalog"]
    t = cat["technical"][cat["technical"]["model"] == model]
    variants = list(dict.fromkeys(t["variant"]))
    rows = []
    for (block, group, attr), g in t.groupby(["block", "group", "attribute"], sort=False, dropna=False):
        rows.append({"block": block, "group": group, "attribute": attr, "page": int(g["page"].iloc[0]),
                     "values": {r.variant: r.value for r in g.itertuples()}})
    prices = cat["price_specs"][cat["price_specs"]["model"] == model]
    price_rows = []
    for (block, attr), g in prices.groupby(["block", "attribute"], sort=False, dropna=False):
        price_rows.append({"block": block, "attribute": attr, "page": int(g["page"].iloc[0]),
                           "values": {r.variant: r.value for r in g.itertuples()}})
    return jsonable({"model": model, "variants": variants, "rows": rows, "price_rows": price_rows})


# ---------------------------------------------------------------------- markets
@app.get("/api/markets")
def markets():
    engine, ctx = STATE["engine"], STATE["ctx"]
    sales = engine.sales.rename(columns={"market_code": "market"})
    fb = ctx.labels.drop_duplicates("comment_id").groupby(["model", "market"]).size().rename("comments").reset_index()
    rep = pd.read_csv(config.REPORTS_DIR / "market_representativeness.csv")
    survey = []
    for (market, model), g in engine.survey_eu_cn.groupby(["market", "model"]):
        survey.append({"sheet": "CN_EU_2025", "market": market, "model": model, "attributes": int(len(g))})
    for model, g in engine.survey_us.groupby("model"):
        survey.append({"sheet": "US_2025", "market": "US", "model": model, "attributes": int(len(g))})
    return jsonable({"sales": _records(sales[["model_group", "market", "year", "volume"]]),
                     "feedback": _records(fb), "representativeness": _records(rep), "survey": survey,
                     "survey_eu_cn": _records(engine.survey_eu_cn), "survey_us": _records(engine.survey_us)})


# ---------------------------------------------------------------------- method & audit
@app.get("/api/method")
def method():
    from . import risk_model
    ablation = _json("model_ablation.json") or {}
    metrics = _json("classifier_metrics.json") or {}
    quality = _json("data_quality.json") or {}
    for k in ("global_production", "global_audit_with_pdf"):
        if k in ablation.get("complaint_risk_ebm", {}):
            for term in ablation["complaint_risk_ebm"][k]:
                term["shape"] = term["shape"][:60]
    return jsonable({"classifier": {t: {k: v for k, v in m.items() if k not in ("per_label_f1", "support")}
                                    for t, m in metrics.get("tasks", {}).items()},
                     "n_training_comments": metrics.get("n_training_comments"),
                     "ablation": ablation, "tier_labels": risk_model.TIER_LABELS, "quality": quality,
                     "policy": DEFAULT_POLICY,
                     "thresholds": {"min_mentions": config.MIN_MENTIONS_FOR_VERDICT, "bad_index": config.BAD_INDEX,
                                    "good_index": config.GOOD_NEG_INDEX, "lean_bad": config.LEAN_BAD_INDEX,
                                    "lean_good": config.LEAN_GOOD_NEG_INDEX, "request_index": config.REQUEST_INDEX,
                                    "prior_strength": config.PRIOR_STRENGTH}})


@app.get("/api/health")
def health():
    return {"ok": "engine" in STATE}


# ---------------------------------------------------------------------- agents (idea evaluation)
class InterpretRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=2000)


class AgentEvaluateRequest(BaseModel):
    spec: dict
    policy: dict | None = None


class ExplainRequest(BaseModel):
    evaluation_id: str
    force: bool = False


def _llm_http_error(e: Exception) -> HTTPException:
    from .agents.llm import LLMOutputInvalid, LLMUnavailable, ModelUnavailable
    if isinstance(e, LLMUnavailable):
        return HTTPException(503, {"code": "llm_unavailable", "message": str(e)})
    if isinstance(e, ModelUnavailable):
        return HTTPException(503, {"code": "model_unavailable", "message": str(e)})
    if isinstance(e, LLMOutputInvalid):
        return HTTPException(502, {"code": "llm_output_invalid", "message": f"{e} ({'; '.join(e.errors[:3])})"})
    return HTTPException(502, {"code": "llm_error", "message": str(e)})


@app.get("/api/agent/status")
def agent_status(check: bool = False):
    from .agents.llm import LLMError
    try:
        return jsonable(STATE["pipeline"].status(check=check))
    except LLMError as e:
        raise _llm_http_error(e)


@app.post("/api/agent/interpret")
def agent_interpret(req: InterpretRequest):
    if not req.idea.strip():
        raise HTTPException(400, "Describe the idea to evaluate.")
    return jsonable(STATE["pipeline"].interpret(req.idea))


@app.post("/api/agent/evaluate")
def agent_evaluate(req: AgentEvaluateRequest):
    from pydantic import ValidationError
    try:
        return jsonable(STATE["pipeline"].evaluate(req.spec, req.policy))
    except ValidationError as e:
        raise HTTPException(422, [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()])


@app.post("/api/agent/explain")
def agent_explain(req: ExplainRequest):
    from .agents.llm import LLMError
    from .agents.pipeline import UnknownEvaluation
    try:
        return jsonable(STATE["pipeline"].explain(req.evaluation_id, force=req.force))
    except UnknownEvaluation:
        raise HTTPException(404, "Unknown evaluation; run the evaluation again.")
    except LLMError as e:
        raise _llm_http_error(e)


@app.get("/api/graph/schema")
def graph_schema():
    meta = STATE["pipeline"].graph_meta
    return jsonable({k: meta.get(k) for k in ("n_nodes", "n_edges", "node_types", "edge_types", "checks", "built_at",
                                               "not_in_graph")})


@app.get("/api/graph/full")
def graph_full():
    """Every node with a precomputed position and every edge, for the full-screen "Entire graph" view."""
    from .graph.layout import overview
    pipe = STATE["pipeline"]
    return JSONResponse(overview(pipe.g, pipe.graph_meta))


@app.get("/api/graph/node/{node_id:path}")
def graph_node(node_id: str):
    from .graph.store import node_view
    view = node_view(STATE["pipeline"].g, node_id)
    if view is None:
        raise HTTPException(404, f"No node {node_id!r} in the knowledge graph.")
    return jsonable(view)


# ---------------------------------------------------------------------- competitors (Agents 4 + 5)
class CompareRequest(BaseModel):
    series: list[str] = Field(default_factory=list)       # empty = all series
    markets: list[str] = Field(default_factory=list)      # empty = all markets
    features: list[str] = Field(default_factory=list, max_length=10)
    idea: str = Field(default="", max_length=2000)
    move: str = ""


class CompetitorAnalyseRequest(BaseModel):
    competition_id: str
    force: bool = False


@app.get("/api/competitors/status")
def competitors_status():
    return jsonable(STATE["competition"].status())


@app.post("/api/competitors/compare")
def competitors_compare(req: CompareRequest):
    """BMW vs its top five competitors per series x market in scope, with the facts (deterministic, no LLM)."""
    return jsonable(STATE["competition"].compare(req.series, req.markets, req.features, req.idea, req.move))


@app.post("/api/agent/competitors")
def agent_competitors(req: CompetitorAnalyseRequest):
    from .agents.llm import LLMError
    try:
        return jsonable(STATE["competition"].analyse(req.competition_id, force=req.force))
    except KeyError:
        raise HTTPException(404, "Unknown competitor comparison; load the comparison again.")
    except LLMError as e:
        raise _llm_http_error(e)


# ---------------------------------------------------------------------- frontend
if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = FRONTEND / path
        if path and target.is_file() and FRONTEND in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(FRONTEND / "index.html")
