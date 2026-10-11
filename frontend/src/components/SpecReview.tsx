import { useState } from "react";
import { MARKET_NAMES, SERIES_LABELS, fmtInt } from "../api";
import type { Candidate, IdeaSpec, InterpretResult } from "../types";
import { CalcPopup, VerdictDial, VerdictLabel } from "./VerdictCalc";
import { complaintReason } from "../plain";

const MAX_FEATURES = 3;
/** Step 1 output, editable: the PM confirms what the retriever read before anything is evaluated. */
export default function SpecReview({
  interp,
  draft,
  setDraft,
  onEvaluate,
  busy,
  compact = false,
  confirmed = false,
}: {
  interp: InterpretResult;
  draft: IdeaSpec;
  setDraft: (s: IdeaSpec) => void;
  onEvaluate: () => void;
  busy: boolean;
  compact?: boolean;
  confirmed?: boolean;
}) {
  const chosen = new Set(draft.features.map((f) => f.feature));
  const failed = interp.attempts.filter((a) => !a.ok);
  const byLLM = interp.method.startsWith("llm:");
  const suggested = new Set(interp.spec.features.map((f) => f.feature));
  const [calc, setCalc] = useState<Candidate | null>(null);

  function toggleFeature(c: Candidate) {
    let features = draft.features;
    if (chosen.has(c.feature)) features = features.filter((f) => f.feature !== c.feature);
    else if (features.length < MAX_FEATURES)
      features = [...features, { feature: c.feature, node_id: c.node_id, reason: "selected by the PM", methods: c.methods }];
    else return;
    const novelty = features.length === 0 ? "new_to_data" : draft.novelty === "new_to_data" ? "related_only" : draft.novelty;
    setDraft({ ...draft, features, novelty });
  }
  const toggle = (key: "series" | "markets", v: string) =>
    setDraft({ ...draft, [key]: draft[key].includes(v) ? draft[key].filter((x) => x !== v) : [...draft[key], v] });

  return (
    <div className={`review stack-lg ${compact ? "review--compact" : ""}`}>
      <div className="stack">
        {!compact && <p className="eyebrow">Step 1 · Retriever agent</p>}
        {!compact && <h2 className="section-title">Which customer topics should we check your idea against?</h2>}
        {compact && <p className="small muted">We found these topics in existing customer feedback that relate to your idea. The suggested ones are ticked.
          Pick up to {MAX_FEATURES}, choose where to look, then run the check.</p>}
        <p className="lead">{draft.summary}</p>
        {!compact && <p className="caption">
          {byLLM ? `Read by ${interp.method.slice(4)}` : "Read by transparent rules (no language model)"}. Candidates come from feature
          names and aliases, the trained feature classifier and the {interp.semantic_method} index over the knowledge graph;{" "}
          {byLLM
            ? "the agent may only choose among them and its answer is validated before you see it."
            : "features matched with a score of 0.5 or more are preselected. Set OPENAI_API_KEY to let the retriever agent read the idea."}
        </p>}
        {failed.length > 0 && (
          <p className="note note--warn">
            <strong>Validation caught {failed.length} invalid answer{failed.length > 1 ? "s" : ""}.</strong>{" "}
            {failed[0].errors.slice(0, 2).join(" ")}{" "}
            {interp.attempts.some((a) => a.ok) ? "The agent corrected it." : "The rules below were used instead."}
          </p>
        )}
        {interp.semantic_error && <p className="note">{interp.semantic_error}</p>}
      </div>

      <fieldset className="review__group">
        <legend className="review__legend">
          Related topics customers talk about <span className="caption">choose up to {MAX_FEATURES}</span>
        </legend>
        <p className="caption">Each topic shows what customers think of it today. Green: the percentage is how many fewer complaints it gets than a
          typical topic, so higher is better. Red: how many more complaints, so higher is worse.</p>
        {interp.candidates.length === 0 && <p className="small muted">Nothing related was found in the customer feedback.</p>}
        <div className="tiles">
          {interp.candidates.map((c) => (
            <div key={c.feature} className="tilebox">
            <button
              type="button"
              className="tile"
              aria-pressed={chosen.has(c.feature)}
              onClick={() => toggleFeature(c)}
              disabled={!chosen.has(c.feature) && draft.features.length >= MAX_FEATURES}
            >
              <span className="tile__split">
                <span className="tile__text">
                  <span className="row" style={{ gap: 8 }}>
                    {chosen.has(c.feature) && <span className="tile__check" aria-hidden />}
                    <span className="tile__title">{c.feature}</span>
                  </span>
                  <span className="caption">{c.domain}</span>
                  <span className="tile__verdict"><VerdictLabel verdict={c.verdict} /></span>
                  <span className="tile__why">{c.verdict === "Not enough data" ? "Too few comments to judge" : complaintReason(c.complaint_index)}</span>
                  <span className="caption num">Based on {fmtInt(c.n_comments)} customer comments</span>
                  {suggested.has(c.feature) && <span className="tile__tag">Suggested</span>}
                  {c.umbrella && <span className="caption">General praise is also filed here.</span>}
                </span>
                <VerdictDial c={c} />
              </span>
            </button>
            <button type="button" className="linkbtn tile__how" onClick={() => setCalc(c)} aria-haspopup="dialog">
              How is this calculated?
            </button>
            </div>
          ))}
        </div>
        {draft.features.length === 0 && (
          <p className="note note--info">
            No feature selected: the idea is evaluated as <strong>new to the data</strong>. The brief will say what the data cannot
            tell you and show the nearest features.
          </p>
        )}
      </fieldset>

      {calc && <CalcPopup c={calc} rule={interp.verdict_rule} onClose={() => setCalc(null)} />}

      <div className="review__grid">
        <fieldset className="review__group">
          <legend className="review__legend">
            Series <span className="caption">none selected = all</span>
          </legend>
          <div className="chips">
            {Object.entries(SERIES_LABELS).map(([k, label]) => (
              <button key={k} type="button" className="chip" aria-pressed={draft.series.includes(k)} onClick={() => toggle("series", k)}>
                {label}
              </button>
            ))}
          </div>
        </fieldset>
        <fieldset className="review__group">
          <legend className="review__legend">
            Markets <span className="caption">none selected = all</span>
          </legend>
          <div className="chips">
            {Object.entries(MARKET_NAMES).map(([k, label]) => (
              <button key={k} type="button" className="chip" aria-pressed={draft.markets.includes(k)} onClick={() => toggle("markets", k)}>
                {label}
              </button>
            ))}
          </div>
        </fieldset>
        <div className="field">
          <label htmlFor="price">Proposed price (EUR, optional)</label>
          <input
            id="price"
            className="input num"
            type="number"
            min={1}
            step={10}
            inputMode="numeric"
            value={draft.proposed_price_eur ?? ""}
            onChange={(e) => setDraft({ ...draft, proposed_price_eur: e.target.value === "" ? null : Number(e.target.value) })}
            placeholder="e.g. 990"
          />
        </div>
      </div>

      {draft.ambiguities.length > 0 && (
        <div className="note note--info">
          <strong>Please check:</strong>
          <ul className="bullets">
            {draft.ambiguities.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="row">
        <button className="btn" type="button" onClick={onEvaluate} disabled={busy}>
          {busy ? "Checking…" : confirmed ? "Check again with these changes" : "Check against the data"}
        </button>
        <span className="caption measure">
          Next, every number is calculated from the customer data, studies and sales. No AI is involved in that step.
        </span>
      </div>
    </div>
  );
}
