import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape from "cytoscape";
import type { Core, ElementDefinition } from "cytoscape";
import { fmtInt, useApi } from "../api";
import type { AgentEvaluation, GraphSchema } from "../types";
import NodeInspector from "./NodeInspector";

// Colour (CSS token) and shape per node group; the legend always shows both.
const GROUPS: Record<string, { label: string; token: string; shape: string }> = {
  idea: { label: "Idea", token: "--g-idea", shape: "star" },
  feedback: { label: "Feedback", token: "--g-feedback", shape: "ellipse" },
  survey: { label: "Customer studies", token: "--g-survey", shape: "round-pentagon" },
  price: { label: "Price list", token: "--g-price", shape: "round-tag" },
  spec: { label: "Technical data", token: "--g-spec", shape: "barrel" },
  product: { label: "Series & variants", token: "--g-product", shape: "round-rectangle" },
  market: { label: "Markets", token: "--g-market", shape: "hexagon" },
  sales: { label: "Sales volumes", token: "--g-sales", shape: "round-hexagon" },
  model_output: { label: "Model outputs", token: "--g-model", shape: "diamond" },
  caveat: { label: "Caveats", token: "--g-caveat", shape: "triangle" },
};
// Rings from the centre outwards: the idea, its features, recommendations, then the evidence behind them.
const RING: Record<string, number> = {
  Idea: 5, Feature: 4, Recommendation: 3, VerdictCell: 3, Series: 3, Market: 3, Domain: 3, FitmentSummary: 3, ModelArtifact: 3,
  SurveyScore: 2, SalesVolume: 2, SurveyAttribute: 2, Reason: 2, EBMTerm: 2, OptionItem: 2, TechSpec: 2, Comment: 1, Caveat: 1,
};
const SCHEMA_RING: Record<string, number> = { Feature: 10 };

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#8e8e8e";
}
const short = (s: string, n = 30) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

