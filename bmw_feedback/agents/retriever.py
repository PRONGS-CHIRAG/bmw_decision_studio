"""Agent 1 - Retriever: free-text idea -> validated IdeaSpec grounded in the knowledge graph.

Candidates are found by code only:
    - feature names, aliases and fuzzy names, plus the trained feature classifier
      (DecisionEngine.resolve_idea - the same matching the decision engine uses);
    - the semantic index over the features' graph neighbourhoods.
The LLM (OPENAI_RETRIEVER_MODEL) only chooses among those candidates and reads
the scope (series, markets, move, price) out of the text. Its answer is
validated by IdeaSpec with the candidate names as context; a rejected answer is
sent back with the validation errors, up to MAX_ATTEMPTS times. Without an API
key, or if every attempt fails validation, transparent rules are used and the
result says so.
"""

import re

from pydantic import ValidationError

from .contracts import MAX_FEATURES, Candidate, FeaturePick, IdeaSpec, IdeaSpecLLM, InterpretResult
from .llm import LLMError, LLMOutputInvalid

MAX_ATTEMPTS = 3
MAX_CANDIDATES = 12

INSTRUCTIONS = """You are the retrieval agent of BMW's product-idea evaluator for product managers.
You map the PM's idea onto features that exist in BMW's customer-feedback knowledge graph and read the scope of the idea.

Rules:
- features: choose ONLY from the CANDIDATES list and copy the names exactly. Pick the features the idea is actually about (at most 3), most relevant first. If no candidate is about the same thing, return an empty list.
- novelty: 'matches_existing' if you chose features that are the idea's subject; 'related_only' if you chose features that are only adjacent to the idea; 'new_to_data' if you chose none.
- series: F70 = 1 Series, G60 = 5 Series, G70 = 7 Series. List only series the idea names; empty list if it names none.
- markets: EU = Europe (Germany, UK, France, the Nordics, ...), US = United States, CN = China, RoW = rest of world (Japan, Korea, Australia, Canada, South Africa, ...). Only markets the idea names; empty list if none.
- move: fix_existing (fix or improve something customers already have), make_standard (make it standard equipment), new_option (offer it as an option), price_change (change its price), introduce_on_series (bring it to a series that lacks it), unspecified.
- proposed_price_eur: only a price in euros that the idea states; otherwise null. Do not convert currencies.
- summary: one sentence restating the idea for a PM. Add nothing the idea does not say.
- ambiguities: short notes on what the PM should confirm (e.g. 'No series named; all three will be evaluated')."""


class Retriever:
    def __init__(self, engine, graph, index):
        self.engine, self.g, self.index = engine, graph, index

    # ------------------------------------------------------------------ candidates (code only)
    def candidates(self, idea: str, llm=None) -> tuple[list[Candidate], str, str | None, dict]:
        res = self.engine.resolve_idea(idea)
        found: dict[str, dict] = {}
        for m in res["matches"]:
            key = "classifier" if m["how"] == "text classifier" else "name_or_alias"
            entry = found.setdefault(m["feature"], {"methods": {}, "how": []})
            entry["methods"][key] = max(entry["methods"].get(key, 0.0), round(float(m["score"]), 4))
            entry["how"].append(f"{m['how']} {m['score']:.2f}")
        sem_error = None
        embed, model = None, None
        if llm is not None:
            embed, model = llm.embed, llm.models["embedding"]
        try:
            sem = self.index.search(idea, k=8, embed=embed, model=model)
        except LLMError as e:
            sem_error = f"Embeddings failed ({e}); fell back to TF-IDF."
            sem = self.index.search(idea, k=8)
        for f, s in sem["results"]:
            entry = found.setdefault(f, {"methods": {}, "how": []})
            entry["methods"]["semantic"] = s
            entry["how"].append(f"semantic {s:.2f}")
        feats = self.engine.ctx.features
        out = []
        for f, e in found.items():
            if f not in feats.index:
                continue
            row = feats.loc[f]
            out.append(Candidate(feature=f, node_id=f"feature:{f}", domain=row["domain"], verdict=row["verdict"],
                                 n_comments=int(row["n_comments"]), umbrella=bool(row["is_umbrella"]),
                                 methods=e["methods"], how=e["how"]))
        out.sort(key=lambda c: (-c.methods.get("name_or_alias", 0), -c.methods.get("classifier", 0),
                                -c.methods.get("semantic", 0)))
        return out[:MAX_CANDIDATES], sem["method"], sem_error, res

    # ------------------------------------------------------------------ interpret
    def interpret(self, idea: str, llm=None) -> InterpretResult:
        idea = idea.strip()
        cands, sem_method, sem_error, resolution = self.candidates(idea, llm)
        by_name = {c.feature: c for c in cands}
        attempts = []
        if llm is not None:
            prompt = _prompt(idea, cands)
            for i in range(1, MAX_ATTEMPTS + 1):
                try:
                    draft = llm.parse("retriever", INSTRUCTIONS, prompt, IdeaSpecLLM)
                    spec = _to_spec(idea, draft, by_name, f"llm:{llm.models['retriever']}")
                    attempts.append({"attempt": i, "ok": True, "errors": []})
                    return InterpretResult(spec=spec, candidates=cands, semantic_method=sem_method,
                                           semantic_error=sem_error, method=spec.method, attempts=attempts)
                except (ValidationError, LLMOutputInvalid) as e:
                    errors = (e.errors if isinstance(e, LLMOutputInvalid) else
                              [f"{'.'.join(str(x) for x in err['loc']) or 'spec'}: {err['msg']}" for err in e.errors()])
                    attempts.append({"attempt": i, "ok": False, "errors": errors})
                    prompt = (_prompt(idea, cands) + "\n\nYour previous answer was rejected by validation:\n- "
                              + "\n- ".join(errors) + "\nFix these problems and answer again.")
                except LLMError as e:
                    attempts.append({"attempt": i, "ok": False, "errors": [str(e)]})
                    break
        spec = rules_spec(idea, resolution, by_name)
        if attempts:
            spec.method = "rules (the LLM answer was not usable; see attempts)"
        return InterpretResult(spec=spec, candidates=cands, semantic_method=sem_method, semantic_error=sem_error,
                               method=spec.method, attempts=attempts)


