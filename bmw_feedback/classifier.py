"""Baseline text classifiers: comment -> feedback type, domain, feature.

All three are multi-label (a comment can praise one thing and report a defect
in another). Model: TF-IDF word 1-2 grams + char 3-5 grams -> one-vs-rest
logistic regression. Deliberately simple; REPORT.md lists stronger options.

Evaluation
- 5-fold CV over comments (each comment is one row, so no row-level leakage;
  duplicate texts are removed first).
- Cross-source test (train Source A -> test Source B and vice versa) to see
  whether the model learned content or channel writing style.
"""

import json
import warnings
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import KFold
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import FeatureUnion, make_pipeline
from sklearn.preprocessing import MultiLabelBinarizer

from . import config

# One-vs-rest warns when a label is absent from a cross-source training slice
warnings.filterwarnings("ignore", message="Label not .* is present in all training examples")

MIN_FEATURE_SUPPORT = 15      # features with fewer labeled comments are not predicted
TASKS = {"feedback_type": "feedback_types", "domain": "domains", "feature": "features"}


def training_frame(comments: pd.DataFrame) -> pd.DataFrame:
    df = comments[(comments["label_status"] == "labeled") & (comments["text_model"].str.len() > 0)]
    return df.drop_duplicates("text_model").reset_index(drop=True)


def _targets(df: pd.DataFrame, task: str):
    labels = df[TASKS[task]]
    if task == "feature":
        counts = labels.explode().value_counts()
        keep = set(counts[counts >= MIN_FEATURE_SUPPORT].index) - set(config.NON_FEATURE_LABELS)
        labels = labels.apply(lambda fs: [f for f in fs if f in keep])
    mlb = MultiLabelBinarizer()
    y = mlb.fit_transform(labels)
    return y, mlb


def make_model():
    features = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=40000, sublinear_tf=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=60000,
                                 sublinear_tf=True)),
    ])
    clf = OneVsRestClassifier(LogisticRegression(C=4.0, class_weight="balanced", solver="liblinear",
                                                 max_iter=2000))
    return make_pipeline(features, clf)


def _topk_hit(y_true, proba, k):
    top = np.argsort(-proba, axis=1)[:, :k]
    has_label = y_true.sum(axis=1) > 0
    hits = np.array([y_true[i, top[i]].any() for i in range(len(y_true))])
    return float(hits[has_label].mean())


def _scores(y_true, proba, classes, threshold=0.5):
    y_pred = (proba >= threshold).astype(int)
    # Always predict at least the most likely label
    empty = y_pred.sum(axis=1) == 0
    y_pred[empty, proba[empty].argmax(axis=1)] = 1
    out = {
        "micro_f1": round(float(f1_score(y_true, y_pred, average="micro", zero_division=0)), 3),
        "macro_f1": round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 3),
        "top1_hit": round(_topk_hit(y_true, proba, 1), 3),
        "top3_hit": round(_topk_hit(y_true, proba, 3), 3),
    }
    per = f1_score(y_true, y_pred, average=None, zero_division=0)
    out["per_label_f1"] = {c: round(float(v), 3) for c, v in zip(classes, per)}
    out["support"] = {c: int(v) for c, v in zip(classes, y_true.sum(axis=0))}
    return out


def _majority_baseline(y_train, y_test):
    """Predict the single most frequent label for every comment."""
    proba = np.tile(y_train.mean(axis=0), (len(y_test), 1))
    pred = np.zeros_like(y_test)
    pred[:, proba[0].argmax()] = 1
    return round(float(f1_score(y_test, pred, average="micro", zero_division=0)), 3)


def cross_validate(df: pd.DataFrame, task: str, n_splits: int = 5) -> dict:
    y, mlb = _targets(df, task)
    mask = y.sum(axis=1) > 0
    X, y = df.loc[mask, "text_model"].to_numpy(), y[mask]
    proba = np.zeros(y.shape, dtype=float)
    base = []
    for tr, te in KFold(n_splits, shuffle=True, random_state=config.RANDOM_STATE).split(X):
        model = make_model().fit(X[tr], y[tr])
        proba[te] = model.predict_proba(X[te])
        base.append(_majority_baseline(y[tr], y[te]))
    res = _scores(y, proba, mlb.classes_)
    res.update(n_comments=int(len(X)), n_labels=int(len(mlb.classes_)),
               majority_baseline_micro_f1=round(float(np.mean(base)), 3))
    return res


