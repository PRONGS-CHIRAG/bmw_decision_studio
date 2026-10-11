"""Pydantic contracts between the three agents, the decision engine and the frontend.

Models ending in `LLM` are what a language model is asked to return. They are
kept free of defaults and dict fields so OpenAI's strict structured outputs
accept them. Everything an LLM returns is then re-validated into the strict
models below with the context it must respect (e.g. the allowed feature names).
"""

from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

Series = Literal["F70", "G60", "G70"]
Market = Literal["EU", "US", "CN", "RoW"]
Move = Literal["fix_existing", "make_standard", "new_option", "price_change", "introduce_on_series", "unspecified"]
Novelty = Literal["matches_existing", "related_only", "new_to_data"]
SERIES: tuple = ("F70", "G60", "G70")
MARKETS: tuple = ("EU", "US", "CN", "RoW")
MAX_FEATURES = 3

MOVE_LABELS = {
    "fix_existing": "Fix or improve what exists",
    "make_standard": "Make it standard equipment",
    "new_option": "Offer it as a new option",
    "price_change": "Change the price",
    "introduce_on_series": "Introduce it on another series",
    "unspecified": "Not specified",
}


# ---------------------------------------------------------------------- Agent 1: retriever
class Candidate(BaseModel):
    """A feature the code (not the LLM) found for the idea, with how it was found."""
    feature: str
    node_id: str
    domain: str
    verdict: str
    n_comments: int
    complaint_index: float | None = None   # observed complaints / expected for the channels (1.0 = typical); drives the verdict
    complaints_observed: int | None = None     # complaint mentions found in the feedback
    complaints_expected: float | None = None   # what a typical topic would get from the same channels
    umbrella: bool
    methods: dict[str, float]          # e.g. {"alias": 1.0, "classifier": 0.42, "semantic": 0.61}
    how: list[str]                     # human-readable match reasons


class FeaturePickLLM(BaseModel):
    feature: str
    reason: str


class IdeaSpecLLM(BaseModel):
    summary: str
    features: list[FeaturePickLLM]
    series: list[Series]
    markets: list[Market]
    move: Move
    proposed_price_eur: float | None
    novelty: Novelty
    ambiguities: list[str]


class FeaturePick(BaseModel):
    feature: str
    node_id: str
    reason: str
    methods: dict[str, float] = Field(default_factory=dict)


