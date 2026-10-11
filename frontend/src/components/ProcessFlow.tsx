import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { MARKET_NAMES, MODEL_NAMES, MOVE_LABELS, fmtInt, fmtNum } from "../api";
import type { AgentEvaluation, AgentStatus, Explained, IdeaSpec, InterpretResult } from "../types";
import { REC_INFO, REC_ORDER, bottomLine, groupCells, placesText } from "../plain";

// The pipeline as a horizontal flowchart. The backend answers in three blocking requests
// (interpret, evaluate, explain), so a card shows "running" with the real elapsed time while its
// request is open, and its child nodes appear only when that response arrives. Nothing is simulated.

export type Phase = "idle" | "interpreting" | "review" | "evaluating" | "done";
export type ExplainState = "idle" | "running" | "done" | "unavailable" | "error" | "stale";
export type RunKey = "interpret" | "evaluate" | "explain";
export interface RunTiming {
  start: number;          // performance.now() when the request was sent
  end?: number;           // when the response (or the error) arrived
  failed?: boolean;
}
export type Runs = Partial<Record<RunKey, RunTiming>>;

export type StepId = "retriever" | "you" | "engine" | "explainer" | "verifier" | "brief";
export type Actor = StepId | "system" | "analyst" | "presenter";
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
type Tone = "ok" | "warn" | "fail" | "info";
interface Line {
  text: string;
  status?: "ok" | "fail" | "skip" | "info";
}
interface Kid {
  key: string;
  label: string;
  sub?: string;
  tone?: Tone;
  body: ReactNode;
}
interface FlowNode {
  id: StepId;
  title: string;
  who: string;
  state: NodeState;
  run?: RunTiming;
  about: string;          // what the step does
  summary?: string;       // one line on the card once it has a result
  lines: Line[];          // what it actually did (popup)
  kids: Kid[];            // child nodes added from the response
  handover?: string;
  note?: string;
}

const MAX_KIDS = 3;

const STATE_TEXT: Record<NodeState, string> = {
  waiting: "Not started", running: "Running", wait: "Your turn", done: "Done", off: "Not available", error: "Failed", stale: "Out of date",
};

export const ACTOR_LABEL: Record<Actor, string> = {
  you: "You", retriever: "Retriever agent", engine: "Decision engine", explainer: "Explainer agent", verifier: "Verifier agent",
  brief: "Brief", system: "System", analyst: "Competitor analyst", presenter: "Presenter agent",
};

const RULE_TEXT: Record<string, string> = {
  citations: "Each sentence cites at least one fact, and every cited fact exists.",
  numbers: "Every number in the sentence equals a value in a cited fact.",
  labels: "Labels such as 'Consider' or 'Mixed' appear in a cited fact.",
  quotes: "Quoted text is copied word for word from a cited customer comment.",
  scope: "Every series and market the sentence names is covered by a cited fact.",
  semantic: "A language model judges whether the cited facts really support the sentence.",
};

