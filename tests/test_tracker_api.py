"""Tracker endpoints, on the real data, with the decision and event logs in a temporary directory."""

import pytest
from fastapi.testclient import TestClient

from bmw_feedback import decision, tracker
from bmw_feedback.api import app

FEATURE = "Seat massage"
SCOPE = {"models": ["G60", "G70"], "markets": ["EU", "US"]}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        from bmw_feedback.api import STATE
        STATE["pipeline"]._env_llm, STATE["pipeline"].llm = False, None     # never call OpenAI from tests
        yield c


@pytest.fixture(autouse=True)
def tmp_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(decision, "log_path", lambda: tmp_path / "decisions.jsonl")
    monkeypatch.setattr(tracker, "events_path", lambda: tmp_path / "decision_events.jsonl")
    return tmp_path


def _evaluate(client, policy=None):
    body = {"features": [FEATURE], **SCOPE}
    if policy:
        body["policy"] = policy
    return client.post("/api/evaluate", json=body).json()


def _record(client, result, *, shift=0.0, legacy=False):
    fr = result["features"][0]
    cells = [{"model": c["model"], "market": c["market"], "recommendation": c["recommendation"],
              "score": None if c["score"] is None else round(c["score"] + shift, 3)} for c in fr["cells"]]
    body = {"pm": "Ana", "idea": "massage seats", "feature": FEATURE, "decision": "accept",
            "rationale": "Customers ask for it", "policy": result["policy"], "policy_hash": result["policy_hash"],
            "data_hash": result["data_hash"],
            "system_recommendation": {"headline": fr["headline"], "rollup_score": fr["rollup"]["score"], "cells": cells}}
    if not legacy:
        body["scope"] = SCOPE
    r = client.post("/api/decisions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_empty_log_gives_an_empty_tracker(client):
    r = client.get("/api/tracker").json()
    assert r["decisions"] == [] and r["n_needs_review"] == 0


def test_legacy_four_weight_decision_recomputes_without_changes(client):
    old = _evaluate(client, {"weights": {"complaints": 0.4, "breadth": 0.2, "requests": 0.2, "survey": 0.2}})
    d = _record(client, old, legacy=True)
    item = client.get("/api/tracker").json()["decisions"][0]
    assert item["decision"]["id"] == d["id"] and item["status"] == "ok"
    assert item["scope"] == SCOPE
    assert item["changes"] == [] and item["needs_review"] is False
    assert item["lifecycle"]["status"] == "Decided"


def test_moved_metrics_need_review_and_a_review_resets_the_baseline(client):
    d = _record(client, _evaluate(client), shift=-0.2, legacy=True)   # stored scores 0.2 lower than today's
    r = client.get("/api/tracker").json()
    assert r["n_needs_review"] == 1
    item = r["decisions"][0]
    assert item["needs_review"] and {c["type"] for c in item["changes"]} & {"score", "recommendation"}

    bad = client.post(f"/api/tracker/{d['id']}/review", json={"pm": "Ana", "note": ""})
    assert bad.status_code == 400
    ok = client.post(f"/api/tracker/{d['id']}/review", json={"pm": "Ana", "note": "Rival moved; still Consider"})
    assert ok.status_code == 200
    item = client.get("/api/tracker").json()["decisions"][0]
    assert not item["needs_review"] and item["baseline"]["source"]["kind"] == "reviewed"


def test_lifecycle_status_updates_and_validation(client):
    d = _record(client, _evaluate(client))
    r = client.post(f"/api/tracker/{d['id']}/status", json={"pm": "Ana", "status": "In development", "note": "Go ahead"})
    assert r.status_code == 200
    item = client.get("/api/tracker").json()["decisions"][0]
    assert item["lifecycle"]["status"] == "In development"
    assert client.post(f"/api/tracker/{d['id']}/status",
                       json={"pm": "Ana", "status": "Shipped", "note": "x y z"}).status_code == 400
    assert client.post("/api/tracker/unknown/status",
                       json={"pm": "Ana", "status": "Launched", "note": "x y z"}).status_code == 404


def test_decision_for_a_feature_no_longer_in_the_data_is_shown_not_dropped(client):
    res = _evaluate(client)
    res["features"][0]["cells"] = res["features"][0]["cells"][:1]
    body = {"pm": "Ana", "idea": "x", "feature": "A feature that does not exist", "decision": "override",
            "rationale": "Legacy entry", "policy": res["policy"], "policy_hash": "p", "data_hash": "d",
            "scope": SCOPE, "system_recommendation": {"rollup_score": 0.5, "cells": []}}
    assert client.post("/api/decisions", json=body).status_code == 200
    item = client.get("/api/tracker").json()["decisions"][0]
    assert item["status"] == "cannot_recompute" and "no longer" in item["reason"]


def test_recording_with_a_scope_stores_a_server_computed_snapshot_with_rivals(client):
    d = _record(client, _evaluate(client))
    snap = d["snapshot"]
    assert {(c["model"], c["market"]) for c in snap["cells"]} == {(m, k) for m in SCOPE["models"] for k in SCOPE["markets"]}
    assert any(c["rivals"] and c["rivals"]["item"] == "massage" for c in snap["cells"])
    assert "competitors" in snap["cells"][0]["signals"]


def test_decision_without_a_stored_policy_is_not_compared_like_for_like(client):
    res = _evaluate(client)
    fr = res["features"][0]
    body = {"pm": "Ana", "idea": "x", "feature": FEATURE, "decision": "accept", "rationale": "No policy stored",
            "policy_hash": "p", "data_hash": "d",
            "system_recommendation": {"rollup_score": fr["rollup"]["score"],
                                      "cells": [{"model": c["model"], "market": c["market"],
                                                 "recommendation": c["recommendation"], "score": c["score"]}
                                                for c in fr["cells"]]}}
    assert client.post("/api/decisions", json=body).status_code == 200
    item = client.get("/api/tracker").json()["decisions"][0]
    assert item["status"] == "cannot_recompute" and "no policy" in item["reason"]
    assert item["needs_review"] is False


def test_rebuilt_competitor_data_is_picked_up_and_a_rival_change_is_flagged(client, monkeypatch):
    """A rival makes the head-up display standard: after the rebuild, the tracker flags it without a restart."""
    import copy

    from bmw_feedback.competitors import build as cbuild
    scope = {"models": ["G70"], "markets": ["EU"]}
    res = client.post("/api/evaluate", json={"features": ["Head-Up Display"], **scope}).json()
    body = {"pm": "Ana", "idea": "HUD", "feature": "Head-Up Display", "decision": "accept", "rationale": "Plan it",
            "policy": res["policy"], "policy_hash": res["policy_hash"], "data_hash": res["data_hash"], "scope": scope}
    d = client.post("/api/decisions", json=body).json()
    cell = d["snapshot"]["cells"][0]
    rival = next(m for m, st in cell["rivals"]["statuses"].items() if st in ("optional", "package", "not_available"))
    assert client.get("/api/tracker").json()["n_needs_review"] == 0

    tables = copy.deepcopy(cbuild.load_tables())
    eq = tables["equipment"]
    eq.loc[(eq["model_id"] == rival) & (eq["item"] == "hud"), ["status", "variant_scope"]] = ["standard", None]
    quality = {**(cbuild.load_quality() or {}), "data_hash": "rebuilt-for-test"}
    monkeypatch.setattr(cbuild, "load_tables", lambda: tables)
    monkeypatch.setattr(cbuild, "load_quality", lambda: quality)

    r = client.get("/api/tracker").json()
    assert r["competitor_data_hash"] == "rebuilt-for-test"
    item = next(i for i in r["decisions"] if i["decision"]["id"] == d["id"])
    comp = [c for c in item["changes"] if c["type"] == "competitor"]
    assert item["needs_review"] and comp and comp[0]["model_id"] == rival and comp[0]["after"] == "standard"
