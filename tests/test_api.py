"""API and pipeline checks against the processed tables and the source PDFs.

Run after `python -m bmw_feedback all`:   python -m pytest tests -q
"""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from bmw_feedback import config, decision
from bmw_feedback.api import app

P = config.PROCESSED_DIR


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        from bmw_feedback.api import STATE
        STATE["pipeline"]._env_llm, STATE["pipeline"].llm = False, None     # never call OpenAI from tests
        yield c


def test_overview_matches_processed_tables(client):
    o = client.get("/api/overview").json()
    quality = json.loads((config.REPORTS_DIR / "data_quality.json").read_text())
    assert o["comments"] == quality["raw_unique_comments"]
    assert o["catalog"]["variants"] == len(pd.read_csv(P / "catalog_variants.csv"))
    assert o["catalog"]["items"] == len(pd.read_csv(P / "catalog_option_items.csv"))
    assert o["catalog"]["fitment_cells"] == len(pd.read_csv(P / "catalog_fitment.csv"))


def test_feature_verdicts_match_scorecard(client):
    api = {r["feature"]: r for r in client.get("/api/features").json()}
    card = pd.read_csv(config.REPORTS_DIR / "feature_scorecard.csv").set_index("feature")
    assert set(api) == set(card.index)
    for f, r in card.iterrows():
        assert api[f]["verdict"] == r["verdict"]
        assert api[f]["n_comments"] == r["n_comments"]
        assert abs(api[f]["complaint_index"] - r["index_negative"]) < 1e-9


def test_price_list_ground_truth(client):
    """Values read off the rendered PDF pages (G60 p.13, p.18; G70 p.4; F70 p.4)."""
    items = client.get("/api/catalog/G60/items?page_type=wheels").json()["items"]
    aero = next(i for i in items if i["sa_code"] == "3G3")
    assert aero["cells"]["520d"] == {"status": "optional", "price_eur": 1520.0, "price_condition": None}
    assert aero["cells"]["i5 eDrive40"]["price_eur"] == 300.0
    assert "i5 M60 xDrive" not in aero["cells"]
    opt = client.get("/api/catalog/G60/items?page_type=optional_equipment").json()["items"]
    vv = next(i for i in opt if i["sa_code"] == "2VV")
    assert vv["cells"]["i5 xDrive40"]["status"] == "standard"
    assert vv["cells"]["520i"]["price_eur"] == 1990.0          # cheapest: 'In Verbindung mit M Sportpaket'
    variants = {(m["model"], v["variant"]): v for m in client.get("/api/catalog").json()["models"] for v in m["variants"]}
    assert variants[("G70", "i7 M70 xDrive")]["base_price_eur"] == 182400.0
    assert variants[("F70", "116")]["base_price_eur"] == 34250.0
    assert variants[("G60", "i5 M60 xDrive")]["power_kw"] == 442.0


def test_catalog_validation_passed():
    quality = json.loads((config.REPORTS_DIR / "data_quality.json").read_text())
    v = quality["option_catalog"]
    stats = pd.read_csv(P / "catalog_page_stats.csv")
    assert v["glyphs_assigned"] == int(stats["glyphs"].sum()) == int(stats["cells"].sum())
    assert (stats["unassigned"] == 0).all()


def test_evaluate_is_traceable_and_deterministic(client):
    a = client.post("/api/evaluate", json={"idea": "climate control"}).json()
    b = client.post("/api/evaluate", json={"idea": "climate control"}).json()
    assert a["policy_hash"] == b["policy_hash"] and a["features"] == b["features"]
    sales = pd.read_csv(P / "sales.csv")
    from bmw_feedback.api import STATE
    cells = STATE["engine"].cells
    for f in a["features"]:
        for c in f["cells"]:
            group = decision.SALES_GROUP[c["model"]]
            vol = sales[(sales["model_group"] == group) & (sales["market_code"] == c["market"])]["volume"].sum()
            if c["recommendation"] == "Not sold":
                assert vol == 0
                continue
            comp = c["signals"]["complaints"]
            if comp.get("level") == "market":
                row = cells.loc[(f["feature"], c["model"], c["market"])]
                assert comp["n_comments"] == row["n_comments"]
                assert comp["verdict"] == row["verdict"]
            if c["market"] == "CN":
                assert comp["score"] is None            # no Chinese comments, no borrowing by default


def test_policy_change_changes_hash_and_scores(client):
    base = client.post("/api/evaluate", json={"features": ["Vehicle, climatization"]}).json()
    alt = client.post("/api/evaluate", json={"features": ["Vehicle, climatization"],
                                             "policy": {"weights": {"complaints": 1.0, "breadth": 0, "requests": 0,
                                                                    "survey": 0}}}).json()
    assert base["policy_hash"] != alt["policy_hash"]
    assert [c["score"] for c in base["features"][0]["cells"]] != [c["score"] for c in alt["features"][0]["cells"]]


def test_unknown_idea_reports_no_direct_evidence(client):
    r = client.post("/api/evaluate", json={"idea": "vacuum for pet hair removal"}).json()
    assert r["status"] == "no_direct_evidence" and r["features"] == []
    assert r["resolution"]["matches"]           # nearest features are still listed with scores


def test_classify_with_car_uses_fitment(client):
    r = client.post("/api/classify", json={"text": "the head up display is hard to read with sunglasses",
                                           "model": "G60", "engine": "BEV"}).json()
    assert r["prediction"]["feature"][0][0] == "Head-Up Display"
    assert r["prediction"]["reranked_with_fitment"] is True
    assert r["prediction"]["feature_fitment_tiers"]["Head-Up Display"] == "optional"


