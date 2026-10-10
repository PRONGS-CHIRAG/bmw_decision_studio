"""Cleaning: raw Feedback_Explorer rows -> two tidy tables.

labels   one row per (comment, feature, reason) with a polarity  -> verdicts
comments one row per comment with cleaned text + label sets      -> classifiers

Every rule below fixes an issue found while profiling the raw data; the
counts are written to reports/data_quality.json by `build`.
"""

import re

import numpy as np
import pandas as pd

from . import config, taxonomy

# ---------------------------------------------------------------- text rules
# Source C: structured survey answers. The prefix names the problem category
# (e.g. 'Parking brake - DTU/controls poorly located') -> direct label leakage.
C_PROBLEM = re.compile(
    r'^I had an? ?(?P<severity>very minor|minor|very serious|serious)? ?problem with '
    r'(?P<code>.+?):\s*"(?P<body>.*)"(?P<followup>[^"]*)$', re.S)
C_PROMPT = re.compile(r'^(?P<prompt>(?:What is the primary|If there was one).+?)\n:\s*"?(?P<body>.*?)"?\s*$', re.S)
# Source D: one-line answers wrapped in a template that names the topic and the
# stance ('I love most' vs 'could be most improved') -> a weak label, but leakage.
D_TEMPLATE = re.compile(
    r'^(?P<body>.*?)\s*That is (?:the )?one thing (?P<stance>I love most|do you love most|could be most improved) '
    r'about (?P<topic>.+?)\.?\s*$', re.S)
D_TOPIC_TAIL = re.compile(r'^the |\s*(?:(?:of|in) my (?:new )?vehicle|you get driving my new vehicle|my vehicle each time)$')
# Source B: call-centre notes. 'Customer stated that ...' boilerplate and the
# advisor's own reply ('Writer explained ...') are not customer voice.
B_PREFIX = re.compile(
    r'\b(?:the )?customer (?:stated|states|mentioned|commented|reported|reports|remarked|said|noted|'
    r'indicated|explained|expressed|added|shared|inquired|asked|also stated|also mentioned|further stated|'
    r'confirmed|advised|replied)(?: that)?\s*', re.I)
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
ADVISOR_SENTENCE = re.compile(r'^\s*(?:the )?(?:writer|wrtier|wirter|writter|witer)\b', re.I)   # incl. typos
# Conversational acknowledgements carry no product signal ('Customer agreed.', 'Customer thanked writer.')
CHATTER_SENTENCE = re.compile(
    r'^\s*customer (?:acknowledged|agreed|thanked|understood|answered|confirmed understanding|was (?:satisfied|appreciative|thankful)|'
    r'had no (?:further|other) questions|declined)\b[^.!?]*[.!?]?\s*$', re.I)

PROMPT_NAMES = {"What is the primary": "nps_reason", "If there was one": "message_to_bmw"}


