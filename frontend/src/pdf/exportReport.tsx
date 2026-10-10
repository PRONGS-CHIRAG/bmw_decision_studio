import cytoscape from "cytoscape";
import type { ElementDefinition } from "cytoscape";
import { pdf } from "@react-pdf/renderer";
import { getJSON } from "../api";
import type { AgentEvaluation, AgentStatus, Explained, GraphSchema } from "../types";
import type { ExplainState } from "../components/ProcessFlow";
import { GROUPS, concentricLayout, cssVar, evaluationElements, graphStyle, groupOf, schemaElements } from "../components/graphModel";
import ReportDocument, { type GraphPictures } from "./ReportDocument";

// Loaded on demand (with @react-pdf/renderer) when the PM exports the report.

/** Draw a graph off screen with the app's own styles and return it as a PNG data URI. */
function snapshot(elements: ElementDefinition[], mode: "evaluation" | "schema", width: number, height: number): string | null {
  if (!elements.length) return null;
  const box = document.createElement("div");
  box.style.cssText = `position:fixed;left:-20000px;top:0;width:${width}px;height:${height}px;`;
  document.body.appendChild(box);
  const cy = cytoscape({
    container: box,
    elements,
    style: graphStyle(mode, "Helvetica, Arial, sans-serif"),
    layout: concentricLayout(mode),
  });
  try {
    return cy.png({ output: "base64uri", full: true, scale: 2, bg: "#ffffff", maxWidth: 2400, maxHeight: 2400 });
  } finally {
    cy.destroy();
    box.remove();
  }
}

export async function downloadReport(input: {
  evaluation: AgentEvaluation;
  explained: Explained | null;
  explainState: ExplainState;
  explainError: string | null;
  status: AgentStatus | null;
}): Promise<void> {
  const { evaluation } = input;
  const schema = await getJSON<GraphSchema>("/api/graph/schema").catch(() => null);
  const groups = new Set(evaluation.graph.nodes.map((n) => groupOf(n.type, n.group)));
  const pictures: GraphPictures = {
    evaluation: snapshot(evaluationElements(evaluation), "evaluation", 1400, 1000),
    schema: schema ? snapshot(schemaElements(schema), "schema", 1400, 900) : null,
    legend: Object.entries(GROUPS).filter(([k]) => groups.has(k)).map(([, g]) => ({ label: g.label, color: cssVar(g.token) })),
  };
  const generatedAt = new Date();
  const blob = await pdf(<ReportDocument {...input} pictures={pictures} generatedAt={generatedAt} />).toBlob();
  const name = evaluation.spec.features[0]?.feature ?? evaluation.spec.idea;
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "idea";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const day = `${generatedAt.getFullYear()}-${String(generatedAt.getMonth() + 1).padStart(2, "0")}-${String(generatedAt.getDate()).padStart(2, "0")}`;
  a.download = `idea-evaluation-${slug}-${day}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
