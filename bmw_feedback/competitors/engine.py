"""BMW vs its top five competitors per series x market, computed from the processed tables (no LLM).

Comparability rules, enforced here:
    prices     only within one market's reference country, currency and price basis (Germany: BMW's own DE price
               list vs German list prices; elsewhere BMW's web price vs rivals' web prices of the same type). Never
               converted between currencies.
    powertrain combustion (ICE, mild and full hybrid) / plug-in hybrid / electric compared like for like.
    sales      a rival's figure is set against the BMW figure of the same source, region and year only.
    ratings    a rival's score is set against BMW's score from the same publisher and kind only.
    equipment  German market (where BMW's price list comes from), labelled as such for every market.
    reviews    counts of review statements classified with the BMW feedback models; small counts are shown as counts.
"""

import re
import statistics

import pandas as pd

from .. import config
from . import registry as R
from .build import load_quality, load_tables

SERIES_NAMES = {"F70": "1 Series (F70)", "G60": "5 Series (G60)", "G70": "7 Series (G70)"}
PT_GROUP = {"ICE": "combustion", "MHEV": "combustion", "HEV": "combustion", "PHEV": "plug-in hybrid",
            "BEV": "electric", "EREV": "electric"}
PT_ORDER = ["combustion", "plug-in hybrid", "electric"]
STATUS_ORDER = {"standard": 0, "optional": 1, "package": 2, "not_available": 3}
SALES_BASES = ("sales", "sales_other_segment", "sales_other_source")
BMW_TIER_STATUS = {"standard_all": "standard", "standard_some": "standard_some", "optional": "optional",
                   "not_listed": "not_listed"}


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _str(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or v == "" else str(v)


LIST_DATE_RE = re.compile(r"(?:valid from|Stand:?|dated|as at|as of|list of|gültig ab)\s+([^;,()]*?\b20\d\d)", re.I)


def list_date(note) -> str | None:
    """The date of the price list an equipment row comes from, when its note states one."""
    m = LIST_DATE_RE.search(note or "")
    return m.group(1).strip() if m else None


def price_basis(row) -> str:
    """Comparable price basis: price type plus, for US MSRPs, whether the destination charge is included."""
    pt = row["price_type"]
    if row["country"] == "US" and pt == "msrp":
        tb = str(row.get("tax_basis") or "").lower()
        if any(w in tb for w in ("excl", "exclud", "before destination", "without destination", "plus destination")):
            return "msrp_excl_destination"
        if "incl" in tb or "includ" in tb:
            return "msrp_incl_destination"
        return "msrp"
    return pt


class CompetitorEngine:
    def __init__(self):
        self.t = load_tables()
        self.quality = load_quality() or {}
        self.available = bool(self.t is not None and len(self.t["sets"]) and self.t["sets"]["model_id"].notna().any())
        if not self.available:
            return
        t = self.t
        self.models = t["models"].set_index("model_id")
        self.sources = t["sources"].set_index("source_id") if len(t["sources"]) else pd.DataFrame()
        self.data_hash = self.quality.get("data_hash")

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        if not self.available:
            return {"available": False, "message": "No competitor data: run `python -m bmw_feedback competitors build`."}
        q = self.quality
        return {"available": True, "data_hash": self.data_hash, "built_at": q.get("built_at"),
                "sources": q.get("sources", {}).get("n"), "retrieved_from": q.get("sources", {}).get("retrieved_from"),
                "retrieved_to": q.get("sources", {}).get("retrieved_to"), "tables": q.get("tables"),
                "sets": q.get("sets"), "records": q.get("records")}

    # ------------------------------------------------------------------ helpers
    def name(self, mid: str) -> str:
        if mid in R.SELF_SERIES:
            return SERIES_NAMES[R.SELF_SERIES[mid]]
        return str(self.models.loc[mid, "name"]) if mid in self.models.index else mid

    def source(self, sid) -> dict | None:
        sid = _str(sid)
        if not sid or sid not in self.sources.index:
            return None
        s = self.sources.loc[sid]
        return {"source_id": sid, "publisher": _str(s.get("publisher")), "url": _str(s.get("url")),
                "title": _str(s.get("title")), "retrieved_at": _str(s.get("retrieved_at"))}

    def _bmw_prices(self, series: str, market: str) -> list[dict]:
        ref = R.REFERENCE[market]
        if market == "EU":
            p = self.t["bmw_prices"]
            p = p[p["model"] == series]
            return [{"model_id": R.BMW_SELF[series], "variant": r.variant, "powertrain": r.powertrain,
                     "group": PT_GROUP.get(r.powertrain, "combustion"), "amount": float(r.amount), "currency": "EUR",
                     "basis": "list_price", "tax_basis": "incl. 19% VAT", "power_kw": _num(r.power_kw),
                     "row_id": None, "source": {"kind": "pdf", "ref": r.ref, "page": int(r.page),
                                                 "publisher": "BMW DE price list (July 2026)"}}
                    for r in p.itertuples()]
        return self._web_prices(R.BMW_SELF[series], ref)

    def _web_prices(self, mid: str, ref: dict) -> list[dict]:
        p = self.t["prices"]
        p = p[(p["model_id"] == mid) & (p["country"] == ref["country"]) & (p["currency"] == ref["currency"])]
        out = []
        for _, r in p.iterrows():
            out.append({"model_id": mid, "variant": r["variant"], "powertrain": r["powertrain"],
                        "group": PT_GROUP.get(r["powertrain"], "combustion"), "amount": float(r["amount"]),
                        "currency": r["currency"], "basis": price_basis(r), "tax_basis": _str(r["tax_basis"]),
                        "power_kw": _num(r["power_kw"]), "model_year": _str(r["model_year"]), "row_id": r["row_id"],
                        "source": {"kind": "web", **(self.source(r["source_id"]) or {})}})
        return out

    @staticmethod
    def _cheapest(prices: list[dict], basis: str | None = None, group: str | None = None) -> dict | None:
        c = [p for p in prices if (basis is None or p["basis"] == basis) and (group is None or p["group"] == group)]
        return min(c, key=lambda p: p["amount"]) if c else None

    def _specs(self, mid: str, series: str | None, market: str) -> dict:
        """attribute -> {min, max, unit, n, variants} over the recorded variants (China: long-wheelbase rows first)."""
        rows = []
        if series is not None:
            b = self.t["bmw_specs"]
            for r in b[b["model"] == series].itertuples():
                rows.append({"attribute": r.attribute, "value": float(r.value), "variant": r.variant, "market": None,
                             "source": f"{series}_OptionList.PDF p.{int(r.page)}"})
        s = self.t["specs"]
        for _, r in s[s["model_id"] == mid].iterrows():
            rows.append({"attribute": r["attribute"], "value": float(r["value"]), "variant": r["variant"],
                         "market": _str(r["market"]), "source": (self.source(r["source_id"]) or {}).get("publisher"),
                         "row_id": r["row_id"]})
        out = {}
        for attr, (unit, label) in R.SPEC_ATTRIBUTES.items():
            a = [x for x in rows if x["attribute"] == attr]
            local = [x for x in a if x["market"] == market]
            a = local or [x for x in a if x["market"] is None]
            if not a:
                continue
            vals = [x["value"] for x in a]
            out[attr] = {"label": label, "unit": unit, "min": min(vals), "max": max(vals), "n": len(a),
                         "variants": sorted({x["variant"] for x in a}), "sources": sorted({x["source"] for x in a if x["source"]}),
                         "row_ids": [x.get("row_id") for x in a if x.get("row_id")]}
        return out

    def _equipment(self, mid: str, items: list[str]) -> dict:
        e = self.t["equipment"]
        out = {}
        for key in items:
            rows = e[(e["model_id"] == mid) & (e["item"] == key)]
            if rows.empty:
                out[key] = {"status": "unknown", "rows": []}
                continue
            lst = [{"status": r["status"], "price_eur": _num(r["price_eur"]), "item_name": r["item_name"],
                    "variant_scope": _str(r["variant_scope"]), "row_id": r["row_id"], "note": _str(r["note"]),
                    "source": self.source(r["source_id"])} for _, r in rows.iterrows()]
            lst.sort(key=lambda x: (STATUS_ORDER[x["status"]], x["variant_scope"] is not None, x["price_eur"] or 0))
            best = lst[0]
            status = best["status"]
            if status == "standard" and best["variant_scope"]:
                status = "standard_some"
            priced = [x for x in lst if x["status"] in ("optional", "package") and x["price_eur"]]
            cheapest = min(priced, key=lambda x: x["price_eur"]) if priced else None
            out[key] = {"status": status, "rows": lst, "variant_scope": best["variant_scope"],
                        "publisher": (best["source"] or {}).get("publisher"), "list_date": list_date(best["note"]),
                        "price_eur": cheapest["price_eur"] if cheapest else None,
                        "price_item": cheapest["item_name"] if cheapest else None,
                        "price_status": cheapest["status"] if cheapest else None}
        return out

    def _bmw_equipment(self, series: str, items: list[str]) -> dict:
        b = self.t["bmw_equipment"]
        out = {}
        for key in items:
            r = b[(b["model"] == series) & (b["item"] == key)]
            if r.empty:
                out[key] = {"status": "not_listed"}
                continue
            r = r.iloc[0]
            tier = r["tier"]
            out[key] = {"status": BMW_TIER_STATUS.get(tier, tier), "tier": tier,
                        "n_variants": None if pd.isna(r["n_variants"]) else int(r["n_variants"]),
                        "n_standard": None if pd.isna(r["n_standard"]) else int(r["n_standard"]),
                        "n_optional": None if pd.isna(r["n_optional"]) else int(r["n_optional"]),
                        "price_eur": _num(r["price_min_eur"]), "price_item": _str(r["price_item"]),
                        "via_package": None if pd.isna(r["via_package"]) else bool(r["via_package"]),
                        "items": _str(r["items"]), "pages": _str(r["pages"]), "item_id": _str(r.get("item_id"))}
        return out

    def _sales(self, mid: str, market: str, region: str | None = None, year: int | None = None,
               sid: str | None = None) -> dict | None:
        s = self.t["sales"]
        s = s[(s["model_id"] == mid) & (s["market"] == market) & (s["period"] == "FY")]
        if region is not None:
            s = s[s["region"] == region]
        if year is not None:
            s = s[s["year"] == year]
        if s.empty:
            return None
        pub = (self.source(sid) or {}).get("publisher") if sid else None
        same = s[s["source_id"] == sid] if sid else s.iloc[0:0]
        if same.empty and pub:                         # same publisher, another page (e.g. one page per model)
            same = s[s["publisher"] == pub]
        r = (same if len(same) else s[s["preferred"]] if s["preferred"].any() else s).sort_values("year").iloc[-1]
        units, twins = int(r["units"]), []
        all_s = self.t["sales"]
        for twin in R.BMW_TWINS.get(mid, []):          # e.g. the i5 listed separately in the same table
            tw = all_s[(all_s["model_id"] == twin) & (all_s["source_id"] == r["source_id"]) & (all_s["market"] == market)
                       & (all_s["region"] == r["region"]) & (all_s["year"] == r["year"]) & (all_s["period"] == r["period"])]
            if len(tw):
                twins.append({"model_id": twin, "name": twin.replace("bmw-", "").replace("-", " ").title().replace("I", "i", 1),
                              "units": int(tw.iloc[0]["units"]), "row_id": tw.iloc[0]["row_id"]})
                units += int(tw.iloc[0]["units"])
        return {"units": units, "year": int(r["year"]), "region": r["region"], "basis": r["basis"],
                "estimate": bool(re.search(r"estimat", str(r["note"] or ""), re.I)),
                "tier": r["tier"], "segment_label": _str(r["segment_label"]), "row_id": r["row_id"],
                "segment_text": R.segment_text(_str(r["segment_label"])), "note": _str(r["note"]),
                "own_units": int(r["units"]), "twins": twins,
                "same_source": bool(sid and (r["source_id"] == sid or (pub and r["publisher"] == pub))),
                "source": self.source(r["source_id"])}

    def _ratings(self, mid: str, market: str) -> list[dict]:
        r = self.t["ratings"]
        r = r[(r["model_id"] == mid) & (r["market"] == market)]
        return [{"publisher": (self.source(x["source_id"]) or {}).get("publisher"), "kind": x["rating_kind"],
                 "score": float(x["score"]), "scale_max": float(x["scale_max"]), "n_reviews": _num(x["n_reviews"]),
                 "row_id": x["row_id"], "source": self.source(x["source_id"])} for _, x in r.iterrows()]

    def _reviews(self, mid: str, market: str, domains: list[str]) -> dict:
        rv = self.t["reviews"]
        rv = rv[(rv["model_id"] == mid) & (rv["market"] == market)]
        if rv.empty:
            return {"n": 0}
        pos, neg = rv[rv["sentiment"] == "positive"], rv[rv["sentiment"] == "negative"]
        top = lambda d: [[k, int(v)] for k, v in d["topic"].dropna().value_counts().head(3).items()]
        quotes = []
        for frame in (pos, neg):
            if len(frame):
                q = frame.assign(L=(frame["text"].str.len() - 160).abs()).sort_values(["L", "row_id"]).iloc[0]
                quotes.append({"text": q["text"], "kind": q["kind"], "sentiment": q["sentiment"],
                               "row_id": q["row_id"], "source": self.source(q["source_id"])})
        in_domain = {d: {"positive": int(((rv["topic"] == d) & (rv["sentiment"] == "positive")).sum()),
                         "negative": int(((rv["topic"] == d) & (rv["sentiment"] == "negative")).sum())}
                     for d in domains}
        return {"n": int(len(rv)), "positive": int(len(pos)), "negative": int(len(neg)),
                "unassigned": int(rv["topic"].isna().sum()),
                "request": int((rv["sentiment"] == "request").sum()), "top_praise": top(pos), "top_criticism": top(neg),
                "publishers": sorted({p for p in rv["publisher"].dropna()}), "in_domain": in_domain, "quotes": quotes}

    # ------------------------------------------------------------------ comparison
    def compare(self, series: list[str] | None = None, markets: list[str] | None = None,
                features: list[str] | None = None, feature_domains: dict | None = None) -> dict:
        if not self.available:
            return {"available": False, "message": self.status()["message"], "tuples": []}
        series = [s for s in (series or config.MODELS) if s in config.MODELS]
        markets = [m for m in (markets or R.MARKETS) if m in R.MARKETS]
        features = features or []
        items = [k for f in features for k in R.FEATURE_ITEMS.get(f, [])]
        domains = sorted({d for d in (feature_domains or {}).values() if d})
        tuples = [self._tuple(s, m, items, domains) for s in series for m in markets]
        used = sorted({x for t in tuples for x in _source_ids(t)})
        return {"available": True, "data_hash": self.data_hash,
                "retrieved_from": self.quality.get("sources", {}).get("retrieved_from"),
                "retrieved_to": self.quality.get("sources", {}).get("retrieved_to"),
                "features": features, "feature_domains": feature_domains or {},
                "items": [{"key": k, **{f: R.EQUIPMENT_ITEMS[k][f] for f in ("label", "feature")}} for k in items],
                "features_without_items": [f for f in features if f not in R.FEATURE_ITEMS],
                "tuples": tuples, "sources": [self.source(s) for s in used if self.source(s)],
                "caveats": self.caveats(markets)}

    def _tuple(self, series: str, market: str, items: list[str], domains: list[str]) -> dict:
        ref = R.REFERENCE[market]
        sets = self.t["sets"]
        g = sets[(sets["series"] == series) & (sets["market"] == market)].sort_values("rank")
        base = {"series": series, "series_name": SERIES_NAMES[series], "market": market,
                "market_name": R.MARKET_NAMES[market], "reference": ref}
        if g.empty or g["model_id"].isna().all():
            basis = g["basis"].iloc[0] if len(g) else "no_data"
            return {**base, "status": "not_sold" if basis == "not_sold" else "no_data",
                    "note": _str(g["note"].iloc[0]) if len(g) else "no competitor set", "competitors": []}
        bmw_mid = R.BMW_SELF[series]
        bmw_prices = self._bmw_prices(series, market)
        bmw_entry = self._cheapest(bmw_prices)
        bmw = {"model_id": bmw_mid, "name": SERIES_NAMES[series], "prices": bmw_prices, "entry": bmw_entry,
               "specs": self._specs(bmw_mid, series, market), "equipment": self._bmw_equipment(series, items),
               "ratings": self._ratings(bmw_mid, market), "reviews": self._reviews(bmw_mid, market, domains)}
        comps = []
        for r in g.itertuples():
            mid = r.model_id
            prices = self._web_prices(mid, ref)
            # a price basis both sides have (BMW's entry basis first), so a gap never mixes e.g. MSRPs with and
            # without the destination charge
            order = ([bmw_entry["basis"]] if bmw_entry else []) + sorted({p["basis"] for p in bmw_prices} -
                                                                         ({bmw_entry["basis"]} if bmw_entry else set()))
            basis = next((b for b in order if any(p["basis"] == b for p in prices)), None)
            entry = self._cheapest(prices, basis) if basis else self._cheapest(prices)
            bmw_ref = self._cheapest(bmw_prices, basis) if basis else None
            gap = None
            if entry and bmw_ref:
                d = entry["amount"] - bmw_ref["amount"]
                gap = {"abs": round(d, 2), "pct": round(d / bmw_ref["amount"] * 100, 1),
                       "direction": "above" if d > 0 else "below" if d < 0 else "equal"}
            by_group = []
            for grp in PT_ORDER:
                c = self._cheapest(prices, basis, grp) if basis else None
                b = self._cheapest(bmw_prices, basis, grp) if basis else None
                if c or b:
                    row = {"group": grp, "competitor": c, "bmw": b, "gap": None}
                    if c and b:
                        d = c["amount"] - b["amount"]
                        row["gap"] = {"abs": round(d, 2), "pct": round(d / b["amount"] * 100, 1),
                                      "direction": "above" if d > 0 else "below" if d < 0 else "equal"}
                    by_group.append(row)
            sel_sales, bmw_sales = None, None
            if r.basis in SALES_BASES:
                sel_sales = self._sales(mid, market, r.region, int(r.year), _str(r.sales_source_id))
                bmw_sales = self._sales(bmw_mid, market, r.region, int(r.year), _str(r.sales_source_id))
            vs = None
            if sel_sales and bmw_sales and bmw_sales["units"] > 0:
                d = sel_sales["units"] - bmw_sales["units"]
                vs = {"abs": d, "pct": round(d / bmw_sales["units"] * 100, 1), "same_source": bmw_sales["same_source"]}
            ratings = []
            for cr in self._ratings(mid, market):
                twin = next((b for b in bmw["ratings"] if b["publisher"] == cr["publisher"] and b["kind"] == cr["kind"]
                             and b["scale_max"] == cr["scale_max"]), None)
                ratings.append({**cr, "bmw": twin})
            comps.append({
                "rank": int(r.rank), "model_id": mid, "name": self.name(mid),
                "brand": _str(self.models.loc[mid, "brand"]) if mid in self.models.index else None,
                "model": _str(self.models.loc[mid, "model"]) if mid in self.models.index else None,
                "segment": _str(self.models.loc[mid, "segment"]) if mid in self.models.index else None,
                "generation": _str(self.models.loc[mid, "generation"]) if mid in self.models.index else None,
                "basis": r.basis,
                "selection": {"units": None if pd.isna(r.units) else int(r.units),
                              "year": None if pd.isna(r.year) else int(r.year), "region": _str(r.region),
                              "segment_label": _str(r.segment_label),
                              "segment_text": R.segment_text(_str(r.segment_label)),
                              "segment_english": R.segment_english(_str(r.segment_label)),
                              "sales_note": (sel_sales or {}).get("note"),
                              "estimate": bool((sel_sales or {}).get("estimate")),
                              "n_rival_mentions": None if pd.isna(r.n_rival_mentions) else int(r.n_rival_mentions),
                              "source": self.source(r.sales_source_id), "note": _str(r.note)},
                "prices": prices, "entry": entry, "bmw_ref": bmw_ref, "gap": gap, "by_powertrain": by_group,
                "sales": sel_sales, "bmw_sales": bmw_sales, "sales_vs_bmw": vs,
                "specs": self._specs(mid, None, market), "equipment": self._equipment(mid, items),
                "ratings": ratings, "reviews": self._reviews(mid, market, domains)})
        notes = []
        if any(c["basis"] == "sales_other_source" and "not in" in (c["selection"].get("note") or "") for c in comps):
            notes.append("some rivals have no row in the main sales source (it may not cover them, e.g. imported "
                         "cars), so their figures come from another source and may be counted differently")
        est = [c["name"] for c in comps if c["selection"].get("estimate")]
        if est:
            notes.append(f"the sales figures for {', '.join(est)} are estimates by the source (the maker does not "
                         "publish them by model)")
        if len(comps) < R.N_COMPETITORS:
            notes.append(f"only {len(comps)} models meet the selection rule here (same segment and premium brand with "
                         f"at least {R.MIN_SHARE_OF_BMW:.0%} of the BMW's volume, or named as a rival by publishers and "
                         "offered in this market)")
        folded = sorted({c["selection"]["sales_note"].split("; ")[-1] for c in comps
                         if c["selection"].get("sales_note") and "no separate" in c["selection"]["sales_note"]})
        if folded:
            notes.append("the German registration statistics count electric twins inside the model series ("
                         + "; ".join(folded) + ")")
        old_lists = sorted({f"{c['name']} ({e['list_date']})" for c in comps for e in c["equipment"].values()
                            if e.get("list_date") and re.search(r"20(1\d|2[0-4])\b", e["list_date"])})
        return {**base, "status": "ok", "bmw": bmw, "competitors": comps, "set_notes": notes,
                "old_equipment_lists": old_lists,
                "selection_rule": self._rule(g), "summary": self._summary(bmw, comps, items)}

    @staticmethod
    def _rule(g: pd.DataFrame) -> str:
        s = g[g["basis"] == "sales"]
        if s.empty:
            s = g[g["basis"].isin(SALES_BASES)]
        parts = []
        if len(s):
            r = s.iloc[0]
            label = f", segment '{R.segment_text(r['segment_label'])}'" if _str(r["segment_label"]) else ""
            parts.append(f"ranked by {int(r['year'])} sales in {r['region']}{label}, among premium-brand models "
                         f"selling at least {R.MIN_SHARE_OF_BMW:.0%} of the BMW's volume")
        if (g["basis"] == "sales_other_segment").any():
            parts.append("then other segment tables of the same source")
        other = g[g["basis"] == "sales_other_source"]
        if other["note"].fillna("").str.startswith("not in").any():
            parts.append("including models the main source has no row for, with figures from other sources")
        if (~other["note"].fillna("").str.startswith("not in")).any() and len(other):
            parts.append("then models from other sales sources for the same region and year")
        if (g["basis"] == "rival_mentions").any():
            parts.append("completed with models publishers name as rivals")
        return "; ".join(parts)

    def _summary(self, bmw: dict, comps: list, items: list[str]) -> dict:
        out = {}
        # rank and median on one basis: BMW's entry basis, or the shared basis that covers the most rivals
        bases = [c["bmw_ref"]["basis"] for c in comps if c["gap"] is not None]
        if bmw["entry"] and bmw["entry"]["basis"] in bases:
            basis = bmw["entry"]["basis"]
        else:
            basis = max(set(bases), key=bases.count) if bases else None
        be = self._cheapest(bmw["prices"], basis) if basis else None
        priced = [c for c in comps if c["gap"] is not None and c["bmw_ref"]["basis"] == basis]
        if be and priced:
            amounts = sorted([c["entry"]["amount"] for c in priced] + [be["amount"]])
            med = statistics.median(c["entry"]["amount"] for c in priced)
            out["price"] = {"bmw_rank_from_cheapest": amounts.index(be["amount"]) + 1, "n_models": len(amounts),
                            "bmw_variant": be["variant"], "bmw_amount": be["amount"], "tax_basis": be.get("tax_basis"),
                            "n_competitors_priced": len(priced), "median_competitor": med,
                            "bmw_vs_median_abs": round(be["amount"] - med, 2),
                            "bmw_vs_median_pct": round((be["amount"] - med) / med * 100, 1),
                            "currency": be["currency"], "basis": be["basis"]}
        eq = {}
        for k in items:
            counts = {"standard": 0, "standard_some": 0, "optional": 0, "package": 0, "not_available": 0, "unknown": 0}
            for c in comps:
                counts[c["equipment"][k]["status"]] += 1
            eq[k] = counts
        out["equipment"] = eq
        return out

    def caveats(self, markets: list[str]) -> list[dict]:
        q = self.quality.get("sources", {})
        out = [{"id": "web-data", "text": f"Competitor data come from {q.get('n')} public web sources retrieved between "
                f"{(q.get('retrieved_from') or '')[:10]} and {(q.get('retrieved_to') or '')[:10]}; every value is "
                "quoted from a saved copy of its source page."},
               {"id": "list-prices", "text": "Prices are published list prices (Germany incl. 19% VAT; United States "
                "MSRP; China manufacturer guide price; Australia list price), without discounts, and are only compared "
                "within one market and currency."},
               {"id": "equipment-de", "text": "Equipment is compared for the German market, where BMW's own price list "
                "comes from; availability can differ in other markets."},
               {"id": "reviews-model", "text": "Review statements are sorted into topics by the classifiers trained on "
                "BMW customer comments; the counts are small and not a representative survey."},
               {"id": "review-generations", "text": "Some ratings and review statements refer to an earlier generation "
                "of a model; each such row says so in the data."}]
        if "RoW" in markets:
            out.append({"id": "row-australia", "text": "Rest of world is represented by Australia for prices, sales "
                        "and reviews."})
        if "CN" in markets:
            out.append({"id": "cn-lwb", "text": "In China the 5 Series is the long-wheelbase G68 and its main rivals "
                        "are long-wheelbase versions (E-Class L, A6L)."})
        return out


def _source_ids(t: dict) -> set:
    out = set()

    def walk(o):
        if isinstance(o, dict):
            if o.get("source_id"):
                out.add(o["source_id"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(t)
    return out
