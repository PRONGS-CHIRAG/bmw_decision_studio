"""Knowledge graph and three-agent checks. No network: a scripted fake stands in for OpenAI.

Run after `python -m bmw_feedback all`:   python -m pytest tests -q
"""

import pandas as pd
import pytest
from pydantic import ValidationError

from bmw_feedback import config
from bmw_feedback.agents import verifier
from bmw_feedback.agents.contracts import Claim, ClaimLLM, ExplanationLLM, FeaturePickLLM, IdeaSpec, IdeaSpecLLM
from bmw_feedback.agents.llm import LLMOutputInvalid, LLMUnavailable
from bmw_feedback.agents.pipeline import Pipeline
from bmw_feedback.decision import DecisionEngine
from bmw_feedback.graph.build import nid
from bmw_feedback.graph.store import get_graph
from conftest import FakeLLM, judge_all

P = config.PROCESSED_DIR


@pytest.fixture(scope="module")
def pipe():
    p = Pipeline(DecisionEngine(), llm=None)
    return p


@pytest.fixture(scope="module")
def hud(pipe):
    spec = {"idea": "head-up display in Europe on the 5 Series", "summary": "HUD", "series": ["G60"],
            "markets": ["EU"], "move": "unspecified", "novelty": "matches_existing",
            "features": [{"feature": "Head-Up Display", "node_id": "feature:Head-Up Display", "reason": "test"}]}
    return pipe.evaluate(spec)


# ---------------------------------------------------------------------- knowledge graph
def test_graph_counts_match_source_tables():
    g, meta = get_graph()
    assert all(c["ok"] for c in meta["checks"]) and len(meta["checks"]) >= 18
    types = pd.Series([d["type"] for _, d in g.nodes(data=True)]).value_counts()
    assert types["Feature"] == len(pd.read_csv(config.REPORTS_DIR / "feature_scorecard.csv")) == 224
    assert types["Variant"] == len(pd.read_csv(P / "catalog_variants.csv"))
    assert types["Comment"] == len(pd.read_csv(P / "comments.csv", keep_default_na=False, na_values=[""]))
    for _, _, d in g.edges(data=True):
        assert d["rel"]
    for n, d in g.nodes(data=True):
        assert d["prov"]["kind"] and d["prov"]["ref"], n


def test_graph_values_trace_to_price_lists():
    g, _ = get_graph()
    assert g.nodes[nid("variant", "G70", "i7 M70 xDrive")]["base_price_eur"] == 182400.0
    item = next(n for n, d in g.nodes(data=True) if d["type"] == "OptionItem" and d.get("model") == "G60"
                and d.get("sa_code") == "2VV")
    edge = [d for _, v, d in g.out_edges(item, data=True) if v == nid("variant", "G60", "520i")]
    assert any(d["price_eur"] == 1990.0 for d in edge)
    linked = {g.nodes[v]["label"] for _, v, d in g.out_edges(nid("feature", "Head-Up Display"), data=True)
              if d["rel"] == "LINKED_TO" and g.nodes[v]["model"] == "G70"}
    assert "BMW 3D Head-Up Display" in linked
    cav = g.nodes[nid("caveat", "equipment-tables-partial|G70")]
    assert cav["variants_covered"] == 4 and cav["variants_listed"] == 7


def test_verdict_cells_equal_engine_cells(pipe):
    g = pipe.g
    for (f, m, k), r in pipe.engine.cells.head(200).iterrows():
        node = g.nodes[nid("verdict", "feature-series-market", f, m, k)]
        assert node["verdict"] == r["verdict"] and node["n_comments"] == r["n_comments"]


