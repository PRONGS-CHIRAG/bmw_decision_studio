"""Decision tracker: change detection, baselines and lifecycle events (pure logic, hand-built snapshots)."""

import pytest

from bmw_feedback import tracker as T


def cell(model="G60", market="EU", rec="Consider", score=0.5, rivals=None):
    return {"model": model, "market": market, "recommendation": rec, "score": score, "signals": {}, "rivals": rivals}


def snap(*cells, rollup=0.5):
    return {"rollup_score": rollup, "cells": list(cells)}


# ---------------------------------------------------------------------- detect_changes
def test_identical_snapshots_have_no_changes():
    s = snap(cell(), cell(market="US", score=0.4))
    assert T.detect_changes(s, s) == []


def test_recommendation_change_is_reported_in_plain_words():
    ch = T.detect_changes(snap(cell(rec="Consider", score=0.55)), snap(cell(rec="Prioritise", score=0.61), rollup=0.5))
    assert [c["type"] for c in ch] == ["recommendation"]
    assert "Consider" in ch[0]["text"] and "Prioritise" in ch[0]["text"] and "5 Series" in ch[0]["text"]


def test_score_move_below_threshold_is_ignored_and_at_threshold_is_reported():
    assert T.detect_changes(snap(cell(score=0.50)), snap(cell(score=0.54))) == []
    ch = T.detect_changes(snap(cell(score=0.50)), snap(cell(score=0.55)))
    assert [c["type"] for c in ch] == ["score"]


def test_scores_of_cells_without_a_recommendation_are_not_compared():
    b = snap(cell(rec="Insufficient evidence", score=0.1))
    t = snap(cell(rec="Insufficient evidence", score=0.4))
    assert T.detect_changes(b, t) == []


def test_rollup_move_is_reported():
    ch = T.detect_changes(snap(cell(), rollup=0.40), snap(cell(), rollup=0.47))
    assert [c["type"] for c in ch] == ["rollup"]


def test_rival_equipment_change_is_reported_with_the_rival_name():
    before = {"item": "massage", "item_label": "Front seat massage", "statuses": {"merc-e": "optional"},
              "names": {"merc-e": "Mercedes E-Class"}}
    after = {**before, "statuses": {"merc-e": "standard"}}
    ch = T.detect_changes(snap(cell(rivals=before)), snap(cell(rivals=after)))
    assert [c["type"] for c in ch] == ["competitor"]
    assert ch[0]["text"] == "Mercedes E-Class: front seat massage optional -> standard (German equipment data)."


def test_baseline_without_rival_data_cannot_report_rival_changes():
    after = {"item": "massage", "item_label": "Front seat massage", "statuses": {"x": "standard"}, "names": {}}
    assert T.detect_changes(snap(cell(rivals=None)), snap(cell(rivals=after))) == []


# ---------------------------------------------------------------------- baseline and lifecycle
DECISION = {"id": "d1", "feature": "Seat massage", "recorded_at": "2026-10-10T10:00:00+00:00",
            "system_recommendation": {"rollup_score": 0.5, "cells": [{"model": "G60", "market": "EU",
                                                                      "recommendation": "Consider", "score": 0.5}]}}


def test_legacy_decision_baseline_comes_from_its_system_recommendation():
    base, source = T.baseline(DECISION, [])
    assert source["kind"] == "decision" and base["rollup_score"] == 0.5
    assert base["cells"][0]["recommendation"] == "Consider"


def test_latest_review_becomes_the_baseline():
    ev = [{"type": "reviewed", "decision_id": "d1", "pm": "Ana", "note": "seen", "recorded_at": "2026-10-11T09:00",
           "snapshot": snap(cell(rec="Prioritise", score=0.7), rollup=0.7)},
          {"type": "reviewed", "decision_id": "other", "pm": "Bo", "note": "x", "recorded_at": "2026-10-12T09:00",
           "snapshot": snap(cell(score=0.1), rollup=0.1)}]
    base, source = T.baseline(DECISION, ev)
    assert source == {"kind": "reviewed", "pm": "Ana", "recorded_at": "2026-10-11T09:00", "note": "seen"}
    assert base["rollup_score"] == 0.7


def test_scope_of_a_legacy_decision_is_read_from_its_cells():
    d = {**DECISION, "system_recommendation": {"cells": [{"model": "G60", "market": "EU"}, {"model": "G60", "market": "US"},
                                                         {"model": "G70", "market": "EU"}]}}
    assert T.scope(d) == {"models": ["G60", "G70"], "markets": ["EU", "US"]}


def test_lifecycle_defaults_to_decided_and_follows_status_events():
    assert T.lifecycle("d1", [])["status"] == "Decided"
    ev = [{"type": "status", "decision_id": "d1", "status": "In development", "pm": "Ana", "note": "go",
           "recorded_at": "1"},
          {"type": "status", "decision_id": "d1", "status": "Launched", "pm": "Ana", "note": "shipped",
           "recorded_at": "2"}]
    lc = T.lifecycle("d1", ev)
    assert lc["status"] == "Launched" and [h["status"] for h in lc["history"]] == ["In development", "Launched"]


# ---------------------------------------------------------------------- events
@pytest.fixture()
def events_file(tmp_path, monkeypatch):
    path = tmp_path / "decision_events.jsonl"
    monkeypatch.setattr(T, "events_path", lambda: path)
    return path


def test_status_event_is_appended_and_read_back(events_file):
    e = T.record_event({"type": "status", "decision_id": "d1", "pm": "Ana", "status": "Launched",
                        "note": "on sale"}, {"d1"})
    assert e["id"] and e["recorded_at"]
    assert T.read_events() == [e]
    T.record_event({"type": "status", "decision_id": "d1", "pm": "Ana", "status": "Dropped", "note": "recall"}, {"d1"})
    assert len(events_file.read_text().splitlines()) == 2          # appended, never rewritten


@pytest.mark.parametrize("entry,error", [
    ({"type": "status", "decision_id": "nope", "pm": "Ana", "status": "Launched", "note": "x y z"}, LookupError),
    ({"type": "status", "decision_id": "d1", "pm": "", "status": "Launched", "note": "x y z"}, ValueError),
    ({"type": "status", "decision_id": "d1", "pm": "Ana", "status": "Shipped", "note": "x y z"}, ValueError),
    ({"type": "status", "decision_id": "d1", "pm": "Ana", "status": "Launched", "note": "  "}, ValueError),
    ({"type": "reviewed", "decision_id": "d1", "pm": "Ana", "note": "looks fine"}, ValueError),     # no snapshot
    ({"type": "deleted", "decision_id": "d1", "pm": "Ana", "note": "x y z"}, ValueError),
])
def test_invalid_events_are_refused(events_file, entry, error):
    with pytest.raises(error):
        T.record_event(entry, {"d1"})
    assert not events_file.exists()
