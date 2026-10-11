# BMW Decision Studio
## MVP Build Specification

| Field | Value |
| --- | --- |
| Version | 1.0 |
| Date | 10 October 2026 |
| Status | Proposed hackathon implementation scope |
| Companion document | BMW_Decision_Studio_PRD.md |
| Demo context | One European BEV concept, 2033 launch, qualitative outlook through 2040 |
| Release objective | Complete one evidence-to-decision workflow with reproducible results |

## 1. MVP outcome

Build a working application in which a product manager can review evidence, compare four feasible vehicle requirement portfolios, inspect future assumptions, ask grounded questions, change a constraint and approve a versioned decision.

The core demonstration question is:

> For our 2033 European EV, which requirement portfolios fit our budget, what supports each one, and what changes if charging infrastructure develops more slowly?

The MVP must connect forecasting, ranking, evidence and human review in one workflow. A disconnected trend dashboard, decorative graph or chat-only recommendation does not meet the release objective.

## 2. Scope contract

| Dimension | First-release scope |
| --- | --- |
| Vehicle context | One fictional future BMW vehicle concept |
| Market | Europe only |
| Launch horizon | 2033; editable configuration rather than multi-year UI complexity |
| Longer horizon | Qualitative scenario notes through 2040 |
| Candidate requirements | 12–20 curated requirements |
| Evidence | Approximately 30–60 reviewed excerpts from a small source pack |
| Trends | Five: charging convenience, long-distance needs, efficiency, digital experience and premium driving experience |
| Future scenarios | Slow, baseline and fast development, with explicit drivers |
| Strategy alternatives | Four distinct portfolios where feasible |
| Users | One named demo PM; not production authentication |
| Inputs | CSV for structured data; Markdown/plain text for report excerpts |
| Outputs | Versioned decision record, Markdown decision package and CSV requirements |

No source pack is assumed to have been provided. Start with labeled synthetic data; replace it with permitted real inputs when available. Keep synthetic labels visible on screens and exports. Do not present invented customer quotes, costs or forecasts as BMW data.

The BEV context is a scenario choice. Do not encode the unverified regulatory date from the challenge notes as law.

## 3. Must-build features

All rows below are release requirements. The order describes implementation sequence, not permission to omit the later rows.

| ID | Capability | Smallest complete implementation |
| --- | --- | --- |
| M1 | Structured ingestion | Import the source pack; validate fields; classify signals and flag duplicates/missing values |
| M2 | Requirement registry | Table of measurable draft requirements, costs, constraints and source links |
| M3 | Future scenarios | Five trend records, three editable scenario assumption sets and documented score impacts |
| M4 | Deterministic ranker | Explicit weighted scoring plus budget/dependency/conflict validation |
| M5 | Four alternatives | Distinct optimization profiles with a portfolio comparison matrix |
| M6 | Evidence graph | Typed stored links and a clickable local graph for a selected requirement or option |
| M7 | Grounded copilot | Answer from project evidence and calculated results with passage-level citations |
| M8 | What-if loop | Change budget or one scenario assumption; recalculate and display differences |
| M9 | Human decision | Approve/reject/request revision with rationale and immutable snapshot |
| M10 | Export | Download the decision package and selected requirement rows |

### Explicitly deferred

Live social-media crawling, arbitrary PDF/OCR ingestion, autonomous agents browsing the internet, validated 2033 demand prediction, three-region operation, live collaboration, enterprise SSO, production compliance claims, dedicated graph infrastructure and PLM integration.

For hybrid decisions, permit requirement checkboxes followed by recalculation. Drag-and-drop strategy composition is optional.

## 4. Input contracts and fixture design

### 4.1 Source and signal fields

`source_id`, `title`, `source_type`, `origin`, `published_at`, `market`, `version`, `is_synthetic`.

Each excerpt adds `excerpt_id`, `source_id`, `locator`, `text`, `topic`, `observed_period`, `classification_status`, `duplicate_group` and optional `provided_customer_weight` plus `weight_definition`.

Locators identify a CSV row, Markdown heading/line range or another resolvable passage. Preserve raw input alongside extracted fields.

### 4.2 Requirement fields

`requirement_id`, `title`, `description`, `target_value`, `unit`, `test_conditions`, `verification_method`, `status`, `market`, `base_criterion_values`, `development_cost`, `cost_currency`, `cost_basis`, `cost_status`, `feasibility_status`, `dependencies`, `exclusions`, `evidence_ids`, `assumption_ids`.

Use one cost basis throughout the MVP, such as incremental development investment in euros. Do not mix per-vehicle component cost with program investment. Include shared enabling costs once using dependency items. Unknown costs are not zero.

