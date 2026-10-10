import { useState } from "react";
import type { AgentStatus } from "../types";

/** Sticky top bar: roundel, product name and agent availability. */
export default function BrandHeader({ status }: { status: AgentStatus | null }) {
  const [logo, setLogo] = useState(true);
  const ready = status?.llm_configured;
  return (
    <header className="nav">
      <div className="wrap nav__inner">
        <a href="#top" className="brand" aria-label="Product Idea Evaluation, back to the top">
          {logo ? (
            <img className="brand__logo" src="/brand/bmw-logo-colour.svg" width={30} height={30} alt="BMW" onError={() => setLogo(false)} />
          ) : (
            <span className="brand__wordmark">BMW</span>
          )}
          <span className="brand__name">Product Idea Evaluation</span>
        </a>
        {status && (
          <span className={`nav__status ${ready ? "nav__status--ok" : "nav__status--warn"}`} title={status.message ?? undefined}>
            <span className="nav__dot" aria-hidden />
            {ready
              ? `Agents ready: ${status.models.retriever} · ${status.models.explainer}`
              : "Explanation agents offline: no OpenAI key"}
          </span>
        )}
      </div>
    </header>
  );
}
