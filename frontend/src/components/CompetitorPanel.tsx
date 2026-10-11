import { useMemo, useState } from "react";
import { fmtInt } from "../api";
import type { Claim, CompEquipment, CompPrice, CompSpec, CompTuple, CompareResult, CompetitorAnalysis, Fact, Gap } from "../types";
import { ClaimText } from "./claims";
import { marketName, seriesName } from "../plain";

// BMW against its top five competitors per series and market (Agents 4 + 5 and the deterministic comparison).
// Every number on this panel comes from the comparison the backend computed; the written part shows only
// sentences that passed verification, word for word.

export type CompState = "idle" | "loading" | "running" | "done" | "unavailable" | "error" | "nodata";

export const BRIEF_SECTIONS: { key: string; title: string }[] = [
  { key: "price_position", title: "Price position" },
  { key: "equipment", title: "Equipment for this idea" },
  { key: "product_and_sales", title: "Product and sales" },
  { key: "customer_view", title: "What customers say about the rivals" },
  { key: "implications", title: "What it means for the idea" },
  { key: "caveats", title: "Limits of this comparison" },
];

const STATUS: Record<string, { glyph: string; text: string }> = {
  standard: { glyph: "■", text: "Standard" },
  standard_some: { glyph: "■□", text: "Standard on some versions" },
  optional: { glyph: "□", text: "Option" },
  package: { glyph: "▣", text: "In a package" },
  not_available: { glyph: "×", text: "Not offered" },
  unknown: { glyph: "?", text: "Not found" },
  not_listed: { glyph: "–", text: "Not in BMW's price list" },
};
const SPEC_ROWS = ["power_kw", "accel_0_100_s", "length_mm", "wheelbase_mm", "boot_l", "range_km_wltp", "dc_charge_kw"];
export const BASIS_LABEL: Record<string, string> = {
  msrp_excl_destination: "MSRP excl. destination", msrp_incl_destination: "incl. destination", msrp: "MSRP",
  list_price: "list price", guide_price: "guide price", drive_away: "drive-away",
};
export const VOLUME_WORDS: Record<string, string> = {
  registrations: "new registrations", deliveries: "deliveries", retail: "retail sales", wholesale: "wholesale units",
  insurance_registrations: "insurance registrations", sales: "units sold",
};
const PT_LABEL: Record<string, string> = { combustion: "Combustion", "plug-in hybrid": "Plug-in hybrid", electric: "Electric" };

export const money = (v: number | null | undefined, currency: string) =>
  v === null || v === undefined ? "–" : `${currency} ${Math.round(v).toLocaleString("en-GB")}`;

export function gapText(g: Gap | null, currency: string): string {
  if (!g) return "–";
  if (g.direction === "equal") return "same";
  return `${g.abs > 0 ? "+" : "−"}${money(Math.abs(g.abs), currency)} (${g.abs > 0 ? "+" : "−"}${Math.abs(g.pct).toFixed(1)}%)`;
}

export function specRange(s: CompSpec | undefined): string {
  if (!s) return "–";
  const f = (v: number) => (s.unit === "s" || s.unit === "kWh" ? v.toFixed(1) : Math.round(v).toLocaleString("en-GB"));
  return s.min === s.max ? `${f(s.min)} ${s.unit}` : `${f(s.min)}–${f(s.max)} ${s.unit}`;
}

export function equipText(e: CompEquipment | undefined): string {
  if (!e) return "–";
  const base = STATUS[e.status]?.text ?? e.status;
  return e.price_eur ? `${base}, from EUR ${Math.round(e.price_eur).toLocaleString("en-GB")}` : base;
}

/** Citation numbers in order of first use across the competitor brief. */
export function compCitations(analysis: CompetitorAnalysis | null): Map<string, number> {
  const map = new Map<string, number>();
  const sections = analysis?.brief?.sections ?? {};
  for (const s of ["headline", ...BRIEF_SECTIONS.map((x) => x.key)])
    for (const c of sections[s] ?? []) for (const id of c.fact_ids) if (!map.has(id)) map.set(id, map.size + 1);
  return map;
}

