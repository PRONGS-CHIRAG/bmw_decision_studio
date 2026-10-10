"""Load the knowledge graph once per process and answer the frontend's graph questions."""

import json
import threading

import networkx as nx

from .build import GRAPH_FILE, GROUPS, build_and_save

_LOCK = threading.Lock()
_CACHE: dict = {}


def get_graph(rebuild: bool = False) -> tuple[nx.MultiDiGraph, dict]:
    """(graph, meta). Built from the processed tables the first time if the file is missing."""
    with _LOCK:
        if rebuild or "g" not in _CACHE:
            if rebuild or not GRAPH_FILE.exists():
                build_and_save()
            payload = json.loads(GRAPH_FILE.read_text())
            _CACHE["g"] = nx.node_link_graph(payload["graph"], directed=True, multigraph=True, edges="edges")
            _CACHE["meta"] = payload["meta"]
        return _CACHE["g"], _CACHE["meta"]


def node_view(g: nx.MultiDiGraph, node_id: str, per_rel: int = 12) -> dict | None:
    """A node's attributes and provenance, plus its neighbours grouped by relation (capped per relation)."""
    if node_id not in g:
        return None
    attrs = dict(g.nodes[node_id])
    groups: dict = {}
    for direction, edges in (("out", g.out_edges(node_id, data=True)), ("in", g.in_edges(node_id, data=True))):
        for u, v, d in edges:
            other = v if direction == "out" else u
            key = f"{direction}:{d['rel']}"
            grp = groups.setdefault(key, {"rel": d["rel"], "direction": direction, "total": 0, "items": []})
            grp["total"] += 1
            if len(grp["items"]) < per_rel:
                o = g.nodes[other]
                grp["items"].append({"id": other, "type": o["type"], "label": o["label"],
                                     "edge": {k: x for k, x in d.items() if k != "rel"}})
    return {"id": node_id, "type": attrs.pop("type"), "group": attrs.pop("group", GROUPS.get(attrs.get("type"))),
            "label": attrs.pop("label"), "prov": attrs.pop("prov"), "attributes": attrs,
            "neighbours": sorted(groups.values(), key=lambda x: (x["direction"], -x["total"]))}
