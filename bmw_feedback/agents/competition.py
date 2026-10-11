"""Agents 4 + 5: competitor analysis and its presentation for the report's price & equipment section.

    CompetitionService.compare(series, markets, features)   CompetitorEngine -> facts (no LLM, instant)
    CompetitionService.analyse(competition_id)               Agent 4 analyst -> verifier -> one rewrite -> strip
                                                              Agent 5 presenter -> verifier -> analyst fallback

Agent 4 (OPENAI_ANALYST_MODEL) compares BMW with its top five competitors per series x market and writes findings,
each citing competitor fact IDs; it runs once per series (in parallel) on that series' facts. The verifier's rules
(citations, numbers, labels, quotes, series/market scope), two extra rules (the finding's series and market match
its facts; it cites a fact of its dimension) and the semantic judge check every finding. Failing findings go back
once and are removed if they still fail.

Agent 5 (OPENAI_PRESENTER_MODEL) turns the verified findings into a short plain-language brief. Its sentences are
verified the same way; a sentence that fails is replaced by the verified finding(s) it was based on, so nothing
unverified is shown and nothing verified is lost.
"""

import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .. import config
from ..competitors import registry as CR
from ..competitors.engine import CompetitorEngine
from ..competitors.facts import build_bundle, competition_id
from . import verifier
from .contracts import (BRIEF_SECTIONS, DIMENSION_GROUPS, Check, CompetitorAnalysisLLM, CompetitorBriefLLM, FactBundle,
                        Finding, PresentedClaim)
from .llm import LLMOutputInvalid, LLMUnavailable

MAX_CACHED = 64
NO_KEY = ("No OpenAI API key is configured, so the competitor analysis and presentation agents cannot run. The "
          "comparison tables come straight from the collected data and do not need the key.")
SERIES_NAMES = {"F70": "1 Series (F70)", "G60": "5 Series (G60)", "G70": "7 Series (G70)"}

ANALYST_INSTRUCTIONS = """You are the competitor analysis agent of BMW's product-idea evaluator. Your reader is a BMW product manager who is evaluating an idea for the 1 Series (F70), 5 Series (G60) or 7 Series (G70) and wants to know how BMW stands against its competitors.

You receive FACTS, one per line as "ID | statement", computed from public web data (sales, list prices, technical data, German-market equipment, ratings and classified review statements) and from BMW's own German price list. For each series and market they name the top five competitors and compare them with BMW. They are your only source of truth.

Write findings that compare BMW with its competitors. For every series and market that has a competitor set in the facts, write 3 to 7 findings, choosing the dimensions that matter most for the IDEA:
- selection: who the main rivals are and why (sales);
- price: where BMW's entry price sits against the rivals (rank, gaps, powertrain prices);
- equipment: how the rivals offer the equipment the idea is about, against BMW (German market);
- product: notable differences in power, size, boot or electric range;
- sales: BMW's volume against the rivals in the same source;
- customers: ratings from the same publisher and the topics reviewers praise or criticise.
Each finding is one sentence with its series, market and dimension.

Rules - a verifier checks every finding and deletes those that break them:
1. fact_ids lists every fact whose number, name, label, quote, series or market the finding uses. Cite at least one fact of the finding's series and market, and one of its dimension.
2. Use only numbers written in the cited facts, at the same or fewer decimals. Never add, subtract, average, convert or count yourself; the facts already state gaps, percentages and ranks.
3. Make the direction explicit: say which car is cheaper, more powerful, sells more, or offers the equipment as standard.
4. Put words in double quotes only when copied exactly from a cited quote fact.
5. Name a series or market only when a cited fact is about it. Write '1 Series (F70)', '5 Series (G60)', '7 Series (G70)', 'Europe', 'United States', 'China', 'Rest of world'. Name competitors as the facts do.
6. No causes, forecasts or general knowledge the facts do not state. Where data is missing or not comparable, say so plainly instead of guessing.
7. Short, direct sentences. No filler, no marketing language."""

