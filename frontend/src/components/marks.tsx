import { fmtNum } from "../api";

// Verdicts use a validated diverging scale: red = more complaints than expected,
// blue = fewer, grey = as expected. The label always accompanies the colour.
const VERDICT_COLORS: Record<string, string> = {
  Bad: "var(--div-red-strong)",
  "Leaning bad": "var(--div-red-light)",
  Mixed: "var(--div-mid)",
  "Leaning good": "var(--div-blue-light)",
  Good: "var(--div-blue-strong)",
  "Not enough data": "transparent",
};

export function Verdict({ verdict }: { verdict: string }) {
  const empty = verdict === "Not enough data";
  return (
    <span className="verdict">
      <span
        className="verdict__mark"
        style={{ background: VERDICT_COLORS[verdict] ?? "transparent", border: empty ? "1px dashed var(--muted-soft)" : "none" }}
        aria-hidden
      />
      {verdict}
    </span>
  );
}

const REC_CLASS: Record<string, string> = {
  Prioritise: "rec--prioritise",
  Consider: "rec--consider",
  "Low priority": "rec--low",
  "Insufficient evidence": "rec--insufficient",
  "Not sold": "rec--notsold",
};

export function Recommendation({ value }: { value: string }) {
  return (
    <span className={`rec ${REC_CLASS[value] ?? ""}`}>
      <span className="rec__mark" aria-hidden />
      {value}
    </span>
  );
}

// Price-list fitment in the PDFs' own notation: ■ standard, □ optional.
const TIER_TEXT: Record<string, [string, string]> = {
  standard_all: ["■", "Standard on all covered variants"],
  standard_some: ["■□", "Standard on some variants"],
  optional: ["□", "Optional extra"],
  not_listed: ["–", "No item in this series' price list matched the curated keywords"],
  no_link: ["", "No curated price-list link"],
  not_covered: ["?", "Variant not in the equipment tables"],
};

export function Fitment({ tier, withLabel = false }: { tier?: string | null; withLabel?: boolean }) {
  if (!tier) return <span className="muted" title="No curated price-list link">·</span>;
  const [glyph, label] = TIER_TEXT[tier] ?? ["", tier];
  return (
    <span title={label} className="row" style={{ gap: 6, display: "inline-flex" }}>
      <span className="fit" aria-hidden>{glyph}</span>
      {withLabel ? <span className="small">{label}</span> : <span className="sr-only">{label}</span>}
    </span>
  );
}

export function tierLabel(tier?: string | null) {
  return tier ? TIER_TEXT[tier]?.[1] ?? tier : "No curated price-list link";
}

/** Complaint index with its 95% interval on a log scale around 1.0 ("as expected"). */
export function IndexGlyph({
  index,
  low,
  high,
  verdict,
  width = 140,
}: {
  index: number;
  low: number;
  high: number;
  verdict: string;
  width?: number;
}) {
  const lo = Math.log(0.25);
  const hi = Math.log(4);
  const x = (v: number) => {
    const c = Math.min(Math.max(Math.log(Math.max(v, 0.01)), lo), hi);
    return 4 + ((c - lo) / (hi - lo)) * (width - 8);
  };
  const color = VERDICT_COLORS[verdict] && verdict !== "Not enough data" ? VERDICT_COLORS[verdict] : "var(--muted-soft)";
  return (
    <svg width={width} height={18} role="img" aria-label={`Complaint index ${fmtNum(index)}, 95% interval ${fmtNum(low)} to ${fmtNum(high)}`}>
      <line x1={x(1)} x2={x(1)} y1={1} y2={17} stroke="var(--hairline-strong)" strokeWidth={1} />
      <line x1={x(low)} x2={x(high)} y1={9} y2={9} stroke="var(--muted)" strokeWidth={2} strokeLinecap="round" />
      <circle cx={x(index)} cy={9} r={5} fill={color} stroke="#fff" strokeWidth={2} />
      <title>{`Complaint index ${fmtNum(index)} (95% CI ${fmtNum(low)}–${fmtNum(high)}); 1.0 = as expected for the channels`}</title>
    </svg>
  );
}

/** A single-series 0–1 bar (score or weight share), blue on a blue track. */
export function Meter({ value, width = 120, label }: { value: number | null; width?: number; label: string }) {
  const v = value === null ? 0 : Math.max(0, Math.min(1, value));
  return (
    <svg width={width} height={10} role="img" aria-label={`${label}: ${value === null ? "missing" : fmtNum(value)}`}>
      <rect x={0} y={1} width={width} height={8} fill={value === null ? "var(--surface-soft)" : "var(--data-blue-track)"} />
      {value !== null && <rect x={0} y={1} width={Math.max(v * width, v > 0 ? 3 : 0)} height={8} fill="var(--data-blue)" />}
    </svg>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="state" role="status">
      <p>Loading {what}…</p>
      <div className="skeleton" style={{ width: "60%" }} />
      <div className="skeleton" style={{ width: "40%" }} />
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="state">
      <p className="error">Could not load data: {message}</p>
      <p className="small">Check that the API is running: python -m bmw_feedback serve</p>
    </div>
  );
}

export function PageRef({ model, page }: { model: string; page: number }) {
  return (
    <span className="caption" title={`${model}_OptionList.PDF, page ${page}`}>
      {model} p.{page}
    </span>
  );
}
