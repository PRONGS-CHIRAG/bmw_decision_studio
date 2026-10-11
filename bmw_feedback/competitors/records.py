"""Extracted value rows and the validator every build runs.

The research writes JSON Lines to competitor-data/extracted/*.jsonl, one value per line:

    {"table": "price", "model_id": "mercedes-e-class", "market": "EU", "country": "DE", "currency": "EUR",
     "variant": "E 200", "amount": 62000, "powertrain": "MHEV", "price_type": "list_price",
     "tax_basis": "incl. 19% VAT", "entry": true, "source_id": "s1a2b3c4d5e",
     "evidence": "E 200 ... 62.000,00 €"}

Common fields: table, model_id, source_id (from `competitors fetch`), evidence (copied from `competitors grep`).
A row is accepted only if
    - every required field is present with an allowed value (registry.py),
    - the evidence occurs in the saved text of that source (whitespace, quotes and dashes normalised, case folded;
      '...' may join fragments that each occur), and
    - every number the row states (units, amount, value, score, ...) is written in the evidence, in English,
      German or Chinese notation (12,345 / 12.345 / 1.190,00 / 43.99万).
Cross-row checks: every model_id is defined by a `model` row, definitions agree, no exact duplicates.
"""

import json
import math
import re
from pathlib import Path

from .. import config
from . import registry as R
from .snapshot import flat, meta as source_meta, text as source_text

REQUIRED = {
    "model": ["brand", "model", "segment", "body"],
    "sales": ["market", "region", "year", "units", "basis", "tier"],
    "price": ["market", "country", "currency", "variant", "amount", "powertrain", "price_type", "tax_basis"],
    "spec": ["variant", "attribute", "value", "unit"],
    "equipment": ["country", "item", "status", "item_name"],
    "review": ["market", "country", "kind", "text"],
    "rating": ["market", "country", "rating_kind", "score", "scale_max"],
    "rival": ["bmw_series"],
}
NUMERIC = {"sales": ["units"], "price": ["amount"], "spec": ["value"], "equipment": ["price_eur"],
           "rating": ["score", "n_reviews"], "review": ["rating"]}
COUNTRIES = {"DE", "US", "CN", "AU", "GB", "FR", "JP", "KR", "CA", "ZA", "EU"}
CURRENCIES = {"EUR", "USD", "CNY", "AUD", "GBP", "JPY", "KRW", "CAD", "ZAR"}

_TOKEN = re.compile(r"(?<![A-Za-z0-9_.])\d(?:[\d.,' ]*\d)?(?:\s?(万|萬|k\b|K\b))?")


# ---------------------------------------------------------------------- numbers
def _interpretations(token: str) -> set[float]:
    out = set()
    pieces = [token] + (token.split(" ") if " " in token else [])
    for p in pieces:
        p = p.strip(" .,'")
        if not p or not p[0].isdigit():
            continue
        en = p.replace(",", "").replace("'", "").replace(" ", "")
        de = p.replace(".", "").replace("'", "").replace(" ", "").replace(",", ".")
        for cand in (en, de):
            if re.fullmatch(r"\d+(?:\.\d+)?", cand):
                out.add(float(cand))
    return out


def numbers_in(text: str) -> set[float]:
    """Every value a number in the text can stand for (both thousands conventions, 万 = 10,000, k = 1,000)."""
    vals = set()
    for m in _TOKEN.finditer(flat(text)):
        raw = m.group(0)
        unit = m.group(1)
        token = raw[: m.start(1) - m.start(0)].strip() if unit else raw
        base = _interpretations(token)
        vals |= base
        if unit in ("万", "萬"):
            vals |= {round(v * 10_000, 6) for v in base}
        elif unit in ("k", "K"):
            vals |= {round(v * 1_000, 6) for v in base}
    return vals


def number_in(value, text: str) -> bool:
    v = float(value)
    return any(math.isclose(v, x, rel_tol=1e-9, abs_tol=1e-6) for x in numbers_in(text))


