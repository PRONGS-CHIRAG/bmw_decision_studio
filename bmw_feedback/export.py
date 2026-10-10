"""Export the scored tables as JSON row files for the interactive dashboard.

python -m bmw_feedback export  ->  data/processed/dashboard/*.json
"""

import json

import pandas as pd

from . import config, scoring, taxonomy
from .verdict import load_context

OUT_DIR = config.PROCESSED_DIR / "dashboard"


def _families(card, sentiment):
    fam = card["reasons"][sentiment]["families"]
    return "; ".join(f"{k} ({v})" for k, v in fam.items())


def _quote(card, sentiment):
    qs = card["quotes"][sentiment]
    if not qs:
        return "", ""
    q = qs[0]
    return q["text"][:320], f"{q['model']} · {q['source']} · {q['reason']}"


def _mix(row):
    total = row["n_defect"] + row["n_difficult_to_use"]
    defect_share = row["n_defect"] / total if total else 0.5
    return {
        "share_defect": round(row["adj_share_negative"] * defect_share, 4),
        "share_dtu": round(row["adj_share_negative"] * (1 - defect_share), 4),
        "share_wants": round(row["adj_share_request"], 4),
        "share_likes": round(row["adj_share_positive"], 4),
    }


def export_dashboard() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ctx = load_context()
    quality = json.loads((config.REPORTS_DIR / "data_quality.json").read_text())
    metrics = json.loads((config.REPORTS_DIR / "classifier_metrics.json").read_text())

    feats = ctx.features.reset_index()
    rows = []
    for r in feats.itertuples():
        card = ctx.feature_card(r.feature)
        ql, qlm = _quote(card, "positive")
        qc, qcm = _quote(card, "negative")
        qr, qrm = _quote(card, "request")
        rows.append({
            "feature": r.feature, "domain": r.domain, "domain_short": taxonomy.DOMAIN_SHORT[r.domain],
            "umbrella": bool(r.is_umbrella), "n_comments": int(r.n_comments),
            "complaint_index": round(r.index_negative, 2), "ci_low": round(r.ci_low_negative, 2),
            "ci_high": round(min(r.ci_high_negative, 99), 2), "praise_index": round(r.index_positive, 2),
            "request_index": round(r.index_request, 2), "verdict": r.verdict, "confidence": r.confidence,
            "requested": bool(r.requested), "bad_kind": scoring.bad_kind(feats.loc[r.Index]),
            **_mix(feats.loc[r.Index]),
            "likes_reasons": _families(card, "positive"), "complaint_reasons": _families(card, "negative"),
            "request_reasons": _families(card, "request"),
            "quote_like": ql, "quote_like_meta": qlm, "quote_complaint": qc, "quote_complaint_meta": qcm,
            "quote_request": qr, "quote_request_meta": qrm,
            "by_model": " · ".join(f"{b['group']}: {b['verdict']} ({b['complaint_index']}, n={b['n_comments']})"
                                   for b in card["by_model"]),
            "summary": card["summary"],
        })
    _write("features", rows)

    dom = ctx.domains.reset_index()
    neg = ctx.labels[ctx.labels["is_feature_label"] & (ctx.labels["sentiment"] == "negative")]
    top_reason = neg.drop_duplicates(["comment_id", "domain", "reason_family"]).groupby("domain")["reason_family"] \
        .agg(lambda s: s.value_counts().index[0])
    _write("domains", [{
        "domain": r.domain, "domain_short": taxonomy.DOMAIN_SHORT[r.domain], "n_comments": int(r.n_comments),
        "complaint_index": round(r.index_negative, 2), "ci_low": round(r.ci_low_negative, 2),
        "ci_high": round(r.ci_high_negative, 2), "praise_index": round(r.index_positive, 2),
        "request_index": round(r.index_request, 2), "verdict": r.verdict,
        "n_defect": int(r.n_defect), "n_dtu": int(r.n_difficult_to_use),
        "top_complaint_reason": top_reason.get(r.domain, ""), **_mix(dom.loc[r.Index]),
    } for r in dom.itertuples()])

    dm = scoring.score(ctx.labels, group_keys=("domain", "model"), prior_keys=())
    _write("domain_model", [{
        "domain": r.domain, "domain_short": taxonomy.DOMAIN_SHORT[r.domain], "model": r.model,
        "model_name": config.MODEL_NAMES[r.model], "complaint_index": round(r.index_negative, 2),
        "n_comments": int(r.n_comments), "verdict": r.verdict,
    } for r in dm.itertuples()])

    comp = ctx.comments.groupby(["model", "source"]).size().rename("comments").reset_index()
    _write("composition", [{"model": r.model, "model_name": config.MODEL_NAMES[r.model], "source": r.source,
                            "comments": int(r.comments)} for r in comp.itertuples()])

    sales = pd.read_csv(config.PROCESSED_DIR / "sales.csv")
    s = sales[sales["year"] == 2025].copy()
    s["sales_share"] = s["volume"] / s.groupby("model_group")["volume"].transform("sum")
    fb = ctx.labels.drop_duplicates("comment_id").groupby(["model", "market"]).size().rename("n").reset_index()
    fb["feedback_share"] = fb["n"] / fb.groupby("model")["n"].transform("sum")
    group = {"F70": "F70", "G60": "G60_G68", "G70": "G70"}
    markets = []
    for model in config.MODELS:
        for market in ["EU", "US", "CN", "RoW"]:
            ss = s[(s["model_group"] == group[model]) & (s["market_code"] == market)]["sales_share"].sum()
            fs = fb[(fb["model"] == model) & (fb["market"] == market)]["feedback_share"].sum()
            if ss > 0 or fs > 0:
                markets.append({"key": f"{model}-{market}", "model": model, "market": market,
                                "sales_share": round(float(ss), 4), "feedback_share": round(float(fs), 4)})
    _write("markets", markets)

    t = metrics["tasks"]
    names = {"feedback_type": "Feedback type", "domain": "Domain", "feature": "Feature"}
    _write("classifier", [{
        "task": names[k], "labels": v["n_labels"], "cv_micro_f1": v["micro_f1"], "macro_f1": v["macro_f1"],
        "a_to_b": v["cross_source"][0]["micro_f1"], "b_to_a": v["cross_source"][1]["micro_f1"],
        "baseline": v["majority_baseline_micro_f1"], "top1": v["top1_hit"], "top3": v["top3_hit"],
    } for k, v in t.items()])

    q = quality
    _write("quality", [
        {"issue": "One row per label, not per comment", "affected": q["raw_rows"],
         "fix": f"Reshaped to {q['raw_unique_comments']:,} comments + one row per label"},
        {"issue": "'no_class_found' placeholder rows", "affected": q["rows_no_class_found"],
         "fix": "Dropped from labels; comments with nothing else go to the unlabelled pool"},
        {"issue": "Comments with no label at all", "affected": q["comments_by_label_status"]["unlabeled"],
         "fix": "Unlabelled pool, classified by the trained model"},
        {"issue": "Problem category written into Source C text (label leakage)",
         "affected": q["source_c_problem_prefix_stripped"], "fix": "Prefix stripped; severity and code kept"},
        {"issue": "Survey prompt prepended to Source C answers", "affected": q["source_c_prompt_stripped"],
         "fix": "Prompt stripped; prompt type kept"},
        {"issue": "Template sentence wrapped around Source D answers", "affected": q["source_d_template_stripped"],
         "fix": "Template stripped; topic and love/improve stance kept as weak labels"},
        {"issue": "Advisor replies and boilerplate in Source B call notes", "affected": q["source_b_comments"],
         "fix": "'Writer …' sentences, 'Customer stated that' and acknowledgements removed"},
        {"issue": "Feedback type missing on labelled rows", "affected": q["feedback_type_imputed_from_reason"],
         "fix": "Imputed from the reason wording"},
        {"issue": "'Wants' rows with complaint-worded reasons", "affected": q["wants_rows_with_complaint_reason"],
         "fix": "Kept as requests; flagged for audit"},
        {"issue": "EV-only features labelled on combustion cars", "affected": q["ev_feature_on_ice_rows"],
         "fix": "Flagged, not dropped"},
        {"issue": "Non-breaking spaces inside feature labels", "affected": q["feature_labels_with_nbsp"],
         "fix": "Normalised"},
        {"issue": "Duplicate short notes across comment IDs", "affected": q["duplicate_texts_across_comment_ids"],
         "fix": "De-duplicated before classifier training"},
    ])

    verdicts = feats.loc[~feats["is_umbrella"], "verdict"].value_counts()
    _write("summary", [{
        "comments": q["raw_unique_comments"], "labelled_comments": q["comments_by_label_status"]["labeled"],
        "unlabelled_pool": q["comments_by_label_status"]["no_class_found_only"] + q["comments_by_label_status"]["unlabeled"],
        "features": int(len(feats)), "specific_features": int((~feats["is_umbrella"]).sum()),
        "domains": len(taxonomy.DOMAINS), "bad": int(verdicts.get("Bad", 0)),
        "leaning_bad": int(verdicts.get("Leaning bad", 0)), "mixed": int(verdicts.get("Mixed", 0)),
        "leaning_good": int(verdicts.get("Leaning good", 0)), "good": int(verdicts.get("Good", 0)),
        "not_enough": int(verdicts.get("Not enough data", 0)),
    }])
    print(f"  wrote {len(list(OUT_DIR.glob('*.json')))} files to {OUT_DIR.relative_to(config.ROOT)}/")


def _write(name, rows):
    (OUT_DIR / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False))