const ICON_PATHS: Record<Actor, ReactNode> = {
  you: (<><circle cx="12" cy="8" r="3.4" /><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" /></>),
  retriever: (<><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.3-4.3" /></>),
  engine: (<><path d="M17 5H7l5 7-5 7h10" /></>),
  explainer: (<><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M13.5 6.5l4 4" /></>),
  verifier: (<><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" /><path d="M9 12l2 2 4-4" /></>),
  brief: (<><path d="M6 3h9l4 4v14H6z" /><path d="M15 3v4h4" /><path d="M9 12h7M9 16h7" /></>),
  system: (<><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>),
  analyst: (<><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>),
  presenter: (<><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M12 16v4M8 20h8" /></>),
};

export function ActorIcon({ actor, size = 16 }: { actor: Actor; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true">
      {ICON_PATHS[actor]}
    </svg>
  );
}

export const secs = (ms: number) => `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
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

const Rows = ({ rows }: { rows: [string, ReactNode][] }) => (
  <dl className="pop__kv">
    {rows.map(([k, v]) => (
      <div key={k}>
        <dt>{k}</dt>
        <dd>{v}</dd>
      </div>
    ))}
  </dl>
);

function buildNodes(p: Props): FlowNode[] {
  const { status, phase, interp, draft, evaluation, explained, explainState, explainError, runs, interpretError, evaluateError } = p;
  const llm = Boolean(status?.llm_configured);
  const m = status?.models ?? {};

  // 1 retriever
  const retriever: FlowNode = {
    id: "retriever", title: "Match the idea", who: interp ? interp.method.replace(/^llm:/, "") : llm ? m.retriever ?? "LLM" : "rules (no API key)",
    state: phase === "interpreting" ? "running" : interp ? "done" : interpretError ? "error" : "waiting", run: runs.interpret,
    about: "Finds the features in the customer data that your idea is about.",
    lines: [], kids: [], note: interpretError ?? undefined,
  };
  if (interp) {
    const picked = new Set(interp.spec.features.map((f) => f.feature));
    const nClass = interp.candidates.filter((c) => c.methods.classifier !== undefined).length;
    const nSem = interp.candidates.filter((c) => c.methods.semantic !== undefined).length;
    retriever.summary = `Picked ${interp.spec.features.length} of ${interp.candidates.length} candidates`;
    retriever.lines.push({ text: `Text classifier proposed ${plural(nClass, "candidate")}`, status: "ok" });
    retriever.lines.push(interp.semantic_error
      ? { text: `Embeddings unavailable: ${interp.semantic_error}`, status: "fail" }
      : { text: `${interp.semantic_method} proposed ${plural(nSem, "candidate")}`, status: "ok" });
    retriever.lines.push({ text: `${interp.method.startsWith("llm:") ? interp.method.slice(4) : "Rules"} picked ${plural(interp.spec.features.length, "feature")}`, status: interp.spec.features.length ? "ok" : "info" });
    for (const a of interp.attempts)
      retriever.lines.push({ text: `Schema check, attempt ${a.attempt}: ${a.ok ? "passed" : `failed (${a.errors[0] ?? "invalid"})`}`, status: a.ok ? "ok" : "fail" });
    const sorted = [...interp.candidates].sort((a, b) => Number(picked.has(b.feature)) - Number(picked.has(a.feature)));
    retriever.kids = sorted.map((c) => ({
      key: c.feature, label: c.feature, sub: picked.has(c.feature) ? "Picked" : `${c.verdict}, ${fmtInt(c.n_comments)} comments`,
      tone: picked.has(c.feature) ? "ok" : "info",
      body: <Rows rows={[["Area", c.domain], ["Customers", `${c.verdict}, ${fmtInt(c.n_comments)} comments`], ["Found by", c.how.join(", ")],
        ["Chosen", picked.has(c.feature) ? "Yes, by the retriever" : "No"]]} />,
    }));
    retriever.handover = `Idea spec with ${plural(interp.spec.features.length, "feature")}`;
  }

  // 2 you confirm the scope
  const spec: IdeaSpec | null = evaluation?.spec ?? draft;
  const confirmed = phase === "evaluating" || phase === "done";
  const you: FlowNode = {
    id: "you", title: "Confirm the scope", who: "Product manager",
    state: phase === "review" ? "wait" : confirmed && interp ? "done" : "waiting",
    about: "You check what will be evaluated before anything is computed.",
    lines: [], kids: [],
  };
  if (spec && interp) {
    you.summary = phase === "review" ? "Check and confirm in the side panel" : "Scope confirmed";
    const feats = spec.features.length ? spec.features.map((f) => f.feature).join(", ") : "No feature selected";
    you.lines.push({ text: feats, status: spec.features.length ? "ok" : "info" });
    you.lines.push({ text: seriesText(spec.series), status: "info" });
    you.lines.push({ text: marketsText(spec.markets), status: "info" });
    you.lines.push({ text: MOVE_LABELS[spec.move] ?? spec.move, status: "info" });
    you.kids = [
      { key: "f", label: "Features", sub: feats, tone: "info", body: <p>{feats}</p> },
      { key: "s", label: "Series and markets", sub: `${seriesText(spec.series)}; ${marketsText(spec.markets)}`, tone: "info",
        body: <Rows rows={[["Series", seriesText(spec.series)], ["Markets", marketsText(spec.markets)]]} /> },
      { key: "m", label: "Move", sub: `${MOVE_LABELS[spec.move] ?? spec.move}${spec.proposed_price_eur ? `, EUR ${fmtInt(spec.proposed_price_eur)}` : ""}`, tone: "info",
        body: <p>{MOVE_LABELS[spec.move] ?? spec.move}{spec.proposed_price_eur ? ` at EUR ${fmtInt(spec.proposed_price_eur)}` : ", no price proposed"}.</p> },
    ];
    if (confirmed) you.handover = "Confirmed scope";
  }

  // 3 decision engine
  const engine: FlowNode = {
    id: "engine", title: "Compute the evidence", who: "Deterministic, no LLM",
    state: phase === "evaluating" ? "running" : evaluation ? "done" : evaluateError ? "error" : "waiting", run: runs.evaluate,
    about: "Scores every series and market from the data and records each number with its source.",
    lines: [], kids: [], note: evaluateError ?? undefined,
  };
  if (evaluation) {
    const r = evaluation.result;
    const cells = r.features.reduce((n, f) => n + f.cells.length, 0);
    const kinds = new Map<string, number>();
    for (const f of evaluation.facts) kinds.set(f.source.kind, (kinds.get(f.source.kind) ?? 0) + 1);
    const kindText = [...kinds.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => `${n} ${k}`).join(", ");
    engine.summary = `${plural(evaluation.facts.length, "fact")}, ${plural(evaluation.graph.n_cited, "graph node")}`;
    engine.lines.push({ text: cells ? `Scored ${plural(cells, "series × market cell")}` : "No direct evidence to score", status: cells ? "ok" : "info" });
    engine.lines.push({ text: `Wrote ${plural(evaluation.facts.length, "fact")}: ${kindText}`, status: "ok" });
    engine.lines.push({ text: `Cited ${plural(evaluation.graph.n_cited, "graph node")}`, status: "ok" });
    engine.lines.push({ text: `Policy ${r.policy_hash}, data ${r.data_hash}`, status: "info" });
    for (const f of r.features) {
      const g = groupCells(f);
      for (const k of REC_ORDER) {
        const cs = g.get(k);
        if (!cs?.length || k === "notsold") continue;
        engine.kids.push({
          key: `${f.feature}|${k}`, label: REC_INFO[k].label, sub: `${r.features.length > 1 ? `${f.feature}: ` : ""}${plural(cs.length, "place")}`,
          tone: k === "prioritise" || k === "consider" ? "ok" : k === "low" ? "info" : "warn",
          body: <><p>{REC_INFO[k].meaning}</p><p className="pop__muted">{placesText(cs)}.</p></>,
        });
      }
    }
    engine.kids.push({
      key: "sources", label: "Fact sources", sub: kindText, tone: "info",
      body: <><p>{plural(evaluation.facts.length, "fact")} from: {kindText}.</p>
        <ul className="pop__list">{evaluation.facts.slice(0, 4).map((f) => <li key={f.id}>{f.statement}<span className="pop__muted"> ({f.source.kind}: {f.source.ref})</span></li>)}</ul></>,
    });
    engine.handover = `${plural(evaluation.facts.length, "fact")} with sources`;
  }

  // 4 + 5 explainer and verifier share one request
  const agentState: NodeState = explainState === "running" ? "running" : explainState === "done" ? "done" : explainState === "unavailable" ? "off"
    : explainState === "error" ? "error" : explainState === "stale" ? "stale" : "waiting";
  const explainer: FlowNode = {
    id: "explainer", title: "Write the brief", who: explained ? explained.explanation.model : llm ? m.explainer ?? "LLM" : "needs an OpenAI key",
    state: agentState, run: runs.explain, about: "Writes the brief from the facts only; every sentence cites its facts.",
    lines: [], kids: [], note: agentState === "off" || agentState === "error" ? explainError ?? undefined : agentState === "stale" ? "The policy changed after this brief was written." : undefined,
  };
  const verifier: FlowNode = {
    id: "verifier", title: "Check every sentence", who: explained ? `rules + ${explained.verification.semantic_model ?? "LLM"}` : llm ? `rules + ${m.verifier ?? "LLM"}` : "needs an OpenAI key",
    state: agentState, run: runs.explain, about: "Checks each sentence against the facts; failures are rewritten once, then removed.",
    lines: [], kids: [], note: agentState === "running" ? "Runs in the same request as the explainer." : undefined,
  };
  if (explained) {
    const v = explained.verification;
    const secsWith = Object.entries(explained.explanation.sections).filter(([, c]) => c.length);
    explainer.summary = `${plural(v.claims.length, "sentence")} in ${plural(secsWith.length, "section")}`;
    explainer.lines.push({ text: `Drafted ${plural(v.claims.length, "claim")}${explained.explanation.attempts > 1 ? " in the final draft" : ""}`, status: "ok" });
    explainer.lines.push({ text: `Covered ${plural(secsWith.length, "section")}`, status: "ok" });
    explainer.lines.push(explained.explanation.attempts > 1
      ? { text: `Rewrote after feedback (draft ${explained.explanation.attempts})`, status: "ok" }
      : { text: "No rewrite needed", status: "skip" });
    const SEC: Record<string, string> = { headline: "Short answer", customer_evidence: "What customers say", market_view: "Where it matters",
      price_and_equipment: "Price and equipment", risks_and_caveats: "What to watch out for", next_steps: "What to do next" };
    explainer.kids = secsWith.map(([k, cl]) => ({
      key: k, label: SEC[k] ?? k, sub: plural(cl.length, "sentence"), tone: "ok",
      body: <ul className="pop__list">{cl.map((c) => <li key={c.id}>{c.text}</li>)}</ul>,
    }));
    explainer.handover = `${plural(v.claims.length, "sentence")} with fact IDs`;

    verifier.summary = `${fmtInt(v.n_verified)} verified, ${fmtInt(v.n_removed)} removed`;
    if (v.rewritten.length)
      verifier.kids.push({
        key: "rewrite", label: "Sent back once", sub: plural(v.rewritten.length, "sentence"), tone: "warn",
        body: <><p>These failed a check in the first draft and were rewritten:</p>
          <ul className="pop__list">{v.rewritten.map((c) => <li key={c.id}>{c.text}<span className="pop__muted"> ({c.checks.filter((k) => !k.passed).map((k) => k.name).join(", ")})</span></li>)}</ul></>,
      });
    for (const rule of v.rules) {
      const checked = v.claims.flatMap((c) => c.checks.filter((k) => k.name === rule).map((k) => ({ c, k })));
      if (!checked.length) continue;
      const failed = checked.filter((x) => !x.k.passed);
      verifier.lines.push({ text: `${rule[0].toUpperCase()}${rule.slice(1)}: ${checked.length - failed.length} of ${checked.length} passed`, status: failed.length ? "fail" : "ok" });
      verifier.kids.push({
        key: rule, label: `${rule[0].toUpperCase()}${rule.slice(1)}`, sub: `${checked.length - failed.length} of ${checked.length} passed`, tone: failed.length ? "fail" : "ok",
        body: <><p>{RULE_TEXT[rule] ?? rule}</p>{failed.length > 0 && <ul className="pop__list">{failed.map(({ c, k }) => <li key={c.id}>{c.text}<span className="pop__muted"> ({k.detail})</span></li>)}</ul>}</>,
      });
    }
    verifier.lines.push(v.rewritten.length ? { text: `${plural(v.rewritten.length, "claim")} sent back for one rewrite`, status: "fail" } : { text: "Rewrite round skipped", status: "skip" });
    verifier.lines.push({ text: `${fmtInt(v.n_verified)} verified, ${fmtInt(v.n_removed)} removed`, status: v.n_removed ? "fail" : "ok" });
    verifier.handover = plural(v.n_verified, "verified sentence");
  }

  // 6 brief
  const brief: FlowNode = {
    id: "brief", title: "Your decision", who: "Report and decision log",
    state: explainState === "done" ? "done" : explainState === "stale" ? "stale"
      : (explainState === "unavailable" || explainState === "error") && evaluation ? "off" : "waiting",
    about: "Read the report below and record your decision in the side panel.",
    lines: [], kids: [],
  };
  if (evaluation && (explainState === "done" || explainState === "unavailable" || explainState === "error" || explainState === "stale")) {
    brief.summary = explainState === "done" ? "Report ready, decide in the side panel" : "Numbers ready, brief missing";
    for (const f of evaluation.result.features) {
      const bl = bottomLine(f);
      brief.kids.push({ key: f.feature, label: "Short answer", sub: f.feature, tone: bl.tone === "go" || bl.tone === "maybe" ? "ok" : "info",
        body: <><p>{bl.text}</p>{f.rollup.score !== null && <p className="pop__muted">Priority score {fmtNum(f.rollup.score)} of 1.</p>}</> });
    }
  }
  if (explained) {
    brief.lines.push({ text: `${plural(explained.verification.n_verified, "verified sentence")} in the brief`, status: "ok" });
    brief.lines.push({ text: `Agents took ${explained.seconds.toFixed(1)} s on the server`, status: "info" });
    if (runs.interpret?.end && runs.explain?.end) brief.lines.push({ text: `${secs(runs.explain.end - runs.interpret.start)} from idea to brief, including your review`, status: "info" });
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
  selected: StepId;
  onSelect: (id: StepId) => void;
}

interface Pop {
  anchor: HTMLElement;
  title: string;
  sub?: string;
  body: ReactNode;
}

export default function ProcessFlow(props: Props) {
  const nodes = buildNodes(props);
  const running = nodes.some((n) => n.state === "running");
  const now = useNow(running);
  const { trace, idea, selected, onSelect } = props;
  const t0 = trace[0]?.at ?? 0;
  const complete = props.explainState === "done";
  const waiting = props.phase === "review";
  const [pop, setPop] = useState<Pop | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const [showKids, setShowKids] = useState(() => window.innerHeight >= 800);   // short windows start compact

  const headline = complete ? "How this result was produced" : waiting ? "Your turn: confirm the scope" : running ? "Working on your idea" : "Process";
  const elapsed = (r?: RunTiming) => (r ? secs((r.end ?? now) - r.start) : null);
  const open = (el: HTMLElement, p: Omit<Pop, "anchor">) => setPop((cur) => (cur?.anchor === el ? null : { anchor: el, ...p }));

  const cardBody = (n: FlowNode) => (
    <>
      <p className="pop__muted">{n.who}</p>
      <p>{n.about}</p>
      {n.lines.length > 0 && (
        <ul className="fnode__lines">
          {n.lines.map((l, j) => (
            <li key={j} className={`fline fline--${l.status ?? "info"}`}>
              <span className="fline__mark" aria-hidden />
              <span>{l.text}</span>
            </li>
          ))}
        </ul>
      )}
      {n.handover && <p className="fnode__handover">Hands over: {n.handover}</p>}
      {n.note && <p className="fnode__note">{n.note}</p>}
    </>
  );

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
        <div className="flow__tools">
          <p className="flow__status" role="status" aria-live="polite">
            {nodes.filter((n) => n.state === "done").length} of {nodes.length} steps done
          </p>
          <button type="button" className="flow__toggle" aria-pressed={!showKids} onClick={() => setShowKids((v) => !v)}>
            {showKids ? "Hide step results" : "Show step results"}
          </button>
        </div>
      </div>

      <div className="flow__body">
        <ol className="flow__lane">
          {nodes.map((n, i) => {
            const next = nodes[i + 1];
            const edge = !next ? null : n.state === "done" && (next.state === "running" || next.state === "wait") ? "active" : n.state === "done" ? "done" : "idle";
            const time = elapsed(n.run);
            const shown = n.kids.slice(0, MAX_KIDS);
            const more = n.kids.slice(MAX_KIDS);
            return (
              <li key={n.id} className={`fcol ${selected === n.id ? "fcol--selected" : ""}`}>
                <button
                  type="button"
                  className={`fnode fnode--${n.state} fnode--${n.id}`}
                  aria-pressed={selected === n.id}
                  aria-label={`Step ${i + 1}, ${n.title}: ${STATE_TEXT[n.state]}. Show in the side panel.`}
                  onClick={(e) => {
                    onSelect(n.id);
                    open(e.currentTarget, { title: `${i + 1}. ${n.title}`, sub: `${ACTOR_LABEL[n.id]}, ${STATE_TEXT[n.state].toLowerCase()}${time ? `, ${time}` : ""}`, body: cardBody(n) });
                  }}
                >
                  <span className="fnode__head">
                    <span className="fnode__icon"><ActorIcon actor={n.id} /></span>
                    <span className="fnode__state">
                      {n.state === "running" ? <span className="spinner spinner--sm" aria-hidden /> : <span className="fnode__dot" aria-hidden />}
                      {STATE_TEXT[n.state]}
                    </span>
                  </span>
                  <span className="fnode__title">{n.title}</span>
                  <span className="fnode__sum">{n.summary ?? (n.state === "running" ? "Request open" : n.about)}</span>
                  {time && (n.state === "running" || n.state === "done" || n.state === "error") && <span className="fnode__time num">{time}</span>}
                </button>
                {edge && (
                  <span className={`fedge fedge--${edge}`} aria-hidden>
                    <svg viewBox="0 0 40 16" preserveAspectRatio="none"><line x1="0" y1="8" x2="32" y2="8" /><path d="M30 3l7 5-7 5" /></svg>
                  </span>
                )}
                {showKids && n.kids.length > 0 && (
                  <ul className="fkids" aria-label={`Results of step ${i + 1}`}>
                    {shown.map((k) => (
                      <li key={k.key}>
                        <button type="button" className={`fkid fkid--${k.tone ?? "info"}`} aria-haspopup="dialog"
                          aria-expanded={pop?.title === k.label && pop?.sub === k.sub}
                          onClick={(e) => open(e.currentTarget, { title: k.label, sub: k.sub, body: k.body })}>
                          <span className="fkid__label">{k.label}</span>
                          {k.sub && <span className="fkid__sub">{k.sub}</span>}
                        </button>
                      </li>
                    ))}
                    {more.length > 0 && (
                      <li>
                        <button type="button" className="fkid fkid--more" aria-haspopup="dialog"
                          onClick={(e) => open(e.currentTarget, {
                            title: `${n.title}: ${more.length} more`, body: (
                              <ul className="pop__list">{more.map((k) => <li key={k.key}><strong>{k.label}</strong>{k.sub ? <span className="pop__muted"> {k.sub}</span> : null}</li>)}</ul>
                            ),
                          })}>
                          + {more.length} more
                        </button>
                      </li>
                    )}
                  </ul>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      <details className="flog" open={logOpen} onToggle={(e) => setLogOpen((e.target as HTMLDetailsElement).open)}>
        <summary>
          Request log <span className="flog__count num">{trace.length}</span>
          <span className="flog__hint">every request, answer, wait and error, with times</span>
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

      {pop && <Popup pop={pop} onClose={() => setPop(null)} />}
    </div>
  );
}

/** One popup, fixed to the viewport and placed next to its node, so the scrolling lane never clips it. */
function Popup({ pop, onClose }: { pop: Pop; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const place = () => {
      const a = pop.anchor.getBoundingClientRect();
      const el = ref.current;
      if (!el) return;
      const w = el.offsetWidth, h = el.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
      const left = Math.min(Math.max(8, a.left), vw - w - 8);
      const below = a.bottom + 8;
      const top = below + h <= vh - 8 ? below : Math.max(8, a.top - h - 8);
      setPos({ left, top });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, { capture: true, passive: true });   // follow the node, including inside the lane
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, { capture: true });
    };
  }, [pop]);

  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node) && !pop.anchor.contains(e.target as Node)) onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        pop.anchor.focus();
      }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [pop, onClose]);

  return (
    <div ref={ref} className="pop" role="dialog" aria-label={pop.title} style={pos ? { left: pos.left, top: pos.top } : { visibility: "hidden", left: 0, top: 0 }}>
      <div className="pop__head">
        <div>
          <p className="pop__title">{pop.title}</p>
          {pop.sub && <p className="pop__sub">{pop.sub}</p>}
        </div>
        <button type="button" className="pop__close" onClick={onClose} aria-label="Close">×</button>
      </div>
      <div className="pop__body">{pop.body}</div>
    </div>
  );
}
