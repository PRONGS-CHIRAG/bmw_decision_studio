"""Fact bundle: every number and label the explainer may use, computed by code.

The decision engine (decision.py) produces the evaluation; this module turns it
into facts with stable IDs, a deterministic sentence, the raw value and a
pointer into the knowledge graph (node id + table / PDF page / model file).
Statements already contain derived numbers a PM would ask for (e.g. "33% more
complaints than expected", "EUR 360 below today's lowest price") so that the
explainer never has to compute anything.
"""

import hashlib
import json

from .. import scoring
from ..graph.build import nid
from .contracts import MOVE_LABELS, Fact, FactBundle, IdeaSpec, Provenance

MARKET_NAMES = {"EU": "Europe", "US": "United States", "CN": "China", "RoW": "Rest of world"}
SERIES_NAMES = {"F70": "1 Series (F70)", "G60": "5 Series (G60)", "G70": "7 Series (G70)"}
SALES_GROUP = {"F70": "F70", "G60": "G60_G68", "G70": "G70"}
RECS = ["Prioritise", "Consider", "Low priority", "Insufficient evidence", "Not sold"]
TIER_TEXT = {
    "standard_all": "standard on every variant in the equipment tables",
    "standard_some": "standard on some variants and optional on others",
    "optional": "an optional extra",
    "not_listed": "not found in this series' price list (no item matched the curated keywords)",
}


