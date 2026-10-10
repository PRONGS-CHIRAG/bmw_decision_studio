"""Agent 3 - Verifier: is every claim backed by the processed data and the model outputs?

Rules run first and need no LLM:
    citations   the claim cites at least one fact, and every cited ID exists in the bundle
    numbers     every number in the claim equals a value in a cited fact at the precision written
                (shares may be written as percentages; signs are checked by the semantic step)
    labels      recommendation / verdict labels in the claim appear in a cited fact
    quotes      text in double quotes (4+ words) is copied from a cited customer comment
    scope       every series and market the claim names is covered by a cited fact
Then an LLM (OPENAI_VERIFIER_MODEL) judges whether the cited facts entail each
claim that passed the rules - the part rules cannot see (direction, causality,
comparisons, words like 'most'). A claim must pass everything to be shown.
"""

import re

from .contracts import Check, Claim, FactBundle, JudgmentsLLM

RULES = ["citations", "numbers", "labels", "quotes", "scope", "semantic"]

LABELS = ["Prioritise", "Consider", "Low priority", "Insufficient evidence", "Not sold", "Bad", "Leaning bad",
          "Mixed", "Leaning good", "Good", "Not enough data"]
UNQUOTED_LABELS = ["Low priority", "Insufficient evidence", "Not sold", "Leaning bad", "Leaning good",
                   "Not enough data"]
SERIES_RX = {"F70": r"\bF70\b|\b1 Series\b|\b1er\b", "G60": r"\bG60\b|\b5 Series\b|\b5er\b",
             "G70": r"\bG70\b|\b7 Series\b|\b7er\b"}
MARKET_RX = {"EU": r"\bEurope(?:an)?\b|\bEU\b", "US": r"\bUnited States\b|\bUS\b|\bU\.S\.|\bAmerican?\b",
             "CN": r"\bChina\b|\bChinese\b|\bCN\b", "RoW": r"\bRest of (?:the )?world\b|\bRoW\b"}
# Phrases whose digits are names, not data
STRIP = [r"\b[A-Z]\d{2}-\d{3,5}\b",                      # comment IDs such as F70-0002 (before series codes)
         r"\b[157](?:\s*(?:,|and|&|/|or)\s*[157])*\s?Series\b",      # '5 Series', '5 and 7 Series', '1, 5 and 7 Series'
         r"\b(?:F70|G60|G68|G70|i5|i7|M60|M70)\b", r"95\s?%\s?(?:CI|confidence)",
         r"\btop[- ]?[23](?:[- ]box)?\b", r"\bbottom[- ]?3(?:[- ]box)?\b", r"\b\d+-fold\b", r"\bSA\s?\w+\b"]
NUM_RE = re.compile(r"(?<![A-Za-z0-9_.,/])(?P<sign>[-−+])?(?:(?:EUR|€)\s?)?"
                    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                    r"(?:\s?(?P<scale>thousand|million|billion|bn|mn|k|K|m|M|x|×))?"
                    r"(?P<pct>\s?%|\s?percent\b|\s?pp\b)?(?![A-Za-z0-9]|-[A-Za-z]|[.,]\d)")
SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "m": 1e6, "M": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9,
         "billion": 1e9, "x": 1.0, "×": 1.0}
DQUOTE_RE = re.compile(r"[\"“]([^\"“”]+)[\"”]")

JUDGE_INSTRUCTIONS = """You are the verification agent of BMW's product-idea evaluator.
For each claim, decide whether its cited facts fully support it. Judge only against the cited facts, never your own knowledge.
- 'supported': everything the claim states follows from the cited facts. Paraphrase and rounding are fine. A recommended next step is supported when the cited facts motivate it and it asserts no new data.
- 'unsupported': the claim adds or changes a number, label, direction (more/fewer, higher/lower), comparison, cause, trend, market, series or quote that the cited facts do not state, or it contradicts them.
Return exactly one judgment per claim_id with a one-sentence reason."""


def numbers_in(text: str) -> list[tuple[float, float, bool]]:
    """(value, tolerance, is_percent) for every data number in the text.

    The tolerance is half a unit of the last digit written, scaled by a k / m / bn suffix, so '0.7' matches
    0.71 and '115k' matches 115,000 but '3.9k' does not match 3,800."""
    for pattern in STRIP:
        text = re.sub(pattern, " ", text)
    out = []
    for m in NUM_RE.finditer(text):
        raw = m.group("num").replace(",", "")
        dec = len(raw.split(".")[1]) if "." in raw else 0
        scale = SCALE.get(m.group("scale") or "", 1.0)
        out.append((float(raw) * scale, 0.5 * 10 ** -dec * scale, bool(m.group("pct"))))
    return out


def _allowed(facts) -> list[tuple[float, bool]]:
    vals = []
    for f in facts:
        if isinstance(f.value, (int, float)) and not isinstance(f.value, bool):
            vals.append((float(f.value), f.unit == "share"))
        vals.extend((v, pct) for v, _, pct in numbers_in(f.statement))
    return vals


