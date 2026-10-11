import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import cytoscape from "cytoscape";
import type { Core, ElementDefinition } from "cytoscape";
import { fmtInt, getJSON, useApi } from "../api";
import type { AgentEvaluation, FullGraph, GraphSchema, NodeView } from "../types";
import EntireGraph, { adjacency } from "./EntireGraph";
import NodeInspector from "./NodeInspector";
import { GROUPS, concentricLayout, cssVar, evaluationElements, graphStyle, groupOf, schemaElements, short } from "./graphModel";

type Mode = "evaluation" | "entire" | "schema";

/**
 * The knowledge graph behind one evaluation. Embedded in the report it shows this evaluation and the schema;
 * `full` (the full-screen page) adds the entire graph, search, zoom controls, legend filters and lets a node's
 * connections be added to the picture.
 */
export default function EvidenceGraph({
  evaluation,
  focus,
  onFocus,
  full = false,
  onOpenFull,
}: {
  evaluation: AgentEvaluation;
  focus: string | null;
  onFocus: (id: string | null) => void;
  full?: boolean;
  onOpenFull?: () => void;
}) {
  const [mode, setMode] = useState<Mode>("evaluation");
  const { data: schema } = useApi<GraphSchema>(mode === "schema" ? "/api/graph/schema" : null);
  const [wantEntire, setWantEntire] = useState(false);    // fetched once, kept while the page is open
  const { data: entire, error: entireError } = useApi<FullGraph>(wantEntire ? "/api/graph/full" : null);
  const adj = useMemo(() => (entire ? adjacency(entire) : null), [entire]);
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const tapped = useRef<string | null>(null);      // focus set by a tap here should not re-centre the view
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [showEdges, setShowEdges] = useState(false);
  const [added, setAdded] = useState(0);           // nodes added to the evaluation picture from the inspector
  const [expanding, setExpanding] = useState(false);

  const elements = useMemo<ElementDefinition[]>(() => {
    if (mode === "schema") return schema ? schemaElements(schema) : [];
    if (mode === "entire") return [];
    return evaluationElements(evaluation);
  }, [mode, schema, evaluation]);

  useEffect(() => {
    if (!box.current || !elements.length || mode === "entire") return;
    const instance = cytoscape({
      container: box.current,
      elements,
      wheelSensitivity: 0.2,
      minZoom: 0.2,
      maxZoom: 3,
      style: graphStyle(mode, getComputedStyle(document.body).fontFamily),
      layout: concentricLayout(mode),
    });
    const highlight = (id: string | null) => {
      instance.elements().removeClass("faded hl");
      if (!id) return;
      const node = instance.getElementById(id);
      if (!node.length) return;
      const hood = node.closedNeighborhood();
      instance.elements().not(hood).addClass("faded");
      node.connectedEdges().addClass("hl");
      instance.nodes().unselect();
      node.select();
    };
    instance.on("tap", "node", (e) => {
      const id = e.target.id() as string;
      highlight(id);
      setSelected(id);
      tapped.current = id;
      if (mode === "evaluation") onFocus(id);
    });
    instance.on("tap", (e) => {
      if (e.target === instance) {
        highlight(null);
        setSelected(null);
      }
    });
    cy.current = instance;
    setAdded(0);
    return () => {
      instance.destroy();
      cy.current = null;
    };
  }, [elements, mode, onFocus]);

  // Focus requested from outside (a citation's "Show in knowledge graph", or a connection picked in the inspector)
  useEffect(() => {
    if (!focus || mode !== "evaluation" || !cy.current) return;
    setSelected(focus);
    if (tapped.current === focus) return;
    tapped.current = null;
    const node = cy.current.getElementById(focus);
    if (node.length) {
      cy.current.elements().removeClass("faded hl");
      cy.current.elements().not(node.closedNeighborhood()).addClass("faded");
      node.connectedEdges().addClass("hl");
      cy.current.nodes().unselect();
      node.select();
      cy.current.animate({ center: { eles: node }, zoom: 1.4 }, { duration: 300 });
    }
  }, [focus, mode, elements]);

  // legend filters (full screen only)
  useEffect(() => {
    const c = cy.current;
    if (!c || mode === "entire") return;
    c.batch(() => {
      c.nodes().removeClass("hidden");
      if (hidden.size) c.nodes().filter((n) => hidden.has(n.data("group"))).addClass("hidden");
    });
  }, [hidden, mode, elements]);

  const switchMode = (m: Mode) => {
    setMode(m);
    if (m === "entire") setWantEntire(true);
    setSelected(m === "evaluation" ? focus : m === "entire" ? focus ?? selected : null);
    setHidden(new Set());
  };
  const selectEntire = useCallback((id: string | null) => {
    setSelected(id);
    if (id) onFocus(id);
  }, [onFocus]);
  const pick = (id: string) => {
    if (mode === "entire") return selectEntire(id);
    if (mode === "schema") {
      setSelected(id);
      const n = cy.current?.getElementById(id);
      if (n?.length) cy.current!.animate({ center: { eles: n }, zoom: 1.4 }, { duration: 300 });
      return;
    }
    onFocus(id);
  };

  /** Add a node's connections (up to 12 per relation, as the inspector lists them) around it on the canvas. */
  const expand = async (id: string) => {
    const c = cy.current;
    if (!c || mode !== "evaluation") return;
    setExpanding(true);
    try {
      const view = await getJSON<NodeView>(`/api/graph/node/${encodeURIComponent(id)}`);
      const centre = c.getElementById(id);
      const at = centre.length ? centre.position() : { x: 0, y: 0 };
      const fresh = view.neighbours.flatMap((g) => g.items.map((it) => ({ ...it, rel: g.rel, direction: g.direction })));
      const toAdd: ElementDefinition[] = [];
      let k = 0;
      const ring = fresh.filter((n) => !c.getElementById(n.id).length).length;
      for (const n of fresh) {
        if (!c.getElementById(n.id).length && !toAdd.some((x) => x.data.id === n.id)) {
          const grp = groupOf(n.type, GROUP_OF_TYPE[n.type] ?? "spec");
          const angle = (2 * Math.PI * k++) / Math.max(ring, 1);
          const r = Math.max(150, (ring * 34) / (2 * Math.PI));   // about 34px of arc per added node
          toAdd.push({
            group: "nodes",
            data: { id: n.id, label: short(n.type === "Comment" ? n.id.replace("comment:", "") : n.label), group: grp, type: n.type,
              color: cssVar(GROUPS[grp]?.token ?? "--g-spec"), shape: GROUPS[grp]?.shape ?? "ellipse", size: 16, cited: false },
            position: { x: at.x + r * Math.cos(angle), y: at.y + r * Math.sin(angle) },
            classes: "added",
          });
        }
        const [s, t] = n.direction === "out" ? [id, n.id] : [n.id, id];
        const eid = `${s}->${t}:${n.rel}`;
        if (!c.getElementById(eid).length && !toAdd.some((x) => x.data.id === eid))
          toAdd.push({ group: "edges", data: { id: eid, source: s, target: t, rel: n.rel } });
      }
      c.add(toAdd);
      setAdded((a) => a + toAdd.filter((x) => x.group === "nodes").length);
      tapped.current = null;
      const node = c.getElementById(id);
      c.elements().removeClass("faded hl");
      c.elements().not(node.closedNeighborhood()).addClass("faded");
      node.connectedEdges().addClass("hl");
      c.animate({ fit: { eles: node.closedNeighborhood(), padding: 60 } }, { duration: 300 });
    } finally {
      setExpanding(false);
    }
  };
  const resetAdded = () => {
    const c = cy.current;
    if (!c) return;
    c.nodes(".added").remove();
    c.layout(concentricLayout("evaluation")).run();
    setAdded(0);
  };

  const present = useMemo(() => mode === "schema"
    ? new Set(schema?.node_types.map((t) => t.group))
    : mode === "entire"
      ? new Set(entire?.nodes.map((n) => n[2]))
      : new Set(evaluation.graph.nodes.map((n) => groupOf(n.type, n.group))), [mode, schema, entire, evaluation]);
  const virtual = selected?.startsWith("rec:") || selected?.startsWith("idea:");
  const inGraph = selected && !virtual && mode !== "schema";
  const inEvaluation = useMemo(() => new Set(evaluation.graph.nodes.map((n) => n.id)), [evaluation]);
  const searchable = useMemo<SearchItem[]>(() => {
    if (!full) return [];
    if (mode === "entire") return entire ? entire.nodes.map((n) => ({ id: n[0], label: n[3], type: n[1] })) : [];
    if (mode === "schema") return schema ? schema.node_types.map((t) => ({ id: t.type, label: t.type, type: t.group })) : [];
    return evaluation.graph.nodes.map((n) => ({ id: n.id, label: n.label, type: n.type }));
  }, [full, mode, entire, schema, evaluation]);
  const toggle = (k: string) => setHidden((h) => {
    const next = new Set(h);
    if (next.has(k)) next.delete(k); else next.add(k);
    return next;
  });

  const modes: { id: Mode; label: string }[] = [
    { id: "evaluation", label: `This evaluation (${evaluation.graph.nodes.length} nodes)` },
    ...(full ? [{ id: "entire" as Mode, label: `Entire graph${entire ? ` (${fmtInt(entire.n_nodes)} nodes)` : ""}` }] : []),
    { id: "schema", label: `How all the data connects${schema ? ` (${fmtInt(schema.n_nodes)} nodes)` : ""}` },
  ];

  const legend = (
    <ul className={`legend ${full ? "graph__legend" : ""}`} aria-label={full ? "Legend; click a group to hide or show it" : "Legend"}>
      {Object.entries(GROUPS)
        .filter(([k]) => present.has(k))
        .map(([k, g]) => (
          <li key={k}>
            {full ? (
              <button type="button" className="legend__toggle" aria-pressed={!hidden.has(k)} onClick={() => toggle(k)}>
                <span className="legend__swatch" style={{ background: `var(${g.token})` }} aria-hidden />
                {g.label}
              </button>
            ) : (
              <>
                <span className="legend__swatch" style={{ background: `var(${g.token})` }} aria-hidden />
                {g.label}
              </>
            )}
          </li>
        ))}
      {mode !== "schema" && (
        <li>
          <span className="legend__swatch legend__swatch--cited" aria-hidden />
          {mode === "entire" ? "Part of this evaluation" : "Cited by a fact"}
        </li>
      )}
    </ul>
  );

  return (
    <div className={`graph ${full ? "graph--full" : ""}`}>
      <div className="graph__bar">
        <div className="graph__tabsrow">
          <div className="tabs graph__tabs" role="tablist" aria-label="Graph view">
            {modes.map((m) => (
              <button key={m.id} className="tab" role="tab" aria-selected={mode === m.id} onClick={() => switchMode(m.id)}>
                {m.label}
              </button>
            ))}
          </div>
          {!full && onOpenFull && (
            <button type="button" className="btn btn--outline btn--small graph__open" onClick={onOpenFull}>
              <ExpandIcon /> Open full screen
            </button>
          )}
        </div>
        {!full && legend}
      </div>
      {full && (
        <div className="graph__tools">
          <GraphSearch items={searchable} onPick={pick} placeholder={mode === "entire" ? `Search ${fmtInt(searchable.length)} nodes by name` : "Search nodes by name"} />
          <div className="graph__zoom" role="group" aria-label="Zoom">
            <button type="button" className="iconbtn" aria-label="Zoom in" onClick={() => zoomBy(cy.current, 1.4)}>+</button>
            <button type="button" className="iconbtn" aria-label="Zoom out" onClick={() => zoomBy(cy.current, 1 / 1.4)}>−</button>
            <button type="button" className="btn btn--outline btn--small" onClick={() => cy.current?.animate({ fit: { eles: cy.current.elements(":visible"), padding: 30 } }, { duration: 300 })}>Fit to screen</button>
          </div>
          {mode === "entire" && (
            <label className="graph__check">
              <input type="checkbox" checked={showEdges} onChange={(e) => setShowEdges(e.target.checked)} /> Show connections between non-comment nodes
            </label>
          )}
          {mode === "evaluation" && added > 0 && (
            <button type="button" className="btn btn--outline btn--small" onClick={resetAdded}>Remove {added} added nodes</button>
          )}
        </div>
      )}
      {full && legend}
      <div className="graph__body">
        {mode === "entire" ? (
          entire && adj ? (
            <EntireGraph data={entire} adj={adj} focus={selected} onSelect={selectEntire} hidden={hidden} showEdges={showEdges}
              inEvaluation={inEvaluation} cyRef={cy} />
          ) : (
            <div className="graph__canvas graph__loading" role="status">
              {entireError ? <p className="note note--error small">The entire graph could not be loaded: {entireError}</p>
                : <p className="small muted"><span className="spinner" aria-hidden /> Loading all {fmtInt(schema?.n_nodes ?? 15064)} nodes…</p>}
            </div>
          )
        ) : (
          <div className="graph__canvas" ref={box} role="img" aria-label={mode === "schema" ? "Schema of the knowledge graph" : "Knowledge-graph neighbourhood of this evaluation"} />
        )}
        <aside className="graph__inspector" aria-live="polite">
          {mode === "schema" ? (
            <SchemaInfo schema={schema} selected={selected} />
          ) : inGraph ? (
            <NodeInspector nodeId={selected!} onSelect={pick} full={full}
              onExpand={full && mode === "evaluation" ? () => expand(selected!) : undefined} expanding={expanding} />
          ) : selected && mode === "evaluation" ? (
            <VirtualInfo id={selected} evaluation={evaluation} />
          ) : mode === "entire" ? (
            <EntireInfo data={entire} />
          ) : (
            <p className="small muted">
              Select a node to see its source (table, PDF page or model file), its attributes and how it connects. Blue rings mark
              nodes that a fact in the brief cites.
              {full && " Use “Show its connections” to add a node's neighbours to the picture."}
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}

// Node type -> group, for nodes added from the inspector (mirrors GROUPS in bmw_feedback/graph/build.py).
const GROUP_OF_TYPE: Record<string, string> = {
  Series: "product", Variant: "product", Powertrain: "product", OptionItem: "price", Package: "price", FitmentSummary: "price",
  TechSpec: "spec", Market: "market", FeedbackCoverage: "market", SalesVolume: "sales", Domain: "feedback", Feature: "feedback",
  Reason: "feedback", ReasonFamily: "feedback", Comment: "feedback", SurveyAttribute: "survey", SurveyScore: "survey",
  VerdictCell: "model_output", ModelArtifact: "model_output", EBMTerm: "model_output", Caveat: "caveat",
};

function zoomBy(c: Core | null, f: number) {
  if (!c) return;
  c.animate({ zoom: { level: c.zoom() * f, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } } }, { duration: 200 });
}

interface SearchItem { id: string; label: string; type: string }

function GraphSearch({ items, onPick, placeholder }: { items: SearchItem[]; onPick: (id: string) => void; placeholder: string }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const hits = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (s.length < 2) return [];
    const starts: SearchItem[] = [];
    const contains: SearchItem[] = [];
    for (const it of items) {
      const l = it.label.toLowerCase();
      if (l.startsWith(s)) starts.push(it);
      else if (l.includes(s) || it.id.toLowerCase().includes(s)) contains.push(it);
      if (starts.length >= 10) break;
    }
    return [...starts, ...contains].slice(0, 10);
  }, [q, items]);
  const choose = (it: SearchItem) => {
    onPick(it.id);
    setQ(it.label);
    setOpen(false);
  };
  return (
    <div className="gsearch">
      <label htmlFor="graph-search" className="sr-only">Search the graph</label>
      <input id="graph-search" className="input gsearch__input" value={q} placeholder={placeholder} autoComplete="off"
        role="combobox" aria-expanded={open && hits.length > 0} aria-controls="graph-search-list"
        onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter" && hits[active]) { e.preventDefault(); choose(hits[active]); }
          else if (e.key === "Escape") { e.stopPropagation(); setOpen(false); }
        }} />
      {open && hits.length > 0 && (
        <ul id="graph-search-list" className="gsearch__list" role="listbox">
          {hits.map((h, i) => (
            <li key={h.id} role="option" aria-selected={i === active}>
              <button type="button" className="gsearch__item" onMouseDown={(e) => e.preventDefault()} onClick={() => choose(h)}>
                <span>{h.label}</span>
                <span className="caption">{h.type}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && q.trim().length >= 2 && hits.length === 0 && <p className="gsearch__none caption">No node matches “{q.trim()}”.</p>}
    </div>
  );
}

function ExpandIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" />
    </svg>
  );
}

