import { fmtNum, useApi } from "../api";
import type { NodeView } from "../types";
import { ErrorState } from "./marks";

const HIDE = new Set(["shape"]);

/** One knowledge-graph node: provenance first, then attributes, then its relations. */
export default function NodeInspector({
  nodeId,
  onSelect,
  full = false,
  onExpand,
  expanding = false,
}: {
  nodeId: string;
  onSelect: (id: string) => void;
  full?: boolean;                     // full-screen page: list every connection the API returns
  onExpand?: () => void;              // add this node's connections to the picture
  expanding?: boolean;
}) {
  const { data, error, loading } = useApi<NodeView>(`/api/graph/node/${encodeURIComponent(nodeId)}`);
  if (error) return <ErrorState message={error} />;
  if (loading || !data) return <p className="small muted">Loading {nodeId}…</p>;
  const attrs = Object.entries(data.attributes).filter(([k, v]) => v !== null && v !== "" && !HIDE.has(k) && k !== "text");
  const text = typeof data.attributes.text === "string" ? (data.attributes.text as string) : null;
  const shape = Array.isArray(data.attributes.shape) ? (data.attributes.shape as { bin: string; score: number }[]) : null;
  return (
    <div className="stack inspector">
      <p className="eyebrow">{data.type}</p>
      <h3 className="inspector__title">{data.label}</h3>
      <dl className="kv">
        <dt>Source</dt>
        <dd>
          {data.prov.kind}: {data.prov.ref}
        </dd>
        {data.prov.key && (
          <>
            <dt>Key</dt>
            <dd>{data.prov.key}</dd>
          </>
        )}
        {data.prov.page && (
          <>
            <dt>Page</dt>
            <dd>{data.prov.page}</dd>
          </>
        )}
      </dl>
      {text && <blockquote className="quote">“{text}”</blockquote>}
      {attrs.length > 0 && (
        <dl className="kv">
          {attrs.slice(0, full ? attrs.length : 18).map(([k, v]) => (
            <Attr key={k} k={k} v={v} />
          ))}
        </dl>
      )}
      {shape && (
        <table className="table">
          <thead>
            <tr>
              <th>Value</th>
              <th className="r">Log-odds</th>
            </tr>
          </thead>
          <tbody>
            {shape.slice(0, 12).map((s) => (
              <tr key={s.bin}>
                <td>{s.bin}</td>
                <td className="r num">{s.score > 0 ? "+" : ""}{fmtNum(s.score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="stack">
        {full && (
          <div className="inspector__conn">
            <p className="caption">
              {data.neighbours.reduce((a, g) => a + g.total, 0).toLocaleString("en-GB")} connections in {data.neighbours.length} relations
            </p>
            {onExpand && (
              <button type="button" className="btn btn--small" onClick={onExpand} disabled={expanding}>
                {expanding ? "Adding…" : "Show its connections"}
              </button>
            )}
          </div>
        )}
        {data.neighbours.map((g) => (
          <div key={`${g.direction}-${g.rel}`}>
            <p className="caption">
              {g.direction === "out" ? "→" : "←"} {g.rel} · {g.total}
              {full && g.total > g.items.length ? ` (first ${g.items.length} shown)` : ""}
            </p>
            <div className="chips">
              {g.items.slice(0, full ? g.items.length : 6).map((n) => (
                <button key={n.id} className="chip chip--small" onClick={() => onSelect(n.id)} title={n.id}>
                  {n.label.length > 34 ? `${n.label.slice(0, 33)}…` : n.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Attr({ k, v }: { k: string; v: unknown }) {
  const shown =
    typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString("en-GB") : fmtNum(v, Math.abs(v) < 1 ? 3 : 2))
      : typeof v === "boolean" ? (v ? "yes" : "no")
      : Array.isArray(v) ? v.slice(0, 6).join(", ") + (v.length > 6 ? ` (+${v.length - 6})` : "")
      : String(v);
  return (
    <>
      <dt>{k.replace(/_/g, " ")}</dt>
      <dd className="num">{shown.length > 160 ? `${shown.slice(0, 159)}…` : shown}</dd>
    </>
  );
}
