"""Signal weights are a PM choice, but they must always sum to 1 (no data needed for these checks)."""

import pytest

from bmw_feedback.decision import DEFAULT_POLICY, PolicyError, merge_policy


def test_default_weights_sum_to_one():
    assert sum(DEFAULT_POLICY["weights"].values()) == pytest.approx(1.0)


def test_weights_that_sum_to_one_are_accepted():
    p = merge_policy({"weights": {"complaints": 0.25, "breadth": 0.25, "requests": 0.25, "survey": 0.25}})
    assert p["weights"] == {"complaints": 0.25, "breadth": 0.25, "requests": 0.25, "survey": 0.25, "competitors": 0.0}


def test_float_noise_from_percent_sliders_is_accepted():
    # 35 + 15 + 15 + 20 + 15 percent sent as floats
    merge_policy({"weights": {"complaints": 0.35, "breadth": 0.15, "requests": 0.15, "survey": 0.2, "competitors": 0.15}})


@pytest.mark.parametrize("weights", [
    {"complaints": 1.0, "breadth": 1.0, "requests": 0, "survey": 0},       # sums to 2
    {"complaints": 0.1, "breadth": 0.1, "requests": 0.1, "survey": 0.1},   # sums to 0.4
    {"complaints": 0.5},                                                   # others read as 0: 0.5
])
def test_weights_that_do_not_sum_to_one_are_rejected(weights):
    with pytest.raises(PolicyError, match="sum to 1"):
        merge_policy({"weights": weights})


def test_negative_weight_is_rejected():
    with pytest.raises(PolicyError, match="negative"):
        merge_policy({"weights": {"complaints": 1.2, "breadth": -0.2, "requests": 0, "survey": 0}})


def test_default_policy_has_five_signals_with_competitors_at_15_percent():
    w = DEFAULT_POLICY["weights"]
    assert DEFAULT_POLICY["version"] == "1.1"
    assert w == {"complaints": 0.35, "breadth": 0.15, "requests": 0.15, "survey": 0.2, "competitors": 0.15}


def test_stored_four_weight_policy_reads_competitors_as_zero():
    # a decision recorded under policy 1.0 must recompute with its own weights, not the new defaults
    p = merge_policy({"weights": {"complaints": 0.4, "breadth": 0.2, "requests": 0.2, "survey": 0.2}})
    assert p["weights"]["competitors"] == 0.0
