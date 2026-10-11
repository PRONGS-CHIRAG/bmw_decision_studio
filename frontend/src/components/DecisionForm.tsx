import { useRef, useState } from "react";
import { postJSON } from "../api";
import { decisionProblem, type DecisionProblem } from "../decisionCheck";
import type { Decision, EvaluateResult, FeatureResult } from "../types";

const PM_KEY = "pds.pm-name";
/** Fired after a decision, status or review is recorded, so the Tracker count refreshes. */
export const TRACKER_CHANGED = "tracker:changed";

export function storedName() {
  try {
    return localStorage.getItem(PM_KEY) ?? "";
  } catch {
    return "";
  }
}

export function storeName(name: string) {
  try {
    localStorage.setItem(PM_KEY, name);
  } catch {
    /* storage unavailable: the name is just not remembered */
  }
}

/** Accept or override the system's recommendation; stored with the policy and data hashes. */
export default function DecisionForm({ result, feature }: { result: EvaluateResult; feature: FeatureResult }) {
  const [pm, setPm] = useState(storedName);
  const [decision, setDecision] = useState<"accept" | "override">("accept");
  const [rationale, setRationale] = useState("");
  const [saved, setSaved] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<DecisionProblem | null>(null);
  const pmRef = useRef<HTMLInputElement>(null);
  const whyRef = useRef<HTMLTextAreaElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    // the button stays clickable; a missing field is named and focused instead of silently blocking the click
    const p = decisionProblem(pm, rationale);
    setProblem(p);
    if (p) {
      (p.field === "pm" ? pmRef : whyRef).current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      storeName(pm);
      const entry = await postJSON<Decision>("/api/decisions", {
        pm,
        idea: result.idea || feature.feature,
        feature: feature.feature,
        decision,
        rationale,
        system_recommendation: {
          headline: feature.headline,
          rollup_score: feature.rollup.score,
          cells: feature.cells.map((c) => ({ model: c.model, market: c.market, recommendation: c.recommendation, score: c.score })),
        },
        policy: result.policy,
        policy_hash: result.policy_hash,
        data_hash: result.data_hash,
        scope: { models: result.models, markets: result.markets },   // the server stores the tracker baseline from it
      });
      setSaved(entry);
      window.dispatchEvent(new Event(TRACKER_CHANGED));
      setRationale("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="decision-form" onSubmit={submit} noValidate aria-labelledby={`decide-${feature.feature}`}>
      <h3 id={`decide-${feature.feature}`}>Record your decision on {feature.feature}</h3>
      <p className="small muted measure">
        The log keeps your decision next to the system's recommendation, the policy ({result.policy_hash}) and the data
        version ({result.data_hash}), so anyone can see where a PM followed or overrode the evidence and why.
      </p>
      <div className="decision-form__grid">
        <div className="field">
          <label htmlFor={`pm-${feature.feature}`}>Your name</label>
          <input id={`pm-${feature.feature}`} ref={pmRef} className="input" value={pm} required aria-invalid={problem?.field === "pm" || undefined}
            onChange={(e) => { setPm(e.target.value); setProblem(null); }} />
        </div>
        <div className="field">
          <span className="label">Decision</span>
          <div className="row" style={{ gap: 12 }} role="radiogroup">
            {(["accept", "override"] as const).map((d) => (
              <button
                type="button"
                key={d}
                className="tile tile--compact"
                aria-pressed={decision === d}
                role="radio"
                aria-checked={decision === d}
                onClick={() => setDecision(d)}
              >
                <span className="tile__title">{d === "accept" ? "Follow the recommendation" : "Override it"}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="field">
        <label htmlFor={`why-${feature.feature}`}>Rationale</label>
        <textarea
          id={`why-${feature.feature}`}
          className="textarea"
          ref={whyRef}
          value={rationale}
          onChange={(e) => { setRationale(e.target.value); setProblem(null); }}
          aria-invalid={problem?.field === "rationale" || undefined}
          placeholder={decision === "override" ? "What do you know that the data does not show?" : "Why does this recommendation hold?"}
          required
          minLength={3}
        />
      </div>
      <div className="row">
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Recording…" : "Record decision"}
        </button>
        {saved && (
          <p className="small" role="status">
            Decision recorded as {saved.id} at {new Date(saved.recorded_at).toLocaleString("en-GB")}. It now appears in the Tracker.
          </p>
        )}
        {problem && <p className="small error" role="alert">Not recorded yet: {problem.message}</p>}
        {error && <p className="small error">Not recorded: {error}</p>}
      </div>
    </form>
  );
}