function EntireInfo({ data }: { data: FullGraph | null }) {
  if (!data) return <p className="small muted">Loading the entire graph…</p>;
  const byType = new Map<string, number>();
  for (const n of data.nodes) byType.set(n[1], (byType.get(n[1]) ?? 0) + 1);
  return (
    <div className="stack">
      <p className="eyebrow">Entire knowledge graph</p>
      <p className="small">
        All {fmtInt(data.n_nodes)} nodes and {fmtInt(data.n_edges)} edges. Each feature sits at the centre of a cluster of its own
        evidence: comments, verdict cells, price-list items and technical data. Series, markets and domains are in the middle.
      </p>
      <p className="small">
        Zoom in to read names, search for any node, or click one to draw all its connections. Nodes with a blue ring are part of this
        evaluation. Click a group in the legend to hide it.
      </p>
      <ul className="rels">
        {[...byType.entries()].sort((a, b) => b[1] - a[1]).map(([t, n]) => (
          <li key={t} className="caption">{t}: {fmtInt(n)}</li>
        ))}
      </ul>
    </div>
  );
}

function SchemaInfo({ schema, selected }: { schema: GraphSchema | null; selected: string | null }) {
  if (!schema) return <p className="small muted">Loading the schema…</p>;
  if (!selected)
    return (
      <div className="stack">
        <p className="eyebrow">Knowledge graph</p>
        <p className="small">
          {fmtInt(schema.n_nodes)} nodes and {fmtInt(schema.n_edges)} edges built from the processed tables and the model outputs.
          Select a type to see its relations.
        </p>
        <p className="caption">
          {schema.checks.filter((c) => c.ok).length} of {schema.checks.length} integrity checks against the source tables passed
          (built {schema.built_at}).
        </p>
        <details>
          <summary>Integrity checks</summary>
          <ul className="rels" style={{ marginTop: 8 }}>
            {schema.checks.map((c) => (
              <li key={c.check} className="caption">
                {c.ok ? "✓" : "✕"} {c.check}: {fmtInt(c.graph)} (source {fmtInt(c.source)})
              </li>
            ))}
          </ul>
        </details>
        {schema.not_in_graph && schema.not_in_graph.length > 0 && (
          <details>
            <summary>Deliberately not in the graph</summary>
            <ul className="rels" style={{ marginTop: 8 }}>
              {schema.not_in_graph.map((x) => (
                <li key={x.source} className="caption">
                  {x.source}: {x.why}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    );
  const t = schema.node_types.find((x) => x.type === selected);
  const rels = schema.edge_types.filter((e) => e.source === selected || e.target === selected);
  return (
    <div className="stack">
      <p className="eyebrow">{t?.group}</p>
      <h3 className="inspector__title">{selected}</h3>
      <p className="small">{fmtInt(t?.count ?? 0)} nodes</p>
      <ul className="rels">
        {rels.map((e, i) => (
          <li key={i} className="small">
            {e.source} <strong>{e.rel}</strong> {e.target} <span className="caption">{fmtInt(e.count)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function VirtualInfo({ id, evaluation }: { id: string; evaluation: AgentEvaluation }) {
  if (id.startsWith("idea:"))
    return (
      <div className="stack">
        <p className="eyebrow">Idea (this request)</p>
        <h3 className="inspector__title">{evaluation.spec.idea}</h3>
        <p className="small">
          Matched to {evaluation.spec.features.map((f) => f.feature).join(", ") || "no feature in the data"}.
        </p>
      </div>
    );
  const facts = evaluation.facts.filter((f) => f.source.node_id === id);
  const [feature, series, market] = id.slice(4).split("|");
  return (
    <div className="stack">
      <p className="eyebrow">Recommendation (decision engine)</p>
      <h3 className="inspector__title">
        {feature}: {series} {market}
      </h3>
      <ul className="bullets small">
        {facts.map((f) => (
          <li key={f.id}>{f.statement}</li>
        ))}
      </ul>
      <p className="caption">Computed by DecisionEngine.evaluate from the verdict cell, survey score and sales volume it connects to.</p>
    </div>
  );
}
