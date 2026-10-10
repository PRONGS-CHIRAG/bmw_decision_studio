"""Agent 2 - Explainer: fact bundle -> a decision brief for a BMW product manager.

The model (OPENAI_EXPLAINER_MODEL) sees only the facts (ID | deterministic
sentence) and the PM's confirmed scope. Every claim it writes must cite fact
IDs; the verifier then checks each claim against those facts.
"""

from .contracts import SECTIONS, Claim, ExplanationLLM, FactBundle, IdeaSpec, MOVE_LABELS
from .facts import fact_lines
from .llm import LLMOutputInvalid

INSTRUCTIONS = """You are the explanation agent of BMW's product-idea evaluator. Your reader is a BMW product manager deciding whether and where to pursue an idea for the 1 Series (F70), 5 Series (G60) and 7 Series (G70).

You receive FACTS, one per line as "ID | statement". They come from processed customer feedback, the 2025 customer studies, sales volumes, the German price lists and the outputs of trained models. They are your only source of truth.

Write a decision brief:
- headline: one sentence with the bottom line - where the idea is worth pursuing, where not, or that the evidence is insufficient.
- customer_evidence: 2-4 claims on what customers say (verdicts, complaint / request indices, top reasons; a short verbatim quote if it helps).
- market_view: 2-4 claims on where it matters by series and market (recommendations, scores, sales volumes, survey ranks).
- price_and_equipment: 1-3 claims on today's fitment and price and what the proposed move implies.
- risks_and_caveats: 1-3 claims on the limits of the evidence (thin or borrowed data, missing markets, caveats).
- next_steps: 1-3 concrete actions the facts motivate.

Rules - a verifier checks every claim and deletes those that break them:
1. Each claim lists in fact_ids every fact whose number, label, quote, series or market it uses.
2. Use only numbers written in the cited facts, at the same or fewer decimals. Never add, subtract, average, convert or count yourself; if you need a count, difference or share, cite the fact that states it.
3. Write recommendation and verdict labels in single quotes exactly as the facts do, e.g. 'Prioritise', 'Leaning bad'.
4. Put a customer's words in double quotes only when copied exactly from a cited comment fact.
5. Name a series or market only when a cited fact is about it. Write '1 Series (F70)', '5 Series (G60)', '7 Series (G70)', 'Europe', 'United States', 'China', 'Rest of world'.
6. No causes, forecasts, competitors or general knowledge the facts do not state. If evidence is thin or missing, say so plainly.
7. Short, direct sentences for a busy manager. No filler, no marketing language. One idea per claim."""


def _scope(spec: IdeaSpec) -> str:
    feats = ", ".join(f.feature for f in spec.features) or "none (no matching feature in the data)"
    return (f"IDEA: {spec.idea}\nPM-CONFIRMED SCOPE: features {feats}; series {', '.join(spec.series) or 'all'}; "
            f"markets {', '.join(spec.markets) or 'all'}; move {MOVE_LABELS[spec.move]}; proposed price "
            f"{'EUR ' + format(spec.proposed_price_eur, ',.0f') if spec.proposed_price_eur else 'none'}.")


def write(llm, bundle: FactBundle, spec: IdeaSpec, feedback: list[Claim] | None = None) -> ExplanationLLM:
    text = f"{_scope(spec)}\n\nFACTS (ID | statement):\n{fact_lines(bundle)}"
    if feedback:
        lines = []
        for c in feedback:
            failed = "; ".join(f"{ch.name}: {ch.detail}" for ch in c.checks if not ch.passed)
            lines.append(f"- [{c.section}] \"{c.text}\" (cited {', '.join(c.fact_ids) or 'nothing'}) -> {failed}")
        text += ("\n\nYOUR PREVIOUS DRAFT FAILED VERIFICATION FOR THESE CLAIMS. Rewrite the whole brief. Fix each claim "
                 "so that it follows the rules, or drop it:\n" + "\n".join(lines))
    draft = llm.parse("explainer", INSTRUCTIONS, text, ExplanationLLM)
    if not draft.headline.text.strip():
        raise LLMOutputInvalid("The explainer returned an empty headline.", ["headline.text: empty"])
    return draft


def to_claims(draft: ExplanationLLM, attempt: int) -> list[Claim]:
    claims, n = [], 0
    for section in SECTIONS:
        items = [draft.headline] if section == "headline" else getattr(draft, section)
        for c in items:
            if not c.text.strip():          # an empty claim says nothing; drop it rather than verify it
                continue
            n += 1
            ids = list(dict.fromkeys(i.strip() for i in c.fact_ids if i.strip()))
            claims.append(Claim(id=f"c{n}", section=section, text=c.text.strip(), fact_ids=ids, attempt=attempt))
    return claims
