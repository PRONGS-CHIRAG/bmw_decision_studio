import { useEffect, useRef } from "react";
import { fmtInt, fmtNum } from "../api";
import type { Candidate, VerdictRule } from "../types";

// What customers think of a topic, as one number a PM can read without the statistics:
// green verdicts show how many fewer complaints it gets than a typical topic, red ones how many more.
// Higher always means "more so" in the direction of the colour.

export type VerdictTone = "good" | "leangood" | "mixed" | "leanbad" | "bad" | "none";

export const VERDICT_TONE: Record<string, VerdictTone> = {
  Good: "good", "Leaning good": "leangood", Mixed: "mixed", "Leaning bad": "leanbad", Bad: "bad", "Not enough data": "none",
};

/** Percent difference from typical, rounded down so a value never looks past a threshold it did not reach. */
const diffPct = (ix: number) => Math.floor(Math.abs(1 - ix) * 100 + 1e-9);

export function dialValue(c: Candidate): { pct: number; word: string } | null {
  const tone = VERDICT_TONE[c.verdict] ?? "none";
  if (tone === "none" || c.complaint_index === null) return null;
  const ix = c.complaint_index;
  const fewer = tone === "good" || tone === "leangood" || (tone === "mixed" && ix < 1);
  return { pct: diffPct(ix), word: fewer ? "fewer complaints" : "more complaints" };
}

export function VerdictLabel({ verdict }: { verdict: string }) {
  return <span className={`vlabel vlabel--${VERDICT_TONE[verdict] ?? "none"}`}>{verdict}</span>;
}

export function VerdictDial({ c }: { c: Candidate }) {
  const v = dialValue(c);
  const tone = VERDICT_TONE[c.verdict] ?? "none";
  return (
    <span className={`dial dial--${tone}`} aria-label={v ? `${c.verdict}: ${v.pct}% ${v.word} than a typical topic` : "Too few comments to judge"}>
      <span className="dial__circle">
        <span className="dial__num num">{v ? `${v.pct}%` : "?"}</span>
        <span className="dial__unit">{v ? v.word : "too few comments"}</span>
      </span>
    </span>
  );
}

const pctOf = (x: number) => Math.round(Math.abs(1 - x) * 100);

/** How the percentage and the label were worked out for one topic, from the numbers the backend sent. */
export function CalcPopup({ c, rule, onClose }: { c: Candidate; rule: VerdictRule; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);

  const v = dialValue(c);
  const obs = c.complaints_observed;
  const exp = c.complaints_expected;
  const raw = obs !== null && exp ? obs / exp : null;
  const nudged = raw !== null && c.complaint_index !== null && Math.abs(raw - c.complaint_index) >= 0.01;
  const cuts = [rule.good, rule.lean_good, rule.lean_bad, rule.bad];
  // two decimals, or three where two would make the value look equal to a threshold it is not
  const ixText = (x: number) => (cuts.includes(Number(x.toFixed(2))) && Math.abs(x - Number(x.toFixed(2))) > 1e-9 ? x.toFixed(3) : x.toFixed(2));
  const rows: { verdict: string; rule: string }[] = [
    { verdict: "Good", rule: `At least ${pctOf(rule.good)}% fewer complaints, clearly more than chance, and at least typical praise` },
    { verdict: "Leaning good", rule: `At least ${pctOf(rule.lean_good)}% fewer complaints` },
    { verdict: "Mixed", rule: "In between: close to a typical topic" },
    { verdict: "Leaning bad", rule: `At least ${pctOf(rule.lean_bad)}% more complaints` },
    { verdict: "Bad", rule: `At least ${pctOf(rule.bad)}% more complaints, clearly more than chance` },
    { verdict: "Not enough data", rule: `Fewer than ${fmtInt(rule.min_mentions)} comments` },
  ];

  return (
    <div className="calc__backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="calc" role="dialog" aria-modal="true" aria-labelledby="calc-title">
        <div className="calc__head">
          <div>
            <p className="calc__eyebrow">How this is calculated</p>
            <h3 id="calc-title" className="calc__title">{c.feature}: <VerdictLabel verdict={c.verdict} /></h3>
          </div>
          <button ref={closeRef} type="button" className="pop__close" onClick={onClose} aria-label="Close">×</button>
        </div>

        {v ? (
          <ol className="calc__steps">
            <li>
              <span className="calc__k">Complaints found <span className="tag">observed</span></span>
              <span><strong className="num">{obs === null ? "unknown" : fmtInt(obs)}</strong> complaint mentions about {c.feature} in{" "}
                <span className="num">{fmtInt(c.n_comments)}</span> customer comments.</span>
            </li>
            <li>
              <span className="calc__k">What a typical topic would get <span className="tag">calculated</span></span>
              <span><strong className="num">{exp === null ? "unknown" : fmtNum(exp)}</strong> complaints, for a topic with the same number of
                comments from the same feedback channels. Channels differ a lot in how much people complain, so this keeps the comparison fair.</span>
            </li>
            <li>
              <span className="calc__k">Compare the two</span>
              <span>
                {raw !== null && <><span className="num">{fmtInt(obs!)} ÷ {fmtNum(exp!)} = {ixText(raw)}</span>. </>}
                {nudged && <>Topics with few comments are noisy, so this is pulled slightly towards the average of its area ({c.domain}),
                  giving <span className="num">{ixText(c.complaint_index!)}</span>. </>}
                1.00 would be exactly typical.
              </span>
            </li>
            <li className="calc__result">
              <span className="calc__k">Result</span>
              <span><strong className="num">{ixText(c.complaint_index!)}</strong> means <strong>{v.pct}% {v.word} than a typical topic</strong>,
                shown as <strong className="num">{v.pct}%</strong> in the circle.</span>
            </li>
          </ol>
        ) : (
          <p className="small">There are only {fmtInt(c.n_comments)} comments on this topic, fewer than the {fmtInt(rule.min_mentions)} needed to judge it.</p>
        )}

        <p className="calc__k" style={{ marginTop: 16 }}>How the label is chosen</p>
        <table className="calc__rules">
          <tbody>
            {rows.map((r) => (
              <tr key={r.verdict} className={r.verdict === c.verdict ? "calc__rules--on" : ""}>
                <td><VerdictLabel verdict={r.verdict} /></td>
                <td>{r.rule}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="caption" style={{ marginTop: 8 }}>"Clearly more than chance" means the 95% range of the ratio does not include 1.00.</p>
      </div>
    </div>
  );
}