# ---------------------------------------------------------------------- Agent 1 contracts + retriever
def test_ideaspec_validation():
    ok = {"idea": "x", "summary": "x", "features": [{"feature": "Seats", "node_id": "feature:Seats", "reason": "r"}]}
    IdeaSpec.model_validate(ok, context={"allowed_features": {"Seats"}})
    with pytest.raises(ValidationError):
        IdeaSpec.model_validate(ok, context={"allowed_features": {"Head-Up Display"}})
    for bad in ({"series": ["G99"]}, {"markets": ["Mars"]}, {"proposed_price_eur": -5},
                {"series": ["G60", "G60"]}, {"novelty": "new_to_data"}):
        with pytest.raises(ValidationError):
            IdeaSpec.model_validate({**ok, **bad})
    with pytest.raises(ValidationError):
        IdeaSpec.model_validate({**ok, "features": [{"feature": "Seats", "node_id": "feature:Other", "reason": "r"}]})


def test_retriever_rejects_invalid_llm_output_then_accepts(pipe):
    bad = IdeaSpecLLM(summary="s", features=[FeaturePickLLM(feature="Teleporter", reason="r")], series=["G60"],
                      markets=["EU"], move="make_standard", proposed_price_eur=None, novelty="matches_existing",
                      ambiguities=[])
    good = bad.model_copy(update={"features": [FeaturePickLLM(feature="Seat massage", reason="r")]})
    fake = FakeLLM({"retriever": [bad, good]})
    r = pipe.retriever.interpret("Make seat massage standard on the 5 Series in Europe", fake)
    assert [a["ok"] for a in r.attempts] == [False, True]
    assert "Teleporter" in r.attempts[0]["errors"][0]
    assert r.spec.features[0].feature == "Seat massage" and r.spec.method == "llm:fake-luna"
    assert "Teleporter" not in fake.calls[0][1] and "rejected by validation" in fake.calls[1][1]
    assert r.semantic_error and "TF-IDF" in r.semantic_error


def test_retriever_falls_back_to_rules_after_repeated_invalid_output(pipe):
    bad = IdeaSpecLLM(summary="s", features=[FeaturePickLLM(feature="Teleporter", reason="r")], series=[],
                      markets=[], move="unspecified", proposed_price_eur=None, novelty="matches_existing",
                      ambiguities=[])
    r = pipe.retriever.interpret("seat massage", FakeLLM({"retriever": [bad, bad, bad]}))
    assert len(r.attempts) == 3 and not any(a["ok"] for a in r.attempts)
    assert r.spec.method.startswith("rules")


def test_rules_extract_scope(pipe):
    r = pipe.retriever.interpret("Make seat massage standard on the 5 Series in Europe for €1,500", None)
    s = r.spec
    assert [f.feature for f in s.features] == ["Seat massage"]
    assert s.series == ["G60"] and s.markets == ["EU"] and s.move == "make_standard"
    assert s.proposed_price_eur == 1500.0 and s.method == "rules"
    us = pipe.retriever.interpret("tell us about the head-up display", None).spec
    assert us.markets == []                     # 'us' the pronoun is not the United States


# ---------------------------------------------------------------------- facts
def test_facts_trace_to_graph_and_engine(pipe, hud):
    g = pipe.g
    facts = {f["id"]: f for f in hud["facts"]}
    for f in hud["facts"]:
        node = f["source"]["node_id"]
        assert node is None or node in g or node.startswith(("rec:", "idea:")), f["id"]
    cell = hud["result"]["features"][0]["cells"][0]
    assert facts["f1.G60.EU.recommendation"]["value"] == cell["recommendation"]
    row = pipe.engine.ctx.features.loc["Head-Up Display"]
    assert facts["f1.overall.complaint_index"]["value"] == round(float(row["index_negative"]), 2)
    assert any(i.startswith("caveat.") for i in facts)
    nodes = {n["id"] for n in hud["graph"]["nodes"]}
    assert "idea:current" in nodes and "rec:Head-Up Display|G60|EU" in nodes
    for e in hud["graph"]["edges"]:
        assert e["source"] in nodes and e["target"] in nodes


