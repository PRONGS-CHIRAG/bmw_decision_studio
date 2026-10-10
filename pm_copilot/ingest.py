"""Ingest the raw BMW workbooks / PDFs into tidy, analysis-ready tables.

Outputs (data/processed/):
  findings.csv   one row per (verbatim x classification) with signal, component, domain, region
  survey.csv     customer-study scores per region x model x attribute (0-10 scale + z vs. model mean)
  sales.csv      planned volumes per derivative x region x year
  equipment.csv  standard / optional equipment from the German price lists
  specs.csv      key technical values from the price lists
  manifest.json  source file hashes and row counts (written to the audit trail)
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

import pandas as pd

from . import taxonomy as tx
from .config import DERIVATIVES, PROCESSED_DIR, RAW_DIR, SEVERITY_MULTIPLIER, SOURCE_KIND, region_of
from .equipment import parse_option_list

FEEDBACK_COLUMNS = {
    "ID": "verbatim_id", "Source": "source", "Country": "country", "Derivate (e-code)": "derivative",
    "Engine Type": "powertrain", "Feedback Type": "feedback_type", "Customer Feedback": "text",
    "Vfc level2 Name": "component", "Vfc level3 Name": "issue",
}
POWERTRAIN = {"ICE": "ICE", "BEVE": "BEV", "PHEV": "PHEV"}


def _sha1(path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def _find_all(text: str, lexicon: dict[str, str]) -> str:
    return "|".join(name for name, rx in lexicon.items() if re.search(rx, text, re.I))


# --------------------------------------------------------------------------
# Feedback
# --------------------------------------------------------------------------
def load_feedback() -> pd.DataFrame:
    frames = []
    for path in sorted(RAW_DIR.glob("*_feedback_hackathon.xlsx")):
        df = pd.read_excel(path).rename(columns=FEEDBACK_COLUMNS)[list(FEEDBACK_COLUMNS.values())]
        df["source_file"] = path.name
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    df["text"] = df["text"].fillna("").astype(str).str.replace(" ", " ").str.replace(r"\s+", " ", regex=True).str.strip()
    df["country"] = df["country"].fillna("??").astype(str).str.upper().str.strip()
    df["region"] = df["country"].map(region_of)
    df["powertrain"] = df["powertrain"].map(POWERTRAIN).fillna("Unknown")
    df["source_kind"] = df["source"].map(SOURCE_KIND).fillna("other")
    for col in ("component", "issue"):  # labels contain non-breaking spaces
        df[col] = df[col].fillna("no_class_found" if col == "component" else "").astype(str)             .str.replace(r"\s+", " ", regex=True).str.strip()
    df["feedback_type"] = df["feedback_type"].fillna("").astype(str).str.strip()
    df["signal"] = [tx.signal_of(f, i) for f, i in zip(df["feedback_type"], df["issue"])]
    df["label_source"] = "vfc"

    # Source D answers carry no label: classify "love most / could be improved about <aspect>".
    is_d = (df["source"] == "Source D") & (df["signal"] == "none")
    for idx in df.index[is_d]:
        result = tx.classify_source_d(df.at[idx, "text"])
        if result:
            df.at[idx, "signal"], df.at[idx, "component"] = result
            df.at[idx, "issue"] = "Like (loyalty survey)" if result[0] == "praise" else "Improvement wish (loyalty survey)"
            df.at[idx, "label_source"] = "rule:source_d"

    df["severity"] = [tx.severity_of(t) if s == "Source C" else "" for t, s in zip(df["text"], df["source"])]
    df["severity_mult"] = df["severity"].map(SEVERITY_MULTIPLIER).fillna(1.0)
    df["domain"] = df["component"].map(tx.domain_of)
    df["scope_note"] = df["component"].map(tx.OUT_OF_SCOPE_COMPONENTS).fillna("")
    df.loc[df["issue"].str.lower().isin(tx.PRICING_ISSUES), "scope_note"] = "pricing (out of scope)"
    df["materials"] = [_find_all(t, tx.MATERIALS) for t in df["text"]]
    df["competitors"] = [_find_all(t, tx.COMPETITORS) for t in df["text"]]
    df["mentions_previous_bmw"] = df["text"].str.contains(tx.PREVIOUS_BMW)
    df["want_cue"] = df["text"].str.contains(tx.WANT_CUES)

    # A verbatim classified twice with the same label is one finding, not two.
    df = df.drop_duplicates(["verbatim_id", "component", "issue", "signal"]).reset_index(drop=True)
    df["finding_id"] = df["verbatim_id"] + "#" + (df.groupby("verbatim_id").cumcount() + 1).astype(str)
    return df


# --------------------------------------------------------------------------
# Customer studies
# --------------------------------------------------------------------------
_MODEL_CODE = re.compile(r"\b([FG]\d{2})\b")
US_SCALE = ["I Hate It", "A Failure", "Unsatisfactory", "Satisfactory", "Excellent", "Delightful", "I Love It"]


def load_survey() -> pd.DataFrame:
    path = RAW_DIR / "F70_G60_G68_G70_customer_studies.xlsx"
    rows: list[dict] = []

    # CN/EU 2025: attribute row, then a "Mean" row; columns grouped by dataset country.
    raw = pd.read_excel(path, sheet_name="CN_EU_2025", header=None)
    region_row, model_row = raw.iloc[1], raw.iloc[2]
    col_region, current = {}, None
    for c in range(1, raw.shape[1]):
        if pd.notna(region_row[c]):
            current = {"China": "CN", "EU": "EU"}.get(str(region_row[c]).strip(), str(region_row[c]))
        col_region[c] = current
    attr = None
    for r in range(2, raw.shape[0]):
        label = raw.iat[r, 0]
        if pd.isna(label):
            continue
        if str(label).strip() == "Mean":
            for c, region in col_region.items():
                m = _MODEL_CODE.search(str(model_row[c]))
                if m and pd.notna(raw.iat[r, c]):
                    rows.append({"study": "CN_EU_2025", "region": region, "model": m.group(1),
                                 "attribute": attr, "score_0_10": float(raw.iat[r, c]),
                                 "top2_box": None, "bottom3_box": None})
        else:
            attr = str(label).strip()  # row 2 doubles as the model header and first attribute

    # US 2025: per attribute a block of 7-point scale shares (% of sample) per model.
    raw = pd.read_excel(path, sheet_name="US_2025", header=None)
    models = {c: _MODEL_CODE.search(str(raw.iat[0, c])).group(1) for c in range(2, raw.shape[1])
              if _MODEL_CODE.search(str(raw.iat[0, c]))}
    r = 0
    while r < raw.shape[0]:
        label = raw.iat[r, 0]
        if pd.notna(label) and pd.isna(raw.iat[r, 1]):
            block = raw.iloc[r + 1:r + 9]
            shares = {str(row[0]).strip(): row for _, row in block.iterrows()}
            for c, model in models.items():
                p = [float(shares[s][c]) for s in US_SCALE if s in shares and pd.notna(shares[s][c])]
                if len(p) != 7 or sum(p) == 0:
                    continue
                mean_1_7 = sum((i + 1) * v for i, v in enumerate(p)) / sum(p)
                rows.append({"study": "US_2025", "region": "US", "model": model, "attribute": str(label).strip(),
                             "score_0_10": (mean_1_7 - 1) / 6 * 10, "top2_box": p[5] + p[6],
                             "bottom3_box": p[0] + p[1] + p[2]})
            r += 9
        else:
            r += 1

    df = pd.DataFrame(rows).dropna(subset=["attribute"])
    # z-score of each attribute within its (study, region, model) column, so "below average
    # for this car in this market" is comparable across the 0-10 means and the US 7-point scale.
    grp = df.groupby(["study", "region", "model"])["score_0_10"]
    df["model_mean"] = grp.transform("mean")
    df["z_vs_model"] = (df["score_0_10"] - df["model_mean"]) / grp.transform("std")
    return df


# --------------------------------------------------------------------------
# Sales
# --------------------------------------------------------------------------
def load_sales() -> pd.DataFrame:
    path = RAW_DIR / "sales_volumes.xlsx"
    sheet_to_deriv = {cfg["sales_sheet"]: code for code, cfg in DERIVATIVES.items()}
    frames = []
    for sheet in pd.ExcelFile(path).sheet_names:
        df = pd.read_excel(path, sheet_name=sheet)
        df["derivative"] = sheet_to_deriv.get(sheet, sheet)
        df["sales_sheet"] = sheet
        frames.append(df)
    df = pd.concat(frames, ignore_index=True).rename(columns={"market_code": "region"})
    return df[["derivative", "sales_sheet", "region", "market", "volume_2024", "volume_2025", "volume_2030"]]


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def build() -> dict:
    from . import model as rim
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    findings = load_feedback()
    review_model = rim.train(findings)          # learn the VFC hierarchy from labelled reviews
    findings = rim.augment(findings, review_model)  # label reviews the VFC left empty
    rim.save(review_model)
    rim.reset_cache()
    survey = load_survey()
    sales = load_sales()
    equipment, specs = [], []
    for code in DERIVATIVES:
        pdf = RAW_DIR / f"{code}_OptionList.PDF"
        if pdf.exists():
            items, sp = parse_option_list(pdf, code)
            equipment.append(items)
            specs.append(sp)
    equipment = pd.concat(equipment, ignore_index=True)
    specs = pd.concat(specs, ignore_index=True).drop_duplicates(["derivative", "spec", "values"])

    findings.to_csv(PROCESSED_DIR / "findings.csv", index=False)
    survey.to_csv(PROCESSED_DIR / "survey.csv", index=False)
    sales.to_csv(PROCESSED_DIR / "sales.csv", index=False)
    equipment.to_csv(PROCESSED_DIR / "equipment.csv", index=False)
    specs.to_csv(PROCESSED_DIR / "specs.csv", index=False)

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {p.name: _sha1(p) for p in sorted(RAW_DIR.iterdir()) if p.is_file()},
        "rows": {"findings": len(findings), "verbatims": int(findings["verbatim_id"].nunique()),
                 "survey": len(survey), "sales": len(sales), "equipment": len(equipment), "specs": len(specs)},
        "signals": findings["signal"].value_counts().to_dict(),
        "model": {k: review_model.card["metrics"][k]["top1_accuracy"] for k in rim.HEADS},
        "model_augmented": review_model.card.get("augmented", {}),
    }
    (PROCESSED_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