def _prompt(idea: str, cands: list[Candidate]) -> str:
    lines = [f"IDEA: {idea}", "", "CANDIDATES (feature | domain | verdict | comments | how it was found):"]
    for c in cands:
        lines.append(f"- {c.feature} | {c.domain} | '{c.verdict}' | {c.n_comments} comments | {', '.join(c.how)}"
                     + (" | umbrella label (general praise is filed here)" if c.umbrella else ""))
    if not cands:
        lines.append("(none)")
    return "\n".join(lines)


def _to_spec(idea: str, d: IdeaSpecLLM, by_name: dict, method: str) -> IdeaSpec:
    """Validate the LLM's draft against the candidates (raises pydantic.ValidationError)."""
    picks = [{"feature": p.feature, "node_id": f"feature:{p.feature}", "reason": p.reason,
              "methods": by_name[p.feature].methods if p.feature in by_name else {}} for p in d.features]
    data = {"idea": idea, "summary": d.summary, "features": picks, "series": d.series, "markets": d.markets,
            "move": d.move, "proposed_price_eur": d.proposed_price_eur, "novelty": d.novelty,
            "ambiguities": d.ambiguities, "method": method}
    return IdeaSpec.model_validate(data, context={"allowed_features": set(by_name)})


# ---------------------------------------------------------------------- rules (no LLM)
SERIES_PATTERNS = {
    "F70": r"\b(f70|1\s?series|1er|1-series|one series)\b",
    "G60": r"\b(g60|5\s?series|5er|5-series|five series|i5)\b",
    "G70": r"\b(g70|7\s?series|7er|7-series|seven series|i7)\b",
}
MARKET_RULES = {   # (pattern, flags): country words case-insensitive, codes case-sensitive ("us" is a pronoun)
    "EU": [(r"\b(europe|european|germany|german|uk|united kingdom|britain|british|france|french|spain|sweden|"
            r"norway|denmark|finland|italy|latvia)\b", re.I), (r"\bEU\b", 0)],
    "US": [(r"\b(united states|america|american)\b", re.I), (r"\b(US|USA)\b|\bU\.S\.", 0)],
    "CN": [(r"\b(china|chinese)\b", re.I), (r"\bCN\b", 0)],
    "RoW": [(r"\b(rest of (the )?world|japan|korea|australia|canada|south africa)\b", re.I), (r"\bRoW\b", 0)],
}
MOVE_PATTERNS = [
    ("price_change", r"\b(cheaper|pric(?:e|ed|es|ing)|discount\w*|cost less|lower the cost|more expensive)\b"),
    ("make_standard", r"\b(standard|as standard|standard equipment|fit as standard|make it standard)\b"),
    ("fix_existing", r"\b(fix|improve|repair|defect|bug|issue|problem|complain\w*|overheat\w*|broken|fail\w*|"
                     r"unreliable|annoying|hard to use|confusing)\b"),
    ("new_option", r"\b(option|optional|add-on|package)\b"),
    ("introduce_on_series", r"\b(introduce|bring|roll out|launch)\b"),
]
PRICE_RE = re.compile(r"(?:€|\beur\b|\beuros?\b)\s?(\d{1,3}(?:[.,]\d{3})+|\d+)|(\d{1,3}(?:[.,]\d{3})+|\d+)\s?"
                      r"(?:€|\beur\b|\beuros?\b)", re.I)


def rules_spec(idea: str, resolution: dict, by_name: dict) -> IdeaSpec:
    low = idea.lower()
    series = [s for s, p in SERIES_PATTERNS.items() if re.search(p, low)]
    markets = [m for m, rules in MARKET_RULES.items() if any(re.search(p, idea, fl) for p, fl in rules)]
    move = next((mv for mv, p in MOVE_PATTERNS if re.search(p, low)), "unspecified")
    price = None
    pm = PRICE_RE.search(idea)
    if pm:
        raw = (pm.group(1) or pm.group(2)).replace(".", "").replace(",", "")
        price = float(raw) if raw.isdigit() and 0 < float(raw) < 1_000_000 else None
    chosen = [f for f in resolution.get("suggested", []) if f in by_name][:MAX_FEATURES]
    picks = [FeaturePick(feature=f, node_id=f"feature:{f}", reason="matched by name, alias or the feature classifier "
                         "with score >= 0.5", methods=by_name[f].methods) for f in chosen]
    novelty = "matches_existing" if picks else ("related_only" if resolution.get("status") == "related"
                                                else "new_to_data")
    amb = []
    if not series:
        amb.append("No series named; all three series are evaluated.")
    if not markets:
        amb.append("No market named; all four markets are evaluated.")
    if not picks:
        amb.append("No feature matched with a score of 0.5 or more; pick a related feature or treat the idea as new.")
    return IdeaSpec(idea=idea, summary=idea, features=picks, series=series, markets=markets, move=move,
                    proposed_price_eur=price, novelty=novelty, ambiguities=amb, method="rules")

