import { fromPercents, rebalance, toPercents } from "../weights";

const SIGNAL_SHORT: Record<string, string> = { complaints: "Complaints", breadth: "Breadth", requests: "Requests", survey: "Survey" };
const SIGNAL_HINT: Record<string, string> = {
  complaints: "more complaints than a typical topic",
  breadth: "how many customers raise it",
  requests: "customers asking for it",
  survey: "rated weakly in the customer study",
};
const SIGNAL_COLOR: Record<string, string> = {
  complaints: "var(--coral)", breadth: "var(--data-blue)", requests: "var(--apricot)", survey: "var(--violet)",
};
const STEP = 5;

/** "Complaints 40% · Breadth 20% · …" for a set of weights. */
export function weightSummary(weights: Record<string, number>) {
  const p = toPercents(weights, STEP);
  return Object.keys(p).map((k) => `${SIGNAL_SHORT[k] ?? k} ${p[k]}%`).join(" · ");
}

/**
 * Linked sliders for the signal weights. They always add up to exactly 100%: moving one gives or takes the
 * difference from the others in proportion to their shares (see ../weights.ts).
 */
export default function WeightSliders({
  weights,
  defaults,
  onChange,
  idPrefix = "w",
}: {
  weights: Record<string, number>;
  defaults: Record<string, number>;
  onChange: (w: Record<string, number>) => void;
  idPrefix?: string;
}) {
  const p = toPercents(weights, STEP);
  const d = toPercents(defaults, STEP);
  const keys = Object.keys(p);
  const total = keys.reduce((a, k) => a + p[k], 0);
  const isDefault = keys.every((k) => p[k] === d[k]);

  return (
    <div className="weights">
      <div className="weights__bar" role="img" aria-label={`Weights: ${weightSummary(weights)}. Total ${total}%.`}>
        {keys.map((k) =>
          p[k] > 0 ? (
            <span key={k} className="weights__seg" style={{ flexGrow: p[k], background: SIGNAL_COLOR[k] ?? "var(--muted)" }}>
              {p[k] >= 10 && <span className="weights__seglabel">{p[k]}%</span>}
            </span>
          ) : null,
        )}
      </div>
      <p className="weights__total small">
        <span className="weights__check" aria-hidden>✓</span> Total <strong className="num">{total}%</strong>, always 100%. Moving one
        signal shares the difference among the others.
      </p>

      {keys.map((k) => (
        <div className="slider" key={k}>
          <div className="spread">
            <label htmlFor={`${idPrefix}-${k}`} className="small">
              <span className="weights__swatch" style={{ background: SIGNAL_COLOR[k] ?? "var(--muted)" }} aria-hidden />
              {SIGNAL_SHORT[k] ?? k}
            </label>
            <span className="small num">
              <strong>{p[k]}%</strong>
              {p[k] !== d[k] && <span className="muted"> (default {d[k]}%)</span>}
            </span>
          </div>
          {SIGNAL_HINT[k] && <span className="caption">{SIGNAL_HINT[k]}</span>}
          <input
            id={`${idPrefix}-${k}`}
            type="range"
            min={0}
            max={100}
            step={STEP}
            value={p[k]}
            aria-valuetext={`${p[k]} percent`}
            onChange={(e) => onChange(fromPercents(rebalance(p, k, Number(e.target.value), STEP)))}
          />
        </div>
      ))}

      <div className="row">
        <button type="button" className="btn btn--secondary btn--small" onClick={() => onChange({ ...defaults })} disabled={isDefault}>
          Reset weights to default
        </button>
      </div>
    </div>
  );
}