# ---------------------------------------------------------------------- evidence
def evidence_in_source(evidence: str, sid: str) -> tuple[bool | None, str]:
    """(True | False | None if the snapshot is absent, detail)."""
    t = source_text(sid)
    if t is None:
        return None, f"no saved text for source {sid}"
    hay = flat(t).lower()
    parts = [flat(p).lower() for p in re.split(r"\.\.\.|…", evidence) if len(flat(p)) >= 3]
    if not parts:
        return False, "evidence is empty"
    missing = [p for p in parts if p not in hay]
    if missing:
        return False, f"not in source {sid}: \"{missing[0][:90]}\""
    return True, "found"


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ---------------------------------------------------------------------- one row
def validate_record(rec: dict, require_snapshot: bool = True) -> list[str]:
    errs = []
    table = rec.get("table")
    if table not in R.TABLES:
        return [f"table must be one of {R.TABLES}, got {table!r}"]
    mid = rec.get("model_id")
    if not isinstance(mid, str) or not re.fullmatch(R.MODEL_ID_RE, mid):
        errs.append(f"model_id {mid!r} must be lowercase words joined by '-' (e.g. 'mercedes-e-class')")
    for f in REQUIRED[table]:
        if rec.get(f) in (None, ""):
            errs.append(f"missing {f}")
    sid = rec.get("source_id")
    evidence = rec.get("text") if table == "review" and not rec.get("evidence") else rec.get("evidence")
    if table != "model" or sid or evidence:
        if not sid or not isinstance(sid, str):
            errs.append("missing source_id")
        if not evidence or not isinstance(evidence, str):
            errs.append("missing evidence")
        elif len(evidence) > 700:
            errs.append(f"evidence is {len(evidence)} characters; keep it under 700")
        if sid and isinstance(sid, str):
            m = source_meta(sid)
            if m is None and require_snapshot:
                errs.append(f"unknown source_id {sid} (fetch it first)")
            elif m is not None and not m.get("ok"):
                errs.append(f"source {sid} was not usable when fetched ({m.get('problem')})")
            if evidence and isinstance(evidence, str):
                ok, detail = evidence_in_source(evidence, sid)
                if ok is False or (ok is None and require_snapshot):
                    errs.append(f"evidence {detail}")
    for f in NUMERIC.get(table, []):
        v = rec.get(f)
        if v is None:
            continue
        if not _is_num(v):
            errs.append(f"{f} must be a number, got {v!r}")
        elif evidence and isinstance(evidence, str) and not number_in(v, evidence):
            errs.append(f"{f}={v} is not written in the evidence")
    errs += _table_rules(table, rec)
    return errs


def _table_rules(table: str, r: dict) -> list[str]:
    e = []
    if r.get("market") is not None and r.get("market") not in R.MARKETS:
        e.append(f"market must be one of {R.MARKETS}")
    if table == "model":
        if r.get("segment") not in R.SEGMENTS:
            e.append(f"segment must be one of {list(R.SEGMENTS)}")
    elif table == "sales":
        if not (isinstance(r.get("year"), int) and 2020 <= r["year"] <= 2026):
            e.append("year must be an integer 2020-2026")
        if _is_num(r.get("units")) and (r["units"] < 0 or r["units"] != int(r["units"])):
            e.append("units must be a whole number >= 0")
        if r.get("basis") not in R.SALES_BASIS:
            e.append(f"basis must be one of {R.SALES_BASIS}")
        if r.get("tier") not in R.SOURCE_TIERS:
            e.append(f"tier must be one of {R.SOURCE_TIERS}")
        if r.get("period", "FY") not in ("FY", "H1", "Q1-Q3", "YTD"):
            e.append("period must be FY, H1, Q1-Q3 or YTD")
    elif table == "price":
        if r.get("country") not in COUNTRIES:
            e.append(f"country must be one of {sorted(COUNTRIES)}")
        if r.get("currency") not in CURRENCIES:
            e.append(f"currency must be one of {sorted(CURRENCIES)}")
        ref = R.REFERENCE.get(r.get("market"))
        if ref and r.get("country") == ref["country"] and r.get("currency") != ref["currency"]:
            e.append(f"prices for {ref['country_name']} must be in {ref['currency']}")
        if r.get("powertrain") not in R.POWERTRAINS:
            e.append(f"powertrain must be one of {R.POWERTRAINS}")
        if r.get("price_type") not in R.PRICE_TYPES:
            e.append(f"price_type must be one of {R.PRICE_TYPES}")
        if _is_num(r.get("amount")) and r["amount"] <= 0:
            e.append("amount must be positive")
        if r.get("model_id") in R.SELF_SERIES and r.get("market") == "EU" and r.get("country") == "DE":
            e.append("BMW prices in Germany come from BMW's own DE price list; do not record them from the web")
    elif table == "spec":
        attr = r.get("attribute")
        if attr not in R.SPEC_ATTRIBUTES:
            e.append(f"attribute must be one of {list(R.SPEC_ATTRIBUTES)}")
        elif r.get("unit") != R.SPEC_ATTRIBUTES[attr][0]:
            e.append(f"unit for {attr} must be {R.SPEC_ATTRIBUTES[attr][0]!r}")
        if r.get("powertrain") is not None and r.get("powertrain") not in R.POWERTRAINS:
            e.append(f"powertrain must be one of {R.POWERTRAINS}")
    elif table == "equipment":
        if r.get("country") != "DE":
            e.append("equipment is compared for Germany only: country must be 'DE'")
        if r.get("item") not in R.EQUIPMENT_ITEMS:
            e.append(f"item must be one of {list(R.EQUIPMENT_ITEMS)}")
        if r.get("status") not in R.EQUIPMENT_STATUS:
            e.append(f"status must be one of {R.EQUIPMENT_STATUS}")
        if r.get("status") in ("standard", "not_available") and r.get("price_eur") not in (None, 0):
            e.append(f"status {r.get('status')} cannot have a price")
        if r.get("model_id") in R.SELF_SERIES:
            e.append("BMW equipment comes from BMW's own DE price list; do not record it from the web")
    elif table == "review":
        if r.get("kind") not in R.REVIEW_KINDS:
            e.append(f"kind must be one of {R.REVIEW_KINDS}")
        if isinstance(r.get("text"), str) and not (12 <= len(r["text"]) <= 600):
            e.append("text must be 12-600 characters")
        if r.get("rating") is not None and not _is_num(r.get("rating_scale")):
            e.append("a rating needs rating_scale")
    elif table == "rating":
        if r.get("rating_kind") not in R.RATING_KINDS:
            e.append(f"rating_kind must be one of {R.RATING_KINDS}")
        if _is_num(r.get("score")) and _is_num(r.get("scale_max")) and not (0 < r["score"] <= r["scale_max"]):
            e.append("score must be > 0 and <= scale_max")
    elif table == "rival":
        if r.get("bmw_series") not in config.MODELS:
            e.append(f"bmw_series must be one of {config.MODELS}")
    return e


