import { MARKET_NAMES, fmtNum } from "../api";
import type { Policy } from "../types";
import WeightSliders from "./WeightSliders";

const THRESHOLD_LABELS: Record<string, string> = {
  prioritise: "Prioritise at score ≥",
  consider: "Consider at score ≥",
  min_coverage: "Minimum evidence for a recommendation",
};

export default function PolicyPanel({
  policy,
  defaults,
  hash,
  onChange,
  onReset,
}: {
  policy: Policy;
  defaults: Policy;
  hash: string | null;
  onChange: (p: Policy) => void;
  onReset: () => void;
}) {
  const changed = JSON.stringify(stripRationale(policy)) !== JSON.stringify(stripRationale(defaults));
  const set = (section: "market_multipliers" | "thresholds", key: string, value: number) =>
    onChange({ ...policy, [section]: { ...policy[section], [key]: value } });

  return (
    <section className="policy" aria-labelledby="policy-title">
      <div className="spread">
        <div>
          <h3 id="policy-title">Decision policy</h3>
          <p className="small muted">
            {changed ? "Adjusted from the default policy." : "Default policy."} Policy {hash ?? "–"}. Two PMs with the
            same policy and data get the same answer.
          </p>
        </div>
        <button className="btn btn--secondary btn--small" onClick={onReset} disabled={!changed}>
          Reset to default
        </button>
      </div>

      <div className="policy__grid">
        <fieldset className="policy__group">
          <legend className="label">Signal weights</legend>
          <WeightSliders idPrefix="pw" weights={policy.weights} defaults={defaults.weights}
            onChange={(weights) => onChange({ ...policy, weights })} />
          <p className="caption">{defaults.rationale.weights}</p>
        </fieldset>

        <fieldset className="policy__group">
          <legend className="label">Market emphasis (× sales volume)</legend>
          {Object.keys(policy.market_multipliers).map((k) => (
            <Slider
              key={k}
              id={`m-${k}`}
              label={MARKET_NAMES[k] ?? k}
              value={policy.market_multipliers[k]}
              def={defaults.market_multipliers[k]}
              min={0}
              max={3}
              step={0.25}
              onChange={(v) => set("market_multipliers", k, v)}
            />
          ))}
          <div className="field">
            <label htmlFor="vol-year">Sales volume year</label>
            <select
              id="vol-year"
              className="select"
              value={policy.volume_year}
              onChange={(e) => onChange({ ...policy, volume_year: Number(e.target.value) })}
            >
              <option value={2024}>2024</option>
              <option value={2025}>2025</option>
              <option value={2030}>2030 (forecast)</option>
            </select>
          </div>
          <p className="caption">{defaults.rationale.market_multipliers}</p>
        </fieldset>

        <fieldset className="policy__group">
          <legend className="label">Thresholds and thin data</legend>
          {Object.keys(policy.thresholds).map((k) => (
            <Slider
              key={k}
              id={`t-${k}`}
              label={THRESHOLD_LABELS[k] ?? k}
              value={policy.thresholds[k]}
              def={defaults.thresholds[k]}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => set("thresholds", k, v)}
            />
          ))}
          <label className="check">
            <input
              type="checkbox"
              checked={policy.borrowing.enabled}
              onChange={(e) => onChange({ ...policy, borrowing: { ...policy.borrowing, enabled: e.target.checked } })}
            />
            Borrow the model's all-market verdict when a market has fewer than 8 comments
          </label>
          <Slider
            id="b-discount"
            label="Weight of borrowed evidence"
            value={policy.borrowing.discount}
            def={defaults.borrowing.discount}
            min={0}
            max={1}
            step={0.05}
            onChange={(v) => onChange({ ...policy, borrowing: { ...policy.borrowing, discount: v } })}
          />
          <label className="check">
            <input
              type="checkbox"
              checked={policy.borrowing.into_cn}
              onChange={(e) => onChange({ ...policy, borrowing: { ...policy.borrowing, into_cn: e.target.checked } })}
            />
            Also borrow into China (the data has no Chinese customer comments)
          </label>
          <p className="caption">{defaults.rationale.borrowing}</p>
        </fieldset>
      </div>
    </section>
  );
}

function Slider({
  id,
  label,
  value,
  def,
  min,
  max,
  step,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  def: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="slider">
      <div className="spread">
        <label htmlFor={id} className="small">
          {label}
        </label>
        <span className="small num">
          <strong>{fmtNum(value)}</strong>
          {value !== def && <span className="muted"> (default {fmtNum(def)})</span>}
        </span>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}

function stripRationale(p: Policy) {
  const { rationale: _r, version: _v, scoring: _s, ...rest } = p;
  return rest;
}