def test_decision_log_round_trip(client, tmp_path, monkeypatch):
    monkeypatch.setattr(decision, "log_path", lambda: tmp_path / "decisions.jsonl")
    bad = client.post("/api/decisions", json={"pm": "A", "idea": "x", "feature": "Seats", "decision": "accept",
                                              "rationale": "", "policy_hash": "p", "data_hash": "d"})
    assert bad.status_code == 422
    ok = client.post("/api/decisions", json={"pm": "A", "idea": "x", "feature": "Seats", "decision": "override",
                                             "rationale": "Known supplier fix", "policy_hash": "p", "data_hash": "d"})
    assert ok.status_code == 200
    log = client.get("/api/decisions").json()
    assert log[0]["id"] == ok.json()["id"] and log[0]["decision"] == "override"


# ---------------------------------------------------------------------- agents + knowledge graph
def test_agent_status_reports_graph_and_models(client):
    s = client.get("/api/agent/status").json()
    assert s["graph"]["checks_passed"] is True and s["graph"]["nodes"] > 13000
    assert s["llm_configured"] is False and "OPENAI_API_KEY" in s["message"]
    assert set(s["models"]) == {"retriever", "explainer", "verifier", "embedding"}


def test_agent_interpret_evaluate_round_trip(client):
    from bmw_feedback.api import STATE
    r = client.post("/api/agent/interpret", json={"idea": "Make seat massage standard on the 5 Series in Europe"})
    assert r.status_code == 200
    spec = r.json()["spec"]
    assert spec["features"][0]["feature"] == "Seat massage" and spec["series"] == ["G60"]
    e = client.post("/api/agent/evaluate", json={"spec": spec}).json()
    g = STATE["pipeline"].g
    assert e["facts"] and e["result"]["models"] == ["G60"] and e["result"]["markets"] == ["EU"]
    for f in e["facts"]:
        node = f["source"]["node_id"]
        assert node is None or node in g or node.startswith(("rec:", "idea:"))
    nodes = {n["id"] for n in e["graph"]["nodes"]}
    assert all(x["source"] in nodes and x["target"] in nodes for x in e["graph"]["edges"])
    again = client.post("/api/agent/evaluate", json={"spec": spec}).json()
    assert again["evaluation_id"] == e["evaluation_id"]


def test_agent_evaluate_rejects_feature_not_in_graph(client):
    spec = {"idea": "x", "summary": "x", "features": [{"feature": "Teleporter", "node_id": "feature:Teleporter",
                                                       "reason": "r"}]}
    assert client.post("/api/agent/evaluate", json={"spec": spec}).status_code == 422


def test_agent_explain_without_key_is_explicit(client):
    spec = client.post("/api/agent/interpret", json={"idea": "head-up display"}).json()["spec"]
    eid = client.post("/api/agent/evaluate", json={"spec": spec}).json()["evaluation_id"]
    r = client.post("/api/agent/explain", json={"evaluation_id": eid})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "llm_unavailable"
    assert client.post("/api/agent/explain", json={"evaluation_id": "nope"}).status_code == 404


def test_agent_explain_with_scripted_llm(client):
    from conftest import FakeLLM, judge_all
    from bmw_feedback.agents.contracts import ClaimLLM, ExplanationLLM
    from bmw_feedback.api import STATE
    spec = client.post("/api/agent/interpret", json={"idea": "head-up display"}).json()["spec"]
    e = client.post("/api/agent/evaluate", json={"spec": spec}).json()
    verdict = next(f for f in e["facts"] if f["id"] == "f1.overall.verdict")
    claim = ClaimLLM(text=f"Head-Up Display is rated '{verdict['value']}' overall.", fact_ids=[verdict["id"]])
    draft = ExplanationLLM(headline=claim, customer_evidence=[], market_view=[], price_and_equipment=[],
                           risks_and_caveats=[], next_steps=[])
    STATE["pipeline"].llm = FakeLLM({"explainer": [draft], "verifier": [judge_all()]})
    try:
        out = client.post("/api/agent/explain", json={"evaluation_id": e["evaluation_id"]}).json()
    finally:
        STATE["pipeline"].llm = None
    assert out["verification"]["n_verified"] == 1 and out["verification"]["n_removed"] == 0
    assert out["explanation"]["sections"]["headline"][0]["text"] == claim.text


def test_graph_endpoints(client):
    schema = client.get("/api/graph/schema").json()
    assert all(c["ok"] for c in schema["checks"])
    assert sum(t["count"] for t in schema["node_types"]) == schema["n_nodes"]
    node = client.get("/api/graph/node/feature:Head-Up Display").json()
    assert node["type"] == "Feature" and node["prov"]["ref"] == "reports/feature_scorecard.csv"
    assert any(n["rel"] == "LINKED_TO" for n in node["neighbours"])
    assert client.get("/api/graph/node/feature:Nope").status_code == 404


def test_graph_full_has_every_node_and_edge(client):
    r = client.get("/api/graph/full", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    full = r.json()
    schema = client.get("/api/graph/schema").json()
    assert full["n_nodes"] == schema["n_nodes"] == len(full["nodes"])
    assert full["n_edges"] == schema["n_edges"] == len(full["edges"])
    n = len(full["nodes"])
    assert all(0 <= u < n and 0 <= v < n for u, v, _ in full["edges"])
    assert all(isinstance(x, float) and isinstance(y, float) for *_, x, y in full["nodes"])
    assert len({(x, y) for *_, x, y in full["nodes"]}) > 0.99 * n          # leaves do not pile up on one point
