import type { Claim, Explained, Fact } from "../types";

const RULE_NAMES: Record<string, string> = {
  citations: "Citations",
  numbers: "Numbers",
  labels: "Labels",
  quotes: "Quotes",
  scope: "Series / market",
  semantic: "Entailment",
};
const SECTION_NAMES: Record<string, string> = {
  headline: "Bottom line",
  customer_evidence: "Customers",
  market_view: "Markets",
  price_and_equipment: "Price",
  risks_and_caveats: "Risks",
  next_steps: "Next steps",
};

/** Agent 3's report: every claim, every check, what was rewritten and what was removed. */
export default function VerificationReport({ explained, facts }: { explained: Explained | null; facts: Fact[] }) {
  if (!explained) return <p className="small muted">The report appears once the explainer and verifier have run.</p>;
  const v = explained.verification;
  const index = new Map(facts.map((f) => [f.id, f]));
  return (
    <div className="stack-lg">
      <div className="facts-row">
        <Fig label="Verified claims" value={String(v.n_verified)} />
        <Fig label="Removed claims" value={String(v.n_removed)} />
        <Fig label="Failed in first draft" value={String(v.rewritten.length)} />
        <Fig label="Semantic checker" value={v.semantic_model ?? "–"} />
      </div>
      <p className="small measure">
        Each claim must cite facts from the decision engine. Rules check citations, numbers (at the precision written), recommendation
        and verdict labels, verbatim quotes and the series and markets named; the semantic checker then judges whether the cited facts
        entail the claim. Claims that fail are sent back for one rewrite and removed if they still fail.
      </p>
      <div className="table-scroll">
        <table className="table verify">
          <thead>
            <tr>
              <th>Status</th>
              <th>Section</th>
              <th>Claim</th>
              {v.rules.map((r) => (
                <th key={r} className="verify__rule">
                  {RULE_NAMES[r] ?? r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {v.claims.map((c) => (
              <Row key={c.id} claim={c} rules={v.rules} index={index} />
            ))}
          </tbody>
        </table>
      </div>
      {v.rewritten.length > 0 && (
        <details>
          <summary>First-draft claims that failed and triggered the rewrite ({v.rewritten.length})</summary>
          <ul className="bullets small" style={{ marginTop: 12 }}>
            {v.rewritten.map((c) => (
              <li key={c.id}>
                “{c.text}” —{" "}
                {c.checks
                  .filter((ch) => !ch.passed)
                  .map((ch) => `${RULE_NAMES[ch.name] ?? ch.name}: ${ch.detail}`)
                  .join(" ")}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Row({ claim, rules, index }: { claim: Claim; rules: string[]; index: Map<string, Fact> }) {
  const byName = new Map(claim.checks.map((c) => [c.name, c]));
  const removed = claim.status === "removed";
  return (
    <tr className={removed ? "verify__removed" : undefined}>
      <td>
        <span className={`pill ${removed ? "pill--error" : "pill--success"}`}>{removed ? "Removed" : "Verified"}</span>
      </td>
      <td className="caption">{SECTION_NAMES[claim.section] ?? claim.section}</td>
      <td>
        <p className="verify__text">{claim.text}</p>
        <p className="caption" title={claim.fact_ids.map((i) => `${i}: ${index.get(i)?.statement ?? "unknown"}`).join("\n")}>
          Cites {claim.fact_ids.length ? claim.fact_ids.join(", ") : "nothing"}
        </p>
        {removed && (
          <p className="caption error">
            {claim.checks
              .filter((c) => !c.passed)
              .map((c) => c.detail)
              .join(" ")}
          </p>
        )}
      </td>
      {rules.map((r) => {
        const ch = byName.get(r);
        return (
          <td key={r} className="verify__cell" title={ch ? ch.detail : "Not run (an earlier check failed)"}>
            {ch ? (
              <span className={ch.passed ? "tick" : "cross"} aria-label={`${r}: ${ch.passed ? "passed" : "failed"}. ${ch.detail}`} />
            ) : (
              <span className="caption" aria-label={`${r}: not run`}>
                –
              </span>
            )}
          </td>
        );
      })}
    </tr>
  );
}

function Fig({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="techfact__label">{label}</p>
      <p className="techfact__value num">{value}</p>
    </div>
  );
}
