import { useCallback, useEffect, useState } from "react";
import { fmtInt, getJSON, useApi } from "./api";
import type { AgentStatus, TrackerView } from "./types";
import BrandHeader, { type View } from "./components/BrandHeader";
import { TRACKER_CHANGED } from "./components/DecisionForm";
import IdeaEvaluation from "./pages/IdeaEvaluation";
import Tracker from "./pages/Tracker";

export default function App() {
  const { data: status } = useApi<AgentStatus>("/api/agent/status");
  const [view, setView] = useState<View>("evaluate");
  const tracker = useTracker();
  // opening the Tracker re-checks the market, so the page never shows a stale comparison
  const open = (v: View) => {
    setView(v);
    if (v === "tracker") tracker.reload();
  };
  return (
    <div className="app">
      <BrandHeader status={status} view={view} onView={open} toReview={tracker.data?.n_needs_review ?? 0} />
      {/* the evaluation stays mounted while another view is open, so no work is lost */}
      <main className="app__main" hidden={view !== "evaluate"}>
        <IdeaEvaluation status={status} />
      </main>
      {view === "tracker" && <Tracker {...tracker} />}
      {view === "about" && <About status={status} />}
    </div>
  );
}

/** Tracker data, loaded on start and reloaded whenever a decision, status or review is recorded. */
function useTracker() {
  const [data, setData] = useState<TrackerView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(() => {
    setLoading(true);
    getJSON<TrackerView>("/api/tracker")
      .then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    reload();
    window.addEventListener(TRACKER_CHANGED, reload);
    return () => window.removeEventListener(TRACKER_CHANGED, reload);
  }, [reload]);
  return { data, error, loading, reload };
}

function About({ status }: { status: AgentStatus | null }) {
  return (
    <main className="app__main about">
      <div className="about__inner">
        <h1 className="about__title">About this prototype</h1>
        <div className="about__grid">
          <section className="about__card">
            <h2 className="about__h">Data</h2>
            <p className="small">Customer feedback exports for the 1, 5 and 7 Series, customer studies 2025, sales volumes 2024–2030 and the German price lists of July 2026 (BMW hackathon data), plus public web data on the top five competitors per series and market (sales, prices, equipment, technical data, reviews), each value quoted from a saved copy of its source.</p>
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
                ? `Retriever ${status.models.retriever}, explainer ${status.models.explainer}, verifier rules + ${status.models.verifier}; competitor analyst ${status.models.analyst ?? status.models.explainer} and presenter ${status.models.presenter ?? status.models.explainer}${status.llm_configured ? "." : " (offline: no OpenAI key)."}`
                : "Loading…"}
            </p>
          </section>
        </div>
        <p className="disclaimer about__legal">
          Internal prototype on BMW hackathon data. The BMW logo is a BMW trademark, used here for the BMW hackathon. BMW Type Next is a
          licensed typeface, loaded locally and not distributed with this code.
        </p>
      </div>
    </main>
  );
}
