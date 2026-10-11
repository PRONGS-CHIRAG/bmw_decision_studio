# Decision Tracker and Competitor Signal Implementation Plan

> **For agentic workers:** executed natively in the session (the user asked to build directly). Steps use checkbox
> syntax. **No commits or pushes** (user instruction for this build).

**Goal:** Add a fifth, competitor priority signal and a Tracker view that lists recorded decisions, their lifecycle
status, and flags decisions whose recomputed metrics changed.

**Architecture:** Pure functions (`competitor_gap`, `detect_changes`, event validation) in a new
`bmw_feedback/tracker.py` plus `decision.py`; the engine reads competitor tables injected at start-up; the tracker
recomputes each decision with its stored policy on request; events are append-only JSONL.

**Tech stack:** Python 3.11, FastAPI, pandas, pytest; React 18 + TypeScript + Vite; Node test runner.

**Spec:** `docs/superpowers/specs/2026-10-11-decision-tracker-design.md`

## Global constraints

- Weights sum to exactly 1; defaults Complaints 0.35 · Breadth 0.15 · Requests 0.15 · Survey 0.20 · Competitors 0.15.
- Policy version "1.1". A stored weights override missing a signal reads that signal as 0.
- Competitor rival points: standard 1.0, standard_some 0.75, optional 0.5, package 0.5, not_available 0.0.
  BMW points: standard_all 1.0, standard_some 0.75, optional 0.5, not_listed 0.0. MIN_KNOWN_RIVALS = 3.
- Change threshold 0.05. Statuses: Decided, In development, Launched, Dropped.
- Logs append-only; never rewrite `data/decisions.jsonl`. Tests write logs to a tmp dir only.
- Competitor values are labelled "German equipment data" in every market.

## Review focus

1. Recorded v1.0 decisions must recompute to their stored scores (no false "market changed" alerts).
2. A decision whose feature is no longer in the data must show "cannot recompute", not crash the tracker.
3. Competitor tables missing → signal missing with "not built" reason, engine still works.
4. Unknown decision id on status/review → 404; empty note or bad status → 400.
5. Five-weight sliders keep the sum at 100 and the evaluate request is accepted.

---

### Task 1: Competitor gap (pure) + policy v1.1

**Files:** Modify `bmw_feedback/decision.py`; Test `tests/test_policy_weights.py`, new `tests/test_competitor_signal.py`

- [ ] Tests: `competitor_gap` points/clamp/min rivals/unknown ignored/BMW not listed; v1.0 weights → competitors 0;
      defaults sum 1 and include competitors.
- [ ] Implement `RIVAL_POINTS`, `BMW_POINTS`, `MIN_KNOWN_RIVALS`, `competitor_gap(rivals, bmw_tier)`;
      `DEFAULT_POLICY` v1.1; `merge_policy` complete-set rule; `SIGNALS` + competitors.
- [ ] Run tests → pass.

### Task 2: Engine wiring + facts + reasons

**Files:** Modify `bmw_feedback/decision.py`, `bmw_feedback/api.py` (lifespan), `bmw_feedback/agents/facts.py`

- [ ] Test (real data): Seat massage G60 EU competitor score equals recomputation from competitor tables; engine
      without tables → missing with "not built".
- [ ] `DecisionEngine(competitor_tables=...)`, `_competitors(feature, model, market)`; `_reasons` line;
      fact `{cell}.competitors`; policy fact lists five weights.
- [ ] Full pytest → pass.

### Task 3: Tracker core (`bmw_feedback/tracker.py`)

- [ ] Tests (hand-built): `snapshot_from_result`, `detect_changes` (none / recommendation / score above+below
      threshold / rollup / competitor / baseline without rivals), `record_event` validation, `lifecycle`.
- [ ] Implement; `events_path()`; `Tracker.list(engine)` with cannot_recompute handling.

### Task 4: API

- [ ] Tests: `GET /api/tracker` with tmp logs (legacy-style entry recomputes with no changes; tampered baseline
      shows changes), `POST status` 200/400/404, `POST review` resets `needs_review`.
- [ ] `DecisionRequest` gains `scope`, `snapshot`; endpoints.

### Task 5: Frontend

- [ ] `WeightSliders`: competitors label/hint/colour; `npm test` five-weight test.
- [ ] `EvidencePanel`: competitors name + detail (rivals offering it, BMW status, "German equipment data").
- [ ] `DecisionForm` sends scope + snapshot; notifies tracker refresh.
- [ ] `BrandHeader` Tracker view with "N to review"; `pages/Tracker.tsx`; types; CSS.
- [ ] `tsc -b`, `vite build`, Playwright: record → tracker → status → review.