PRESENTER_INSTRUCTIONS = """You are the presentation agent of BMW's product-idea evaluator. You turn the competitor analyst's verified FINDINGS into a short, plain-language brief that sits next to the price and equipment section of a report for a busy BMW product manager.

You receive the IDEA, the verified FINDINGS ("ID | series | market | dimension | text | cited facts") and the FACTS they cite ("ID | statement").

Write:
- headline: one sentence on how BMW stands against its competitors for this idea.
- price_position: 1-3 sentences on BMW's price against the rivals.
- equipment: 1-3 sentences on how the rivals offer the equipment the idea is about, against BMW (say when the facts have no equipment data for it).
- product_and_sales: 0-3 sentences on product and sales differences that matter for the idea.
- customer_view: 0-2 sentences on what ratings and reviewers say about the rivals.
- implications: 1-3 sentences on what the comparison means for the idea - only what the findings support; phrase them as points to weigh, not forecasts.
- caveats: 1-2 sentences on the limits of this comparison.

Rules - a verifier checks every sentence; one that fails is replaced by the analyst's original finding:
1. Restate the findings in plain words; do not add facts. For each sentence list in finding_ids the findings it restates or combines, and in fact_ids every fact whose number, name, label, quote, series or market it uses.
2. Use only numbers written in the cited facts, at the same or fewer decimals. Never compute.
3. Name a series or market only when a cited fact is about it ('1 Series (F70)', '5 Series (G60)', '7 Series (G70)', 'Europe', 'United States', 'China', 'Rest of world').
4. Double quotes only for words copied exactly from a cited quote fact.
5. Plain words: no jargon, no marketing language, one idea per sentence."""


# ---------------------------------------------------------------------- helpers
def model_names(comparison: dict) -> tuple:
    """Competitor names with digits ('DS Automobiles DS 4', 'DS 4', 'Avatr 12'), for the numbers rule to skip.
    A model name made of digits only ('12', '001') is skipped only together with its brand."""
    out = set()
    for t in comparison.get("tuples", []):
        for c in t.get("competitors", []):
            for n in (c.get("name"), f"{c.get('brand') or ''} {c.get('model') or ''}".strip()):
                if n and re.search(r"\d", n):
                    out.add(n)
            m = c.get("model") or ""
            if re.search(r"\d", m) and re.search(r"[A-Za-z]", m):
                out.add(m)
    return tuple(sorted(out))


def _lines(facts) -> str:
    return "\n".join(f"{f.id} | {f.statement}" for f in facts)


def _facts_for(bundle: FactBundle, series: str) -> list:
    """The facts of one series plus the shared ones (data version, caveats, features without equipment data)."""
    return [f for f in bundle.facts if f.series == series or f.series is None]


def _scope_text(scope: dict) -> str:
    feats = ", ".join(scope.get("features") or []) or "none (no matching feature)"
    return (f"IDEA: {scope.get('idea') or '(not given)'}\nSCOPE: features {feats}; series "
            f"{', '.join(scope.get('series') or []) or 'all'}; markets {', '.join(scope.get('markets') or []) or 'all'}; "
            f"move {scope.get('move') or 'unspecified'}.")


def finding_rules(meta: dict):
    """Extra rules for analyst findings: series/market and dimension must match the cited facts."""
    def run(claim, index) -> list[Check]:
        m = meta.get(claim.id) or {}
        cited = [index[i] for i in claim.fact_ids if i in index]
        tuple_ok = any(f.series == m.get("series") and f.market == m.get("market") for f in cited)
        groups = DIMENSION_GROUPS.get(m.get("dimension"), set())
        dim_ok = any(f.group in groups for f in cited)
        return [Check(name="tuple", passed=tuple_ok,
                      detail=(f"Cites a fact of {m.get('series')} {m.get('market')}." if tuple_ok else
                              f"No cited fact is about {m.get('series')} in {m.get('market')}.")),
                Check(name="dimension", passed=dim_ok,
                      detail=(f"Cites a {m.get('dimension')} fact." if dim_ok else
                              f"No cited fact is of the '{m.get('dimension')}' kind ({', '.join(sorted(groups))})."))]
    return run


