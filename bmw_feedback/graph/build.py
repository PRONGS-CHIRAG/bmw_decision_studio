"""Build the knowledge graph from the processed tables and the trained models' outputs.

    python -m bmw_feedback graph        (also part of `all`)

Every node has an id `<prefix>:<key>` (keys are the source names, joined with '|'),
a `type`, a `label`, its attributes and `prov` - where the value comes from
(processed table, PDF page, Excel file, model artifact, or a derivation).
Edges carry a `rel`. The builder never creates a node implicitly: an edge to a
missing endpoint is an error, and the finished graph is checked against the
row counts of the tables it was built from (see `validate`).

Groups of node types:
    product      Series, Variant, Powertrain
    price        OptionItem, Package, FitmentSummary
    spec         TechSpec
    market/sales Market, SalesVolume, FeedbackCoverage
    feedback     Domain, Feature, Reason, ReasonFamily, Comment
    survey       SurveyAttribute, SurveyScore
    model_output VerdictCell, ModelArtifact, EBMTerm
    caveat       Caveat  (limits of the data, computed from the data itself)
    competitor   CompetitorModel, CompetitorPrice, CompetitorSales, CompetitorSpec, CompetitorEquipment,
                 CompetitorReview, CompetitorRating  (public web data, only when the competitor tables exist)
    web          WebSource (the saved page each competitor value is quoted from)
"""

import json
import math
import time

import networkx as nx
import numpy as np
import pandas as pd

from .. import config, scoring, taxonomy

GRAPH_FILE = config.PROCESSED_DIR / "knowledge_graph.json"
SCHEMA_FILE = config.PROCESSED_DIR / "graph_schema.json"

TYPES = {
    "series": "Series", "variant": "Variant", "market": "Market", "sales": "SalesVolume", "domain": "Domain",
    "feature": "Feature", "reason": "Reason", "family": "ReasonFamily", "comment": "Comment",
    "survey": "SurveyAttribute", "surveyscore": "SurveyScore", "option": "OptionItem", "package": "Package",
    "spec": "TechSpec", "fitment": "FitmentSummary", "verdict": "VerdictCell", "model": "ModelArtifact",
    "ebmterm": "EBMTerm", "caveat": "Caveat", "powertrain": "Powertrain", "coverage": "FeedbackCoverage",
    "competitor": "CompetitorModel", "cprice": "CompetitorPrice", "csales": "CompetitorSales", "cspec": "CompetitorSpec",
    "cequip": "CompetitorEquipment", "creview": "CompetitorReview", "crating": "CompetitorRating", "source": "WebSource",
}
GROUPS = {
    "Series": "product", "Variant": "product", "OptionItem": "price", "Package": "price", "FitmentSummary": "price",
    "TechSpec": "spec", "Market": "market", "SalesVolume": "sales", "Domain": "feedback", "Feature": "feedback",
    "Reason": "feedback", "ReasonFamily": "feedback", "Comment": "feedback", "SurveyAttribute": "survey",
    "SurveyScore": "survey", "VerdictCell": "model_output", "ModelArtifact": "model_output",
    "EBMTerm": "model_output", "Caveat": "caveat", "Powertrain": "product", "FeedbackCoverage": "market",
    "CompetitorModel": "competitor", "CompetitorPrice": "competitor", "CompetitorSales": "competitor",
    "CompetitorSpec": "competitor", "CompetitorEquipment": "competitor", "CompetitorReview": "competitor",
    "CompetitorRating": "competitor", "WebSource": "web",
}
MARKET_NAMES = {"EU": "Europe", "US": "United States", "CN": "China", "RoW": "Rest of world"}
SALES_GROUP_SERIES = {"F70": ["F70"], "G60_G68": ["G60", "G68"], "G70": ["G70"]}
SERIES = config.MODELS                                   # F70, G60, G70 (sold, with price lists)
POWERTRAINS = {"ICE": "Combustion (ICE)", "BEV": "Battery electric (BEV)", "PHEV": "Plug-in hybrid (PHEV)"}
SURVEY_ONLY_SERIES = ["G68"]                              # 5 Series long wheelbase: CN customer study only
OVERALL_ATTRIBUTE = "Overall product satisfaction"        # excluded from survey ranks, as in decision.py
VERDICT_COLS = ["verdict", "confidence", "n_comments", "n_units", "obs_negative", "exp_negative", "index_negative",
                "ci_low_negative", "ci_high_negative", "obs_positive", "exp_positive", "index_positive",
                "ci_low_positive", "ci_high_positive", "obs_request", "exp_request", "index_request",
                "ci_low_request", "ci_high_request", "requested", "n_defect", "n_difficult_to_use"]
P = config.PROCESSED_DIR
R = config.REPORTS_DIR
# Processed outputs deliberately left out, with the reason (shown in the graph meta and the schema view)
NOT_IN_GRAPH = [
    {"source": "data/processed/dashboard/*.json", "why": "re-exports of the scorecards that are already nodes"},
    {"source": "reports/figure_stats.json", "why": "rendering statistics of the report figures"},
    {"source": "models/*.joblib weights, models/feature_reranker.json car_prior",
     "why": "model internals; the graph holds each model's metrics, terms and predictions instead"},
    {"source": "reports/data_quality.json source_baselines_*",
     "why": "channel baselines used inside scoring.score; their effect is in every VerdictCell"},
]


def nid(prefix: str, *parts) -> str:
    return f"{prefix}:" + "|".join(str(p) for p in parts)


def _clean(v):
    """JSON-safe scalar: numpy -> python, NaN / inf -> None."""
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    return v


def prov(kind: str, ref: str, key: str | None = None, page=None) -> dict:
    """kind: table | pdf | xlsx | model | derived | config | web."""
    return {"kind": kind, "ref": ref, "key": key, "page": None if page is None or pd.isna(page) else int(page)}


