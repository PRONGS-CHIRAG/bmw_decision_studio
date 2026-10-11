"""API boundary checks use PM inputs; evidence integration uses raw-data fixtures."""

import pytest
from pydantic import ValidationError

from pm_copilot.decision_api import CandidateInput, ContextInput, RunConfig


def test_A6_unknown_cost_stays_unknown():
    candidate = CandidateInput(id="pm-action", feature="component: Steering wheel", market="EU", action="improve")
    assert candidate.development_cost is None
    assert candidate.impact is None


def test_A2_clients_cannot_supply_observed_counts():
    with pytest.raises(ValidationError):
        CandidateInput(id="pm-action", feature="component: Steering wheel", market="EU", action="improve", support_count=99)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_A6_invalid_cost_is_rejected(value):
    with pytest.raises(ValidationError):
        CandidateInput(id="pm-action", feature="component: Steering wheel", market="EU", action="improve", development_cost=value)


def test_A2_context_has_explicit_vehicle_and_unique_markets():
    with pytest.raises(ValidationError):
        ContextInput(vehicle="G60", launch_year=2030, markets=["EU", "EU"])


def test_A2_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        RunConfig(weights={"customer": 1, "future": 1, "delivery": 0, "regional": 0, "experience": 0})


def test_A7_unknown_scenario_values_not_replaced_with_defaults():
    candidate = CandidateInput(id="pm-action", feature="component: Steering wheel", market="EU", action="improve")
    assert all(value is None for value in candidate.scenario_values.values())
