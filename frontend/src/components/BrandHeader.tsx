import { useState } from "react";
import type { AgentStatus } from "../types";

export type View = "evaluate" | "tracker" | "about";

const VIEW_LABEL: Record<View, string> = { evaluate: "Evaluate", tracker: "Tracker", about: "About" };

/** Top bar: roundel, product name, the views (Tracker shows how many decisions need review) and agent availability. */
export default function BrandHeader({ status, view, onView, toReview = 0 }: {
  status: AgentStatus | null;
  view: View;
  onView: (v: View) => void;
  toReview?: number;
}) {
  const [logo, setLogo] = useState(true);
  const ready = status?.llm_configured;
  return (
    <header className="nav">
      <div className="nav__inner">
        <span className="brand">
          {logo ? (
            <img className="brand__logo" src="/brand/bmw-logo-colour.svg" width={30} height={30} alt="BMW" onError={() => setLogo(false)} />
          ) : (
            <span className="brand__wordmark">BMW</span>
          )}
          <span className="brand__name">Product Idea Evaluation</span>
        </span>
        <nav className="nav__views" aria-label="Views">
          {(["evaluate", "tracker", "about"] as const).map((v) => (
            <button key={v} type="button" className="nav__view" aria-current={view === v ? "page" : undefined} onClick={() => onView(v)}>
              {VIEW_LABEL[v]}
              {v === "tracker" && toReview > 0 && <span className="nav__badge">{toReview} to review</span>}
            </button>
          ))}
        </nav>
        {status && (
          <span className={`nav__status ${ready ? "nav__status--ok" : "nav__status--warn"}`} title={status.message ?? undefined}>
            <span className="nav__dot" aria-hidden />
            {ready ? `Agents ready: ${status.models.retriever}, ${status.models.explainer}` : "Explanation agents offline: no OpenAI key"}
          </span>
        )}
      </div>
    </header>
  );
}
