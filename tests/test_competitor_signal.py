"""Competitor signal: how far BMW is behind its top-5 rivals on an equipment item (pure calculation, PM-style inputs)."""

import pytest

from bmw_feedback.decision import MIN_KNOWN_RIVALS, competitor_gap


def test_rivals_standard_bmw_optional_gives_half_gap():
    g = competitor_gap({"a": "standard", "b": "standard", "c": "standard"}, "optional")
    assert g["score"] == pytest.approx(0.5)
    assert g["rival_mean"] == pytest.approx(1.0) and g["bmw_points"] == pytest.approx(0.5)


def test_bmw_ahead_of_rivals_is_clamped_to_zero():
    g = competitor_gap({"a": "not_available", "b": "optional", "c": "package"}, "standard_all")
    assert g["score"] == 0.0


def test_bmw_not_listed_and_no_row_are_the_same():
    rivals = {"a": "standard", "b": "optional", "c": "not_available"}
    assert competitor_gap(rivals, "not_listed")["score"] == competitor_gap(rivals, None)["score"] == pytest.approx(0.5)


def test_standard_on_some_variants_counts_three_quarters():
    g = competitor_gap({"a": "standard_some", "b": "standard_some", "c": "standard_some"}, "not_listed")
    assert g["score"] == pytest.approx(0.75)


def test_unknown_rivals_are_left_out_of_the_mean():
    g = competitor_gap({"a": "standard", "b": None, "c": "standard", "d": "not_available", "e": None}, "optional")
    assert g["n_known"] == 3
    assert g["score"] == pytest.approx(2 / 3 - 0.5, abs=1e-3)


def test_too_few_known_rivals_gives_no_score():
    g = competitor_gap({"a": "standard", "b": "standard", "c": None, "d": None}, "not_listed")
    assert MIN_KNOWN_RIVALS == 3
    assert g["score"] is None and "2 of" in g["status"]


# ---------------------------------------------------------------------- engine, on the real tables
@pytest.fixture(scope="module")
def engine():
    from bmw_feedback.competitors.build import load_tables
    if load_tables() is None:
        pytest.skip("competitor tables not built: run `python -m bmw_feedback competitors build`")
    from bmw_feedback.decision import DecisionEngine
    return DecisionEngine()


@pytest.mark.parametrize("feature,item,series,market", [
    ("Head-Up Display", "hud", "G60", "EU"),          # four rivals with data: a real score
    ("Head-Up Display", "hud", "G70", "US"),
    ("Seat massage", "massage", "G60", "EU"),         # one rival with data: no score on both sides
])
def test_signal_matches_the_competitor_comparison(engine, feature, item, series, market):
    """Recompute through CompetitorEngine (the comparison the UI shows): every rival status and the score agree."""
    from bmw_feedback.competitors.engine import CompetitorEngine
    t = CompetitorEngine().compare([series], [market], [feature])["tuples"][0]
    rivals = {c["model_id"]: c["equipment"][item]["status"] for c in t["competitors"]}
    expected = competitor_gap({m: (None if s == "unknown" else s) for m, s in rivals.items()},
                              t["bmw"]["equipment"][item].get("tier") or "not_listed")

    cell = engine.evaluate("", [feature], models=[series], markets=[market])["features"][0]["cells"][0]
    sig = cell["signals"]["competitors"]
    assert sig["item"] == item and sig["basis"] == "German equipment data"
    assert {r["model_id"]: r["status"] for r in sig["rivals"]} == rivals
    assert sig["score"] == expected["score"] and sig["n_known"] == expected["n_known"]


def test_head_up_display_has_a_real_score_to_compare(engine):
    sig = engine.evaluate("", ["Head-Up Display"], models=["G60"], markets=["EU"])["features"][0]["cells"][0][
        "signals"]["competitors"]
    assert sig["n_known"] >= 3 and sig["score"] is not None


def test_feature_without_equipment_item_has_no_competitor_signal(engine):
    cell = engine.evaluate("", ["Vehicle, climatization"], models=["G60"], markets=["EU"])["features"][0]["cells"][0]
    sig = cell["signals"]["competitors"]
    assert sig["score"] is None and "no competitor equipment data" in sig["status"]


def test_engine_without_competitor_tables_still_scores(engine):
    from bmw_feedback.decision import DecisionEngine
    bare = DecisionEngine(ctx=engine.ctx, competitor_tables=None)
    cell = bare.evaluate("", ["Seat massage"], models=["G60"], markets=["EU"])["features"][0]["cells"][0]
    assert cell["signals"]["competitors"]["score"] is None
    assert "not built" in cell["signals"]["competitors"]["status"]
    assert cell["score"] is not None