def cross_source(df: pd.DataFrame, task: str, train_source: str, test_source: str) -> dict:
    y, mlb = _targets(df, task)
    tr = (df["source"] == train_source).to_numpy() & (y.sum(axis=1) > 0)
    te = (df["source"] == test_source).to_numpy() & (y.sum(axis=1) > 0)
    model = make_model().fit(df.loc[tr, "text_model"], y[tr])
    proba = model.predict_proba(df.loc[te, "text_model"])
    res = _scores(y[te], proba, mlb.classes_)
    return {k: res[k] for k in ("micro_f1", "macro_f1", "top1_hit", "top3_hit")} | {
        "train": train_source, "test": test_source, "n_train": int(tr.sum()), "n_test": int(te.sum())}


def evaluate_all(comments: pd.DataFrame) -> dict:
    df = training_frame(comments)
    metrics = {"n_training_comments": int(len(df)), "tasks": {}}
    for task in TASKS:
        t0 = time.time()
        m = cross_validate(df, task)
        m["cross_source"] = [cross_source(df, task, "Source A", "Source B"),
                             cross_source(df, task, "Source B", "Source A")]
        m["seconds"] = round(time.time() - t0, 1)
        metrics["tasks"][task] = m
        print(f"  {task:14s} micro-F1 {m['micro_f1']:.3f}  macro-F1 {m['macro_f1']:.3f}  "
              f"top-1 {m['top1_hit']:.3f}  top-3 {m['top3_hit']:.3f}  ({m['seconds']}s)")
    return metrics


def fit_and_save(comments: pd.DataFrame) -> None:
    df = training_frame(comments)
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for task in TASKS:
        y, mlb = _targets(df, task)
        mask = y.sum(axis=1) > 0
        model = make_model().fit(df.loc[mask, "text_model"], y[mask])
        joblib.dump({"model": model, "classes": list(mlb.classes_)}, config.MODELS_DIR / f"{task}.joblib")


def load_models() -> dict:
    return {t: joblib.load(config.MODELS_DIR / f"{t}.joblib") for t in TASKS
            if (config.MODELS_DIR / f"{t}.joblib").exists()}


RERANKER_FILE = "feature_reranker.json"


def save_reranker(ablation: dict, comments: pd.DataFrame) -> None:
    """Persist the fitment re-ranker exactly as evaluated: weights + the car prior table.

    Used only when the comment's car (model, engine) is known.
    """
    df = training_frame(comments)
    y, mlb = _targets(df, "feature")
    prior = {}
    for (model, engine), idx in df.groupby(["model", "engine"]).groups.items():
        c = y[df.index.get_indexer(idx)].sum(axis=0)
        prior[f"{model}|{engine}"] = [round(float(v), 8) for v in (c + 1) / (c.sum() + len(mlb.classes_))]
    payload = {"coefficients": ablation["fitment_reranker_coefficients"], "k": ablation["candidates_per_comment"],
               "tiers": TIERS, "mcnemar_linked": ablation["mcnemar_linked"], "classes": list(mlb.classes_),
               "car_prior": prior}
    (config.MODELS_DIR / RERANKER_FILE).write_text(json.dumps(payload))


def _rerank(ranked_all, car, reranker, tier):
    """Re-score the top-k text candidates with the fitment tier of each on the given car."""
    coef = reranker["coefficients"]
    index = {c: j for j, c in enumerate(reranker["classes"])}
    prior = reranker["car_prior"].get(f"{car[0]}|{car[1]}")
    n = len(reranker["classes"])
    rows = []
    for rank, (feature, p) in enumerate(ranked_all[:reranker["k"]]):
        t = tier(feature, car[0], car[1])
        logprior = np.log(prior[index[feature]]) if prior else np.log(1 / n)
        z = (coef["logp"] * np.log(p + 1e-9) + coef["rank"] * rank + coef["logprior"] * logprior
             + coef[f"tier_{t}"])
        rows.append((feature, p, t, z))
    rows.sort(key=lambda r: -r[3])
    return rows


