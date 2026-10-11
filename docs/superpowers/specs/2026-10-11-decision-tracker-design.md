# Decision tracker and competitor signal: design

Date: 2026-10-11. Status: approved in conversation, awaiting spec review.

## Goal

A product manager can see every idea that was evaluated and decided, what they decided and why, where each decision
stands, and is told when the market has moved since: a competitor's equipment changed or the data changed enough that
the system's recommendation would now differ. Competitor equipment becomes part of the priority score, so a rival
introducing a feature can raise the priority.

## What the user asked for, and the decisions taken

| Question | Decision |
| --- | --- |
| Should competitor changes move the score? | Yes: a fifth signal, `competitors`. |
| Which markets does it score? | All markets. Each market uses its own top-5 rival set; the equipment status is German-market data and is labelled "German equipment data" everywhere. |
| Default weight | 15 %. Defaults become Complaints 35 · Breadth 15 · Requests 15 · Survey 20 · Competitors 15. |
| "Status in the market" | A lifecycle status the PM sets: Decided → In development → Launched, or Dropped. |
| Storage | Append-only JSONL, recomputed when the tracker is opened (no new database). |
| Notification | In the app: a badge on the Tracker view and a banner on each changed decision. No email or chat. |

## Non-goals

- Live monitoring or crawling. A change is detected only after the competitor data or the BMW data is rebuilt.
- Changing or deleting a recorded decision. Every edit is a new event.
- Synthetic history. The tracker shows only decisions that PMs actually recorded.

## 1. Competitor signal (`bmw_feedback/decision.py`)

### Inputs

- Equipment items and their feedback features: `competitors.registry.EQUIPMENT_ITEMS` / `FEATURE_ITEMS`
  (22 items, German market).
- Rival set per series × market: the `sets` table (top five by rank).
- Rival equipment status per item: the `equipment` table, reduced per rival exactly as `CompetitorEngine._equipment`
  does (best row: standard < optional < package < not_available; standard on some variants = `standard_some`).
- BMW's own status per item: the `bmw_equipment` table (`tier`).

### Calculation (pure function, no I/O)

```
competitor_gap(rival_statuses: dict[model_id, status | None], bmw_tier: str | None) -> dict
```

- Rival points: `standard` 1.0, `standard_some` 0.75, `optional` 0.5, `package` 0.5, `not_available` 0.0.
  A rival without a row for the item is `unknown` and left out.
- BMW points: `standard_all` 1.0, `standard_some` 0.75, `optional` 0.5, `not_listed` 0.0.
  No BMW row = `not_listed`.
- Fewer than `MIN_KNOWN_RIVALS = 3` known rivals: `score None`, status
  "only N of the top-5 rivals have equipment data for <item>".
- Otherwise `score = clamp(mean(rival points) - BMW points, 0, 1)`, rounded to 3 decimals.
- If several items ever map to one feature, the item with the highest score is used; ties broken by item key order.
  (Today each feature has at most one item.)
- Output: `score`, `status`, `item`, `item_label`, `rivals` (list of `{model_id, name, status, points}` in rank order),
  `bmw_tier`, `bmw_points`, `rival_mean`, `basis: "German equipment data"`.

### Missing cases (signal skipped, shown with its reason)

- Feature has no equipment item: "no competitor equipment data for this feature".
- No rival set for the series × market (not sold / no data): the set's note.
- Competitor tables not built: "competitor data not built (run `python -m bmw_feedback competitors build`)".

### Policy changes

- `DEFAULT_POLICY.version` becomes `"1.1"`; `weights` gains `competitors: 0.15`, others become 0.35 / 0.15 / 0.15 / 0.20.
- `SIGNALS` gains `competitors`.
- `merge_policy`: when an override contains `weights`, it is taken as the complete set; any signal it does not name
  is 0. So a stored version-1.0 policy (four weights) recomputes with `competitors = 0` and reproduces its old scores.
  The sum-to-1 check (Feature 1) then runs on the complete set.
- `rationale.weights` gains a sentence on competitors.

### Engine wiring

- `DecisionEngine.__init__` takes an optional `competitor_tables` (the dict from `competitors.build.load_tables()`),
  loaded by the API at start-up. `None` means the signal is missing with the "not built" reason.
- `_evaluate_feature` adds `signals["competitors"]`; scoring, coverage, contribution and the
  "Insufficient evidence" rule are unchanged and now run over five signals.
- `_reasons` adds one line: "Competitors (German equipment data): 3 of 5 rivals offer <item> as standard; BMW has it
  as an option (gap 0.40)." or the missing reason.

### Frontend

- `WeightSliders` picks up the fifth key automatically; add its short label, hint ("rivals offer it, BMW does not")
  and colour.
- The evidence panel shows the competitor signal row with the rival list and the "German equipment data" label.

## 2. What a recorded decision stores

`POST /api/decisions` keeps all current fields and adds (sent by `DecisionForm`):

