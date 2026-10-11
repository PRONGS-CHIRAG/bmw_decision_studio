// Run with: npm test   (Node's built-in runner; Node >= 23 runs TypeScript directly)
import { test } from "node:test";
import assert from "node:assert/strict";
import { fromPercents, rebalance, toPercents } from "../src/weights.ts";

const sum = (p: Record<string, number>) => Object.values(p).reduce((a, b) => a + b, 0);
const KEYS = ["complaints", "breadth", "requests", "survey"];
const DEFAULT = { complaints: 40, breadth: 20, requests: 20, survey: 20 };

test("toPercents turns weights into whole percents that sum to 100", () => {
  assert.deepEqual(toPercents({ complaints: 0.4, breadth: 0.2, requests: 0.2, survey: 0.2 }), DEFAULT);
  const thirds = toPercents({ a: 1 / 3, b: 1 / 3, c: 1 / 3 }, 5);
  assert.equal(sum(thirds), 100);
  assert.deepEqual(thirds, { a: 35, b: 35, c: 30 });    // remainder goes to the first keys, deterministically
});

test("raising one signal takes the difference from the others in proportion", () => {
  const p = rebalance(DEFAULT, "complaints", 60);
  assert.deepEqual(p, { complaints: 60, breadth: 15, requests: 15, survey: 10 });
  assert.equal(sum(p), 100);
});

test("lowering one signal gives the difference to the others in proportion", () => {
  assert.deepEqual(rebalance(DEFAULT, "complaints", 10), { complaints: 10, breadth: 30, requests: 30, survey: 30 });
});

test("a signal at 0 stays at 0 while the others still have weight", () => {
  const p = rebalance({ complaints: 50, breadth: 0, requests: 25, survey: 25 }, "complaints", 70);
  assert.equal(p.breadth, 0);
  assert.equal(sum(p), 100);
});

test("when every other signal is at 0, the freed share is split equally", () => {
  assert.deepEqual(rebalance({ complaints: 100, breadth: 0, requests: 0, survey: 0 }, "complaints", 40),
    { complaints: 40, breadth: 20, requests: 20, survey: 20 });
});

test("values are clamped to 0..100 and snapped to the step", () => {
  assert.deepEqual(rebalance(DEFAULT, "survey", 140), { complaints: 0, breadth: 0, requests: 0, survey: 100 });
  assert.equal(rebalance(DEFAULT, "survey", -10).survey, 0);
  assert.equal(rebalance(DEFAULT, "survey", 23).survey % 5, 0);
});

test("the sum is exactly 100 after any sequence of moves", () => {
  let p: Record<string, number> = { ...DEFAULT };
  let seed = 7;
  for (let i = 0; i < 2000; i++) {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    const key = KEYS[seed % KEYS.length];
    p = rebalance(p, key, seed % 101);
    assert.equal(sum(p), 100, `after move ${i}`);
    for (const v of Object.values(p)) assert.ok(v >= 0 && v <= 100 && v % 5 === 0);
  }
});

test("fromPercents gives weights the backend accepts (sum within 1e-6 of 1)", () => {
  const w = fromPercents({ complaints: 35, breadth: 15, requests: 15, survey: 35 });
  assert.ok(Math.abs(Object.values(w).reduce((a, b) => a + b, 0) - 1) < 1e-6);
});

test("five signals (with competitors) also always total 100", () => {
  const five = toPercents({ complaints: 0.35, breadth: 0.15, requests: 0.15, survey: 0.2, competitors: 0.15 });
  assert.deepEqual(five, { complaints: 35, breadth: 15, requests: 15, survey: 20, competitors: 15 });
  const p = rebalance(five, "competitors", 40);
  assert.equal(p.competitors, 40);
  assert.equal(sum(p), 100);
});
