import { useEffect, useMemo, useRef } from "react";
import cytoscape from "cytoscape";
import type { Core, ElementDefinition } from "cytoscape";
import type { FullGraph } from "../types";
import { GROUPS, cssVar } from "./graphModel";

// Every node of the knowledge graph at a position computed on the server (bmw_feedback/graph/layout.py).
// Edges are not all drawn: 40k of them run from comments to four series, four markets and three powertrains
// and would only paint those hubs grey. A selected node's connections are drawn in full; "show connections"
// adds every edge that does not end at a comment.

const SIZE: Record<string, number> = {
  Series: 44, Market: 40, Powertrain: 36, Domain: 30, Feature: 16, ModelArtifact: 16, Variant: 12, ReasonFamily: 10, Package: 10,
  SurveyAttribute: 8, SalesVolume: 8, Caveat: 10, EBMTerm: 10, FeedbackCoverage: 8, Comment: 3,
};
const FONT: Record<string, number> = { Series: 30, Market: 28, Powertrain: 24, Domain: 22, Feature: 9, Variant: 7, ModelArtifact: 9 };
const MAX_DRAWN = 4000;           // edges drawn for one selected node; hubs have up to 10k

export interface Adjacency {
  index: Map<string, number>;
  out: number[][];                 // edge indices per node
  inn: number[][];
}

export function adjacency(data: FullGraph): Adjacency {
  const index = new Map(data.nodes.map((n, i) => [n[0], i]));
  const out: number[][] = data.nodes.map(() => []);
  const inn: number[][] = data.nodes.map(() => []);
  data.edges.forEach(([u, v], i) => {
    out[u].push(i);
    inn[v].push(i);
  });
  return { index, out, inn };
}

export default function EntireGraph({
  data,
  adj,
  focus,
  onSelect,
  hidden,
  showEdges,
  inEvaluation,
  cyRef,
}: {
  data: FullGraph;
  adj: Adjacency;
  focus: string | null;
  onSelect: (id: string | null) => void;
  hidden: Set<string>;
  showEdges: boolean;
  inEvaluation: Set<string>;
  cyRef: React.MutableRefObject<Core | null>;
}) {
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  // A selection carried over from another view keeps its ring but does not zoom in: the page opens on the whole graph.
  const tapped = useRef<string | null>(focus);

  const elements = useMemo<ElementDefinition[]>(() => {
    const color = Object.fromEntries(Object.entries(GROUPS).map(([k, g]) => [k, cssVar(g.token)]));
    return data.nodes.map(([id, type, group, label, x, y]) => ({
      data: {
        id, type, group, label, color: color[group] ?? "#8e8e8e", shape: GROUPS[group]?.shape ?? "ellipse",
        size: SIZE[type] ?? 4, font: FONT[type] ?? 0, ev: inEvaluation.has(id),
      },
      position: { x, y },
    }));
  }, [data, inEvaluation]);

  useEffect(() => {
    if (!box.current) return;
    const font = getComputedStyle(document.body).fontFamily;
    const instance = cytoscape({
      container: box.current,
      elements,
      layout: { name: "preset", fit: true, padding: 30 },
      wheelSensitivity: 0.25,
      minZoom: 0.05,
      maxZoom: 8,
      textureOnViewport: true,
      hideEdgesOnViewport: true,
      motionBlur: false,
      boxSelectionEnabled: false,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)", shape: "data(shape)" as never, width: "data(size)", height: "data(size)",
            "border-width": 0, "overlay-opacity": 0, label: "", "font-family": font, color: "#1C1917",
            "min-zoomed-font-size": 7, "text-valign": "bottom", "text-margin-y": 3,
            "text-background-color": "#FAF8F5", "text-background-opacity": 0.85, "text-background-padding": "1px",
          },
        },
        { selector: "node[font > 0]", style: { label: "data(label)", "font-size": "data(font)", "text-wrap": "wrap", "text-max-width": "160px" } },
        { selector: "node[?ev]", style: { "border-width": 2, "border-color": "#DC2626" } },
        { selector: "node.nb", style: { label: "data(label)", "font-size": 5, "text-max-width": "90px", "text-wrap": "ellipsis", "z-index": 8 } },
        { selector: "node.sel", style: { "border-width": 4, "border-color": "#1C1917", label: "data(label)", "font-size": 12, "z-index": 9 } },
        { selector: "node.hidden", style: { display: "none" } },
        { selector: "edge", style: { "curve-style": "haystack", width: 0.4, "line-color": "#CFC8BC", opacity: 0.5 } },
        { selector: "edge.hl", style: { width: 1, "line-color": "#DC2626", opacity: 0.7, "z-index": 7 } },
      ],
    });
    instance.on("tap", "node", (e) => {
      const id = e.target.id() as string;
      tapped.current = id;
      onSelect(id);
    });
    instance.on("tap", (e) => {
      if (e.target === instance) onSelect(null);
    });
    cy.current = instance;
    cyRef.current = instance;
    return () => {
      instance.destroy();
      cy.current = null;
      if (cyRef.current === instance) cyRef.current = null;
    };
  }, [elements, onSelect, cyRef]);

  // groups switched off in the legend
  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.batch(() => {
      c.nodes().removeClass("hidden");
      if (hidden.size) c.nodes().filter((n) => hidden.has(n.data("group"))).addClass("hidden");
    });
  }, [hidden, elements]);

  // background edges: everything that does not touch a comment
  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.edges(".bg").remove();
    if (!showEdges) return;
    const isComment = (i: number) => data.nodes[i][1] === "Comment";
    const bg: ElementDefinition[] = [];
    data.edges.forEach(([u, v, rel], i) => {
      if (!isComment(u) && !isComment(v)) bg.push({ group: "edges", data: { id: `bg${i}`, source: data.nodes[u][0], target: data.nodes[v][0], rel }, classes: "bg" });
    });
    c.add(bg);
  }, [showEdges, data, elements]);

  // the selected node: its connections drawn and its neighbours labelled
  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.batch(() => {
      c.edges(".hl").remove();
      c.nodes(".sel, .nb").removeClass("sel nb");
    });
    if (!focus) return;
    const i = adj.index.get(focus);
    if (i === undefined) return;
    const edges = [...adj.out[i], ...adj.inn[i]].slice(0, MAX_DRAWN);
    c.batch(() => {
      const add: ElementDefinition[] = edges.map((k) => {
        const [u, v, rel] = data.edges[k];
        return { group: "edges", data: { id: `hl${k}`, source: data.nodes[u][0], target: data.nodes[v][0], rel }, classes: "hl" };
      });
      c.add(add);
      for (const k of edges) {
        const [u, v] = data.edges[k];
        c.getElementById(data.nodes[u === i ? v : u][0]).addClass("nb");
      }
      c.getElementById(focus).addClass("sel");
    });
    if (tapped.current === focus) return;            // a tap here should not move the view
    tapped.current = null;
    const node = c.getElementById(focus);
    c.animate({ center: { eles: node }, zoom: Math.max(c.zoom(), 2.2) }, { duration: 350 });
  }, [focus, adj, data, elements]);

  return <div className="graph__canvas" ref={box} role="img" aria-label={`The entire knowledge graph: ${data.n_nodes} nodes`} />;
}
