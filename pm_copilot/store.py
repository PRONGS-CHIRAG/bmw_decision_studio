"""Read access to the processed tables plus small lookup helpers shared by the
feature brief and the requirement builder."""
from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from . import taxonomy as tx
from .config import DERIVATIVES, MIN_REGION_BASE, PROCESSED_DIR, RAW_DIR, REGIONS
from .equipment import equipment_status


class DataNotBuilt(RuntimeError):
    pass


@dataclass
class Data:
    findings: pd.DataFrame
    survey: pd.DataFrame
    sales: pd.DataFrame
    equipment: pd.DataFrame
    specs: pd.DataFrame
    manifest: dict

    # ---------------------------------------------------------------- bases
    def scope(self, derivative: str | None = None, powertrain: str | None = None) -> pd.DataFrame:
        f = self.findings
        if derivative:
            f = f[f["derivative"] == derivative]
        if powertrain:
            f = f[f["powertrain"] == powertrain]
        return f

    def verbatim_base(self, derivative: str | None = None, powertrain: str | None = None) -> dict[str, int]:
        """Unique verbatims per region: the denominator for every rate."""
        f = self.scope(derivative, powertrain)
        counts = f.groupby("region")["verbatim_id"].nunique().to_dict()
        return {r: int(counts.get(r, 0)) for r in REGIONS}

    @staticmethod
    def covered(base: dict[str, int]) -> dict[str, bool]:
        return {r: base.get(r, 0) >= MIN_REGION_BASE for r in REGIONS}

    # ---------------------------------------------------------------- sales
    def volumes(self, derivative: str, horizon: str) -> dict[str, int]:
        s = self.sales[self.sales["derivative"] == derivative]
        col = f"volume_{horizon}"
        return {r: int(s.loc[s["region"] == r, col].sum()) for r in REGIONS}

    # ---------------------------------------------------------------- survey
    def survey_for(self, derivative: str, prefixes: list[str] | tuple[str, ...]) -> pd.DataFrame:
        """Survey rows for the derivative (per region model, e.g. G68 in China) matching prefixes."""
        models = DERIVATIVES[derivative]["survey_models"]
        s = self.survey
        mask = pd.Series(False, index=s.index)
        for region, model in models.items():
            mask |= (s["region"] == region) & (s["model"] == model)
        s = s[mask]
        if not prefixes:
            return s.iloc[0:0]
        pref = tuple(p.lower() for p in prefixes)
        return s[s["attribute"].str.lower().str.startswith(pref)]

    def _memo(self, name: str, key, compute):
        cache = self.__dict__.setdefault("_memo_" + name, {})
        if key not in cache:
            cache[key] = compute()
        return cache[key]

    def survey_by_region(self, derivative: str, prefixes) -> dict[str, dict]:
        return self._memo("survey", (derivative, tuple(prefixes or ())),
                          lambda: self._survey_by_region(derivative, prefixes))

    def _survey_by_region(self, derivative: str, prefixes) -> dict[str, dict]:
        rows = self.survey_for(derivative, prefixes)
        out = {}
        for region, grp in rows.groupby("region"):
            out[region] = {
                "attributes": [
                    {"attribute": r.attribute, "score": round(r.score_0_10, 2), "z": round(r.z_vs_model, 2),
                     "top2_box": None if pd.isna(r.top2_box) else round(r.top2_box, 3),
                     "bottom3_box": None if pd.isna(r.bottom3_box) else round(r.bottom3_box, 3),
                     "study": r.study, "model": r.model}
                    for r in grp.itertuples()],
                "mean_z": round(float(grp["z_vs_model"].mean()), 2),
                "mean_score": round(float(grp["score_0_10"].mean()), 2),
            }
        return out

    # ---------------------------------------------------------------- equipment
    def n_variants(self, derivative: str) -> int:
        e = self.equipment[(self.equipment["derivative"] == derivative) & (self.equipment["kind"] == "standard")]
        return int((e["n_standard"] + e["n_optional"]).max()) if not e.empty else 0

    def equipment_match(self, derivative: str, terms) -> dict:
        return self._memo("equipment", (derivative, tuple(terms or ())),
                          lambda: self._equipment_match(derivative, terms))

    def _equipment_match(self, derivative: str, terms) -> dict:
        e = self.equipment[self.equipment["derivative"] == derivative]
        if not terms or e.empty:
            return {"status": "no equipment terms" if not terms else "not in price list", "items": []}
        rx = "|".join(re.escape(t) for t in terms)
        by_name = e[e["name"].str.contains(rx, case=False, regex=True)]
        in_package = e[~e.index.isin(by_name.index) & e["details"].fillna("").str.contains(rx, case=False, regex=True)
                       & e["kind"].eq("options")]
        rows = pd.concat([by_name, in_package])
        items = [{"name": r.name, "kind": r.kind, "in_package": i >= len(by_name),
                  "price_eur": None if pd.isna(r.price_eur) else r.price_eur, "sa_code": r.sa_code or None,
                  "n_standard": int(r.n_standard), "n_optional": int(r.n_optional), "page": int(r.page),
                  "source": r.source}
                 for i, r in enumerate(rows.itertuples())]
        status = equipment_status(by_name, self.n_variants(derivative)) if not by_name.empty else (
            "optional, only within a package" if not in_package.empty else "not in price list")
        return {"status": status, "items": items[:8], "market": "DE price list (EU baseline), 07/2026"}

    def offered_on_other_derivatives(self, derivative: str, terms) -> list[str]:
        others = [d for d in DERIVATIVES if d != derivative]
        return [d for d in others if self.equipment_match(d, terms)["status"] not in
                ("not in price list", "no equipment terms")]

    def specs_for(self, derivative: str) -> dict[str, str]:
        s = self.specs[self.specs["derivative"] == derivative]
        return {r.spec: r.values for r in s.drop_duplicates("spec").itertuples()}


