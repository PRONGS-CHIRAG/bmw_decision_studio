import { useState } from "react";
import { fmtInt, useApi } from "./api";
import type { AgentStatus } from "./types";
import BrandHeader, { type View } from "./components/BrandHeader";
import IdeaEvaluation from "./pages/IdeaEvaluation";

export default function App() {
  const { data: status } = useApi<AgentStatus>("/api/agent/status");
  const [view, setView] = useState<View>("evaluate");
  return (
    <div className="app">
      <BrandHeader status={status} view={view} onView={setView} />
      {/* the evaluation stays mounted while About is open, so no work is lost */}
      <main className="app__main" hidden={view !== "evaluate"}>
        <IdeaEvaluation status={status} />
      </main>
      {view === "about" && <About status={status} />}
    </div>
  );
}

function About({ status }: { status: AgentStatus | null }) {
  return (
    <main className="app__main about">
      <div className="about__inner">
        <h1 className="about__title">About this prototype</h1>
        <div className="about__grid">
          <section className="about__card">
            <h2 className="about__h">Data</h2>
            <p className="small">Customer feedback exports for the 1, 5 and 7 Series, customer studies 2025, sales volumes 2024–2030 and the German price lists of July 2026 (BMW hackathon data).</p>
          </section>
          <section className="about__card">
            <h2 className="about__h">Models</h2>
            <p className="small">Channel-adjusted complaint index, TF-IDF feature classifiers, an explainable boosting machine for complaints and a price-list fitment re-ranker.</p>
          </section>
          <section className="about__card">
            <h2 className="about__h">Knowledge graph</h2>
            <p className="small">
              {status
                ? `${fmtInt(status.graph.nodes)} nodes and ${fmtInt(status.graph.edges)} edges; ${status.graph.checks_passed ? "all" : "not all"} ${status.graph.n_checks} integrity checks against the source tables passed.`
                : "Loading…"}
            </p>
          </section>
          <section className="about__card">
            <h2 className="about__h">Agents</h2>
            <p className="small">
              {status
                ? `Retriever ${status.models.retriever}, explainer ${status.models.explainer}, verifier rules + ${status.models.verifier}${status.llm_configured ? "." : " (offline: no OpenAI key)."}`
                : "Loading…"}
            </p>
          </section>
        </div>
        <p className="disclaimer about__legal">
          Internal prototype on BMW hackathon data. The BMW logo and BMW Type Next are BMW trademarks / licensed assets, loaded locally and not
          distributed with this code.
        </p>
      </div>
    </main>
  );
}