A sample target such as “DC charging from 10% to 80% in at most 20 minutes” remains a synthetic draft unless operating temperature, charger conditions and engineering validation are supplied.

### 4.3 Fixture requirements

Include at least one mandatory requirement, one dependency, one mutually exclusive pair, one missing estimate, one duplicate signal, one contradictory source and one weakly supported assumption.

Construct the synthetic fixture so four distinct portfolios are feasible at the initial budget. This demonstrates the workflow, not a real-world recommendation. Include a second configuration with too few feasible alternatives to exercise honest failure behavior.

## 5. Forecasting and trend implementation

The first release is **scenario-based future reasoning**. It must not claim a statistically validated forecast from a sparse demo dataset.

For each trend, store:

- Observed evidence and dates, or an explicit statement that observations are unavailable.
- Baseline interpretation and evidence-quality label with a written justification.
- Slow, baseline and fast development assumptions for 2033.
- Qualitative continuation or reversal possibilities through 2040.
- Affected requirements and the exact mapping to future-relevance values or constraints.
- Counterevidence and a condition that would trigger reconsideration.

For the MVP, a reviewed lookup table may map each trend/scenario to each affected requirement's future-relevance value on a 0–100 scale. Display these values as **scenario evaluations**, not probabilities or demand forecasts. Each value must link to an assumption or a documented derivation.

Example assumption: slower charging-infrastructure development increases the scenario value assigned to long-distance self-sufficiency. The magnitude is a team assumption until calibrated; the copilot cannot silently supply it as a fact.

The PM can edit one driver, such as infrastructure development, and apply it. This creates a new scenario version and a new ranking run. Historical observations remain unchanged.

A time-series model is a later addition unless a suitable dataset is available. Any implementation using one must record the method, fit period, error/backtest results and limitations.

## 6. Ranking and portfolio generation

### 6.1 Requirement utility

For requirement `r`, future scenario `s` and objective profile `p`:

`utility(r, s, p) = sum(weight(p, k) * value(r, s, k))`

Weights are nonnegative and sum to 1. Criterion values use fixed, documented 0–100 rubrics; avoid per-run min/max scaling, which can change scores merely because a candidate was added.

Initial criteria:

| Criterion | Interpretation |
| --- | --- |
| Customer value | Reviewed customer evidence, not raw mention count |
| Future relevance | Scenario-dependent value at 2033 launch |
| Engineering feasibility | Reviewed maturity/risk evaluation, separate from hard blockers |
| Regional fit | Suitability for the defined European context |
| BMW experience | Explicit expert judgment about driving enjoyment and differentiation |

Store the evaluator and reasoning for every criterion value. Missing information remains visible. A requirement with unresolved cost or feasibility cannot be labeled feasible unless a named PM accepts a specific planning assumption, which remains part of the output.

### 6.2 Hard constraints

Select binary variables `x_r` for candidate requirements. Enforce:

- Total incremental development cost, including shared enablers once, is within budget.
- Mandatory requirements are selected.
- If requirement A depends on B, selecting A requires B.
- Mutually exclusive requirements cannot both be selected.
- Known engineering blockers prevent selection.

Selection must not silently relax these constraints. If a mandatory requirement is blocked, return “No feasible portfolio” with the conflict.

### 6.3 Four objective profiles

Suggested seed weights are configurable demo assumptions:

| Criterion | Customer-led | Future-led | BMW experience-led |
| --- | --- | --- | --- |
| Customer value | 0.40 | 0.20 | 0.20 |
| Future relevance | 0.20 | 0.40 | 0.15 |
| Engineering feasibility | 0.15 | 0.15 | 0.15 |
| Regional fit | 0.15 | 0.10 | 0.10 |
| BMW experience | 0.10 | 0.15 | 0.40 |

For these three profiles, maximize total selected utility subject to constraints. For **Cost-disciplined**, minimize spend while achieving a configurable common-utility floor; seed the floor at 85% of the best feasible common-utility result and label it as a demo setting.

Use a small binary optimizer or enumeration for the curated candidate set. A dedicated optimization service is optional. Stable requirement-ID ordering resolves equal solutions deterministically.

### 6.4 Distinctness and comparison

Deduplicate identical selections. Target at least two differing optional requirement selections between alternatives on the fixture. Search next-best candidates subject to diversity constraints if initial profile solutions coincide.

Do not select a clearly inferior portfolio only to meet a diversity quota. Flag dominance under common evaluation criteria and constraints. If four useful alternatives cannot be produced, return the available number with an explanation.