def predict(texts, models=None, top_k: int = 3, cars=None, fitment_lookup=None) -> list:
    """Predict feedback types, domains and top-k features for raw comment texts.

    cars: optional list of (model, engine) per text. When given together with a
    fitment_lookup (see _tier_lookup), feature candidates are re-ranked with the
    price-list fitment re-ranker and each candidate carries its fitment tier.
    """
    from .clean import _normalise_whitespace, model_text
    models = models or load_models()
    if not models:
        raise FileNotFoundError("No trained models found - run `python -m bmw_feedback train` first.")
    reranker_path = config.MODELS_DIR / RERANKER_FILE
    reranker = json.loads(reranker_path.read_text()) if cars and fitment_lookup and reranker_path.exists() else None
    texts = [model_text(_normalise_whitespace(t if isinstance(t, str) else "")) for t in texts]
    results = [dict() for _ in texts]
    for task, bundle in models.items():
        proba = bundle["model"].predict_proba(texts)
        for i, row in enumerate(proba):
            order = np.argsort(-row)
            ranked = [(bundle["classes"][j], round(float(row[j]), 3)) for j in order]
            if task == "feature":
                if reranker and cars[i] and all(cars[i]):
                    rr = _rerank(ranked, cars[i], reranker, fitment_lookup)
                    results[i][task] = [(f, p) for f, p, _, _ in rr[:top_k]]
                    results[i]["feature_fitment_tiers"] = {f: t for f, _, t, _ in rr[:top_k]}
                    results[i]["reranked_with_fitment"] = True
                else:
                    results[i][task] = ranked[:top_k]
            else:
                chosen = [r for r in ranked if r[1] >= 0.5] or ranked[:1]
                results[i][task] = chosen
    return results


# --------------------------------------------------------------------------- fitment ablation
TIERS = ["standard_all", "standard_some", "optional", "not_listed", "not_covered", "no_link"]


def _tier_lookup(fit_by_engine: pd.DataFrame, covered: set):
    linked = set(fit_by_engine["feature"])
    tiers = {(r.feature, r.model, r.engine): r.tier for r in fit_by_engine.itertuples()}

    def tier(feature, model, engine):
        if (model, engine) not in covered:
            return "not_covered"
        if feature not in linked:
            return "no_link"
        return tiers.get((feature, model, engine), "not_listed")
    return tier


