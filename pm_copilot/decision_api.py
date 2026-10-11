"""Validated HTTP boundary for the integrated feature decision workspace."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import DB_PATH, DERIVATIVES, RAW_DIR, REGIONS
from .taxonomy import FEATURES
from .store import DataNotBuilt

router = APIRouter(prefix="/api/decision", tags=["Decision workspace"])
CRITERIA = ("customer", "future", "delivery", "regional", "experience")
WEIGHTS = dict(zip(CRITERIA, (0.4, 0.2, 0.15, 0.15, 0.1)))
SCENARIOS = ("slow", "baseline", "fast")
Score = Annotated[float, Field(ge=0, le=100)]
Money = Annotated[float, Field(ge=0)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class ContextInput(Input):
    project_id: str = Field(default="default", min_length=1, max_length=120)
    vehicle: str
    launch_year: int = Field(ge=2000, le=2100)
    markets: list[str] = Field(min_length=1, max_length=4)
    powertrain: Literal["BEV", "ICE", "PHEV"] | None = None

    @field_validator("vehicle")
    @classmethod
    def valid_vehicle(cls, value):
        if value not in DERIVATIVES:
            raise ValueError("Select a supported vehicle context")
        return value

    @field_validator("markets")
    @classmethod
    def valid_markets(cls, value):
        if len(value) != len(set(value)) or any(m not in REGIONS for m in value):
            raise ValueError("Select unique supported markets")
        return sorted(value)


class CandidateInput(Input):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    feature: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=500)
    market: str
    action: Literal["improve", "add", "retain", "remove"]
    impact: Score | None = None
    saturation: Annotated[float, Field(gt=0, le=1)] | None = None
    values: dict[str, Score | None] = Field(default_factory=lambda: dict.fromkeys(CRITERIA[1:]))
    scenario_values: dict[str, Score | None] = Field(default_factory=lambda: dict.fromkeys(SCENARIOS))
    development_cost: Money | None = None
    feasibility: Literal["unknown", "reviewed", "assumption", "blocked"] = "unknown"
    assumption_rationale: str = Field(default="", max_length=3000)
    mandatory: bool = False
    dependencies: list[str] = Field(default_factory=list, max_length=16)
    exclusions: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("values")
    @classmethod
    def criteria_known(cls, value):
        if set(value) - set(CRITERIA[1:]):
            raise ValueError("Customer value is calculated server-side; unknown criterion")
        return dict.fromkeys(CRITERIA[1:]) | value

    @field_validator("scenario_values")
    @classmethod
    def scenarios_known(cls, value):
        if set(value) - set(SCENARIOS):
            raise ValueError("Unknown future scenario")
        return dict.fromkeys(SCENARIOS) | value


class SalesAssumption(Input):
    baseline_units: Money | None = None
    delta_implemented: Annotated[float, Field(ge=-1)] | None = None
    delta_omitted: Annotated[float, Field(ge=-1)] | None = None
    baseline_rationale: str = Field(default="", max_length=3000)


class RunConfig(Input):
    weights: dict[str, Annotated[float, Field(ge=0, le=1)]] = Field(default_factory=lambda: dict(WEIGHTS))
    market_weights: dict[str, Annotated[float, Field(ge=0, le=1)]] = Field(default_factory=dict)
    budget: Money | None = None
    currency: str = Field(default="EUR", min_length=1, max_length=12)
    cost_basis: str = Field(default="development investment", min_length=1, max_length=160)
    scenario: Literal["slow", "baseline", "fast"] = "baseline"
    reviewer: str = Field(default="", max_length=150)
    rationale: str = Field(default="", max_length=5000)
    value_floor: Annotated[float, Field(gt=0, le=1)] = 0.85
    sales_assumptions: dict[str, SalesAssumption] = Field(default_factory=dict)

    @field_validator("weights")
    @classmethod
    def valid_weights(cls, value):
        if set(value) != set(CRITERIA) or abs(sum(value.values()) - 1) > 1e-9:
            raise ValueError("All five comparison weights must sum to one")
        return value


class EvidenceRequest(Input):
    context: ContextInput
    features: list[str] = Field(min_length=1, max_length=16)


class ReaderRequest(EvidenceRequest):
    question: str = Field(default="Identify specific customer outcomes and conflicting evidence.", max_length=3000)


class RunRequest(Input):
    context: ContextInput
    candidates: list[CandidateInput] = Field(min_length=1, max_length=16)
    config: RunConfig
    parent_run_id: str | None = None
    evidence_hash: str | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        ids = [c.id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("Candidate IDs must be unique")
        if any(c.market not in self.context.markets for c in self.candidates):
            raise ValueError("Candidate market is outside the selected context")
        for candidate in self.candidates:
            if set(candidate.dependencies + candidate.exclusions) - set(ids):
                raise ValueError("A dependency or exclusion refers to an unknown candidate")
            if candidate.id in candidate.dependencies + candidate.exclusions:
                raise ValueError("A candidate cannot depend on or exclude itself")
        weights = self.config.market_weights
        if weights and (set(weights) != set(self.context.markets) or abs(sum(weights.values()) - 1) > 1e-9):
            raise ValueError("Market weights must cover selected markets and sum to one")
        if set(self.config.sales_assumptions) - set(self.context.markets):
            raise ValueError("Sales assumption is outside the selected markets")
        if not self.config.reviewer or not self.config.rationale:
            raise ValueError("Applying PM planning inputs requires a reviewer and rationale")
        return self


class DecisionRequest(Input):
    portfolio_id: str | None = None
    status: Literal["Approved", "Rejected", "Changes requested"]
    actor: str = Field(min_length=1, max_length=150)
    rationale: str = Field(min_length=3, max_length=5000)
    acknowledge_assumptions: bool = False


class QuestionRequest(Input):
    question: str = Field(min_length=3, max_length=3000)


class ResearchRequest(Input):
    vehicle: str
    feature: str = Field(min_length=1, max_length=200)
    market: str


def _store():
    from .decision_store import DecisionStore

    return DecisionStore(DB_PATH)


def _evidence(context, features):
    from .decision_evidence import build_evidence

    try:
        return build_evidence(context, features)
    except (DataNotBuilt, FileNotFoundError, OSError) as exc:
        raise HTTPException(503, "BMW source data could not be loaded. Check BMW-Data/ and source-file access.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _run(run_id):
    try:
        run = _store().get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run
    except KeyError as exc:
        raise HTTPException(404, "Ranking run not found") from exc


@router.get("/meta")
def meta():
    from .decision_agents import agent_status

    return {
        "vehicles": DERIVATIVES,
        "markets": {r: {"EU": "Europe", "CN": "China", "US": "United States", "RoW": "Rest of World"}[r] for r in REGIONS},
        "features": [{"key": f.key, "label": f.label} for f in FEATURES],
        "criteria": CRITERIA,
        "weights": WEIGHTS,
        "scenarios": SCENARIOS,
        "default_launch_year": datetime.now(timezone.utc).year + 4,
        "agent_status": agent_status(),
        "data_available": RAW_DIR.is_dir(),
        "max_candidates": 16,
    }


@router.post("/evidence")
def evidence(body: EvidenceRequest):
    return _evidence(body.context.model_dump(), body.features)


@router.post("/read")
def read(body: ReaderRequest):
    from .decision_agents import AgentUnavailable, read_evidence

    try:
        return read_evidence(_evidence(body.context.model_dump(), body.features), body.question)
    except AgentUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc), "claims": [], "unknowns": [], "review_required": True}


def _sales(config):
    out = {}
    for market, assumption in config.get("sales_assumptions", {}).items():
        baseline = assumption.get("baseline_units")
        implemented = assumption.get("delta_implemented")
        omitted = assumption.get("delta_omitted")
        if None in (baseline, implemented, omitted) or not assumption.get("baseline_rationale"):
            out[market] = {"status": "unknown", "label": "scenario evaluation", "reason": "A baseline, both effect assumptions and their rationale are required."}
        else:
            out[market] = {
                "status": "evaluated", "label": "scenario evaluation", "assumptions": assumption,
                "if_implemented": round(baseline * (1 + implemented), 2),
                "if_omitted": round(baseline * (1 + omitted), 2),
                "difference": round(baseline * (implemented - omitted), 2),
                "note": "Conditional PM assumptions, not a forecast or an effect estimated from feedback.",
            }
    return out


@router.post("/runs")
def create_run(body: RunRequest):
    from .decision_core import build_run

    context = body.context.model_dump()
    queries = list(dict.fromkeys(c.feature for c in body.candidates))
    pack = _evidence(context, queries)
    if body.evidence_hash and body.evidence_hash != pack["evidence_hash"]:
        raise HTTPException(409, "Evidence changed. Reload the evidence before applying these inputs.")
    by_id = {feature["id"]: feature for feature in pack["features"]}
    by_query = {query: by_id[pack["feature_queries"][query]] for query in queries}
    candidates = []
    identities = set()
    for item in body.candidates:
        row = item.model_dump()
        feature = by_query[item.feature]
        region = feature["markets"][item.market]
        identity = (feature["id"], item.market, item.action)
        if identity in identities:
            raise HTTPException(422, "Duplicate feature/action/market would double-count customer value")
        identities.add(identity)
        count_key = {"improve": "complaints", "add": "requests", "retain": "praise"}.get(item.action)
        row.update({
            "title": item.title or f"{item.action.title()} {feature['label']} · {item.market}",
            "feature_id": feature["id"],
            "support_count": region["counts"].get(count_key) if count_key else None,
            "sample_size": region["sample"]["n"],
            "evidence_ids": region.get("support", {}).get(item.action, []),
            "evidence_readiness": "Direct sample evidence" if region["direct_evidence_ids"] else "No direct evidence",
        })
        candidates.append(row)
    for row in candidates:
        siblings = [c["id"] for c in candidates if c["id"] != row["id"] and c["feature_id"] == row["feature_id"] and c["market"] == row["market"]]
        row["exclusions"] = sorted(set(row["exclusions"] + siblings))
    config = body.config.model_dump()
    if not config["market_weights"]:
        config["market_weights"] = {m: 1 / len(context["markets"]) for m in context["markets"]}
    try:
        run = build_run(context, candidates, config, pack["source_hashes"])
        run["evidence"] = pack
        run["evidence_hash"] = pack["evidence_hash"]
        run["sales_scenarios"] = _sales(config)
        run["changes"] = {"added": [], "removed": [], "score_changes": []}
        if body.parent_run_id:
            previous = _run(body.parent_run_id)
            if previous["context"]["project_id"] != context["project_id"]:
                raise ValueError("The parent run belongs to another project")
            old = previous.get("candidate_scores", {})
            new = run["candidate_scores"]
            run["changes"] = {
                "added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new)),
                "score_changes": [{"id": key, "before": old[key].get("score"), "after": new[key].get("score")}
                                  for key in sorted(set(new) & set(old)) if old[key].get("score") != new[key].get("score")],
            }
        return _store().save_run(run, parent_run_id=body.parent_run_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/runs")
def runs(project_id: str = "default", limit: int = Query(default=30, ge=1, le=100)):
    return _store().list_runs(project_id=project_id, limit=limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run = _run(run_id)
    run["decisions"] = _store().history(run_id=run_id)
    return run


@router.post("/runs/{run_id}/decisions")
def decision(run_id: str, body: DecisionRequest):
    try:
        return _store().decide(run_id, body.portfolio_id, body.status, body.actor, body.rationale,
                               acknowledge_assumptions=body.acknowledge_assumptions)
    except KeyError as exc:
        raise HTTPException(404, "Run or portfolio not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/decisions/{event_id}/export")
def export_decision(event_id: str):
    try:
        package = _store().export_decision(event_id)
    except KeyError as exc:
        raise HTTPException(404, "Decision not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    payload = json.dumps(package, ensure_ascii=False, indent=2, allow_nan=False)
    safe_id = hashlib.sha256(str(event_id).encode()).hexdigest()[:12]
    return Response(payload, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="decision-{safe_id}.json"'})


@router.post("/runs/{run_id}/questions")
def question(run_id: str, body: QuestionRequest):
    from .decision_agents import AgentUnavailable, explain_run

    run = _run(run_id)
    run["decisions"] = _store().history(run_id=run_id)
    try:
        return explain_run(run, body.question)
    except AgentUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc), "answer": "Decision explainer unavailable. Stored calculations and evidence remain available.", "claims": [], "assumptions": [], "proposed_change": None}


@router.post("/research")
def research(body: ResearchRequest):
    from .decision_agents import AgentUnavailable, public_research

    if body.vehicle not in DERIVATIVES or body.market not in REGIONS:
        raise HTTPException(422, "Select a supported vehicle and market")
    feature = next((f for f in FEATURES if body.feature in (f.key, f.label)), None)
    if feature is None:
        raise HTTPException(422, "Select a catalog feature for public research; private free text is never sent to search")
    try:
        return public_research(DERIVATIVES[body.vehicle]["name"], feature.label, body.market)
    except AgentUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc), "claims": [], "unknowns": [], "review_required": True}
