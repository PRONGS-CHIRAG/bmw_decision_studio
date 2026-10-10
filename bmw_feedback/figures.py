"""Static figures for REPORT.md (reports/figures/*.png).

Colour roles (validated with the dataviz palette validator):
    categorical series  slot 1-4 of the reference palette
    sentiment           Defect dark red, Difficult to Use light red, Wants neutral gray, Likes blue
    verdict (diverging) Bad / Leaning bad / Mixed / Leaning good / Good
    magnitude           single-hue blue ramp
"""

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from . import config, scoring, taxonomy  # noqa: E402

# ---------------------------------------------------------------- tokens
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SENTIMENT_COLORS = {"Defect": "#a12f2f", "Difficult to Use": "#f5938c", "Wants": "#d6d5ce", "Likes": "#2a78d6"}
VERDICT_COLORS = {"Bad": "#a12f2f", "Leaning bad": "#f5938c", "Mixed": "#d6d5ce",
                  "Leaning good": "#86b6ef", "Good": "#1c5cab"}
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = LinearSegmentedColormap.from_list("blue_gray_red", ["#1c5cab", "#86b6ef", "#f0efec", "#f5938c", "#a12f2f"])
SEQUENTIAL = LinearSegmentedColormap.from_list("blue_seq", BLUE_RAMP)

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "font.size": 10,
    "text.color": INK, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": INK2,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 24,
    "legend.frameon": False, "legend.fontsize": 9, "grid.color": GRID, "grid.linewidth": 0.6,
    "xtick.major.size": 0, "ytick.major.size": 0,
})


def _subtitle(ax, text):
    ax.annotate(text, xy=(0, 1), xycoords="axes fraction", xytext=(0, 6), textcoords="offset points",
                fontsize=9.5, color=INK2, va="bottom")


def _label_points(ax, xs, ys, names, fontsize=7.8):
    """Direct-label selected points, nudging labels vertically until they stop overlapping."""
    renderer = ax.figure.canvas.get_renderer()
    placed = []
    for x, y, name in sorted(zip(xs, ys, names), key=lambda t: -t[1]):
        for dy in (3, -11, 12, -20, 21, -29, 30, -38):
            t = ax.annotate(name, (x, y), xytext=(6, dy), textcoords="offset points", fontsize=fontsize, color=INK2)
            box = t.get_window_extent(renderer).expanded(1.03, 1.15)
            if not any(box.overlaps(b) for b in placed):
                placed.append(box)
                break
            t.remove()
        else:
            ax.annotate(name, (x, y), xytext=(6, 3), textcoords="offset points", fontsize=fontsize, color=INK2)


def _save(fig, name):
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(config.FIGURES_DIR / name, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  reports/figures/{name}")


def _text_color(rgba):
    r, g, b = rgba[:3]
    return INK if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 0.55 else "white"


def _diverging_stack(ax, frame, order=("Defect", "Difficult to Use", "Wants", "Likes")):
    """Diverging stacked bars centred on the neutral 'Wants' segment (shares sum to 1)."""
    y = np.arange(len(frame))
    left = -(frame["Defect"] + frame["Difficult to Use"] + frame["Wants"] / 2)
    for col in order:
        ax.barh(y, frame[col], left=left, height=0.62, color=SENTIMENT_COLORS[col],
                edgecolor=SURFACE, linewidth=2, label=col)
        for yi, (lv, wv) in enumerate(zip(left, frame[col])):
            if wv >= 0.09 and col != "Wants":
                ax.text(lv + wv / 2, yi, f"{wv:.0%}", ha="center", va="center", fontsize=8,
                        color=_text_color(matplotlib.colors.to_rgba(SENTIMENT_COLORS[col])))
        left = left + frame[col]
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.set_yticks(y, frame.index)
    ax.invert_yaxis()
    ax.set_xlim(-1, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{abs(v):.0%}"))
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)


# ---------------------------------------------------------------- figures
def fig_data_composition(comments):
    tab = pd.crosstab(comments["model"], comments["source"]).reindex(config.MODELS)
    tab.index = [config.MODEL_NAMES[m] for m in tab.index]
    fig, ax = plt.subplots(figsize=(9, 3.2))
    left = np.zeros(len(tab))
    for i, src in enumerate(tab.columns):
        ax.barh(tab.index, tab[src], left=left, height=0.6, color=SERIES[i], edgecolor=SURFACE, linewidth=2, label=src)
        for yi, (lv, v) in enumerate(zip(left, tab[src])):
            if v > 350:
                ax.text(lv + v / 2, yi, f"{v:,}", ha="center", va="center", fontsize=8.5,
                        color=_text_color(matplotlib.colors.to_rgba(SERIES[i])))
        left += tab[src].to_numpy()
    for yi, total in enumerate(left):
        ax.text(total + 40, yi, f"{int(total):,}", va="center", fontsize=9, color=INK2)
    ax.invert_yaxis()
    ax.set_xlabel("Comments")
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, -0.28))
    ax.set_title("Each model is heard through different channels")
    _subtitle(ax, "Unique comments by model and feedback source. F70 is Source A only; G60/G70 are mostly Source B.")
    _save(fig, "01_data_composition.png")