export default function EvidenceGraph({
  evaluation,
  focus,
  onFocus,
}: {
  evaluation: AgentEvaluation;
  focus: string | null;
  onFocus: (id: string | null) => void;
}) {
  const [mode, setMode] = useState<"evaluation" | "schema">("evaluation");
  const { data: schema } = useApi<GraphSchema>(mode === "schema" ? "/api/graph/schema" : null);
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const tapped = useRef<string | null>(null);      // focus set by a tap here should not re-centre the view

  const elements = useMemo<ElementDefinition[]>(() => {
    if (mode === "schema") {
      if (!schema) return [];
      const maxLog = Math.log10(Math.max(...schema.node_types.map((t) => t.count)));
      const nodes = schema.node_types.map((t) => ({
        data: {
          id: t.type, label: `${t.type}\n${fmtInt(t.count)}`, group: t.group, ring: SCHEMA_RING[t.type] ?? 1,
          color: cssVar(GROUPS[t.group]?.token ?? "--g-spec"), shape: GROUPS[t.group]?.shape ?? "ellipse",
          size: 26 + 34 * (Math.log10(t.count + 1) / maxLog), cited: false,
        },
      }));
      const types = new Set(schema.node_types.map((t) => t.type));
      const edges = schema.edge_types
        .filter((e) => types.has(e.source) && types.has(e.target))
        .map((e, i) => ({ data: { id: `s${i}`, source: e.source, target: e.target, rel: `${e.rel} · ${fmtInt(e.count)}` } }));
      return [...nodes, ...edges];
    }
    const g = evaluation.graph;
    return [
      ...g.nodes.map((n) => {
        const grp = n.type === "Recommendation" ? "model_output" : n.group;
        return {
          data: {
            id: n.id, label: short(n.type === "Comment" ? n.id.replace("comment:", "") : n.label), group: grp, type: n.type,
            ring: RING[n.type] ?? 1, color: cssVar(GROUPS[grp]?.token ?? "--g-spec"),
            shape: n.type === "Recommendation" ? "round-diamond" : GROUPS[grp]?.shape ?? "ellipse",
            size: n.type === "Idea" ? 46 : n.chosen ? 38 : n.type === "Recommendation" ? 28 : 20, cited: n.cited,
          },
        };
      }),
      ...g.edges.map((e) => ({ data: { id: e.id, source: e.source, target: e.target, rel: e.rel } })),
    ];
  }, [mode, schema, evaluation]);

  useEffect(() => {
    if (!box.current || !elements.length) return;
    const font = getComputedStyle(document.body).fontFamily;
    const instance = cytoscape({
      container: box.current,
      elements,
      wheelSensitivity: 0.2,
      minZoom: 0.2,
      maxZoom: 3,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)", shape: "data(shape)" as never, width: "data(size)", height: "data(size)",
            label: "data(label)", "font-family": font, "font-size": mode === "schema" ? 11 : 10, color: "#111827",
            "text-background-color": "#ffffff", "text-background-opacity": 0.85, "text-background-padding": "1px",
            "text-valign": "bottom", "text-margin-y": 4, "text-wrap": "wrap", "text-max-width": "120px",
            "border-width": 0, "overlay-opacity": 0,
          },
        },
        { selector: "node[?cited]", style: { "border-width": 3, "border-color": "#2f6fed" } },
        { selector: "node:selected", style: { "border-width": 4, "border-color": "#111827" } },
        {
          selector: "edge",
          style: {
            width: 1, "line-color": "#d0d5dd", "target-arrow-color": "#d0d5dd", "target-arrow-shape": "triangle", "arrow-scale": 0.6,
            "curve-style": "bezier", ...(mode === "schema"
              ? { label: "data(rel)", "font-size": 8, color: "#6b7280", "text-rotation": "autorotate", "font-family": font,
                  "text-background-color": "#ffffff", "text-background-opacity": 1, "text-background-padding": "2px" }
              : {}),
          },
        },
        {
          selector: "edge.hl",
          style: {
            "line-color": "#2f6fed", "target-arrow-color": "#2f6fed", width: 2, label: "data(rel)", "font-size": 8, color: "#2f6fed",
            "font-family": font, "text-rotation": "autorotate", "text-background-color": "#ffffff", "text-background-opacity": 1,
            "text-background-padding": "2px",
          },
        },
        { selector: ".faded", style: { opacity: 0.18 } },
      ],
      layout: {
        name: "concentric",
        concentric: (n: cytoscape.NodeSingular) => n.data("ring"),
        levelWidth: () => 1,
        minNodeSpacing: mode === "schema" ? 40 : 34,
        animate: false,
      } as cytoscape.LayoutOptions,
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
    return () => {
      instance.destroy();
      cy.current = null;
    };
  }, [elements, mode, onFocus]);

  // Focus requested from outside (a citation's "Show in knowledge graph")
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

  const present = mode === "schema"
    ? new Set(schema?.node_types.map((t) => t.group))
    : new Set(evaluation.graph.nodes.map((n) => (n.type === "Recommendation" ? "model_output" : n.group)));
  const inGraph = selected && !selected.startsWith("rec:") && !selected.startsWith("idea:") && mode === "evaluation";

  return (
    <div className="graph">
      <div className="graph__bar">
        <div className="tabs graph__tabs" role="tablist" aria-label="Graph view">
          <button className="tab" role="tab" aria-selected={mode === "evaluation"} onClick={() => { setMode("evaluation"); setSelected(null); }}>
            This evaluation ({evaluation.graph.nodes.length} nodes)
          </button>
          <button className="tab" role="tab" aria-selected={mode === "schema"} onClick={() => { setMode("schema"); setSelected(null); }}>
            How all the data connects{schema ? ` (${fmtInt(schema.n_nodes)} nodes)` : ""}
          </button>
        </div>
        <ul className="legend" aria-label="Legend">
          {Object.entries(GROUPS)
            .filter(([k]) => present.has(k))
            .map(([k, g]) => (
              <li key={k}>
                <span className="legend__swatch" style={{ background: `var(${g.token})` }} aria-hidden />
                {g.label}
              </li>
            ))}
          {mode === "evaluation" && (
            <li>
              <span className="legend__swatch legend__swatch--cited" aria-hidden />
              Cited by a fact
            </li>
          )}
        </ul>
      </div>
      <div className="graph__body">
        <div className="graph__canvas" ref={box} role="img" aria-label={mode === "schema" ? "Schema of the knowledge graph" : "Knowledge-graph neighbourhood of this evaluation"} />
        <aside className="graph__inspector" aria-live="polite">
          {mode === "schema" ? (
            <SchemaInfo schema={schema} selected={selected} />
          ) : inGraph ? (
            <NodeInspector nodeId={selected!} onSelect={(id) => onFocus(id)} />
          ) : selected ? (
            <VirtualInfo id={selected} evaluation={evaluation} />
          ) : (
            <p className="small muted">
              Select a node to see its source (table, PDF page or model file), its attributes and how it connects. Blue rings mark
              nodes that a fact in the brief cites.
            </p>
          )}
        </aside>
      </div>
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
