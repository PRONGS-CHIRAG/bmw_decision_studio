import { useState } from "react";
import { MARKET_NAMES, MODEL_NAMES, fmtNum, postJSON } from "../api";
import type { Snapshot, TrackerItem, TrackerView } from "../types";
import { Recommendation } from "../components/marks";
import { TRACKER_CHANGED, storedName, storeName } from "../components/DecisionForm";

const STATUSES = ["Decided", "In development", "Launched", "Dropped"];
const STATUS_ICON: Record<string, string> = { Decided: "◆", "In development": "◐", Launched: "●", Dropped: "✕" };

const fmtDate = (iso?: string) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "–");

/** Every recorded decision over time, its lifecycle, and whether the market has moved since. */
export default function Tracker({ data, error, loading, reload }: {
  data: TrackerView | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}) {
  const [filter, setFilter] = useState<"all" | "review">("all");
  const items = (data?.decisions ?? []).filter((i) => filter === "all" || i.needs_review);
  const years = [...new Set(items.map((i) => i.decision.recorded_at.slice(0, 4)))];

  return (
    <main className="app__main tracker">
      <div className="tracker__inner">
        <header className="tracker__head">
          <div>
            <h1 className="tracker__title">Decision tracker</h1>
            <p className="small muted measure">
              Every idea a PM evaluated and decided, with the verdict, the reason and where it stands. Each decision is
              recomputed with <strong>its own saved weights</strong> on today's data. When a rival's equipment or the
              customer data changes enough to move the metrics, the decision is flagged for review.
            </p>
          </div>
          {data && (
            <p className="tracker__count small" role="status">
              {data.decisions.length} decision{data.decisions.length === 1 ? "" : "s"} ·{" "}
              {data.n_needs_review > 0 ? <strong className="tracker__alert">⚠ {data.n_needs_review} to review</strong> : "✓ nothing to review"}
            </p>
          )}
        </header>

        <div className="row tracker__filters" role="group" aria-label="Filter">
          <button type="button" className="chip" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All decisions</button>
          <button type="button" className="chip" aria-pressed={filter === "review"} onClick={() => setFilter("review")}>
            Needs review{data ? ` (${data.n_needs_review})` : ""}
          </button>
          <button type="button" className="btn btn--secondary btn--small" onClick={reload} disabled={loading}>
            {loading ? "Checking…" : "Check the market again"}
          </button>
        </div>
        <p className="caption">
          Alerts come from the data on this server: they appear after the BMW data or the competitor data
          {data?.competitor_data_hash ? ` (now version ${data.competitor_data_hash})` : ""} is refreshed. There is no live monitoring.
        </p>

        {error && <p className="note note--warn">The tracker could not be loaded: {error}</p>}
        {data && data.decisions.length === 0 && (
          <p className="note">No decisions recorded yet. Record one at the end of an evaluation, under "Your decision".</p>
        )}
        {data && data.decisions.length > 0 && items.length === 0 && <p className="note">No decision needs review.</p>}

        {years.map((y) => (
          <section key={y} className="tracker__year" aria-labelledby={`year-${y}`}>
            <h2 id={`year-${y}`} className="tracker__yearh">{y}</h2>
            <div className="stack">
              {items.filter((i) => i.decision.recorded_at.startsWith(y)).map((i) => (
                <DecisionCard key={i.decision.id} item={i} onChanged={reload} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </main>
  );
}

function DecisionCard({ item, onChanged }: { item: TrackerItem; onChanged: () => void }) {
  const d = item.decision;
  const [open, setOpen] = useState<"status" | "review" | null>(null);
  const src = item.baseline.source;
  return (
    <article className={`tcard ${item.needs_review ? "tcard--alert" : ""}`} aria-labelledby={`t-${d.id}`}>
      <div className="tcard__top">
        <div className="tcard__titles">
          <h3 id={`t-${d.id}`} className="tcard__title">{d.feature}</h3>
          <p className="small muted">"{d.idea}"</p>
        </div>
        <div className="tcard__pills">
          <span className={`tpill tpill--${item.lifecycle.status.toLowerCase().replace(/ /g, "-")}`}>
            <span aria-hidden>{STATUS_ICON[item.lifecycle.status] ?? "◆"}</span> {item.lifecycle.status}
          </span>
          {item.needs_review && <span className="tpill tpill--alert"><span aria-hidden>⚠</span> Market has changed</span>}
          {item.status === "ok" && !item.needs_review && <span className="tpill tpill--ok"><span aria-hidden>✓</span> No change</span>}
        </div>
      </div>

      <p className="small">
        <strong>{d.pm}</strong> · {fmtDate(d.recorded_at)} · {d.decision === "accept" ? "Followed the recommendation" : "Overrode the recommendation"}
      </p>
      <p className="small tcard__why">“{d.rationale}”</p>

      {item.needs_review && (
        <div className="note note--warn" role="alert">
          <strong>⚠ Market has changed: review the new metrics.</strong>
          <ul className="bullets">
            {item.changes.map((c, k) => <li key={k}>{c.text}</li>)}
          </ul>
        </div>
      )}
      {item.status === "cannot_recompute" && (
        <p className="note">This decision cannot be recomputed on today's data: {item.reason}. It is kept as recorded.</p>
      )}

      <Compare item={item} />
      <p className="caption">
        Baseline: {src.kind === "reviewed" ? `reviewed by ${src.pm} on ${fmtDate(src.recorded_at)}` : `recorded with the decision on ${fmtDate(src.recorded_at)}`}.
        "At baseline" is observed (stored); "Today" is a scenario evaluation with the decision's saved policy on the current data.
      </p>

      <div className="row">
        {item.needs_review && (
          <button type="button" className="btn btn--small" onClick={() => setOpen(open === "review" ? null : "review")} aria-expanded={open === "review"}>
            Mark reviewed
          </button>
        )}
        <button type="button" className="btn btn--secondary btn--small" onClick={() => setOpen(open === "status" ? null : "status")} aria-expanded={open === "status"}>
          Update status
        </button>
        {item.lifecycle.history.length > 0 && (
          <details className="tcard__history">
            <summary className="small">Status history ({item.lifecycle.history.length})</summary>
            <ol className="small">
              {item.lifecycle.history.map((h) => (
                <li key={h.id}>{fmtDate(h.recorded_at)}: <strong>{h.status}</strong> by {h.pm}: {h.note}</li>
              ))}
            </ol>
          </details>
        )}
      </div>
      {open && <EventForm kind={open} item={item} onDone={() => { setOpen(null); onChanged(); }} />}
    </article>
  );
}

function Compare({ item }: { item: TrackerItem }) {
  const base = item.baseline;
  const today = item.today;
  const changed = new Set(item.changes.filter((c) => c.model).map((c) => `${c.model}|${c.market}`));
  const cells = base.cells.length ? base.cells : today?.cells ?? [];
  const now = new Map((today?.cells ?? []).map((c) => [`${c.model}|${c.market}`, c]));
  return (
    <div className="tcompare">
      <dl className="tcompare__totals">
        <div><dt className="caption">Priority at baseline <span className="tlabel">observed</span></dt><dd className="num">{fmtNum(base.rollup_score)}</dd></div>
        <div><dt className="caption">Priority today <span className="tlabel">scenario evaluation</span></dt><dd className="num">{today ? fmtNum(today.rollup_score) : "–"}</dd></div>
      </dl>
      {cells.length > 0 && (
        <table className="table tcompare__table">
          <caption className="sr-only">Recommendation per series and market, at baseline and today</caption>
          <thead>
            <tr><th>Series · market</th><th>At baseline</th><th>Today</th><th className="r">Score</th></tr>
          </thead>
          <tbody>
            {cells.map((c) => {
              const key = `${c.model}|${c.market}`;
              const t = now.get(key);
              return (
                <tr key={key} className={changed.has(key) ? "tcompare__changed" : undefined}>
                  <td>{changed.has(key) && <span aria-label="changed">⚠ </span>}{MODEL_NAMES[c.model] ?? c.model} · {MARKET_NAMES[c.market] ?? c.market}</td>
                  <td>{c.recommendation ? <Recommendation value={c.recommendation} /> : "–"}</td>
                  <td>{t?.recommendation ? <Recommendation value={t.recommendation} /> : "–"}</td>
                  <td className="r num small">{scoreMove(c, t)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

const NO_SCORE = ["Not sold", "Insufficient evidence"];

/** Score at baseline -> today; "–" where the cell has no recommendation (its score does not count). */
function scoreMove(b: Snapshot["cells"][number], t?: Snapshot["cells"][number]) {
  if (NO_SCORE.includes(b.recommendation ?? "") && (!t || NO_SCORE.includes(t.recommendation ?? ""))) return "–";
  if (!t) return fmtNum(b.score);
  if (b.score === null || t.score === null || b.score === t.score) return fmtNum(t.score ?? b.score);
  return `${fmtNum(b.score)} → ${fmtNum(t.score)}`;
}

function EventForm({ kind, item, onDone }: { kind: "status" | "review"; item: TrackerItem; onDone: () => void }) {
  const [pm, setPm] = useState(storedName);
  const [note, setNote] = useState("");
  const [status, setStatus] = useState(item.lifecycle.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = `${kind}-${item.decision.id}`;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      storeName(pm);
      const path = `/api/tracker/${item.decision.id}/${kind === "review" ? "review" : "status"}`;
      await postJSON(path, kind === "review" ? { pm, note } : { pm, note, status });
      window.dispatchEvent(new Event(TRACKER_CHANGED));
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="tform" onSubmit={submit}>
      <p className="small">
        {kind === "review"
          ? "You have looked at the new metrics. Today's values become the new baseline; the original decision stays as recorded."
          : "Where does this decision stand in the market? Each change is logged with your name and note."}
      </p>
      <div className="tform__grid">
        <div className="field">
          <label htmlFor={`${id}-pm`}>Your name</label>
          <input id={`${id}-pm`} className="input" value={pm} onChange={(e) => setPm(e.target.value)} required />
        </div>
        {kind === "status" && (
          <div className="field">
            <label htmlFor={`${id}-status`}>Status</label>
            <select id={`${id}-status`} className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        )}
      </div>
      <div className="field">
        <label htmlFor={`${id}-note`}>{kind === "review" ? "What do you conclude?" : "Note"}</label>
        <textarea id={`${id}-note`} className="textarea" value={note} onChange={(e) => setNote(e.target.value)} required minLength={3}
          placeholder={kind === "review" ? "e.g. Rival made it standard; raise to Prioritise in the next cycle" : "e.g. Approved for the 2029 model year"} />
      </div>
      <div className="row">
        <button className="btn btn--small" type="submit" disabled={busy || !pm.trim() || note.trim().length < 3}>
          {busy ? "Saving…" : kind === "review" ? "Mark reviewed" : "Save status"}
        </button>
        {error && <p className="small error">Not saved: {error}</p>}
      </div>
    </form>
  );
}
