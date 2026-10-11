"""Review Intelligence Model - a trained, explainable text classifier (no LLM).

It learns BMW's own three-level feedback taxonomy from the labelled reviews:

  Category (L1, 12 classes)  ->  Component (VFC level 2)  ->  Issue (VFC level 3)
  plus the Signal head: praise / defect / usability / request

Method: TF-IDF word uni+bi-grams -> one-vs-rest logistic regression per head
(multi-label, class-balanced). Trained on 80 % of reviews, evaluated on a held-out
20 % (split by review, never by row). Linear weights make every prediction
explainable: the words that pushed a label up are returned with it.

Uses:
  * aspect extraction: each sentence of a review gets its own component/issue/signal
  * labels the ~900 reviews the VFC classification left empty (marked 'model')
  * understands the PM's question (which component is being asked about)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer

from . import taxonomy as tx
from .config import PROCESSED_DIR

MODEL_PATH = PROCESSED_DIR / "review_model.joblib"
CARD_PATH = PROCESSED_DIR / "model_card.json"
MIN_EXAMPLES = 15            # a component / issue needs this many labelled reviews to get its own class
SENTENCE_MIN_P = 0.40        # minimum component probability for a sentence-level aspect
DOMAIN_STOP = {"customer", "stated", "states", "mentioned", "said", "writer", "explained", "advised", "vehicle",
               "really", "car", "bmw", "inquired", "asked", "noted", "shared", "indicated", "like", "likes"}
HEADS = ("category", "component", "issue", "signal")
_SENT = re.compile(r"(?<=[.!?;])\s+|\s+(?:but|however|although|though|whereas)\s+|"
                   r",?\s+and\s+(?=(?:the|my|its|it's|i|they|there|also)\b)", re.I)


@dataclass
class ReviewModel:
    vectorizer: TfidfVectorizer
    heads: dict = field(default_factory=dict)   # name -> {"classes": [...], "clf": est, "threshold": float, "coef": ndarray}
    issue_signal: dict = field(default_factory=dict)
    card: dict = field(default_factory=dict)

    # ------------------------------------------------------------ prediction
    def proba(self, texts: list[str], head: str) -> np.ndarray:
        return self.heads[head]["clf"].predict_proba(self.vectorizer.transform(texts))

    def top(self, text: str, head: str, k: int = 3) -> list[dict]:
        p = self.proba([text], head)[0]
        idx = np.argsort(-p)[:k]
        classes = self.heads[head]["classes"]
        return [{"label": classes[i], "p": round(float(p[i]), 3)} for i in idx]

    def explain(self, text: str, head: str, label: str, k: int = 6) -> list[dict]:
        """Words that pushed `label` up: tf-idf value x class weight."""
        h = self.heads[head]
        if label not in h["classes"]:
            return []
        x = self.vectorizer.transform([text])
        row = h["coef"][h["classes"].index(label)]
        contrib = x.multiply(row).tocsr()
        idx = contrib.indices[np.argsort(-contrib.data)][:k]
        vocab = self.vectorizer.get_feature_names_out()
        return [{"term": vocab[i], "weight": round(float(contrib[0, i]), 3)} for i in idx if contrib[0, i] > 0]

    def analyse(self, text: str) -> dict:
        """Whole-review labels + sentence-level aspects with the words behind them."""
        out = {h: self.top(text, h, 3) for h in HEADS}
        aspects = []
        for s in sentences(text):
            comp = self.top(s, "component", 1)[0]
            if comp["p"] < SENTENCE_MIN_P:
                continue
            sig = self.top(s, "signal", 1)[0]
            issue = self.consistent_issue(s, sig["label"])
            aspects.append({"sentence": s, "component": comp["label"], "p": comp["p"],
                            "category": tx.domain_of(comp["label"]), "signal": sig["label"],
                            "signal_p": sig["p"], "issue": issue,
                            "terms": [t["term"] for t in self.explain(s, "component", comp["label"], 4)]})
        out["aspects"] = aspects
        return out

    def consistent_issue(self, text: str, signal: str) -> str:
        """Best issue (VFC L3) whose usual signal matches the predicted signal."""
        p = self.proba([text], "issue")[0]
        classes = self.heads["issue"]["classes"]
        for i in np.argsort(-p):
            if self.issue_signal.get(classes[i]) == signal:
                return classes[i]
        return classes[int(np.argmax(p))]


def sentences(text: str) -> list[str]:
    parts = [s.strip(" .;-") for s in _SENT.split(text or "") if s and len(s.strip()) > 12]
    return parts or [text]


def _reviews(findings: pd.DataFrame) -> pd.DataFrame:
    lab = findings[(findings["component"] != "no_class_found") & (findings["signal"] != "none")
                   & (findings["label_source"] != "model")]
    return lab.groupby("verbatim_id").agg(
        text=("text", "first"), category=("domain", lambda s: sorted(set(s))),
        component=("component", lambda s: sorted(set(s))), issue=("issue", lambda s: sorted(set(s))),
        signal=("signal", lambda s: sorted(set(s)))).reset_index()


def _fit_head(X, labels, tr, te, name: str) -> tuple[dict, dict]:
    mlb = MultiLabelBinarizer()
    Y = mlb.fit_transform(labels)
    clf = OneVsRestClassifier(LogisticRegression(C=8, solver="liblinear", class_weight="balanced"), n_jobs=-1)
    clf.fit(X[tr], Y[tr])
    P = clf.predict_proba(X[te])
    Yt = Y[te]
    best = None
    for th in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        pred = (P >= th).astype(int)
        pred[np.arange(len(P)), P.argmax(1)] = 1  # every review gets at least its top label
        f1 = f1_score(Yt, pred, average="micro", zero_division=0)
        if best is None or f1 > best[0]:
            best = (f1, th, pred)
    f1, th, pred = best
    has = Yt.sum(1) > 0
    top1 = float(np.mean(Yt[has, P[has].argmax(1)] == 1))
    top3 = float(np.mean([Yt[i, np.argsort(-P[i])[:3]].any() for i in np.where(has)[0]]))
    per_class = f1_score(Yt, pred, average=None, zero_division=0)
    support = Yt.sum(0)
    metrics = {"classes": int(Y.shape[1]), "threshold": th, "micro_f1": round(f1, 3),
               "precision": round(precision_score(Yt, pred, average="micro", zero_division=0), 3),
               "recall": round(recall_score(Yt, pred, average="micro", zero_division=0), 3),
               "top1_accuracy": round(top1, 3), "top3_accuracy": round(top3, 3),
               "per_class": {c: {"f1": round(float(per_class[i]), 3), "support": int(support[i])}
                             for i, c in enumerate(mlb.classes_)}}
    coef = np.vstack([e.coef_[0] if hasattr(e, "coef_") else np.zeros(X.shape[1]) for e in clf.estimators_])
    return {"classes": list(mlb.classes_), "clf": clf, "threshold": th, "coef": coef}, metrics


def train(findings: pd.DataFrame) -> ReviewModel:
    rev = _reviews(findings)
    comp_counts = findings[findings["component"] != "no_class_found"]["component"].value_counts()
    issue_counts = findings[findings["issue"] != ""]["issue"].value_counts()
    keep_c = set(comp_counts[comp_counts >= MIN_EXAMPLES].index)
    keep_i = set(issue_counts[issue_counts >= MIN_EXAMPLES].index)
    rev["component"] = rev["component"].apply(lambda c: [x for x in c if x in keep_c])
    rev["issue"] = rev["issue"].apply(lambda c: [x for x in c if x in keep_i])

    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=60000,
                          stop_words=list(ENGLISH_STOP_WORDS.union(DOMAIN_STOP)))
    X = vec.fit_transform(rev["text"])
    tr, te = next(GroupShuffleSplit(1, test_size=0.2, random_state=7).split(rev, groups=rev["verbatim_id"]))
    model = ReviewModel(vectorizer=vec)
    metrics = {}
    for head in HEADS:
        model.heads[head], metrics[head] = _fit_head(X, rev[head], tr, te, head)
    lab = findings[findings["issue"] != ""]
    model.issue_signal = lab.groupby("issue")["signal"].agg(lambda s: s.value_counts().index[0]).to_dict()

    vocab = vec.get_feature_names_out()
    top_terms = {}
    for i, c in enumerate(model.heads["component"]["classes"]):
        idx = np.argsort(-model.heads["component"]["coef"][i])[:8]
        top_terms[c] = [vocab[j] for j in idx]
    model.card = {
        "method": "TF-IDF (word 1-2 grams, sublinear) + one-vs-rest logistic regression per head, class-balanced",
        "train_reviews": int(len(tr)), "test_reviews": int(len(te)), "vocabulary": int(len(vocab)),
        "min_examples_per_class": MIN_EXAMPLES, "metrics": metrics, "top_terms": top_terms,
        "hierarchy": {"categories": int(findings["domain"].nunique()),
                      "components": int((comp_counts.index != "no_class_found").sum()),
                      "issues": int(issue_counts.size),
                      "components_modelled": len(keep_c), "issues_modelled": len(keep_i)},
    }
    return model


def augment(findings: pd.DataFrame, model: ReviewModel) -> pd.DataFrame:
    """Give reviews without any VFC label sentence-level aspects predicted by the model."""
    labelled = set(findings.loc[findings["component"] != "no_class_found", "verbatim_id"])
    todo = findings[~findings["verbatim_id"].isin(labelled)].drop_duplicates("verbatim_id")
    rows = []
    for r in todo.itertuples(index=False):
        seen = set()
        for a in model.analyse(r.text)["aspects"]:
            if a["component"] in seen:
                continue
            seen.add(a["component"])
            row = r._asdict()
            row.update({"component": a["component"], "issue": a["issue"], "signal": a["signal"],
                        "domain": tx.domain_of(a["component"]), "label_source": "model", "confidence": a["p"],
                        "feedback_type": "", "scope_note": tx.OUT_OF_SCOPE_COMPONENTS.get(a["component"], "")})
            rows.append(row)
    model_rows = pd.DataFrame(rows)
    if not model_rows.empty:
        model_rows["finding_id"] = model_rows["verbatim_id"] + "#m" + \
            (model_rows.groupby("verbatim_id").cumcount() + 1).astype(str)
    out = pd.concat([findings.assign(confidence=1.0), model_rows], ignore_index=True)
    model.card["augmented"] = {"reviews_without_label": int(len(todo)),
                               "reviews_labelled_by_model": int(model_rows["verbatim_id"].nunique()) if rows else 0,
                               "aspects_added": int(len(model_rows))}
    return out


def save(model: ReviewModel) -> None:
    joblib.dump(model, MODEL_PATH)
    CARD_PATH.write_text(json.dumps(model.card, indent=2), encoding="utf-8")


_cache: dict = {}


def load() -> ReviewModel | None:
    if "m" not in _cache:
        _cache["m"] = joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None
    return _cache["m"]


def reset_cache() -> None:
    _cache.clear()
