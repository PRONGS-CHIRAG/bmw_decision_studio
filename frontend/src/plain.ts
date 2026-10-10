import { MARKET_NAMES, MODEL_NAMES, fmtNum } from "./api";
import type { Cell, FeatureResult } from "./types";

// Plain-English wording for engine results. Everything here is derived from engine fields;
// the verified claims of the written brief are always shown word for word, never rephrased.

export type RecGroup = "prioritise" | "consider" | "low" | "insufficient" | "notsold";

/** The engine's own labels stay the group names; the meaning is added in plain words. */
export const REC_INFO: Record<RecGroup, { label: string; meaning: string; tone: string }> = {
  prioritise: { label: "Prioritise", meaning: "Strong customer signal. Act on these first.", tone: "go" },
  consider: { label: "Consider", meaning: "Some customer signal. Worth planning, not urgent.", tone: "maybe" },
  low: { label: "Low priority", meaning: "Little customer signal. Park it for now.", tone: "low" },
  insufficient: { label: "Insufficient evidence", meaning: "Too little feedback to judge. Collect more before deciding.", tone: "unknown" },
  notsold: { label: "Not sold", meaning: "This series is not sold in this market.", tone: "na" },
};
export const REC_ORDER: RecGroup[] = ["prioritise", "consider", "low", "insufficient", "notsold"];

export function recGroup(rec: string): RecGroup {
  if (rec.startsWith("Prioritise")) return "prioritise";
  if (rec.startsWith("Consider")) return "consider";
  if (rec.startsWith("Low")) return "low";
  if (rec.startsWith("Not sold")) return "notsold";
  return "insufficient";
}

export const seriesName = (m: string) => MODEL_NAMES[m] ?? m;
export const marketName = (m: string) => MARKET_NAMES[m] ?? m;

export function list(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** "5 Series in Europe and the United States; 7 Series in Europe" */
export function placesText(cells: Cell[]): string {
  const by = new Map<string, string[]>();
  for (const c of cells) by.set(c.model, [...(by.get(c.model) ?? []), marketName(c.market)]);
  return [...by.entries()].map(([m, ms]) => `${seriesName(m)} in ${list(ms)}`).join("; ");
}

export function groupCells(feature: FeatureResult): Map<RecGroup, Cell[]> {
  const g = new Map<RecGroup, Cell[]>();
  for (const c of feature.cells) {
    const k = recGroup(c.recommendation);
    g.set(k, [...(g.get(k) ?? []), c]);
  }
  return g;
}

/** One opening sentence from the strongest group the engine produced. */
export function bottomLine(feature: FeatureResult): { tone: string; text: string } {
  const g = groupCells(feature);
  const name = feature.feature;
  if (g.get("prioritise")?.length)
    return { tone: "go", text: `Customers give clear reasons to act on ${name}, first for the ${placesText(g.get("prioritise")!)}.` };
  if (g.get("consider")?.length)
    return { tone: "maybe", text: `There is a case for acting on ${name}, but it is not urgent. It is worth planning for the ${placesText(g.get("consider")!)}.` };
  if (g.get("low")?.length)
    return { tone: "low", text: `Customer feedback does not support prioritising ${name} right now.` };
  return { tone: "unknown", text: `There is not enough customer feedback to judge ${name} yet.` };
}

export const VERDICT_WORDS: Record<string, string> = {
  Good: "Customers mostly like it",
  "Leaning good": "Customers lean positive",
  Mixed: "Customers are split",
  "Leaning bad": "Customers lean negative",
  Bad: "Customers mostly complain about it",
  "Not enough data": "Too few comments to say",
};

/** Complaint index read with its 95% interval: only a clear difference is called more or fewer. */
export function complaintWords(o: FeatureResult["overall"]): string {
  const ix = fmtNum(o.complaint_index);
  if (o.ci_low > 1) return `More complaints than expected (index ${ix}; 1.00 is normal, and the difference is clear).`;
  if (o.ci_high < 1) return `Fewer complaints than expected (index ${ix}; 1.00 is normal, and the difference is clear).`;
  return `About as many complaints as expected (index ${ix}; 1.00 is normal, and the difference is within normal variation).`;
}
