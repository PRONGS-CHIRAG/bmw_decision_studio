"""The competitor comparison as facts: stable ID, a deterministic sentence, the value and where it comes from.

The competitor analyst and presenter agents may use only these facts. Every derived number a manager would ask
for (price gaps in money and percent, ranks, sales differences, equipment counts) is already in a statement, so
the agents never compute. Provenance points to the knowledge-graph node of the row (competitor nodes are added
by graph/build.py) and to the saved web source.
"""

import hashlib
import json

from ..agents.contracts import Fact, FactBundle, Provenance
from . import registry as R

PT_SLUG = {"combustion": "ice", "plug-in hybrid": "phev", "electric": "bev"}
PT_TEXT = {"combustion": "combustion (incl. mild and full hybrid)", "plug-in hybrid": "plug-in hybrid",
           "electric": "electric"}
STATUS_TEXT = {"standard": "standard", "standard_some": "standard on some versions", "optional": "a paid option",
               "package": "available only in a package", "not_available": "not offered",
               "unknown": "not found in the collected data", "not_listed": "not found in BMW's DE price list"}
KIND_TEXT = {"owner_review": "owner review", "expert_pro": "expert pro", "expert_con": "expert con",
             "expert_verdict": "expert verdict"}


def competition_id(scope: dict, data_hash: str) -> str:
    payload = json.dumps({"scope": scope, "data": data_hash}, sort_keys=True)
    return "cx" + hashlib.sha256(payload.encode()).hexdigest()[:14]


def money(amount: float, currency: str) -> str:
    return f"{R.CURRENCY_SYMBOL.get(currency, currency)} {amount:,.0f}"


def _rng(spec: dict) -> str:
    unit = spec["unit"]
    fmt = (lambda v: f"{v:,.1f}") if unit in ("s", "kWh") else (lambda v: f"{v:,.0f}")
    return f"{fmt(spec['min'])} {unit}" if spec["min"] == spec["max"] else f"{fmt(spec['min'])}-{fmt(spec['max'])} {unit}"


def vname(c: dict, variant: str) -> str:
    """'Audi A6 Limousine 2.0 TFSI' rather than 'Audi A6 A6 Limousine 2.0 TFSI'."""
    model = c.get("model") or ""
    if model and variant.lower().startswith(model.lower()) and c.get("brand"):
        return f"{c['brand']} {variant}"
    return f"{c['name']} {variant}"


def rating_words(r: dict) -> str:
    if r["kind"] == "owner_average" and r["scale_max"] == 100:
        return "owner-survey score"                    # e.g. a 100-point index, not a star average
    return {"owner_average": "owner average", "expert_score": "expert score"}.get(r["kind"], r["kind"])


def volume_words(basis: str | None) -> str:
    return {"registrations": "new registrations", "deliveries": "deliveries", "retail": "retail sales",
            "wholesale": "wholesale units", "insurance_registrations": "insurance registrations"}.get(basis or "", "units sold")


def _pct_word(gap: dict) -> str:
    return "the same as" if gap["direction"] == "equal" else f"{abs(gap['pct']):.1f}% {gap['direction']}"


