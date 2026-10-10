"""Glass-box complaint-risk model: does price-list fitment explain complaints?

Unit: one (comment, feature, sentiment) triple from the human labels.
Target: the unit is a complaint (Defect / Difficult to Use).

Inputs
    context  source (channel), market, model, engine, domain
    PDF      fitment tier of the feature on the comment's model + engine
             (standard on all / some covered variants, optional, no listing,
             no curated link, variant not covered by the equipment tables),
             cheapest option price (EUR, DE list), price as % of base price,
             share of variants with the feature as standard, median base price

Model: Explainable Boosting Machine (a GAM: one additive shape function per
input, no interactions), so every prediction decomposes into per-input
contributions a PM can read.

Validation: GroupKFold by feature. PDF inputs are constant within
(feature, model, engine), so plain k-fold would let the model memorise feature
identity through them; grouping by feature asks the honest question 'does
fitment generalise to features the model has not seen?'. The context-only
model is the baseline; the PDF inputs are credited only with the gain beyond it.
"""

import json
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

from . import config, scoring, taxonomy

CONTEXT = ["source", "market", "model", "engine", "domain", "is_umbrella"]
PDF = ["fitment_tier", "option_price_eur", "option_price_pct_of_base", "share_standard", "base_price_eur"]
TIER_LABELS = {
    "standard_all": "Standard on all covered variants",
    "standard_some": "Standard on some variants",
    "optional": "Optional extra",
    "not_listed": "Linked, but not listed for this engine",
    "no_link": "No curated price-list link",
    "not_covered": "Variant not in equipment tables",
}
MODEL_FILE = "complaint_risk.joblib"                   # context only (production)
AUDIT_MODEL_FILE = "complaint_risk_with_pdf.joblib"    # context + PDF (audit only)


def unit_frame(labels: pd.DataFrame, fit_by_engine: pd.DataFrame, variants: pd.DataFrame,
               fitment: pd.DataFrame) -> pd.DataFrame:
    """Feature units joined to fitment on (feature, model, engine)."""
    units = scoring.feature_units(labels).copy()
    units["market"] = units["market"].fillna("Unknown")
    units["engine"] = units["engine"].fillna("Unknown")
    units["is_complaint"] = (units["sentiment"] == "negative").astype(int)
    # Umbrella labels ('Exterior design') collect praise and have no price-list item; without
    # this flag in the baseline, 'no_link' would get credit for umbrella-ness.
    units["is_umbrella"] = units["feature"].isin(taxonomy.UMBRELLA_FEATURES).map({True: "yes", False: "no"})

    covered = fitment[["model", "variant"]].drop_duplicates().merge(
        variants[["model", "variant", "engine"]], on=["model", "variant"])[["model", "engine"]].drop_duplicates()
    covered["covered"] = True
    linked = set(fit_by_engine["feature"])
    fe = fit_by_engine.rename(columns={"tier": "fitment_tier", "price_min_eur": "option_price_eur",
                                       "price_pct_of_base": "option_price_pct_of_base"})
    out = units.merge(fe[["feature", "model", "engine", "fitment_tier", "option_price_eur",
                          "option_price_pct_of_base", "share_standard"]],
                      on=["feature", "model", "engine"], how="left")
    out = out.merge(covered, on=["model", "engine"], how="left")
    out["covered"] = out["covered"].fillna(False).astype(bool)
    missing = out["fitment_tier"].isna()
    out.loc[missing & ~out["feature"].isin(linked), "fitment_tier"] = "no_link"
    out.loc[missing & out["feature"].isin(linked) & out["covered"], "fitment_tier"] = "not_listed"
    out.loc[~out["covered"], "fitment_tier"] = "not_covered"
    out.loc[~out["covered"], ["option_price_eur", "option_price_pct_of_base", "share_standard"]] = np.nan
    out["has_link"] = out["feature"].isin(linked)

    base = (variants.groupby(["model", "engine"])["base_price_eur"].median().rename("base_price_eur").reset_index())
    out = out.merge(base, on=["model", "engine"], how="left")
    return out


def _ebm(features):
    from interpret.glassbox import ExplainableBoostingClassifier
    cat = [f for f in features if f in CONTEXT or f == "fitment_tier"]
    return ExplainableBoostingClassifier(
        feature_names=features, feature_types=["nominal" if f in cat else "continuous" for f in features],
        interactions=0, outer_bags=8, random_state=config.RANDOM_STATE, n_jobs=-1)


def _compare(frame: pd.DataFrame, n_splits: int) -> dict:
    y, groups = frame["is_complaint"].to_numpy(), frame["feature"].to_numpy()
    folds = list(GroupKFold(n_splits).split(frame, y, groups))
    out = {"n_units": int(len(frame)), "n_features": int(frame["feature"].nunique()),
           "complaint_rate": round(float(y.mean()), 3), "folds": n_splits, "variants": {}}
    for name, feats in {"context_only": CONTEXT, "context_plus_pdf": CONTEXT + PDF}.items():
        aucs, losses = [], []
        for tr, te in folds:
            m = _ebm(feats).fit(frame.iloc[tr][feats], y[tr])
            p = m.predict_proba(frame.iloc[te][feats])[:, 1]
            aucs.append(roc_auc_score(y[te], p))
            losses.append(log_loss(y[te], p))
        out["variants"][name] = {"auc_mean": round(float(np.mean(aucs)), 4), "auc_sd": round(float(np.std(aucs)), 4),
                                 "auc_by_fold": [round(float(a), 4) for a in aucs],
                                 "log_loss_mean": round(float(np.mean(losses)), 4)}
    v = out["variants"]
    gain = [b - a for a, b in zip(v["context_only"]["auc_by_fold"], v["context_plus_pdf"]["auc_by_fold"])]
    out["pdf_auc_gain_mean"] = round(float(np.mean(gain)), 4)
    out["pdf_auc_gain_by_fold"] = [round(float(g), 4) for g in gain]
    out["pdf_gain_positive_folds"] = int(sum(g > 0 for g in gain))
    return out


