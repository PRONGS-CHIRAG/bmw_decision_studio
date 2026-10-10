"""Competitor & market intelligence.

Three layers, from most to least grounded:
1. Competitor mentions mined from BMW's own verbatims (works offline).
2. A seed list of segment rivals per market (data/external/competitors.json).
3. Optional web research with Claude + the web search tool: competitor availability of a
   feature, specs, reception and sales signals in a market, each fact tied to source URLs.
   Results are cached in data/external/research/ and written to the audit trail.

Claude is also used to answer a PM's challenge of a requirement from its evidence pack.
Both AI paths are optional; everything else in the app works without an API key.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pandas as pd

from . import taxonomy as tx
from .config import CLAUDE_MODEL, DERIVATIVES, EXTERNAL_DIR, REGION_NAMES, RESEARCH_DIR


class AIUnavailable(RuntimeError):
    pass


# --------------------------------------------------------------------------
# 1 + 2: offline intelligence
# --------------------------------------------------------------------------
def competitor_mentions(f: pd.DataFrame, limit_quotes: int = 3) -> list[dict]:
    """Which competitors do BMW customers compare with, in what tone, about what."""
    hits = f[f["competitors"] != ""]
    if hits.empty:
        return []
    rows = hits.assign(brand=hits["competitors"].str.split("|")).explode("brand")
    out = []
    for brand, grp in rows.groupby("brand"):
        per = grp.drop_duplicates(["verbatim_id", "signal"])
        quotes = []
        for r in grp.drop_duplicates("verbatim_id").sort_values("text", key=lambda s: s.str.len()).itertuples():
            m = re.search(tx.COMPETITORS[brand], r.text, re.I)
            start = max(0, (m.start() if m else 0) - 120)
            quotes.append({"verbatim_id": r.verbatim_id, "country": r.country, "derivative": r.derivative,
                           "text": ("..." if start else "") + r.text[start:start + 280]})
            if len(quotes) >= limit_quotes:
                break
        out.append({
            "brand": brand, "verbatims": int(grp["verbatim_id"].nunique()),
            "praise": int((per["signal"] == "praise").sum()),
            "complaints": int(per["signal"].isin(tx.COMPLAINT_SIGNALS).sum()),
            "requests": int((per["signal"] == "request").sum()),
            "topics": grp[grp["component"] != "no_class_found"]["component"].value_counts().head(4).index.tolist(),
            "quotes": quotes,
        })
    return sorted(out, key=lambda x: -x["verbatims"])


def seed_competitors(derivative: str) -> dict[str, list[str]]:
    data = json.loads((EXTERNAL_DIR / "competitors.json").read_text(encoding="utf-8"))
    return data.get(derivative, {})


def _cache_path(derivative: str, region: str, feature_key: str):
    slug = re.sub(r"[^a-z0-9]+", "_", feature_key.lower()).strip("_")
    return RESEARCH_DIR / f"{derivative}_{region}_{slug}.json"


def cached_research(derivative: str, feature_key: str, region: str | None = None) -> list[dict]:
    if not RESEARCH_DIR.exists():
        return []
    slug = re.sub(r"[^a-z0-9]+", "_", feature_key.lower()).strip("_")
    pattern = f"{derivative}_{region or '*'}_{slug}.json"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESEARCH_DIR.glob(pattern))]


def research_gap(derivative: str, feature_key: str) -> bool | None:
    """True if cached research says a competitor is ahead; None if never researched."""
    results = cached_research(derivative, feature_key)
    if not results:
        return None
    return any(r["result"].get("competitor_ahead") for r in results)


# --------------------------------------------------------------------------
# 3: Claude web research
# --------------------------------------------------------------------------
RESEARCH_TOOL = {
    "name": "record_market_research",
    "description": "Record the structured result of the competitor and market research. Call it exactly once, "
                   "after searching, with only facts supported by the pages you found.",
    "strict": True,
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "required": ["summary", "competitors", "market_trends", "implications_for_bmw", "competitor_ahead",
                     "confidence"],
        "properties": {
            "summary": {"type": "string", "description": "3-5 sentence answer for a product manager."},
            "competitors": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["brand", "model", "availability", "detail", "customer_reception", "sales_signal",
                             "source_urls"],
                "properties": {
                    "brand": {"type": "string"}, "model": {"type": "string"},
                    "availability": {"type": "string", "enum": ["standard", "optional", "not_offered", "unknown"],
                                     "description": "Availability of the researched feature in this market."},
                    "detail": {"type": "string", "description": "Spec / execution details, e.g. material, levels."},
                    "customer_reception": {"type": "string", "description": "What reviews/owners say, or 'unknown'."},
                    "sales_signal": {"type": "string",
                                     "description": "Public sales figure or trend with year and market, or 'unknown'."},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                }}},
            "market_trends": {"type": "array", "items": {"type": "string"}},
            "implications_for_bmw": {"type": "string"},
            "competitor_ahead": {"type": "boolean",
                                 "description": "True if at least one rival offers clearly more on this feature."},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    },
}


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise AIUnavailable("The 'anthropic' package is not installed (pip install -r requirements.txt).") from exc
    return anthropic, anthropic.Anthropic()


NO_CREDENTIALS = "No Anthropic credentials - set ANTHROPIC_API_KEY (or run `ant auth login`)."


def _create(client, **kwargs):
    # Server-side refusal fallback: a declined request is re-run on Anthropic's recommended model.
    try:
        return client.beta.messages.create(model=CLAUDE_MODEL, betas=["server-side-fallback-2026-07-01"],
                                           extra_body={"fallbacks": "default"}, **kwargs)
    except TypeError as exc:  # the SDK raises this before sending when no credentials resolve
        if "authentication" in str(exc).lower():
            raise AIUnavailable(NO_CREDENTIALS) from exc
        raise


def run_web_research(derivative: str, region: str, feature_label: str, feature_key: str, bmw_context: str,
                     max_searches: int = 8) -> dict:
    anthropic, client = _client()
    vehicle = DERIVATIVES[derivative]
    rivals = seed_competitors(derivative).get(region, [])
    prompt = (
        f"You are supporting a BMW product manager deciding on customer requirements for the successor of the "
        f"{vehicle['name']} ({derivative}, {vehicle['segment']}).\n\n"
        f"Market: {REGION_NAMES[region]}.\nFeature under review: {feature_label}.\n"
        f"Likely rivals in this market (starting point, adjust if research shows others matter more): "
        f"{', '.join(rivals) or 'identify the main segment rivals'}.\n\n"
        f"What BMW's own data says:\n{bmw_context}\n\n"
        "Research with web search, using publicly available sources (manufacturer configurators and price lists, "
        "reputable reviews, owner forums, registration or sales statistics):\n"
        "1. For each relevant rival in this market: is the feature standard, optional or not offered; notable "
        "execution details (materials, levels, specs); how reviewers and owners receive it; and any public sales "
        "signal (figure or trend, with year).\n"
        "2. Market trends for this feature in this market (e.g. what local brands are doing).\n"
        "3. What this implies for BMW.\n"
        "Only record facts supported by pages you found and give their URLs; write 'unknown' where you found "
        "nothing. Finish by calling record_market_research once."
    )
    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}, RESEARCH_TOOL]
    seen: dict[str, str] = {}
    result = None
    try:
        for _ in range(6):
            resp = _create(client, max_tokens=16000, output_config={"effort": "medium"}, tools=tools,
                           messages=messages)
            for block in resp.content:
                if block.type == "web_search_tool_result" and isinstance(block.content, list):
                    for item in block.content:
                        seen[item.url] = getattr(item, "title", "") or item.url
            if resp.stop_reason == "refusal":
                raise AIUnavailable("Claude declined this research request.")
            call = next((b for b in resp.content if b.type == "tool_use" and b.name == RESEARCH_TOOL["name"]), None)
            if call is not None:
                result = call.input if isinstance(call.input, dict) else json.loads(call.input)
                break
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "pause_turn":  # ended without recording: ask for the tool call
                messages.append({"role": "user", "content": "Record your findings now with record_market_research."})
    except anthropic.AuthenticationError as exc:
        raise AIUnavailable(NO_CREDENTIALS) from exc
    except anthropic.APIConnectionError as exc:
        raise AIUnavailable("Could not reach the Anthropic API.") from exc
    except anthropic.APIStatusError as exc:
        raise AIUnavailable(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    if result is None:
        raise AIUnavailable("Research finished without a structured result.")

    for comp in result.get("competitors", []):
        comp["unverified_urls"] = [u for u in comp.get("source_urls", []) if u not in seen]
    record = {
        "derivative": derivative, "region": region, "feature_key": feature_key, "feature_label": feature_label,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": CLAUDE_MODEL,
        "result": result, "search_results": [{"url": u, "title": t} for u, t in seen.items()],
    }
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(derivative, region, feature_key).write_text(json.dumps(record, indent=2, ensure_ascii=False),
                                                           encoding="utf-8")
    return record


def answer_challenge(requirement: dict, question: str) -> str:
    """Answer a PM's challenge strictly from the requirement's evidence pack."""
    anthropic, client = _client()
    pack = {k: requirement.get(k) for k in ("id", "title", "description", "type", "derivative", "kano", "priority",
                                            "evidence", "factor_notes", "regions", "assumptions", "quotes",
                                            "top_issues", "survey", "sales")}
    prompt = (
        "A product manager challenges a requirement proposed by an AI pipeline. Answer only from the evidence "
        "pack below. Cite verbatim IDs or survey attributes for each claim, say plainly where the evidence is "
        "thin, and end with one line: 'Suggested action: keep / lower priority / gather more evidence / reject'.\n\n"
        f"Challenge: {question}\n\nEvidence pack (JSON):\n{json.dumps(pack, ensure_ascii=False, default=str)[:60000]}"
    )
    try:
        resp = _create(client, max_tokens=4000, output_config={"effort": "low"},
                       messages=[{"role": "user", "content": prompt}])
    except anthropic.AuthenticationError as exc:
        raise AIUnavailable(NO_CREDENTIALS) from exc
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
        raise AIUnavailable(f"Anthropic API unavailable: {exc}") from exc
    if resp.stop_reason == "refusal":
        raise AIUnavailable("Claude declined to answer this challenge.")
    return "".join(b.text for b in resp.content if b.type == "text").strip()
