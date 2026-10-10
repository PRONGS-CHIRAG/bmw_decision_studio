"""No external calls or invented customer evidence in agent contract tests."""

import pytest

from pm_copilot.decision_agents import AgentUnavailable, agent_status, validate_claims


def test_A9_unresolvable_citation_is_rejected():
    with pytest.raises(AgentUnavailable, match="citation"):
        validate_claims([{"text": "", "evidence_ids": ["missing"], "metric_ids": []}], {}, {})


def test_A9_unresolvable_calculation_is_rejected():
    with pytest.raises(AgentUnavailable, match="metric"):
        validate_claims([{"text": "", "evidence_ids": [], "metric_ids": ["missing"]}], {}, {})


def test_A9_uncited_claim_is_rejected():
    with pytest.raises(AgentUnavailable, match="citation"):
        validate_claims([{"text": "Unsupported claim", "evidence_ids": [], "metric_ids": []}], {}, {})


def test_A9_agent_unavailable_without_model_or_key(monkeypatch):
    monkeypatch.setattr("pm_copilot.decision_agents.settings", lambda: ("", ""))
    assert agent_status()["status"] == "unavailable"