- `scope`: `{models: [...], markets: [...]}` from the evaluation.
- `snapshot`: per cell `{model, market, recommendation, score, signals: {name: score | null}, rivals: {item,
  statuses: {model_id: status}}}`, plus `rollup_score` and `competitor_data_hash`.

Older entries without these fields stay valid. Their scope is read from `system_recommendation.cells`, and their
baseline is that block.

## 3. Lifecycle and review events (`data/decision_events.jsonl`)

Append-only, one JSON object per line, written by `record_event`:

| type | fields |
| --- | --- |
| `status` | `decision_id, pm, status ∈ {Decided, In development, Launched, Dropped}, note, recorded_at, id` |
| `reviewed` | `decision_id, pm, note, snapshot (today's values at review time), recorded_at, id` |

Validation: the decision id must exist, `pm` and `note` are non-empty (note ≥ 3 characters), the status is from the
list. A decision with no status event is `Decided`.

## 4. Change detection (pure function)

```
detect_changes(baseline: dict, today: dict, threshold=0.05) -> list[change]
```

- Baseline: the latest `reviewed` event's snapshot, else the decision's `snapshot`, else its
  `system_recommendation`.
- Today: `engine.evaluate("", [feature], stored_policy, scope.models, scope.markets)`, reduced to the snapshot shape.
- Changes, in this order, each with a plain-language text:
  - `recommendation`: a cell's label changed ("5 Series Europe: Consider → Prioritise").
  - `score`: a cell's score moved by ≥ 0.05 ("5 Series Europe: 0.52 → 0.61").
  - `rollup`: the overall score moved by ≥ 0.05.
  - `competitor`: a rival's status for the item changed ("Mercedes E-Class: seat massage optional → standard").
    Only possible when the baseline has rival statuses.
  - Moving into or out of "Insufficient evidence" or "Not sold" counts as a `recommendation` change.
- `needs_review = len(changes) > 0`.

A decision whose stored policy can no longer be applied (e.g. a feature that disappeared from the data) is reported
with `status: "cannot_recompute"` and the reason, never dropped.

## 5. API (`bmw_feedback/api.py`)

- `GET /api/tracker`: `{decisions: [...], n_needs_review, competitor_data_hash, data_hash}`, newest first. Each item:
  the decision record, `lifecycle` (current status + history), `baseline` (with its source: "at decision" or
  "reviewed by X on date"), `today`, `changes`, `needs_review`.
- `POST /api/tracker/{decision_id}/status`: body `{pm, status, note}`. 400 on validation errors, 404 on unknown id.
- `POST /api/tracker/{decision_id}/review`: body `{pm, note}`. Stores today's snapshot as the new baseline.

## 6. UI

- `BrandHeader`: views become Evaluate · **Tracker** · About. The Tracker button shows "N to review" as text when
  N > 0. The count comes from `GET /api/tracker` on load and after every decision, status or review.
- `pages/Tracker.tsx`:
  - Grouped by year of `recorded_at`, newest first. Empty state: "No decisions recorded yet. Record one at the end
    of an evaluation."
  - Card: idea, feature, PM, date, follow / override with the rationale, lifecycle status with history,
    "At decision" vs "Today" (overall score and a compact series × market table of recommendations).
  - Changed card: a warning note with an icon and the text "Market has changed: review the new metrics", the list of
    changes, and a "Mark reviewed" form (name + note).
  - Lifecycle: a select and a note field, "Update status".
  - Labels: every value is marked "observed" (recorded) or "scenario evaluation" (today's recomputation); the
    competitor rows say "German equipment data".
- Status is text plus icon, never colour alone.

## 7. Testing

- Unit (hand-built inputs, no customer evidence):
  - `competitor_gap`: points, clamp, fewer than three known rivals, unknown rivals ignored, BMW not listed.
  - `merge_policy`: version-1.0 weights read with competitors = 0; five weights must sum to 1.
  - `detect_changes`: no change; recommendation change; score below and above threshold; competitor status change;
    baseline without rival data.
  - Event validation: unknown id, empty note, bad status.
- Real data (`tests/test_api.py`):
  - The competitor signal for "Seat massage", G60 EU, equals a recomputation from the competitor tables.
  - Each existing decision recomputed with its stored policy gives its stored cell scores (no change today).
- API: tracker endpoints with `log_path` / `events_path` monkeypatched to a temporary directory.
- Frontend: `npm test` keeps passing with five weights; a Playwright run through record → tracker → status →
  review.

## Risks and limits

- Alerts only fire after a data refresh. With today's snapshot every decision shows "No change since the decision".
- On the deployed Render backend the JSONL logs reset on every redeploy (no persistent disk). This is already true
  for `decisions.jsonl`.
- Changing the defaults changes every new evaluation's numbers. Recorded decisions are unaffected because they are
  recomputed with their own stored policy.