def fig_feedback_type_by_source(labels):
    units = labels.drop_duplicates(["comment_id", "feedback_type"])
    tab = pd.crosstab(units["source"], units["feedback_type"], normalize="index")
    tab = tab.reindex(columns=["Defect", "Difficult to Use", "Wants", "Likes"], fill_value=0)
    n = units.groupby("source")["comment_id"].nunique()
    tab.index = [f"{s} (n={n[s]:,})" for s in tab.index]
    fig, ax = plt.subplots(figsize=(9, 2.8))
    _diverging_stack(ax, tab)
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, -0.3))
    ax.set_title("Sources have very different base rates of praise and complaints")
    _subtitle(ax, "Share of labelled mentions by feedback type. Source C never contains Likes; Source D is unlabelled.")
    _save(fig, "02_feedback_type_by_source.png")


def _adjusted_frame(score_df, key):
    """Channel-adjusted sentiment mix split into the four feedback types."""
    neg_defect_share = score_df["n_defect"] / (score_df["n_defect"] + score_df["n_difficult_to_use"]).replace(0, np.nan)
    neg_defect_share = neg_defect_share.fillna(0.5)
    out = pd.DataFrame({
        "Defect": score_df["adj_share_negative"] * neg_defect_share,
        "Difficult to Use": score_df["adj_share_negative"] * (1 - neg_defect_share),
        "Wants": score_df["adj_share_request"],
        "Likes": score_df["adj_share_positive"],
    })
    out.index = score_df[key]
    return out


def fig_domain_overview(labels):
    d = scoring.score(labels, group_keys=("domain",), prior_keys=()).sort_values("index_negative", ascending=False)
    frame = _adjusted_frame(d, "domain")
    frame.index = [f"{taxonomy.DOMAIN_SHORT[x]}" for x in frame.index]
    fig, ax = plt.subplots(figsize=(10, 5.6))
    _diverging_stack(ax, frame)
    for yi, r in enumerate(d.itertuples()):
        ax.text(1.02, yi, f"{r.verdict}  ·  idx {r.index_negative:.2f}  ·  n={r.n_comments:,}",
                transform=ax.get_yaxis_transform(), va="center", fontsize=8.5, color=INK2)
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, -0.08))
    ax.set_title("Digital, access and ownership topics draw the most complaints; driving draws praise")
    _subtitle(ax, "Channel-adjusted sentiment mix per domain, sorted by complaint index (1.0 = as expected for the "
                  "channels). Includes umbrella labels.")
    _save(fig, "03_domain_overview.png")


