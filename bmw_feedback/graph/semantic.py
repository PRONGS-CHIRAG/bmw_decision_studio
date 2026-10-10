"""Semantic index over the 224 feedback features, used to match a free-text idea.

Each feature is described by its graph neighbourhood: name, domain, aliases,
the reasons customers give, the survey attributes that measure it and the
price-list items linked to it (German names, so an English idea can still land
on 'Massagefunktion'). With an OpenAI key the documents are embedded
(cached in data/processed/graph_embeddings.npz, keyed by model and content
hash); without one a character n-gram TF-IDF is used and labelled as such.
"""

import hashlib
import threading

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .. import config
from .build import nid

EMB_FILE = config.PROCESSED_DIR / "graph_embeddings.npz"


def feature_doc(g, feature: str) -> str:
    from ..verdict import ALIASES
    node = nid("feature", feature)
    reasons, surveys, options = [], [], []
    for _, v, d in g.out_edges(node, data=True):
        if d["rel"] == "HAS_REASON":
            reasons.append((d.get("n_comments") or 0, g.nodes[v]["label"]))
        elif d["rel"] == "LINKED_TO":
            options.append(g.nodes[v]["label"])
    for u, _, d in g.in_edges(node, data=True):
        if d["rel"] == "MEASURES":
            surveys.append(g.nodes[u]["label"])
    top_reasons = [r for _, r in sorted(reasons, key=lambda x: -x[0])[:6]]
    aliases = sorted(a for a, target in ALIASES.items() if target == feature)
    parts = [feature, f"Domain: {g.nodes[node]['domain']}."]
    if aliases:
        parts.append("Also called: " + ", ".join(aliases) + ".")
    if top_reasons:
        parts.append("Customers mention: " + "; ".join(top_reasons) + ".")
    if surveys:
        parts.append("Survey attributes: " + "; ".join(sorted(set(surveys))) + ".")
    if options:
        parts.append("Price-list items: " + "; ".join(sorted(set(options))[:8]) + ".")
    return " ".join(parts)


class SemanticIndex:
    def __init__(self, g):
        self.features = sorted(d["label"] for _, d in g.nodes(data=True) if d["type"] == "Feature")
        self.docs = [feature_doc(g, f) for f in self.features]
        self.docs_hash = hashlib.sha256("\n".join(self.docs).encode()).hexdigest()[:16]
        self.tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, lowercase=True)
        self.X = self.tfidf.fit_transform(self.docs)
        self._emb: dict = {}
        self._lock = threading.Lock()

    def _embeddings(self, embed, model: str) -> np.ndarray:
        """Feature-document embeddings for `model`, from the cache file or computed once."""
        with self._lock:
            if model in self._emb:
                return self._emb[model]
            if EMB_FILE.exists():
                z = np.load(EMB_FILE, allow_pickle=False)
                if str(z["model"]) == model and str(z["docs_hash"]) == self.docs_hash:
                    self._emb[model] = z["vectors"]
                    return self._emb[model]
            vecs = np.vstack([embed(self.docs[i:i + 96], model) for i in range(0, len(self.docs), 96)])
            vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
            np.savez(EMB_FILE, vectors=vecs, model=np.array(model), docs_hash=np.array(self.docs_hash))
            self._emb[model] = vecs
            return vecs

    def search(self, text: str, k: int = 8, embed=None, model: str | None = None) -> dict:
        """Top-k features for `text`. embed(texts, model) -> array; None means TF-IDF."""
        if embed is not None and model:
            vecs = self._embeddings(embed, model)
            q = embed([text], model)[0]
            q = q / np.linalg.norm(q)
            sims = vecs @ q
            method = f"embeddings ({model})"
        else:
            sims = (self.X @ self.tfidf.transform([text]).T).toarray().ravel()
            method = "tf-idf (character n-grams)"
        order = np.argsort(-sims)[:k]
        return {"method": method, "results": [(self.features[i], round(float(sims[i]), 4)) for i in order]}