Profile-specific utilities explain generation; they must not be compared as though they share a scale of preference. For the comparison matrix, use a **single PM-selected comparison weight vector**, initially equal weights across the five criteria.

### 6.5 Robustness

Evaluate every portfolio in every future scenario under the common comparison weights. Show:

- Feasible scenarios out of three.
- Common utility under each scenario.
- Worst-case common utility among feasible scenarios.
- Regret relative to the best feasible portfolio under each scenario, when computed.

Label these as scenario comparisons, not probabilities or calibrated confidence scores. Do not reduce feasibility and uncertainty to a single unexplained “robustness percentage.”

## 7. Evidence and decision data model

| Entity | Minimum responsibility |
| --- | --- |
| Project | Active context and data-isolation boundary |
| Source / Excerpt | Original content, provenance and passage locator |
| Claim | Reviewed interpretation plus supporting/contradicting excerpt links |
| Trend / Scenario / Assumption | Dated future reasoning and scenario parameters |
| Requirement | Target, cost, criterion values, status and constraints |
| EvidenceEdge | Typed link between supported entities with provenance |
| RankingRun | Frozen inputs, hashes, weights, scenario and algorithm version |
| Portfolio | Selected requirement IDs, totals, exclusions and scenario evaluations |
| DecisionEvent | Human action, reviewer, rationale, timestamp and immutable run/portfolio reference |

Store graph edges in the same database as the structured records. Provide a small node-link view centered on the selected requirement or portfolio, plus a readable evidence list. The list remains usable if graph rendering fails.

Decision events are append-only in application behavior. This is not a claim of a tamper-proof enterprise audit system.

## 8. Screens and interactions

### Screen A: Decision workspace

Context header: concept, Europe, 2033, budget, selected future scenario and run status.

Main area: four strategy summaries above a side-by-side comparison matrix. Show selected requirements, spend, main strengths, sacrifices, assumptions and feasibility. A requirement table below supports selection and evidence inspection.

Right panel: contextual copilot, collapsible to provide more comparison width.

Primary actions: **Recalculate**, **Compare changes**, **Review decision**.

### Screen B: Future Radar

Five trend rows with source dates, observed direction where supported, evidence quality and the three scenario assumptions. Selecting a trend opens its sources and affected requirements.

Primary action: **Apply assumptions and recalculate**. Do not imply a continuous historical series where only qualitative evidence exists.

### Screen C: Evidence drawer

Open from a source badge, score contribution or requirement. Show the claim, exact source passage, date, region, assumptions, counterevidence and local graph. Keep the selected option visible behind the drawer.

### Screen D: Decision review and history

Summarize the selected version, constraints, unresolved assumptions and changes since the previous run. Require reviewer name and rationale. Available actions: approve, reject or request revision. Approval is blocked by known hard-constraint violations.

Show saved decisions and exports. Reopening creates a new draft; it never overwrites the prior approval.

This arrangement follows a PM's sequence of comparing, investigating, negotiating and documenting. The graph and chat support that sequence rather than becoming the only way to operate the product.

## 9. Grounded copilot contract

Supported intents:

1. Explain a portfolio or requirement with evidence and score contributions.
2. Compare two options under common weights.
3. Identify contradictions, weak evidence or missing information.
4. Explain a future assumption and its downstream effects.
5. Propose a structured budget or scenario change for PM review.

Retrieve only evidence belonging to the current project and run. Include exact excerpts and structured calculation outputs in context. Validate that cited IDs exist and resolve to the passages used.

Use a response structure of concise answer, supporting citations, relevant assumptions and optional proposed change. The application, not the language model, performs calculations and validates proposed changes.

If a requested figure is unavailable, say so. If the model service is unavailable, retain the deterministic ranking and evidence views and mark copilot unavailable. Do not disguise prerecorded answers as live model output.

## 10. Suggested implementation architecture

The following is an implementation proposal, not a mandated BMW stack:

- **Frontend:** React/Next.js with a table, comparison matrix and lightweight graph component.
- **Backend:** Python API for validation, deterministic scoring, optimization and retrieval orchestration.
- **Persistence:** PostgreSQL for structured records, typed graph edges and decision history; SQLite is an acceptable single-user prototype alternative.
- **Retrieval:** metadata-filtered full-text search initially; embeddings only if needed by the source pack.
- **LLM:** one available text model for cited explanations and structured extraction, accessed only from the backend.

Logical flow: reviewed inputs feed the requirement registry and future scenarios; the ranking service writes a frozen run; the UI and copilot read that run; the PM creates a decision event referencing it.

Suggested API boundaries:

