/** What still stops a decision from being recorded; mirrors the server's rules (name required, rationale >= 3 characters). */
export type DecisionProblem = { field: "pm" | "rationale"; message: string };

export function decisionProblem(pm: string, rationale: string): DecisionProblem | null {
  if (!pm.trim()) return { field: "pm", message: "Enter your name." };
  if (rationale.trim().length < 3) return { field: "rationale", message: "Write a short rationale (at least 3 characters)." };
  return null;
}