def evaluation_id(spec: IdeaSpec, policy_hash: str, data_hash: str) -> str:
    payload = json.dumps({"spec": spec.model_dump(exclude={"method", "ambiguities", "summary"}),
                          "policy": policy_hash, "data": data_hash}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _n2(v) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def _int(v) -> str:
    return f"{int(round(v)):,}"


def _eur(v) -> str:
    return f"EUR {v:,.0f}"


def _pct_more(index: float) -> str:
    pct = round((index - 1) * 100)
    if pct == 0:
        return "as many complaints as expected"
    return f"{abs(pct)}% {'more' if pct > 0 else 'fewer'} complaints than expected for its channels"


class FactBuilder:
    def __init__(self, engine, graph, spec: IdeaSpec, result: dict, candidates: list, eval_id: str):
        self.engine, self.g, self.spec, self.result = engine, graph, spec, result
        self.candidates, self.eval_id = candidates, eval_id
        self.facts: list[Fact] = []
        self._ids: set = set()

    def add(self, fid, group, statement, value=None, *, node=None, kind="engine", ref="DecisionEngine.evaluate",
            key=None, page=None, unit=None, feature=None, series=None, market=None):
        if fid in self._ids:
            raise ValueError(f"duplicate fact id {fid}")
        if node is not None and not node.startswith(("rec:", "idea:")) and node not in self.g:
            raise KeyError(f"fact {fid} points to a node that is not in the graph: {node}")
        self._ids.add(fid)
        self.facts.append(Fact(id=fid, group=group, statement=statement, value=value, unit=unit, feature=feature,
                               series=series, market=market,
                               source=Provenance(node_id=node, kind=kind, ref=ref, key=key, page=page)))

    # ------------------------------------------------------------------ top level
    def build(self) -> FactBundle:
        r, spec = self.result, self.spec
        self._scope()
        if not r["features"]:
            self._no_match()
        for i, fr in enumerate(r["features"], start=1):
            self._feature(f"f{i}", fr)
        self._models()
        self._caveats()
        self._policy()
        return FactBundle(evaluation_id=self.eval_id, idea=spec.idea, facts=self.facts)

    def _scope(self):
        s, r = self.spec, self.result
        series = ", ".join(SERIES_NAMES[m] for m in r["models"])
        markets = ", ".join(MARKET_NAMES[m] for m in r["markets"])
        price = _eur(s.proposed_price_eur) if s.proposed_price_eur else "none"
        self.add("idea.scope", "scope", f"Scope confirmed by the PM: series {series}; markets {markets}; proposed move: "
                 f"{MOVE_LABELS[s.move]}; proposed price: {price}.", s.move, node="idea:current", kind="pm",
                 ref="IdeaSpec confirmed in the app")
        if s.proposed_price_eur:
            self.add("idea.price", "scope", f"Proposed price: {_eur(s.proposed_price_eur)}.", s.proposed_price_eur,
                     unit="EUR", node="idea:current", kind="pm", ref="IdeaSpec confirmed in the app")

    def _no_match(self):
        res = self.engine.resolve_idea(self.spec.idea)
        best = res["matches"][0]["score"] if res["matches"] else 0.0
        self.add("match.none", "match", "No feature in the customer feedback matches the idea directly (best match "
                 f"score {best:.2f}; a direct match needs 0.50). The data holds no customer evidence for it.",
                 best, node="idea:current", kind="engine", ref="DecisionEngine.resolve_idea")
        for j, c in enumerate(self.candidates[:5], start=1):
            how = ", ".join(f"{k} {v:.2f}" for k, v in c.methods.items())
            self.add(f"match.near{j}", "match", f"Nearest feature in the data: '{c.feature}' ({c.domain}), rated "
                     f"'{c.verdict}' from {c.n_comments} comments (match: {how}).", c.feature,
                     node=nid("feature", c.feature), kind="table", ref="reports/feature_scorecard.csv",
                     key=c.feature, feature=c.feature)

    # ------------------------------------------------------------------ one feature
    def _feature(self, p: str, fr: dict):
        f = fr["feature"]
        o = fr["overall"]
        pick = next((x for x in self.spec.features if x.feature == f), None)
        vnode = nid("verdict", "feature", f)
        card_ref = "reports/feature_scorecard.csv"
        self.add(f"{p}.feature", "feature", f"Feature evaluated: '{f}' (domain {fr['domain']}).", f,
                 node=nid("feature", f), kind="table", ref=card_ref, key=f, feature=f)
        if pick and pick.methods:
            how = ", ".join(f"{k.replace('_', ' ')} {v:.2f}" for k, v in pick.methods.items())
            self.add(f"{p}.match", "match", f"'{f}' was matched to the idea by: {how}.",
                     max(pick.methods.values()), node=nid("feature", f), kind="engine",
                     ref="Retriever candidates (name/alias, feature classifier, semantic index)", feature=f)
        self.add(f"{p}.overall.verdict", "feature", f"Across all series and markets '{f}' is rated '{o['verdict']}' "
                 f"({o['confidence']} confidence, {o['n_comments']:,} comments).", o["verdict"], node=vnode,
                 kind="table", ref=card_ref, key=f, feature=f)
        self.add(f"{p}.overall.n_comments", "feature", f"{o['n_comments']:,} customer comments mention '{f}'.",
                 o["n_comments"], unit="comments", node=vnode, kind="table", ref=card_ref, key=f, feature=f)
        if o["verdict"] != "Not enough data":
            self.add(f"{p}.overall.complaint_index", "feature", f"Complaint index for '{f}': {_n2(o['complaint_index'])}"
                     f" (95% CI {_n2(o['ci_low'])}-{_n2(o['ci_high'])}), i.e. {_pct_more(o['complaint_index'])}. "
                     "1.00 means as expected.", o["complaint_index"], node=vnode, kind="table", ref=card_ref, key=f,
                     feature=f)
            self.add(f"{p}.overall.request_index", "feature", f"Request index for '{f}': {_n2(o['request_index'])} "
                     "(1.00 = as many requests as expected).", o["request_index"], node=vnode, kind="table",
                     ref=card_ref, key=f, feature=f)
            self.add(f"{p}.overall.praise_index", "feature", f"Praise index for '{f}': {_n2(o['praise_index'])} "
                     "(1.00 = as much praise as expected).", o["praise_index"], node=vnode, kind="table",
                     ref=card_ref, key=f, feature=f)
        row = self.engine.ctx.features.loc[f]
        requested = bool(row["requested"])
        self.add(f"{p}.overall.requested", "feature", f"'{f}' {'is' if requested else 'is not'} a statistically "
                 "significant unmet need (request index >= 1.5 with the 95% CI above 1).", requested, node=vnode,
                 kind="table", ref=card_ref, key=f, feature=f)
        nd, nu = int(row["n_defect"]), int(row["n_difficult_to_use"])
        if nd + nu:
            self.add(f"{p}.overall.bad_kind", "feature", f"Complaints about '{f}' are {scoring.bad_kind(row)}: {nd} "
                     f"defect and {nu} difficult-to-use mentions.", scoring.bad_kind(row), node=vnode, kind="table",
                     ref=card_ref, key=f, feature=f)
        if fr["umbrella"]:
            self.add(f"{p}.umbrella", "caveat", f"'{f}' is an umbrella label: annotators file general praise here, "
                     "so judge it at domain level.", True, node=nid("feature", f), kind="config",
                     ref="bmw_feedback/taxonomy.py UMBRELLA_FEATURES", feature=f)
        reasons = scoring.reason_breakdown(self.engine.ctx.labels, f)
        for sent, word in (("negative", "complaint"), ("positive", "praise"), ("request", "request")):
            fams = reasons[sent]["families"]
            if fams:
                text = "; ".join(f"{k} ({v} comments)" for k, v in fams.items())
                self.add(f"{p}.reasons.{sent}", "feature", f"Top {word} reasons for '{f}': {text}.",
                         next(iter(fams)), node=nid("feature", f), kind="table", ref="data/processed/labels.csv",
                         key=f"{f} / {sent}", feature=f)
        self._rollup(p, fr)
        for c in fr["cells"]:
            self._cell(p, f, c)
        self._price(p, fr)
        self._specs(p, f)
        self._move(p, fr)
        self._ebm(p, fr)

    def _rollup(self, p, fr):
        f, ru = fr["feature"], fr["rollup"]
        if ru["score"] is not None:
            self.add(f"{p}.rollup.score", "summary", f"Volume-weighted priority score for '{f}' over the cells with "
                     f"enough evidence: {_n2(ru['score'])} (0 = no case, 1 = strongest case).", ru["score"],
                     node=nid("feature", f), feature=f)
        self.add(f"{p}.rollup.volume_share", "summary", f"Cells with enough evidence for a recommendation on '{f}' "
                 f"cover {ru['evidence_volume_share'] * 100:.0f}% of the sales volume in scope.",
                 ru["evidence_volume_share"], unit="share", node=nid("feature", f), feature=f)
        for m, v in ru["by_model"].items():
            if v["score"] is not None:
                self.add(f"{p}.rollup.{m}", "summary", f"Volume-weighted priority score for '{f}' on the "
                         f"{SERIES_NAMES[m]}: {_n2(v['score'])}.", v["score"], node=nid("series", m), feature=f,
                         series=m)
        cells = fr["cells"]
        sold = [c for c in cells if c["recommendation"] != "Not sold"]
        self.add(f"{p}.counts.sold", "summary", f"'{f}' is evaluated in {len(cells)} series-market cells, "
                 f"{len(sold)} of them with sales volume.", len(sold), node=nid("feature", f), feature=f)
        for rec in RECS:
            hit = [c for c in cells if c["recommendation"] == rec]
            if hit:
                where = ", ".join(f"{c['model']} {c['market']}" for c in hit)
                slug = rec.lower().replace(" ", "_")
                self.add(f"{p}.counts.{slug}", "summary", f"'{rec}' for '{f}' in {len(hit)} of {len(cells)} cells: "
                         f"{where}.", len(hit), node=nid("feature", f), feature=f)

    def _cell(self, p, f, c):
        m, k = c["model"], c["market"]
        cp = f"{p}.{m}.{k}"
        where = f"{SERIES_NAMES[m]} in {MARKET_NAMES[k]}"
        rec_node = f"rec:{f}|{m}|{k}"
        year = self.result["policy"]["volume_year"]
        sales_node = nid("sales", SALES_GROUP[m], k, year)
        vol = c["sales"].get(year, c["sales"].get(str(year), 0))
        note = " (includes the G68 long wheelbase)" if m == "G60" else ""
        self.add(f"{cp}.volume", "sales", f"Sales volume {year}, {where}: {_int(vol)} units{note}.", vol, unit="units",
                 node=sales_node, kind="xlsx", ref="sales_volumes.xlsx", key=f"{SALES_GROUP[m]} / {k} / {year}",
                 feature=f, series=m, market=k)
        if c["recommendation"] == "Not sold":
            self.add(f"{cp}.recommendation", "cell", f"{where}: 'Not sold' (zero sales volume in 2024, 2025 and "
                     "2030 in sales_volumes.xlsx).", "Not sold", node=rec_node, feature=f, series=m, market=k)
            return
        score = "" if c["score"] is None else f", score {_n2(c['score'])}"
        self.add(f"{cp}.recommendation", "cell", f"{where}: '{c['recommendation']}'{score} with "
                 f"{c['coverage'] * 100:.0f}% of the weighted evidence available.", c["recommendation"],
                 node=rec_node, ref=f"DecisionEngine.evaluate (policy {self.result['policy_hash']})", feature=f,
                 series=m, market=k)
        if c["score"] is not None:
            self.add(f"{cp}.score", "cell", f"Priority score {where}: {_n2(c['score'])}.", c["score"], node=rec_node,
                     feature=f, series=m, market=k)
        s = c["signals"]
        comp = s["complaints"]
        if comp.get("score") is not None:
            lvl = comp.get("level")
            if lvl == "borrowed":
                node = nid("verdict", "feature-series", f, m)
                text = (f"Complaints {where}: only {comp['n_comments_market']} comments in this market, so the "
                        f"{m} all-market verdict is borrowed at reduced weight: '{comp['verdict']}', complaint index "
                        f"{_n2(comp['complaint_index'])} (95% CI {_n2(comp['ci_low'])}-{_n2(comp['ci_high'])}), "
                        f"{comp['n_comments']} comments.")
            else:
                node = nid("verdict", "feature-series-market", f, m, k)
                text = (f"Complaints {where}: '{comp['verdict']}', complaint index {_n2(comp['complaint_index'])} "
                        f"(95% CI {_n2(comp['ci_low'])}-{_n2(comp['ci_high'])}), {comp['observed']} complaint "
                        f"mentions vs {comp['expected']:.1f} expected, {comp['n_comments']} comments; i.e. "
                        f"{_pct_more(comp['complaint_index'])}.")
            self.add(f"{cp}.complaints", "cell", text, comp["complaint_index"], node=node, kind="derived",
                     ref="scoring.score (channel-adjusted complaint index)", feature=f, series=m, market=k)
        else:
            self.add(f"{cp}.complaints", "cell", f"Complaints {where}: no signal ({comp.get('status')}).", None,
                     node=nid("feature", f), kind="derived", ref="DecisionEngine signals", feature=f, series=m,
                     market=k)
        req = s["requests"]
        if req.get("score") is not None:
            node = (nid("verdict", "feature-series", f, m) if req.get("level") == "borrowed"
                    else nid("verdict", "feature-series-market", f, m, k))
            need = "a significant unmet need" if req.get("requested") else "not a significant unmet need"
            borrowed = " (borrowed from all markets)" if req.get("level") == "borrowed" else ""
            self.add(f"{cp}.requests", "cell", f"Requests {where}{borrowed}: request index "
                     f"{_n2(req['request_index'])}, {req['observed']} requests vs {req['expected']:.1f} expected; "
                     f"{need}.", req["request_index"], node=node, kind="derived", ref="scoring.score (request index)",
                     feature=f, series=m, market=k)
        br = s["breadth"]
        if br.get("score") is not None and br.get("n_comments") is not None:
            rank = (f", rank {br['rank_among_features']} of {br['n_features']} features"
                    if br.get("rank_among_features") else "")
            self.add(f"{cp}.breadth", "cell", f"Breadth for the {SERIES_NAMES[m]}: {br['n_comments']:,} of "
                     f"{br['model_comments']:,} {m} comments (all markets) mention '{f}'{rank}; percentile "
                     f"{_n2(br['score'])}.", br["score"], node=nid("feature", f), kind="derived",
                     ref="data/processed/labels.csv (comment counts per series)", feature=f, series=m, market=k)
        sv = s["survey"]
        if sv.get("score") is not None:
            for j, a in enumerate(sv["attributes"], start=1):
                study = "US" if k == "US" else k
                node = nid("surveyscore", study, sv["survey_model"], a["attribute"])
                if "top2_box" in a:
                    val = (f"top-2 box {a['top2_box'] * 100:.1f}% vs {a['model_mean_top2'] * 100:.1f}% series "
                           "average")
                else:
                    val = f"mean {a['mean']:.2f} of 10 vs {a['model_mean']:.2f} series average"
                g68 = " (the China study covers the G68 long wheelbase)" if sv["survey_model"] == "G68" else ""
                self.add(f"{cp}.survey{j}", "survey", f"Customer study {sv['sheet']}{g68}: '{a['attribute']}' ranks "
                         f"{a['rank']} of {a['of']} attributes for the {sv['survey_model']} ({val}); 1 = best rated.",
                         a["rank"], node=node, kind="xlsx", ref="F70_G60_G68_G70_customer_studies.xlsx",
                         key=sv["sheet"], feature=f, series=m, market=k)
        else:
            self.add(f"{cp}.survey", "survey", f"Customer study {where}: {sv.get('status')}.", None,
                     node=nid("feature", f), kind="derived", ref="taxonomy survey maps", feature=f, series=m,
                     market=k)
        cpt = s.get("competitors") or {}
        if cpt.get("score") is not None:
            listed = "; ".join(f"{r['name']}: {r['status'].replace('_', ' ')}" for r in cpt["rivals"])
            self.add(f"{cp}.competitors", "competitor", f"Competitors {where} ({cpt['basis']}): BMW "
                     f"{cpt['bmw_tier'].replace('_', ' ')} for {cpt['item_label'].lower()}; top-5 rivals: {listed}. "
                     f"Gap score {_n2(cpt['score'])} (rival average {_n2(cpt['rival_mean'])} minus BMW "
                     f"{_n2(cpt['bmw_points'])}).", cpt["score"], node=nid("feature", f), kind="table",
                     ref="data/processed/competitor_equipment.csv + competitor_sets.csv", key=cpt["item"],
                     feature=f, series=m, market=k)
        else:
            self.add(f"{cp}.competitors", "competitor", f"Competitors {where}: no signal "
                     f"({cpt.get('status', 'no data')}).", None, node=nid("feature", f), kind="derived",
                     ref="DecisionEngine signals", feature=f, series=m, market=k)
        if c.get("action"):
            fnode = nid("fitment", f, m)
            self.add(f"{cp}.action", "price", f"Suggested move {where}: {c['action']['type']} "
                     f"(basis: {c['action']['basis']}).", c["action"]["type"],
                     node=fnode if fnode in self.g else nid("feature", f), kind="derived",
                     ref="decision._action + DE price list", feature=f, series=m, market=k)
        for j, q in enumerate((c.get("evidence") or {}).get("quotes", [])[:2], start=1):
            self.add(f"{cp}.quote{j}", "quote", f"Customer comment {q['comment_id']} ({q['feedback_type']}, "
                     f"{q['source']}, {q['country']}, reason: {q['reason']}): \"{q['text']}\"", q["text"],
                     node=nid("comment", q["comment_id"]), kind="xlsx", ref=f"{m}_feedback_hackathon.xlsx",
                     key=q["comment_id"], feature=f, series=m, market=k)

    def _price(self, p, fr):
        f = fr["feature"]
        for lad in fr["price_ladder"]:
            m = lad["model"]
            if m not in self.result["models"]:
                continue
            tier = lad.get("tier")
            fnode = nid("fitment", f, m)
            if tier in (None, "no_link"):
                self.add(f"{p}.price.{m}", "price", f"'{f}' has no curated link to the {SERIES_NAMES[m]} price list, so "
                         "its fitment and price there are unknown.", "no_link", node=nid("feature", f),
                         kind="config", ref="taxonomy.FEATURE_TO_OPTION_KEYWORDS", feature=f, series=m)
                continue
            if tier == "not_listed" or fnode not in self.g:
                listed = ", ".join(lad.get("listed_on") or []) or "no other series"
                self.add(f"{p}.price.{m}", "price", f"On the {SERIES_NAMES[m]}, '{f}' is {TIER_TEXT['not_listed']}; "
                         f"matching items are listed on: {listed}.", "not_listed", node=nid("series", m),
                         kind="pdf", ref=f"{m}_OptionList.PDF", feature=f, series=m)
                continue
            text = (f"On the {SERIES_NAMES[m]} (DE price list, July 2026), '{f}' is {TIER_TEXT.get(tier, tier)}: "
                    f"standard on {lad['n_standard']} and optional on {lad['n_optional']} of {lad['n_variants']} "
                    "variants in the equipment tables")
            if lad.get("price_min_eur"):
                pkg = " as part of a package" if lad.get("price_via_package") else ""
                text += (f"; cheapest way to get it: '{lad.get('price_item')}' from {_eur(lad['price_min_eur'])}{pkg}"
                         + (f" ({lad['price_pct_of_base']:.1f}% of that variant's base price)"
                            if lad.get("price_pct_of_base") else ""))
            self.add(f"{p}.price.{m}", "price", text + ".", tier, node=fnode, kind="pdf", ref=f"{m}_OptionList.PDF",
                     feature=f, series=m)
            if lad.get("price_min_eur"):
                self.add(f"{p}.price.{m}.min_eur", "price", f"Lowest listed price for '{f}' on the {SERIES_NAMES[m]}: "
                         f"{_eur(lad['price_min_eur'])} (incl. 19% VAT).", lad["price_min_eur"], unit="EUR",
                         node=fnode, kind="pdf", ref=f"{m}_OptionList.PDF", feature=f, series=m)
            links = sorted((v for _, v, d in self.g.out_edges(nid("feature", f), data=True)
                            if d["rel"] == "LINKED_TO" and self.g.nodes[v].get("model") == m))[:3]
            for j, o in enumerate(links, start=1):
                n = self.g.nodes[o]
                sa = f" (SA {n['sa_code']})" if n.get("sa_code") else ""
                self.add(f"{p}.price.{m}.item{j}", "price", f"Price-list item linked to '{f}' on the {SERIES_NAMES[m]}: "
                         f"'{n['name']}'{sa}, {m}_OptionList.PDF page {n['page']}.", n["name"], node=o, kind="pdf",
                         ref=f"{m}_OptionList.PDF", page=n["page"], feature=f, series=m)

    def _specs(self, p, f):
        specs = sorted(v for _, v, d in self.g.out_edges(nid("feature", f), data=True) if d["rel"] == "HAS_SPEC"
                       and self.g.nodes[v]["model"] in self.result["models"])
        seen, j = set(), 0
        for s in specs:
            n = self.g.nodes[s]
            key = (n["model"], n["attribute"])
            if key in seen:
                continue
            seen.add(key)
            j += 1
            self.add(f"{p}.spec{j}", "spec", f"Technical data, {n['model']} {n['variant']}: {n['attribute']} = "
                     f"{n['value']} ({n['model']}_OptionList.PDF page {n['prov']['page']}).", str(n["value"]),
                     node=s, kind="pdf", ref=f"{n['model']}_OptionList.PDF", page=n["prov"]["page"], feature=f,
                     series=n["model"])
            if j >= 6:
                break

    def _move(self, p, fr):
        """What the PM's proposed move means against today's DE price list, per series in scope."""
        s, f = self.spec, fr["feature"]
        if s.move == "unspecified" and not s.proposed_price_eur:
            return
        for lad in fr["price_ladder"]:
            m = lad["model"]
            if m not in self.result["models"]:
                continue
            tier, low, name = lad.get("tier") or "no_link", lad.get("price_min_eur"), SERIES_NAMES[m]
            item = lad.get("price_item")
            via = (f" via the package '{item}' (which includes other equipment)" if lad.get("price_via_package")
                   else f" ('{item}')" if item else "")
            value = tier
            if tier == "no_link":
                text = f"'{f}' has no curated link to the {name} price list, so the move cannot be checked against it."
            elif tier == "not_listed":
                listed = ", ".join(lad.get("listed_on") or [])
                text = (f"No {name} price-list item matched '{f}'" + (f"; matching items are listed on {listed}"
                                                                     if listed else "")
                        + "; on this series the move means introducing it.")
            elif s.proposed_price_eur and low:
                d = s.proposed_price_eur - low
                value = round(d, 2)
                text = (f"Proposed {_eur(s.proposed_price_eur)} vs today's lowest {_eur(low)} on the {name}{via}: "
                        f"{_eur(abs(d))} {'lower' if d < 0 else 'higher'} ({abs(d) / low * 100:.1f}% "
                        f"{'below' if d < 0 else 'above'} today).") if d else (
                    f"Proposed {_eur(s.proposed_price_eur)} equals today's lowest price on the {name}{via}.")
            elif s.proposed_price_eur:
                text = (f"There is no listed price for '{f}' on the {name} to compare the proposed "
                        f"{_eur(s.proposed_price_eur)} with: it is {TIER_TEXT.get(tier, tier)}.")
            elif s.move == "make_standard":
                text = {"standard_all": f"Making it standard changes nothing on the {name}: it is already standard "
                                        "on every variant in the equipment tables.",
                        "standard_some": f"On the {name} it is already standard on {lad.get('n_standard')} of "
                                         f"{lad.get('n_variants')} variants; making it standard affects the other "
                                         f"{lad.get('n_optional')}.",
                        "optional": f"On the {name} it is an option today" + (f" from {_eur(low)}{via}" if low else "")
                                    + "; making it standard removes that charge to customers."}.get(tier)
            elif s.move in ("new_option", "introduce_on_series"):
                text = {"standard_all": f"It is already standard on every {name} variant in the equipment tables.",
                        "standard_some": f"It is already standard on some {name} variants.",
                        "optional": f"It is already an option on the {name}" + (f" from {_eur(low)}{via}" if low
                                                                                else "") + "."}.get(tier)
            elif s.move == "price_change":
                text = (f"Today's lowest price on the {name} is {_eur(low)}{via}." if low else
                        f"There is no listed price for '{f}' on the {name}: it is {TIER_TEXT.get(tier, tier)}.")
            else:   # fix_existing
                text = (f"A fix reaches {name} customers who have it: it is {TIER_TEXT.get(tier, tier)}"
                        + (f" (standard on {lad.get('n_standard')}, optional on {lad.get('n_optional')} of "
                           f"{lad.get('n_variants')} variants)." if lad.get("n_variants") else "."))
            if text:
                fnode = nid("fitment", f, m)
                self.add(f"{p}.move.{m}", "move", text, value, node=fnode if fnode in self.g else nid("series", m),
                         kind="derived", ref=f"IdeaSpec move vs {m}_OptionList.PDF", feature=f, series=m)

    def _ebm(self, p, fr):
        f, d = fr["feature"], fr["domain"]
        term = nid("ebmterm", "domain")
        if term not in self.g:
            return
        terms = sorted((n for n in self.g.nodes if n.startswith("ebmterm:")),
                       key=lambda n: -self.g.nodes[n]["importance"])
        rank = terms.index(term) + 1
        score = next((e["score"] for _, v, e in self.g.out_edges(term, data=True)
                      if e["rel"] == "CONTRIBUTES" and v == nid("domain", d)), None)
        if score is None:
            return
        imp = self.g.nodes[term]["importance"]
        self.add(f"{p}.ebm.domain", "model", f"Complaint model (EBM): comments in the domain '{d}' get {score:+.2f} "
                 f"log-odds of being a complaint (the domain input ranks {rank} of {len(terms)} inputs by "
                 f"importance, {imp:.2f}).", score, node=term, kind="model", ref="models/complaint_risk.joblib",
                 key="reports/model_ablation.json#global_production", feature=f)

    # ------------------------------------------------------------------ shared
    def _models(self):
        g = self.g
        e = g.nodes[nid("model", "complaint_ebm")]
        self.add("model.complaint_ebm", "model", f"The complaint model (EBM on comment context) separates complaints "
                 f"from other mentions with a held-out AUC of {e['auc_mean']:.2f} (feature-grouped 5-fold CV).",
                 e["auc_mean"], node=nid("model", "complaint_ebm"), kind="model", ref="reports/model_ablation.json")
        fc = g.nodes[nid("model", "feature_classifier")]
        self.add("model.feature_classifier", "model", "The feature classifier (TF-IDF + logistic regression) ranks the "
                 f"right feature first for {fc['top1_hit'] * 100:.0f}% of held-out comments and in its top 3 for "
                 f"{fc['top3_hit'] * 100:.0f}%.", fc["top1_hit"], node=nid("model", "feature_classifier"),
                 kind="model", ref="reports/classifier_metrics.json")

    def _caveats(self):
        targets = {nid("series", m) for m in self.result["models"]} | {nid("market", k) for k in self.result["markets"]}
        targets |= {nid("feature", fr["feature"]) for fr in self.result["features"]}
        targets.add(nid("model", "complaint_ebm"))
        year = self.result["policy"]["volume_year"]
        targets |= {nid("sales", SALES_GROUP[m], k, year) for m in self.result["models"] for k in self.result["markets"]}
        seen = set()
        for c in sorted(n for n in self.g.nodes if n.startswith("caveat:")):
            hits = [v for _, v, d in self.g.out_edges(c, data=True) if d["rel"] == "QUALIFIES" and v in targets]
            if hits and c not in seen:
                seen.add(c)
                slug = c.split(":", 1)[1].replace("|", ".")
                self.add(f"caveat.{slug}", "caveat", self.g.nodes[c]["text"], None, node=c, kind="derived",
                         ref="bmw_feedback/graph/build.py")

    def _policy(self):
        pol = self.result["policy"]
        w, th = pol["weights"], pol["thresholds"]
        self.add("policy", "policy", f"Decision policy {self.result['policy_hash']}: weights complaints {w['complaints']:.2f}, "
                 f"breadth {w['breadth']:.2f}, requests {w['requests']:.2f}, survey {w['survey']:.2f}, competitors "
                 f"{w.get('competitors', 0):.2f}; 'Prioritise' "
                 f"at score >= {th['prioritise']:.2f}, 'Consider' at >= {th['consider']:.2f}; a recommendation needs "
                 f"{th['min_coverage'] * 100:.0f}% of the weighted evidence; sales year {pol['volume_year']}.",
                 self.result["policy_hash"], node=None, kind="config", ref="decision.DEFAULT_POLICY + PM overrides")
        self.add("data.version", "policy", f"Data version {self.result['data_hash']} (content hash of every file in "
                 "BMW-Data/).", self.result["data_hash"], node=None, kind="derived", ref="decision.data_fingerprint")


def build_bundle(engine, graph, spec: IdeaSpec, result: dict, candidates: list, eval_id: str) -> FactBundle:
    return FactBuilder(engine, graph, spec, result, candidates, eval_id).build()


def fact_lines(bundle: FactBundle) -> str:
    return "\n".join(f"{f.id} | {f.statement}" for f in bundle.facts)


__all__ = ["build_bundle", "evaluation_id", "fact_lines", "SERIES_NAMES", "MARKET_NAMES"]