| Operation | Contract |
| --- | --- |
| `POST /projects/{id}/imports` | Return accepted rows, validation errors and classification warnings |
| `GET /projects/{id}/requirements` | Return candidates with evidence and constraint metadata |
| `POST /projects/{id}/runs` | Validate context and generate versioned portfolios |
| `GET /runs/{id}` | Return frozen results and comparison data |
| `GET /runs/{id}/evidence` | Return scoped excerpts and graph links |
| `POST /runs/{id}/questions` | Return a grounded answer and optional change proposal |
| `POST /runs/{id}/decisions` | Validate state and record the explicit human decision |
| `GET /decisions/{id}/export` | Return a decision package and requirement export |

API paths are illustrative. Persist run IDs, source versions and decision references regardless of framework choices.

## 11. Build sequence

| Step | Build | Exit condition |
| --- | --- | --- |
| 1 | Fixture, schemas and import validation | Reviewed data can be loaded with errors and assumptions visible |
| 2 | Constraints, scoring and portfolio generation | Four distinct feasible fixture alternatives with reproducible calculations |
| 3 | Future assumptions and scenario evaluation | Changing one driver changes documented values and can change selection |
| 4 | Decision workspace and evidence drawer | A PM can compare options and locate supporting passages |
| 5 | Stored graph, contextual copilot and what-if changes | Questions cite evidence; applying a proposal creates a new run |
| 6 | Decision persistence and exports | Approval survives reload and exported contents match the approved snapshot |
| 7 | End-to-end verification and pitch rehearsal | All release gates pass and the core story fits three minutes |

If time is tight, reduce source count, graph styling and number of supported import formats. Preserve forecasting-to-ranking linkage, multiple alternatives, evidence lookup, human approval and grounded Q&A.

## 12. Acceptance checks and release gates

| ID | Check | Passing result |
| --- | --- | --- |
| A1 | Import duplicate and malformed input | Duplicate flagged; malformed row rejected or quarantined with reason |
| A2 | Rerun identical frozen inputs | Same scores, selected IDs and ordering |
| A3 | Evaluate default fixture | Four distinct, feasible portfolios with visible differences |
| A4 | Reduce budget below mandatory cost | Clear infeasibility result; no invented feasible option |
| A5 | Select a dependent or conflicting requirement | Dependency included or conflict blocked |
| A6 | Supply an unknown cost | No zero-cost substitution; unresolved status remains visible |
| A7 | Change a future driver | New scenario/run version, explicit score impact and a before/after comparison |
| A8 | Ask why a requirement was prioritized | Answer cites supporting excerpts and stored calculation contributions |
| A9 | Ask for unsupported information | Copilot acknowledges missing evidence without inventing a citation |
| A10 | Open any selected requirement | Evidence or accepted assumption is reachable |
| A11 | Approve a portfolio | Reviewer, rationale, timestamp and frozen version persist after reload |
| A12 | Edit inputs after approval | Prior approval unchanged; new draft generated |
| A13 | Export an approved decision | Selected IDs, costs, assumptions and source versions match its snapshot |
| A14 | Use fixture with fewer useful alternatives | Available options shown with explanation; no forced fourth answer |

Verification should focus on constraints, provenance, versioning and the end-to-end decision loop. UI styling changes do not require a separate test suite.

Performance goals on the actual demo machine: recalculation within five seconds for the curated fixture; copilot response within fifteen seconds with a visible loading state. These are targets to measure, not achieved claims.

## 13. Three-minute demonstration

| Time | Demonstration |
| --- | --- |
| 0:00–0:20 | State the problem: many signals, long planning horizon, competing requirements |
| 0:20–0:45 | Show the reviewed source pack and four portfolio alternatives |
| 0:45–1:15 | Open a requirement and show evidence, counterevidence and score contributions |
| 1:15–1:45 | Inspect the 2033 trend assumptions; ask the copilot why they matter |
| 1:45–2:20 | Apply a slower-infrastructure scenario or reduced budget; show changed portfolios |
| 2:20–2:45 | Select an option, record rationale and save a human decision |
| 2:45–3:00 | Export the package and state measured traceability/reproducibility results |

Choose one what-if change for the live pitch. Keep a saved scenario ready for recovery while labeling it accurately if used.

## 14. Definition of done

The MVP is complete when a reviewer can start with the labeled source pack, inspect future scenarios, generate and compare distinct feasible portfolios, verify the rationale, ask grounded questions, apply a change and save/export a human-approved decision without editing code.

All acceptance checks must pass. The team must disclose which data are synthetic, which values are assumptions, which forecasts are scenarios and which capabilities remain prototypes. Neither a future-demand prediction nor a production-ready BMW integration is required to demonstrate the intended decision workflow.