# ---------------------------------------------------------------------- files
def record_files() -> list[Path]:
    return sorted(R.EXTRACTED_DIR.glob("*.jsonl")) if R.EXTRACTED_DIR.exists() else []


def load(paths: list[Path] | None = None) -> tuple[list[dict], list[str]]:
    """All rows with their file and line; malformed lines are reported, not skipped silently."""
    rows, errs = [], []
    for path in (record_files() if paths is None else paths):
        for i, line in enumerate(Path(path).read_text().splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                errs.append(f"{Path(path).name}:{i}: not valid JSON ({e.msg})")
                continue
            if not isinstance(rec, dict):
                errs.append(f"{Path(path).name}:{i}: a row must be a JSON object")
                continue
            rec["_where"] = f"{Path(path).name}:{i}"
            rows.append(rec)
    return rows, errs


def _key(rec: dict) -> str:
    return json.dumps({k: v for k, v in rec.items() if not k.startswith("_")}, sort_keys=True, ensure_ascii=False)


def validate_all(rows: list[dict], require_snapshot: bool = True) -> tuple[list[dict], list[str], dict]:
    """(valid rows without exact duplicates, errors, stats)."""
    errors, valid, seen, dupes = [], [], set(), 0
    for r in rows:
        errs = validate_record(r, require_snapshot)
        if errs:
            errors += [f"{r['_where']} [{r.get('table')} {r.get('model_id')}]: {x}" for x in errs]
            continue
        k = _key(r)
        if k in seen:
            dupes += 1
            continue
        seen.add(k)
        valid.append(r)
    # the canonical file (00_*.jsonl) defines a model once and for all; elsewhere a differing definition is an error
    # unless the canonical file overrides it (recorded in the stats)
    models: dict[str, dict] = {}
    canonical = {r["model_id"] for r in valid if r["table"] == "model" and str(r["_where"]).startswith("00_")}
    overridden, keep = [], []
    for r in sorted(valid, key=lambda r: not str(r["_where"]).startswith("00_")):
        if r["table"] != "model":
            continue
        ident = {f: r.get(f) for f in ("brand", "model", "segment")}
        prev = models.get(r["model_id"])
        if prev and prev != ident:
            if r["model_id"] in canonical:
                overridden.append(f"{r['_where']}: {r['model_id']} {ident} -> canonical {prev}")
                r["_drop"] = True
                continue
            errors.append(f"{r['_where']}: model {r['model_id']} defined twice differently: {prev} vs {ident}")
        models.setdefault(r["model_id"], ident)
    valid = [r for r in valid if not r.pop("_drop", False)]
    for r in valid:
        if r["model_id"] not in models:
            errors.append(f"{r['_where']} [{r['table']}]: model_id {r['model_id']} has no `model` row")
    stats = {"rows": len(rows), "valid": len(valid), "duplicates": dupes, "errors": len(errors),
             "models": len(models), "overridden_models": overridden,
             "by_table": {t: sum(r["table"] == t for r in valid) for t in R.TABLES}}
    return valid, errors, stats
