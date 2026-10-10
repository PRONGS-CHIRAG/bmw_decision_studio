import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, MARKET_NAMES, MODEL_NAMES, MOVE_LABELS, fmtInt, postJSON, useApi } from "../api";
import type { AgentEvaluation, AgentStatus, Explained, IdeaSpec, InterpretResult, Policy } from "../types";
import ProcessFlow, { type Actor, type ExplainState, type Phase, type RunKey, type Runs, type TraceEvent } from "../components/ProcessFlow";
import ContentNav from "../components/ContentNav";
import DecisionForm from "../components/DecisionForm";
import DecisionMatrix from "../components/DecisionMatrix";
import EvidencePanel from "../components/EvidencePanel";
import ExplanationView from "../components/ExplanationView";
import IdeaHero from "../components/IdeaHero";
import KeyFigures from "../components/KeyFigures";
import PolicyPanel from "../components/PolicyPanel";
import PriceLadder from "../components/PriceLadder";
import SpecReview from "../components/SpecReview";
import VerificationReport from "../components/VerificationReport";
import { Verdict } from "../components/marks";

// cytoscape is large: load the graph view only when an evaluation exists
const EvidenceGraph = lazy(() => import("../components/EvidenceGraph"));

const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "explanation", label: "Explanation" },
  { id: "markets", label: "Series × markets" },
  { id: "equipment", label: "Price & equipment" },
  { id: "graph", label: "Knowledge graph" },
  { id: "verification", label: "Verification" },
  { id: "decision", label: "Decision" },
];

