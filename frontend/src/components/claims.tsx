import { useEffect, useRef, useState } from "react";
import type { Claim, Explained, Fact } from "../types";

export const TITLES: Record<string, string> = {
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

export function ClaimText({
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