# ---------------------------------------------------------------------- Agent 4
def analyse_series(llm, bundle: FactBundle, scope: dict, series: str, start: int, names: tuple = ()) -> dict:
    """Analyst for one series: draft, verify, one rewrite of what failed, verify again."""
    facts = _facts_for(bundle, series)
    sub = FactBundle(evaluation_id=bundle.evaluation_id, idea=bundle.idea, facts=facts)
    base = f"{_scope_text(scope)}\nSERIES OF THIS ANALYSIS: {SERIES_NAMES[series]}\n\nFACTS (ID | statement):\n{_lines(facts)}"

    def draft(prompt: str, attempt: int, offset: int) -> tuple[list[Finding], dict]:
        out = llm.parse("analyst", ANALYST_INSTRUCTIONS, prompt, CompetitorAnalysisLLM)
        claims, meta = [], {}
        for f in out.findings:
            if not f.text.strip():
                continue
            cid = f"a{offset + len(claims) + 1}"
            ids = list(dict.fromkeys(i.strip() for i in f.fact_ids if i.strip()))
            claims.append(Finding(id=cid, section=f.dimension, text=f.text.strip(), fact_ids=ids, attempt=attempt,
                                  series=f.series, market=f.market))
            meta[cid] = {"series": f.series, "market": f.market, "dimension": f.dimension}
        return claims, meta

    claims, meta = draft(base, 1, start)
    claims = verifier.verify(claims, sub, llm, extra=finding_rules(meta), names=names)
    rewritten, attempts = [], 1
    failed = [c for c in claims if c.status == "removed"]
    if failed:
        rewritten = failed
        lines = []
        for c in failed:
            why = "; ".join(f"{ch.name}: {ch.detail}" for ch in c.checks if not ch.passed)
            lines.append(f"- [{c.series} {c.market} {c.section}] \"{c.text}\" (cited {', '.join(c.fact_ids) or 'nothing'})"
                         f" -> {why}")
        prompt = (base + "\n\nYOUR PREVIOUS FINDINGS FAILED VERIFICATION FOR THESE. Write all findings again; fix each "
                  "of these so that it follows the rules, or drop it:\n" + "\n".join(lines))
        kept = [c for c in claims if c.status == "verified"]
        again, meta2 = draft(prompt, 2, start + len(claims))
        again = verifier.verify(again, sub, llm, extra=finding_rules(meta2), names=names)
        claims = again if any(c.status == "verified" for c in again) or not kept else again + kept
        attempts = 2
    return {"series": series, "claims": claims, "rewritten": rewritten, "attempts": attempts}


# ---------------------------------------------------------------------- Agent 5
def present(llm, bundle: FactBundle, scope: dict, findings: list[Finding],
            names: tuple = ()) -> tuple[dict, list[PresentedClaim]]:
    index = bundle.index()
    cited = list(dict.fromkeys(i for f in findings for i in f.fact_ids))
    shared = [f.id for f in bundle.facts if f.group == "caveat"]
    facts = [index[i] for i in dict.fromkeys(cited + shared) if i in index]
    flines = "\n".join(f"{f.id} | {f.series} | {f.market} | {f.section} | {f.text} | {', '.join(f.fact_ids)}"
                       for f in findings)
    prompt = (f"{_scope_text(scope)}\n\nFINDINGS (ID | series | market | dimension | text | cited facts):\n{flines}"
              f"\n\nFACTS (ID | statement):\n{_lines(facts)}")
    draft = llm.parse("presenter", PRESENTER_INSTRUCTIONS, prompt, CompetitorBriefLLM)
    if not draft.headline.text.strip():
        raise LLMOutputInvalid("The presenter returned an empty headline.", ["headline.text: empty"])
    by_id = {f.id: f for f in findings}
    claims, n = [], 0
    for section in BRIEF_SECTIONS:
        items = [draft.headline] if section == "headline" else getattr(draft, section)
        for c in items:
            if not c.text.strip():
                continue
            n += 1
            claims.append(PresentedClaim(id=f"p{n}", section=section, text=c.text.strip(),
                                         fact_ids=list(dict.fromkeys(i.strip() for i in c.fact_ids if i.strip())),
                                         finding_ids=[i for i in dict.fromkeys(c.finding_ids) if i in by_id]))
    claims = verifier.verify(claims, bundle, llm, names=names)
    shown: dict[str, list] = {s: [] for s in BRIEF_SECTIONS}
    used: dict[str, set] = {s: set() for s in BRIEF_SECTIONS}          # findings already shown, per section
    for c in claims:
        if c.status == "verified":
            shown[c.section].append(c)
            used[c.section] |= set(c.finding_ids)
    for c in claims:                                   # fall back to the verified findings behind a failed sentence
        if c.status != "removed":
            continue
        for fid in c.finding_ids:
            if fid in used[c.section] or (c.section == "headline" and shown["headline"]):
                continue                               # the headline stays a single sentence
            f = by_id[fid]
            used[c.section].add(fid)
            shown[c.section].append(PresentedClaim(id=f"{c.id}-{fid}", section=c.section, text=f.text,
                                                   fact_ids=f.fact_ids, finding_ids=[fid], origin="analyst_fallback",
                                                   checks=f.checks, attempt=f.attempt))
    return shown, claims