def _normalise_whitespace(text: str) -> str:
    text = text.replace("\u3000", " ").replace("・", "- ").replace("▶", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def clean_text(text: str, source: str) -> dict:
    """Return customer-voice text plus any structured fields peeled off it."""
    out = {"text": text, "severity": None, "survey_problem_code": None, "survey_followup": None,
           "survey_prompt": None, "template_topic": None, "template_stance": None}
    if source == "Source C":
        m = C_PROBLEM.match(text)
        if m:
            out.update(text=m["body"], severity=m["severity"] or "unspecified",
                       survey_problem_code=m["code"].strip(),
                       survey_followup=(m["followup"].strip(" .") or None))
        else:
            m = C_PROMPT.match(text)
            if m:
                prompt = next(v for k, v in PROMPT_NAMES.items() if m["prompt"].startswith(k))
                out.update(text=m["body"], survey_prompt=prompt)
    elif source == "Source D":
        m = D_TEMPLATE.match(text)
        if m:
            topic = D_TOPIC_TAIL.sub("", D_TOPIC_TAIL.sub("", m["topic"].strip()))
            out.update(text=m["body"].rstrip(". "), template_topic=topic,
                       template_stance="improve" if "improved" in m["stance"] else "love")
    elif source == "Source B":
        kept = [s for s in SENTENCE_SPLIT.split(text) if not (ADVISOR_SENTENCE.match(s) or CHATTER_SENTENCE.match(s))]
        body = B_PREFIX.sub("", " ".join(kept))
        out["text"] = body if body.strip() else text
    out["text"] = _normalise_whitespace(out["text"])
    return out


def model_text(text: str) -> str:
    """Text the classifiers see: lower-cased so casing cannot reveal the source."""
    return re.sub(r"\s+", " ", text.lower()).strip()


# ---------------------------------------------------------------- tables
def build_tables(raw: pd.DataFrame):
    """Return (labels, comments, quality) from the stacked raw feedback."""
    q = {"raw_rows": int(len(raw)), "raw_unique_comments": int(raw["comment_id"].nunique())}
    df = raw.copy()

    # Constant / redundant columns. vfc_l2_l3 == feature + ' : ' + reason except
    # 5 rows that differ only in whitespace -> safe to drop.
    q["dropped_constant_columns"] = ["brand", "sales_description", "vfc_l2_l3", "file_model"]
    df = df.drop(columns=q["dropped_constant_columns"])
    df["engine"] = df["engine"].map(config.ENGINE_NAMES)
    df["market"] = df["country"].map(config.COUNTRY_TO_MARKET)
    # Label strings contain non-breaking spaces (e.g. 'ground\xa0clearance')
    for col in ["feature", "reason"]:
        nbsp = df[col].str.contains("\xa0", na=False)
        q[f"{col}_labels_with_nbsp"] = int(nbsp.sum())
        df[col] = df[col].str.replace("\xa0", " ").str.strip()

    # --- comment-level text cleaning (text is identical across a comment's rows)
    first = df.drop_duplicates("comment_id").set_index("comment_id")
    cleaned = pd.DataFrame([clean_text(t, s) for t, s in zip(first["text_raw"], first["source"])],
                           index=first.index)
    q["source_c_problem_prefix_stripped"] = int(cleaned["survey_problem_code"].notna().sum())
    q["source_c_prompt_stripped"] = int(cleaned["survey_prompt"].notna().sum())
    q["source_d_template_stripped"] = int(cleaned["template_topic"].notna().sum())
    q["source_b_comments"] = int((first["source"] == "Source B").sum())
    q["text_was_all_lowercase_share_by_source"] = (
        first.groupby("source")["text_raw"].apply(lambda s: round(float((s == s.str.lower()).mean()), 2)).to_dict())

    # --- label rows
    lab = df[df["feature"].notna()].copy()
    q["rows_without_any_vfc_label"] = int(df["feature"].isna().sum())
    q["rows_no_class_found"] = int((lab["feature"] == "no_class_found").sum())
    lab = lab[lab["feature"] != "no_class_found"]

    # 18 rows have a real label but no Feedback Type -> impute from the reason wording
    missing_type = lab["feedback_type"].isna()
    lab.loc[missing_type, "feedback_type"] = lab.loc[missing_type, "reason"].map(
        taxonomy.REASON_TO_FEEDBACK_TYPE_HINT)
    q["feedback_type_imputed_from_reason"] = int(missing_type.sum())
    lab = lab[lab["feedback_type"].notna()]

    lab["sentiment"] = lab["feedback_type"].map(config.SENTIMENT)
    lab["domain"] = lab["feature"].map(taxonomy.FEATURE_TO_DOMAIN)
    unmapped = sorted(lab.loc[lab["domain"].isna(), "feature"].unique())
    if unmapped:
        raise ValueError(f"Features missing from taxonomy.DOMAIN_FEATURES: {unmapped}")
    lab["reason_family"] = lab["reason"].map(taxonomy.REASON_TO_FAMILY).fillna("Other")
    lab["is_feature_label"] = ~lab["feature"].isin(config.NON_FEATURE_LABELS)

    # Wants rows whose reason is complaint-worded (e.g. 'Dislike: price-performance
    # ratio'): keep Feedback Type as polarity (it is the human judgement of intent),
    # keep the reason as the 'why'. Flag them so they can be audited.
    lab["flag_request_with_complaint_reason"] = (
        (lab["sentiment"] == "request") & (lab["reason"].map(taxonomy.reason_polarity) == "negative"))
    q["wants_rows_with_complaint_reason"] = int(lab["flag_request_with_complaint_reason"].sum())
    # EV-only features on combustion cars: often comparisons with a previous EV or
    # mild-hybrid talk. Flagged, not dropped.
    lab["flag_ev_feature_on_ice"] = lab["feature"].isin(taxonomy.EV_ONLY_FEATURES) & (lab["engine"] == "ICE")
    q["ev_feature_on_ice_rows"] = int(lab["flag_ev_feature_on_ice"].sum())

    meta_cols = ["comment_id", "source", "country", "market", "model", "engine"]
    labels = lab[meta_cols + ["feedback_type", "sentiment", "domain", "feature", "reason", "reason_family",
                              "is_feature_label", "flag_request_with_complaint_reason",
                              "flag_ev_feature_on_ice"]].copy()
    labels = labels.join(cleaned[["severity"]], on="comment_id")
    q["label_rows"] = int(len(labels))
    q["feature_label_rows"] = int(labels["is_feature_label"].sum())

    # --- comment table
    comments = first[["source", "country", "market", "model", "engine", "text_raw"]].join(cleaned)
    comments["text_model"] = comments["text"].map(model_text)
    sets = labels.groupby("comment_id").agg(
        feedback_types=("feedback_type", lambda s: sorted(set(s))),
        sentiments=("sentiment", lambda s: sorted(set(s))),
        domains=("domain", lambda s: sorted(set(s))),
        features=("feature", lambda s: sorted(set(s))),
        n_labels=("feature", "size"),
    )
    comments = comments.join(sets)
    comments["n_labels"] = comments["n_labels"].fillna(0).astype(int)
    for col in ["feedback_types", "sentiments", "domains", "features"]:
        comments[col] = comments[col].apply(lambda v: v if isinstance(v, list) else [])
    has_ncf = df.loc[df["feature"] == "no_class_found", "comment_id"].unique()
    comments["label_status"] = np.select(
        [comments["n_labels"] > 0, comments.index.isin(has_ncf)],
        ["labeled", "no_class_found_only"], default="unlabeled")
    comments["n_words"] = comments["text"].str.split().str.len()
    comments = comments.reset_index()

    q["comments_by_label_status"] = comments["label_status"].value_counts().to_dict()
    q["labels_per_labeled_comment"] = comments.loc[comments["n_labels"] > 0, "n_labels"].describe().round(2).to_dict()
    q["short_comments_under_4_words"] = int((comments["n_words"] < 4).sum())
    q["non_english_or_symbol_text"] = int(comments["text_raw"].str.contains(r"[\u3000-\u30ff\u4e00-\u9fff▶・]").sum())
    q["exact_duplicate_rows"] = int(raw.duplicated().sum())
    q["duplicate_texts_across_comment_ids"] = int(comments.duplicated("text").sum())
    return labels, comments, q


def market_weights(labels: pd.DataFrame, sales: pd.DataFrame, year: int = 2025) -> pd.DataFrame:
    """Sales share / feedback share per (model, market): >1 means under-represented feedback."""
    model_group = {"F70": "F70", "G60": "G60_G68", "G70": "G70"}
    s = sales[sales["year"] == year].copy()
    s["sales_share"] = s["volume"] / s.groupby("model_group")["volume"].transform("sum")
    per_comment = labels.drop_duplicates("comment_id")
    fb = per_comment.groupby(["model", "market"]).size().rename("comments").reset_index()
    fb["feedback_share"] = fb["comments"] / fb.groupby("model")["comments"].transform("sum")
    fb["model_group"] = fb["model"].map(model_group)
    out = fb.merge(s[["model_group", "market_code", "volume", "sales_share"]],
                   left_on=["model_group", "market"], right_on=["model_group", "market_code"], how="left")
    out["weight"] = out["sales_share"] / out["feedback_share"]
    return out[["model", "market", "comments", "feedback_share", "volume", "sales_share", "weight"]]
