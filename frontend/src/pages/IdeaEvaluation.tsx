import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, MARKET_NAMES, MODEL_NAMES, MOVE_LABELS, fmtInt, fmtNum, postJSON, useApi } from "../api";
import type { AgentEvaluation, AgentStatus, Explained, FeatureResult, IdeaSpec, InterpretResult, Policy } from "../types";
import ProcessFlow, { ACTOR_LABEL, ActorIcon, type Actor, type ExplainState, type Phase, type RunKey, type Runs, type StepId, type TraceEvent } from "../components/ProcessFlow";
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
  { id: "markets", label: "Series × markets" },
  { id: "equipment", label: "Price & equipment" },
  { id: "graph", label: "Knowledge graph" },
  { id: "verification", label: "Verification" },
];
const STEPS: StepId[] = ["retriever", "you", "engine", "explainer", "verifier", "brief"];
const STEP_TITLE: Record<StepId, string> = {
  retriever: "Match the idea", you: "Confirm the scope", engine: "Compute the evidence", explainer: "Write the brief",
  verifier: "Check every sentence", brief: "Your decision",
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
      log("you", "Waiting for you to confirm the scope", "Check features, series, markets and move, then run the evaluation.", "wait");
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

  async function evaluate(spec: IdeaSpec, pol: Policy | null, withAgents: boolean) {
    setError(null);
    setEvaluateError(null);
    if (withAgents) {
      log("you", "Scope confirmed", `${spec.features.map((f) => f.feature).join(", ") || "no feature"}; ${spec.series.map((m) => MODEL_NAMES[m] ?? m).join(", ") || "all series"}; ${spec.markets.map((m) => MARKET_NAMES[m] ?? m).join(", ") || "all markets"}; ${MOVE_LABELS[spec.move] ?? spec.move}`);
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
      await downloadReport({ evaluation, explained, explainState, explainError, status });
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
              <p className="small muted">{phase === "review" ? "Confirm the scope in the side panel to start step 3." : "Steps 1 and 2 come first: matching your idea and confirming what to evaluate."}</p>
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
                {tab === "summary" && (
                  <PlainReport evaluation={evaluation} feature={fr} explained={explained} explainState={explainState} explainError={explainError}
                    onExplain={() => explain(evaluation.evaluation_id)} onShowNode={showNode} />
                )}
                {tab === "markets" && (fr && cell ? (
                  <div className="stack">
                    <p className="small muted measure">One recommendation per series and market, from complaints, how often it comes up, requests and customer-study weakness. Select a cell to see its evidence.</p>
                    <div className="decision-grid">
                      <DecisionMatrix cells={fr.cells} models={evaluation.result.models} markets={evaluation.result.markets} selected={`${cell.model}|${cell.market}`} onSelect={setCellKey} />
                      <EvidencePanel cell={cell} fitment={fr.price_ladder.find((l) => l.model === cell.model)} />
                    </div>
                  </div>
                ) : <p className="small muted">No feature was evaluated, so there is no series × market evidence.</p>)}
                {tab === "equipment" && (fr ? (
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
                ) : <p className="small muted">No feature was evaluated.</p>)}
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
              <Working title="Reading your idea">
                A text classifier and an embedding search score every feature in the knowledge graph. The language model then picks from those
                candidates only and its answer is checked against a schema. Takes about 5 seconds.
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
                  Picked {interp.spec.features.length ? interp.spec.features.map((f) => f.feature).join(", ") : "no feature"} from {interp.candidates.length} candidates.
                  Click the nodes under step 1 for details.
                </p>
                {phase === "review" && <button className="btn btn--small" onClick={() => setPanel("you")}>Next: confirm the scope</button>}
              </div>
            ) : null
          )}

          {panel === "you" && (
            interp && draft ? (
              <SpecReview compact interp={interp} draft={draft} setDraft={setDraft} busy={phase === "evaluating"}
                onEvaluate={() => evaluate(draft, policy, true)} confirmed={phase === "evaluating" || phase === "done"} />
            ) : <Waiting>This step opens when the retriever has matched your idea.</Waiting>
          )}

          {panel === "engine" && (
            evaluation ? (
              <div className="stack">
                {fr ? <EngineSummary feature={fr} /> : <p className="small">No feature matched directly, so there is nothing to score. See the report for the nearest features.</p>}
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
              <Working title="Computing the evidence">The decision engine scores every series and market from the data. No language model is used.</Working>
            ) : <Waiting>This step starts when you confirm the scope.</Waiting>
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
                    <p className="side__answer">{bottomLine(f).text}</p>
                    <DecisionForm result={evaluation.result} feature={f} />
                  </div>
                ))}
                {features.length === 0 && <p className="small muted">Pick a related feature in step 2 to record a decision against its evidence.</p>}
                {explainState === "running" && <p className="caption">The written brief is still being prepared; you can read the numbers in the report already.</p>}
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

function EngineSummary({ feature }: { feature: FeatureResult }) {
  const g = groupCells(feature);
  return (
    <div className="stack">
      <p className="side__answer">{bottomLine(feature).text}</p>
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