# ---------------------------------------------------------------------- service
class CompetitionService:
    def __init__(self, graph=None, llm_getter=None, ctx=None, parallel: bool = True):
        self.engine = CompetitorEngine()
        self.g = graph
        self.llm_getter = llm_getter or (lambda: None)
        self.ctx = ctx
        self.parallel = parallel
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def status(self) -> dict:
        return self.engine.status()

    def compare(self, series=None, markets=None, features=None, idea: str = "", move: str = "") -> dict:
        series = [s for s in (series or []) if s in config.MODELS]
        markets = [m for m in (markets or []) if m in CR.MARKETS]
        features = list(dict.fromkeys(features or []))
        domains = {}
        if self.ctx is not None:
            domains = {f: str(self.ctx.features.loc[f, "domain"]) for f in features if f in self.ctx.features.index}
        comparison = self.engine.compare(series or None, markets or None, features, domains)
        if not comparison.get("available"):
            return {"competition_id": None, "available": False, "comparison": comparison, "facts": []}
        scope = {"series": series, "markets": markets, "features": features, "idea": idea, "move": move}
        # the idea and the move are part of the key: the agents' text depends on them, the comparison does not
        cid = competition_id({k: scope[k] for k in ("series", "markets", "features", "idea", "move")},
                             comparison["data_hash"])
        bundle, missing = build_bundle(comparison, self.g, cid)
        with self._lock:
            prev = self._cache.get(cid)
            self._cache[cid] = {"scope": scope, "comparison": comparison, "bundle": bundle,
                                "analysed": prev["analysed"] if prev else None}
            self._cache.move_to_end(cid)
            while len(self._cache) > MAX_CACHED:
                self._cache.popitem(last=False)
        return {"competition_id": cid, "available": True, "comparison": comparison,
                "facts": [f.model_dump() for f in bundle.facts], "graph_missing_nodes": len(missing)}

    def analyse(self, cid: str, force: bool = False) -> dict:
        with self._lock:
            entry = self._cache.get(cid)
        if entry is None:
            raise KeyError(cid)
        if entry["analysed"] and not force:
            return entry["analysed"]
        llm = self.llm_getter()
        if llm is None:
            raise LLMUnavailable(NO_KEY)
        t0 = time.time()
        bundle, scope = entry["bundle"], entry["scope"]
        series = [t["series"] for t in entry["comparison"]["tuples"] if t["status"] == "ok"]
        series = list(dict.fromkeys(series))
        if not series:
            out = {"competition_id": cid, "analysis": {"findings": [], "removed": [], "rewritten": [], "attempts": 0,
                                                       "model": llm.models.get("analyst")},
                   "brief": None, "verification": None, "seconds": 0.0,
                   "message": "No series in scope has a competitor set, so there is nothing to analyse."}
            entry["analysed"] = out
            return out
        offsets = {s: i * 100 for i, s in enumerate(series)}
        names = model_names(entry["comparison"])
        if self.parallel and len(series) > 1:
            with ThreadPoolExecutor(max_workers=len(series)) as ex:
                results = list(ex.map(lambda s: analyse_series(llm, bundle, scope, s, offsets[s], names), series))
        else:
            results = [analyse_series(llm, bundle, scope, s, offsets[s], names) for s in series]
        claims = [c for r in results for c in r["claims"]]
        findings = [c for c in claims if c.status == "verified"]
        analysis = {"model": llm.models.get("analyst"), "attempts": max(r["attempts"] for r in results),
                    "findings": [c.model_dump() for c in findings],
                    "removed": [c.model_dump() for c in claims if c.status == "removed"],
                    "rewritten": [c.model_dump() for r in results for c in r["rewritten"]]}
        brief, verification = None, None
        if findings:
            shown, pclaims = present(llm, bundle, scope, findings, names)
            brief = {"model": llm.models.get("presenter"),
                     "sections": {s: [c.model_dump() for c in v] for s, v in shown.items()}}
            verification = {"rules": verifier.RULES + ["tuple", "dimension"], "semantic_model": llm.models.get("verifier"),
                            "presented": [c.model_dump() for c in pclaims],
                            "n_presented_verified": sum(c.status == "verified" for c in pclaims),
                            "n_presented_replaced": sum(c.status == "removed" for c in pclaims),
                            "n_findings_verified": len(findings),
                            "n_findings_removed": len(analysis["removed"])}
        out = {"competition_id": cid, "analysis": analysis, "brief": brief, "verification": verification,
               "seconds": round(time.time() - t0, 1),
               "message": None if findings else "No finding passed verification, so there is no written comparison."}
        entry["analysed"] = out
        return out