def fitment_ablation(comments: pd.DataFrame, fit_by_engine: pd.DataFrame, covered: set,
                     k: int = 10, n_splits: int = 5) -> dict:
    """Does price-list fitment help the feature classifier beyond knowing the car?

    1. text            out-of-fold TF-IDF probabilities, ranked as is
    2. + car prior     re-ranker adds log P(feature | model, engine) from the training folds
    3. + PDF fitment   re-ranker also sees the candidate feature's fitment tier on that car

    The re-ranker is a logistic regression over the top-k text candidates per
    comment, cross-validated by comment. Fitment is credited only with the
    gain of 3 over 2.
    """
    df = training_frame(comments)
    y, mlb = _targets(df, "feature")
    mask = y.sum(axis=1) > 0
    df, y = df[mask].reset_index(drop=True), y[mask]
    classes = list(mlb.classes_)
    X = df["text_model"].to_numpy()
    cars = list(zip(df["model"], df["engine"]))
    proba = np.zeros(y.shape)
    prior = np.zeros(y.shape)
    for tr, te in KFold(n_splits, shuffle=True, random_state=config.RANDOM_STATE).split(X):
        proba[te] = make_model().fit(X[tr], y[tr]).predict_proba(X[te])
        counts = {}
        for i in tr:
            counts.setdefault(cars[i], np.zeros(len(classes)))
            counts[cars[i]] += y[i]
        for i in te:
            c = counts.get(cars[i], np.zeros(len(classes)))
            prior[i] = (c + 1) / (c.sum() + len(classes))
    tier = _tier_lookup(fit_by_engine, covered)

    rows = []
    for i in range(len(df)):
        top = np.argsort(-proba[i])[:k]
        for rank, j in enumerate(top):
            t = tier(classes[j], cars[i][0], cars[i][1])
            rows.append([i, j, int(y[i, j]), np.log(proba[i, j] + 1e-9), rank, np.log(prior[i, j])]
                        + [int(t == x) for x in TIERS])
    cand = pd.DataFrame(rows, columns=["i", "j", "label", "logp", "rank", "logprior"] + [f"tier_{x}" for x in TIERS])
    sets = {"text": ["logp", "rank"], "text_plus_car_prior": ["logp", "rank", "logprior"],
            "text_plus_car_prior_plus_fitment": ["logp", "rank", "logprior"] + [f"tier_{x}" for x in TIERS]}
    linked = set(fit_by_engine["feature"])
    true_linked = np.array([any(classes[j] in linked for j in np.flatnonzero(y[i])) for i in range(len(df))])
    out = {"n_comments": int(len(df)), "candidates_per_comment": k, "variants": {},
           "n_comments_true_feature_linked": int(true_linked.sum())}
    from scipy.stats import binomtest
    from sklearn.model_selection import GroupKFold
    # Sanity check that the car prior is informative on its own (not a key mismatch)
    prior_top1 = np.array([y[i, prior[i].argmax()] for i in range(len(df))])
    out["car_prior_alone_top1_hit"] = round(float(prior_top1.mean()), 4)
    out["uniform_top1_hit"] = round(float(np.mean([y[i].sum() / len(classes) for i in range(len(df))])), 4)
    hits = {}
    for name, cols in sets.items():
        score = np.zeros(len(cand))
        if name == "text":
            score = -cand["rank"].to_numpy(dtype=float)
        else:
            for tr, te in GroupKFold(n_splits).split(cand, groups=cand["i"]):
                lr = LogisticRegression(max_iter=2000).fit(cand.iloc[tr][cols], cand.iloc[tr]["label"])
                score[te] = lr.decision_function(cand.iloc[te][cols])
        c = cand.assign(score=score).sort_values(["i", "score"], ascending=[True, False])
        c["new_rank"] = c.groupby("i").cumcount()
        hit1 = c[c["new_rank"] < 1].groupby("i")["label"].max().reindex(range(len(df)), fill_value=0).to_numpy()
        hit3 = c[c["new_rank"] < 3].groupby("i")["label"].max().reindex(range(len(df)), fill_value=0).to_numpy()
        hits[name] = hit1
        out["variants"][name] = {"top1_hit": round(float(hit1.mean()), 4), "top3_hit": round(float(hit3.mean()), 4),
                                 "top1_hit_linked": round(float(hit1[true_linked].mean()), 4),
                                 "top3_hit_linked": round(float(hit3[true_linked].mean()), 4)}
        if name == "text_plus_car_prior_plus_fitment":
            lr = LogisticRegression(max_iter=2000).fit(cand[cols], cand["label"])
            out["fitment_reranker_coefficients"] = {col: round(float(w), 4) for col, w in zip(cols, lr.coef_[0])}
    v = out["variants"]
    out["fitment_gain_top1"] = round(v["text_plus_car_prior_plus_fitment"]["top1_hit"]
                                     - v["text_plus_car_prior"]["top1_hit"], 4)
    out["fitment_gain_top1_linked"] = round(v["text_plus_car_prior_plus_fitment"]["top1_hit_linked"]
                                            - v["text_plus_car_prior"]["top1_hit_linked"], 4)
    # McNemar exact test on paired top-1 hits (fitment vs car prior), linked comments
    a = hits["text_plus_car_prior"][true_linked]
    b = hits["text_plus_car_prior_plus_fitment"][true_linked]
    gained, lost = int(((b == 1) & (a == 0)).sum()), int(((b == 0) & (a == 1)).sum())
    pval = binomtest(gained, gained + lost, 0.5).pvalue if gained + lost else 1.0
    out["mcnemar_linked"] = {"fitment_fixes": gained, "fitment_breaks": lost, "p_value": round(float(pval), 4),
                             "significant_at_0_05": bool(pval < 0.05)}
    return out


def save_metrics(metrics: dict, path) -> None:
    path.write_text(json.dumps(metrics, indent=2))