# ---------------------------------------------------------------------- Agent 3 rules
def _bundle(pipe, hud):
    return pipe._evals[hud["evaluation_id"]]["bundle"]


def test_verifier_rules(pipe, hud):
    b = _bundle(pipe, hud)
    idx = b.index()
    ci = idx["f1.overall.complaint_index"].value
    rec = idx["f1.G60.EU.recommendation"].value
    other = next(lb for lb in ("Prioritise", "Consider", "Low priority") if lb != rec)
    quote = next(f for f in b.facts if f.group == "quote")

    def run(text, ids):
        return {c.name: c.passed for c in verifier.rule_checks(Claim(id="c", section="s", text=text, fact_ids=ids),
                                                                idx)}

    assert all(run(f"Head-Up Display has a complaint index of {ci:.2f}.", ["f1.overall.complaint_index"]).values())
    assert not run(f"Head-Up Display has a complaint index of 9.87.",
                   ["f1.overall.complaint_index"])["numbers"]
    assert not run("The 7 Series (G70) has it.", ["f1.G60.EU.recommendation"])["scope"]
    assert run(f"On the 5 Series (G60) in Europe it is '{rec}'.", ["f1.G60.EU.recommendation"])["labels"]
    assert not run(f"On the 5 Series (G60) in Europe it is '{other}'.", ["f1.G60.EU.recommendation"])["labels"]
    words = " ".join(w for w in str(quote.value).split()[:6] if not set(w) & set("\"“”"))
    assert run(f"A customer wrote \"{words}\".", [quote.id])["quotes"]
    assert not run("A customer wrote \"this display is perfect in every way\".", [quote.id])["quotes"]
    assert not run("Something.", ["no.such.fact"])["citations"]
    assert not run("Something.", [])["citations"]


def test_retry_then_strip(pipe, hud):
    idx = _bundle(pipe, hud).index()
    ci = idx["f1.overall.complaint_index"].value
    good = ClaimLLM(text=f"Head-Up Display has a complaint index of {ci:.2f}.", fact_ids=["f1.overall.complaint_index"])
    fabricated = ClaimLLM(text="Complaints are 7.77 times the norm.", fact_ids=["f1.overall.complaint_index"])
    unsupported = ClaimLLM(text="Customers love it more every year.", fact_ids=["f1.overall.verdict"])

    def draft(*claims):
        return ExplanationLLM(headline=claims[0], customer_evidence=list(claims[1:]), market_view=[],
                              price_and_equipment=[], risks_and_caveats=[], next_steps=[])

    fake = FakeLLM({"explainer": [draft(good, fabricated), draft(good, fabricated, unsupported)],
                    "verifier": [judge_all(), judge_all(unsupported_text="every year")]})
    pipe.llm = fake
    try:
        out = pipe.explain(hud["evaluation_id"], force=True)
    finally:
        pipe.llm = None
    v = out["verification"]
    assert [c["text"] for c in v["rewritten"]] == [fabricated.text]
    removed = {c["text"]: c for c in v["claims"] if c["status"] == "removed"}
    assert set(removed) == {fabricated.text, unsupported.text}
    assert not next(ch for ch in removed[fabricated.text]["checks"] if ch["name"] == "numbers")["passed"]
    assert not next(ch for ch in removed[unsupported.text]["checks"] if ch["name"] == "semantic")["passed"]
    shown = [c["text"] for s in out["explanation"]["sections"].values() for c in s]
    assert shown == [good.text] and v["n_verified"] == 1 and v["n_removed"] == 2
    assert out["explanation"]["attempts"] == 2
    assert "FAILED VERIFICATION" in fake.calls[2][1] and fabricated.text in fake.calls[2][1]


def test_explain_needs_a_key(pipe, hud):
    pipe._env_llm, pipe.llm = False, None
    with pytest.raises(LLMUnavailable):
        pipe.explain(hud["evaluation_id"], force=True)


