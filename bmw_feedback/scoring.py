"""Feature health scoring: is a feature good or bad, controlling for the channel.

Why not just '% positive'? The four sources have very different base rates:
Source C (problem survey) contains no Likes at all, Source B (call notes) is
mostly Likes, and the F70 is covered only by Source A. A raw positive share
would mostly tell you which channel a feature is discussed in.

Method (indirect standardisation, as used for standardised mortality ratios):
    unit       = one (comment, feature, sentiment) triple
    b_s(c)     = share of sentiment c among all units from source s
    E_f(c)     = sum_s N_fs * b_s(c)    expected units of c given f's source mix
    O_f(c)     = observed units of c for feature f
    index_f(c) = (O_f(c) + k * index_domain(c)) / (E_f(c) + k)

index = 1.0 means "as expected for these channels"; 2.0 means twice as many
complaints as expected. At feature level the baselines b_s(c) and the domain
priors come from specific (non-umbrella) features only, because annotators
park most praise on umbrella labels such as 'Exterior design'. The pseudo-count k shrinks low-volume features toward
their domain (the cold-start fallback, analogous to borrowing from similar
buyers in the old Demandra pipeline).
"""

import numpy as np
import pandas as pd

from . import config, taxonomy

SENTIMENTS = ["positive", "negative", "request"]
VERDICTS = ["Bad", "Leaning bad", "Mixed", "Leaning good", "Good", "Not enough data"]