class IdeaSpec(BaseModel):
    """What the idea is about, validated against the knowledge graph. Confirmed or edited by the PM."""
    idea: str = Field(min_length=1, max_length=2000)
    summary: str
    features: list[FeaturePick] = Field(default_factory=list, max_length=MAX_FEATURES)
    series: list[Series] = Field(default_factory=list)       # empty = all series
    markets: list[Market] = Field(default_factory=list)      # empty = all markets
    move: Move = "unspecified"
    proposed_price_eur: float | None = None
    novelty: Novelty = "matches_existing"
    ambiguities: list[str] = Field(default_factory=list)
    method: str = "rules"

    @field_validator("proposed_price_eur")
    @classmethod
    def _price_positive(cls, v):
        if v is not None and not (0 < v < 1_000_000):
            raise ValueError("proposed_price_eur must be a positive amount in EUR below 1,000,000")
        return v

    @field_validator("series", "markets")
    @classmethod
    def _unique(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("duplicate entries")
        return v

    @model_validator(mode="after")
    def _graph_consistency(self, info: ValidationInfo):
        allowed = (info.context or {}).get("allowed_features")
        names = [f.feature for f in self.features]
        if len(set(names)) != len(names):
            raise ValueError("a feature is listed twice")
        if allowed is not None:
            unknown = [n for n in names if n not in allowed]
            if unknown:
                raise ValueError(f"features not among the retrieved candidates: {unknown}. "
                                 f"Choose only from: {sorted(allowed)}")
        for f in self.features:
            if f.node_id != f"feature:{f.feature}":
                raise ValueError(f"node_id {f.node_id!r} does not belong to feature {f.feature!r}")
        if self.novelty == "matches_existing" and not self.features:
            raise ValueError("novelty is 'matches_existing' but no feature was chosen")
        if self.novelty == "new_to_data" and self.features:
            raise ValueError("novelty is 'new_to_data' but features were chosen; use 'matches_existing' "
                             "or 'related_only'")
        return self


def _verdict_rule() -> dict[str, float]:
    """The verdict thresholds from config, so the UI can explain a label without restating them."""
    from .. import config
    return {"min_mentions": config.MIN_MENTIONS_FOR_VERDICT, "bad": config.BAD_INDEX, "lean_bad": config.LEAN_BAD_INDEX,
            "good": config.GOOD_NEG_INDEX, "lean_good": config.LEAN_GOOD_NEG_INDEX, "prior_strength": config.PRIOR_STRENGTH}


class InterpretResult(BaseModel):
    spec: IdeaSpec
    candidates: list[Candidate]
    semantic_method: str
    semantic_error: str | None = None
    method: str
    attempts: list[dict]
    verdict_rule: dict[str, float] = Field(default_factory=_verdict_rule)   # thresholds behind the verdict labels


# ---------------------------------------------------------------------- facts (deterministic)
class Provenance(BaseModel):
    node_id: str | None                # knowledge-graph node (or request-time node such as rec:...)
    kind: str                          # table | pdf | xlsx | model | derived | config | engine | pm
    ref: str
    key: str | None = None
    page: int | None = None


class Fact(BaseModel):
    id: str
    group: str
    statement: str
    value: float | int | str | bool | None = None
    unit: str | None = None
    feature: str | None = None
    series: str | None = None
    market: str | None = None
    source: Provenance


class FactBundle(BaseModel):
    evaluation_id: str
    idea: str
    facts: list[Fact]

    def index(self) -> dict:
        return {f.id: f for f in self.facts}


# ---------------------------------------------------------------------- Agent 2: explainer
SECTIONS = ["headline", "customer_evidence", "market_view", "price_and_equipment", "risks_and_caveats", "next_steps"]
SECTION_TITLES = {
    "headline": "Bottom line", "customer_evidence": "What customers say", "market_view": "Where it matters",
    "price_and_equipment": "Price and equipment today", "risks_and_caveats": "Risks and limits of the evidence",
    "next_steps": "Recommended next steps",
}


class ClaimLLM(BaseModel):
    text: str
    fact_ids: list[str]


class ExplanationLLM(BaseModel):
    headline: ClaimLLM
    customer_evidence: list[ClaimLLM]
    market_view: list[ClaimLLM]
    price_and_equipment: list[ClaimLLM]
    risks_and_caveats: list[ClaimLLM]
    next_steps: list[ClaimLLM]

    def claims(self) -> list[ClaimLLM]:
        return [self.headline] + [c for s in SECTIONS[1:] for c in getattr(self, s)]


class Check(BaseModel):
    name: str
    passed: bool
    detail: str


class Claim(BaseModel):
    id: str
    section: str
    text: str
    fact_ids: list[str]
    status: Literal["verified", "removed"] = "verified"
    attempt: int = 1
    checks: list[Check] = Field(default_factory=list)


class Explanation(BaseModel):
    evaluation_id: str
    model: str
    sections: dict[str, list[Claim]]       # section -> verified claims only
    attempts: int


class VerificationReport(BaseModel):
    evaluation_id: str
    rules: list[str]
    semantic_model: str | None
    claims: list[Claim]                    # final claims, verified and removed
    rewritten: list[Claim]                 # claims of the first draft that failed and triggered the rewrite
    n_verified: int
    n_removed: int


class JudgmentLLM(BaseModel):
    claim_id: str
    verdict: Literal["supported", "unsupported"]
    reason: str


class JudgmentsLLM(BaseModel):
    judgments: list[JudgmentLLM]


# ---------------------------------------------------------------------- Agents 4 + 5: competitor analyst, presenter
CompetitorDimension = Literal["selection", "price", "equipment", "product", "sales", "customers"]
COMPETITOR_DIMENSIONS: tuple = ("selection", "price", "equipment", "product", "sales", "customers")
# fact groups a finding of each dimension must cite at least one of
DIMENSION_GROUPS = {"selection": {"set"}, "price": {"price", "summary"}, "equipment": {"equipment"},
                    "product": {"spec"}, "sales": {"sales", "set"}, "customers": {"rating", "reviews", "quote"}}
BRIEF_SECTIONS = ["headline", "price_position", "equipment", "product_and_sales", "customer_view", "implications",
                  "caveats"]
BRIEF_TITLES = {"headline": "In one sentence", "price_position": "Price position", "equipment": "Equipment for this idea",
                "product_and_sales": "Product and sales", "customer_view": "What customers say about the rivals",
                "implications": "What it means for the idea", "caveats": "Limits of this comparison"}


class FindingLLM(BaseModel):
    series: Series
    market: Market
    dimension: CompetitorDimension
    text: str
    fact_ids: list[str]


class CompetitorAnalysisLLM(BaseModel):
    findings: list[FindingLLM]


class Finding(Claim):
    """An analyst finding after verification (section = dimension)."""
    series: str
    market: str


class PresentedClaimLLM(BaseModel):
    text: str
    fact_ids: list[str]
    finding_ids: list[str]


class CompetitorBriefLLM(BaseModel):
    headline: PresentedClaimLLM
    price_position: list[PresentedClaimLLM]
    equipment: list[PresentedClaimLLM]
    product_and_sales: list[PresentedClaimLLM]
    customer_view: list[PresentedClaimLLM]
    implications: list[PresentedClaimLLM]
    caveats: list[PresentedClaimLLM]


class PresentedClaim(Claim):
    finding_ids: list[str] = Field(default_factory=list)
    origin: Literal["presenter", "analyst_fallback"] = "presenter"
