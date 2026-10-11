"""Competitor data, comparison and the two competitor agents. No network: a scripted fake stands in for OpenAI.

The synthetic tests build from rows written to a temporary folder; the data tests check the processed tables
written by `python -m bmw_feedback competitors build` and are skipped when those are absent.
"""

import json

import pandas as pd
import pytest

from bmw_feedback import config
from bmw_feedback.agents import competition
from bmw_feedback.agents.contracts import (CompetitorAnalysisLLM, CompetitorBriefLLM, FactBundle, FindingLLM,
                                           PresentedClaimLLM)
from bmw_feedback.competitors import build, records, registry, snapshot
from conftest import FakeLLM, judge_all

HAS_TABLES = build.load_tables() is not None


# ---------------------------------------------------------------------- validator
@pytest.mark.parametrize("text,value,ok", [
    ("2025 fell 23.1 percent to 13,575", 13575, True), ("Preis 62.300,00 €", 62300, True), ("ab 1.190 Euro", 1190, True),
    ("指导价43.99万元", 439900, True), ("$58,450 MSRP", 58450, True), ("6,1 s", 6.1, True), ("5 060 mm", 5060, True),
    ("13,575", 13576, False), ("1.190 Euro", 119, False), ("E200", 200, False),
])
def test_numbers_in_evidence(text, value, ok):
    assert records.number_in(value, text) is ok


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Snapshot, text and extracted folders in a temporary directory, with one saved page."""
    raw, txt, ext = tmp_path / "raw", tmp_path / "text", tmp_path / "extracted"
    for d in (raw, txt, ext):
        d.mkdir()
    monkeypatch.setattr(snapshot, "RAW_DIR", raw)
    monkeypatch.setattr(snapshot, "TEXT_DIR", txt)
    monkeypatch.setattr(registry, "EXTRACTED_DIR", ext)

    def page(sid, text, publisher="example.org"):
        (raw / sid).mkdir()
        (raw / sid / "meta.json").write_text(json.dumps({
            "source_id": sid, "url": f"https://{publisher}/{sid}", "final_url": f"https://{publisher}/{sid}",
            "publisher": publisher, "title": sid, "retrieved_at": "2026-10-11T10:00:00+0200", "kind": "html",
            "rendered": False, "sha256": "0" * 64, "bytes": len(text), "ok": True}))
        (txt / f"{sid}.txt").write_text(text)

    def rows(name, items):
        (ext / name).write_text("\n".join(json.dumps(r) for r in items) + "\n")

    return page, rows, ext


def test_validator_rejects_invented_values(sandbox):
    page, _, _ = sandbox
    page("s0000000001", "In 2025 the E-Class sold 13,575 units in the US.\nBase MSRP $63,050 for the E 350.")
    base = {"table": "sales", "model_id": "mercedes-e-class", "market": "US", "region": "United States", "year": 2025,
            "units": 13575, "basis": "sales", "tier": "aggregator", "source_id": "s0000000001",
            "evidence": "In 2025 the E-Class sold 13,575 units"}
    assert records.validate_record(base) == []
    assert any("not written in the evidence" in e for e in records.validate_record({**base, "units": 13600}))
    assert any("not in source" in e for e in records.validate_record({**base, "evidence": "sold 14,000 units"}))
    assert any("unknown source_id" in e for e in records.validate_record({**base, "source_id": "s9999999999"}))
    assert any("basis must be" in e for e in records.validate_record({**base, "basis": "guess"}))
    price = {"table": "price", "model_id": "bmw-5-series", "market": "EU", "country": "DE", "currency": "EUR",
             "variant": "520i", "amount": 63050, "powertrain": "ICE", "price_type": "list_price", "tax_basis": "x",
             "source_id": "s0000000001", "evidence": "Base MSRP $63,050"}
    assert any("BMW's own DE price list" in e for e in records.validate_record(price))
    wrong_cur = {**price, "model_id": "mercedes-e-class", "currency": "USD"}
    assert any("must be in EUR" in e for e in records.validate_record(wrong_cur))


def test_selection_ranks_by_segment_sales_and_falls_back_to_rivals(sandbox, monkeypatch):
    page, rows, ext = sandbox
    lines = [f"Model {i} sold {u:,} units in 2025 in Europe." for i, u in enumerate([9000, 7000, 5000, 3000], start=1)]
    page("s0000000001", "\n".join(lines) + "\nThe BMW sold 8,000 units in 2025 in Europe.\n"
         "The People's Saloon sold 12,000 units in 2025 in Europe.\nThe Tiny Exec sold 100 units in 2025 in Europe.")
    page("s0000000002", "Rivals: the Rival Five and the Rival Six are named as 5 Series competitors.", "press.example")
    models = [{"table": "model", "model_id": f"maker-m{i}", "brand": "Genesis", "model": f"M{i}", "segment": "executive",
               "body": "saloon"} for i in range(1, 7)]
    models.append({"table": "model", "model_id": "people-saloon", "brand": "Volkswagen", "model": "Saloon",
                   "segment": "executive", "body": "saloon"})                   # mainstream brand: not a premium rival
    models.append({"table": "model", "model_id": "tiny-exec", "brand": "Lexus", "model": "Tiny", "segment": "executive",
                   "body": "saloon"})                                          # below 2% of the BMW's volume
    models.append({"table": "model", "model_id": "bmw-5-series", "brand": "BMW", "model": "5 Series",
                   "segment": "executive", "body": "saloon"})
    models.append({"table": "model", "model_id": "maker-compact", "brand": "Maker", "model": "C", "segment": "compact",
                   "body": "hatch"})
    sales = [{"table": "sales", "model_id": f"maker-m{i}", "market": "EU", "region": "Europe (EU+EFTA+UK)",
              "year": 2025, "units": u, "basis": "registrations", "tier": "aggregator", "source_id": "s0000000001",
              "evidence": f"Model {i} sold {u:,} units in 2025 in Europe."}
             for i, u in enumerate([9000, 7000, 5000, 3000], start=1)]
    sales.append({"table": "sales", "model_id": "bmw-5-series", "market": "EU", "region": "Europe (EU+EFTA+UK)",
                  "year": 2025, "units": 8000, "basis": "registrations", "tier": "aggregator",
                  "source_id": "s0000000001", "evidence": "The BMW sold 8,000 units in 2025 in Europe."})
    for mid, u, txt in (("people-saloon", 12000, "The People's Saloon sold 12,000 units in 2025 in Europe."),
                        ("tiny-exec", 100, "The Tiny Exec sold 100 units in 2025 in Europe.")):
        sales.append({"table": "sales", "model_id": mid, "market": "EU", "region": "Europe (EU+EFTA+UK)", "year": 2025,
                      "units": u, "basis": "registrations", "tier": "aggregator", "source_id": "s0000000001",
                      "evidence": txt})
    rivals = [{"table": "rival", "model_id": mid, "bmw_series": "G60", "market": "EU", "source_id": "s0000000002",
               "evidence": "Rivals: the Rival Five and the Rival Six are named as 5 Series competitors."}
              for mid in ("maker-m5", "maker-m6", "maker-compact")]
    # a rival counts only if it is present in the market (a price or sales row there)
    prices = [{"table": "price", "model_id": mid, "market": "EU", "country": "DE", "currency": "EUR",
               "variant": "Base", "amount": 50000 + i, "powertrain": "ICE", "price_type": "list_price",
               "tax_basis": "incl. 19% VAT", "entry": True, "source_id": "s0000000003",
               "evidence": f"Base {50000 + i:,} EUR"} for i, mid in enumerate(["maker-m5", "maker-compact"])]
    page("s0000000003", "Base 50,000 EUR. Base 50,001 EUR.")
    rows("all.jsonl", models + sales + rivals + prices)
    tables, quality = build.build()
    sets = tables["sets"]
    g = sets[(sets["series"] == "G60") & (sets["market"] == "EU")].sort_values("rank")
    assert list(g["model_id"]) == ["maker-m1", "maker-m2", "maker-m3", "maker-m4", "maker-m5"]
    assert list(g["basis"]) == ["sales"] * 4 + ["rival_mentions"]
    assert "bmw-5-series" not in set(g["model_id"])                       # BMW is never its own competitor
    assert not {"people-saloon", "tiny-exec"} & set(g["model_id"])         # mainstream brand; below 2% of the BMW
    assert tables["models"].set_index("model_id").loc["people-saloon", "competitive_segment"] == "large"
    f70 = sets[(sets["series"] == "F70") & (sets["market"] == "US")]
    assert f70["basis"].tolist() == ["not_sold"]                         # sales_volumes.xlsx: no F70 in the US
    assert all(quality["checks"].values())
    assert tables["sales"]["row_id"].is_unique and tables["prices"]["row_id"].is_unique


def test_bmw_side_comes_from_the_price_list():
    t = build.bmw_tables()
    var = pd.read_csv(config.PROCESSED_DIR / "catalog_variants.csv")
    for m, g in var.groupby("model"):
        entry = t["bmw_prices"][(t["bmw_prices"]["model"] == m) & t["bmw_prices"]["entry"]]
        assert len(entry) == 1 and entry["amount"].iloc[0] == g["base_price_eur"].min()
    eq = t["bmw_equipment"].set_index(["model", "item"])
    assert eq.loc[("G70", "hud"), "tier"] == "standard_all"                # BMW 3D Head-Up Display, standard on the G70
    assert eq.loc[("G60", "hud"), "tier"] == "optional" and eq.loc[("G60", "hud"), "price_min_eur"] == 2400.0
    assert eq.loc[("G60", "hud"), "via_package"] == True                     # noqa: E712 - inside the Innovationspaket


# ---------------------------------------------------------------------- processed data
needs_tables = pytest.mark.skipif(not HAS_TABLES, reason="run `python -m bmw_feedback competitors build` first")


@needs_tables
def test_competitor_tables_are_consistent():
    t = build.load_tables()
    q = build.load_quality()
    assert all(q["checks"].values()) and q["records"]["errors"] == 0
    sets = t["sets"]
    assert len(sets.groupby(["series", "market"])) == 12
    assert (sets.dropna(subset=["model_id"]).groupby(["series", "market"]).size() <= 5).all()
    assert not sets["model_id"].isin(registry.SELF_SERIES).any()
    sold = {(s, m) for s in config.MODELS for m in registry.MARKETS if build.bmw_sold(s, m)}
    for (s, m), g in sets.groupby(["series", "market"]):
        assert (g["basis"].iloc[0] == "not_sold") == ((s, m) not in sold)
    used = set(pd.concat([t[k]["source_id"] for k in ("sales", "prices", "specs", "equipment", "ratings", "rivals",
                                                        "reviews")]))
    assert used <= set(t["sources"]["source_id"])
    for _, r in t["prices"].iterrows():                                     # one currency per reference country
        ref = registry.REFERENCE[r["market"]]
        if r["country"] == ref["country"]:
            assert r["currency"] == ref["currency"]


@needs_tables
def test_every_stored_value_is_quoted_from_its_source():
    """Re-check the saved snapshots (when present): each number is in its evidence and each quote in its page."""
    t = build.load_tables()
    checked = 0
    for table, col in (("sales", "units"), ("prices", "amount"), ("specs", "value"), ("ratings", "score")):
        for _, r in t[table].iterrows():
            assert records.number_in(r[col], r["evidence"]), (table, r["row_id"])
            ok, detail = records.evidence_in_source(r["evidence"], r["source_id"])
            assert ok is not False, detail
            checked += ok is True
    assert checked > 0 or not snapshot.all_sources()        # with snapshots on disk, every quote was re-checked


@needs_tables
def test_comparison_and_facts_trace_to_the_graph():
    from bmw_feedback.competitors.engine import CompetitorEngine
    from bmw_feedback.competitors.facts import build_bundle
    from bmw_feedback.graph.store import get_graph
    g, _ = get_graph()
    eng = CompetitorEngine()
    cmp = eng.compare(features=["Head-Up Display", "Seat massage"])
    assert len(cmp["tuples"]) == 12
    for tup in cmp["tuples"]:
        if tup["status"] != "ok":
            continue
        ref = tup["reference"]
        for c in tup["competitors"]:
            if c["entry"] and c["gap"]:                         # same market, currency and price basis on both sides
                br = c["bmw_ref"]
                assert c["entry"]["currency"] == ref["currency"] == br["currency"]
                assert c["entry"]["basis"] == br["basis"]
                assert br["amount"] == min(p["amount"] for p in tup["bmw"]["prices"] if p["basis"] == br["basis"])
                assert c["gap"]["abs"] == round(c["entry"]["amount"] - br["amount"], 2)
            for row in c["by_powertrain"]:
                if row["gap"]:
                    assert row["competitor"]["basis"] == row["bmw"]["basis"]
    bundle, missing = build_bundle(cmp, g, "cxtest")
    ids = [f.id for f in bundle.facts]
    assert len(ids) == len(set(ids))
    assert missing == [], f"facts point to nodes missing from the graph: {missing[:5]}"
    assert any(f.group == "price" for f in bundle.facts)


# ---------------------------------------------------------------------- agents (scripted LLM)
def _bundle():
    from bmw_feedback.agents.contracts import Fact, Provenance
    p = Provenance(node_id=None, kind="web", ref="https://example.org")
    facts = [
        Fact(id="cx.G60.EU.set", group="set", statement="Top 2 competitors of the 5 Series (G60) in Europe: 1. Mercedes-Benz "
             "E-Class (61,000 units); 2. Audi A6 (55,000 units).", value=2, series="G60", market="EU", source=p),
        Fact(id="cx.G60.EU.bmw.entry", group="price", statement="Entry price of the 5 Series (G60) in Germany: EUR 60,000.",
             value=60000, series="G60", market="EU", source=p),
        Fact(id="cx.G60.EU.c1.entry", group="price", statement="Entry price of the Mercedes-Benz E-Class in Germany: "
             "EUR 62,000; that is EUR 2,000 (3.3%) above the 5 Series (G60) entry price of EUR 60,000.", value=62000,
             series="G60", market="EU", source=p),
        Fact(id="cx.caveat.list-prices", group="caveat", statement="Prices are list prices without discounts.",
             source=p),
    ]
    return FactBundle(evaluation_id="cxtest", idea="test", facts=facts)


def test_finding_rules_check_tuple_and_dimension():
    b = _bundle()
    rule = competition.finding_rules({"a1": {"series": "G60", "market": "US", "dimension": "price"},
                                      "a2": {"series": "G60", "market": "EU", "dimension": "customers"}})
    from bmw_feedback.agents.contracts import Finding
    f1 = Finding(id="a1", section="price", text="x", fact_ids=["cx.G60.EU.c1.entry"], series="G60", market="US")
    f2 = Finding(id="a2", section="customers", text="x", fact_ids=["cx.G60.EU.c1.entry"], series="G60", market="EU")
    c1 = {c.name: c.passed for c in rule(f1, b.index())}
    c2 = {c.name: c.passed for c in rule(f2, b.index())}
    assert c1 == {"tuple": False, "dimension": True} and c2 == {"tuple": True, "dimension": False}


def test_analyst_rewrites_then_presenter_falls_back_to_verified_findings():
    good = FindingLLM(series="G60", market="EU", dimension="price", fact_ids=["cx.G60.EU.c1.entry"],
                      text="In Europe the Mercedes-Benz E-Class starts EUR 2,000 (3.3%) above the 5 Series (G60).")
    bad = FindingLLM(series="G60", market="EU", dimension="price", fact_ids=["cx.G60.EU.c1.entry"],
                     text="In Europe the E-Class costs EUR 2,500 more than the 5 Series (G60).")
    fixed = FindingLLM(series="G60", market="EU", dimension="selection", fact_ids=["cx.G60.EU.set"],
                       text="In Europe the Mercedes-Benz E-Class is the best-selling rival of the 5 Series (G60), "
                            "with 61,000 units.")
    llm = FakeLLM({
        "analyst": [CompetitorAnalysisLLM(findings=[good, bad]), CompetitorAnalysisLLM(findings=[good, fixed])],
        "verifier": [judge_all(), judge_all(), judge_all(unsupported_text="cheaper")],
        "presenter": [CompetitorBriefLLM(
            headline=PresentedClaimLLM(text="In Europe the 5 Series (G60) starts below the E-Class.",
                                       fact_ids=["cx.G60.EU.c1.entry"], finding_ids=["a3"]),
            price_position=[PresentedClaimLLM(text="The E-Class is cheaper than the 5 Series (G60) in Europe.",
                                              fact_ids=["cx.G60.EU.c1.entry"], finding_ids=["a3"])],
            equipment=[], product_and_sales=[], customer_view=[], implications=[],
            caveats=[PresentedClaimLLM(text="Prices are list prices without discounts.",
                                       fact_ids=["cx.caveat.list-prices"], finding_ids=[])])],
    })
    res = competition.analyse_series(llm, _bundle(), {"features": [], "idea": "x"}, "G60", 0)
    assert res["attempts"] == 2 and [c.text for c in res["rewritten"]] == [bad.text]
    verified = [c for c in res["claims"] if c.status == "verified"]
    assert {c.section for c in verified} == {"price", "selection"}
    shown, claims = competition.present(llm, _bundle(), {"features": [], "idea": "x"}, verified)
    status = {c.text: c.status for c in claims}
    assert status["The E-Class is cheaper than the 5 Series (G60) in Europe."] == "removed"     # judged unsupported
    assert [c.origin for c in shown["price_position"]] == ["analyst_fallback"]                 # replaced by finding a3
    assert shown["price_position"][0].text == verified[0].text
    assert shown["headline"] and shown["caveats"]


def test_service_reports_missing_key(tmp_path):
    from bmw_feedback.agents.llm import LLMUnavailable
    svc = competition.CompetitionService(llm_getter=lambda: None)
    svc._cache["cx1"] = {"scope": {}, "comparison": {"tuples": []}, "bundle": _bundle(), "analysed": None}
    with pytest.raises(LLMUnavailable):
        svc.analyse("cx1")
    with pytest.raises(KeyError):
        svc.analyse("nope")


# ---------------------------------------------------------------------- API
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from bmw_feedback.api import STATE, app
    with TestClient(app) as c:
        STATE["pipeline"]._env_llm, STATE["pipeline"].llm = False, None     # never call OpenAI from tests
        yield c


def test_competitor_endpoints(client):
    s = client.get("/api/competitors/status").json()
    assert "available" in s
    r = client.post("/api/competitors/compare", json={"series": ["G60"], "markets": ["EU", "US"],
                                                      "features": ["Head-Up Display"]})
    assert r.status_code == 200
    body = r.json()
    if not body["available"]:
        assert body["competition_id"] is None
        return
    assert [(t["series"], t["market"]) for t in body["comparison"]["tuples"]] == [("G60", "EU"), ("G60", "US")]
    again = client.post("/api/competitors/compare", json={"series": ["G60"], "markets": ["EU", "US"],
                                                          "features": ["Head-Up Display"]}).json()
    assert again["competition_id"] == body["competition_id"] and again["facts"] == body["facts"]
    out = client.post("/api/agent/competitors", json={"competition_id": body["competition_id"]})
    assert out.status_code == 503 and out.json()["detail"]["code"] == "llm_unavailable"
    assert client.post("/api/agent/competitors", json={"competition_id": "missing"}).status_code == 404


def test_model_name_digits_are_not_data():
    from bmw_feedback.agents.verifier import numbers_in
    cmp = {"tuples": [{"competitors": [{"name": "DS Automobiles DS 4", "brand": "DS Automobiles", "model": "DS 4"},
                                       {"name": "Avatr 12", "brand": "Avatr", "model": "12"}]}]}
    names = competition.model_names(cmp)
    assert "DS 4" in names and "Avatr 12" in names and "12" not in names
    assert numbers_in("The DS 4 and the Avatr 12 start at EUR 39,230.", names) == [(39230.0, 0.5, False)]
    assert numbers_in("12 rivals", names) == [(12.0, 0.5, False)]          # a bare number is still data


def test_source_coverage_gap_versus_other_segment(sandbox):
    """A rival the main table cannot contain (no row there, no other segment label) ranks with the table by units;
    one that another source files under a different segment stays behind the table."""
    page, rows, _ = sandbox
    page("s0000000001", "Table T 2025: BMW 7,000 units; Rival A 9,000 units; Rival B 3,000 units.", "main.example")
    page("s0000000002", "Imports 2025: Import C 8,000 units. Mid-large 2025: Other D 20,000 units.", "other.example")
    mk = lambda mid, brand: {"table": "model", "model_id": mid, "brand": brand, "model": mid, "segment": "executive",
                             "body": "saloon"}
    sale = lambda mid, u, sid, ev, lb: {"table": "sales", "model_id": mid, "market": "CN", "region": "China",
                                        "year": 2025, "units": u, "basis": "retail", "tier": "press",
                                        "source_id": sid, "evidence": ev, "segment_label": lb}
    rows("cn.jsonl", [mk("bmw-5-series", "BMW"), mk("rival-a", "Audi"), mk("rival-b", "Volvo"),
                      mk("import-c", "Lexus"), mk("other-d", "Cadillac"),
                      sale("bmw-5-series", 7000, "s0000000001", "BMW 7,000 units", "T"),
                      sale("rival-a", 9000, "s0000000001", "Rival A 9,000 units", "T"),
                      sale("rival-b", 3000, "s0000000001", "Rival B 3,000 units", "T"),
                      sale("import-c", 8000, "s0000000002", "Import C 8,000 units", None),
                      sale("other-d", 20000, "s0000000002", "Other D 20,000 units", "Mid-large")])
    tables, _ = build.build()
    g = tables["sets"][(tables["sets"]["series"] == "G60") & (tables["sets"]["market"] == "CN")].sort_values("rank")
    assert list(g["model_id"]) == ["rival-a", "import-c", "rival-b", "other-d"]
    assert list(g["basis"]) == ["sales", "sales_other_source", "sales", "sales_other_source"]
