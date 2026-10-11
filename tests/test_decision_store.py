"""Decision snapshots use PM-only input objects in a temporary SQLite database."""

import sqlite3

import pytest

from pm_copilot.decision_core import CRITERIA, build_run
from pm_copilot.decision_store import DecisionStore


def planning_run(cost=10, project="planning-test"):
    return build_run(
        {"project_id": project, "markets": ["test-market"], "launch_year": 2030},
        [{"id": "pm-choice", "market": "test-market", "development_cost": cost,
          "feasibility": "reviewed", "criteria": dict.fromkeys(CRITERIA, 50),
          "mandatory": True, "reviewer": "Test PM", "rationale": "PM test assumption"}],
        {"budget": 20, "weights": dict.fromkeys(CRITERIA, 0.2), "scenarios": {"baseline": {}}},
        {},
    )


def approve(store, saved):
    return store.decide(saved["id"], saved["portfolios"][0]["id"], "approve", "Test PM",
                        "Accept the explicitly reviewed planning assumptions", acknowledge_assumptions=True)


def test_A11_approval_survives_reloading_store(tmp_path):
    path = tmp_path / "decisions.sqlite"
    store = DecisionStore(path)
    saved = store.save_run(planning_run())
    event = approve(store, saved)
    reloaded = DecisionStore(path)
    assert reloaded.get_decision(event["id"])["reviewer"] == "Test PM"
    assert reloaded.get_history(run_id=saved["id"])[0]["action"] == "approved"
    assert reloaded.get_run(saved["id"])["input_hash"] == saved["input_hash"]


def test_A12_new_draft_never_changes_approved_snapshot(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    first = store.save_run(planning_run())
    event = approve(store, first)
    second = store.save_run(planning_run(cost=15), parent_run_id=first["id"])
    assert second["id"] != first["id"]
    assert second["parent_run_id"] == first["id"]
    assert store.get_run(first["id"])["candidates"][0]["development_cost"] == 10
    assert store.export_decision(event["id"])["portfolio"]["cost"] == 10


def test_A13_export_contains_exact_approved_snapshot(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    source = planning_run()
    saved = store.save_run(source)
    event = approve(store, saved)
    source["candidates"][0]["development_cost"] = 999
    saved["portfolios"][0]["selected_ids"].append("not-persisted")
    exported = store.export_decision(event["id"])
    assert exported["run"]["candidates"][0]["development_cost"] == 10
    assert exported["portfolio"]["selected_ids"] == ["pm-choice"]
    assert exported["decision"]["run_id"] == saved["id"]


@pytest.mark.parametrize("reviewer,rationale", [("", "reason"), ("PM", " ")])
def test_all_decisions_require_reviewer_and_rationale(tmp_path, reviewer, rationale):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    saved = store.save_run(planning_run())
    with pytest.raises(ValueError):
        store.decide(saved["id"], None, "reject", reviewer, rationale)
    assert store.history() == []


def test_approval_requires_feasible_portfolio_and_assumption_acknowledgement(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    feasible = store.save_run(planning_run())
    with pytest.raises(ValueError, match="acknowledge"):
        store.decide(feasible["id"], feasible["portfolios"][0]["id"], "approve", "PM", "reason")
    impossible = store.save_run(planning_run(cost=30))
    with pytest.raises(ValueError, match="ready|feasible"):
        store.decide(impossible["id"], None, "approve", "PM", "reason", acknowledge_assumptions=True)


def test_unknown_portfolio_and_cross_project_parent_are_rejected(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    saved = store.save_run(planning_run())
    with pytest.raises(ValueError, match="portfolio"):
        store.decide(saved["id"], "invented", "approve", "PM", "reason", acknowledge_assumptions=True)
    with pytest.raises(ValueError, match="project"):
        store.save_run(planning_run(project="another"), parent_run_id=saved["id"])


@pytest.mark.parametrize("table", ["decision_runs", "decision_events"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_database_triggers_enforce_snapshot_immutability(tmp_path, table, operation):
    path = tmp_path / "decisions.sqlite"
    store = DecisionStore(path)
    approve(store, store.save_run(planning_run()))
    with sqlite3.connect(path) as connection:
        sql = f"DELETE FROM {table}" if operation == "DELETE" else f"UPDATE {table} SET id = id"
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(sql)


def test_rejected_decision_is_retained_but_not_exported_as_approval(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    saved = store.save_run(planning_run())
    event = store.decide(saved["id"], None, "reject", "PM", "Revise the planning assumptions")
    assert event["action"] == "rejected"
    with pytest.raises(ValueError, match="approved"):
        store.export_decision(event["id"])


def test_each_explicit_apply_creates_new_run_even_with_identical_inputs(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    first = store.save_run(planning_run())
    second = store.save_run(planning_run(), parent_run_id=first["id"])
    assert first["id"] != second["id"]
    assert first["input_hash"] == second["input_hash"]
    assert len(store.list_runs(project_id="planning-test")) == 2