def fig_feature_health_map(labels):
    f = scoring.score(labels)
    f = f[(~f["is_umbrella"]) & (f["verdict"] != "Not enough data")]
    fig, ax = plt.subplots(figsize=(11, 7))
    for verdict, color in VERDICT_COLORS.items():
        sub = f[f["verdict"] == verdict]
        ax.scatter(sub["n_comments"], sub["index_negative"], s=46, color=color, edgecolor=MUTED if verdict == "Mixed" else SURFACE,
                   linewidth=0.8 if verdict == "Mixed" else 2, label=f"{verdict} ({len(sub)})", zorder=3)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.axhline(1, color=AXIS, linewidth=1, zorder=1)
    ax.set_yticks([0.35, 0.5, 0.7, 1, 1.4, 2], ["0.35", "0.5", "0.7", "1.0", "1.4", "2.0"])
    ax.set_xticks([8, 15, 30, 60, 120, 250], ["8", "15", "30", "60", "120", "250"])
    ax.minorticks_off()
    ax.grid(True)
    ax.set_axisbelow(True)
    ax.set_xlabel("Comments mentioning the feature (log scale)")
    ax.set_ylabel("Complaint index (log scale; 1.0 = as expected)")
    ax.legend(loc="upper right", ncol=1, title="Verdict", title_fontsize=9)
    pick = pd.concat([f[f["verdict"].isin(["Bad", "Good"])], f.nlargest(10, "n_comments")]).drop_duplicates("feature")
    names = [n if len(n) <= 28 else n[:26] + "…" for n in pick["feature"]]
    _label_points(ax, pick["n_comments"], pick["index_negative"], names)
    ax.set_title("Feature health map: where complaints exceed what the channel mix predicts")
    _subtitle(ax, "Specific features with >= 8 comments. Above the line = more complaints than comparable features.")
    _save(fig, "04_feature_health_map.png")


def fig_top_features(labels, top=30):
    f = scoring.score(labels)
    f = f[(~f["is_umbrella"])].nlargest(top, "n_comments").sort_values("index_negative", ascending=False)
    frame = _adjusted_frame(f, "feature")
    frame.index = [x if len(x) <= 34 else x[:32] + "…" for x in frame.index]
    fig, ax = plt.subplots(figsize=(10.5, 10))
    _diverging_stack(ax, frame)
    for yi, r in enumerate(f.itertuples()):
        ax.text(1.02, yi, f"{r.verdict}  ·  {r.index_negative:.2f}  ·  n={r.n_comments}",
                transform=ax.get_yaxis_transform(), va="center", fontsize=8.3, color=INK2)
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, -0.04))
    ax.set_title(f"The {top} most-discussed specific features")
    _subtitle(ax, "Channel-adjusted sentiment mix, sorted by complaint index (right: verdict · index · comments).")
    _save(fig, "05_top_features.png")


def fig_reason_heatmap(labels):
    lab = labels[labels["is_feature_label"] & (labels["sentiment"] == "negative")]
    lab = lab.drop_duplicates(["comment_id", "feature", "reason_family"])
    tab = pd.crosstab(lab["domain"], lab["reason_family"], normalize="index")
    tab = tab.loc[:, tab.max() >= 0.03]                      # drop families that never reach 3%
    tab = tab.loc[:, tab.sum().sort_values(ascending=False).index]
    tab.index = [taxonomy.DOMAIN_SHORT[d] for d in tab.index]
    fig, ax = plt.subplots(figsize=(11, 5.4))
    cmap = SEQUENTIAL.copy()
    cmap.set_bad(SURFACE)
    im = ax.imshow(np.ma.masked_less(tab.to_numpy(), 0.005), cmap=cmap, vmin=0, vmax=0.8, aspect="auto")
    ax.set_xticks(range(tab.shape[1]), tab.columns, rotation=35, ha="right")
    ax.set_yticks(range(tab.shape[0]), tab.index)
    for (i, j), v in np.ndenumerate(tab.to_numpy()):
        if v >= 0.05:
            ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=8, color=_text_color(im.cmap(im.norm(v))))
    ax.spines[:].set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01, format=matplotlib.ticker.PercentFormatter(1.0))
    cb.outline.set_visible(False)
    ax.set_title("Why customers complain, by domain")
    _subtitle(ax, "Share of each domain's complaints by reason family (VFC level-3 grouped). Rare families omitted.")
    _save(fig, "06_complaint_reasons_by_domain.png")