class CompetitorFactBuilder:
    def __init__(self, comparison: dict, graph=None, cid: str = ""):
        self.c, self.g, self.cid = comparison, graph, cid
        self.facts: list[Fact] = []
        self._ids: set = set()
        self.missing_nodes: list[str] = []

    def _node(self, node: str | None) -> str | None:
        if node is None or self.g is None:
            return node
        if node in self.g:
            return node
        self.missing_nodes.append(node)
        return None

    def add(self, fid, group, statement, value=None, *, node=None, kind="web", ref="", key=None, page=None, unit=None,
            feature=None, series=None, market=None):
        if fid in self._ids:
            raise ValueError(f"duplicate competitor fact id {fid}")
        self._ids.add(fid)
        self.facts.append(Fact(id=fid, group=group, statement=statement, value=value, unit=unit, feature=feature,
                               series=series, market=market,
                               source=Provenance(node_id=self._node(node), kind=kind, ref=ref, key=key, page=page)))

    @staticmethod
    def _src(src: dict | None) -> tuple[str, str | None]:
        if not src:
            return "", None
        return src.get("url") or src.get("ref") or "", src.get("retrieved_at")

    # ------------------------------------------------------------------ build
    def build(self) -> FactBundle:
        c = self.c
        self.add("cx.data", "data", f"Competitor data version {c['data_hash']}: public web sources retrieved between "
                 f"{(c.get('retrieved_from') or '')[:10]} and {(c.get('retrieved_to') or '')[:10]}.", c["data_hash"],
                 kind="derived", ref="data/processed/competitor_sources.csv")
        for cv in c["caveats"]:
            self.add(f"cx.caveat.{cv['id']}", "caveat", cv["text"], None, kind="derived",
                     ref="bmw_feedback/competitors/engine.py")
        for f in c.get("features_without_items", []):
            slug = "".join(ch if ch.isalnum() else "_" for ch in f.lower()).strip("_")
            self.add(f"cx.noitem.{slug}", "equipment", f"Competitor equipment was not collected for '{f}': it is not "
                     "one of the compared equipment items.", f, kind="config", ref="competitors/registry.py",
                     feature=f, node=f"feature:{f}")
        for t in c["tuples"]:
            self._tuple(t)
        return FactBundle(evaluation_id=self.cid, idea="competitor analysis", facts=self.facts)

    def _tuple(self, t: dict):
        s, m = t["series"], t["market"]
        p = f"cx.{s}.{m}"
        where = f"the {t['series_name']} in {t['market_name']}"
        if t["status"] != "ok":
            text = (f"The {t['series_name']} is 'Not sold' in {t['market_name']} (zero volume in sales_volumes.xlsx), "
                    "so it has no competitor set there." if t["status"] == "not_sold" else
                    f"No competitor set could be formed for {where}: {t.get('note')}.")
            self.add(f"{p}.status", "set", text, "Not sold" if t["status"] == "not_sold" else "no data",
                     node=f"series:{s}", kind="derived", ref="competitors/build.py select_sets", series=s, market=m)
            return
        comps, bmw, ref = t["competitors"], t["bmw"], t["reference"]
        listing = "; ".join(f"{c['rank']}. {c['name']}" + (
            f" ({c['selection']['units']:,} units{', estimated' if c['selection'].get('estimate') else ''})"
            if c["selection"]["units"] is not None else "") for c in comps)
        why = "".join(f" Note: {n}." for n in t.get("set_notes", []))
        self.add(f"{p}.set", "set", f"Top {len(comps)} competitors of {where} ({t['selection_rule']}): {listing}.{why}",
                 len(comps), node=f"series:{s}", kind="derived", ref="data/processed/competitor_sets.csv",
                 key=f"{s}|{m}", series=s, market=m)
        if t.get("old_equipment_lists"):
            self.add(f"{p}.caveat.equipment_age", "caveat", f"Equipment data for some competitors of {where} come from "
                     f"price lists published before 2025: {', '.join(t['old_equipment_lists'])}; current equipment may "
                     "differ.", len(t["old_equipment_lists"]), node=f"series:{s}", kind="derived",
                     ref="data/processed/competitor_equipment.csv (notes)", series=s, market=m)
        self._bmw(p, t)
        for c in comps:
            self._competitor(p, t, c)
        self._summary(p, t)

    # ------------------------------------------------------------------ BMW
    def _bmw(self, p, t):
        s, m, bmw, ref = t["series"], t["market"], t["bmw"], t["reference"]
        e = bmw["entry"]
        name, country = t["series_name"], ref["country_name"]
        if e:
            if m == "EU":
                self.add(f"{p}.bmw.entry", "price", f"Entry price of the {name} in Germany: {money(e['amount'], 'EUR')} "
                         f"({e['variant']}, BMW DE price list July 2026, incl. 19% VAT).", e["amount"], unit="EUR",
                         node=f"variant:{s}|{e['variant']}", kind="pdf", ref=e["source"]["ref"], page=e["source"]["page"],
                         series=s, market=m)
            else:
                url, at = self._src(e["source"])
                self.add(f"{p}.bmw.entry", "price", f"Entry price of the {name} in {country}: "
                         f"{money(e['amount'], e['currency'])} ({e['variant']}, {e['tax_basis']}, "
                         f"{e['source'].get('publisher')}).", e["amount"], unit=e["currency"],
                         node=f"cprice:{e['row_id']}", ref=url, key=at, series=s, market=m)
        else:
            self.add(f"{p}.bmw.entry", "price", f"No {country} price for the {name} was found in the collected data, "
                     "so prices cannot be compared in this market.", None, node=f"series:{s}", kind="derived",
                     ref="data/processed/competitor_prices.csv", series=s, market=m)
        self._ratings_own(p, t)
        self._reviews(f"{p}.bmw", t, bmw, name)
        for k, eq in bmw["equipment"].items():
            label = R.EQUIPMENT_ITEMS[k]["label"]
            st = eq["status"]
            text = f"{label} on the {name} (BMW DE price list, July 2026): "
            if st in ("standard", "standard_some", "optional"):
                text += {"standard": f"standard on all {eq['n_variants']} variants in the equipment tables",
                         "standard_some": f"standard on {eq['n_standard']} of {eq['n_variants']} variants, optional on "
                                          f"{eq['n_optional']}",
                         "optional": f"optional on {eq['n_optional']} of {eq['n_variants']} variants"}[st]
                if eq.get("price_eur"):
                    text += (f"; cheapest way to get it: '{eq['price_item']}' from {money(eq['price_eur'], 'EUR')}"
                             + (" (a package with other equipment)" if eq.get("via_package") else ""))
                text += "."
            else:
                text += "no item in the price list matched (it may be missing from the price list or named differently)."
            node = f"option:{eq['item_id']}" if eq.get("item_id") else f"series:{s}"
            self.add(f"{p}.bmw.eq.{k}", "equipment", text, st, node=node, kind="pdf", ref=f"{s}_OptionList.PDF",
                     feature=R.EQUIPMENT_ITEMS[k]["feature"], series=s, market=m)

    def _ratings_own(self, p, t):
        s, m, name = t["series"], t["market"], t["series_name"]
        for j, r in enumerate(t["bmw"]["ratings"], start=1):
            url, at = self._src(r["source"])
            n = f" from {int(r['n_reviews']):,} reviews" if r.get("n_reviews") else ""
            self.add(f"{p}.bmw.rating{j}", "rating", f"{r['publisher']} {rating_words(r)} for the {name}: "
                     f"{r['score']:g} of {r['scale_max']:g}{n}.", r["score"], node=f"crating:{r['row_id']}", ref=url,
                     key=at, series=s, market=m)

    def _reviews(self, fid, t, entity, name):
        s, m = t["series"], t["market"]
        rv = entity["reviews"]
        if not rv.get("n"):
            return
        top = lambda xs: ", ".join(f"{d} ({n})" for d, n in xs) or "none"
        self.add(f"{fid}.reviews", "reviews", f"Review statements about the {name} in {t['market_name']} "
                 f"({', '.join(rv['publishers'])}): {rv['n']} statements, {rv['positive']} praise and {rv['negative']} "
                 f"criticism; most-praised topics: {top(rv['top_praise'])}; most-criticised topics: "
                 f"{top(rv['top_criticism'])}; {rv.get('unassigned', 0)} not assigned to a topic (classifier "
                 "confidence below 0.5).", rv["n"], kind="derived",
                 node=f"competitor:{entity['model_id']}" if entity["model_id"] not in R.SELF_SERIES else f"series:{s}",
                 ref="data/processed/competitor_reviews.csv (feedback-type and domain classifiers)", series=s, market=m)
        for d, counts in rv.get("in_domain", {}).items():
            slug = "".join(ch if ch.isalnum() else "_" for ch in d.lower()).strip("_")
            self.add(f"{fid}.reviews.{slug}", "reviews", f"Review statements about the {name} in {t['market_name']} "
                     f"on the topic '{d}': {counts['positive']} praise, {counts['negative']} criticism.",
                     counts["negative"], kind="derived",
                     node=f"competitor:{entity['model_id']}" if entity["model_id"] not in R.SELF_SERIES else f"series:{s}",
                     ref="data/processed/competitor_reviews.csv", series=s, market=m)
        for j, q in enumerate(rv.get("quotes", []), start=1):
            url, at = self._src(q["source"])
            pub = (q["source"] or {}).get("publisher")
            self.add(f"{fid}.quote{j}", "quote", f"{KIND_TEXT[q['kind']].capitalize()} on the {name} ({pub}): "
                     f"\"{q['text']}\"", q["text"], node=f"creview:{q['row_id']}", ref=url, key=at, series=s, market=m)

    # ------------------------------------------------------------------ one competitor
    def _competitor(self, p, t, c):
        s, m, ref, bmw = t["series"], t["market"], t["reference"], t["bmw"]
        k = f"{p}.c{c['rank']}"
        name, bname, country = c["name"], t["series_name"], ref["country_name"]
        node = f"competitor:{c['model_id']}"
        sel = c["selection"]
        if c["basis"] in ("sales", "sales_other_segment", "sales_other_source"):
            url, at = self._src(sel["source"])
            seg = f" (segment '{sel['segment_text']}')" if sel.get("segment_text") else ""
            gap = c["basis"] == "sales_other_source" and (sel.get("note") or "").startswith("not in")
            other = ("; it has no row in the main sales source (which may not cover it, e.g. imports), so this figure "
                     "comes from another source" if gap else
                     {"sales_other_source": "; ranked after the main sales source, from another source",
                      "sales_other_segment": "; from another segment table of the same source"}.get(c["basis"], ""))
            vw = volume_words((c.get("sales") or {}).get("basis"))
            est = " (an estimate by the source)" if sel.get("estimate") else ""
            text = (f"Competitor {c['rank']} of the {bname} in {t['market_name']}: {name}, with {sel['units']:,} "
                    f"{vw}{est} in {sel['region']} in {sel['year']}{seg}, source {(sel['source'] or {}).get('publisher')}"
                    f"{other}.")
            self.add(k, "set", text, c["rank"], node=node, ref=url, key=at, series=s, market=m)
        else:
            self.add(k, "set", f"Competitor {c['rank']} of the {bname} in {t['market_name']}: {name}, {sel['note']}.",
                     c["rank"], node=node, kind="derived", ref="data/processed/competitor_rivals.csv", series=s, market=m)
        e = c["entry"]
        if e and c["gap"]:
            g, br = c["gap"], c["bmw_ref"]
            url, at = self._src(e["source"])
            rel = ("the same as" if g["direction"] == "equal" else
                   f"{money(abs(g['abs']), e['currency'])} ({abs(g['pct']):.1f}%) {g['direction']}")
            same_as_entry = bmw["entry"] and br["variant"] == bmw["entry"]["variant"] and br["basis"] == bmw["entry"]["basis"]
            ref_txt = (f"the {bname} entry price of {money(br['amount'], e['currency'])}" if same_as_entry else
                       f"the {bname} {br['variant']} at {money(br['amount'], e['currency'])} on the same price basis "
                       f"({br['tax_basis']}, {(br['source'] or {}).get('publisher')})")
            self.add(f"{k}.entry", "price", f"Entry price of the {name} in {country}: {money(e['amount'], e['currency'])}"
                     f" ({e['variant']}, {e['tax_basis']}, {e['source'].get('publisher')}); that is {rel} {ref_txt}.",
                     e["amount"], unit=e["currency"], node=f"cprice:{e['row_id']}", ref=url, key=at, series=s, market=m)
        elif e:
            url, at = self._src(e["source"])
            self.add(f"{k}.entry", "price", f"Entry price of the {name} in {country}: {money(e['amount'], e['currency'])}"
                     f" ({e['variant']}, {e['tax_basis']}); not comparable with the {bname} price in the data "
                     "(different price basis or no BMW price).", e["amount"], unit=e["currency"],
                     node=f"cprice:{e['row_id']}", ref=url, key=at, series=s, market=m)
        else:
            self.add(f"{k}.entry", "price", f"No {country} price for the {name} was found in the collected data.", None,
                     node=node, kind="derived", ref="data/processed/competitor_prices.csv", series=s, market=m)
        for row in c["by_powertrain"]:
            if not (row["competitor"] and row["bmw"] and row["gap"]):
                continue
            cp, bp, g = row["competitor"], row["bmw"], row["gap"]
            if e and cp["row_id"] == e["row_id"] and c["bmw_ref"] and bp["variant"] == c["bmw_ref"]["variant"]:
                continue                                      # same pair as the entry-price fact
            url, at = self._src(cp["source"])
            rel = ("the same as" if g["direction"] == "equal" else
                   f"{money(abs(g['abs']), cp['currency'])} ({abs(g['pct']):.1f}%) {g['direction']}")
            self.add(f"{k}.price.{PT_SLUG[row['group']]}", "price", f"Cheapest {PT_TEXT[row['group']]} version in "
                     f"{country}: {vname(c, cp['variant'])} at {money(cp['amount'], cp['currency'])}, {rel} the {bname} "
                     f"{bp['variant']} at {money(bp['amount'], bp['currency'])}.", cp["amount"], unit=cp["currency"],
                     node=f"cprice:{cp['row_id']}", ref=url, key=at, series=s, market=m)
        if c["sales"]:
            sa = c["sales"]
            url, at = self._src(sa["source"])
            est = " (an estimate by the source)" if sa.get("estimate") else ""
            text = f"{name}: {sa['units']:,} {volume_words(sa.get('basis'))}{est} in {sa['region']} in {sa['year']}"
            if c["sales_vs_bmw"] and c["bmw_sales"]:
                v, b = c["sales_vs_bmw"], c["bmw_sales"]
                word = "more" if v["abs"] > 0 else "fewer" if v["abs"] < 0 else "the same number of"
                same = "same source" if v["same_source"] else "same region and year, different source"
                if b.get("twins"):
                    same += "; " + " and ".join(f"{b['own_units']:,} {bname.split(' (')[0]} plus {tw['units']:,} "
                                                f"{tw['name']}, listed separately" for tw in b["twins"][:1])
                text += (f", vs {b['units']:,} for the {bname} ({same}): {abs(v['abs']):,} ({abs(v['pct']):.1f}%) "
                         f"{word}" if v["abs"] else f", the same as the {bname} ({same})")
            self.add(f"{k}.sales", "sales", text + ".", sa["units"], unit="units", node=f"csales:{sa['row_id']}",
                     ref=url, key=at, series=s, market=m)
        for attr, sp in c["specs"].items():
            b = bmw["specs"].get(attr)
            text = f"{sp['label']}: {name} {_rng(sp)} across {sp['n']} recorded value(s)"
            text += f" vs {bname} {_rng(b)}." if b else f"; no comparable {bname} value in the data."
            node_id = f"cspec:{sp['row_ids'][0]}" if sp.get("row_ids") else node
            self.add(f"{k}.spec.{attr}", "spec", text, sp["max"], unit=sp["unit"], node=node_id, kind="web",
                     ref="; ".join(sp["sources"]), series=s, market=m)
        for item, eq in c["equipment"].items():
            label = R.EQUIPMENT_ITEMS[item]["label"]
            st = eq["status"]
            pub = (f", {eq['publisher']}" if eq.get("publisher") else "") + (
                f", price list {eq['list_date']}" if eq.get("list_date") else "")
            text = f"{label} on the {name} (German market{pub}): {STATUS_TEXT[st]}"
            if st == "standard_some" and eq.get("variant_scope"):
                text += f" ({eq['variant_scope']})"
            if eq.get("price_eur"):
                how = "in the package" if eq.get("price_status") == "package" else "as the option"
                text += f"; from {money(eq['price_eur'], 'EUR')} {how} '{eq['price_item']}'"
            text += "."
            row = eq["rows"][0] if eq.get("rows") else None
            url, at = self._src(row["source"]) if row else ("", None)
            self.add(f"{k}.eq.{item}", "equipment", text, st, node=f"cequip:{row['row_id']}" if row else node,
                     kind="web" if row else "derived", ref=url or "data/processed/competitor_equipment.csv", key=at,
                     feature=R.EQUIPMENT_ITEMS[item]["feature"], series=s, market=m)
        for j, r in enumerate(c["ratings"], start=1):
            url, at = self._src(r["source"])
            n = f" from {int(r['n_reviews']):,} reviews" if r.get("n_reviews") else ""
            text = f"{r['publisher']} {rating_words(r)} for the {name}: {r['score']:g} of {r['scale_max']:g}{n}"
            if r.get("bmw"):
                b = r["bmw"]
                bn = f" from {int(b['n_reviews']):,} reviews" if b.get("n_reviews") else ""
                text += f"; the {bname} scores {b['score']:g} of {b['scale_max']:g}{bn} on the same publisher"
            self.add(f"{k}.rating{j}", "rating", text + ".", r["score"], node=f"crating:{r['row_id']}", ref=url, key=at,
                     series=s, market=m)
        self._reviews(k, t, c, name)

    # ------------------------------------------------------------------ summary
    def _summary(self, p, t):
        s, m, bmw = t["series"], t["market"], t["bmw"]
        sm = t["summary"]
        pr = sm.get("price")
        if pr:
            n, rank = pr["n_models"], pr["bmw_rank_from_cheapest"]
            d = pr["bmw_vs_median_abs"]
            rel = ("equal to" if d == 0 else f"{money(abs(d), pr['currency'])} ({abs(pr['bmw_vs_median_pct']):.1f}%) "
                   f"{'above' if d > 0 else 'below'}")
            self.add(f"{p}.price_rank", "summary", f"Of the {t['series_name']} and its {pr['n_competitors_priced']} "
                     f"competitors with a comparable price in {t['reference']['country_name']} ({pr['tax_basis']}), the "
                     f"{t['series_name']} ({pr['bmw_variant']}, {money(pr['bmw_amount'], pr['currency'])}) has entry "
                     f"price rank {rank} of {n} (1 = cheapest); that is {rel} the competitors' median of "
                     f"{money(pr['median_competitor'], pr['currency'])}.", rank, kind="derived",
                     node=f"series:{s}", ref="competitors/engine.py", series=s, market=m)
        for item, counts in sm.get("equipment", {}).items():
            label = R.EQUIPMENT_ITEMS[item]["label"]
            n = sum(counts.values())
            parts = [f"{v} {STATUS_TEXT[k]}" for k, v in counts.items() if v]
            self.add(f"{p}.eq.{item}", "equipment", f"{label} across the {n} competitors of the {t['series_name']} in "
                     f"{t['market_name']} (German-market equipment): {'; '.join(parts)}.", counts.get("standard", 0),
                     kind="derived", node=f"series:{s}", ref="competitors/engine.py",
                     feature=R.EQUIPMENT_ITEMS[item]["feature"], series=s, market=m)


def build_bundle(comparison: dict, graph=None, cid: str = "") -> tuple[FactBundle, list[str]]:
    b = CompetitorFactBuilder(comparison, graph, cid)
    return b.build(), b.missing_nodes
