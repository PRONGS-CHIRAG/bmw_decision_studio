"""Pure scoring/constraint checks use PM planning inputs, never customer fixtures."""

import copy
import math

import pytest

from pm_copilot.decision_core import (
    CRITERIA,
    build_run,
    customer_value,
    score_criteria,
)


def weights(**changes):
    result = dict.fromkeys(CRITERIA, 0.0)
    result.update(changes or {"customer": 1.0})
    return result


def candidate(identifier, cost=10, value=50, **changes):
    """An explicitly reviewed PM planning object, containing no customer evidence."""
    item = {
        "id": identifier,
        "market": "test-market",
        "development_cost": cost,
        "cost_basis": "PM planning assumption",
        "feasibility": "reviewed_feasible",
        "criteria": dict.fromkeys(CRITERIA, value),
        "dependencies": [],
        "exclusions": [],
        "mandatory": False,
        "reviewer": "Test PM",
        "rationale": "Test planning assumption",
    }
    item.update(changes)
    return item


def run(items, budget=100, **config):
    return build_run(
        {"project_id": "test-project", "markets": ["test-market"], "launch_year": 2030},
        items,
        {
            "budget": budget,
            "comparison_weights": dict.fromkeys(CRITERIA, 0.2),
            "market_weights": {"test-market": 1.0},
            "active_scenario": "baseline",
            "scenarios": {"baseline": {}},
            **config,
        },
        {"planning_inputs": "pm-assumptions-only"},
    )


def test_customer_value_zero_reviewed_benefit_stays_zero():
    assert customer_value(impact=0, frequency=100) == 0
    assert customer_value(impact=100, frequency=0) == 60
    assert customer_value(impact=100, frequency=100) == 100
    assert customer_value(impact=None, frequency=50) is None
    assert customer_value(impact=50, frequency=None) is None


def test_missing_active_criterion_has_bounds_and_no_invented_score():
    score = score_criteria({"customer": 80}, weights(customer=0.5, future=0.5))
    assert score["score"] is None
    assert score["lower_bound"] == 40
    assert score["upper_bound"] == 90
    assert score["missing"] == ["future"]


def test_zero_weight_unknown_is_disclosed_but_does_not_reduce_score():
    score = score_criteria({"customer": 80}, weights())
    assert score["score"] == 80
    assert "future" in score["unknown_criteria"]
    assert score["missing"] == []


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1, 101, True])
def test_invalid_criterion_numbers_fail_visibly(bad):
    with pytest.raises(ValueError):
        score_criteria({"customer": bad}, weights())


def test_A2_frozen_input_order_does_not_change_scores_or_selections():
    items = [candidate("b"), candidate("a")]
    a = run(items, budget=10)
    b = run(list(reversed(items)), budget=10)
    assert a == b
    assert a["portfolios"][0]["selected_ids"] == ["a"]


def test_A2_unrelated_candidate_does_not_change_existing_score():
    before = run([candidate("a")])
    after = run([candidate("a"), candidate("b", value=10)])
    assert before["candidate_scores"]["a"] == after["candidate_scores"]["a"]


def test_A4_budget_below_mandatory_is_infeasible():
    result = run([candidate("mandatory", cost=20, mandatory=True)], budget=10)
    assert result["status"] == "infeasible"
    assert result["portfolios"] == []
    assert "budget" in " ".join(result["conflicts"]).lower()


def test_A5_shared_dependency_cost_is_charged_once():
    items = [
        candidate("enabler", cost=10, value=0),
        candidate("a", cost=10, dependencies=["enabler"], mandatory=True),
        candidate("b", cost=10, dependencies=["enabler"], mandatory=True),
    ]
    result = run(items, budget=30)
    assert result["portfolios"][0]["cost"] == 30
    assert result["portfolios"][0]["selected_ids"] == ["a", "b", "enabler"]


