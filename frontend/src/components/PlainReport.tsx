import { fmtEur, fmtInt, fmtNum, fmtPct } from "../api";
import type { AgentEvaluation, Explained, FeatureResult } from "../types";
import { ClaimText, citationNumbers } from "./claims";
import type { ExplainState } from "./ProcessFlow";
import { Verdict } from "./marks";
import { REC_INFO, REC_ORDER, VERDICT_WORDS, bottomLine, complaintWords, groupCells, marketName, seriesName } from "../plain";

// The written sections, in reading order, with plain headings. Claim text is shown exactly as verified.
const SECTIONS: { key: string; title: string; hint: string }[] = [
  { key: "customer_evidence", title: "What customers say", hint: "From customer comments and studies." },
  { key: "market_view", title: "Where it matters", hint: "Series and markets compared." },
  { key: "price_and_equipment", title: "Price and equipment today", hint: "From the German price lists, July 2026." },
  { key: "risks_and_caveats", title: "What to watch out for", hint: "Limits of the evidence." },
  { key: "next_steps", title: "What to do next", hint: "Suggested actions." },
];

export default function PlainReport({
  evaluation,
  feature,
  explained,
  explainState,
  explainError,
  onExplain,
  onShowNode,
  onOpenMetrics,
}: {
  evaluation: AgentEvaluation;
  feature: FeatureResult | null;
  explained: Explained | null;
  explainState: ExplainState;
  explainError: string | null;
  onExplain: () => void;
  onShowNode: (id: string) => void;
  onOpenMetrics: () => void;
}) {
  if (!feature) return <NoEvidence evaluation={evaluation} />;
  const line = bottomLine(feature);
  const groups = groupCells(feature);
  const o = feature.overall;
  const spec = evaluation.spec;
  const numbers = citationNumbers(explained);
  const facts = new Map(evaluation.facts.map((f) => [f.id, f]));
  const s = explained?.explanation.sections ?? {};

  const verified = explained?.verification;
  const whereSummary = REC_ORDER.filter((k) => k !== "notsold" && groups.get(k)?.length)
    .map((k) => `${REC_INFO[k].label}: ${groups.get(k)!.length}`).join(" · ");
  const metricsLink = (text: string) => (
    <button type="button" className="linkbtn" onClick={onOpenMetrics} title="Open the Metrics tab: how the priority is calculated per series and market">
      {text}
    </button>
  );

  return (
    <div className="report">
      <section className={`report__bottom report__bottom--${line.tone}`} aria-labelledby="bottom-line">
        <p id="bottom-line" className="report__kicker">Summary</p>
        <p className="report__answer">{line.text}</p>
        {spec.proposed_price_eur ? <p className="report__move">Your proposed price: {fmtEur(spec.proposed_price_eur)} (your assumption).</p> : null}
        {explainState === "done" && (s.headline ?? []).length > 0 && (
          <div className="report__headline">
            <p className="report__label">The brief in one sentence (fact-checked)</p>
            {s.headline.map((c) => <ClaimText key={c.id} claim={c} numbers={numbers} index={facts} onShowNode={onShowNode} />)}
          </div>
        )}
      </section>

      <section aria-labelledby="numbers-title">
        <h3 id="numbers-title" className="report__h">The numbers, in plain words</h3>
        <dl className="plainfacts">
          <div>
            <dt>How customers feel</dt>
            <dd>
              <Verdict verdict={o.verdict} />
              <span className="plainfacts__line">{VERDICT_WORDS[o.verdict] ?? o.verdict}, based on {fmtInt(o.n_comments)} comments.</span>
            </dd>
          </div>
          <div>
            <dt>Complaints</dt>
            <dd>{complaintWords(o)}</dd>
          </div>
          <div>
            <dt>{metricsLink("Priority score")}</dt>
            <dd>
              {feature.rollup.score === null ? "Not enough evidence for a score." : <><strong className="num">{fmtNum(feature.rollup.score)}</strong> on a scale from 0 (no reason to act) to 1 (strong reason), weighted by how many cars are sold.</>}
              {" "}{metricsLink("See how it is calculated per series and market")}
            </dd>
          </div>
          <div>
            <dt>How much is backed by data</dt>
            <dd>
              Direct evidence covers <strong className="num">{fmtPct(feature.rollup.evidence_volume_share)}</strong> of the cars sold in scope. The rest has too
              little feedback to judge.
            </dd>
          </div>
        </dl>
      </section>

      <details className="report__fold">
        <summary>
          <span className="report__foldtitle">The written brief</span>
          <span className="report__foldmeta">
            {explainState === "done" && verified
              ? `${verified.n_verified} sentences, all checked against the data${verified.n_removed ? ` (${verified.n_removed} removed)` : ""}`
              : explainState === "unavailable" ? "Not available" : explainState === "stale" ? "Out of date" : explainState === "error" ? "Failed" : "Not written yet"}
          </span>
        </summary>
        <div className="report__foldbody">
          <BriefState state={explainState} error={explainError} onExplain={onExplain} />
          {explainState === "done" && (
            <div className="briefsecs">
              {SECTIONS.filter((x) => (s[x.key] ?? []).length).map((x) => (
                <article key={x.key} className={`briefsec ${x.key === "next_steps" ? "briefsec--next" : ""}`}>
                  <h4 className="briefsec__title">{x.title}</h4>
                  <p className="briefsec__hint">{x.hint}</p>
                  <ul className="briefsec__claims">
                    {s[x.key].map((c) => (
                      <li key={c.id}>
                        <ClaimText claim={c} numbers={numbers} index={facts} onShowNode={onShowNode} />
                      </li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
          )}
          {explainState === "done" && <p className="disclaimer">The small numbers link each sentence to the facts it relies on. Click one to see the source.</p>}
        </div>
      </details>

      <details className="report__fold">
        <summary>
          <span className="report__foldtitle">Where to act</span>
          <span className="report__foldmeta">{whereSummary || "No series or market to score"}</span>
        </summary>
        <div className="report__foldbody">
          <p className="report__hint">
            One recommendation per series and market, calculated from the data with no AI. The numbers are each place's {metricsLink("priority score")} (0 to 1).
          </p>
          <div className="recgroups">
            {REC_ORDER.filter((k) => groups.get(k)?.length).map((k) => {
              const cells = groups.get(k)!;
              const info = REC_INFO[k];
              const actions = [...new Set(cells.map((c) => c.recommendation).filter((r) => r !== info.label))];
              return (
                <article key={k} className={`recgroup recgroup--${info.tone}`}>
                  <header className="recgroup__head">
                    <span className="recgroup__label">{info.label}</span>
                    <span className="recgroup__n num">{cells.length}</span>
                  </header>
                  <p className="recgroup__meaning">{info.meaning}</p>
                  <ul className="recgroup__places">
                    {cells.map((c) => (
                      <li key={`${c.model}|${c.market}`}>
                        <strong>{seriesName(c.model)}</strong> in {marketName(c.market)}
                        {c.score !== null && (k === "prioritise" || k === "consider" || k === "low") && <span className="recgroup__score num"> {fmtNum(c.score)}</span>}
                      </li>
                    ))}
                  </ul>
                  {actions.length > 0 && <p className="recgroup__action">{actions.join(" ")}</p>}
                </article>
              );
            })}
          </div>
          <p className="small">{metricsLink("Open Metrics for the evidence behind each place")}</p>
        </div>
      </details>

      <details className="report__tech">
        <summary>Technical details</summary>
        <p className="small">{feature.headline}</p>
        <p className="caption">
          Policy {evaluation.result.policy_hash}, data version {evaluation.result.data_hash}, evaluation {evaluation.evaluation_id}. Complaint index
          1.00 means as many complaints as expected for the channels the feature is discussed in. Where a market has almost no comments, the
          series' all-market verdict is borrowed at reduced weight.
        </p>
      </details>
    </div>
  );
}

function BriefState({ state, error, onExplain }: { state: ExplainState; error: string | null; onExplain: () => void }) {
  if (state === "running")
    return (
      <p className="note note--info" role="status">
        <span className="spinner" aria-hidden /> The brief is being written and fact-checked. This takes about half a minute.
      </p>
    );
  if (state === "unavailable") return <p className="note note--warn">The written brief is not available. {error}</p>;
  if (state === "error")
    return (
      <div className="note note--error row">
        <span>The brief could not be written. {error} Nothing unchecked is shown.</span>
        <button className="btn btn--small btn--dark" onClick={onExplain}>Try again</button>
      </div>
    );
  if (state === "stale" || state === "idle")
    return (
      <div className="note note--warn row">
        <span>{state === "stale" ? "You changed the decision policy, so the numbers were updated but the brief is out of date." : "The brief has not been written yet."}</span>
        <button className="btn btn--small" onClick={onExplain}>Write the brief</button>
      </div>
    );
  return null;
}

function NoEvidence({ evaluation }: { evaluation: AgentEvaluation }) {
  return (
    <div className="report">
      <section className="report__bottom report__bottom--unknown">
        <p className="report__kicker">Summary</p>
        <p className="report__answer">The customer data has nothing on this idea directly, so it cannot tell you whether customers want it.</p>
        <p className="report__move">No customer comments, survey questions or price-list items match it. The closest features are below; pick one in step 2 to see their evidence.</p>
      </section>
      <div className="tiles">
        {evaluation.candidates.slice(0, 6).map((c) => (
          <div key={c.feature} className="tile tile--static">
            <span className="tile__title">{c.feature}</span>
            <span className="caption">{c.domain}</span>
            <span className="row small" style={{ gap: 12 }}>
              <Verdict verdict={c.verdict} />
              <span className="muted num">{fmtInt(c.n_comments)} comments</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