def _number_ok(n: float, tol: float, pct: bool, allowed) -> bool:
    for v, _ in allowed:
        cands = [abs(v)]
        if pct:
            cands.append(abs(v) * 100)
        if any(abs(c - abs(n)) <= tol + 1e-9 for c in cands):
            return True
    return False


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip(" .,;:!?…'\"“”")


def rule_checks(claim: Claim, index: dict) -> list[Check]:
    checks = []
    unknown = [i for i in claim.fact_ids if i not in index]
    cited = [index[i] for i in claim.fact_ids if i in index]
    if not claim.fact_ids:
        checks.append(Check(name="citations", passed=False, detail="The claim cites no fact."))
    elif unknown:
        checks.append(Check(name="citations", passed=False, detail=f"Unknown fact IDs: {', '.join(unknown)}."))
    else:
        checks.append(Check(name="citations", passed=True, detail=f"{len(cited)} fact(s) cited."))

    allowed = _allowed(cited)
    nums = numbers_in(claim.text)
    bad = [n for n in nums if not _number_ok(n[0], n[1], n[2], allowed)]
    if bad:
        shown = ", ".join(f"{v:,.10g}{'%' if p else ''}" for v, _, p in bad)
        checks.append(Check(name="numbers", passed=False, detail=f"Not found in the cited facts: {shown}."))
    else:
        checks.append(Check(name="numbers", passed=True,
                            detail=f"{len(nums)} number(s) match cited values." if nums else "No numbers."))

    cited_text = " ".join(f.statement for f in cited) + " " + " ".join(str(f.value) for f in cited)
    used = set()
    for label in LABELS:
        if re.search(rf"['‘\"“]{re.escape(label)}['’\"”]", claim.text, re.I):
            used.add(label)
    for label in UNQUOTED_LABELS:
        if re.search(rf"\b{re.escape(label)}\b", claim.text):
            used.add(label)
    values = {str(f.value).lower() for f in cited}
    missing = [lb for lb in sorted(used) if lb.lower() not in values
               and not re.search(rf"['‘]{re.escape(lb)}['’]", " ".join(f.statement for f in cited), re.I)]
    checks.append(Check(name="labels", passed=not missing,
                        detail=(f"Label(s) not in the cited facts: {', '.join(missing)}." if missing else
                                f"{len(used)} label(s) match." if used else "No labels.")))

    sources = [str(f.value) for f in cited if f.group == "quote"] + [f.statement for f in cited]
    norm_sources = [_norm(s) for s in sources]
    bad_quotes = []
    for q in DQUOTE_RE.findall(claim.text):
        if len(q.split()) < 4:
            continue
        parts = [_norm(p) for p in re.split(r"…|\.\.\.", q) if _norm(p)]
        if not all(any(p in s for s in norm_sources) for p in parts):
            bad_quotes.append(q[:60])
    checks.append(Check(name="quotes", passed=not bad_quotes,
                        detail=(f"Not copied from a cited comment: “{bad_quotes[0]}”." if bad_quotes else
                                "Quotes match cited comments." if DQUOTE_RE.search(claim.text) else "No quotes.")))

    scope_missing = []
    for code, rx in SERIES_RX.items():
        if re.search(rx, claim.text) and not (any(f.series == code for f in cited) or re.search(rx, cited_text)):
            scope_missing.append(code)
    for code, rx in MARKET_RX.items():
        if re.search(rx, claim.text) and not (any(f.market == code for f in cited) or re.search(rx, cited_text)):
            scope_missing.append(code)
    checks.append(Check(name="scope", passed=not scope_missing,
                        detail=(f"Names {', '.join(scope_missing)} but no cited fact covers it." if scope_missing
                                else "Series and markets match the cited facts.")))
    return checks


def verify(claims: list[Claim], bundle: FactBundle, llm=None) -> list[Claim]:
    """Run the rules, then the semantic judge on what passed. Returns claims with checks and status set."""
    index = bundle.index()
    for c in claims:
        c.checks = rule_checks(c, index)
    passing = [c for c in claims if all(ch.passed for ch in c.checks)]
    if llm is not None and passing:
        blocks = []
        for c in passing:
            facts = "\n".join(f"    {i}: {index[i].statement}" for i in c.fact_ids)
            blocks.append(f"claim_id: {c.id}\nclaim: {c.text}\ncited facts:\n{facts}")
        result = llm.parse("verifier", JUDGE_INSTRUCTIONS, "\n\n".join(blocks), JudgmentsLLM)
        by_id = {j.claim_id: j for j in result.judgments}
        for c in passing:
            j = by_id.get(c.id)
            if j is None:
                c.checks.append(Check(name="semantic", passed=False, detail="The verifier returned no judgment."))
            else:
                c.checks.append(Check(name="semantic", passed=j.verdict == "supported", detail=j.reason))
    for c in claims:
        if llm is None and all(ch.passed for ch in c.checks):
            c.checks.append(Check(name="semantic", passed=False, detail="Semantic check needs the verifier model."))
        c.status = "verified" if all(ch.passed for ch in c.checks) else "removed"
    return claims
