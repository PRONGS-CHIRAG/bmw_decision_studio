"""The part of the knowledge graph one evaluation touches, ready for the graph view.

Nodes: the idea, its candidate and chosen features, everything a fact cites
(verdict cells, survey scores, sales, price-list items, comments, model terms,
caveats) and the structure that connects them (domain, reasons, series,
markets, fitment). Request-time nodes - the idea and one recommendation per
series x market cell - are added so the PM can see how the model outputs feed
each recommendation. Capped so the view stays readable; cited nodes are kept first.
"""

from ..graph.build import GROUPS, nid
from .contracts import FactBundle, IdeaSpec

CAP = 170
DROP_ORDER = ["Comment", "OptionItem", "TechSpec", "Reason", "SurveyAttribute", "SalesVolume", "SurveyScore",
              "VerdictCell", "FitmentSummary", "EBMTerm", "Caveat"]


def subgraph(g, spec: IdeaSpec, result: dict, bundle: FactBundle, candidates: list) -> dict:
    nodes: dict = {}
    edges: dict = {}
    cited = {f.source.node_id for f in bundle.facts if f.source.node_id}

    def add(node_id, **extra):
        if node_id not in nodes:
            if node_id not in g:
                return
            d = g.nodes[node_id]
            nodes[node_id] = {"id": node_id, "type": d["type"], "group": d["group"], "label": d["label"]}
        nodes[node_id].update({k: v for k, v in extra.items() if v})

    def virtual(node_id, type_, group, label):
        nodes.setdefault(node_id, {"id": node_id, "type": type_, "group": group, "label": label, "virtual": True})

    def link(u, v, rel, **attrs):
        if u in nodes and v in nodes:
            edges.setdefault((u, v, rel), {"id": f"{u}->{v}:{rel}", "source": u, "target": v, "rel": rel, **attrs})

    virtual("idea:current", "Idea", "idea", spec.idea[:80])
    chosen = {f.feature for f in spec.features}
    for c in candidates[:6]:
        add(c.node_id, chosen=c.feature in chosen)
    for f in spec.features:
        add(f.node_id, chosen=True)

    for node_id in cited:
        if node_id in g:
            add(node_id, cited=True)

    for fr in result["features"]:
        f = fr["feature"]
        fn = nid("feature", f)
        add(fn, chosen=True)
        add(nid("domain", fr["domain"]))
        add(nid("verdict", "feature", f))
        reasons = sorted(((d.get("n_comments") or 0, v) for _, v, d in g.out_edges(fn, data=True)
                          if d["rel"] == "HAS_REASON"), reverse=True)[:5]
        for _, v in reasons:
            add(v)
        for u, _, d in g.in_edges(fn, data=True):
            if d["rel"] == "MEASURES":
                add(u)
        for m in result["models"]:
            add(nid("series", m))
            if nid("fitment", f, m) in g:
                add(nid("fitment", f, m))
        for k in result["markets"]:
            add(nid("market", k))
        for cell in fr["cells"]:
            rec = f"rec:{f}|{cell['model']}|{cell['market']}"
            label = f"{cell['model']} {cell['market']}: {cell['recommendation']}"
            if cell.get("score") is not None and cell["recommendation"] != "Not sold":
                label += f" ({cell['score']:.2f})"
            virtual(rec, "Recommendation", "model_output", label)
            nodes[rec]["recommendation"] = cell["recommendation"]
    for term in ("domain", "market", "model"):
        if nid("ebmterm", term) in g:
            add(nid("ebmterm", term))
    for m in ("complaint_ebm", "feature_classifier"):
        add(nid("model", m))

    _cap(nodes, cited)

    # edges: idea -> candidates, recommendation cells -> their evidence, then all graph edges among kept nodes
    for c in candidates[:6]:
        link("idea:current", c.node_id, "MATCHED" if c.feature in chosen else "CANDIDATE",
             detail=", ".join(c.how))
    for fact in bundle.facts:
        src = fact.source.node_id
        if src and src.startswith("rec:"):
            continue
        if fact.feature and fact.series and fact.market:
            link(f"rec:{fact.feature}|{fact.series}|{fact.market}", src, "USES", fact=fact.id)
    for fr in result["features"]:
        for cell in fr["cells"]:
            rec = f"rec:{fr['feature']}|{cell['model']}|{cell['market']}"
            link(rec, nid("feature", fr["feature"]), "EVALUATES")
            link(rec, nid("series", cell["model"]), "FOR_SERIES")
            link(rec, nid("market", cell["market"]), "IN_MARKET")
    real = [n for n in nodes if n in g]
    keep = set(real)
    for u in real:
        for _, v, d in g.out_edges(u, data=True):
            if v in keep:
                link(u, v, d["rel"])
    for n in nodes.values():
        n["cited"] = bool(n.get("cited")) or n["id"] in cited
        n.setdefault("group", GROUPS.get(n["type"], "other"))
    return {"nodes": list(nodes.values()), "edges": list(edges.values()),
            "n_cited": sum(1 for n in nodes.values() if n["cited"])}


def _cap(nodes: dict, cited: set) -> None:
    for t in DROP_ORDER:
        if len(nodes) <= CAP:
            return
        drop = [k for k, v in nodes.items() if v["type"] == t and not v.get("virtual") and not v.get("chosen")]
        drop.sort(key=lambda k: k in cited)            # uncited first
        for k in drop[: len(nodes) - CAP]:
            del nodes[k]
