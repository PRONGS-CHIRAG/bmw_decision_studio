// Run with: npm test   (Node's built-in runner; Node >= 23 runs TypeScript directly)
import { test } from "node:test";
import assert from "node:assert/strict";
import { decisionProblem } from "../src/decisionCheck.ts";

test("a complete decision has no problem", () => {
  assert.equal(decisionProblem("Alex", "Customers ask for it"), null);
});

test("a missing name is reported and points at the name field", () => {
  assert.deepEqual(decisionProblem("   ", "Customers ask for it"), { field: "pm", message: "Enter your name." });
});

test("a rationale under 3 characters is reported and points at the rationale field", () => {
  assert.equal(decisionProblem("Alex", " ok ")?.field, "rationale");
  assert.equal(decisionProblem("Alex", "")?.field, "rationale");
});

test("the name is checked before the rationale", () => {
  assert.equal(decisionProblem("", "")?.field, "pm");
});
