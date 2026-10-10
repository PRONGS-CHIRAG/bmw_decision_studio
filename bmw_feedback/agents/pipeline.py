"""Orchestrates the three agents around the decision engine.

    interpret(idea)            Agent 1 -> IdeaSpec + candidates             (PM confirms / edits)
    evaluate(spec, policy)     DecisionEngine -> FactBundle + evidence subgraph   (no LLM, instant)
    explain(evaluation_id)     Agent 2 writes -> Agent 3 verifies -> one rewrite -> strip what still fails
"""

import threading
import time
from collections import OrderedDict

from .. import config
from ..decision import MARKETS, merge_policy, policy_hash
from ..graph.semantic import SemanticIndex
from ..graph.store import get_graph
from . import explainer, verifier
from .contracts import SECTIONS, Explanation, IdeaSpec, VerificationReport
from .evidence import subgraph
from .facts import build_bundle, evaluation_id
from .llm import LLMUnavailable, from_env, model_config
from .retriever import Retriever

MAX_CACHED = 64


class UnknownEvaluation(LookupError):
    """The evaluation id is not (or no longer) in the cache."""

NO_KEY = ("No OpenAI API key is configured, so the explanation and verification agents cannot run. Set "
          "OPENAI_API_KEY in the environment or in a .env file in the repository root, then try again. The "
          "evidence above comes from the decision engine and does not need the key.")


class Pipeline:
    def __init__(self, engine, llm="env"):
        self.engine = engine
        self.g, self.graph_meta = get_graph()
        self.index = SemanticIndex(self.g)
        self.retriever = Retriever(engine, self.g, self.index)
        self._env_llm = llm == "env"
        self.llm = from_env() if self._env_llm else llm
        self.feature_names = set(engine.ctx.features.index)
        self._evals: OrderedDict = OrderedDict()
        self._candidates: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def _current_llm(self):
        """Pick up a key added to the environment or .env after start-up."""
        if self.llm is None and self._env_llm:
            self.llm = from_env()
        return self.llm

    # ------------------------------------------------------------------ status
    def status(self, check: bool = False) -> dict:
        llm = self._current_llm()
        out = {"llm_configured": llm is not None, "provider": "openai",
               "models": llm.models if llm else model_config(),
               "graph": {"nodes": self.graph_meta["n_nodes"], "edges": self.graph_meta["n_edges"],
                         "built_at": self.graph_meta["built_at"],
                         "checks_passed": all(c["ok"] for c in self.graph_meta["checks"]),
                         "n_checks": len(self.graph_meta["checks"])},
               "message": None if llm else NO_KEY}
        if llm is not None and check:
            out["availability"] = llm.check_models(refresh=True)
        return out

    # ------------------------------------------------------------------ Agent 1
    def interpret(self, idea: str) -> dict:
        res = self.retriever.interpret(idea, self._current_llm())
        with self._lock:
            self._candidates[res.spec.idea] = res.candidates
            while len(self._candidates) > MAX_CACHED:
                self._candidates.popitem(last=False)
        return res.model_dump()

    # ------------------------------------------------------------------ engine + facts
    def evaluate(self, spec_data: dict, policy: dict | None = None) -> dict:
        spec = IdeaSpec.model_validate(spec_data, context={"allowed_features": self.feature_names})
        models = list(spec.series) or None
        markets = list(spec.markets) or None
        if spec.features:
            result = self.engine.evaluate("", [f.feature for f in spec.features], policy, models, markets)
            result["idea"] = spec.idea
        else:
            pol = merge_policy(policy)
            result = {"idea": spec.idea, "resolution": None, "features": [], "status": "no_direct_evidence",
                      "policy": pol, "policy_hash": policy_hash(pol), "data_hash": self.engine.fingerprint["hash"],
                      "models": models or list(config.MODELS), "markets": markets or list(MARKETS)}
        with self._lock:
            candidates = self._candidates.get(spec.idea)
        if candidates is None:
            candidates = self.retriever.candidates(spec.idea, self._current_llm())[0]
        eid = evaluation_id(spec, result["policy_hash"], result["data_hash"])
        bundle = build_bundle(self.engine, self.g, spec, result, candidates, eid)
        graph = subgraph(self.g, spec, result, bundle, candidates)
        with self._lock:
            prev = self._evals.get(eid)
            self._evals[eid] = {"spec": spec, "result": result, "bundle": bundle,
                                "explained": prev["explained"] if prev else None}
            self._evals.move_to_end(eid)
            while len(self._evals) > MAX_CACHED:
                self._evals.popitem(last=False)
        return {"evaluation_id": eid, "spec": spec.model_dump(), "result": result,
                "facts": [f.model_dump() for f in bundle.facts], "graph": graph,
                "candidates": [c.model_dump() for c in candidates]}

    # ------------------------------------------------------------------ Agents 2 + 3
    def explain(self, eid: str, force: bool = False) -> dict:
        with self._lock:
            entry = self._evals.get(eid)
        if entry is None:
            raise UnknownEvaluation(eid)
        if entry["explained"] and not force:
            return entry["explained"]
        llm = self._current_llm()
        if llm is None:
            raise LLMUnavailable(NO_KEY)
        t0 = time.time()
        spec, bundle = entry["spec"], entry["bundle"]
        claims = verifier.verify(explainer.to_claims(explainer.write(llm, bundle, spec), 1), bundle, llm)
        rewritten, attempts = [], 1
        if any(c.status == "removed" for c in claims):
            rewritten = [c for c in claims if c.status == "removed"]
            draft = explainer.write(llm, bundle, spec, feedback=rewritten)
            claims = verifier.verify(explainer.to_claims(draft, 2), bundle, llm)
            attempts = 2
        sections = {s: [c for c in claims if c.section == s and c.status == "verified"] for s in SECTIONS}
        explanation = Explanation(evaluation_id=eid, model=llm.models["explainer"], sections=sections,
                                  attempts=attempts)
        report = VerificationReport(evaluation_id=eid, rules=verifier.RULES, semantic_model=llm.models["verifier"],
                                    claims=claims, rewritten=rewritten,
                                    n_verified=sum(c.status == "verified" for c in claims),
                                    n_removed=sum(c.status == "removed" for c in claims))
        out = {"explanation": explanation.model_dump(), "verification": report.model_dump(),
               "seconds": round(time.time() - t0, 1)}
        entry["explained"] = out
        return out
