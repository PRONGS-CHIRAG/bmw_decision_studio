import { MARKET_NAMES, MOVE_LABELS, SERIES_LABELS, fmtInt, fmtNum } from "../api";
import type { Candidate, IdeaSpec, InterpretResult, Move } from "../types";
import { Verdict } from "./marks";

const MAX_FEATURES = 3;
const METHOD_NAMES: Record<string, string> = { name_or_alias: "name / alias", classifier: "classifier", semantic: "semantic" };

/** Step 1 output, editable: the PM confirms what the retriever read before anything is evaluated. */
export default function SpecReview({
  interp,
  draft,
  setDraft,
  onEvaluate,
  busy,
}: {
  interp: InterpretResult;
  draft: IdeaSpec;
  setDraft: (s: IdeaSpec) => void;
  onEvaluate: () => void;
  busy: boolean;
}) {
  const chosen = new Set(draft.features.map((f) => f.feature));
  const failed = interp.attempts.filter((a) => !a.ok);
  const byLLM = interp.method.startsWith("llm:");

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
    <div className="review stack-lg">
      <div className="stack">
        <p className="eyebrow">Step 1 · Retriever agent</p>
        <h2 className="section-title">Is this what you want to evaluate?</h2>
        <p className="lead">{draft.summary}</p>
        <p className="caption">
          {byLLM ? `Read by ${interp.method.slice(4)}` : "Read by transparent rules (no language model)"}. Candidates come from feature
          names and aliases, the trained feature classifier and the {interp.semantic_method} index over the knowledge graph;{" "}
          {byLLM
            ? "the agent may only choose among them and its answer is validated before you see it."
            : "features matched with a score of 0.5 or more are preselected. Set OPENAI_API_KEY to let the retriever agent read the idea."}
        </p>
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
          Features in the customer data <span className="caption">choose up to {MAX_FEATURES}</span>
        </legend>
        {interp.candidates.length === 0 && <p className="small muted">No candidate features were found.</p>}
        <div className="tiles">
          {interp.candidates.map((c) => (
            <button
              key={c.feature}
              type="button"
              className="tile"
              aria-pressed={chosen.has(c.feature)}
              onClick={() => toggleFeature(c)}
              disabled={!chosen.has(c.feature) && draft.features.length >= MAX_FEATURES}
            >
              <span className="spread">
                <span className="tile__title">{c.feature}</span>
                {chosen.has(c.feature) && <span className="tile__check" aria-hidden />}
              </span>
              <span className="caption">{c.domain}</span>
              <span className="row small" style={{ gap: 12 }}>
                <Verdict verdict={c.verdict} />
                <span className="muted num">{fmtInt(c.n_comments)} comments</span>
              </span>
              <span className="tile__methods">
                {Object.entries(c.methods).map(([k, v]) => (
                  <span key={k} className="method">
                    {METHOD_NAMES[k] ?? k} <span className="num">{fmtNum(v)}</span>
                  </span>
                ))}
              </span>
              {c.umbrella && <span className="caption">Umbrella label: general praise is filed here.</span>}
            </button>
          ))}
        </div>
        {draft.features.length === 0 && (
          <p className="note note--info">
            No feature selected: the idea is evaluated as <strong>new to the data</strong>. The brief will say what the data cannot
            tell you and show the nearest features.
          </p>
        )}
      </fieldset>

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
          <label htmlFor="move">Proposed move</label>
          <select id="move" className="select" value={draft.move} onChange={(e) => setDraft({ ...draft, move: e.target.value as Move })}>
            {Object.entries(MOVE_LABELS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </div>
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
          {busy ? "Evaluating…" : "Evaluate this idea"}
        </button>
        <span className="caption measure">
          The decision engine computes every number from the processed data and model outputs. No language model is involved in this step.
        </span>
      </div>
    </div>
  );
}