class GraphBuilder:
    def __init__(self):
        self.g = nx.MultiDiGraph()

    def node(self, prefix: str, parts, label: str, provenance: dict, **attrs) -> str:
        node_id = nid(prefix, *parts)
        if node_id in self.g:
            raise ValueError(f"duplicate node id {node_id!r}")
        reserved = {"type", "group", "label", "prov"} & set(attrs)
        if reserved:
            raise ValueError(f"node {node_id!r}: attribute names {sorted(reserved)} are reserved")
        t = TYPES[prefix]
        self.g.add_node(node_id, type=t, group=GROUPS[t], label=str(label), prov=provenance,
                        **{k: _clean(v) for k, v in attrs.items()})
        return node_id

    def edge(self, u: str, v: str, rel: str, **attrs) -> None:
        for end in (u, v):
            if end not in self.g:
                raise KeyError(f"edge {rel} {u!r} -> {v!r}: endpoint {end!r} does not exist")
        self.g.add_edge(u, v, rel=rel, **{k: _clean(x) for k, x in attrs.items()})


# ---------------------------------------------------------------------- inputs
def load_inputs() -> dict:
    """All tables the graph is built from (written by `build` and `train`)."""
    t = {
        "labels": pd.read_csv(P / "labels.csv"),
        "comments": pd.read_csv(P / "comments.csv", keep_default_na=False, na_values=[""]),
        "feature_scorecard": pd.read_csv(R / "feature_scorecard.csv"),
        "domain_scorecard": pd.read_csv(R / "domain_scorecard.csv"),
        "feature_by_model": pd.read_csv(P / "feature_by_model_scorecard.csv"),
        "survey_cn_eu": pd.read_csv(P / "survey_cn_eu.csv"),
        "survey_us": pd.read_csv(P / "survey_us_summary.csv"),
        "sales": pd.read_csv(P / "sales.csv"),
        "unlabeled": pd.read_csv(P / "unlabeled_predictions.csv"),
        "classifier_metrics": json.loads((R / "classifier_metrics.json").read_text()),
        "ablation": json.loads((R / "model_ablation.json").read_text()),
        "data_quality": json.loads((R / "data_quality.json").read_text()),
        "domain_by_model": pd.read_csv(R / "domain_by_model_scorecard.csv"),
        "representativeness": pd.read_csv(R / "market_representativeness.csv"),
        "survey_us_points": pd.read_csv(P / "survey_us.csv"),
    }
    for name in ("variants", "option_items", "fitment", "packages", "technical", "price_specs", "feature_option_links",
                 "feature_specs", "feature_fitment", "feature_fitment_summary", "feature_fitment_by_engine"):
        t[name] = pd.read_csv(P / f"catalog_{name}.csv")
    t["comments"]["text"] = t["comments"]["text"].fillna("")
    from ..competitors.build import load_tables
    t["competitors"] = load_tables()             # None until `competitors build` has run
    return t


# ---------------------------------------------------------------------- build
def build_graph(t: dict | None = None) -> tuple[nx.MultiDiGraph, dict]:
    t = t or load_inputs()
    b = GraphBuilder()
    _entities(b, t)
    _feedback(b, t)
    _surveys(b, t)
    _sales(b, t)
    _catalog(b, t)
    _model_outputs(b, t)
    _caveats(b, t)
    if t.get("competitors") is not None:
        _competitors(b, t["competitors"])
    checks = validate(b.g, t)
    meta = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "checks": checks, "not_in_graph": NOT_IN_GRAPH,
            **schema_of(b.g)}
    return b.g, meta


def _entities(b: GraphBuilder, t: dict) -> None:
    for s in SERIES:
        b.node("series", [s], config.MODEL_NAMES[s], prov("config", "bmw_feedback/config.py", "MODEL_NAMES"),
               code=s, sold=True, has_price_list=True)
    for s in SURVEY_ONLY_SERIES:
        b.node("series", [s], config.MODEL_NAMES[s], prov("config", "bmw_feedback/config.py", "MODEL_NAMES"),
               code=s, sold=False, has_price_list=False, survey_only=True)
    b.edge(nid("series", "G68"), nid("series", "G60"), "LONG_WHEELBASE_OF")
    for m, name in MARKET_NAMES.items():
        b.node("market", [m], name, prov("config", "bmw_feedback/decision.py", "MARKETS"), code=m)
    for e in POWERTRAINS:
        b.node("powertrain", [e], POWERTRAINS[e], prov("config", "bmw_feedback/config.py", "ENGINE_NAMES"), code=e)
    for d in taxonomy.DOMAINS:
        b.node("domain", [d], d, prov("config", "bmw_feedback/taxonomy.py", "DOMAIN_FEATURES"),
               short=taxonomy.DOMAIN_SHORT.get(d))


def _feedback(b: GraphBuilder, t: dict) -> None:
    fs = t["feature_scorecard"]
    for r in fs.itertuples():
        b.node("feature", [r.feature], r.feature, prov("table", "reports/feature_scorecard.csv", r.feature),
               domain=r.domain, umbrella=bool(r.is_umbrella))
        b.edge(nid("feature", r.feature), nid("domain", r.domain), "IN_DOMAIN")

    lab = t["labels"]
    flab = lab[lab["is_feature_label"]]
    for fam in sorted(flab["reason_family"].dropna().unique()):
        b.node("family", [fam], fam, prov("config", "bmw_feedback/taxonomy.py", "REASON_FAMILIES"))
    fam_of = flab.dropna(subset=["reason"]).drop_duplicates("reason").set_index("reason")["reason_family"]
    for reason, fam in fam_of.items():
        b.node("reason", [reason], reason, prov("table", "data/processed/labels.csv", "reason"),
               family=fam, polarity=taxonomy.reason_polarity(reason))
        if isinstance(fam, str):
            b.edge(nid("reason", reason), nid("family", fam), "IN_FAMILY")

    com = t["comments"]
    for r in com.itertuples():
        b.node("comment", [r.comment_id], r.comment_id,
               prov("xlsx", f"{r.model}_feedback_hackathon.xlsx", r.comment_id),
               source=r.source, country=r.country, market=r.market, model=r.model, engine=r.engine,
               label_status=r.label_status, text=r.text, n_words=r.n_words)
        if isinstance(r.model, str) and r.model in SERIES:
            b.edge(nid("comment", r.comment_id), nid("series", r.model), "ABOUT")
        if isinstance(r.market, str) and r.market in MARKET_NAMES:
            b.edge(nid("comment", r.comment_id), nid("market", r.market), "FROM_MARKET")
        if isinstance(r.engine, str) and r.engine in POWERTRAINS:
            b.edge(nid("comment", r.comment_id), nid("powertrain", r.engine), "ON_POWERTRAIN")

    for r in flab.itertuples():
        b.edge(nid("comment", r.comment_id), nid("feature", r.feature), "MENTIONS", sentiment=r.sentiment,
               feedback_type=r.feedback_type, reason=r.reason, reason_family=r.reason_family)

    units = flab.dropna(subset=["reason"]).drop_duplicates(["comment_id", "feature", "sentiment", "reason"])
    agg = units.groupby(["feature", "reason", "sentiment"])["comment_id"].nunique().reset_index(name="n_comments")
    for r in agg.itertuples():
        b.edge(nid("feature", r.feature), nid("reason", r.reason), "HAS_REASON", sentiment=r.sentiment,
               n_comments=r.n_comments)

    for r in t["unlabeled"].itertuples():
        b.edge(nid("comment", r.comment_id), nid("feature", r.pred_top_feature), "PREDICTED_AS",
               p=r.pred_top_feature_p, model=nid("model", "feature_classifier"))


