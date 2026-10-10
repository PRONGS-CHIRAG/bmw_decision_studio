import { MODEL_NAMES, fmtEur, fmtNum } from "../api";
import type { Fitment } from "../types";
import { Fitment as FitGlyph, tierLabel } from "./marks";

/** How the same feature is offered across the three series in the DE price lists. */
export default function PriceLadder({ ladder }: { ladder: Fitment[] }) {
  if (!ladder.some((l) => l.tier !== "no_link")) {
    return (
      <p className="small muted">
        This feature has no curated link to the price lists, so availability and price are not shown.
      </p>
    );
  }
  return (
    <div className="specs">
      {ladder.map((l) => (
        <div key={l.model} className="spec">
          <p className="spec__label">
            {MODEL_NAMES[l.model ?? ""]} ({l.model})
          </p>
          <p className="spec__value">
            {l.tier === "optional" && l.price_min_eur ? fmtEur(l.price_min_eur) : shortTier(l.tier)}
          </p>
          <div className="row small" style={{ gap: 8 }}>
            <FitGlyph tier={l.tier} />
            <span>{tierLabel(l.tier)}</span>
          </div>
          {l.tier === "optional" && l.price_item && (
            <p className="small">
              Cheapest listed: {l.price_item}
              {l.price_via_package ? " (a package with other equipment)" : ""}
            </p>
          )}
          {l.n_variants !== undefined && (
            <p className="caption">
              Standard on {l.n_standard} and optional on {l.n_optional} of {l.n_variants} variants in the equipment tables
              {l.price_pct_of_base ? `; the option costs as little as ${fmtNum(l.price_pct_of_base, 1)}% of a variant's base price` : ""}
            </p>
          )}
          {l.items.length > 0 && (
            <p className="caption">
              {l.items
                .slice(0, 3)
                .map((i) => `${i.name}${i.sa_code ? ` (SA ${i.sa_code})` : ""}, p.${i.page}`)
                .join("; ")}
              {l.items.length > 3 ? `; and ${l.items.length - 3} more` : ""}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function shortTier(tier: string) {
  return (
    {
      standard_all: "Standard",
      standard_some: "Partly standard",
      optional: "Optional",
      not_listed: "Not listed",
      no_link: "No link",
    } as Record<string, string>
  )[tier] ?? tier;
}
