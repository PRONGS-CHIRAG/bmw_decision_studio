import type { ElementDefinition, LayoutOptions, NodeSingular, Stylesheet } from "cytoscape";
import { fmtInt } from "../api";
import type { AgentEvaluation, GraphSchema } from "../types";

// Shared by the report's graph tab, the full-screen graph page and the PDF snapshot, so all three draw the same picture.

// Colour (CSS token) and shape per node group; the legend always shows both.
export const GROUPS: Record<string, { label: string; token: string; shape: string }> = {
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

export function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#8e8e8e";
}
export const short = (s: string, n = 30) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
export const groupOf = (type: string, group: string) => (type === "Recommendation" ? "model_output" : group);

export function evaluationElements(evaluation: AgentEvaluation): ElementDefinition[] {
  const g = evaluation.graph;
  return [
    ...g.nodes.map((n) => {
      const grp = groupOf(n.type, n.group);
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
}

export function schemaElements(schema: GraphSchema): ElementDefinition[] {
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

export function graphStyle(mode: "evaluation" | "schema", font: string): Stylesheet[] {
  return [
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
    { selector: "node.added", style: { "border-width": 2, "border-color": "#98a2b3", "border-style": "dashed" } },
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
    { selector: ".hidden", style: { display: "none" } },
  ] as Stylesheet[];
}

export function concentricLayout(mode: "evaluation" | "schema"): LayoutOptions {
  return {
    name: "concentric",
    concentric: (n: NodeSingular) => n.data("ring"),
    levelWidth: () => 1,
    minNodeSpacing: mode === "schema" ? 40 : 34,
    animate: false,
  } as LayoutOptions;
}