const scrollTo = (id: string) =>
  requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }));

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
  const shown = useRef<string | null>(null);          // evaluation id on screen; late agent answers for others are dropped
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
    scrollTo("pipeline");
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
      scrollTo("pipeline");
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
    } catch (e) {
      if (shown.current !== eid) return;
      endRun("explain", true);
      const err = e as ApiError;
      const off = err.code === "llm_unavailable" || err.code === "model_unavailable";
      log("explainer", off ? "Explainer not available" : "Explainer failed", err.message, "error");
      setExplainError(err.message);
      setExplainState(off ? "unavailable" : "error");
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
    if (withAgents) scrollTo("pipeline");
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
    scrollTo("graph");
  };

  const features = evaluation?.result.features ?? [];
  const fr = features[featIdx] ?? null;
  const firstCell = fr?.cells.find((c) => c.recommendation !== "Not sold" && c.recommendation !== "Insufficient evidence") ?? fr?.cells[0];
  const cell = fr?.cells.find((c) => `${c.model}|${c.market}` === cellKey) ?? firstCell;
  const busy = phase === "interpreting" || phase === "evaluating";

  return (
    <>
      <IdeaHero idea={idea} setIdea={setIdea} onSubmit={interpret} busy={busy} status={status} />
      <div className="sourceline">
        <div className="wrap">
          <p className="disclaimer">
            Sources: customer feedback exports for the F70, G60 and G70 ({status ? `${fmtInt(status.graph.nodes)} graph nodes, ` : ""}10,128
            comments), customer studies 2025 (CN/EU and US), sales volumes 2024–2030 and the German price lists of July 2026, plus the
            outputs of the trained classifiers and complaint model.
          </p>
          {error && <p className="error small">Something went wrong: {error}</p>}
        </div>
      </div>

      {trace.length > 0 && (
        <section id="pipeline" className="band band--tight anchor" aria-label="Process">
          <div className="wrap">
            <ProcessFlow status={status} idea={submitted} phase={phase} interp={interp} draft={draft} evaluation={evaluation}
              explained={explained} explainState={explainState} explainError={explainError} interpretError={interpretError}
              evaluateError={evaluateError} runs={runs} trace={trace} onJump={scrollTo} />
          </div>
        </section>
      )}

      {interp && draft && (
        <section id="review" className="band band--soft anchor" aria-label="What will be evaluated">
          <div className="wrap">
            <SpecReview interp={interp} draft={draft} setDraft={setDraft} busy={phase === "evaluating"} onEvaluate={() => evaluate(draft, policy, true)} />
          </div>
        </section>
      )}

      {evaluation && (
        <>
          <ContentNav sections={SECTIONS} cta="Evaluate another idea" onCta={() => {
            scrollTo("top");
            document.getElementById("idea")?.focus();
          }} />

          <section id="overview" className="band anchor">
            <div className="wrap stack-lg">
              <div className="stack">
                <p className="eyebrow">Step 2 · Decision engine</p>
                <h2 className="section-title">{fr ? "The evidence at a glance" : "No direct customer evidence"}</h2>
              </div>
              {features.length > 1 && (
                <div className="tabs" role="tablist" aria-label="Features">
                  {features.map((f, i) => (
                    <button key={f.feature} className="tab" role="tab" aria-selected={i === featIdx} onClick={() => {
                      setFeatIdx(i);
                      setCellKey(null);
                    }}>
                      {f.feature}
                    </button>
                  ))}
                </div>
              )}
              {fr ? (
                <KeyFigures feature={fr} explained={explained} policyHash={evaluation.result.policy_hash} dataHash={evaluation.result.data_hash} />
              ) : (
                <NoEvidence evaluation={evaluation} />
              )}
            </div>
          </section>

          <section id="explanation" className="band band--soft anchor">
            <div className="wrap stack-lg">
              <div className="stack">
                <p className="eyebrow">Steps 3 and 4 · Explainer and verifier agents</p>
                <h2 className="section-title">The brief for product management</h2>
              </div>
              <ExplanationView explained={explained} state={explainState} error={explainError} facts={evaluation.facts}
                onExplain={() => explain(evaluation.evaluation_id)} onShowNode={showNode} />
            </div>
          </section>

          <section id="markets" className="band anchor">
            <div className="wrap stack-lg">
              <div className="stack">
                <p className="eyebrow">Decision engine</p>
                <h2 className="section-title">Where it matters</h2>
                <p className="small muted measure">
                  One recommendation per series and market from complaints, breadth, requests and customer-study weakness, weighted by the
                  decision policy. Select a cell for its evidence.
                </p>
              </div>
              {fr && cell ? (
                <div className="decision-grid">
                  <DecisionMatrix cells={fr.cells} models={evaluation.result.models} markets={evaluation.result.markets}
                    selected={`${cell.model}|${cell.market}`} onSelect={setCellKey} />
                  <EvidencePanel cell={cell} fitment={fr.price_ladder.find((l) => l.model === cell.model)} />
                </div>
              ) : (
                <p className="small muted">No feature was evaluated, so there is no series × market evidence.</p>
              )}
            </div>
          </section>

          <section id="equipment" className="band band--soft anchor">
            <div className="wrap stack-lg">
              <div className="stack">
                <p className="eyebrow">German price lists, July 2026</p>
                <h2 className="section-title">Price and equipment today</h2>
                <p className="small muted measure">EUR incl. 19% VAT. Prices for other markets are not in the data.</p>
              </div>
              {fr ? <PriceLadder ladder={fr.price_ladder} /> : <p className="small muted">No feature was evaluated.</p>}
              {fr && fr.specs.length > 0 && (
                <details>
                  <summary>Technical data linked to {fr.feature} ({fr.specs.length} values)</summary>
                  <div className="table-scroll" style={{ marginTop: 12 }}>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Series</th>
                          <th>Variant</th>
                          <th>Attribute (as printed)</th>
                          <th>Value</th>
                          <th>Page</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fr.specs.map((s, i) => (
                          <tr key={i}>
                            <td>{MODEL_NAMES[s.model]}</td>
                            <td>{s.variant}</td>
                            <td>{s.attribute}</td>
                            <td className="num">{s.value}</td>
                            <td className="caption">{s.model} p.{s.page}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
            </div>
          </section>

          <section id="graph" className="band anchor">
            <div className="wrap stack-lg">
              <div className="stack">
                <p className="eyebrow">Knowledge graph</p>
                <h2 className="section-title">How the evidence connects</h2>
                <p className="small muted measure">
                  The idea, the features it matched, one recommendation node per series × market and every graph node a fact cites: verdict
                  cells, survey scores, sales volumes, price-list items, customer comments, model terms and caveats. Switch to the schema to
                  see how all the processed data and model outputs connect.
                </p>
              </div>
              <Suspense fallback={<div className="skeleton" style={{ height: 320 }} />}>
                <EvidenceGraph evaluation={evaluation} focus={focus} onFocus={setFocus} />
              </Suspense>
            </div>
          </section>

          <section id="verification" className="band band--soft anchor">
            <div className="wrap stack-lg">
              <div className="stack">
                <p className="eyebrow">Step 4 · Verifier agent</p>
                <h2 className="section-title">Verification report</h2>
              </div>
              <VerificationReport explained={explained} facts={evaluation.facts} />
            </div>
          </section>

          <section id="decision" className="band anchor">
            <div className="wrap stack-lg">
              <div className="stack">
                <p className="eyebrow">Your call</p>
                <h2 className="section-title">Decision and policy</h2>
              </div>
              {policy && policyData && (
                <div className="stack">
                  <div className="row">
                    <button className="btn btn--outline btn--small" onClick={() => setShowPolicy((s) => !s)} aria-expanded={showPolicy}>
                      {showPolicy ? "Hide decision policy" : "Adjust decision policy"}
                    </button>
                    <span className="small muted">Policy {evaluation.result.policy_hash}. Changing it recomputes the numbers instantly.</span>
                  </div>
                  {showPolicy && (
                    <PolicyPanel policy={policy} defaults={policyData.default} hash={evaluation.result.policy_hash} onChange={editPolicy}
                      onReset={() => editPolicy(policyData.default)} />
                  )}
                </div>
              )}
              {features.map((f) => (
                <DecisionForm key={f.feature} result={evaluation.result} feature={f} />
              ))}
              {!fr && <p className="small muted">Select a related feature in step 1 to record a decision against the evidence.</p>}
            </div>
          </section>
        </>
      )}
    </>
  );
}

function NoEvidence({ evaluation }: { evaluation: AgentEvaluation }) {
  return (
    <div className="stack">
      <p className="note note--warn">
        <strong>No feature in the customer data matches this idea directly.</strong> The data holds no customer comments, survey
        attributes or price-list items for it. The nearest features are below; choose one in step 1 to see related evidence.
      </p>
      <div className="tiles">
        {evaluation.candidates.slice(0, 6).map((c) => (
          <div key={c.feature} className="tile tile--static">
            <span className="tile__title">{c.feature}</span>
            <span className="caption">{c.domain}</span>
            <span className="row small" style={{ gap: 12 }}>
              <Verdict verdict={c.verdict} />
              <span className="muted num">{fmtInt(c.n_comments)} comments</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
