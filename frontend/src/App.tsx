import { fmtInt, useApi } from "./api";
import type { AgentStatus } from "./types";
import BrandHeader from "./components/BrandHeader";
import IdeaEvaluation from "./pages/IdeaEvaluation";

export default function App() {
  const { data: status } = useApi<AgentStatus>("/api/agent/status");
  return (
    <>
      <BrandHeader status={status} />
      <main>
        <IdeaEvaluation status={status} />
      </main>
      <footer className="footer">
        <div className="wrap footer__grid">
          <div className="stack">
            <h3 className="footer__title">Data</h3>
            <p className="small">Customer feedback exports for the 1, 5 and 7 Series, customer studies 2025, sales volumes 2024–2030 and the German price lists of July 2026 (BMW hackathon data).</p>
          </div>
          <div className="stack">
            <h3 className="footer__title">Models</h3>
            <p className="small">Channel-adjusted complaint index, TF-IDF feature classifiers, an explainable boosting machine for complaints and a price-list fitment re-ranker.</p>
          </div>
          <div className="stack">
            <h3 className="footer__title">Knowledge graph</h3>
            <p className="small">
              {status
                ? `${fmtInt(status.graph.nodes)} nodes and ${fmtInt(status.graph.edges)} edges; ${status.graph.checks_passed ? "all" : "not all"} ${status.graph.n_checks} integrity checks against the source tables passed.`
                : "Loading…"}
            </p>
          </div>
          <div className="stack">
            <h3 className="footer__title">Agents</h3>
            <p className="small">
              {status
                ? `Retriever ${status.models.retriever}, explainer ${status.models.explainer}, verifier rules + ${status.models.verifier}${status.llm_configured ? "." : " (offline: no OpenAI key)."}`
                : "Loading…"}
            </p>
          </div>
        </div>
        <div className="wrap footer__legal">
          <p className="disclaimer">
            Internal prototype on BMW hackathon data. The BMW logo and BMW Type Next are BMW trademarks / licensed assets, loaded locally
            and not distributed with this code.
          </p>
        </div>
      </footer>
    </>
  );
}
