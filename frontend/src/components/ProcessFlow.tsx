import { useEffect, useState, type ReactNode } from "react";
import { MARKET_NAMES, MODEL_NAMES, MOVE_LABELS, fmtInt } from "../api";
import type { AgentEvaluation, AgentStatus, Explained, IdeaSpec, InterpretResult } from "../types";

// The pipeline as a horizontal flowchart. The backend answers in three blocking requests
// (interpret, evaluate, explain), so a card shows "running" with the real elapsed time while its
// request is open, and its sub-steps are filled only from the fields of the response. Nothing is simulated.

export type Phase = "idle" | "interpreting" | "review" | "evaluating" | "done";
export type ExplainState = "idle" | "running" | "done" | "unavailable" | "error" | "stale";
export type RunKey = "interpret" | "evaluate" | "explain";
export interface RunTiming {
  start: number;          // performance.now() when the request was sent
  end?: number;           // when the response (or the error) arrived
  failed?: boolean;
}
export type Runs = Partial<Record<RunKey, RunTiming>>;

export type Actor = "you" | "retriever" | "engine" | "explainer" | "verifier" | "brief" | "system";
export interface TraceEvent {
  id: number;
  at: number;             // performance.now()
  clock: string;          // wall-clock time, HH:MM:SS
  actor: Actor;
  title: string;
  detail?: string;
  tone?: "wait" | "error" | "stale";
}

type NodeState = "waiting" | "running" | "wait" | "done" | "off" | "error" | "stale";
interface Line {
  text: string;
  status?: "ok" | "fail" | "skip" | "info";
}
interface FlowNode {
  id: Actor;
  title: string;
  who: string;
  state: NodeState;
  run?: RunTiming;
  about: string;          // what the step does (shown before it has a result)
  lines: Line[];          // what it actually did (from the response)
  handover?: string;      // the artifact passed to the next step
  target?: string;        // section id to jump to
  note?: string;
}

const STATE_TEXT: Record<NodeState, string> = {
  waiting: "Not started", running: "Running", wait: "Waiting for you", done: "Done", off: "Not available", error: "Failed",
  stale: "Out of date",
};

const ACTOR_LABEL: Record<Actor, string> = {
  you: "You", retriever: "Retriever agent", engine: "Decision engine", explainer: "Explainer agent", verifier: "Verifier agent",
  brief: "Brief", system: "System",
};

