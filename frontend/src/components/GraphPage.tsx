import { useEffect } from "react";
import { createPortal } from "react-dom";
import type { AgentEvaluation } from "../types";
import EvidenceGraph from "./EvidenceGraph";

/**
 * The knowledge graph on a page of its own, over the workspace. The workspace stays mounted underneath,
 * so closing it (button, Esc or the browser's Back) returns to the report exactly as it was.
 */
export default function GraphPage({
  evaluation,
  focus,
  onFocus,
  onClose,
  onExport,
  exporting,
  exportError,
}: {
  evaluation: AgentEvaluation;
  focus: string | null;
  onFocus: (id: string | null) => void;
  onClose: () => void;
  onExport: () => void;
  exporting: boolean;
  exportError: string | null;
}) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  return createPortal(
    <div className="gpage" role="dialog" aria-modal="true" aria-labelledby="gpage-title">
      <header className="gpage__bar">
        <button type="button" className="btn btn--outline btn--small" onClick={onClose} autoFocus>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
            <path d="M10 3 5 8l5 5" />
          </svg>
          Back to the report
        </button>
        <div className="gpage__titles">
          <h1 id="gpage-title" className="gpage__title">Knowledge graph</h1>
          <p className="gpage__idea" title={evaluation.spec.idea}>{evaluation.spec.idea}</p>
        </div>
        <button type="button" className="btn btn--small" onClick={onExport} disabled={exporting}>
          {exporting ? "Preparing PDF…" : "Export report as PDF"}
        </button>
      </header>
      {exportError && <p className="note note--error small gpage__error">The PDF could not be created: {exportError}</p>}
      <div className="gpage__body">
        <EvidenceGraph evaluation={evaluation} focus={focus} onFocus={onFocus} full />
      </div>
    </div>,
    document.body,
  );
}