@lru_cache(maxsize=1)
def load() -> Data:
    if not (PROCESSED_DIR / "findings.csv").exists():
        raise DataNotBuilt("Processed data missing - run `python -m pm_copilot build` first.")
    read = lambda name: pd.read_csv(PROCESSED_DIR / name, keep_default_na=False, na_values=[""])
    findings = read("findings.csv")
    for col in ("materials", "competitors", "severity", "scope_note", "issue", "feedback_type", "text"):
        findings[col] = findings[col].fillna("")
    findings["confidence"] = findings["confidence"].fillna(1.0) if "confidence" in findings else 1.0
    for col in ("mentions_previous_bmw", "want_cue"):
        findings[col] = findings[col].astype(str).str.lower().eq("true")
    zones = {c: tx.zone_of(c, d) for c, d in findings[["component", "domain"]].drop_duplicates().itertuples(index=False)}
    findings["zone"] = findings["component"].map(zones).where(findings["component"] != "no_class_found", "")
    equipment = read("equipment.csv")
    equipment["details"] = equipment["details"].fillna("")
    equipment["sa_code"] = equipment["sa_code"].fillna("")
    return Data(findings=findings, survey=read("survey.csv"), sales=read("sales.csv"), equipment=equipment,
                specs=read("specs.csv"),
                manifest=json.loads((PROCESSED_DIR / "manifest.json").read_text(encoding="utf-8")))


def reload() -> Data:
    load.cache_clear()
    return load()


_runtime_cache: dict = {}


def load_runtime() -> Data:
    """Read private source files in memory, with exact provenance and no model or writes.

    Hashes are checked on each access, so a changed workbook creates a new input snapshot.
    The legacy build command is not used and tracked processed files are never refreshed.
    """
    from . import ingest
    from .equipment import parse_option_list

    if not RAW_DIR.is_dir():
        raise DataNotBuilt("BMW-Data is missing. Supply the original private BMW data directory.")
    paths = sorted(p for p in RAW_DIR.iterdir()
                   if p.is_file() and p.suffix.lower() in {".xlsx", ".pdf"})
    required = {"F70_G60_G68_G70_customer_studies.xlsx", "sales_volumes.xlsx"}
    missing = sorted(required - {p.name for p in paths})
    if missing or not list(RAW_DIR.glob("*_feedback_hackathon.xlsx")):
        raise DataNotBuilt("Required BMW source data is missing: " + ", ".join(missing or ["feedback workbooks"]))
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    key = tuple(hashes.items())
    if _runtime_cache.get("key") == key:
        return _runtime_cache["data"]
    try:
        findings = ingest.load_feedback()
        survey = ingest.load_survey()
        sales = ingest.load_sales()
        equipment, specs = [], []
        for code in DERIVATIVES:
            path = RAW_DIR / f"{code}_OptionList.PDF"
            if path.exists():
                items, values = parse_option_list(path, code)
                equipment.append(items)
                specs.append(values)
    except Exception as exc:
        raise DataNotBuilt(f"BMW source ingestion failed: {type(exc).__name__}: {exc}") from exc
    manifest = {"sources": hashes, "reader_version": "raw-evidence-1",
                "ingestion_report": findings.attrs.get("ingestion_report", {})}
    data = Data(findings=findings, survey=survey, sales=sales,
                equipment=pd.concat(equipment, ignore_index=True) if equipment else pd.DataFrame(),
                specs=pd.concat(specs, ignore_index=True) if specs else pd.DataFrame(), manifest=manifest)
    _runtime_cache.update(key=key, data=data)
    return data

