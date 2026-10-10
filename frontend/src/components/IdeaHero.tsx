import { fmtInt } from "../api";
import type { AgentStatus } from "../types";

// Ideas a PM might bring; the last one has no customer evidence in the data on purpose.
export const EXAMPLES = [
  "Make seat massage standard on the 5 Series in Europe",
  "Fix the wireless phone charger overheating",
  "Head-up display on the 1 Series for EUR 990",
  "Offer automatic doors on the 5 Series",
  "A built-in vacuum for pet hair",
];

/** Centred ask: one input, example chips, and what the answer is grounded in. */
export default function IdeaHero({
  idea,
  setIdea,
  onSubmit,
  busy,
  status,
}: {
  idea: string;
  setIdea: (v: string) => void;
  onSubmit: (text: string) => void;
  busy: boolean;
  status: AgentStatus | null;
}) {
  return (
    <section className="stage" id="top" aria-labelledby="stage-title">
      <div className="wrap stage__inner">
        <span className="stage__kicker">Customer evidence for the 1, 5 and 7 Series</span>
        <h1 id="stage-title" className="stage__title">
          Evaluate a product idea.
        </h1>
        <p className="stage__copy">
          Describe a feature idea in plain words. Three agents match it to the knowledge graph, explain the evidence for product
          management and check every sentence against the data. Each step and hand-over is shown as it happens.
        </p>
        <form
          className="stage__form"
          onSubmit={(e) => {
            e.preventDefault();
            if (idea.trim()) onSubmit(idea.trim());
          }}
        >
          <svg className="stage__glyph" aria-hidden="true" width="18" height="18" viewBox="0 0 18 18">
            <rect x="1" y="1" width="9" height="9" stroke="currentColor" strokeWidth="1.4" fill="none" />
            <rect x="8" y="8" width="9" height="9" fill="currentColor" />
          </svg>
          <label htmlFor="idea" className="sr-only">
            Your feature idea
          </label>
          <input
            id="idea"
            className="input stage__input"
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            placeholder="For example: make seat massage standard on the 5 Series in Europe"
            autoComplete="off"
            maxLength={2000}
          />
          <button className="btn stage__cta" type="submit" disabled={busy || !idea.trim()}>
            {busy ? "Working…" : "Evaluate idea"}
          </button>
        </form>
        <div className="stage__examples" role="group" aria-label="Example ideas">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              className="chip"
              disabled={busy}
              onClick={() => {
                setIdea(ex);
                onSubmit(ex);
              }}
            >
              {ex}
            </button>
          ))}
        </div>
        {status && (
          <p className="stage__meta">
            <span>{fmtInt(status.graph.nodes)} graph nodes</span>
            <span className="stage__meta-sep" aria-hidden />
            <span>{fmtInt(status.graph.edges)} edges</span>
            <span className="stage__meta-sep" aria-hidden />
            <span>
              <strong>{status.graph.checks_passed ? "All" : "Not all"} {status.graph.n_checks} integrity checks passed</strong>
            </span>
          </p>
        )}
      </div>
    </section>
  );
}