def test_A5_optional_exclusions_produce_alternatives_not_global_conflict():
    result = run([
        candidate("a", exclusions=["b"], criteria={**dict.fromkeys(CRITERIA, 0), "customer": 100}),
        candidate("b", criteria={**dict.fromkeys(CRITERIA, 0), "future": 100}),
    ])
    assert result["status"] == "ready"
    assert all(len(p["selected_ids"]) <= 1 for p in result["portfolios"])
    assert {tuple(p["selected_ids"]) for p in result["portfolios"]} >= {("a",), ("b",)}


def test_A6_unknown_cost_is_excluded_and_mandatory_unknown_blocks_generation():
    result = run([candidate("unknown", cost=None)])
    assert result["candidate_scores"]["unknown"]["eligible"] is False
    assert all("unknown" not in p["selected_ids"] for p in result["portfolios"])
    blocked = run([candidate("unknown", cost=None, mandatory=True)])
    assert blocked["status"] == "unresolved"
    assert blocked["portfolios"] == []


def test_known_blocker_cannot_be_overridden_by_assumed_feasibility():
    result = run([candidate("a", mandatory=True, feasibility="assumed_feasible", blocked=True)])
    assert result["status"] == "infeasible"


def test_incomplete_priority_is_visible_but_not_optimized():
    result = run([candidate("a", criteria={"customer": 100})])
    assert result["candidate_scores"]["a"]["score"] is None
    assert result["candidate_scores"]["a"]["eligible"] is False
    assert result["investigation_queue"][0]["id"] == "a"


def test_generation_profile_cannot_silently_use_unknown_inactive_criteria():
    result = run([candidate("a", criteria={"customer": 100})], comparison_weights=weights())
    assert result["candidate_scores"]["a"]["eligible"] is True
    assert result["unavailable_profiles"]
    assert result["portfolios"][0]["selected_ids"] == ["a"]


def test_known_mandatory_budget_conflict_is_reported_despite_other_unknown_inputs():
    result = run([candidate("known", cost=50, mandatory=True), candidate("unknown", cost=None, mandatory=True)], budget=20)
    assert result["status"] == "infeasible"
    assert "budget" in " ".join(result["conflicts"]).lower()


def test_unequal_market_weights_change_aggregate_not_regional_score():
    items = [candidate("a", market="region-a", criteria=dict.fromkeys(CRITERIA, 100)),
             candidate("b", market="region-b", criteria=dict.fromkeys(CRITERIA, 50))]
    context = {"project_id": "test", "markets": ["region-a", "region-b"]}
    config = {"budget": 10, "weights": weights(), "market_weights": {"region-a": .1, "region-b": .9}}
    result = build_run(context, items, config, {})
    assert result["candidate_scores"]["a"]["score"] == 100
    assert result["candidate_scores"]["b"]["score"] == 50
    assert result["portfolios"][0]["selected_ids"] == ["b"]


def test_A7_scenario_values_change_selection_without_mutating_input():
    items = [
        candidate("a", criteria={**dict.fromkeys(CRITERIA, 0), "future": 90}),
        candidate("b", criteria={**dict.fromkeys(CRITERIA, 0), "future": 10}),
    ]
    original = copy.deepcopy(items)
    scenarios = {"baseline": {}, "alternative": {"criteria": {"a": {"future": 10}, "b": {"future": 90}}}}
    result = run(items, budget=10, scenarios=scenarios, comparison_weights=weights(future=1))
    changed = run(items, budget=10, scenarios=scenarios, comparison_weights=weights(future=1), active_scenario="alternative")
    assert result["portfolios"][0]["selected_ids"] == ["a"]
    assert changed["portfolios"][0]["selected_ids"] == ["b"]
    assert result["input_hash"] != changed["input_hash"]
    assert items == original
    assert all("alternative" in p["scenario_evaluations"] for p in result["portfolios"])


def test_A14_only_useful_distinct_options_are_returned():
    result = run([candidate("a", cost=0)])
    assert len(result["portfolios"]) == 1
    assert result["alternatives_note"]


def test_invalid_dependency_and_too_many_candidates_are_visible_errors():
    with pytest.raises(ValueError, match="dependency"):
        run([candidate("a", dependencies=["missing"])])
    with pytest.raises(ValueError, match="16"):
        run([candidate(str(i)) for i in range(17)])