def evaluate(frame: pd.DataFrame, n_splits: int = 5) -> dict:
    """GroupKFold-by-feature AUC / log loss for context-only vs context + PDF.

    Run twice: on all feature units, and on units of features that have a
    curated price-list link (so 'no_link' cannot carry the result).
    """
    warnings.filterwarnings("ignore", message="Missing values detected")
    linked = frame[frame["has_link"]]
    return {"all_features": _compare(frame, n_splits), "linked_features_only": _compare(linked, n_splits)}


def value_check(frame: pd.DataFrame, labels: pd.DataFrame) -> dict:
    """'Poor value / missing equipment' labels by fitment tier (any sentiment).

    Where price-list fitment should matter most: the family holds 'Vehicle
    equipment: not standard / too costly'. Reported so the PM can see whether
    the data can test it at all.
    """
    lab = labels[labels["is_feature_label"]].drop_duplicates(["comment_id", "feature", "reason"])
    pv = lab[lab["reason_family"] == "Poor value / missing equipment"]
    tiers = frame[["comment_id", "feature", "fitment_tier"]].drop_duplicates(["comment_id", "feature"])
    f = pv.merge(tiers, on=["comment_id", "feature"], how="left")
    return {"n_labels": int(len(pv)), "by_sentiment": pv["sentiment"].value_counts().to_dict(),
            "by_reason": pv["reason"].value_counts().to_dict(),
            "by_fitment_tier": f["fitment_tier"].fillna("unknown").value_counts().to_dict()}


def fit_and_save(frame: pd.DataFrame) -> None:
    """Production model: context only (the PDF inputs showed no held-out gain).

    The context + PDF variant is fitted too and kept as an audited artifact so its
    shape functions can be inspected, but it is never used for PM-facing scores.
    """
    warnings.filterwarnings("ignore", message="Missing values detected")
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for path, feats in ((MODEL_FILE, CONTEXT), (AUDIT_MODEL_FILE, CONTEXT + PDF)):
        model = _ebm(feats).fit(frame[feats], frame["is_complaint"])
        joblib.dump({"model": model, "features": feats}, config.MODELS_DIR / path)


def load(audit: bool = False):
    path = config.MODELS_DIR / (AUDIT_MODEL_FILE if audit else MODEL_FILE)
    return joblib.load(path) if path.exists() else None


def global_explanation(bundle) -> list:
    """Per input: importance (mean |contribution|) and its shape function (bins -> log-odds)."""
    model = bundle["model"]
    imp = model.term_importances()
    out = []
    for i, name in enumerate(model.term_names_):
        scores = model.term_scores_[i]
        bins = model.bins_[i][0]
        if isinstance(bins, dict):           # nominal: category -> bin index
            shape = [{"bin": str(k), "score": round(float(scores[v]), 4)} for k, v in bins.items()]
        else:                                # continuous: cut points; scores[0] = missing, [-1] = unseen
            edges = [-np.inf] + list(bins) + [np.inf]
            shape = [{"bin": f"{_fmt(edges[j])} – {_fmt(edges[j + 1])}", "low": _num(edges[j]),
                      "high": _num(edges[j + 1]), "score": round(float(scores[j + 1]), 4)}
                     for j in range(len(edges) - 1)]
            shape.insert(0, {"bin": "missing", "score": round(float(scores[0]), 4)})
        out.append({"term": name, "importance": round(float(imp[i]), 4), "shape": shape})
    return sorted(out, key=lambda t: -t["importance"])


def _num(v):
    return None if not np.isfinite(v) else round(float(v), 2)


def _fmt(v):
    return "−∞" if v == -np.inf else "∞" if v == np.inf else f"{v:,.2f}"


def explain_rows(bundle, rows: pd.DataFrame) -> list:
    """Local explanations: intercept + per-input contribution (log-odds) -> probability."""
    model, feats = bundle["model"], bundle["features"]
    X = rows[feats]
    p = model.predict_proba(X)[:, 1]
    contrib = model.eval_terms(X)
    out = []
    for i in range(len(X)):
        terms = [{"term": t, "value": _jsonable(X.iloc[i][t]), "contribution": round(float(contrib[i, j]), 4)}
                 for j, t in enumerate(model.term_names_)]
        out.append({"intercept": round(float(model.intercept_[0]), 4), "probability": round(float(p[i]), 4),
                    "terms": sorted(terms, key=lambda t: -abs(t["contribution"]))})
    return out


def _jsonable(v):
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else round(float(v), 2)
    if isinstance(v, np.integer):
        return int(v)
    return v


def save_report(metrics: dict, path) -> None:
    path.write_text(json.dumps(metrics, indent=2))
