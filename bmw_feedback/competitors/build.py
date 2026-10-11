"""Validated competitor rows -> processed tables, the top-5 competitor sets and the quality report.

    python -m bmw_feedback competitors build        (also part of `all` when competitor-data/extracted exists)

Writes data/processed/competitor_*.csv and reports/competitor_quality.json. No network: it reads the extracted
rows, the saved source texts (to check every quote) and BMW's own processed price list.

Selection of the five competitors per BMW series x market (deterministic, recorded per row in `basis`):
    1. Models of the series' segment (registry.SERIES_SEGMENT) with a full-year sales figure in that market, from
       the (region, year) that covers the most of them (Europe-wide before Germany, 2025 before 2024); ranked by
       units. A source's own segment table is the evidence of who competes.
    2. If fewer than five, models that publishers name as rivals of that BMW (`rival` rows), from the fallback
       segments only, present in the market (a price or sales row there); ranked by the number of publishers.
    BMW series that are not sold in a market (zero volume in sales_volumes.xlsx) get no set.
"""

import hashlib
import json
import re

import numpy as np
import pandas as pd

from .. import config
from . import records, registry as R
from .snapshot import all_sources

P = config.PROCESSED_DIR
QUALITY_FILE = config.REPORTS_DIR / "competitor_quality.json"
TABLE_FILES = {name: P / f"competitor_{name}.csv" for name in
               ("models", "sets", "sales", "prices", "specs", "equipment", "reviews", "ratings", "rivals", "sources",
                "bmw_prices", "bmw_specs", "bmw_equipment")}

# BMW's own equipment, read from its DE price list: item key -> pattern on price-list item name / description /
# package contents (calibrated on catalog_option_items.csv; see the registry for what each item means)
BMW_ITEM_PATTERNS = {
    "hud": r"Head-Up", "acc": r"Driving Assistant Plus\b", "hands_off": r"Autobahnassistent|Autobahn- & City-Assistent",
    "pano_roof": r"Panorama[- ]?Glasdach", "massage": r"Massagefunktion vorn", "ventilated_seats": r"Sitzbelüftung vorn",
    "heated_wheel": r"Lenkradheizung", "surround_view": r"Surround View", "auto_parking": r"Parking Assistant",
    "wireless_charging": r"Wireless Charging", "premium_audio": r"harman|Bowers", "ambient_light": r"Ambientes? Licht",
    "keyless": r"Komfortzugang", "power_tailgate": r"Heckklappenbetätigung", "soft_close": r"Soft-Close",
    "auto_doors": r"Automatiktür", "rear_entertainment": r"Theatre Screen|Theater Screen", "air_suspension": r"Luftfeder",
    "rear_steering": r"Integral-Aktivlenkung",
    "matrix_lights": r"Adaptiver LED-Scheinwerfer|Kristallscheinwerfer|Laserlicht", "dashcam": r"Drive Recorder",
    "digital_key": r"Digital Key",
}
BMW_SPEC_KEYS = {   # spec attribute -> (technical attribute_key(s), which bound of a range: min | max)
    "torque_nm": (["drehmoment in nm"], "min"),
    "accel_0_100_s": (["beschleunigung 0–100 km / h in s"], "min"),
    "top_speed_kmh": (["höchstgeschwindigkeit in km / h", "höchstgeschwindigkeit elektr. in km / h"], "max"),
    "boot_l": (["gepäckraumvolumen in l"], "min"),
    "range_km_wltp": (["elektrische reichweite, wltp in km"], "max"),
    "battery_kwh_net": (["energieinhalt batterie in kwh, netto"], "min"),
    "dc_charge_kw": (["maximale ladeleistung dc in kw"], "max"),
}
SENTIMENT_OF_KIND = {"expert_pro": "positive", "expert_con": "negative"}
TOPIC_MIN_P = 0.5           # same rule as classifier.predict for domains: a topic needs p >= 0.5
REGION_PREFERENCE = {"EU": ["Europe", "Germany"], "US": ["United States"], "CN": ["China"], "RoW": ["Australia"]}


class CompetitorDataError(ValueError):
    """Extracted rows failed validation; the build writes nothing."""


