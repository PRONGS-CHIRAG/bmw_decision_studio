"""Build a scoped, source-resolvable evidence pack without an LLM or file writes.

Only original component classifications enter observed feature counts. Text matches,
parent components and model labels remain separate review queues. This module reports
observations and their denominators; it never supplies priority, cost or feasibility.
"""
from __future__ import annotations

import hashlib
import json
import re

import pandas as pd

from . import taxonomy as tx
from .brief import Resolution, resolve
from .config import DERIVATIVES, REGIONS
from .store import Data, load_runtime

READER_VERSION = "decision-evidence-1"
SIGNALS = {"defects": ("defect",), "usability": ("usability",),
           "complaints": ("defect", "usability"), "requests": ("request",), "praise": ("praise",)}


def _number(value):
    if value is None or pd.isna(value):
        return None
    result = float(value)
    return int(result) if result.is_integer() else result


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _hash(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _context(context: dict) -> dict:
    vehicle = context.get("vehicle") or context.get("derivative")
    markets = context.get("markets") or ([context["market"]] if context.get("market") else [])
    if vehicle not in DERIVATIVES:
        raise ValueError("Select a vehicle present in the BMW source data.")
    if not markets or any(m not in REGIONS for m in markets):
        raise ValueError("Select at least one supported market.")
    powertrain = context.get("powertrain") or None
    if powertrain in {"all", "All"}:
        powertrain = None
    if powertrain not in {None, "BEV", "PHEV", "ICE", "Unknown"}:
        raise ValueError("Unknown powertrain filter.")
    try:
        launch_year = int(context["launch_year"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("A project launch_year is required.") from exc
    if not 2000 <= launch_year <= 2100:
        raise ValueError("launch_year is outside the supported planning range.")
    return {"vehicle": vehicle, "markets": sorted(set(markets)), "powertrain": powertrain,
            "launch_year": launch_year}


def _query_text(query) -> str:
    if isinstance(query, dict):
        query = next((query[k] for k in ("feature", "feature_id", "query", "key", "id", "label")
                      if query.get(k)), "")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("A feature key, label or component query is required.")
    return query


def _resolution(query, data: Data) -> Resolution:
    return resolve(_query_text(query), data)


def _ids(rows: pd.DataFrame) -> list[str]:
    return sorted(set(rows["finding_id"].astype(str)))


def _feedback_citations(rows: pd.DataFrame, citations: dict) -> None:
    for row in rows.drop_duplicates("finding_id").sort_values("finding_id").itertuples():
        citations[row.finding_id] = {
            "id": row.finding_id, "kind": "feedback", "file": row.source_file,
            "sheet": row.source_sheet, "row": int(row.source_row), "cell": None,
            "raw_record_id": str(row.raw_record_id), "review_id": str(row.verbatim_id),
            "text": str(row.raw_text), "component": row.component, "issue": row.issue,
            "signal": row.signal, "label_source": row.label_source, "market": row.region,
            "country": row.country, "source_family": row.source, "powertrain": row.powertrain,
            "label": "observed" if row.label_source == "vfc" else "assumption",
        }


def _mix(rows: pd.DataFrame, column: str) -> dict:
    return {str(key): int(value) for key, value in sorted(
        rows.groupby(column, dropna=False)["verbatim_id"].nunique().items(), key=lambda item: str(item[0]))}


def _sample(rows: pd.DataFrame) -> dict:
    return {"n": int(rows["verbatim_id"].nunique()), "label": "observed",
            "unit": "unique feedback records, not representative buyers",
            "country_mix": _mix(rows, "country"), "source_mix": _mix(rows, "source"),
            "powertrain_mix": _mix(rows, "powertrain"),
            "record_ids": sorted(set(rows["verbatim_id"].astype(str))),
            "source_rows": [{"file": row.source_file, "sheet": row.source_sheet,
                             "row": int(row.source_row), "raw_record_id": str(row.raw_record_id)}
                            for row in rows.drop_duplicates("verbatim_id").sort_values("verbatim_id").itertuples()]}


def _select(rows: pd.DataFrame, resolution: Resolution):
    component = rows["component"].isin(resolution.components)
    direct = component.copy()
    if resolution.feature and resolution.feature.component_text_filter:
        direct &= rows["text"].str.contains(resolution.feature.component_text_filter,
                                            case=False, regex=True, na=False)
    original = rows["label_source"].eq("vfc")
    observed = rows[direct & original]
    contextual = rows[component & ~direct & original]
    terms = "|".join(re.escape(term) for term in resolution.terms if term)
    text_match = rows["text"].str.contains(terms, case=False, regex=True, na=False) if terms else direct & False
    # A sentence mentioning the requested term needs review if its classification is different.
    unreviewed = rows[(direct & ~original) | (text_match & ~direct)]
    unreviewed = unreviewed[~unreviewed["verbatim_id"].isin(observed["verbatim_id"])]
    return observed, contextual, unreviewed


def _survey(data: Data, context: dict, market: str, resolution: Resolution, citations: dict) -> list[dict]:
    rows = data.survey_for(context["vehicle"], resolution.survey_prefixes)
    rows = rows[rows["region"].eq(market)]
    result = []
    for row in rows.sort_values(["study", "model", "attribute"]).itertuples():
        source_ids = []
        for cell in row.source_cells:
            cid = f"{row.source_file}:{cell['sheet']}:{cell['cell']}"
            source_ids.append(cid)
            citations[cid] = {"id": cid, "kind": "customer_study", "file": row.source_file,
                "sheet": cell["sheet"], "row": cell["row"], "cell": cell["cell"],
                "text": cell["value"], "attribute": row.attribute, "model": row.model,
                "response": cell["response"], "market": market, "label": "observed"}
        result.append({"attribute": row.attribute, "study": row.study, "model": row.model,
            "original_value": _number(row.original_value), "original_scale": row.original_scale,
            "distribution": row.distribution if isinstance(row.distribution, dict) else None,
            "sample_size": None, "label": "observed", "source_ids": source_ids,
            "relationship": "related_attribute",
            "applicability": "Vehicle-level study; no feature-specific or powertrain-specific causal effect established."})
    return result


def _sales(data: Data, context: dict, market: str, citations: dict) -> dict:
    rows = data.sales[data.sales["derivative"].eq(context["vehicle"]) & data.sales["region"].eq(market)]
    year = context["launch_year"]
    column = f"volume_{year}"
    available_years = sorted(int(c.removeprefix("volume_")) for c in rows.columns if c.startswith("volume_"))
    label = "scenario evaluation" if year >= 2030 else "observed"
    result = {"volume": None, "vehicle_volume": None, "year": year, "status": "unknown",
              "label": label, "basis": "BMW projection" if year >= 2030 else "BMW reported sales",
              "source_ids": [], "available_years": available_years,
              "scope": "vehicle line and market; no powertrain split", "incremental_sales": None}
    if rows.empty or column not in rows or rows[column].isna().any():
        result["reason"] = "No source volume for this vehicle, market and launch year. No interpolation is assumed."
        return result
    total = int(rows[column].sum())
    result["vehicle_volume"] = total
    for row in rows.sort_values("source_row").to_dict("records"):
        cell = f"{row['source_columns'][column]}{int(row['source_row'])}"
        cid = f"{row['source_file']}:{row['sales_sheet']}:{cell}"
        result["source_ids"].append(cid)
        citations[cid] = {"id": cid, "kind": "sales", "file": row["source_file"],
            "sheet": row["sales_sheet"], "row": int(row["source_row"]), "cell": cell,
            "text": str(row[column]), "value": _number(row[column]), "market": market,
            "year": year, "label": label, "basis": result["basis"]}
    if context["powertrain"]:
        result["reason"] = "Source volumes cannot be disaggregated to the selected powertrain; vehicle_volume is context."
    else:
        result.update(volume=total, status="available")
    return result


def _equipment(data: Data, context: dict, resolution: Resolution, citations: dict) -> list[dict]:
    if data.equipment.empty:
        return []
    match = data.equipment_match(context["vehicle"], resolution.equipment_terms)
    result = []
    for item in match["items"]:
        cid = f"{item['source']}:page:{item['page']}"
        # Names are extracted text; provenance always resolves to the complete PDF page.
        existing = citations.get(cid, {}).get("text", "")
        text = "\n".join(sorted(set(filter(None, [*existing.splitlines(), item["name"]]))))
        citations[cid] = {"id": cid, "kind": "equipment", "file": item["source"],
            "page": item["page"], "text": text, "market": "DE", "label": "observed"}
        result.append({**item, "source_ids": [cid], "label": "observed", "market": "DE",
            "relationship": "German price-list context", "development_cost": None,
            "applicability": "German July 2026 equipment listing; other markets and future availability unknown.",
            "price_basis": "Retail list price, not a development-cost estimate"})
    return result


def _facets(rows: pd.DataFrame, lexicon: dict, kind: str) -> list[dict]:
    result = []
    for name, pattern in sorted(lexicon.items()):
        matches, source_ids, review_ids = [], set(), set()
        for row in rows.drop_duplicates("verbatim_id").sort_values("verbatim_id").itertuples():
            text = str(row.raw_text)
            found = list(re.finditer(pattern, text, re.I))
            if not found:
                continue
            review_ids.add(row.verbatim_id)
            source_ids.add(row.finding_id)
            for match in found[:2]:
                start, end = max(0, match.start() - 80), min(len(text), match.end() + 80)
                matches.append({"citation_id": row.finding_id, "start": start, "end": end,
                                "text": text[start:end], "matched_text": match.group(0)})
        if matches:
            result.append({"name": name, "mentions": len(review_ids), "source_ids": sorted(source_ids),
                "spans": matches[:8], "label": "observed", "relationship": "co-mention in a direct feature review",
                "limitation": ("Material suitability and material-specific sentiment are not established."
                               if kind == "materials" else
                               "BMW customer mention; not an independently verified competitor specification or review.")})
    return sorted(result, key=lambda x: (-x["mentions"], x["name"]))


def _market(data: Data, context: dict, market: str, resolution: Resolution, citations: dict) -> dict:
    rows = data.scope(context["vehicle"], context["powertrain"])
    rows = rows[rows["region"].eq(market)].drop_duplicates("finding_id").sort_values("finding_id")
    direct, contextual, unreviewed = _select(rows, resolution)
    _feedback_citations(pd.concat([direct, contextual, unreviewed]), citations)
    counts = {"mentions": int(direct["verbatim_id"].nunique())}
    counts.update({key: int(direct.loc[direct["signal"].isin(signals), "verbatim_id"].nunique())
                   for key, signals in SIGNALS.items()})
    sample = _sample(rows)
    count_ids = {key: _ids(direct[direct["signal"].isin(signals)]) for key, signals in SIGNALS.items()}
    count_ids["mentions"] = _ids(direct)
    grouped = direct[direct["signal"].isin(tx.COMPLAINT_SIGNALS + ("request",))]
    issues = [{"issue": str(issue), "signal": str(signal), "count": int(part["verbatim_id"].nunique()),
               "source_ids": _ids(part), "label": "observed"}
              for (issue, signal), part in grouped.groupby(["issue", "signal"])]
    issues.sort(key=lambda item: (-item["count"], item["issue"], item["signal"]))
    positive = direct[direct["signal"].eq("praise")]
    negative = direct[direct["signal"].isin(tx.COMPLAINT_SIGNALS)]
    coverage = "no feedback" if not sample["n"] else ("direct evidence present" if counts["mentions"] else
                                                     "no direct classified feature evidence")
    return {"sample": sample, "counts": counts, "count_evidence_ids": count_ids,
        "rates_per_1000": {key: round(value / sample["n"] * 1000, 4) if sample["n"] else None
                           for key, value in counts.items()},
        "label": "observed", "coverage": coverage,
        "direct_evidence_ids": _ids(direct), "contextual_evidence_ids": _ids(contextual),
        "unreviewed_evidence_ids": _ids(unreviewed), "evidence_preview": _ids(direct)[:12],
        "support": {"improve": count_ids["complaints"], "add": count_ids["requests"],
                    "retain": count_ids["praise"], "remove": []},
        "counterevidence": {"improve": _ids(positive), "add": [], "retain": _ids(negative),
                            "remove": _ids(positive)},
        "counterevidence_note": "Praise and complaints may concern different aspects; these are review prompts, not proof against an action.",
        "survey": _survey(data, context, market, resolution, citations),
        "sales": _sales(data, context, market, citations),
        "equipment": _equipment(data, context, resolution, citations),
        "materials": _facets(direct, tx.MATERIALS, "materials"),
        "competitors": _facets(direct, tx.COMPETITORS, "competitors"), "issues": issues,
        "limitations": ["Feedback rates describe this sample and do not estimate buyer demand or willingness to pay.",
                        "No direct evidence does not establish that the feature is unnecessary.",
                        "Model labels and free-text candidates are excluded until reviewed."]}


def build_evidence(context: dict, features: list, data: Data | None = None) -> dict:
    """Return a reproducible regional evidence snapshot and its citation registry."""
    context = _context(context)
    if not features:
        raise ValueError("Select at least one feature.")
    data = data if data is not None else load_runtime()
    required = {"source_file", "source_sheet", "source_row", "raw_record_id", "raw_text", "finding_id"}
    if not required <= set(data.findings.columns):
        raise ValueError("Raw BMW source locators are missing; use load_runtime(), not legacy processed CSV files.")
    citations, result, seen, feature_queries = {}, [], set(), {}
    for query in features:
        resolution = _resolution(query, data)
        feature_queries[_query_text(query)] = resolution.key
        if resolution.key in seen:
            continue
        seen.add(resolution.key)
        result.append({"id": resolution.key, "label": resolution.label,
            "resolution": {"components": resolution.components, "terms": resolution.terms,
                "note": resolution.note, "alternatives": resolution.alternatives,
                "subfeature_filter": resolution.feature.component_text_filter if resolution.feature else None},
            "markets": {market: _market(data, context, market, resolution, citations)
                        for market in context["markets"]}})
    result.sort(key=lambda f: f["id"])
    pack = {"reader_version": READER_VERSION, "context": context, "features": result,
            "feature_queries": dict(sorted(feature_queries.items())),
            "source_hashes": dict(sorted(data.manifest.get("sources", {}).items())),
            "citations": dict(sorted(citations.items())),
            "ingestion_report": data.manifest.get("ingestion_report", {}),
            "external_research": {"status": "not attached", "reason": "Only the supplied BMW sources are in this snapshot."}}
    pack["evidence_hash"] = _hash(pack)
    validate_citations(pack, list(pack["citations"]))
    return pack


def validate_citations(pack: dict, citation_ids: list[str]) -> list[dict]:
    """Validate references against the frozen source registry, never free-form model IDs."""
    result = []
    for cid in citation_ids:
        citation = pack.get("citations", {}).get(cid)
        if citation is None:
            raise ValueError(f"Unknown citation ID: {cid}")
        if citation.get("file") not in pack.get("source_hashes", {}):
            raise ValueError(f"Citation has no frozen source hash: {cid}")
        if not citation.get("page") and not (citation.get("sheet") and citation.get("row")):
            raise ValueError(f"Citation has no resolvable passage locator: {cid}")
        result.append(citation)
    return result
