"""Positions for drawing the entire knowledge graph at once (the full-screen "Entire graph" view).

A force layout over 15k nodes is too slow for the browser, so positions are computed
here once per graph build. Two levels keep it fast and readable:

1. a spring layout over the backbone (features, domains, series, markets, variants,
   survey attributes, model artefacts and the other small node types), and
2. every leaf (comments, verdict cells, price-list items, technical data, survey
   scores, fitment summaries, reasons) placed on a sunflower disc around the backbone
   node it belongs to, so each feature shows up as a cluster of its own evidence.

The payload is compact: one row per node, edges as index pairs. Attributes and
provenance stay behind /api/graph/node/{id}.
"""

import math
import threading

import networkx as nx
import numpy as np

_LOCK = threading.Lock()
_CACHE: dict = {}

LEAF_TYPES = {"Comment", "VerdictCell", "OptionItem", "TechSpec", "SurveyScore", "FitmentSummary", "Reason"}
# Which neighbour a leaf is drawn next to, in order of preference.
ANCHOR_PREF = ["Feature", "SurveyAttribute", "Variant", "ReasonFamily", "Series", "Domain", "Market", "Powertrain"]
GOLDEN = math.pi * (3 - math.sqrt(5))
SPACING = 5.0           # distance between leaves on a disc
SCALE = 1000.0          # radius of the initial backbone layout, before packing


def overview(g: nx.MultiDiGraph, meta: dict) -> dict:
    """Cached per graph build."""
    with _LOCK:
        key = meta.get("built_at")
        if _CACHE.get("key") != key:
            _CACHE["key"], _CACHE["payload"] = key, _compute(g, meta)
        return _CACHE["payload"]


def _anchor(g: nx.MultiDiGraph, n: str) -> str | None:
    best, rank = None, len(ANCHOR_PREF)
    for other in list(g.successors(n)) + list(g.predecessors(n)):
        t = g.nodes[other]["type"]
        if t in ANCHOR_PREF and ANCHOR_PREF.index(t) < rank:
            best, rank = other, ANCHOR_PREF.index(t)
    return best


def _compute(g: nx.MultiDiGraph, meta: dict) -> dict:
    core = [n for n, d in g.nodes(data=True) if d["type"] not in LEAF_TYPES]
    # Hubs (series, markets, powertrains) touch almost everything; down-weight them so features spread out.
    hub = {n for n in core if g.nodes[n]["type"] in ("Series", "Market", "Powertrain")}
    sk = nx.Graph()
    sk.add_nodes_from(core)
    for u, v in g.edges():
        if u in sk and v in sk and u != v:
            sk.add_edge(u, v, weight=0.15 if (u in hub or v in hub) else 1.0)
    anchors = {n: _anchor(g, n) for n, d in g.nodes(data=True) if d["type"] in LEAF_TYPES}
    by_anchor: dict = {}
    for n, a in sorted(anchors.items()):
        by_anchor.setdefault(a, []).append(n)
    pos = nx.spring_layout(sk, k=1.6 / math.sqrt(max(len(core), 1)), iterations=120, seed=7, weight="weight")
    xy = _pack(core, pos, {a: len(v) for a, v in by_anchor.items() if a is not None})

    # leaves on a sunflower disc around their anchor; leaves without one go to a disc of their own
    for a, leaves in by_anchor.items():
        cx, cy = xy[a] if a in xy else (0.0, max(y for _, y in xy.values()) + 120)
        leaves.sort(key=lambda n: (g.nodes[n]["type"], n))
        for i, n in enumerate(leaves):
            r = SPACING * math.sqrt(i + 6)
            xy[n] = (cx + r * math.cos(i * GOLDEN), cy + r * math.sin(i * GOLDEN))

    ids = list(g.nodes())
    index = {n: i for i, n in enumerate(ids)}
    nodes = []
    for n in ids:
        d = g.nodes[n]
        x, y = xy[n]
        nodes.append([n, d["type"], d["group"], _short(d["label"]), round(x, 1), round(y, 1)])
    edges = [[index[u], index[v], d["rel"]] for u, v, d in g.edges(data=True)]
    return {"built_at": meta.get("built_at"), "n_nodes": len(nodes), "n_edges": len(edges),
            "anchored": sum(1 for a in anchors.values() if a is not None),
            "node_fields": ["id", "type", "group", "label", "x", "y"], "edge_fields": ["source", "target", "rel"],
            "nodes": nodes, "edges": edges}


def _pack(core: list, pos: dict, n_leaves: dict, iterations: int = 400) -> dict:
    """Keep the spring layout's arrangement but pull everything together until the leaf discs touch.

    Each backbone node gets the radius of its leaf disc; overlapping discs push apart while a weak
    pull towards the centre closes the gaps (and brings in the disconnected nodes).
    """
    P = np.array([pos[n] for n in core], dtype=float) * SCALE
    R = np.array([SPACING * math.sqrt(n_leaves.get(n, 0) + 6) + 8 for n in core])
    eye = np.eye(len(core), dtype=bool)
    for i in range(iterations):
        d = P[:, None, :] - P[None, :, :]
        dist = np.sqrt((d ** 2).sum(-1)) + 1e-6
        overlap = (R[:, None] + R[None, :]) - dist
        overlap[eye | (overlap < 0)] = 0
        P += 0.25 * ((d / dist[..., None]) * overlap[..., None]).sum(1)
        if i < iterations * 0.75:                       # the last quarter only resolves overlaps
            P -= 0.03 * (P - P.mean(0))
    return {n: (float(x), float(y)) for n, (x, y) in zip(core, P)}


def _short(s: str, n: int = 60) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"
