import { MOVE_LABELS, fmtEur, fmtInt, fmtNum, fmtPct } from "../api";
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
}: {
  evaluation: AgentEvaluation;
  feature: FeatureResult | null;
  explained: Explained | null;
  explainState: ExplainState;
  explainError: string | null;
  onExplain: () => void;
  onShowNode: (id: string) => void;
}) {
  if (!feature) return <NoEvidence evaluation={evaluation} />;
  const line = bottomLine(feature);
  const groups = groupCells(feature);
  const o = feature.overall;
  const spec = evaluation.spec;
  const numbers = citationNumbers(explained);
  const facts = new Map(evaluation.facts.map((f) => [f.id, f]));
  const s = explained?.explanation.sections ?? {};

  return (
    <div className="report">
      <section className={`report__bottom report__bottom--${line.tone}`} aria-labelledby="bottom-line">
        <p id="bottom-line" className="report__kicker">The short answer</p>
        <p className="report__answer">{line.text}</p>
        <p className="report__move">
          Your proposal: {MOVE_LABELS[spec.move] ?? spec.move}
          {spec.proposed_price_eur ? ` at ${fmtEur(spec.proposed_price_eur)}` : ""}.
        </p>
        {explainState === "done" && (s.headline ?? []).length > 0 && (
          <div className="report__headline">
            <p className="report__label">The brief in one sentence (verified)</p>
            {s.headline.map((c) => <ClaimText key={c.id} claim={c} numbers={numbers} index={facts} onShowNode={onShowNode} />)}
          </div>
        )}
      </section>

      <section aria-labelledby="where-title">
        <h3 id="where-title" className="report__h">Where to act</h3>
        <p className="report__hint">One recommendation per series and market, computed from the data. No language model is involved.</p>
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
            <dt>Priority score</dt>
            <dd>
              {feature.rollup.score === null ? "Not enough evidence for a score." : <><strong className="num">{fmtNum(feature.rollup.score)}</strong> on a scale from 0 (no reason to act) to 1 (strong reason), weighted by how many cars are sold.</>}
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

      <section aria-labelledby="brief-title">
        <div className="report__briefhead">
          <h3 id="brief-title" className="report__h">The written brief</h3>
          {explained && (
            <span className="report__verified">
              {explained.verification.n_verified} sentences checked against the data
              {explained.verification.n_removed ? `, ${explained.verification.n_removed} removed` : ""}
            </span>
          )}
        </div>
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
      </section>

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
        <span className="spinner" aria-hidden /> The brief is being written and checked. This takes about half a minute. The sections above already
        come straight from the data.
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
        <span>{state === "stale" ? "You changed the decision policy, so the numbers above were updated but the brief is out of date." : "The brief has not been written yet."}</span>
        <button className="btn btn--small" onClick={onExplain}>Write the brief</button>
      </div>
    );
  return null;
}

function NoEvidence({ evaluation }: { evaluation: AgentEvaluation }) {
  return (
    <div className="report">
      <section className="report__bottom report__bottom--unknown">
        <p className="report__kicker">The short answer</p>
        <p className="report__answer">The customer data has nothing on this idea directly, so it cannot tell you whether customers want it.</p>
        <p className="report__move">No customer comments, survey questions or price-list items match it. The closest features are below; pick one in the scope step to see their evidence.</p>
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
