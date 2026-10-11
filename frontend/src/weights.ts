/**
 * Signal weights as whole percents that always sum to exactly 100.
 *
 * The UI works in steps of `step` percent (default 5). Moving one signal gives or takes the difference from the
 * others in proportion to their current shares; when the others are all at 0, the difference is split equally.
 * Rounding uses the largest remainder, ties going to the earlier key, so the result is deterministic.
 * Pure functions only (unit-tested with `npm test`).
 */
export type Percents = Record<string, number>;

/** Split `units` over `keys` in proportion to `shares` (largest remainder, ties by key order). */
function apportion(keys: string[], shares: number[], units: number): number[] {
  const total = shares.reduce((a, b) => a + b, 0);
  const exact = total > 0 ? shares.map((s) => (s * units) / total) : keys.map(() => units / keys.length);
  const out = exact.map(Math.floor);
  let left = units - out.reduce((a, b) => a + b, 0);
  const order = exact.map((x, i) => ({ i, r: x - Math.floor(x) })).sort((a, b) => b.r - a.r || a.i - b.i);
  for (const { i } of order) {
    if (left <= 0) break;
    out[i] += 1;
    left -= 1;
  }
  return out;
}

/** Weights in [0, 1] (any total) -> whole percents in multiples of `step` that sum to 100. */
export function toPercents(weights: Record<string, number>, step = 5): Percents {
  const keys = Object.keys(weights);
  const units = apportion(keys, keys.map((k) => Math.max(0, weights[k])), Math.round(100 / step));
  return Object.fromEntries(keys.map((k, i) => [k, units[i] * step]));
}

/** Percents -> weights for the API (sum is 1 up to float rounding). */
export function fromPercents(p: Percents): Record<string, number> {
  return Object.fromEntries(Object.entries(p).map(([k, v]) => [k, v / 100]));
}

/** Set `key` to `value` (clamped to 0..100, snapped to `step`) and rebalance the others so the sum stays 100. */
export function rebalance(p: Percents, key: string, value: number, step = 5): Percents {
  const total = Math.round(100 / step);
  const mine = Math.min(total, Math.max(0, Math.round(value / step)));
  const others = Object.keys(p).filter((k) => k !== key);
  const units = apportion(others, others.map((k) => Math.max(0, p[k])), total - mine);
  const out: Percents = {};
  for (const k of Object.keys(p)) out[k] = k === key ? mine * step : units[others.indexOf(k)] * step;
  return out;
}