export default function CompetitorPanel({
  compare,
  analysis,
  state,
  error,
  onRetry,
  onShowNode,
}: {
  compare: CompareResult | null;
  analysis: CompetitorAnalysis | null;
  state: CompState;
  error: string | null;
  onRetry: () => void;
  onShowNode: (id: string) => void;
}) {
  const tuples = compare?.comparison.tuples ?? [];
  const firstOk = tuples.find((t) => t.status === "ok") ?? tuples[0];
  const [key, setKey] = useState<string | null>(null);
  const t = tuples.find((x) => `${x.series}|${x.market}` === key) ?? firstOk;
  const facts = useMemo(() => new Map((compare?.facts ?? []).map((f) => [f.id, f])), [compare]);
  const numbers = useMemo(() => compCitations(analysis), [analysis]);

  if (state === "loading" && !compare)
    return (
      <section className="comp" aria-labelledby="comp-title">
        <CompHead />
        <p className="note note--info" role="status"><span className="spinner" aria-hidden /> Loading the competitor comparison…</p>
      </section>
    );
  if (!compare || !compare.available)
    return (
      <section className="comp" aria-labelledby="comp-title">
        <CompHead />
        <p className="note note--warn">
          {state === "error" ? `The competitor comparison could not be loaded: ${error}` : compare?.comparison.message ?? "No competitor data is available."}
        </p>
        {state === "error" && <button className="btn btn--small" onClick={onRetry}>Try again</button>}
      </section>
    );
  const c = compare.comparison;

  return (
    <section className="comp" aria-labelledby="comp-title">
      <CompHead comparison={c} />

      <WrittenComparison analysis={analysis} state={state} error={error} onRetry={onRetry} numbers={numbers} facts={facts} onShowNode={onShowNode} />

      <div className="chips comp__tuples" role="group" aria-label="Series and market">
        {tuples.map((x) => (
          <button key={`${x.series}|${x.market}`} type="button" className="chip chip--small" aria-pressed={x === t}
            disabled={x.status !== "ok"} title={x.status !== "ok" ? x.note ?? "No competitor set" : undefined}
            onClick={() => setKey(`${x.series}|${x.market}`)}>
            {seriesName(x.series)} · {marketName(x.market)}{x.status === "not_sold" ? " (not sold)" : ""}
          </button>
        ))}
      </div>

      {t && t.status === "ok" && t.bmw ? <TupleDetail t={t} items={c.items ?? []} /> : t ? <p className="small muted">{t.note}</p> : null}
      {(c.features_without_items ?? []).length > 0 && (
        <p className="caption">Competitor equipment is not collected for {(c.features_without_items ?? []).join(", ")}; the comparison covers prices, product, sales and reviews.</p>
      )}

      {analysis && <CompVerification analysis={analysis} />}
      {(c.sources ?? []).length > 0 && (
        <details className="comp__sources">
          <summary>Web sources used here ({c.sources!.length})</summary>
          <ul>
            {c.sources!.map((s) => (
              <li key={s.source_id}>
                <span className="comp__pub">{s.publisher}</span>{" "}
                {s.url ? <a href={s.url} target="_blank" rel="noreferrer noopener">{s.title || s.url}</a> : s.title}
                <span className="caption"> · retrieved {(s.retrieved_at ?? "").slice(0, 10)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {(c.caveats ?? []).length > 0 && (
        <ul className="comp__caveats caption">
          {c.caveats!.map((cv) => <li key={cv.id}>{cv.text}</li>)}
        </ul>
      )}
    </section>
  );
}

function CompHead({ comparison }: { comparison?: CompareResult["comparison"] }) {
  return (
    <div>
      <h3 id="comp-title" className="report__h">How BMW compares with its top five competitors</h3>
      <p className="report__hint">
        Per series and market: rivals ranked by sales in the same segment, with prices, equipment, product data and reviews from public web
        sources{comparison?.retrieved_to ? ` (retrieved ${String(comparison.retrieved_from ?? "").slice(0, 10)} to ${comparison.retrieved_to.slice(0, 10)})` : ""}.
        Prices are compared within one market and currency, never converted.
      </p>
    </div>
  );
}

function WrittenComparison({ analysis, state, error, onRetry, numbers, facts, onShowNode }: {
  analysis: CompetitorAnalysis | null; state: CompState; error: string | null; onRetry: () => void;
  numbers: Map<string, number>; facts: Map<string, Fact>; onShowNode: (id: string) => void;
}) {
  if (state === "running")
    return (
      <p className="note note--info" role="status">
        <span className="spinner" aria-hidden /> The competitor analyst is comparing the data and the presenter is writing it up; both are checked by the
        verifier. This takes about a minute. The tables below already come straight from the data.
      </p>
    );
  if (state === "unavailable") return <p className="note note--warn">The written comparison is not available. {error}</p>;
  if (state === "error")
    return (
      <div className="note note--error row">
        <span>The written comparison could not be produced. {error} Nothing unchecked is shown.</span>
        <button className="btn btn--small btn--dark" onClick={onRetry}>Try again</button>
      </div>
    );
  if (!analysis) return null;
  if (!analysis.brief) return <p className="note note--warn">{analysis.message ?? "No finding passed verification."}</p>;
  const s = analysis.brief.sections;
  const v = analysis.verification!;
  return (
    <div className="comp__brief">
      <div className="report__briefhead">
        <p className="report__label">The comparison in plain words (verified)</p>
        <span className="report__verified">
          {v.n_findings_verified} findings and {v.n_presented_verified} sentences checked against the data
          {v.n_presented_replaced ? `, ${v.n_presented_replaced} replaced by the analyst's finding` : ""}
        </span>
      </div>
      {(s.headline ?? []).map((cl) => (
        <div key={cl.id} className="comp__headline"><ClaimText claim={cl as Claim} numbers={numbers} index={facts} onShowNode={onShowNode} /></div>
      ))}
      <div className="briefsecs">
        {BRIEF_SECTIONS.filter((x) => (s[x.key] ?? []).length).map((x) => (
          <article key={x.key} className={`briefsec ${x.key === "implications" ? "briefsec--next" : ""}`}>
            <h4 className="briefsec__title">{x.title}</h4>
            <ul className="briefsec__claims">
              {s[x.key].map((cl) => (
                <li key={cl.id}>
                  <ClaimText claim={cl as Claim} numbers={numbers} index={facts} onShowNode={onShowNode} />
                  {cl.origin === "analyst_fallback" && <span className="caption"> (the analyst's finding, shown because the rewrite failed a check)</span>}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
      <p className="disclaimer">Written by {analysis.brief.model} from {analysis.analysis.findings.length} findings of {analysis.analysis.model}, in {analysis.seconds.toFixed(0)} s. The small numbers open the fact behind each statement.</p>
    </div>
  );
}

function TupleDetail({ t, items }: { t: CompTuple; items: { key: string; label: string }[] }) {
  const bmw = t.bmw!;
  const cur = t.reference.currency;
  const pr = t.summary?.price;
  const comps = t.competitors;
  return (
    <div className="stack-lg comp__tuple">
      <p className="small">
        <strong>{t.series_name} in {t.market_name}.</strong> Rivals {t.selection_rule || "as listed"}. Prices: {t.reference.country_name}, {cur}
        {t.market === "EU" ? " (BMW from its own DE price list)" : ""}.
        {pr && ` The ${seriesName(t.series)} (${pr.bmw_variant}, ${money(pr.bmw_amount, cur)}) has entry price rank ${pr.bmw_rank_from_cheapest} of ${pr.n_models} (1 = cheapest), ${gapText({ abs: pr.bmw_vs_median_abs, pct: pr.bmw_vs_median_pct, direction: pr.bmw_vs_median_abs > 0 ? "above" : pr.bmw_vs_median_abs < 0 ? "below" : "equal" }, cur)} against the rivals' median${BASIS_LABEL[pr.basis] ? ` (${BASIS_LABEL[pr.basis]})` : ""}.`}
      </p>

      {(t.set_notes ?? []).length > 0 && <p className="caption">{t.set_notes!.map((n) => n[0].toUpperCase() + n.slice(1)).join(". ")}.</p>}

      <PriceStrip t={t} />

      <div className="table-scroll">
        <table className="table comp__table">
          <caption className="sr-only">Rivals at a glance</caption>
          <thead>
            <tr><th>#</th><th>Model</th><th>Entry version</th><th className="r">Entry price</th><th className="r">vs {seriesName(t.series)}</th><th className="r">Sold</th><th>Rating</th></tr>
          </thead>
          <tbody>
            <tr className="comp__bmwrow">
              <td>–</td>
              <td><strong>{bmw.name}</strong></td>
              <td>{bmw.entry ? `${bmw.entry.variant} (${bmw.entry.powertrain})` : "–"}</td>
              <td className="r num">{money(bmw.entry?.amount, cur)}</td>
              <td className="r">–</td>
              <td className="r num">{comps.find((c) => c.bmw_sales)?.bmw_sales ? fmtInt(comps.find((c) => c.bmw_sales)!.bmw_sales!.units) : "–"}</td>
              <td>{bmw.ratings.map((r) => `${r.score}/${r.scale_max} ${r.publisher ?? ""}`).join("; ") || "–"}</td>
            </tr>
            {comps.map((c) => (
              <tr key={c.model_id}>
                <td className="num">{c.rank}</td>
                <td>
                  <strong>{c.name}</strong>
                  {c.basis === "rival_mentions" && <span className="caption"> named rival</span>}
                </td>
                <td>{c.entry ? `${c.entry.variant} (${c.entry.powertrain})` : <span className="muted">no {t.reference.country_name} price found</span>}</td>
                <td className="r num">{money(c.entry?.amount, cur)}</td>
                <td className="r num">
                  {gapText(c.gap, cur)}
                  {c.gap && c.bmw_ref && bmw.entry && (c.bmw_ref.basis !== bmw.entry.basis || c.bmw_ref.variant !== bmw.entry.variant) && (
                    <span className="caption comp__basis">vs {c.bmw_ref.variant} {money(c.bmw_ref.amount, cur)}{BASIS_LABEL[c.bmw_ref.basis] ? `, ${BASIS_LABEL[c.bmw_ref.basis]}` : ""}</span>
                  )}
                </td>
                <td className="r num" title={c.sales ? `${c.sales.region} ${c.sales.year}, ${c.sales.source?.publisher ?? ""}` : undefined}>
                  {c.sales ? `${fmtInt(c.sales.units)}` : "–"}
                </td>
                <td>{c.ratings.map((r) => `${r.score}/${r.scale_max} ${r.publisher ?? ""}`).join("; ") || "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {comps.some((c) => c.sales) && (
          <p className="caption">
            Sold: {VOLUME_WORDS[comps.find((c) => c.sales)?.sales?.basis ?? ""] ?? "units sold"} in {comps.find((c) => c.sales)?.sales?.region} in {comps.find((c) => c.sales)?.sales?.year}
            {comps.find((c) => c.sales)?.sales?.segment_text ? `, segment '${comps.find((c) => c.sales)?.sales?.segment_text}'` : ""}; the BMW row is from the same source where one exists.
          </p>
        )}
      </div>

      {items.length > 0 && (
        <div>
          <h4 className="comp__h">Equipment for this idea (German market)</h4>
          <div className="table-scroll">
            <table className="table comp__table">
              <thead>
                <tr><th>Item</th><th>{seriesName(t.series)}</th>{comps.map((c) => <th key={c.model_id}>{c.name}</th>)}</tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.key}>
                    <td>{it.label}</td>
                    <td><EquipCell e={bmw.equipment[it.key]} /></td>
                    {comps.map((c) => <td key={c.model_id}><EquipCell e={c.equipment[it.key]} /></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="caption">■ standard · ■□ standard on some versions · □ option · ▣ only in a package · × not offered · ? not found in the collected data. EUR incl. 19% VAT.
            {(t.old_equipment_lists ?? []).length > 0 && ` From price lists published before 2025, so current equipment may differ: ${t.old_equipment_lists!.join(", ")}.`}</p>
        </div>
      )}

      <div>
        <h4 className="comp__h">Product</h4>
        <div className="table-scroll">
          <table className="table comp__table">
            <thead>
              <tr><th>Attribute</th><th>{seriesName(t.series)}</th>{comps.map((c) => <th key={c.model_id}>{c.name}</th>)}</tr>
            </thead>
            <tbody>
              {SPEC_ROWS.filter((k) => bmw.specs[k] || comps.some((c) => c.specs[k])).map((k) => (
                <tr key={k}>
                  <td>{(bmw.specs[k] ?? comps.find((c) => c.specs[k])?.specs[k])?.label}</td>
                  <td className="num">{specRange(bmw.specs[k])}</td>
                  {comps.map((c) => <td key={c.model_id} className="num">{specRange(c.specs[k])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="caption">Ranges over the variants recorded; BMW values from its DE price list (technical data), rivals from manufacturer and catalogue pages.</p>
      </div>

      <PowertrainPrices t={t} />

      <div>
        <h4 className="comp__h">What reviewers say</h4>
        <div className="comp__voices">
          {[{ name: bmw.name, model_id: bmw.model_id, reviews: bmw.reviews }, ...comps].filter((x) => x.reviews.n > 0).map((x) => (
            <article key={x.model_id} className="comp__voice">
              <p className="comp__voice-name">{x.name}</p>
              <p className="caption">
                {x.reviews.n} statements ({(x.reviews.publishers ?? []).join(", ")}): {x.reviews.positive} praise, {x.reviews.negative} criticism
                {x.reviews.unassigned ? `; ${x.reviews.unassigned} without a confident topic` : ""}
              </p>
              {(x.reviews.top_praise ?? []).length > 0 && <p className="small">Praised: {x.reviews.top_praise!.map(([d, n]) => `${d} (${n})`).join(", ")}</p>}
              {(x.reviews.top_criticism ?? []).length > 0 && <p className="small">Criticised: {x.reviews.top_criticism!.map(([d, n]) => `${d} (${n})`).join(", ")}</p>}
              {(x.reviews.quotes ?? []).slice(0, 2).map((q, i) => (
                <blockquote key={i} className={`comp__quote comp__quote--${q.sentiment}`}>“{q.text}”<span className="caption"> {q.source?.publisher}</span></blockquote>
              ))}
            </article>
          ))}
          {![bmw, ...comps].some((x) => x.reviews.n > 0) && <p className="small muted">No review statements were collected for this market.</p>}
        </div>
        <p className="caption">Topics are assigned by the domain classifier trained on BMW customer comments, only where it is at least 50% confident (the BMW pipeline's own rule); counts are small and not a survey.</p>
      </div>
    </div>
  );
}

function EquipCell({ e }: { e: CompEquipment | undefined }) {
  if (!e) return <span className="muted">–</span>;
  const s = STATUS[e.status] ?? { glyph: "", text: e.status };
  const scope = e.status === "standard_some" && e.variant_scope ? ` (${e.variant_scope})` : "";
  return (
    <span className="comp__eq" title={`${s.text}${scope}${e.price_item ? `: ${e.price_item}` : ""}${e.publisher ? ` (${e.publisher}${e.rows?.[0]?.note ? `; ${e.rows[0].note}` : ""})` : ""}`}>
      <span className="fit" aria-hidden>{s.glyph}</span>
      <span>
        {s.text}
        {e.price_eur ? <span className="num"> EUR {Math.round(e.price_eur).toLocaleString("en-GB")}</span> : null}
      </span>
    </span>
  );
}

function PowertrainPrices({ t }: { t: CompTuple }) {
  const cur = t.reference.currency;
  const rows = t.competitors.flatMap((c) => c.by_powertrain.filter((r) => r.competitor).map((r) => ({ c, r })));
  if (!rows.length) return null;
  return (
    <details>
      <summary>Cheapest version per powertrain ({rows.length})</summary>
      <div className="table-scroll" style={{ marginTop: 12 }}>
        <table className="table comp__table">
          <thead><tr><th>Model</th><th>Powertrain</th><th>Version</th><th className="r">Price</th><th>{seriesName(t.series)} counterpart</th><th className="r">Gap</th></tr></thead>
          <tbody>
            {rows.map(({ c, r }) => (
              <tr key={`${c.model_id}|${r.group}`}>
                <td>{c.name}</td>
                <td>{PT_LABEL[r.group] ?? r.group}</td>
                <td>{r.competitor!.variant}</td>
                <td className="r num">{money(r.competitor!.amount, cur)}</td>
                <td>{r.bmw ? `${r.bmw.variant}, ${money(r.bmw.amount, cur)}` : <span className="muted">none in the data</span>}</td>
                <td className="r num">{gapText(r.gap, cur)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** Entry prices of BMW and its rivals on one axis (same market and currency). */
function PriceStrip({ t }: { t: CompTuple }) {
  const cur = t.reference.currency;
  const pts: { name: string; p: CompPrice; bmw: boolean }[] = [];
  const basis = t.bmw?.entry?.basis;
  if (t.bmw?.entry) pts.push({ name: seriesName(t.series), p: t.bmw.entry, bmw: true });
  for (const c of t.competitors) if (c.entry && c.gap && c.entry.basis === basis) pts.push({ name: c.name, p: c.entry, bmw: false });
  if (pts.length < 2) return null;
  const W = 720, H = 30 + pts.length * 18, L = 16, R = 16;
  const vals = pts.map((x) => x.p.amount);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.08 || hi * 0.05;
  const x = (v: number) => L + ((v - (lo - pad)) / (hi + pad - (lo - pad))) * (W - L - R);
  const sorted = [...pts].sort((a, b) => a.p.amount - b.p.amount);
  return (
    <figure className="comp__strip">
      <figcaption className="caption">Entry prices, {t.reference.country_name}, {cur}{basis && BASIS_LABEL[basis] ? `, ${BASIS_LABEL[basis]}` : ""} (cheapest version of each model on the same price basis)</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Entry prices: ${sorted.map((d) => `${d.name} ${money(d.p.amount, cur)}`).join(", ")}`}>
        <line x1={L} x2={W - R} y1={H - 14} y2={H - 14} stroke="var(--border)" strokeWidth={1} />
        {sorted.map((d, i) => {
          const cx = x(d.p.amount);
          const y = 14 + i * 18;
          const right = cx < W * 0.6;
          return (
            <g key={d.name}>
              <line x1={cx} x2={cx} y1={y} y2={H - 14} stroke="var(--border)" strokeWidth={1} strokeDasharray="2 3" />
              <circle cx={cx} cy={y} r={d.bmw ? 6 : 5} fill={d.bmw ? "var(--cta)" : "#667085"} stroke="#fff" strokeWidth={2}>
                <title>{`${d.name} ${d.p.variant}: ${money(d.p.amount, cur)}`}</title>
              </circle>
              <text x={right ? cx + 10 : cx - 10} y={y + 4} textAnchor={right ? "start" : "end"} fontSize={12}
                fill="var(--copy-text)" fontWeight={d.bmw ? 600 : 400}>
                {d.name} · {money(d.p.amount, cur)}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

function CompVerification({ analysis }: { analysis: CompetitorAnalysis }) {
  const a = analysis.analysis;
  const v = analysis.verification;
  const all: (Claim & { series?: string; market?: string; origin?: string })[] = [...a.findings, ...a.removed];
  if (!all.length) return null;
  return (
    <details className="comp__verify">
      <summary>How the comparison was checked ({a.findings.length} findings verified, {a.removed.length} removed{v ? `; ${v.n_presented_verified} sentences verified, ${v.n_presented_replaced} replaced` : ""})</summary>
      <p className="caption" style={{ marginTop: 8 }}>
        The analyst ({a.model}) writes findings that cite facts; rules check citations, numbers, labels, quotes, series and markets, that each finding
        cites a fact of its series, market and kind, and {v?.semantic_model ?? "a second model"} judges whether the facts support it. A failing finding is
        rewritten once, then removed. The presenter's sentences are checked the same way; a failing sentence is replaced by the findings it was based on.
      </p>
      <div className="table-scroll">
        <table className="table comp__table">
          <thead><tr><th>Status</th><th>Where</th><th>Finding</th><th>Failed checks</th></tr></thead>
          <tbody>
            {all.map((f) => (
              <tr key={f.id}>
                <td><span className={`pill ${f.status === "verified" ? "pill--success" : "pill--error"}`}>{f.status === "verified" ? "Verified" : "Removed"}</span></td>
                <td className="caption">{f.series ? `${seriesName(f.series)} · ${marketName(f.market ?? "")}` : ""} · {f.section}</td>
                <td className={f.status === "removed" ? "muted" : ""}>{f.text}</td>
                <td className="caption">{f.checks.filter((ch) => !ch.passed).map((ch) => `${ch.name}: ${ch.detail}`).join(" ") || "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

