import type React from "react";
import { MARKET_NAMES, MODEL_NAMES, fmtNum } from "../api";
import type { Cell } from "../types";
import { Recommendation } from "./marks";

/** Models x markets, laid out like configurator option tiles; one cell is selected at a time. */
export default function DecisionMatrix({
  cells,
  models,
  markets,
  selected,
  onSelect,
}: {
  cells: Cell[];
  models: string[];
  markets: string[];
  selected: string | null;
  onSelect: (key: string) => void;
}) {
  const byKey = new Map(cells.map((c) => [`${c.model}|${c.market}`, c]));
  return (
    <div className="matrix" style={{ "--n": markets.length, gridTemplateColumns: `minmax(72px, 0.7fr) repeat(${markets.length}, minmax(0, 1fr))` } as React.CSSProperties} role="grid" aria-label="Recommendation by model and market">
      <div className="matrix__corner" role="columnheader" />
      {markets.map((m) => (
        <div key={m} className="matrix__colhead" role="columnheader">
          <span className="matrix__code">{m}</span>
          <span className="caption">{MARKET_NAMES[m]}</span>
        </div>
      ))}
      {models.map((model) => (
        <div key={model} className="matrix__row" role="row">
          <div className="matrix__rowhead" role="rowheader">
            <span className="matrix__model">{MODEL_NAMES[model]}</span>
            <span className="caption">{model}</span>
          </div>
          {markets.map((market) => {
            const c = byKey.get(`${model}|${market}`);
            const key = `${model}|${market}`;
            if (!c) return <div key={key} className="matrix__cell" />;
            const inactive = c.recommendation === "Not sold";
            return (
              <button
                key={key}
                className={`matrix__cell${inactive ? " matrix__cell--inactive" : ""}`}
                aria-pressed={selected === key}
                onClick={() => onSelect(key)}
                aria-label={`${MODEL_NAMES[model]} in ${MARKET_NAMES[market]}: ${c.recommendation}${c.score !== null ? `, score ${fmtNum(c.score)}` : ""}`}
              >
                <Recommendation value={c.recommendation} />
                {c.recommendation === "Insufficient evidence" && c.score !== null ? (
                  <span className="matrix__score matrix__score--partial num" title="Score from the partial evidence only; no recommendation">
                    {fmtNum(c.score)} partial
                  </span>
                ) : c.score !== null && c.recommendation !== "Not sold" ? (
                  <span className="matrix__score num">{fmtNum(c.score)}</span>
                ) : (
                  <span className="matrix__score matrix__score--empty">–</span>
                )}
                <span className="caption">
                  {c.recommendation === "Not sold" ? "No sales volume" : `Evidence ${Math.round(c.coverage * 100)}%`}
                </span>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