def _surveys(b: GraphBuilder, t: dict) -> None:
    cn_eu, us = t["survey_cn_eu"], t["survey_us"]
    for a in sorted(cn_eu["attribute"].unique()):
        b.node("survey", ["CN_EU", a], a, prov("xlsx", "F70_G60_G68_G70_customer_studies.xlsx", "CN_EU_2025"),
               study="CN_EU_2025", scale="mean 0-10")
    for a in sorted(us["attribute"].unique()):
        b.node("survey", ["US", a], a, prov("xlsx", "F70_G60_G68_G70_customer_studies.xlsx", "US_2025"),
               study="US_2025", scale="top-2 box share")
    ranked = cn_eu[cn_eu["attribute"] != OVERALL_ATTRIBUTE]
    for (market, model), g in cn_eu.groupby(["market", "model"]):
        rg = ranked[(ranked["market"] == market) & (ranked["model"] == model)]
        ranks = rg.set_index("attribute")["mean"].rank(ascending=False, method="min")
        avg = float(rg["mean"].mean())
        for r in g.itertuples():
            sid = b.node("surveyscore", [market, model, r.attribute], f"{r.attribute} ({market} {model})",
                         prov("table", "data/processed/survey_cn_eu.csv", f"{market}|{model}|{r.attribute}"),
                         study="CN_EU_2025", market=market, model=model, attribute=r.attribute, mean=r.mean,
                         rank=None if r.attribute == OVERALL_ATTRIBUTE else int(ranks[r.attribute]),
                         of=int(len(rg)), series_mean=avg)
            b.edge(sid, nid("survey", "CN_EU", r.attribute), "SCORES_ATTRIBUTE")
            b.edge(sid, nid("series", model), "FOR_SERIES")
            b.edge(sid, nid("market", market), "IN_MARKET")
    points = t["survey_us_points"].sort_values("scale_rank")
    dist = {k: [{"scale_point": r.scale_point, "scale_rank": int(r.scale_rank), "share": r.share} for r in g.itertuples()]
            for k, g in points.groupby(["attribute", "model"])}
    for model, g in us.groupby("model"):
        ranks = g.set_index("attribute")["top2_box"].rank(ascending=False, method="min")
        avg = float(g["top2_box"].mean())
        for r in g.itertuples():
            sid = b.node("surveyscore", ["US", model, r.attribute], f"{r.attribute} (US {model})",
                         prov("table", "data/processed/survey_us_summary.csv", f"US|{model}|{r.attribute}"),
                         study="US_2025", market="US", model=model, attribute=r.attribute, top2_box=r.top2_box,
                         bottom3_box=r.bottom3_box, mean_score=r.mean_score, rank=int(ranks[r.attribute]),
                         of=int(len(g)), series_top2_mean=avg, distribution=dist.get((r.attribute, model), []),
                         distribution_source="data/processed/survey_us.csv")
            b.edge(sid, nid("survey", "US", r.attribute), "SCORES_ATTRIBUTE")
            b.edge(sid, nid("series", model), "FOR_SERIES")
            b.edge(sid, nid("market", "US"), "IN_MARKET")
    for study, mapping in (("US", taxonomy.US_SURVEY_TO_FEATURES), ("CN_EU", taxonomy.CN_EU_SURVEY_TO_FEATURES)):
        for attr, feats in mapping.items():
            for f in feats:
                b.edge(nid("survey", study, attr), nid("feature", f), "MEASURES",
                       basis="hand-curated map in taxonomy.py")


def _sales(b: GraphBuilder, t: dict) -> None:
    for r in t["sales"].itertuples():
        sid = b.node("sales", [r.model_group, r.market_code, r.year],
                     f"{r.model_group} {r.market_code} {r.year}: {int(r.volume):,} units",
                     prov("xlsx", "sales_volumes.xlsx", f"{r.model_group} / {r.market} / {r.year}"),
                     model_group=r.model_group, market=r.market_code, year=int(r.year), volume=int(r.volume),
                     forecast=int(r.year) > 2025)
        for s in SALES_GROUP_SERIES[r.model_group]:
            b.edge(nid("series", s), sid, "HAS_SALES")
        b.edge(sid, nid("market", r.market_code), "IN_MARKET")
    for r in t["representativeness"].itertuples():
        cid = b.node("coverage", [r.model, r.market], f"{r.model} {r.market}: {r.feedback_share:.0%} of feedback, "
                     f"{r.sales_share:.0%} of sales", prov("table", "reports/market_representativeness.csv",
                                                           f"{r.model}|{r.market}"),
                     model=r.model, market=r.market, comments=r.comments, feedback_share=r.feedback_share,
                     volume=r.volume, sales_share=r.sales_share, weight=r.weight)
        b.edge(cid, nid("series", r.model), "FOR_SERIES")
        b.edge(cid, nid("market", r.market), "IN_MARKET")