const ICON_PATHS: Record<Actor, ReactNode> = {
  you: (<><circle cx="12" cy="8" r="3.4" /><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" /></>),
  retriever: (<><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.3-4.3" /></>),
  engine: (<><path d="M17 5H7l5 7-5 7h10" /></>),
  explainer: (<><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M13.5 6.5l4 4" /></>),
  verifier: (<><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" /><path d="M9 12l2 2 4-4" /></>),
  brief: (<><path d="M6 3h9l4 4v14H6z" /><path d="M15 3v4h4" /><path d="M9 12h7M9 16h7" /></>),
  system: (<><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>),
};

export function ActorIcon({ actor, size = 16 }: { actor: Actor; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true">
      {ICON_PATHS[actor]}
    </svg>
  );
}

const secs = (ms: number) => `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
const plural = (n: number, one: string, many = `${one}s`) => `${fmtInt(n)} ${n === 1 ? one : many}`;
const seriesText = (s: string[]) => (s.length ? s.map((m) => MODEL_NAMES[m] ?? m).join(", ") : "All series");
const marketsText = (s: string[]) => (s.length ? s.map((m) => MARKET_NAMES[m] ?? m).join(", ") : "All markets");

/** Re-render on a 100 ms tick while something is running, so elapsed times are live. */
function useNow(active: boolean) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(t);
  }, [active]);
  return active ? now : performance.now();
}

function buildNodes(p: Props): FlowNode[] {
  const { status, phase, interp, draft, evaluation, explained, explainState, explainError, runs, interpretError, evaluateError } = p;
  const llm = Boolean(status?.llm_configured);
  const m = status?.models ?? {};

  // 1 retriever
  const retriever: FlowNode = {
    id: "retriever", title: "Match the idea", who: interp ? interp.method.replace(/^llm:/, "") : llm ? m.retriever ?? "LLM" : "rules (no API key)",
    state: phase === "interpreting" ? "running" : interp ? "done" : interpretError ? "error" : "waiting", run: runs.interpret,
    about: "Scores every feature in the knowledge graph with a text classifier and embeddings, then the model picks among those candidates only.",
    lines: [], target: "review", note: interpretError ?? undefined,
  };
  if (interp) {
    const nClass = interp.candidates.filter((c) => c.methods.classifier !== undefined).length;
    const nSem = interp.candidates.filter((c) => c.methods.semantic !== undefined).length;
    retriever.lines.push({ text: `Text classifier proposed ${plural(nClass, "candidate")}`, status: "ok" });
    retriever.lines.push(interp.semantic_error
      ? { text: `Embeddings unavailable: ${interp.semantic_error}`, status: "fail" }
      : { text: `${interp.semantic_method} proposed ${plural(nSem, "candidate")}`, status: "ok" });
    retriever.lines.push({ text: `${interp.method.startsWith("llm:") ? interp.method.slice(4) : "Rules"} picked ${plural(interp.spec.features.length, "feature")}`, status: interp.spec.features.length ? "ok" : "info" });
    for (const a of interp.attempts) {
      retriever.lines.push({ text: `Schema check, attempt ${a.attempt}: ${a.ok ? "passed" : `failed (${a.errors[0] ?? "invalid"})`}`, status: a.ok ? "ok" : "fail" });
    }
    retriever.handover = `Idea spec with ${plural(interp.spec.features.length, "feature")}`;
  }

  // 2 you confirm the scope
  const spec: IdeaSpec | null = evaluation?.spec ?? draft;
  const confirmed = phase === "evaluating" || phase === "done";
  const you: FlowNode = {
    id: "you", title: "Confirm the scope", who: "Product manager",
    state: phase === "review" ? "wait" : confirmed && interp ? "done" : "waiting",
    about: "You check the matched features, series, markets and move before anything is computed.",
    lines: [], target: "review",
  };
  if (spec && interp) {
    you.lines.push({ text: spec.features.length ? spec.features.map((f) => f.feature).join(", ") : "No feature selected", status: spec.features.length ? "ok" : "info" });
    you.lines.push({ text: seriesText(spec.series), status: "info" });
    you.lines.push({ text: marketsText(spec.markets), status: "info" });
    you.lines.push({ text: `${MOVE_LABELS[spec.move] ?? spec.move}${spec.proposed_price_eur ? `, EUR ${fmtInt(spec.proposed_price_eur)}` : ""}`, status: "info" });
    if (confirmed) you.handover = "Confirmed scope";
  }

  // 3 decision engine
  const engine: FlowNode = {
    id: "engine", title: "Compute the evidence", who: "Deterministic, no LLM",
    state: phase === "evaluating" ? "running" : evaluation ? "done" : evaluateError ? "error" : "waiting", run: runs.evaluate,
    about: "Scores each series and market from complaints, requests, survey weakness and sales, and turns every number into a fact with its source.",
    lines: [], target: "overview", note: evaluateError ?? undefined,
  };
  if (evaluation) {
    const r = evaluation.result;
    const cells = r.features.reduce((n, f) => n + f.cells.length, 0);
    const kinds = new Map<string, number>();
    for (const f of evaluation.facts) kinds.set(f.source.kind, (kinds.get(f.source.kind) ?? 0) + 1);
    const kindText = [...kinds.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => `${n} ${k}`).join(", ");
    engine.lines.push({ text: cells ? `Scored ${plural(cells, "series × market cell")}` : "No direct evidence to score", status: cells ? "ok" : "info" });
    engine.lines.push({ text: `Wrote ${plural(evaluation.facts.length, "fact")}: ${kindText}`, status: "ok" });
    engine.lines.push({ text: `Cited ${plural(evaluation.graph.n_cited, "graph node")}`, status: "ok" });
    engine.lines.push({ text: `Policy ${r.policy_hash}, data ${r.data_hash}`, status: "info" });
    engine.handover = `${plural(evaluation.facts.length, "fact")} with sources`;
  }

  // 4 + 5 explainer and verifier share one request
  const agentState: NodeState = explainState === "running" ? "running" : explainState === "done" ? "done" : explainState === "unavailable" ? "off"
    : explainState === "error" ? "error" : explainState === "stale" ? "stale" : "waiting";
  const explainer: FlowNode = {
    id: "explainer", title: "Write the brief", who: explained ? explained.explanation.model : llm ? m.explainer ?? "LLM" : "needs an OpenAI key",
    state: agentState, run: runs.explain, target: "explanation",
    about: "Writes the product-management brief from the facts only. Every claim must cite fact IDs.",
    lines: [], note: agentState === "off" || agentState === "error" ? explainError ?? undefined : agentState === "stale" ? "The policy changed after this brief was written. Write it again to update it." : undefined,
  };
  const verifier: FlowNode = {
    id: "verifier", title: "Check every claim", who: explained ? `rules + ${explained.verification.semantic_model ?? "LLM"}` : llm ? `rules + ${m.verifier ?? "LLM"}` : "needs an OpenAI key",
    state: agentState, run: runs.explain, target: "verification",
    about: "Checks citations, numbers, labels, quotes and scope by rule, then entailment by model. A failing claim is rewritten once, then removed.",
    lines: [], note: agentState === "running" ? "Runs in the same request as the explainer; both results arrive together." : undefined,
  };
  if (explained) {
    const v = explained.verification;
    const sections = Object.values(explained.explanation.sections).filter((c) => c.length).length;
    explainer.lines.push({ text: `Drafted ${plural(v.claims.length, "claim")}${explained.explanation.attempts > 1 ? " in the final draft" : ""}`, status: "ok" });
    explainer.lines.push({ text: `Covered ${plural(sections, "section")}`, status: "ok" });
    explainer.lines.push(explained.explanation.attempts > 1
      ? { text: `Rewrote after feedback (draft ${explained.explanation.attempts})`, status: "ok" }
      : { text: "No rewrite needed", status: "skip" });
    explainer.handover = `${plural(v.claims.length, "claim")} with fact IDs`;

    for (const rule of v.rules) {
      const checked = v.claims.flatMap((c) => c.checks.filter((k) => k.name === rule));
      if (!checked.length) continue;
      const passed = checked.filter((k) => k.passed).length;
      verifier.lines.push({ text: `${rule[0].toUpperCase()}${rule.slice(1)}: ${passed} of ${checked.length} passed`, status: passed === checked.length ? "ok" : "fail" });
    }
    verifier.lines.push(v.rewritten.length
      ? { text: `${plural(v.rewritten.length, "claim")} sent back for one rewrite`, status: "fail" }
      : { text: "Rewrite round skipped", status: "skip" });
    verifier.lines.push({ text: `${fmtInt(v.n_verified)} verified, ${fmtInt(v.n_removed)} removed`, status: v.n_removed ? "fail" : "ok" });
    verifier.handover = `${plural(v.n_verified, "verified claim")}`;
  }

  // 6 brief
  const brief: FlowNode = {
    id: "brief", title: "Ready for your decision", who: "Verified output",
    state: explainState === "done" ? "done" : explainState === "stale" ? "stale" : explainState === "unavailable" || explainState === "error" ? (evaluation ? "off" : "waiting") : "waiting",
    about: "Only verified claims reach the brief. The numbers above it come straight from the engine.",
    lines: [], target: explainState === "done" ? "explanation" : "overview",
  };
  if (explained) {
    const v = explained.verification;
    brief.lines.push({ text: `${plural(v.n_verified, "verified claim")} in the brief`, status: "ok" });
    brief.lines.push({ text: `Agents took ${explained.seconds.toFixed(1)} s on the server`, status: "info" });
    if (runs.interpret?.end && runs.explain?.end) brief.lines.push({ text: `${secs(runs.explain.end - runs.interpret.start)} from idea to brief, including your review`, status: "info" });
  } else if (evaluation && (explainState === "unavailable" || explainState === "error")) {
    brief.lines.push({ text: "The evidence and numbers are ready; the written brief is not.", status: "info" });
  }
  return [retriever, you, engine, explainer, verifier, brief];
}

interface Props {
  status: AgentStatus | null;
  idea: string;
  phase: Phase;
  interp: InterpretResult | null;
  draft: IdeaSpec | null;
  evaluation: AgentEvaluation | null;
  explained: Explained | null;
  explainState: ExplainState;
  explainError: string | null;
  interpretError: string | null;
  evaluateError: string | null;
  runs: Runs;
  trace: TraceEvent[];
  onJump: (id: string) => void;
}

export default function ProcessFlow(props: Props) {
  const nodes = buildNodes(props);
  const running = nodes.some((n) => n.state === "running");
  const now = useNow(running);
  const { trace, idea, onJump } = props;
  const t0 = trace[0]?.at ?? 0;
  const complete = props.explainState === "done";
  const waiting = props.phase === "review";
  const [logOpen, setLogOpen] = useState(false);

  const headline = complete ? "How this result was produced" : waiting ? "Waiting for you to confirm the scope" : running ? "Working on your idea" : "Process";
  const elapsed = (r?: RunTiming) => (r ? secs((r.end ?? now) - r.start) : null);

  return (
    <div className="flow" aria-labelledby="flow-title">
      <div className="flow__head">
        <div className="flow__heading">
          <h2 id="flow-title" className="flow__title">
            {running && <span className="spinner" aria-hidden />}
            {headline}
          </h2>
          <p className="flow__idea">“{idea}”</p>
        </div>
        <p className="flow__status" role="status" aria-live="polite">
          {nodes.filter((n) => n.state === "done").length} of {nodes.length} steps done
          {trace.length > 0 && <>, {plural(trace.length, "recorded event")}</>}
        </p>
      </div>

      <div className="flow__scroll" tabIndex={0} aria-label="Process flowchart, scrolls sideways">
        <ol className="flow__lane">
          {nodes.map((n, i) => {
            const next = nodes[i + 1];
            const edge = !next ? null : n.state === "done" && (next.state === "running" || next.state === "wait") ? "active"
              : n.state === "done" ? "done" : "idle";
            const clickable = Boolean(n.target) && n.state !== "waiting" && n.state !== "running";
            const time = elapsed(n.run);
            return (
              <li key={n.id} className="flow__item">
                <article className={`fnode fnode--${n.state} fnode--${n.id}`} aria-label={`${i + 1}. ${n.title}: ${STATE_TEXT[n.state]}`}>
                  <header className="fnode__head">
                    <span className="fnode__icon"><ActorIcon actor={n.id === "brief" ? "brief" : n.id} /></span>
                    <span className="fnode__state">
                      {n.state === "running" ? <span className="spinner spinner--sm" aria-hidden /> : <span className="fnode__dot" aria-hidden />}
                      {STATE_TEXT[n.state]}
                      {time && (n.state === "running" || n.state === "done" || n.state === "error") && <span className="fnode__time num">{time}</span>}
                    </span>
                  </header>
                  <p className="fnode__step">
                    <span className="num">{i + 1}</span> {ACTOR_LABEL[n.id]}
                  </p>
                  <h3 className="fnode__title">{n.title}</h3>
                  <p className="fnode__who">{n.who}</p>
                  {n.lines.length > 0 ? (
                    <ul className="fnode__lines">
                      {n.lines.map((l, j) => (
                        <li key={j} className={`fline fline--${l.status ?? "info"}`}>
                          <span className="fline__mark" aria-hidden />
                          <span>{l.text}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="fnode__about">{n.about}</p>
                  )}
                  {n.note && <p className={`fnode__note ${n.state === "error" ? "fnode__note--error" : ""}`}>{n.note}</p>}
                  {(n.handover || clickable) && (
                    <footer className="fnode__foot">
                      {n.handover && <span className="fnode__handover">Hands over: {n.handover}</span>}
                      {clickable && (
                        <button type="button" className="fnode__jump" onClick={() => onJump(n.target!)}>
                          {n.state === "wait" ? "Review now" : "Inspect"}
                        </button>
                      )}
                    </footer>
                  )}
                </article>
                {edge && (
                  <div className={`fedge fedge--${edge}`} aria-hidden>
                    <svg viewBox="0 0 40 16" preserveAspectRatio="none">
                      <line x1="0" y1="8" x2="32" y2="8" />
                      <path d="M30 3l7 5-7 5" />
                    </svg>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      <details className="flog" open={logOpen} onToggle={(e) => setLogOpen((e.target as HTMLDetailsElement).open)}>
        <summary>
          Request log <span className="flog__count num">{trace.length}</span>
        </summary>
        <ol className="flog__list">
          {trace.map((ev) => (
            <li key={ev.id} className={`flog__row ${ev.tone ? `flog__row--${ev.tone}` : ""}`}>
              <span className="flog__t num">{ev.clock}</span>
              <span className="flog__dt num">+{secs(ev.at - t0)}</span>
              <span className={`flog__actor flog__actor--${ev.actor}`}>
                <ActorIcon actor={ev.actor} size={13} />
                {ACTOR_LABEL[ev.actor]}
              </span>
              <span className="flog__what">
                <span className="flog__title">{ev.title}</span>
                {ev.detail && <span className="flog__detail">{ev.detail}</span>}
              </span>
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}