def feature_units(labels: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate to one unit per (comment, feature, sentiment)."""
    lab = labels[labels["is_feature_label"]]
    return lab.drop_duplicates(["comment_id", "feature", "sentiment"])


def _byar_interval(observed, expected, z=1.96):
    """Approximate 95% CI for observed/expected with Poisson observed counts."""
    o = np.asarray(observed, dtype=float)
    e = np.asarray(expected, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        lo = np.where(o > 0, o * (1 - 1 / (9 * o) - z / (3 * np.sqrt(o))) ** 3 / e, 0.0)
        o1 = o + 1
        hi = o1 * (1 - 1 / (9 * o1) + z / (3 * np.sqrt(o1))) ** 3 / e
    return lo, hi


def source_baselines(units: pd.DataFrame) -> pd.DataFrame:
    """Share of each sentiment per source (rows: source, cols: sentiment)."""
    tab = pd.crosstab(units["source"], units["sentiment"]).reindex(columns=SENTIMENTS, fill_value=0)
    return tab.div(tab.sum(axis=1), axis=0)


def _observed_expected(units: pd.DataFrame, keys: list, base: pd.DataFrame) -> pd.DataFrame:
    """Observed and expected unit counts per group in `keys` for each sentiment."""
    obs = units.pivot_table(index=keys, columns="sentiment", values="comment_id", aggfunc="count",
                            fill_value=0).reindex(columns=SENTIMENTS, fill_value=0)
    n_by_source = units.groupby(keys + ["source"]).size().unstack("source", fill_value=0)
    exp = n_by_source.reindex(columns=base.index, fill_value=0) @ base
    out = pd.concat({"obs": obs, "exp": exp.reindex(obs.index)}, axis=1)
    out.columns = [f"{a}_{b}" for a, b in out.columns]
    out["n_units"] = obs.sum(axis=1)
    out["n_comments"] = units.groupby(keys)["comment_id"].nunique()
    return out


def score(labels: pd.DataFrame, group_keys=("feature",), prior_keys=("domain",)) -> pd.DataFrame:
    """Score every group (default: feature) with indices, intervals and a verdict.

    group_keys can include 'model' or 'engine' for breakdowns; the prior is
    then taken at (domain + the same extra keys).
    """
    units = feature_units(labels)
    group_keys, prior_keys = list(group_keys), list(prior_keys)
    feature_level = "feature" in group_keys
    peers = units[~units["feature"].isin(taxonomy.UMBRELLA_FEATURES)] if feature_level else units
    base = source_baselines(peers)
    extra = [k for k in group_keys if k not in ("feature", "domain")]
    prior_keys = prior_keys + extra

    g = _observed_expected(units, group_keys, base)
    if prior_keys:
        p = _observed_expected(peers, prior_keys, base)
        for c in SENTIMENTS:
            p[f"prior_{c}"] = (p[f"obs_{c}"] + 1) / (p[f"exp_{c}"] + 1)
    else:                                   # top level: prior is "as expected"
        p = pd.DataFrame({f"prior_{c}": [1.0] for c in SENTIMENTS})

    if "domain" not in group_keys:
        dom = units.drop_duplicates(group_keys)[group_keys + ["domain"]].set_index(group_keys)["domain"]
        g = g.join(dom)
    g = g.reset_index()
    if prior_keys:
        g = g.merge(p[[f"prior_{c}" for c in SENTIMENTS]].reset_index(), on=prior_keys, how="left")
    else:
        g = g.merge(p, how="cross")

    if feature_level:
        g["is_umbrella"] = g["feature"].isin(taxonomy.UMBRELLA_FEATURES)
    k = config.PRIOR_STRENGTH
    overall = peers["sentiment"].value_counts(normalize=True).reindex(SENTIMENTS)
    for c in SENTIMENTS:
        g[f"index_{c}"] = (g[f"obs_{c}"] + k * g[f"prior_{c}"]) / (g[f"exp_{c}"] + k)
        g[f"ci_low_{c}"], g[f"ci_high_{c}"] = _byar_interval(g[f"obs_{c}"], g[f"exp_{c}"])
        g[f"raw_share_{c}"] = g[f"obs_{c}"] / g["n_units"]
    # Channel-adjusted shares: overall share x index, renormalised to sum to 1
    adj = pd.DataFrame({c: overall[c] * g[f"index_{c}"] for c in SENTIMENTS})
    adj = adj.div(adj.sum(axis=1), axis=0)
    for c in SENTIMENTS:
        g[f"adj_share_{c}"] = adj[c]

    # Which kind of 'bad'? Defect (engineering / quality) vs Difficult to Use (UX)
    neg = units[units["sentiment"] == "negative"]
    kind = pd.crosstab([neg[k_] for k_ in group_keys], neg["feedback_type"])
    kind = kind.reindex(columns=["Defect", "Difficult to Use"], fill_value=0)
    kind.columns = ["n_defect", "n_difficult_to_use"]
    g = g.merge(kind.reset_index(), on=group_keys, how="left")
    g[["n_defect", "n_difficult_to_use"]] = g[["n_defect", "n_difficult_to_use"]].fillna(0).astype(int)

    g["verdict"] = g.apply(_verdict, axis=1)
    g["confidence"] = pd.cut(g["n_comments"], [0, config.MIN_MENTIONS_FOR_VERDICT - 1, 29, 99, np.inf],
                             labels=["insufficient", "low", "medium", "high"]).astype(str)
    g["requested"] = ((g["n_comments"] >= config.MIN_MENTIONS_FOR_VERDICT)
                      & (g["index_request"] >= config.REQUEST_INDEX) & (g["ci_low_request"] > 1))
    order = {v: i for i, v in enumerate(VERDICTS)}
    return g.sort_values(["verdict", "n_comments"], key=lambda s: s.map(order) if s.name == "verdict" else -s)


def _verdict(row) -> str:
    """Bad / Good need the 95% interval to exclude 'as expected' (index 1.0);
    the 'Leaning' tiers only need the point estimate past a softer threshold."""
    neg, pos = row["index_negative"], row["index_positive"]
    if row["n_comments"] < config.MIN_MENTIONS_FOR_VERDICT:
        return "Not enough data"
    if neg >= config.BAD_INDEX and row["ci_low_negative"] > 1:
        return "Bad"
    if neg <= config.GOOD_NEG_INDEX and row["ci_high_negative"] < 1 and pos >= 1:
        return "Good"
    if neg >= config.LEAN_BAD_INDEX:
        return "Leaning bad"
    if neg <= config.LEAN_GOOD_NEG_INDEX and pos >= 1:
        return "Leaning good"
    return "Mixed"


def bad_kind(row) -> str:
    """'defect-led' / 'usability-led' / 'mixed' for the negative mentions of a feature."""
    total = row["n_defect"] + row["n_difficult_to_use"]
    if total == 0:
        return "none"
    share = row["n_defect"] / total
    return "defect-led" if share >= 0.6 else "usability-led" if share <= 0.4 else "defects and usability"


def reason_breakdown(labels: pd.DataFrame, feature: str, top: int = 3) -> dict:
    """Top reason families per sentiment for one feature (counts of comments)."""
    lab = labels[(labels["feature"] == feature) & labels["is_feature_label"]]
    out = {}
    for c in SENTIMENTS:
        sub = lab[lab["sentiment"] == c].drop_duplicates(["comment_id", "reason_family"])
        vc = sub["reason_family"].value_counts().head(top)
        detail = sub["reason"].value_counts().head(top)
        out[c] = {"families": vc.to_dict(), "reasons": detail.to_dict()}
    return out


def representative_quotes(labels: pd.DataFrame, comments: pd.DataFrame, feature: str, per_sentiment: int = 2) -> dict:
    """Short, single-topic cleaned quotes for each sentiment of a feature."""
    lab = labels[labels["feature"] == feature].drop_duplicates(["comment_id", "sentiment"])
    merged = lab.merge(comments[["comment_id", "text", "n_labels", "n_words"]], on="comment_id")
    merged = merged[(merged["n_words"] >= 6)]
    merged["focus"] = (merged["n_labels"] == 1).astype(int)
    merged["len_penalty"] = (merged["text"].str.len() - 140).abs()
    out = {}
    for c in SENTIMENTS:
        sub = merged[merged["sentiment"] == c].sort_values(["focus", "len_penalty"], ascending=[False, True])
        sub = sub.drop_duplicates("text").head(per_sentiment)
        out[c] = [{"comment_id": r.comment_id, "model": r.model, "source": r.source, "reason": r.reason,
                   "text": r.text} for r in sub.itertuples()]
    return out


def survey_crosscheck(survey_us: pd.DataFrame) -> pd.DataFrame:
    """Map US survey attributes onto feedback features (feature, model, top2, bottom3)."""
    rows = []
    for attr, feats in taxonomy.US_SURVEY_TO_FEATURES.items():
        for f in feats:
            rows.append({"survey_attribute": attr, "feature": f})
    m = pd.DataFrame(rows)
    return m.merge(survey_us, left_on="survey_attribute", right_on="attribute").drop(columns="attribute")