def _catalog(b: GraphBuilder, t: dict) -> None:
    for r in t["variants"].itertuples():
        vid = b.node("variant", [r.model, r.variant], f"{r.model} {r.variant}",
                     prov("pdf", f"{r.model}_OptionList.PDF", r.variant, r.page),
                     model=r.model, variant=r.variant, powertrain=r.powertrain, engine=r.engine,
                     transmission=r.transmission, power_kw=r.power_kw, power_ps=r.power_ps,
                     base_price_eur=r.base_price_eur, base_price_net_eur=r.base_price_net_eur)
        b.edge(vid, nid("series", r.model), "VARIANT_OF")
        b.edge(vid, nid("powertrain", r.engine), "HAS_POWERTRAIN")

    for r in t["option_items"].itertuples():
        oid = b.node("option", [r.item_id], r.name, prov("pdf", f"{r.model}_OptionList.PDF", r.item_id, r.page),
                     model=r.model, page=r.page, page_type=r.page_type, section=r.section, name=r.name,
                     sa_code=r.sa_code, description=r.description, contents=r.contents, conditions=r.conditions)
        b.edge(oid, nid("series", r.model), "LISTED_FOR")
    for r in t["fitment"].itertuples():
        b.edge(nid("option", r.item_id), nid("variant", r.model, r.variant), "FITTED_ON", status=r.status,
               price_eur=r.price_eur, price_net_eur=r.price_net_eur, price_text=r.price_text,
               price_condition=r.price_condition, page=r.page)

    items = t["option_items"].dropna(subset=["sa_code"])
    sa_index = {(m, sa): i for m, sa, i in zip(items["model"], items["sa_code"], items["item_id"])}
    for (model, package), g in t["packages"].groupby(["model", "package"], sort=False):
        head = g[g["price_text"].notna()]
        head = head.iloc[0] if len(head) else g.iloc[0]
        pid = b.node("package", [model, package], package,
                     prov("pdf", f"{model}_OptionList.PDF", package, head["page"]),
                     model=model, sa_code=head["sa_code"], price_text=head["price_text"],
                     members=[n for n in g["name"].tolist() if n != package])
        b.edge(pid, nid("series", model), "FOR_SERIES")
        for r in g.itertuples():
            item = sa_index.get((model, r.sa_code)) if isinstance(r.sa_code, str) else None
            if item and r.name != package:
                b.edge(pid, nid("option", item), "INCLUDES", sa_code=r.sa_code)

    tech = t["technical"]
    spec_ids = {}
    for r in tech.itertuples():
        sid = b.node("spec", [r.model, r.variant, r.page, r.block, r.group, r.attribute],
                     f"{r.attribute}: {r.value}", prov("pdf", f"{r.model}_OptionList.PDF", r.attribute, r.page),
                     model=r.model, variant=r.variant, attribute=r.attribute, value=r.value, block=r.block,
                     table_group=r.group, value_min=r.value_min, value_max=r.value_max)
        b.edge(sid, nid("variant", r.model, r.variant), "SPEC_OF")
        spec_ids.setdefault((r.model, r.variant, r.attribute, r.page), []).append(sid)
    for r in t["feature_specs"].itertuples():
        for sid in spec_ids[(r.model, r.variant, r.attribute, r.page)]:
            b.edge(nid("feature", r.feature), sid, "HAS_SPEC")
    for r in t["price_specs"].itertuples():
        group = r.group if isinstance(r.group, str) else ""
        sid = b.node("spec", [r.model, r.variant, r.page, r.block, group, r.attribute], f"{r.attribute}: {r.value}",
                     prov("pdf", f"{r.model}_OptionList.PDF", r.attribute, r.page), model=r.model, variant=r.variant,
                     attribute=r.attribute, value=r.value, block=r.block, table_group=group or None, table=r.table)
        b.edge(sid, nid("variant", r.model, r.variant), "SPEC_OF")

    for r in t["feature_option_links"].itertuples():
        b.edge(nid("feature", r.feature), nid("option", r.item_id), "LINKED_TO", matched_keyword=r.matched_keyword,
               matched_in=r.matched_in, matched_text=r.matched_text, page=r.page)

    for r in t["feature_fitment_summary"].itertuples():
        fid = b.node("fitment", [r.feature, r.model], f"{r.feature} on {r.model}: {r.tier}",
                     prov("derived", "data/processed/catalog_feature_fitment_summary.csv", f"{r.feature}|{r.model}"),
                     feature=r.feature, model=r.model, tier=r.tier, n_variants=r.n_variants,
                     n_standard=r.n_standard, n_optional=r.n_optional, price_item=r.price_item,
                     price_sa_code=r.price_sa_code, price_via_package=r.price_via_package,
                     price_min_eur=r.price_min_eur, price_max_eur=r.price_max_eur,
                     price_pct_of_base=r.price_pct_of_base, share_standard=r.share_standard)
        b.edge(fid, nid("feature", r.feature), "FITMENT_OF")
        b.edge(fid, nid("series", r.model), "ON_SERIES")
    for r in t["feature_fitment_by_engine"].itertuples():
        fid = b.node("fitment", [r.feature, r.model, r.engine], f"{r.feature} on {r.model} {r.engine}: {r.tier}",
                     prov("derived", "data/processed/catalog_feature_fitment_by_engine.csv",
                          f"{r.feature}|{r.model}|{r.engine}"),
                     scope="series-powertrain", feature=r.feature, model=r.model, engine=r.engine, tier=r.tier,
                     n_variants=r.n_variants, n_standard=r.n_standard, n_optional=r.n_optional,
                     price_item=r.price_item, price_min_eur=r.price_min_eur, price_max_eur=r.price_max_eur,
                     price_pct_of_base=r.price_pct_of_base, share_standard=r.share_standard)
        b.edge(fid, nid("feature", r.feature), "FITMENT_OF")
        b.edge(fid, nid("series", r.model), "ON_SERIES")
        b.edge(fid, nid("powertrain", r.engine), "ON_POWERTRAIN")
    for r in t["feature_fitment"].itertuples():
        b.edge(nid("feature", r.feature), nid("variant", r.model, r.variant), "FITMENT_ON", status=r.status,
               price_min_eur=r.price_min_eur, price_item=r.price_item, price_sa_code=r.price_sa_code,
               price_page=r.price_page, via_package=r.via_package, standard_item=r.standard_item,
               standard_page=r.standard_page, base_price_eur=r.base_price_eur)