def fig_domain_by_model(labels):
    d = scoring.score(labels, group_keys=("domain", "model"), prior_keys=())
    idx = d.pivot(index="domain", columns="model", values="index_negative").reindex(columns=config.MODELS)
    n = d.pivot(index="domain", columns="model", values="n_comments").reindex(columns=config.MODELS)
    order = idx.mean(axis=1).sort_values(ascending=False).index
    idx, n = idx.loc[order], n.loc[order]
    fig, ax = plt.subplots(figsize=(7.5, 5.6))
    norm = TwoSlopeNorm(vcenter=0, vmin=-1.1, vmax=1.1)
    im = ax.imshow(np.log(idx.to_numpy()), cmap=DIVERGING, norm=norm, aspect="auto")
    for (i, j), v in np.ndenumerate(idx.to_numpy()):
        weak = n.iloc[i, j] < 30
        ax.text(j, i, f"{v:.2f}" + ("*" if weak else "") + f"\nn={int(n.iloc[i, j])}", ha="center", va="center",
                fontsize=8, color=_text_color(im.cmap(norm(np.log(v)))))
    ax.set_xticks(range(3), [config.MODEL_NAMES[m] for m in config.MODELS])
    ax.set_yticks(range(len(idx)), [taxonomy.DOMAIN_SHORT[x] for x in idx.index])
    ax.spines[:].set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02, ticks=np.log([0.4, 0.7, 1, 1.4, 2.5]))
    cb.ax.set_yticklabels(["0.4", "0.7", "1.0", "1.4", "2.5"])
    cb.outline.set_visible(False)
    ax.set_title("Complaint index by domain and model")
    _subtitle(ax, "Red = more complaints than expected for the channel mix. * fewer than 30 comments.")
    _save(fig, "07_domain_by_model.png")


def fig_survey_vs_feedback(labels, survey_us_summary):
    fm = scoring.score(labels, group_keys=("feature", "model"))
    cross = scoring.survey_crosscheck(survey_us_summary)
    cross = cross[~cross["feature"].isin(taxonomy.UMBRELLA_FEATURES)]       # same peer set as the verdicts
    m = cross.merge(fm[["feature", "model", "obs_negative", "exp_negative", "n_comments"]], on=["feature", "model"])
    agg = m.groupby(["survey_attribute", "model"]).agg(
        obs=("obs_negative", "sum"), exp=("exp_negative", "sum"), n=("n_comments", "sum"),
        bottom3=("bottom3_box", "first"), top2=("top2_box", "first")).reset_index()
    agg = agg[agg["n"] >= 10]
    agg["complaint_index"] = (agg["obs"] + 1) / (agg["exp"] + 1)
    rho = agg[["bottom3", "complaint_index"]].corr(method="spearman").iloc[0, 1]
    fig, ax = plt.subplots(figsize=(10, 6.5))
    for i, model in enumerate(["G60", "G70"]):
        sub = agg[agg["model"] == model]
        ax.scatter(sub["bottom3"], sub["complaint_index"], s=sub["n"].clip(10, 300) * 0.9 + 20, color=SERIES[i],
                   edgecolor=SURFACE, linewidth=2, label=config.MODEL_NAMES[model], zorder=3, alpha=0.9)
    ax.set_yscale("log")
    ax.set_yticks([0.35, 0.5, 0.7, 1, 1.4, 2], ["0.35", "0.5", "0.7", "1.0", "1.4", "2.0"])
    ax.minorticks_off()
    ax.axhline(1, color=AXIS, linewidth=1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(True)
    ax.set_axisbelow(True)
    ax.set_xlabel("US survey: share rating the attribute 'Unsatisfactory' or worse (bottom-3 box)")
    ax.set_ylabel("Feedback complaint index (log)")
    ax.legend(loc="lower right")
    pick = pd.concat([agg.nlargest(4, "complaint_index"), agg.nlargest(3, "bottom3"), agg.nsmallest(3, "complaint_index")])
    pick = pick.drop_duplicates(["survey_attribute", "model"])
    names = [(a if len(a) <= 30 else a[:28] + "…") + f" ({m_})" for a, m_ in zip(pick["survey_attribute"], pick["model"])]
    _label_points(ax, pick["bottom3"], pick["complaint_index"], names)
    strength = "weakly" if abs(rho) < 0.4 else "moderately" if abs(rho) < 0.6 else "strongly"
    ax.set_title(f"US survey and free-text complaints agree only {strength} (Spearman rho = {rho:.2f})")
    _subtitle(ax, f"{len(agg)} survey attribute x model pairs mapped to specific feedback features; bubble size = comments.")
    _save(fig, "08_survey_vs_feedback.png")
    return float(rho), int(len(agg))


def fig_survey_cn_eu(survey_cn_eu):
    piv = survey_cn_eu.pivot_table(index="attribute", columns=["market", "model"], values="mean")
    piv = piv[[("EU", "F70"), ("EU", "G60"), ("EU", "G70"), ("CN", "G68"), ("CN", "G70")]]
    piv = piv.loc[piv.mean(axis=1).sort_values().index]
    dev = piv.sub(piv.mean(axis=0), axis=1)          # deviation from each column's own mean
    fig, ax = plt.subplots(figsize=(8.5, 11))
    norm = TwoSlopeNorm(vcenter=0, vmin=-1.6, vmax=1.6)
    im = ax.imshow(-dev.to_numpy(), cmap=DIVERGING, norm=norm, aspect="auto")
    for (i, j), v in np.ndenumerate(piv.to_numpy()):
        ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=7.8,
                color=_text_color(im.cmap(norm(-dev.iloc[i, j]))))
    ax.set_xticks(range(piv.shape[1]), [f"{mk} · {config.MODEL_NAMES[mo]}" for mk, mo in piv.columns], rotation=25, ha="right")
    ax.set_yticks(range(piv.shape[0]), piv.index, fontsize=8.5)
    ax.spines[:].set_visible(False)
    ax.set_title("CN/EU 2025 survey: relative strengths and weaknesses")
    _subtitle(ax, "Mean satisfaction (0-10). Colour = deviation from that model's own average: red below, blue above.")
    _save(fig, "09_survey_cn_eu.png")