def test_retriever_retries_after_invalid_structured_output(pipe):
    good = IdeaSpecLLM(summary="s", features=[FeaturePickLLM(feature="Seat massage", reason="r")], series=[], markets=[],
                       move="unspecified", proposed_price_eur=None, novelty="matches_existing", ambiguities=[])
    fake = FakeLLM({"retriever": [LLMOutputInvalid("bad output", ["move: not a valid option"]), good]})
    r = pipe.retriever.interpret("seat massage", fake)
    assert [a["ok"] for a in r.attempts] == [False, True] and r.attempts[0]["errors"] == ["move: not a valid option"]
    assert r.spec.method == "llm:fake-luna"


def test_number_suffixes_cannot_hide_a_fabricated_figure(pipe):
    spec = {"idea": "hud", "summary": "hud", "series": ["G60"], "markets": ["EU"], "novelty": "matches_existing",
            "features": [{"feature": "Head-Up Display", "node_id": "feature:Head-Up Display", "reason": "t"}]}
    idx = pipe._evals[pipe.evaluate(spec)["evaluation_id"]]["bundle"].index()
    low = idx["f1.price.G60.min_eur"].value
    vol = idx["f1.G60.EU.volume"].value

    def numbers_pass(text, ids):
        checks = verifier.rule_checks(Claim(id="c", section="s", text=text, fact_ids=ids), idx)
        return next(c for c in checks if c.name == "numbers").passed

    assert numbers_pass(f"It costs from €{low / 1000:.1f}k today.", ["f1.price.G60.min_eur"])
    assert not numbers_pass(f"It costs from €{low / 1000 + 0.5:.1f}k today.", ["f1.price.G60.min_eur"])
    assert numbers_pass(f"The 5 Series sells {vol / 1000:.0f}k units in Europe.", ["f1.G60.EU.volume"])
    assert not numbers_pass(f"The 5 Series sells {vol / 1000 + 40:.0f}k units in Europe.", ["f1.G60.EU.volume"])
    assert not numbers_pass("Complaints run at 3x the norm.", ["f1.overall.complaint_index"])


def test_realistic_brief_is_not_over_stripped(pipe):
    """Claims phrased the way a PM-facing model writes (rounded, several markets, quotes, next steps) pass the rules."""
    spec = {"idea": "head-up display", "summary": "HUD", "novelty": "matches_existing",
            "features": [{"feature": "Head-Up Display", "node_id": "feature:Head-Up Display", "reason": "t"}]}
    idx = pipe._evals[pipe.evaluate(spec)["evaluation_id"]]["bundle"].index()
    v, ci = idx["f1.overall.verdict"], idx["f1.overall.complaint_index"]
    g60us, g70us = idx["f1.G60.US.recommendation"], idx["f1.G70.US.recommendation"]
    vol = idx["f1.G60.EU.volume"].value
    quote = next(f for f in idx.values() if f.group == "quote" and f.market == "US" and f.series == "G60")
    words = " ".join(str(quote.value).split()[2:9]).strip(".,;")
    brief = [
        (f"Customers rate it '{v.value}' overall (complaint index {ci.value:.1f}).", [v.id, ci.id]),
        (f"In the United States the 5 and 7 Series are '{g60us.value}' and '{g70us.value}'.", [g60us.id, g70us.id]),
        (f"In Europe the 5 Series sells {vol / 1000:.0f}k units a year.", ["f1.G60.EU.volume"]),
        (f"A US 5 Series customer wrote \"{words}\".", [quote.id]),
        ("Prices are German list prices only; there is no US or China price list in the data.", ["caveat.prices-de-only"]),
        ("Test the layout with 5 Series owners in Europe before changing anything else.", ["f1.G60.EU.recommendation"]),
    ]
    for text, ids in brief:
        failed = [c.detail for c in verifier.rule_checks(Claim(id="c", section="s", text=text, fact_ids=ids), idx)
                  if not c.passed]
        assert not failed, (text, failed)