def _verdict_attrs(row) -> dict:
    return {c: row[c] for c in VERDICT_COLS if c in row.index}


def _model_outputs(b: GraphBuilder, t: dict) -> None:
    for _, r in t["feature_scorecard"].iterrows():
        vid = b.node("verdict", ["feature", r["feature"]], f"{r['feature']}: {r['verdict']}",
                     prov("table", "reports/feature_scorecard.csv", r["feature"]),
                     scope="feature", feature=r["feature"], bad_kind=scoring.bad_kind(r), **_verdict_attrs(r))
        b.edge(vid, nid("feature", r["feature"]), "SCORES")
    for _, r in t["domain_scorecard"].iterrows():
        vid = b.node("verdict", ["domain", r["domain"]], f"{r['domain']}: {r['verdict']}",
                     prov("table", "reports/domain_scorecard.csv", r["domain"]),
                     scope="domain", domain=r["domain"], **_verdict_attrs(r))
        b.edge(vid, nid("domain", r["domain"]), "SCORES")
    for _, r in t["feature_by_model"].iterrows():
        vid = b.node("verdict", ["feature-series", r["feature"], r["model"]],
                     f"{r['feature']} on {r['model']}: {r['verdict']}",
                     prov("table", "data/processed/feature_by_model_scorecard.csv", f"{r['feature']}|{r['model']}"),
                     scope="feature-series", feature=r["feature"], model=r["model"], **_verdict_attrs(r))
        b.edge(vid, nid("feature", r["feature"]), "SCORES")
        b.edge(vid, nid("series", r["model"]), "SCORES")
    for _, r in t["domain_by_model"].iterrows():
        vid = b.node("verdict", ["domain-series", r["domain"], r["model"]], f"{r['domain']} on {r['model']}: {r['verdict']}",
                     prov("table", "reports/domain_by_model_scorecard.csv", f"{r['domain']}|{r['model']}"),
                     scope="domain-series", domain=r["domain"], model=r["model"], **_verdict_attrs(r))
        b.edge(vid, nid("domain", r["domain"]), "SCORES")
        b.edge(vid, nid("series", r["model"]), "SCORES")
    for _, r in scoring.score(t["labels"], group_keys=("feature", "engine")).iterrows():
        vid = b.node("verdict", ["feature-powertrain", r["feature"], r["engine"]],
                     f"{r['feature']} on {r['engine']}: {r['verdict']}",
                     prov("derived", "scoring.score(labels, group_keys=(feature, engine))", f"{r['feature']}|{r['engine']}"),
                     scope="feature-powertrain", feature=r["feature"], engine=r["engine"], **_verdict_attrs(r))
        b.edge(vid, nid("feature", r["feature"]), "SCORES")
        b.edge(vid, nid("powertrain", r["engine"]), "SCORES")
    cells = scoring.score(t["labels"], group_keys=("feature", "model", "market"))
    for _, r in cells.iterrows():
        vid = b.node("verdict", ["feature-series-market", r["feature"], r["model"], r["market"]],
                     f"{r['feature']} on {r['model']} in {r['market']}: {r['verdict']}",
                     prov("derived", "scoring.score(labels, group_keys=(feature, model, market))",
                          f"{r['feature']}|{r['model']}|{r['market']}"),
                     scope="feature-series-market", feature=r["feature"], model=r["model"], market=r["market"],
                     **_verdict_attrs(r))
        b.edge(vid, nid("feature", r["feature"]), "SCORES")
        b.edge(vid, nid("series", r["model"]), "SCORES")
        b.edge(vid, nid("market", r["market"]), "SCORES")

    cm = t["classifier_metrics"]
    names = {"feedback_type": "Feedback-type classifier", "domain": "Domain classifier",
             "feature": "Feature classifier"}
    for task, m in cm["tasks"].items():
        b.node("model", [f"{task}_classifier"], names.get(task, task),
               prov("model", f"models/{task}.joblib", "reports/classifier_metrics.json"),
               method="TF-IDF + one-vs-rest logistic regression, 5-fold CV",
               n_training_comments=cm.get("n_training_comments"),
               per_label_f1=m.get("per_label_f1"), cross_source=m.get("cross_source"),
               **{k: m.get(k) for k in ("micro_f1", "macro_f1", "top1_hit", "top3_hit", "n_comments", "n_labels",
                                       "majority_baseline_micro_f1")})
    e = t["ablation"]["complaint_risk_ebm"]
    ctx_only = e["all_features"]["variants"]["context_only"]
    b.node("model", ["complaint_ebm"], "Complaint model (explainable boosting machine)",
           prov("model", "models/complaint_risk.joblib", "reports/model_ablation.json"),
           method="EBM on comment context, feature-grouped 5-fold CV", inputs=e["production_inputs"],
           auc_mean=ctx_only["auc_mean"], auc_sd=ctx_only["auc_sd"], n_units=e["all_features"]["n_units"],
           complaint_rate=e["all_features"]["complaint_rate"], pdf_auc_gain_mean=e["all_features"]["pdf_auc_gain_mean"])
    fr = t["ablation"]["feature_classifier_fitment"]
    b.node("model", ["fitment_reranker"], "Price-list fitment re-ranker",
           prov("model", "models/feature_reranker.json", "reports/model_ablation.json"),
           method="re-ranks feature-classifier candidates by the feature's fitment on the comment's car",
           fitment_gain_top1_linked=fr["fitment_gain_top1_linked"], mcnemar_fixes=fr["mcnemar_linked"]["fitment_fixes"],
           mcnemar_breaks=fr["mcnemar_linked"]["fitment_breaks"], mcnemar_p=fr["mcnemar_linked"]["p_value"])
    b.edge(nid("model", "fitment_reranker"), nid("model", "feature_classifier"), "RERANKS")
    pv = t["ablation"]["poor_value_check"]
    b.node("model", ["poor_value_check"], "Poor-value check (price complaints vs fitment tier)",
           prov("model", "reports/model_ablation.json", "poor_value_check"), n_labels=pv["n_labels"],
           by_sentiment=pv["by_sentiment"], by_reason=pv["by_reason"], by_fitment_tier=pv["by_fitment_tier"])
    b.edge(nid("model", "poor_value_check"), nid("model", "complaint_ebm"), "AUDITS")
    q = t["data_quality"]
    oc = {k: v for k, v in q["option_catalog"].items() if not isinstance(v, (list, dict))}
    b.node("model", ["option_catalog_parser"], "Price-list PDF parser (validated on every build)",
           prov("model", "bmw_feedback/option_catalog.py", "reports/data_quality.json#option_catalog"),
           source_price_anomalies=len(q["option_catalog"].get("source_price_anomalies", [])), **oc)
    clean = {k: v for k, v in q.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    b.node("model", ["feedback_cleaning"], "Feedback cleaning (label leakage, templates, duplicates)",
           prov("model", "bmw_feedback/clean.py", "reports/data_quality.json"),
           comments_by_label_status=q.get("comments_by_label_status"), **clean)
    for s in SERIES:
        b.edge(nid("model", "option_catalog_parser"), nid("series", s), "PARSED_PRICE_LIST_OF")
        b.edge(nid("model", "feedback_cleaning"), nid("series", s), "CLEANED_FEEDBACK_OF")

    targets = {"domain": "domain", "market": "market", "model": "series", "engine": "powertrain"}
    for term in e["global_production"]:
        tid = b.node("ebmterm", [term["term"]], f"EBM term: {term['term']}",
                     prov("model", "models/complaint_risk.joblib", "reports/model_ablation.json#global_production"),
                     term=term["term"], importance=term["importance"],
                     shape=[{"bin": s["bin"], "score": s["score"]} for s in term["shape"]])
        b.edge(tid, nid("model", "complaint_ebm"), "TERM_OF")
        prefix = targets.get(term["term"])
        for s in term["shape"] if prefix else []:
            target = nid(prefix, s["bin"])
            if target in b.g:
                b.edge(tid, target, "CONTRIBUTES", bin=s["bin"], score=s["score"])


def _caveats(b: GraphBuilder, t: dict) -> None:
    def cav(key, text, targets, **attrs):
        cid = b.node("caveat", [key], text, prov("derived", "bmw_feedback/graph/build.py", key), text=text, **attrs)
        for target in targets:
            b.edge(cid, target, "QUALIFIES")

    cav("prices-de-only", "Prices and equipment come from the German price lists (July 2026, EUR incl. 19% VAT). "
        "The data has no price list for the United States, China or the rest of the world, and none for other "
        "European countries.", [nid("series", s) for s in SERIES])

    com = t["comments"]
    n_cn = int((com["market"] == "CN").sum())
    if n_cn == 0:
        cav("no-china-feedback", f"No customer comment in the data comes from China (0 of {len(com):,} comments).",
            [nid("market", "CN")], n_comments=0)

    cn = t["survey_cn_eu"][t["survey_cn_eu"]["market"] == "CN"]
    if "G68" in set(cn["model"]) and "G60" not in set(cn["model"]):
        cav("cn-survey-g68", "The China customer study covers the 5 Series long wheelbase (G68), not the G60.",
            [nid("series", "G68"), nid("series", "G60"), nid("market", "CN")])

    covered = t["fitment"].groupby("model")["variant"].nunique()
    listed = t["variants"].groupby("model")["variant"].nunique()
    for s in SERIES:
        a, n = int(covered.get(s, 0)), int(listed.get(s, 0))
        if a < n:
            cav(f"equipment-tables-partial|{s}", f"The {s} equipment tables cover {a} of {n} variants in the "
                "price list; fitment for the other variants is unknown.", [nid("series", s)],
                variants_covered=a, variants_listed=n)

    sources = t["labels"].groupby("model")["source"].unique()
    for s in SERIES:
        if s in sources.index and len(sources[s]) == 1:
            cav(f"single-source|{s}", f"All {s} feedback comes from one channel ({sources[s][0]}).",
                [nid("series", s)], source=sources[s][0])

    gain = t["ablation"]["complaint_risk_ebm"]["all_features"]["pdf_auc_gain_mean"]
    cav("pdf-fitment-no-auc-gain", f"Adding price-list fitment to the complaint model changed held-out AUC by "
        f"{gain:+.4f} (feature-grouped 5-fold CV), so the production complaint model uses comment context only.",
        [nid("model", "complaint_ebm")], auc_gain=gain)

    umbrellas = sorted(f for f in taxonomy.UMBRELLA_FEATURES if nid("feature", f) in b.g)
    cav("umbrella-labels", "Umbrella labels (e.g. 'Exterior design') collect general praise; specific features are "
        "compared only with other specific features.", [nid("feature", f) for f in umbrellas])

    g6068 = [nid("sales", r.model_group, r.market_code, r.year) for r in t["sales"].itertuples()
             if r.model_group == "G60_G68"]
    cav("sales-g60-includes-g68", "5 Series sales volumes include the G68 long wheelbase (sheet G60_G68).", g6068)
    future = [nid("sales", r.model_group, r.market_code, r.year) for r in t["sales"].itertuples() if r.year > 2025]
    cav("sales-forecast", "Volumes after 2025 are planning figures from sales_volumes.xlsx, not actual sales.", future)


def _competitors(b: GraphBuilder, c: dict) -> None:
    """Competitor web data: models, the top-5 sets, and one node per extracted value with its source page."""
    from ..competitors import registry as CR

    def entity(mid):
        return nid("series", CR.SELF_SERIES[mid]) if mid in CR.SELF_SERIES else nid("competitor", mid)

    def src(sid):
        return nid("source", sid)

    for r in c["sources"].itertuples():
        b.node("source", [r.source_id], f"{r.publisher}: {str(r.title or r.url)[:70]}",
               prov("web", r.url, r.retrieved_at), url=r.url, final_url=r.final_url, publisher=r.publisher,
               title=r.title, retrieved_at=r.retrieved_at, kind=r.kind, sha256=r.sha256)
    for r in c["models"].itertuples():
        if r.model_id in CR.SELF_SERIES:
            continue
        b.node("competitor", [r.model_id], r.name, prov("table", "data/processed/competitor_models.csv", r.model_id),
               brand=r.brand, model=r.model, segment=r.segment, body=r.body, generation=r.generation)
    for r in c["sets"].dropna(subset=["model_id"]).itertuples():
        b.edge(nid("series", r.series), entity(r.model_id), "COMPETES_WITH", market=r.market, rank=int(r.rank),
               basis=r.basis, units=r.units, year=r.year, region=r.region, segment_label=r.segment_label)
    for r in c["rivals"].itertuples():
        b.edge(entity(r.model_id), nid("series", r.bmw_series), "NAMED_RIVAL_OF", publisher=r.publisher,
               market=r.market, evidence=r.evidence, source=r.source_id)

    def row_node(prefix, table, r, label, rel, extra):
        attrs = {k: getattr(r, k) for k in extra if hasattr(r, k)}
        n = b.node(prefix, [r.row_id], label, prov("web", f"data/processed/competitor_{table}.csv", r.row_id),
                   model_id=r.model_id, source_id=r.source_id, evidence=getattr(r, "evidence", None), **attrs)
        b.edge(n, entity(r.model_id), rel)
        b.edge(n, src(r.source_id), "FROM_SOURCE")
        market = getattr(r, "market", None)
        if isinstance(market, str) and market in MARKET_NAMES:
            b.edge(n, nid("market", market), "IN_MARKET")
        return n

    for r in c["prices"].itertuples():
        row_node("cprice", "prices", r, f"{r.variant}: {r.currency} {r.amount:,.0f}", "PRICE_OF",
                 ["market", "country", "currency", "variant", "amount", "powertrain", "price_type", "tax_basis",
                  "model_year", "as_of", "power_kw"])
    for r in c["sales"].itertuples():
        row_node("csales", "sales", r, f"{r.region} {r.year}: {int(r.units):,} units", "SALES_OF",
                 ["market", "region", "year", "period", "units", "basis", "tier", "segment_label"])
    for r in c["specs"].itertuples():
        row_node("cspec", "specs", r, f"{r.attribute}: {r.value:g} {r.unit} ({r.variant})", "SPEC_OF",
                 ["variant", "attribute", "value", "unit", "powertrain", "market"])
    for r in c["equipment"].itertuples():
        n = row_node("cequip", "equipment", r, f"{r.item}: {r.status}", "EQUIPMENT_OF",
                     ["country", "item", "status", "price_eur", "item_name", "variant_scope"])
        b.edge(n, nid("feature", r.feature), "FOR_FEATURE", item=r.item)
    for r in c["reviews"].itertuples():
        n = row_node("creview", "reviews", r, f"{r.kind}: {str(r.text)[:60]}", "REVIEW_OF",
                     ["market", "country", "kind", "text", "rating", "rating_scale", "sentiment", "sentiment_basis",
                      "pred_feedback_type", "pred_domain", "pred_domain_p", "topic", "pred_feature", "pred_feature_p"])
        if nid("feature", r.pred_feature) in b.g:
            b.edge(n, nid("feature", r.pred_feature), "CLASSIFIED_AS", p=r.pred_feature_p,
                   model=nid("model", "feature_classifier"))
    for r in c["ratings"].itertuples():
        row_node("crating", "ratings", r, f"{r.rating_kind}: {r.score:g}/{r.scale_max:g}", "RATING_OF",
                 ["market", "country", "rating_kind", "score", "scale_max", "n_reviews", "model_year"])


def _competitor_checks(g: nx.MultiDiGraph, c: dict, types, rels) -> list:
    from ..competitors import registry as CR
    return [
        ("CompetitorModel nodes = rows of competitor_models.csv without the BMW series",
         types.get("CompetitorModel", 0), int((~c["models"]["model_id"].isin(CR.SELF_SERIES)).sum())),
        ("COMPETES_WITH edges = competitor set rows", rels.get("COMPETES_WITH", 0), int(c["sets"]["model_id"].notna().sum())),
        ("CompetitorPrice nodes = rows of competitor_prices.csv", types.get("CompetitorPrice", 0), len(c["prices"])),
        ("CompetitorSales nodes = rows of competitor_sales.csv", types.get("CompetitorSales", 0), len(c["sales"])),
        ("CompetitorSpec nodes = rows of competitor_specs.csv", types.get("CompetitorSpec", 0), len(c["specs"])),
        ("CompetitorEquipment nodes = rows of competitor_equipment.csv", types.get("CompetitorEquipment", 0),
         len(c["equipment"])),
        ("CompetitorReview nodes = rows of competitor_reviews.csv", types.get("CompetitorReview", 0), len(c["reviews"])),
        ("CompetitorRating nodes = rows of competitor_ratings.csv", types.get("CompetitorRating", 0), len(c["ratings"])),
        ("WebSource nodes = rows of competitor_sources.csv", types.get("WebSource", 0), len(c["sources"])),
        ("NAMED_RIVAL_OF edges = rows of competitor_rivals.csv", rels.get("NAMED_RIVAL_OF", 0), len(c["rivals"])),
        ("CLASSIFIED_AS edges = competitor reviews with a predicted feature", rels.get("CLASSIFIED_AS", 0),
         int(c["reviews"]["pred_feature"].map(lambda f: nid("feature", f) in g).sum()) if len(c["reviews"]) else 0),
    ]


# ---------------------------------------------------------------------- validation
def validate(g: nx.MultiDiGraph, t: dict) -> list:
    """Counts in the graph against the tables it was built from. Raises on any mismatch."""
    types = pd.Series([d["type"] for _, d in g.nodes(data=True)]).value_counts()
    rels = pd.Series([d["rel"] for _, _, d in g.edges(data=True)]).value_counts()
    flab = t["labels"][t["labels"]["is_feature_label"]]
    cells = scoring.score(t["labels"], group_keys=("feature", "model", "market"))
    expected = [
        ("Feature nodes = rows of feature_scorecard.csv", types.get("Feature", 0), len(t["feature_scorecard"])),
        ("Feature nodes = distinct feature labels", types.get("Feature", 0), flab["feature"].nunique()),
        ("Domain nodes = taxonomy domains", types.get("Domain", 0), len(taxonomy.DOMAINS)),
        ("Reason nodes = distinct reasons", types.get("Reason", 0), flab["reason"].nunique()),
        ("Comment nodes = rows of comments.csv", types.get("Comment", 0), len(t["comments"])),
        ("MENTIONS edges = feature-label rows", rels.get("MENTIONS", 0), len(flab)),
        ("PREDICTED_AS edges = unlabeled predictions", rels.get("PREDICTED_AS", 0), len(t["unlabeled"])),
        ("Variant nodes = rows of catalog_variants.csv", types.get("Variant", 0), len(t["variants"])),
        ("OptionItem nodes = rows of catalog_option_items.csv", types.get("OptionItem", 0), len(t["option_items"])),
        ("FITTED_ON edges = rows of catalog_fitment.csv", rels.get("FITTED_ON", 0), len(t["fitment"])),
        ("TechSpec nodes = rows of catalog_technical.csv + catalog_price_specs.csv", types.get("TechSpec", 0),
         len(t["technical"]) + len(t["price_specs"])),
        ("LINKED_TO edges = rows of catalog_feature_option_links.csv", rels.get("LINKED_TO", 0),
         len(t["feature_option_links"])),
        ("HAS_SPEC edges = rows of catalog_feature_specs.csv", rels.get("HAS_SPEC", 0), len(t["feature_specs"])),
        ("FitmentSummary nodes = rows of the series and series x powertrain fitment summaries",
         types.get("FitmentSummary", 0), len(t["feature_fitment_summary"]) + len(t["feature_fitment_by_engine"])),
        ("FITMENT_ON edges = rows of catalog_feature_fitment.csv", rels.get("FITMENT_ON", 0), len(t["feature_fitment"])),
        ("FeedbackCoverage nodes = rows of market_representativeness.csv", types.get("FeedbackCoverage", 0),
         len(t["representativeness"])),
        ("US survey distribution points = rows of survey_us.csv",
         sum(len(d.get("distribution") or []) for _, d in g.nodes(data=True) if d["type"] == "SurveyScore"),
         len(t["survey_us_points"])),
        ("ON_POWERTRAIN edges from comments = comments with a powertrain",
         sum(1 for u, _, d in g.edges(data=True) if d["rel"] == "ON_POWERTRAIN" and u.startswith("comment:")),
         int(t["comments"]["engine"].isin(POWERTRAINS).sum())),
        ("SalesVolume nodes = rows of sales.csv", types.get("SalesVolume", 0), len(t["sales"])),
        ("SurveyScore nodes = rows of both survey tables", types.get("SurveyScore", 0),
         len(t["survey_cn_eu"]) + len(t["survey_us"])),
        ("VerdictCell nodes = feature + domain + domain x series + feature x series + feature x powertrain + "
         "feature x series x market rows", types.get("VerdictCell", 0),
         len(t["feature_scorecard"]) + len(t["domain_scorecard"]) + len(t["domain_by_model"]) + len(t["feature_by_model"])
         + len(scoring.score(t["labels"], group_keys=("feature", "engine"))) + len(cells)),
        ("Package nodes = distinct packages", types.get("Package", 0),
         len(t["packages"].drop_duplicates(["model", "package"]))),
    ]
    if t.get("competitors") is not None:
        expected += _competitor_checks(g, t["competitors"], types, rels)
    checks = [{"check": name, "graph": int(a), "source": int(e), "ok": int(a) == int(e)} for name, a, e in expected]
    missing_prov = [n for n, d in g.nodes(data=True) if not d.get("prov") or not d.get("type")]
    checks.append({"check": "Every node has a type and provenance", "graph": len(missing_prov), "source": 0,
                   "ok": not missing_prov})
    failed = [c for c in checks if not c["ok"]]
    if failed:
        raise ValueError("Knowledge graph does not match its source tables: " + json.dumps(failed, indent=1))
    return checks


def schema_of(g: nx.MultiDiGraph) -> dict:
    """Meta-graph: node types with counts and groups, (source type, rel, target type) with counts."""
    types = pd.Series([d["type"] for _, d in g.nodes(data=True)]).value_counts()
    rows = [(g.nodes[u]["type"], d["rel"], g.nodes[v]["type"]) for u, v, d in g.edges(data=True)]
    rel = pd.DataFrame(rows, columns=["source", "rel", "target"]).value_counts().reset_index(name="n")
    return {"n_nodes": g.number_of_nodes(), "n_edges": g.number_of_edges(),
            "node_types": [{"type": k, "group": GROUPS.get(k), "count": int(v)} for k, v in types.items()],
            "edge_types": [{"source": r.source, "rel": r.rel, "target": r.target, "count": int(r.n)}
                           for r in rel.itertuples()]}


def save(g: nx.MultiDiGraph, meta: dict) -> None:
    data = nx.node_link_data(g, edges="edges")
    GRAPH_FILE.write_text(json.dumps({"meta": meta, "graph": data}, default=str))
    SCHEMA_FILE.write_text(json.dumps(meta, indent=1, default=str))


def build_and_save() -> dict:
    g, meta = build_graph()
    save(g, meta)
    return meta