def fig_market_representativeness(labels, sales):
    s = sales[sales["year"] == 2025].copy()
    s["sales_share"] = s["volume"] / s.groupby("model_group")["volume"].transform("sum")
    fb = labels.drop_duplicates("comment_id").groupby(["model", "market"]).size().rename("n").reset_index()
    fb["feedback_share"] = fb["n"] / fb.groupby("model")["n"].transform("sum")
    group = {"F70": "F70", "G60": "G60_G68", "G70": "G70"}
    rows = []
    for model in config.MODELS:
        for market in ["EU", "US", "CN", "RoW"]:
            ss = s[(s["model_group"] == group[model]) & (s["market_code"] == market)]["sales_share"].sum()
            fs = fb[(fb["model"] == model) & (fb["market"] == market)]["feedback_share"].sum()
            if ss > 0 or fs > 0:
                rows.append({"label": f"{model} · {market}", "sales": ss, "feedback": fs})
    t = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    y = np.arange(len(t))
    ax.barh(y - 0.18, t["sales"], height=0.34, color=SERIES[0], edgecolor=SURFACE, linewidth=2, label="Share of 2025 sales")
    ax.barh(y + 0.18, t["feedback"], height=0.34, color=SERIES[1], edgecolor=SURFACE, linewidth=2, label="Share of feedback comments")
    ax.set_yticks(y, t["label"])
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    ax.legend(loc="lower right")
    ax.set_title("Feedback over-represents the US and misses China entirely")
    _subtitle(ax, "Within each model: share of 2025 sales volume vs share of feedback comments, by market.")
    _save(fig, "10_market_representativeness.png")


