import { useEffect, useRef, useState } from "react";
import type { Claim, Explained, Fact } from "../types";
import type { ExplainState } from "./ProcessFlow";

const TITLES: Record<string, string> = {
  customer_evidence: "What customers say",
  market_view: "Where it matters",
  price_and_equipment: "Price and equipment today",
  risks_and_caveats: "Risks and limits of the evidence",
  next_steps: "Recommended next steps",
};

/** Citation numbers in order of first use across the brief. */
export function citationNumbers(explained: Explained | null): Map<string, number> {
  const map = new Map<string, number>();
  if (!explained) return map;
  const order = ["headline", ...Object.keys(TITLES)];
  for (const s of order)
    for (const c of explained.explanation.sections[s] ?? []) for (const id of c.fact_ids) if (!map.has(id)) map.set(id, map.size + 1);
  return map;
}

export default function ExplanationView({
  explained,
  state,
  error,
  facts,
  onExplain,
  onShowNode,
}: {
  explained: Explained | null;
  state: ExplainState;
  error: string | null;
  facts: Fact[];
  onExplain: () => void;
  onShowNode: (id: string) => void;
}) {
  const index = new Map(facts.map((f) => [f.id, f]));
  const numbers = citationNumbers(explained);

  if (state === "running")
    return (
      <div className="explain explain--loading" role="status">
        <p className="small">The explainer is writing the brief; the verifier then checks every claim against the facts…</p>
        <div className="skeleton" style={{ width: "80%", height: 28 }} />
        <div className="skeleton" style={{ width: "60%" }} />
        <div className="skeleton" style={{ width: "70%" }} />
      </div>
    );
  if (state === "unavailable")
    return (
      <div className="note note--warn">
        <strong>The written explanation is not available.</strong> {error}
      </div>
    );
  if (state === "error")
    return (
      <div className="note note--error stack">
        <p>
          <strong>The explanation could not be produced.</strong> {error} Nothing unverified is shown.
        </p>
        <button className="btn btn--dark btn--small" onClick={onExplain}>
          Try again
        </button>
      </div>
    );
  if (state === "stale" || (!explained && state === "idle"))
    return (
      <div className="note note--info stack">
        <p>
          {state === "stale"
            ? "The decision policy changed, so the numbers above were recomputed. Generate the explanation again for them."
            : "Generate the written brief for this evaluation."}
        </p>
        <button className="btn btn--small" onClick={onExplain}>
          Generate explanation
        </button>
      </div>
    );
  if (!explained) return null;

  const s = explained.explanation.sections;
  const headline = s.headline ?? [];
  const v = explained.verification;
  return (
    <div className="explain">
      <div className="explain__headline">
        {headline.length ? (
          headline.map((c) => <ClaimText key={c.id} claim={c} numbers={numbers} index={index} onShowNode={onShowNode} />)
        ) : (
          <p className="small muted">The headline did not pass verification and was removed; see the verification report.</p>
        )}
      </div>
      <div className="explain__grid">
        {Object.entries(TITLES).map(([key, title]) =>
          (s[key] ?? []).length ? (
            <section key={key} className="card explain__card" aria-label={title}>
              <h3 className="explain__title">{title}</h3>
              <ul className="claims">
                {(s[key] ?? []).map((c) => (
                  <li key={c.id} className="claim">
                    <span className="claim__ok" title="Verified against the cited facts" aria-label="verified" />
                    <ClaimText claim={c} numbers={numbers} index={index} onShowNode={onShowNode} />
                  </li>
                ))}
              </ul>
            </section>
          ) : null,
        )}
      </div>
      <p className="disclaimer">
        Written by {explained.explanation.model}. {v.n_verified} claim{v.n_verified === 1 ? "" : "s"} passed the verifier (rules:{" "}
        {v.rules.join(", ")}; semantic check: {v.semantic_model}); {v.n_removed} removed
        {explained.explanation.attempts > 1 ? " after one rewrite of the first draft" : ""}. Numbers in brackets cite the facts each
        claim relies on.
      </p>
    </div>
  );
}

function ClaimText({
  claim,
  numbers,
  index,
  onShowNode,
}: {
  claim: Claim;
  numbers: Map<string, number>;
  index: Map<string, Fact>;
  onShowNode: (id: string) => void;
}) {
  return (
    <p className="claim__text">
      {claim.text}{" "}
      {claim.fact_ids.map((id) => (
        <Cite key={id} n={numbers.get(id) ?? 0} fact={index.get(id)} id={id} onShowNode={onShowNode} />
      ))}
    </p>
  );
}

function Cite({ n, fact, id, onShowNode }: { n: number; fact?: Fact; id: string; onShowNode: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  const src = fact?.source;
  return (
    <span className="cite" ref={ref}>
      <button type="button" className="cite__btn" aria-expanded={open} onClick={() => setOpen((o) => !o)} aria-label={`Source ${n}: ${id}`}>
        {n}
      </button>
      {open && (
        <span className="popover" role="dialog" aria-label={`Fact ${id}`}>
          <span className="popover__id">{id}</span>
          <span className="popover__text">{fact ? fact.statement : "This fact is not in the bundle."}</span>
          {src && (
            <span className="popover__src">
              {src.kind}: {src.ref}
              {src.key ? ` · ${src.key}` : ""}
              {src.page ? ` · page ${src.page}` : ""}
            </span>
          )}
          {src?.node_id && (
            <button
              type="button"
              className="textlink popover__link"
              onClick={() => {
                setOpen(false);
                onShowNode(src.node_id!);
              }}
            >
              Show in knowledge graph
            </button>
          )}
        </span>
      )}
    </span>
  );
}
