import { useState } from "react";
import { postJSON } from "../api";
import type { Decision, EvaluateResult, FeatureResult } from "../types";

const PM_KEY = "pds.pm-name";

function storedName() {
  try {
    return localStorage.getItem(PM_KEY) ?? "";
  } catch {
    return "";
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      try {
        localStorage.setItem(PM_KEY, pm);
      } catch {
        /* storage unavailable: the name is just not remembered */
      }
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
      });
      setSaved(entry);
      setRationale("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="decision-form" onSubmit={submit} aria-labelledby={`decide-${feature.feature}`}>
      <h3 id={`decide-${feature.feature}`}>Record your decision on {feature.feature}</h3>
      <p className="small muted measure">
        The log keeps your decision next to the system's recommendation, the policy ({result.policy_hash}) and the data
        version ({result.data_hash}), so anyone can see where a PM followed or overrode the evidence and why.
      </p>
      <div className="decision-form__grid">
        <div className="field">
          <label htmlFor={`pm-${feature.feature}`}>Your name</label>
          <input id={`pm-${feature.feature}`} className="input" value={pm} onChange={(e) => setPm(e.target.value)} required />
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
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          placeholder={decision === "override" ? "What do you know that the data does not show?" : "Why does this recommendation hold?"}
          required
          minLength={3}
        />
      </div>
      <div className="row">
        <button className="btn" type="submit" disabled={busy || !pm.trim() || rationale.trim().length < 3}>
          {busy ? "Recording…" : "Record decision"}
        </button>
        {saved && (
          <p className="small" role="status">
            Decision recorded as {saved.id} at {new Date(saved.recorded_at).toLocaleString("en-GB")}.
          </p>
        )}
        {error && <p className="small error">Not recorded: {error}</p>}
      </div>
    </form>
  );
}
