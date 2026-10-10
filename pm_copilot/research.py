"""Offline competitor evidence and read-only historical research.

Live structured research and grounded explanations use decision_agents and the
configured backend OpenAI service. Legacy provider endpoints are retired.
"""
from __future__ import annotations

import json
import re

import pandas as pd

from . import taxonomy as tx
from .config import EXTERNAL_DIR, RESEARCH_DIR


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


def run_web_research(derivative: str, region: str, feature_label: str, feature_key: str,
                     bmw_context: str, max_searches: int = 8) -> dict:
    raise AIUnavailable("Use the Decision workspace public research action; legacy external-provider research is disabled.")


def answer_challenge(requirement: dict, question: str) -> str:
    raise AIUnavailable("Use the Decision workspace explainer on a saved ranking run for validated citations.")
