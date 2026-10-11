import { fmtInt, fmtNum, fmtPct } from "../api";
import type { Cell, Fitment, Signal } from "../types";
import { Meter, Recommendation, Verdict, tierLabel } from "./marks";

const SIGNAL_NAMES: Record<string, string> = {
  complaints: "Complaints",
  breadth: "Breadth",
  requests: "Requests",
  survey: "Survey weakness",
  competitors: "Competitors",
};

export default function EvidencePanel({ cell, fitment }: { cell: Cell; fitment?: Fitment }) {
  const sold = cell.recommendation !== "Not sold";
  return (
    <aside className="evidence" aria-live="polite">
      <div className="stack">
        <div>
          <h3>
            {cell.model_name} in {cell.market_name}
          </h3>
          <div className="row" style={{ marginTop: 8 }}>
            <Recommendation value={cell.recommendation} />
            {cell.score !== null && sold && (
              <span className="small num">
                Score <strong>{fmtNum(cell.score)}</strong> with {Math.round(cell.coverage * 100)}% of the weighted evidence
              </span>
            )}
          </div>
        </div>

        <dl className="kv">
          {Object.entries(cell.sales)
            .sort(([a], [b]) => Number(a) - Number(b))
            .map(([year, v]) => (
              <Fragmentish key={year} k={`Sales ${year}${year === "2030" ? " (forecast)" : ""}`} v={`${fmtInt(v)} units`} />
            ))}
        </dl>
        {cell.sales_note && <p className="caption">{cell.sales_note} (sales_volumes.xlsx, sheet G60_G68).</p>}

        {!sold && <p className="note">{cell.reasons[0]}</p>}

        {sold && (
          <>
            <table className="table signals">
              <caption className="sr-only">Evidence signals and their weights</caption>
              <thead>
                <tr>
                  <th>Signal</th>
                  <th>Score</th>
                  <th className="r">Weight</th>
                  <th className="r">Share of score</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(cell.signals).map(([k, s]) => (
                  <tr key={k}>
                    <td>
                      <strong>{SIGNAL_NAMES[k] ?? k}</strong>
                      <div className="caption">{signalDetail(k, s)}</div>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                        <Meter value={s.score} width={72} label={SIGNAL_NAMES[k]} />
                        <span className="num small">{s.score === null ? "missing" : fmtNum(s.score)}</span>
                      </div>
                    </td>
                    <td className="r num small">
                      {fmtNum(s.effective_weight)}
                      {s.effective_weight !== s.weight && <div className="caption">of {fmtNum(s.weight)}</div>}
                    </td>
                    <td className="r num small">{s.contribution === null ? "–" : fmtNum(s.contribution)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="stack">
              <h4>Why</h4>
              <ul className="reasons">
                {cell.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>

            {cell.action && (
              <div className="stack">
                <h4>Suggested move</h4>
                <p className="small">
                  <strong>{cell.action.type}</strong>
                </p>
                <p className="caption">
                  {tierLabel(cell.action.tier)}. Basis: {cell.action.basis}.
                </p>
                {cell.market === "EU" && fitment && fitment.items.length > 0 && (
                  <ul className="items">
                    {fitment.items.map((it, i) => (
                      <li key={i} className="small">
                        {it.name}
                        {it.sa_code && <span className="muted"> SA {it.sa_code}</span>}
                        <span className="caption">
                          {" "}
                          {cell.model}_OptionList.PDF p.{it.page}, matched “{it.matched_keyword.replace(/^re:/, "")}” in the {it.matched_in}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {cell.signals.survey?.attributes && (
              <div className="stack">
                <h4>
                  Customer study: {cell.signals.survey.sheet}, {cell.signals.survey.survey_model}
                </h4>
                {cell.signals.survey.note && <p className="caption">{cell.signals.survey.note}</p>}
                <table className="table">
                  <thead>
                    <tr>
                      <th>Attribute</th>
                      <th className="r">Rank</th>
                      <th className="r">{cell.market === "US" ? "Top-2 box" : "Mean (0–10)"}</th>
                      <th className="r">Model average</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cell.signals.survey.attributes.map((a) => (
                      <tr key={a.attribute}>
                        <td>{a.attribute}</td>
                        <td className="r num">
                          {a.rank} of {a.of}
                        </td>
                        <td className="r num">{a.top2_box !== undefined ? fmtPct(a.top2_box) : fmtNum(a.mean)}</td>
                        <td className="r num">{a.model_mean_top2 !== undefined ? fmtPct(a.model_mean_top2) : fmtNum(a.model_mean)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {cell.evidence.quotes && cell.evidence.quotes.length > 0 && (
              <div className="stack">
                <h4>What customers in this market say</h4>
                {cell.evidence.quotes.map((q) => (
                  <blockquote key={q.comment_id} className="quote">
                    <p>“{q.text}”</p>
                    <p className="caption">
                      Comment {q.comment_id}, {q.feedback_type}, {q.source}, {q.country}. Reason: {q.reason}
                    </p>
                  </blockquote>
                ))}
              </div>
            )}

            {(cell.evidence.n_comment_ids ?? 0) > 0 && (
              <details>
                <summary>
                  {cell.evidence.n_comment_ids} comment IDs behind this cell
                  {(cell.evidence.n_comment_ids ?? 0) > (cell.evidence.comment_ids?.length ?? 0) ? " (first 40 shown)" : ""}
                </summary>
                <p className="caption num" style={{ marginTop: 8, wordBreak: "break-word" }}>
                  {cell.evidence.comment_ids?.join(", ")}
                </p>
              </details>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

function Fragmentish({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt>{k}</dt>
      <dd className="num">{v}</dd>
    </>
  );
}

function signalDetail(kind: string, s: Signal): React.ReactNode {
  if (s.score === null && kind !== "survey") return s.status;
  if (kind === "complaints") {
    const where = s.level === "borrowed" ? `borrowed (${s.n_comments_market} comment${s.n_comments_market === 1 ? "" : "s"} in this market); ` : "";
    return (
      <>
        {where}
        <Verdict verdict={s.verdict ?? ""} /> index {fmtNum(s.complaint_index)} (CI {fmtNum(s.ci_low)}–{fmtNum(s.ci_high)}),{" "}
        {s.observed} vs {fmtNum(s.expected, 1)} expected, {s.n_comments} comments
      </>
    );
  }
  if (kind === "requests") {
    const where = s.level === "borrowed" ? "borrowed; " : "";
    return `${where}index ${fmtNum(s.request_index)}, ${s.observed} vs ${fmtNum(s.expected, 1)} expected${s.requested ? ", a significant unmet need" : ""}`;
  }
  if (kind === "breadth") {
    return `${fmtInt(s.n_comments)} of ${fmtInt(s.model_comments)} comments on this model (all markets)${
      s.rank_among_features ? `, rank ${s.rank_among_features} of ${s.n_features} features` : ""
    }`;
  }
  if (kind === "competitors") {
    const offer = (s.rivals ?? []).filter((r) => ["standard", "standard_some", "optional", "package"].includes(r.status));
    const std = offer.filter((r) => r.status.startsWith("standard"));
    return `${s.basis}: ${offer.length} of ${s.n_known} rivals with data offer ${s.item_label?.toLowerCase()} (${std.length} as standard: ${
      std.map((r) => r.name).join(", ") || "none"}); BMW ${s.bmw_tier?.replace(/_/g, " ")}`;
  }
  if (kind === "survey") {
    if (s.score === null) return s.status;
    const worst = [...(s.attributes ?? [])].sort((a, b) => b.weakness - a.weakness)[0];
    return worst ? `${worst.attribute}: rank ${worst.rank} of ${worst.of}` : s.status;
  }
  return s.status;
}