def fig_classifier(metrics):
    tasks = ["feedback_type", "domain", "feature"]
    names = {"feedback_type": "Feedback type\n(4 labels)", "domain": "Domain\n(11 labels)", "feature": "Feature\n(131 labels)"}
    cv = [metrics["tasks"][t]["micro_f1"] for t in tasks]
    ab = [metrics["tasks"][t]["cross_source"][0]["micro_f1"] for t in tasks]
    ba = [metrics["tasks"][t]["cross_source"][1]["micro_f1"] for t in tasks]
    base = [metrics["tasks"][t]["majority_baseline_micro_f1"] for t in tasks]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    x = np.arange(len(tasks))
    w = 0.26
    for i, (vals, lab) in enumerate([(cv, "5-fold CV (all sources)"), (ab, "Train Source A → test B"),
                                     (ba, "Train Source B → test A")]):
        bars = ax.bar(x + (i - 1) * w, vals, width=w - 0.02, color=SERIES[i], edgecolor=SURFACE, linewidth=2, label=lab)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.2f}", ha="center", fontsize=8, color=INK2)
    for xi, b in zip(x, base):
        ax.plot([xi - 1.5 * w, xi + 1.5 * w], [b, b], color=INK, linewidth=1.2)
        ax.text(xi + 1.5 * w, b, " majority\n baseline", fontsize=7, color=MUTED, va="center")
    ax.set_xticks(x, [names[t] for t in tasks])
    ax.set_ylim(0, 1)
    ax.set_ylabel("micro-F1")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.legend(loc="upper right")
    ax.set_title("TF-IDF + logistic regression baseline: good in-channel, weaker across channels")
    _subtitle(ax, "Multi-label micro-F1. The drop across sources shows the model partly learns channel writing style.")
    _save(fig, "11_classifier_performance.png")


def fig_label_coverage(comments):
    tab = pd.crosstab(comments["source"], comments["label_status"], normalize="index")
    tab = tab.reindex(columns=["labeled", "no_class_found_only", "unlabeled"], fill_value=0)
    n = comments["source"].value_counts()
    tab.index = [f"{s} (n={n[s]:,})" for s in tab.index]
    names = {"labeled": "Has a VFC label", "no_class_found_only": "Only 'no_class_found'", "unlabeled": "No label at all"}
    fig, ax = plt.subplots(figsize=(9, 2.9))
    left = np.zeros(len(tab))
    for i, col in enumerate(tab.columns):
        ax.barh(tab.index, tab[col], left=left, height=0.6, color=SERIES[i], edgecolor=SURFACE, linewidth=2, label=names[col])
        for yi, (lv, v) in enumerate(zip(left, tab[col])):
            if v >= 0.08:
                ax.text(lv + v / 2, yi, f"{v:.0%}", ha="center", va="center", fontsize=8.5,
                        color=_text_color(matplotlib.colors.to_rgba(SERIES[i])))
        left += tab[col].to_numpy()
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlim(0, 1)
    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, -0.25))
    ax.set_title("1,180 comments carry no usable label")
    _subtitle(ax, "Label status per comment by source: the unlabelled pool is the target for the trained classifier.")
    _save(fig, "12_label_coverage.png")


def make_all() -> dict:
    p = config.PROCESSED_DIR
    labels = pd.read_csv(p / "labels.csv")
    comments = pd.read_csv(p / "comments.csv", keep_default_na=False, na_values=[""])
    print("Writing figures ...")
    fig_data_composition(comments)
    fig_feedback_type_by_source(labels)
    fig_domain_overview(labels)
    fig_feature_health_map(labels)
    fig_top_features(labels)
    fig_reason_heatmap(labels)
    fig_domain_by_model(labels)
    rho, n_pairs = fig_survey_vs_feedback(labels, pd.read_csv(p / "survey_us_summary.csv"))
    fig_survey_cn_eu(pd.read_csv(p / "survey_cn_eu.csv"))
    fig_market_representativeness(labels, pd.read_csv(p / "sales.csv"))
    metrics_path = config.REPORTS_DIR / "classifier_metrics.json"
    if metrics_path.exists():
        fig_classifier(json.loads(metrics_path.read_text()))
    fig_label_coverage(comments)
    stats = {"survey_vs_feedback_spearman": round(rho, 3), "survey_vs_feedback_pairs": n_pairs}
    (config.REPORTS_DIR / "figure_stats.json").write_text(json.dumps(stats, indent=2))
    return stats
