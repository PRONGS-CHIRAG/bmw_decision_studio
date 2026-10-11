import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, MARKET_NAMES, MODEL_NAMES, fmtInt, fmtNum, postJSON, useApi } from "../api";
import type { AgentEvaluation, AgentStatus, CompareResult, CompetitorAnalysis, Explained, FeatureResult, IdeaSpec, InterpretResult, Policy } from "../types";
import ProcessFlow, { ACTOR_LABEL, ActorIcon, type Actor, type ExplainState, type Phase, type RunKey, type Runs, type StepId, type TraceEvent } from "../components/ProcessFlow";
import CompetitorPanel, { type CompState } from "../components/CompetitorPanel";
import DecisionForm from "../components/DecisionForm";
import DecisionMatrix from "../components/DecisionMatrix";
import EvidencePanel from "../components/EvidencePanel";
import IdeaHero, { EXAMPLES } from "../components/IdeaHero";
import PlainReport from "../components/PlainReport";
import PolicyPanel from "../components/PolicyPanel";
import PriceLadder from "../components/PriceLadder";
import SpecReview from "../components/SpecReview";
import VerificationReport from "../components/VerificationReport";
import { REC_INFO, REC_ORDER, bottomLine, groupCells } from "../plain";

// cytoscape is large: load the graph view only when its tab or the full-screen page is opened
const EvidenceGraph = lazy(() => import("../components/EvidenceGraph"));
const GraphPage = lazy(() => import("../components/GraphPage"));

type Tab = "summary" | "markets" | "equipment" | "graph" | "verification";
const TABS: { id: Tab; label: string }[] = [
  { id: "summary", label: "Summary" },
  { id: "markets", label: "Metrics" },
  { id: "equipment", label: "Price & equipment" },
  { id: "graph", label: "Knowledge graph" },
  { id: "verification", label: "Verification" },
];
const STEPS: StepId[] = ["retriever", "you", "engine", "explainer", "verifier", "brief"];
const STEP_TITLE: Record<StepId, string> = {
  retriever: "Break down your idea", you: "Choose what to check", engine: "Score against the data", explainer: "Write the brief",
  verifier: "Fact-check the brief", brief: "Your decision",
};
const STEP_TAB: Partial<Record<StepId, Tab>> = { engine: "summary", explainer: "summary", verifier: "verification", brief: "summary" };