# ---------------------------------------------------------------------- helpers
def _frame(rows: list[dict], cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame([{c: r.get(c) for c in cols} for r in rows], columns=cols)
    return df


def _with_row_ids(df: pd.DataFrame) -> pd.DataFrame:
    """A stable id per row (hash of its content), used as the knowledge-graph node key."""
    if df.empty:
        return df.assign(row_id=pd.Series(dtype=str))
    cols = [c for c in df.columns if c not in ("publisher", "preferred", "tier_rank")]
    df = df.drop_duplicates(subset=cols).reset_index(drop=True)     # rows equal in every stored field are one row
    ids = [hashlib.sha1(json.dumps([str(x) for x in row], ensure_ascii=False).encode()).hexdigest()[:12]
           for row in df[cols].itertuples(index=False)]
    if len(set(ids)) != len(ids):
        raise CompetitorDataError("two competitor rows hash to the same id")
    return df.assign(row_id=ids)


def display_publisher(meta: dict) -> str:
    """The publisher a reader knows: an archived copy is credited to its original site."""
    from urllib.parse import urlparse
    m = re.match(r"https?://web\.archive\.org/web/[^/]+/(https?://[^\s]+)", meta.get("final_url") or meta.get("url") or "")
    if m:
        host = urlparse(m.group(1)).netloc.lower()
        return f"{host[4:] if host.startswith('www.') else host} (archived copy)"
    return meta["publisher"]


def _publisher(sid: str, metas: dict) -> str | None:
    m = metas.get(sid)
    return display_publisher(m) if m else None


def _region_key(market: str, region: str) -> int:
    prefs = REGION_PREFERENCE.get(market, [])
    low = (region or "").lower()
    for i, p in enumerate(prefs):
        if p.lower() in low:
            return i
    return len(prefs)


def bmw_sold(series: str, market: str) -> bool:
    sales = pd.read_csv(P / "sales.csv")
    group = {"F70": "F70", "G60": "G60_G68", "G70": "G70"}[series]
    s = sales[(sales["model_group"] == group) & (sales["market_code"] == market)]
    return bool(s["volume"].sum() > 0)


# ---------------------------------------------------------------------- BMW side (official data)
def bmw_tables() -> dict[str, pd.DataFrame]:
    """BMW entry prices, specs and equipment from the DE price list already parsed by option_catalog."""
    from .. import option_catalog
    var = pd.read_csv(P / "catalog_variants.csv")
    tech = pd.read_csv(P / "catalog_technical.csv")
    prices = []
    for m, g in var.groupby("model"):
        g = g.sort_values("base_price_eur")
        cheapest = g.iloc[0]
        for engine, ge in g.groupby("engine"):
            r = ge.iloc[0]
            prices.append({"model": m, "variant": r["variant"], "powertrain": r["engine"], "power_kw": r["power_kw"],
                           "amount": r["base_price_eur"], "page": int(r["page"]), "entry": r["variant"] == cheapest["variant"],
                           "ref": f"{m}_OptionList.PDF"})
    specs = []
    for r in var.itertuples():
        specs.append({"model": r.model, "variant": r.variant, "powertrain": r.engine, "attribute": "power_kw",
                      "value": r.power_kw, "page": int(r.page)})
    engines = dict(zip(zip(var["model"], var["variant"]), var["engine"]))
    for attr, (keys, bound) in BMW_SPEC_KEYS.items():
        t = tech[tech["attribute_key"].isin(keys)].copy()
        if attr in ("range_km_wltp", "battery_kwh_net", "dc_charge_kw"):        # electric data: BEVs only
            t = t[[engines.get((m, v)) == "BEV" for m, v in zip(t["model"], t["variant"])]]
        t = t.dropna(subset=["value_min" if bound == "min" else "value_max"])
        t = t.drop_duplicates(["model", "variant"])
        for r in t.itertuples():
            specs.append({"model": r.model, "variant": r.variant, "powertrain": engines.get((r.model, r.variant)),
                          "attribute": attr, "value": float(r.value_min if bound == "min" else r.value_max),
                          "page": int(r.page)})
    cat = {k: pd.read_csv(P / f"catalog_{k}.csv") for k in ("option_items", "fitment", "variants")}
    items = cat["option_items"][cat["option_items"]["page_type"].isin(option_catalog.LINK_PAGE_TYPES)]
    links = []
    for key, pat in BMW_ITEM_PATTERNS.items():
        rx = re.compile(pat, re.I)
        for it in items.itertuples():
            parts = [("name", it.name)]
            parts += [("description", d) for d in str(it.description or "").split(" | ") if d and d != "nan"]
            parts += [("contents", c) for c in str(it.contents or "").split(" | ") if c and c != "nan"]
            hit = next(((where, text) for where, text in parts if rx.search(str(text))), None)
            if hit:
                links.append({"feature": key, "model": it.model, "item_id": it.item_id, "option_name": it.name,
                              "sa_code": it.sa_code, "page": it.page, "page_type": it.page_type,
                              "matched_in": hit[0], "matched_text": hit[1]})
    links = pd.DataFrame(links, columns=["feature", "model", "item_id", "option_name", "sa_code", "page", "page_type",
                                         "matched_in", "matched_text"])
    fv = option_catalog.feature_fitment(links, cat)
    summ = option_catalog.fitment_summary(fv) if len(fv) else pd.DataFrame()
    equip = []
    for key in R.EQUIPMENT_ITEMS:
        for m in config.MODELS:
            s = summ[(summ["feature"] == key) & (summ["model"] == m)] if len(summ) else summ
            lk = links[(links["feature"] == key) & (links["model"] == m)]
            if s is None or s.empty:
                equip.append({"model": m, "item": key, "tier": "not_listed", "n_variants": None, "n_standard": None,
                              "n_optional": None, "price_min_eur": None, "price_item": None, "via_package": None,
                              "items": "", "pages": "", "item_id": None})
                continue
            r = s.iloc[0]
            equip.append({"model": m, "item": key, "tier": r["tier"], "n_variants": int(r["n_variants"]),
                          "n_standard": int(r["n_standard"]), "n_optional": int(r["n_optional"]),
                          "price_min_eur": None if pd.isna(r["price_min_eur"]) else float(r["price_min_eur"]),
                          "price_item": None if pd.isna(r["price_item"]) else r["price_item"],
                          "via_package": None if pd.isna(r["price_via_package"]) else bool(r["price_via_package"]),
                          "items": " | ".join(sorted(set(lk["option_name"]))),
                          "pages": " | ".join(str(int(p)) for p in sorted(set(lk["page"]))),
                          "item_id": _item_id(lk, None if pd.isna(r["price_item"]) else r["price_item"])})
    return {"bmw_prices": pd.DataFrame(prices), "bmw_specs": pd.DataFrame(specs), "bmw_equipment": pd.DataFrame(equip)}


def _item_id(links: pd.DataFrame, price_item: str | None) -> str | None:
    """The price-list item behind a BMW equipment status: the priced item if any, else the first linked one."""
    if links.empty:
        return None
    hit = links[links["option_name"] == price_item] if price_item else links.iloc[0:0]
    return str((hit if len(hit) else links).sort_values("item_id").iloc[0]["item_id"])


# ---------------------------------------------------------------------- selection
def effective_segment(segment: str, brand: str) -> str:
    """Premium segments hold premium brands only; other brands move to the mainstream segment of their size."""
    if segment in R.MAINSTREAM_OF and str(brand).lower() not in R.PREMIUM_BRANDS:
        return R.MAINSTREAM_OF[segment]
    return segment


def select_sets(models: pd.DataFrame, sales: pd.DataFrame, rivals: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    own = set(models.loc[models["brand"].str.lower().isin(R.BMW_GROUP_BRANDS), "model_id"]) | set(R.SELF_SERIES)
    seg = {m: s for m, s in zip(models["model_id"], models["competitive_segment"]) if m not in own}
    rows = []
    fy = sales[sales["period"] == "FY"] if len(sales) else sales       # all sources; deduplicated after ranking
    for series in config.MODELS:
        segment = R.SERIES_SEGMENT[series]
        for market in R.MARKETS:
            base = {"series": series, "market": market}
            if not bmw_sold(series, market):
                rows.append({**base, "rank": None, "model_id": None, "basis": "not_sold",
                             "note": f"BMW sells no {series} in {R.MARKET_NAMES[market]} (sales_volumes.xlsx)"})
                continue
            cand = fy[(fy["market"] == market) & (fy["model_id"].map(seg) == segment)
                      & ~fy["model_id"].isin(R.SELF_SERIES) & (fy["units"] > 0)] if len(fy) else fy
            chosen = []
            if len(cand):
                # 1. the (region, year) covering the most segment models (Europe-wide before Germany, newest first)
                cand = cand.assign(rk=[_region_key(market, r) for r in cand["region"]])
                cover = cand.groupby(["region", "year", "rk"])["model_id"].nunique().reset_index(name="n")
                cover = cover.sort_values(["n", "rk", "year"], ascending=[False, True, False])
                region, year = cover.iloc[0]["region"], int(cover.iloc[0]["year"])
                pool = cand[(cand["region"] == region) & (cand["year"] == year)].copy()
                pool["label"] = pool["segment_label"].fillna("")
                # 2. the publisher and segment table of the BMW itself in that region and year, if it has a row:
                #    models in the BMW's own segment table first, then that publisher's other rows, then others.
                #    One publisher counts on one basis, so units from different counting bases are not mixed silently.
                own = fy[(fy["model_id"] == R.BMW_SELF[series]) & (fy["market"] == market) & (fy["region"] == region)
                         & (fy["year"] == year)] if len(fy) else fy
                options = [(p, str(lb) if isinstance(lb, str) else "") for p, lb in zip(own["publisher"], own["segment_label"])]
                options = [o for o in dict.fromkeys(options)]
                if options:
                    pub, label = max(options, key=lambda o: ((pool["publisher"] == o[0]) & (pool["label"] == o[1])).sum())
                else:
                    pub, label = pool.groupby("publisher")["model_id"].nunique().sort_values(ascending=False).index[0], None
                same_pub = pool["publisher"] == pub
                in_table = same_pub & ((pool["label"] == label) if label is not None else True)
                # a model the main publisher has no row for at all (e.g. an import in a table of China-built cars) is a
                # gap in that source, not a smaller model: it is ranked by units together with the BMW's table
                # ... unless a source files it under a different segment label, which means it is not in the segment
                other_label = {m for m, lb in zip(pool["model_id"], pool["label"]) if lb and lb != (label or "")}
                gap = (~same_pub & ~pool["model_id"].isin(set(pool.loc[same_pub, "model_id"]))
                       & ~pool["model_id"].isin(other_label))
                bmw_row = own[(own["publisher"] == pub) & (own["segment_label"].fillna("") == (label or ""))]
                floor = R.MIN_SHARE_OF_BMW * float(bmw_row["units"].max()) if len(bmw_row) else 0.0
                pool = pool.assign(material=pool["units"] >= floor)
                ranked = []
                first = pool[in_table | gap].assign(sel_basis=["sales" if t else "sales_other_source"
                                                           for t in in_table[in_table | gap]])
                for frame in (first, pool[same_pub & ~in_table].assign(sel_basis="sales_other_segment"),
                              pool[~same_pub & ~gap].assign(sel_basis="sales_other_source")):
                    part = frame.sort_values(["units", "tier_rank"], ascending=[False, True])
                    ranked += [(r, r.sel_basis) for r in part.itertuples()]
                seen = set()
                for r, basis in ranked:
                    if r.model_id in seen or len(chosen) >= R.N_COMPETITORS or not r.material:
                        continue
                    seen.add(r.model_id)
                    note = {"sales": None,
                            "sales_other_segment": f"ranked after the BMW's segment table ('{label}') of {pub}: this "
                                                   f"model is in its table '{r.segment_label}'",
                            "sales_other_source": (f"not in {pub}'s tables (which may not cover it, e.g. imports); its "
                                                   f"figure comes from {r.publisher} ({r.basis.replace('_', ' ')})")
                                                  if gap.get(r.Index, False) else
                                                  f"ranked after the models of {pub}: its figure comes from "
                                                  f"{r.publisher}, another source for the same region and year"}[basis]
                    chosen.append({**base, "model_id": r.model_id, "basis": basis, "units": int(r.units), "year": year,
                                   "region": region, "sales_source_id": r.source_id, "segment_label": r.segment_label,
                                   "n_rival_mentions": None, "note": note})
            if len(chosen) < R.N_COMPETITORS and len(rivals):
                present = set(prices.loc[prices["market"] == market, "model_id"]) | set(
                    sales.loc[sales["market"] == market, "model_id"])
                allowed = set(R.FALLBACK_SEGMENTS[series])
                rv = rivals[(rivals["bmw_series"] == series) & (rivals["market"].isna() | (rivals["market"] == market))]
                rv = rv[rv["model_id"].map(seg).isin(allowed) & rv["model_id"].isin(present)
                        & ~rv["model_id"].isin([c["model_id"] for c in chosen]) & ~rv["model_id"].isin(R.SELF_SERIES)]
                ranked = (rv.groupby("model_id")["publisher"].nunique().reset_index(name="n")
                          .assign(seg_order=lambda d: d["model_id"].map(lambda m: R.FALLBACK_SEGMENTS[series].index(seg[m])))
                          .sort_values(["n", "seg_order", "model_id"], ascending=[False, True, True]))
                for r in ranked.itertuples():
                    if len(chosen) >= R.N_COMPETITORS:
                        break
                    chosen.append({**base, "model_id": r.model_id, "basis": "rival_mentions", "units": None,
                                   "year": None, "region": None, "sales_source_id": None, "segment_label": None,
                                   "n_rival_mentions": int(r.n),
                                   "note": f"named as a {series} rival by {int(r.n)} publisher(s); no same-segment "
                                           "sales figure for this market"})
            if not chosen:
                rows.append({**base, "rank": None, "model_id": None, "basis": "no_data",
                             "note": "no sales figures or rival mentions found for this market"})
            for i, c in enumerate(chosen, start=1):
                rows.append({**c, "rank": i})
    cols = ["series", "market", "rank", "model_id", "basis", "units", "year", "region", "sales_source_id",
            "segment_label", "n_rival_mentions", "note"]
    return pd.DataFrame(rows).reindex(columns=cols)


# ---------------------------------------------------------------------- reviews
def classify_reviews(reviews: pd.DataFrame) -> pd.DataFrame:
    if reviews.empty:
        return reviews.assign(pred_feedback_type=None, pred_feedback_type_p=None, pred_domain=None, pred_domain_p=None,
                              pred_feature=None, pred_feature_p=None, sentiment=None, sentiment_basis=None, topic=None)
    from ..classifier import predict
    preds = predict(reviews["text"].tolist())
    out = reviews.copy()
    out["pred_feedback_type"] = [p["feedback_type"][0][0] for p in preds]
    out["pred_feedback_type_p"] = [p["feedback_type"][0][1] for p in preds]
    out["pred_domain"] = [p["domain"][0][0] for p in preds]
    out["pred_domain_p"] = [p["domain"][0][1] for p in preds]
    out["pred_feature"] = [p["feature"][0][0] for p in preds]
    out["pred_feature_p"] = [p["feature"][0][1] for p in preds]
    sent, basis = [], []
    for kind, ft in zip(out["kind"], out["pred_feedback_type"]):
        if kind in SENTIMENT_OF_KIND:
            sent.append(SENTIMENT_OF_KIND[kind])
            basis.append("pros/cons list")
        else:
            sent.append(config.SENTIMENT.get(ft, "positive"))
            basis.append("feedback-type classifier")
    out["sentiment"], out["sentiment_basis"] = sent, basis
    out["topic"] = [d if p >= TOPIC_MIN_P else None for d, p in zip(out["pred_domain"], out["pred_domain_p"])]
    return out


# ---------------------------------------------------------------------- build
def build(drop_invalid: bool = False, require_snapshot: bool = True) -> tuple[dict, dict]:
    rows, load_errors = records.load()
    valid, errors, stats = records.validate_all(rows, require_snapshot=require_snapshot)
    errors = load_errors + errors
    if errors and not drop_invalid:
        raise CompetitorDataError(f"{len(errors)} invalid competitor row(s); fix them or build with --drop-invalid:\n"
                                  + "\n".join(errors[:40]))
    if errors:                                   # rows named in a cross-row error are dropped as well
        bad = {e.split(" ", 1)[0].rstrip(":") for e in errors}
        valid = [r for r in valid if r["_where"] not in bad]
    metas = {m["source_id"]: m for m in all_sources()}
    by = {t: [r for r in valid if r["table"] == t] for t in R.TABLES}
    for r in valid:
        r["publisher"] = _publisher(r.get("source_id"), metas)

    models = _frame(by["model"], ["model_id", "brand", "model", "segment", "body", "generation"]).drop_duplicates("model_id")
    models["name"] = models["brand"] + " " + models["model"]
    models["competitive_segment"] = [effective_segment(sg, b) for sg, b in zip(models["segment"], models["brand"])]
    models["is_bmw"] = models["model_id"].isin(R.SELF_SERIES)
    models["bmw_series"] = models["model_id"].map(R.SELF_SERIES)
    models = models.sort_values(["segment", "model_id"]).reset_index(drop=True)

    sales = _frame(by["sales"], ["model_id", "market", "region", "year", "period", "units", "basis", "tier",
                                 "segment_label", "source_id", "publisher", "evidence", "note"])
    sales["period"] = sales["period"].fillna("FY")
    sales["tier_rank"] = sales["tier"].map(R.TIER_RANK)
    # several sources for the same figure: the most authoritative one is preferred; disagreements are reported
    sales = sales.sort_values(["model_id", "market", "region", "year", "period", "tier_rank", "source_id"])
    key = ["model_id", "market", "region", "year", "period"]
    sales["preferred"] = ~sales.duplicated(key)
    conflicts = []
    for k, g in sales.groupby(key):
        if g["units"].nunique() > 1:
            conflicts.append({"key": dict(zip(key, [str(x) for x in k])),
                              "values": [{"units": int(r.units), "source_id": r.source_id, "tier": r.tier}
                                         for r in g.itertuples()]})

    prices = _frame(by["price"], ["model_id", "market", "country", "currency", "variant", "amount", "powertrain",
                                  "price_type", "tax_basis", "entry", "model_year", "as_of", "power_kw", "source_id",
                                  "publisher", "evidence", "note"])
    prices["entry"] = prices["entry"].fillna(False).astype(bool)
    specs = _frame(by["spec"], ["model_id", "variant", "attribute", "value", "unit", "powertrain", "market",
                                "source_id", "publisher", "evidence", "note"])
    equipment = _frame(by["equipment"], ["model_id", "country", "item", "status", "price_eur", "item_name",
                                         "variant_scope", "source_id", "publisher", "evidence", "note"])
    equipment["feature"] = equipment["item"].map(lambda k: R.EQUIPMENT_ITEMS[k]["feature"])
    reviews = _frame(by["review"], ["model_id", "market", "country", "kind", "text", "rating", "rating_scale", "date",
                                    "model_year", "source_id", "publisher", "note"])
    reviews = classify_reviews(reviews)
    ratings = _frame(by["rating"], ["model_id", "market", "country", "rating_kind", "score", "scale_max", "n_reviews",
                                    "model_year", "source_id", "publisher", "evidence", "note"])
    rivals = _frame(by["rival"], ["model_id", "bmw_series", "market", "source_id", "publisher", "evidence"])
    used = sorted({r["source_id"] for r in valid if r.get("source_id")})
    src_cols = ["source_id", "url", "final_url", "publisher", "title", "retrieved_at", "kind", "rendered", "sha256",
                "bytes"]
    sources = pd.DataFrame([{**{k: metas[s].get(k) for k in src_cols}, "publisher": display_publisher(metas[s])}
                            for s in used if s in metas], columns=src_cols)

    sets = select_sets(models, sales, rivals, prices)
    tables = {"models": models, "sets": sets, "sales": _with_row_ids(sales.drop(columns=["tier_rank"])),
              "prices": _with_row_ids(prices), "specs": _with_row_ids(specs), "equipment": _with_row_ids(equipment),
              "reviews": _with_row_ids(reviews), "ratings": _with_row_ids(ratings), "rivals": _with_row_ids(rivals),
              "sources": sources, **bmw_tables()}
    quality = _quality(tables, stats, errors, conflicts, drop_invalid)
    return tables, quality


def _coverage(tables: dict) -> list[dict]:
    """Per competitor in each set: which kinds of data exist for its market."""
    out = []
    t = tables
    for r in t["sets"].dropna(subset=["model_id"]).itertuples():
        ref = R.REFERENCE[r.market]
        out.append({"series": r.series, "market": r.market, "rank": int(r.rank), "model_id": r.model_id,
                    "price": bool(((t["prices"]["model_id"] == r.model_id) & (t["prices"]["country"] == ref["country"])).any()),
                    "sales": bool(((t["sales"]["model_id"] == r.model_id) & (t["sales"]["market"] == r.market)).any()),
                    "specs": int((t["specs"]["model_id"] == r.model_id).sum()),
                    "equipment_items": int((t["equipment"]["model_id"] == r.model_id).sum()),
                    "reviews": int(((t["reviews"]["model_id"] == r.model_id) & (t["reviews"]["market"] == r.market)).sum()),
                    "ratings": int(((t["ratings"]["model_id"] == r.model_id) & (t["ratings"]["market"] == r.market)).sum())})
    return out


def data_hash(tables: dict) -> str:
    h = hashlib.sha256()
    for name in sorted(tables):
        h.update(name.encode() + tables[name].to_csv(index=False).encode())
    return h.hexdigest()[:12]


def _quality(tables: dict, stats: dict, errors: list, conflicts: list, dropped: bool) -> dict:
    sets = tables["sets"]
    retrieved = sorted(tables["sources"]["retrieved_at"].dropna()) if len(tables["sources"]) else []
    return {
        "built_at": pd.Timestamp.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "data_hash": data_hash(tables),
        "records": {**stats, "dropped_invalid": len(errors) if dropped else 0},
        "invalid_rows": errors[:200],
        "sales_conflicts": conflicts,
        "tables": {k: int(len(v)) for k, v in tables.items()},
        "sources": {"n": int(len(tables["sources"])), "retrieved_from": retrieved[0] if retrieved else None,
                    "retrieved_to": retrieved[-1] if retrieved else None,
                    "publishers": tables["sources"]["publisher"].value_counts().to_dict() if len(tables["sources"]) else {}},
        "sets": [{"series": s, "market": m, "status": g["basis"].iloc[0] if g["model_id"].isna().all() else "ok",
                  "competitors": [x for x in g["model_id"].dropna()],
                  "basis": sorted(set(g["basis"].dropna()))}
                 for (s, m), g in sets.groupby(["series", "market"], sort=False)],
        "coverage": _coverage(tables),
        "checks": {"sets_at_most_five": bool((sets.groupby(["series", "market"])["model_id"].count() <= R.N_COMPETITORS).all()),
                   "no_duplicate_competitor_in_a_set": not sets.dropna(subset=["model_id"]).duplicated(["series", "market", "model_id"]).any(),
                   "every_sold_tuple_has_a_set_or_reason": bool(len(sets.groupby(["series", "market"])) == len(config.MODELS) * len(R.MARKETS)),
                   "one_currency_per_reference_country": _one_currency(tables["prices"])},
    }


def _one_currency(prices: pd.DataFrame) -> bool:
    for market, ref in R.REFERENCE.items():
        p = prices[(prices["market"] == market) & (prices["country"] == ref["country"])]
        if len(p) and set(p["currency"]) != {ref["currency"]}:
            return False
    return True


def save(tables: dict, quality: dict) -> None:
    P.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(TABLE_FILES[name], index=False)
    QUALITY_FILE.write_text(json.dumps(quality, indent=1, default=_json_default, ensure_ascii=False))


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def build_and_save(drop_invalid: bool = False) -> dict:
    tables, quality = build(drop_invalid=drop_invalid)
    failed = [k for k, v in quality["checks"].items() if not v]
    if failed:
        raise CompetitorDataError(f"competitor checks failed: {failed}")
    save(tables, quality)
    return quality


def load_tables() -> dict | None:
    """The processed competitor tables, or None if they were never built."""
    if not all(f.exists() for f in TABLE_FILES.values()):
        return None
    out = {}
    for name, f in TABLE_FILES.items():
        try:
            out[name] = pd.read_csv(f, keep_default_na=False, na_values=[""])
        except pd.errors.EmptyDataError:
            out[name] = pd.DataFrame()
    return out


def load_quality() -> dict | None:
    return json.loads(QUALITY_FILE.read_text()) if QUALITY_FILE.exists() else None