export default function IdeaEvaluation({ status }: { status: AgentStatus | null }) {
  const { data: policyData } = useApi<{ default: Policy }>("/api/policy");
  const [idea, setIdea] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [interp, setInterp] = useState<InterpretResult | null>(null);
  const [draft, setDraft] = useState<IdeaSpec | null>(null);
  const [evaluation, setEvaluation] = useState<AgentEvaluation | null>(null);
  const [explained, setExplained] = useState<Explained | null>(null);
  const [explainState, setExplainState] = useState<ExplainState>("idle");
  const [explainError, setExplainError] = useState<string | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [showPolicy, setShowPolicy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState("");
  const [runs, setRuns] = useState<Runs>({});
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [interpretError, setInterpretError] = useState<string | null>(null);
  const [evaluateError, setEvaluateError] = useState<string | null>(null);
  const traceId = useRef(0);
  const [focus, setFocus] = useState<string | null>(null);
  const [featIdx, setFeatIdx] = useState(0);
  const [cellKey, setCellKey] = useState<string | null>(null);
  const [panel, setPanel] = useState<StepId>("retriever");   // side panel; follows each real step transition
  const [tab, setTab] = useState<Tab>("summary");
  const shown = useRef<string | null>(null);          // evaluation id on screen; late agent answers for others are dropped
  const [graphOpen, setGraphOpen] = useState(false);  // the knowledge graph on a page of its own
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const policyEdited = useRef(false);
  const [comp, setComp] = useState<CompareResult | null>(null);              // competitor comparison (no LLM)
  const [compAnalysis, setCompAnalysis] = useState<CompetitorAnalysis | null>(null);   // Agents 4 + 5
  const [compState, setCompState] = useState<CompState>("idle");
  const [compError, setCompError] = useState<string | null>(null);
  const compShown = useRef<string | null>(null);      // scope on screen; late competitor answers for others are dropped

  useEffect(() => {
    if (policyData && !policy) setPolicy(policyData.default);
  }, [policyData, policy]);

  // ---- audit trail: every request, response, wait and error, with real timestamps
  const log = useCallback((actor: Actor, title: string, detail?: string, tone?: TraceEvent["tone"]) => {
    const ev: TraceEvent = { id: ++traceId.current, at: performance.now(), clock: new Date().toLocaleTimeString("en-GB"), actor, title, detail, tone };
    setTrace((t) => [...t, ev]);
  }, []);
  const startRun = (k: RunKey) => setRuns((r) => ({ ...r, [k]: { start: performance.now() } }));
  const endRun = (k: RunKey, failed = false) =>
    setRuns((r) => (r[k] ? { ...r, [k]: { ...r[k]!, end: performance.now(), failed } } : r));

  async function interpret(text: string) {
    setError(null);
    setInterpretError(null);
    setEvaluateError(null);
    setSubmitted(text);
    setRuns({});
    traceId.current = 0;
    setTrace([]);
    log("you", "Idea submitted", text);
    log("retriever", "Request sent: match the idea", "POST /api/agent/interpret");
    startRun("interpret");
    setPhase("interpreting");
    setInterp(null);
    setDraft(null);
    setEvaluation(null);
    setExplained(null);
    setExplainState("idle");
    setFocus(null);
    shown.current = null;
    compShown.current = null;
    setComp(null);
    setCompAnalysis(null);
    setCompState("idle");
    setCompError(null);
    setPanel("retriever");
    setTab("summary");
    const t = performance.now();
    try {
      const r = await postJSON<InterpretResult>("/api/agent/interpret", { idea: text });
      endRun("interpret");
      setInterp(r);
      setDraft(r.spec);
      for (const a of r.attempts.filter((a) => !a.ok)) log("retriever", `Schema check failed on attempt ${a.attempt}`, a.errors.join("; "), "error");
      log("retriever", `Idea spec returned in ${((performance.now() - t) / 1000).toFixed(1)} s`,
        `${r.spec.features.length ? r.spec.features.map((f) => f.feature).join(", ") : "no feature picked"}; ${r.candidates.length} candidates; ${r.method}${r.semantic_error ? `; embeddings failed: ${r.semantic_error}` : ""}`);
      if (r.spec.ambiguities.length) log("retriever", `${r.spec.ambiguities.length} ambiguity noted`, r.spec.ambiguities.join(" "));
      log("you", "Waiting for you to choose what to check", "Pick topics, series and markets, then run the check.", "wait");
      setPhase("review");
      setPanel("you");
    } catch (e) {
      endRun("interpret", true);
      const msg = (e as Error).message;
      log("retriever", "Matching failed", msg, "error");
      setInterpretError(msg);
      setError(msg);
      setPhase("idle");
    }
  }

  async function explain(eid: string) {
    setExplainState("running");
    setExplainError(null);
    setExplained(null);
    log("explainer", "Request sent: write and verify the brief", `POST /api/agent/explain, evaluation ${eid}`);
    setPanel("explainer");
    startRun("explain");
    const t = performance.now();
    try {
      const x = await postJSON<Explained>("/api/agent/explain", { evaluation_id: eid });
      if (shown.current !== eid) return;
      endRun("explain");
      const v = x.verification;
      log("explainer", `Brief drafted by ${x.explanation.model}`, `${v.claims.length} claims, ${x.explanation.attempts} draft(s)`);
      if (v.rewritten.length) log("verifier", `${v.rewritten.length} claim(s) failed and were sent back once`, v.rewritten.map((c) => c.text).join(" | "), "error");
      log("verifier", `${v.n_verified} claims verified, ${v.n_removed} removed`, `Rules: ${v.rules.join(", ")}; entailment by ${v.semantic_model ?? "none"}`);
      log("brief", `Brief ready in ${((performance.now() - t) / 1000).toFixed(1)} s`, `${x.seconds.toFixed(1)} s spent by the agents on the server`);
      setExplained(x);
      setExplainState("done");
      setPanel("brief");
    } catch (e) {
      if (shown.current !== eid) return;
      endRun("explain", true);
      const err = e as ApiError;
      const off = err.code === "llm_unavailable" || err.code === "model_unavailable";
      log("explainer", off ? "Explainer not available" : "Explainer failed", err.message, "error");
      setExplainError(err.message);
      setExplainState(off ? "unavailable" : "error");
      setPanel("brief");
    }
  }

  // Competitors: the comparison depends on the scope only (series, markets, features), not on the policy.
  async function analyseCompetitors(cid: string) {
    setCompState("running");
    setCompError(null);
    setCompAnalysis(null);
    log("analyst", "Request sent: compare with the competitors", `POST /api/agent/competitors, comparison ${cid}`);
    const t = performance.now();
    try {
      const x = await postJSON<CompetitorAnalysis>("/api/agent/competitors", { competition_id: cid });
      if (compShown.current !== cid) return;
      const a = x.analysis;
      log("analyst", `${a.findings.length} findings verified, ${a.removed.length} removed`, `${a.model}; ${a.rewritten.length} sent back once`);
      if (x.verification) log("presenter", `Competitor brief: ${x.verification.n_presented_verified} sentences verified`,
        `${x.brief?.model}; ${x.verification.n_presented_replaced} replaced by the analyst's finding; ${((performance.now() - t) / 1000).toFixed(1)} s`);
      setCompAnalysis(x);
      setCompState("done");
    } catch (e) {
      if (compShown.current !== cid) return;
      const err = e as ApiError;
      const off = err.code === "llm_unavailable" || err.code === "model_unavailable";
      log("analyst", off ? "Competitor agents not available" : "Competitor analysis failed", err.message, "error");
      setCompError(err.message);
      setCompState(off ? "unavailable" : "error");
    }
  }

  async function loadCompetitors(spec: IdeaSpec) {
    const scope = JSON.stringify([spec.series, spec.markets, spec.features.map((f) => f.feature)]);
    compShown.current = scope;
    setComp(null);
    setCompAnalysis(null);
    setCompError(null);
    setCompState("loading");
    log("system", "Request sent: competitor comparison", "POST /api/competitors/compare");
    try {
      const r = await postJSON<CompareResult>("/api/competitors/compare", {
        series: spec.series, markets: spec.markets, features: spec.features.map((f) => f.feature), idea: spec.idea, move: spec.move,
      });
      if (compShown.current !== scope) return;
      setComp(r);
      if (!r.available || !r.competition_id) {
        log("system", "No competitor data", r.comparison.message ?? "", "error");
        setCompState("nodata");
        return;
      }
      const n = r.comparison.tuples.filter((x) => x.status === "ok").length;
      log("system", `Competitor comparison: ${n} series-market sets, ${r.facts.length} facts`, `Comparison ${r.competition_id}; data ${r.comparison.data_hash}`);
      compShown.current = r.competition_id;
      analyseCompetitors(r.competition_id);
    } catch (e) {
      if (compShown.current !== scope) return;
      const msg = (e as Error).message;
      log("system", "Competitor comparison failed", msg, "error");
      setCompError(msg);
      setCompState("error");
    }
  }

  async function evaluate(spec: IdeaSpec, pol: Policy | null, withAgents: boolean) {
    setError(null);
    setEvaluateError(null);
    if (withAgents) {
      log("you", "Choice confirmed", `${spec.features.map((f) => f.feature).join(", ") || "no topic"}; ${spec.series.map((m) => MODEL_NAMES[m] ?? m).join(", ") || "all series"}; ${spec.markets.map((m) => MARKET_NAMES[m] ?? m).join(", ") || "all markets"}`);
      setRuns((r) => ({ interpret: r.interpret }));
      setExplainState("idle");
      setExplained(null);
    } else {
      log("system", "Decision policy changed", "Re-running the decision engine only; the agents are not called.");
    }
    log("engine", "Request sent: compute the evidence", "POST /api/agent/evaluate");
    startRun("evaluate");
    setPhase("evaluating");
    if (withAgents) setPanel("engine");
    const t = performance.now();
    try {
      const r = await postJSON<AgentEvaluation>("/api/agent/evaluate", { spec, policy: pol ?? undefined });
      endRun("evaluate");
      log("engine", `${r.facts.length} facts and ${r.graph.n_cited} cited graph nodes in ${((performance.now() - t) / 1000).toFixed(2)} s`,
        `Evaluation ${r.evaluation_id}; policy ${r.result.policy_hash}; data ${r.result.data_hash}`);
      const changed = shown.current !== r.evaluation_id;
      shown.current = r.evaluation_id;
      setEvaluation(r);
      setPhase("done");
      setFeatIdx((i) => Math.min(i, Math.max(0, r.result.features.length - 1)));
      if (withAgents) {
        setCellKey(null);
        explain(r.evaluation_id);
        loadCompetitors(r.spec);
      } else if (changed) {
        setExplained(null);
        setExplainState((s) => (s === "unavailable" ? s : "stale"));
        log("system", "The written brief is now out of date", "Write it again to match the new policy.", "stale");
      }
    } catch (e) {
      endRun("evaluate", true);
      const msg = (e as Error).message;
      log("engine", "Evaluation failed", msg, "error");
      setEvaluateError(msg);
      setError(msg);
      setPhase(evaluation ? "done" : "review");
    }
  }

  // Policy edits re-run the decision engine (instant, no LLM); the written brief is then marked stale.
  useEffect(() => {
    if (!policyEdited.current || !evaluation || !policy) return;
    const t = setTimeout(() => evaluate(evaluation.spec, policy, false), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [policy]);

  const editPolicy = (p: Policy) => {
    policyEdited.current = true;
    setPolicy(p);
  };
  const showNode = (id: string) => {
    setFocus(id);
    setTab("graph");
    requestAnimationFrame(() => document.getElementById("report")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  // The graph page gets a history entry, so the browser's Back closes it instead of leaving the app.
  const openGraph = useCallback(() => {
    window.history.pushState({ graphPage: true }, "", "#knowledge-graph");
    setGraphOpen(true);
  }, []);
  const closeGraph = useCallback(() => {
    if (window.history.state?.graphPage) window.history.back();
    else setGraphOpen(false);
  }, []);
  useEffect(() => {
    if (!graphOpen) return;
    const pop = () => setGraphOpen(false);
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, [graphOpen]);

  async function exportPdf() {
    if (!evaluation) return;
    setPdfBusy(true);
    setPdfError(null);
    try {
      const { downloadReport } = await import("../pdf/exportReport");
      await downloadReport({ evaluation, explained, explainState, explainError, status, competitors: { compare: comp, analysis: compAnalysis, state: compState, error: compError } });
      log("system", "Report exported as PDF", `Evaluation ${evaluation.evaluation_id}${explainState === "done" ? ", with the verified brief" : ", without the written brief"}`);
    } catch (e) {
      setPdfError((e as Error).message);
    } finally {
      setPdfBusy(false);
    }
  }

  const features = evaluation?.result.features ?? [];
  const fr = features[featIdx] ?? null;
  const firstCell = fr?.cells.find((c) => c.recommendation !== "Not sold" && c.recommendation !== "Insufficient evidence") ?? fr?.cells[0];
  const cell = fr?.cells.find((c) => `${c.model}|${c.market}` === cellKey) ?? firstCell;
  const busy = phase === "interpreting" || phase === "evaluating";
  // The summary is shown only once the last step has finished (or cannot run), so nothing unchecked is presented as the answer.
  const final = explainState !== "running" && explainState !== "idle";

  // The step the process is actually at (the side panel returns here on every transition).
  const current: StepId = phase === "interpreting" || (phase === "idle" && interpretError) ? "retriever" : phase === "review" ? "you"
    : phase === "evaluating" && !evaluation ? "engine" : explainState === "running" ? "explainer" : evaluation ? "brief" : "retriever";

  if (trace.length === 0)
    return (
      <div className="landing">
        <IdeaHero idea={idea} setIdea={setIdea} onSubmit={interpret} busy={busy} status={status} />
        <div className="sourceline">
          <div className="wrap">
            <p className="disclaimer">
              Sources: customer feedback exports for the F70, G60 and G70 ({status ? `${fmtInt(status.graph.nodes)} graph nodes, ` : ""}10,128
              comments), customer studies 2025 (CN/EU and US), sales volumes 2024–2030 and the German price lists of July 2026, plus the
              outputs of the trained classifiers and complaint model.
            </p>
          </div>
        </div>
      </div>
    );

  const selectStep = (id: StepId) => {
    setPanel(id);
    const t = STEP_TAB[id];
    if (t && evaluation) setTab(t);
  };

  return (
    <div className="ws">
      <div className="ws__main">
        <IdeaBar idea={idea} setIdea={setIdea} onSubmit={interpret} busy={busy} />
        {error && <p className="note note--error small">Something went wrong: {error}</p>}
        <section aria-label="Process" className="ws__flow">
          <ProcessFlow status={status} idea={submitted} phase={phase} interp={interp} draft={draft} evaluation={evaluation}
            explained={explained} explainState={explainState} explainError={explainError} interpretError={interpretError}
            evaluateError={evaluateError} runs={runs} trace={trace} selected={panel} onSelect={selectStep} />
        </section>

        <section id="report" className="ws__report anchor" aria-labelledby="report-title">
          <div className="report__top">
            <h2 id="report-title" className="report__title">Report</h2>
            {evaluation && (
              <div className="report__actions">
                <button type="button" className="btn btn--outline btn--small" onClick={openGraph}>
                  <GraphIcon /> Open knowledge graph
                </button>
                <button type="button" className="btn btn--small" onClick={exportPdf} disabled={pdfBusy}
                  title={explainState === "running" ? "The written brief is still being prepared; export now leaves it out" : undefined}>
                  <DownloadIcon /> {pdfBusy ? "Preparing PDF…" : "Export PDF"}
                </button>
              </div>
            )}
            {features.length > 1 && (
              <div className="chips" role="group" aria-label="Feature">
                {features.map((f, i) => (
                  <button key={f.feature} type="button" className="chip" aria-pressed={i === featIdx} onClick={() => { setFeatIdx(i); setCellKey(null); }}>
                    {f.feature}
                  </button>
                ))}
              </div>
            )}
          </div>
          {pdfError && <p className="note note--error small">The PDF could not be created: {pdfError}</p>}
          {!evaluation ? (
            <div className="report__empty">
              <p><strong>The report appears here once the evidence is computed.</strong></p>
              <p className="small muted">{phase === "review" ? "Choose what to check in the side panel to continue." : "First your idea is broken down into topics from customer feedback, then you choose what to check."}</p>
            </div>
          ) : (
            <>
              <div className="tabs" role="tablist" aria-label="Report sections">
                {TABS.map((t) => (
                  <button key={t.id} id={`tab-${t.id}`} className="tab" role="tab" aria-selected={tab === t.id} aria-controls="report-panel" onClick={() => setTab(t.id)}>
                    {t.label}
                  </button>
                ))}
              </div>
              <div id="report-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="report__panel">
                {tab === "summary" && (final ? (
                  <PlainReport evaluation={evaluation} feature={fr} explained={explained} explainState={explainState} explainError={explainError}
                    onExplain={() => explain(evaluation.evaluation_id)} onShowNode={showNode} onOpenMetrics={() => setTab("markets")} />
                ) : (
                  <div className="report__pending" role="status">
                    <p className="side__working-title"><span className="spinner" aria-hidden /> Preparing your summary</p>
                    <p className="small">The summary appears once the brief has been written and every sentence fact-checked, so you only see checked results.</p>
                    <ol>
                      <li>Scored against the data: done</li>
                      <li>Writing the brief: {explainState === "running" ? "in progress" : "starting"}</li>
                      <li>Fact-checking every sentence: waiting</li>
                    </ol>
                    <p className="caption">The raw numbers are already in the Metrics tab if you want to look now.</p>
                  </div>
                ))}
                {tab === "markets" && (fr && cell ? (
                  <div className="stack">
                    <p className="small muted measure">
                      The priority score (0 to 1) says how strongly customers give a reason to act, for each series and market. It combines complaints,
                      how often the topic comes up, requests, customer-study weakness and how many cars are sold there. Select a cell to see its evidence.
                    </p>
                    <div className="decision-grid">
                      <DecisionMatrix cells={fr.cells} models={evaluation.result.models} markets={evaluation.result.markets} selected={`${cell.model}|${cell.market}`} onSelect={setCellKey} />
                      <EvidencePanel cell={cell} fitment={fr.price_ladder.find((l) => l.model === cell.model)} />
                    </div>
                  </div>
                ) : <p className="small muted">No feature was evaluated, so there is no series × market evidence.</p>)}
                {tab === "equipment" && (<>{fr ? (
                  <div className="stack">
                    <p className="small muted">German price lists, July 2026. EUR incl. 19% VAT. Prices for other markets are not in the data.</p>
                    <PriceLadder ladder={fr.price_ladder} />
                    {fr.specs.length > 0 && (
                      <details>
                        <summary>Technical data linked to {fr.feature} ({fr.specs.length} values)</summary>
                        <div className="table-scroll" style={{ marginTop: 12 }}>
                          <table className="table">
                            <thead><tr><th>Series</th><th>Variant</th><th>Attribute (as printed)</th><th>Value</th><th>Page</th></tr></thead>
                            <tbody>
                              {fr.specs.map((s, i) => (
                                <tr key={i}><td>{MODEL_NAMES[s.model]}</td><td>{s.variant}</td><td>{s.attribute}</td><td className="num">{s.value}</td><td className="caption">{s.model} p.{s.page}</td></tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    )}
                  </div>
                ) : <p className="small muted">No feature was evaluated, so there is no BMW price-list position for it.</p>}
                  <CompetitorPanel compare={comp} analysis={compAnalysis} state={compState} error={compError} onShowNode={showNode}
                    onRetry={() => (comp?.competition_id ? analyseCompetitors(comp.competition_id) : evaluation && loadCompetitors(evaluation.spec))} />
                </>)}
                {tab === "graph" && (
                  <Suspense fallback={<div className="skeleton" style={{ height: 320 }} />}>
                    <EvidenceGraph evaluation={evaluation} focus={focus} onFocus={setFocus} onOpenFull={openGraph} />
                  </Suspense>
                )}
                {tab === "verification" && <VerificationReport explained={explained} facts={evaluation.facts} />}
              </div>
            </>
          )}
        </section>
      </div>

      {graphOpen && evaluation && (
        <Suspense fallback={<div className="gpage gpage--loading" role="status"><span className="spinner" aria-hidden /></div>}>
          <GraphPage evaluation={evaluation} focus={focus} onFocus={setFocus} onClose={closeGraph} onExport={exportPdf} exporting={pdfBusy} exportError={pdfError} />
        </Suspense>
      )}

      <aside className="ws__side side" aria-label="Side panel">
        <div className="side__head">
          <ol className="side__steps" aria-label="Steps">
            {STEPS.map((id, i) => (
              <li key={id}>
                <button type="button" className={`side__step ${id === panel ? "side__step--on" : ""} ${id === current ? "side__step--now" : ""}`}
                  aria-current={id === panel ? "step" : undefined} aria-label={`Step ${i + 1}: ${STEP_TITLE[id]}`} onClick={() => selectStep(id)}>
                  <ActorIcon actor={id} size={14} />
                </button>
              </li>
            ))}
          </ol>
          <p className="side__eyebrow">Step {STEPS.indexOf(panel) + 1} of 6, {ACTOR_LABEL[panel]}</p>
          <h2 className="side__title">{STEP_TITLE[panel]}</h2>
          {panel !== current && (
            <button type="button" className="side__back" onClick={() => selectStep(current)}>
              Back to the current step: {STEP_TITLE[current]}
            </button>
          )}
        </div>
        <div className="side__body">
          {panel === "retriever" && (
            phase === "interpreting" ? (
              <Working title="Breaking down your idea">
                We look for topics in existing customer feedback that your idea touches, by name, with a trained text classifier and by meaning.
                The AI then suggests the best matches from that list only. Takes about 5 seconds.
              </Working>
            ) : interpretError ? (
              <div className="stack">
                <p className="note note--error">The idea could not be matched: {interpretError}</p>
                <button className="btn btn--small" onClick={() => interpret(submitted)}>Try again</button>
              </div>
            ) : interp ? (
              <div className="stack">
                <p>{interp.spec.summary}</p>
                <p className="small muted">
                  {interp.spec.features.length ? `Suggested: ${interp.spec.features.map((f) => f.feature).join(", ")}.` : "No exact match."}{" "}
                  {interp.candidates.length} related topics were found in the customer feedback for you to choose from.
                </p>
                {phase === "review" && <button className="btn btn--small" onClick={() => setPanel("you")}>Next: choose what to check</button>}
              </div>
            ) : null
          )}

          {panel === "you" && (
            interp && draft ? (
              <SpecReview compact interp={interp} draft={draft} setDraft={setDraft} busy={phase === "evaluating"}
                onEvaluate={() => evaluate(draft, policy, true)} confirmed={phase === "evaluating" || phase === "done"} />
            ) : <Waiting>This step opens once your idea has been broken down into topics.</Waiting>
          )}

          {panel === "engine" && (
            evaluation ? (
              <div className="stack">
                {fr ? <EngineSummary feature={fr} final={final} /> : <p className="small">No topic matched directly, so there is nothing to score. See the report for the nearest topics.</p>}
                {policy && policyData && (
                  <div className="stack">
                    <button className="btn btn--outline btn--small" onClick={() => setShowPolicy((s) => !s)} aria-expanded={showPolicy}>
                      {showPolicy ? "Hide the decision policy" : "Adjust the decision policy"}
                    </button>
                    <p className="caption">Changing the policy recomputes the numbers instantly. The written brief is then marked out of date.</p>
                    {showPolicy && (
                      <PolicyPanel policy={policy} defaults={policyData.default} hash={evaluation.result.policy_hash} onChange={editPolicy}
                        onReset={() => editPolicy(policyData.default)} />
                    )}
                  </div>
                )}
              </div>
            ) : phase === "evaluating" ? (
              <Working title="Scoring against the data">Every series and market is scored from customer feedback, studies and sales. No AI is used.</Working>
            ) : <Waiting>This step starts when you have chosen what to check.</Waiting>
          )}

          {(panel === "explainer" || panel === "verifier") && (
            explainState === "running" ? (
              <Working title={panel === "explainer" ? "Writing the brief" : "Checking every sentence"}>
                The explainer writes the brief from the facts only, citing a fact for every sentence. The verifier then checks numbers, labels,
                quotes and scope by rule and asks a second model whether the facts support each sentence. A failing sentence is rewritten once,
                then removed. Both run in one request of about 20 to 50 seconds.
              </Working>
            ) : explained ? (
              <div className="stack">
                <p>
                  <strong>{explained.verification.n_verified} sentences</strong> passed every check
                  {explained.verification.n_removed ? `, ${explained.verification.n_removed} were removed` : ", none were removed"}
                  {explained.verification.rewritten.length ? `. ${explained.verification.rewritten.length} were sent back once and fixed.` : "."}
                </p>
                <p className="small muted">Click the nodes under steps 4 and 5 to see each section and each check.</p>
                <button className="btn btn--outline btn--small" onClick={() => setTab("verification")}>Open the verification report</button>
              </div>
            ) : explainState === "stale" || explainState === "error" ? (
              <div className="stack">
                <p className="note note--warn">{explainState === "stale" ? "The policy changed, so the brief is out of date." : `The brief failed: ${explainError}`}</p>
                {evaluation && <button className="btn btn--small" onClick={() => explain(evaluation.evaluation_id)}>Write the brief again</button>}
              </div>
            ) : explainState === "unavailable" ? (
              <p className="note note--warn">The writing agents are not available. {explainError}</p>
            ) : <Waiting>This step starts after the evidence is computed.</Waiting>
          )}

          {panel === "brief" && (
            evaluation ? (
              <div className="stack-lg">
                {features.map((f) => (
                  <div key={f.feature} className="stack">
                    {final && <p className="side__answer">{bottomLine(f).text}</p>}
                    <DecisionForm result={evaluation.result} feature={f} />
                  </div>
                ))}
                {features.length === 0 && <p className="small muted">Pick a related topic in step 2 to record a decision against its evidence.</p>}
                {!final && <p className="caption">The summary appears once the brief is written and fact-checked.</p>}
              </div>
            ) : <Waiting>Your decision comes last, after the report is ready.</Waiting>
          )}
        </div>
      </aside>
    </div>
  );
}

function IdeaBar({ idea, setIdea, onSubmit, busy }: { idea: string; setIdea: (v: string) => void; onSubmit: (t: string) => void; busy: boolean }) {
  return (
    <form className="ideabar" onSubmit={(e) => { e.preventDefault(); if (idea.trim()) onSubmit(idea.trim()); }}>
      <label htmlFor="idea" className="sr-only">Your feature idea</label>
      <input id="idea" className="input ideabar__input" value={idea} onChange={(e) => setIdea(e.target.value)} placeholder={`Try another idea, for example: ${EXAMPLES[0]}`} autoComplete="off" maxLength={2000} />
      <button className="btn btn--small ideabar__btn" type="submit" disabled={busy || !idea.trim()}>{busy ? "Working…" : "Evaluate"}</button>
    </form>
  );
}

function GraphIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <circle cx="3.5" cy="8" r="2" /><circle cx="12.5" cy="3.5" r="2" /><circle cx="12.5" cy="12.5" r="2" />
      <path d="M5.3 7.1 10.7 4.4M5.3 8.9l5.4 2.7" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <path d="M8 2v8M4.5 6.5 8 10l3.5-3.5M2.5 13.5h11" />
    </svg>
  );
}

function Working({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="side__working" role="status">
      <p className="side__working-title"><span className="spinner" aria-hidden /> {title}</p>
      <p className="small">{children}</p>
    </div>
  );
}

function Waiting({ children }: { children: React.ReactNode }) {
  return <p className="side__waiting">{children}</p>;
}

function EngineSummary({ feature, final }: { feature: FeatureResult; final: boolean }) {
  const g = groupCells(feature);
  return (
    <div className="stack">
      {final ? <p className="side__answer">{bottomLine(feature).text}</p> : <p className="small">Places per recommendation. The summary follows after the fact-check.</p>}
      <ul className="side__groups">
        {REC_ORDER.filter((k) => g.get(k)?.length).map((k) => (
          <li key={k} className={`side__group side__group--${REC_INFO[k].tone}`}>
            <span>{REC_INFO[k].label}</span>
            <span className="num">{g.get(k)!.length}</span>
          </li>
        ))}
      </ul>
      {feature.rollup.score !== null && <p className="small muted">Priority score {fmtNum(feature.rollup.score)} on a scale from 0 to 1.</p>}
    </div>
  );
}
