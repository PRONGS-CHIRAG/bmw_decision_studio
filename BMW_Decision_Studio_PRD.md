# BMW Decision Studio
## Product Requirements Document

| Field | Value |
| --- | --- |
| Version | 1.0 |
| Date | 10 October 2026 |
| Status | Proposed product specification for the Munich EHL Finale |
| Primary user | Automotive product manager responsible for future vehicle requirements |
| Initial context | One European battery-electric vehicle concept targeting 2033 |
| Planning horizon | Launch in 2033, with scenarios extending through 2040 |
| Companion document | BMW_Decision_Studio_MVP.md |

## 1. Product summary

BMW Decision Studio turns customer feedback, competitor information, engineering constraints and future trends into several defensible vehicle requirement portfolios. Product managers compare the alternatives, inspect their evidence, ask grounded questions, change assumptions and make the final decision.

The product combines four capabilities:

1. **Future Trend Intelligence:** distinguish current observations from plausible developments in 2033 and beyond.
2. **Explainable Multi-Objective Ranker:** construct and compare three to four meaningfully different requirement portfolios within explicit constraints.
3. **Evidence Graph and Decision Memory:** preserve the sources, assumptions, trade-offs, alternatives and human rationale behind every decision.
4. **Human-in-the-Loop Scenario Copilot:** help the product manager investigate and revise options without surrendering decision authority.

**Product promise:** understand the options, see why they differ, choose deliberately and retain the reasoning for future review.

The ranker proposes alternatives. The graph explains and remembers them. The copilot helps users investigate. The product manager decides.

## 2. Basis and boundaries

This specification is based on the supplied BMW kickoff/deep-dive notes and the subsequent concept discussion. It is a team proposal, not an official BMW specification or confirmed procurement requirement.

The notes emphasize human control, trend capture, structured ingestion, explainability and actionable prioritization. They describe fragmented information and presentation-based decision tracking. No formal numerical judging rubric or fixed benchmark has been provided.

No BMW dataset or trend-report attachment was available when this document was prepared. All sample strategies, weights, thresholds and evaluation targets below are proposed design choices. They are not measured BMW results.

The BEV scope is a product scenario. The notes' reference to an EU “2033/2035 BEV-only mandate” is unverified and must not be encoded as a legal fact. Any regulatory constraint requires a dated, authoritative source and applicability review before use.

## 3. Problem and opportunity

Vehicle planning requires balancing customer needs, cost, engineering feasibility, market differences and BMW's driving experience over a long product lifecycle. The evidence is fragmented across customer research, competitor sheets, sales information, social media and consulting reports.

The difficult work is deciding which requirements deserve investment, how competing requirements interact and whether the reasoning will still hold when the vehicle launches. A summary of documents does not resolve these trade-offs.

| Pain point | Product response |
| --- | --- |
| More information than a PM can consume | Classified, deduplicated evidence linked to specific requirements |
| Conflicting requests and limited resources | Explicit constraints and several comparable portfolios |
| Present-day preferences may change by 2033 | Scenario-based future value and sensitivity analysis |
| Recommendations lack a defensible explanation | Traceable score contributions, sources, counterevidence and assumptions |
| Reasoning is lost in presentation files | Versioned decision records with rejected alternatives retained |
| AI output can displace human judgment | Review, modification and approval remain explicit human actions |

## 4. Users and jobs to be done

| User | Primary job | Success condition |
| --- | --- | --- |
| Product manager / vehicle project lead | Decide which requirements belong in a future vehicle concept | Can compare viable choices and explain the selected portfolio |
| Engineering reviewer | Assess feasibility, dependencies and measurable targets | Can identify unsupported assumptions and specify validation work |
| Market or customer analyst | Curate signals and challenge projections | Can trace each interpretation to its source and regional context |
| Decision sponsor | Review investment trade-offs and approvals | Can inspect a concise decision record and its supporting evidence |

Primary job story: “When preparing a future vehicle requirements review, I need several feasible choices with clear trade-offs, so I can make a decision that is defensible today and understandable years later.”

The MVP centers on the product manager. Separate enterprise role permissions and multi-reviewer workflows follow later.

## 5. Goals, outcomes and non-goals

### Goals

- Reduce the effort required to produce a reviewable requirement portfolio from heterogeneous inputs.
- Produce up to four distinct, feasible alternatives rather than one opaque recommendation.
- Make every selected requirement traceable to evidence or an explicitly accepted assumption.
- Connect future scenarios to actual changes in requirement priorities.
- Preserve human decisions and the exact information available at decision time.
- Export structured candidate requirements for engineering review.

### Non-goals

- Autonomous vehicle design, engineering certification or production release approval.
- Claiming accurate knowledge of customer demand in 2033 or 2040.
- Treating social-media frequency as representative customer demand.
- Inventing cost estimates, regulatory rules or technical feasibility.
- Replacing existing requirements-management or product-lifecycle systems in the first release.
- Producing four options when fewer feasible, distinct portfolios exist.

## 6. Core concepts

| Concept | Meaning |
| --- | --- |
| Signal | A dated observation or excerpt from a source |
| Claim | A structured interpretation supported or contradicted by signals |
| Requirement | A proposed, measurable vehicle capability with acceptance conditions |
| Trend | A theme whose development over time may affect requirement value |
| Future scenario | A coherent set of assumptions about a possible market and technology future |
| Strategy / portfolio | A feasible set of selected requirements and their associated trade-offs |
| Decision record | A human action against a specific portfolio version, with rationale |

**Three future scenarios and four strategy alternatives are different dimensions.** Each strategy must be evaluated under each future scenario; the UI must not confuse a possible future with a vehicle design choice.

## 7. End-to-end user workflow

1. **Define the planning context:** vehicle concept, target market, launch year, planning horizon, budget and mandatory requirements.
2. **Review the evidence:** upload available inputs; inspect source dates, classifications, duplicates and unsupported claims.
3. **Review future assumptions:** inspect trends, select a future scenario and adjust documented assumptions.
4. **Generate alternatives:** create four distinct portfolios where feasible; show included requirements, cost, constraints and unresolved issues.
5. **Compare and investigate:** examine evidence, conflicts, criterion contributions and performance under alternative futures.
6. **Revise:** change priorities, costs or assumptions; create a new run and view differences from the previous one.
7. **Decide:** approve, reject, request revision or assemble a hybrid for recalculation. Record the human rationale.
8. **Export and revisit:** export the approved planning package; retain prior options and trigger review when critical assumptions change.

## 8. Functional requirements

### FR-01: Context and evidence ingestion

The system shall accept structured customer feedback, competitor fact sheets, engineering estimates and text reports. Source metadata must include origin, date, region, version and evidence type. Provided customer weights must be retained with their meaning and provenance.

Before use, signals must be classified by topic, market, period and relevance. Duplicate or syndicated content must not be counted as independent support. Extraction failures and unmapped fields must be visible in an ingestion report.

**Acceptance:** a PM can trace any extracted claim to the original row or text passage and review uncertain classifications before they influence a ranking.

### FR-02: Requirement registry

Each requirement shall have an ID, title, description, measurable target, unit, validation conditions, market, rationale, evidence links, cost basis, feasibility status, dependencies and conflicts. Missing targets or estimates remain explicitly unknown.

Requirements may begin as drafts. Selection into a portfolio does not automatically make a draft engineering-ready.

**Acceptance:** incomplete requirements are visibly marked and cannot be exported as validated engineering commitments.

### FR-03: Future Trend Intelligence

The system shall connect dated historical and current evidence to trends relevant to 2033 and a configurable longer horizon, initially through 2040. It shall support slow, baseline and fast development scenarios with named assumptions.

Where suitable quantitative history exists, a documented forecasting method may estimate trajectories. Where it does not, the system shall present qualitative or numerical scenario assumptions with their provenance. Scenario ranges must not be labeled statistical confidence intervals.

Each trend must show observation period, market, source freshness, evidence quality, conflicting signals, scenario drivers and affected requirements. Future changes shall affect scores or constraints through documented mappings.

**Acceptance:** a PM can change an assumption, see which requirement values change and reproduce the resulting ranking. Unsupported forecasts are labeled as assumptions, not observations.

### FR-04: Explainable ranking

The ranking model shall use explicit criteria, normalization rules and PM-adjustable weights. Initial criteria are customer value, future relevance, feasibility, regional fit and BMW driving experience. Cost is a hard budget constraint in the initial implementation; any later cost-efficiency criterion must be explicitly enabled to avoid accidental double counting.

Hard constraints shall be evaluated separately from preference scores. They include budget, mandatory capabilities, incompatible features and dependencies. Unknown feasibility or missing costs shall block definitive feasibility claims until resolved or accepted as explicit planning assumptions.

**Acceptance:** identical inputs and model versions produce identical rankings. The PM can inspect every criterion contribution and the reason a requirement is excluded.

### FR-05: Multiple strategy alternatives

The system shall target four feasible alternatives using different objective profiles:

| Alternative | Emphasis |
| --- | --- |
| Customer-led | Documented customer value within the target market |
| Future-led | Projected 2033 relevance under the selected future scenario |
| Cost-disciplined | Lower development spend while meeting a stated value floor |
| BMW experience-led | Driving enjoyment and differentiation alongside mandatory EV capability |

All four must use the same disclosed evidence and constraint context. They must differ in selected requirements or meaningful target levels, not just their names. Dominated and near-duplicate solutions should be flagged or excluded from the main comparison.

**Acceptance:** the comparison explains at least one consequential difference for each option. If only two distinct feasible alternatives exist, it shows two and explains the limiting constraints rather than manufacturing four.

### FR-06: Scenario comparison and robustness

Every portfolio shall be evaluated across the three future scenarios using the same comparison weights. The interface shall show value, feasibility and sensitivity separately. A robust option is one that remains viable and performs acceptably across stated scenarios; this is not a probability of real-world success.

**Acceptance:** changing an assumption creates a versioned result, highlights additions/removals and shows why the preferred option changes or remains unchanged.

### FR-07: Evidence graph and decision memory

The graph shall link sources, excerpts, claims, trends, assumptions, requirements, portfolios, runs and human decisions. Relationships include supports, contradicts, derived from, depends on, excludes, selected in, evaluated under and supersedes.

Every alternative, including rejected ones, shall remain inspectable. Decision records must reference immutable snapshots of inputs, scoring configuration, scenario assumptions and portfolio contents.

**Acceptance:** a reviewer can reconstruct what was selected, what was rejected, who decided, why they decided and which evidence version was used.

### FR-08: Grounded scenario copilot

The copilot shall answer questions within the active project, portfolio and run. Factual claims must cite source passages; calculations must reference structured scoring or optimization results. Unsupported questions should receive a clear explanation of missing evidence.

Examples include “Why is faster charging preferred?”, “Which source contradicts this assumption?” and “What changes if charging infrastructure develops more slowly?”

The copilot may propose structured changes. Applying those changes requires an explicit PM action and creates a new run. It cannot approve decisions or silently rewrite constraints.

**Acceptance:** answers distinguish evidence, assumptions and model outputs. Citation links resolve to the supporting passage rather than only a document title.

### FR-09: Human review and approval

The PM shall be able to approve, reject, request revision or modify a portfolio. Approval and rejection require rationale. A hybrid portfolio must be revalidated before approval.

An approval applies only to the reviewed version. Changed evidence or constraints create a draft revision; they cannot alter the approved snapshot. Approval means approval of a planning decision, not technical certification.

**Acceptance:** hard-constraint violations block approval. Unresolved assumptions must be acknowledged and recorded; exports preserve them.

### FR-10: Export and reopening

The system shall export a decision summary and structured requirement list containing selected targets, evidence references, assumptions, validation status, decision owner, timestamp and version. Later releases shall integrate with existing enterprise requirements tools.

Decision records shall support explicit reconsideration triggers, such as a material cost revision or contradictory customer evidence. Reopening preserves the original decision.

**Acceptance:** the exported package is sufficient to understand the selected portfolio without access to the chat transcript.

## 9. Product-manager interface

Use a desktop-first workspace with a broad central decision area, compact navigation and an optional contextual copilot panel. Keep the graph and source viewer available on demand.

| Area | Contents | Why this serves PMs |
| --- | --- | --- |
| Context header | Concept, market, horizon, budget, run version and status | Keeps the scope of a decision visible |
| Strategy workspace | Four compact option summaries and a comparison matrix | Enables trade-off review without reading long AI responses |
| Requirement table | Priority, target, cost, feasibility, evidence quality and selection | Supports sorting and reviewing many requirements |
| Evidence drawer | Source passages, assumptions, counterevidence and local graph | Gives fast verification without a full-screen graph |
| Future Radar | Trends, scenario assumptions and effects on requirements | Makes future reasoning inspectable |
| Copilot panel | Questions and proposed changes tied to the current selection | Supports investigation without losing context |
| Decision history | Review actions, rationale, versions and superseded decisions | Preserves accountability and continuity |

Key interaction rules:

- Put comparable quantities in aligned columns with units and visible definitions.
- Show “unknown”, “assumption” and “observed” explicitly; do not hide them in tooltips.
- Display strengths and sacrifices for every alternative.
- Keep the active future scenario separate from the selected strategy.
- Use an explicit “Apply and recalculate” step for changes, followed by a before/after view.
- Make approval available after review, with version and rationale visible.
- Support keyboard navigation and use text/icons as well as color for status.

This UI hypothesis is based on the workflow, not completed BMW user research. Validate it with product managers using comparison, evidence lookup and revision tasks.

## 10. Data and technical principles

Separate language interpretation from numerical decision logic. LLMs may extract claims and summarize cited evidence. A deterministic service evaluates constraints, scores requirements and generates portfolios.

The graph is a logical data model; a dedicated graph database is not required for the first release. Relational tables and typed edges can preserve traceability while keeping implementation manageable.

Minimum entities: Project, Source, Excerpt, Claim, Trend, Scenario, Assumption, Requirement, RequirementDependency, RankingRun, Portfolio, PortfolioRequirement, EvidenceEdge and DecisionEvent.

Every calculation must retain its data snapshot, weights, normalization rules, solver/model version and deterministic tie-breaking policy. Confidence in evidence is distinct from customer value or strategic importance.

## 11. Quality and operational requirements

| Area | Requirement |
| --- | --- |
| Reproducibility | Frozen inputs produce the same numerical result |
| Grounding | No fabricated citations, figures or source passages |
| Isolation | Retrieval is limited to the active project and permitted sources |
| Persistence | Approval records and portfolio snapshots survive application restart |
| Failure behavior | Model or ingestion failures produce explicit states; no silent success |
| Data handling | Use approved data-processing destinations; keep secrets out of the client |
| Review safety | Source text is evidence, never authority to execute instructions or approve changes |
| Usability | Core comparison and evidence lookup work without using chat |

Enterprise identity, fine-grained permissions, retention policies and independent audit controls are required before organizational deployment; a hackathon demo must not claim these are complete.

## 12. Success metrics

Targets are provisional and must be reported with their sample size and measurement method.

| Metric | Proposed target / method |
| --- | --- |
| Traceability coverage | 100% of selected requirements link to evidence or an explicitly accepted assumption |
| Feasibility correctness | Zero hard-constraint violations among portfolios labeled feasible |
| Alternative quality | Four distinct feasible portfolios on the prepared fixture; honest shortfall elsewhere |
| Decision completeness | 100% of approvals/rejections include reviewer, rationale, version and timestamp |
| Reproducibility | Same input snapshot and configuration yield the same portfolio result |
| Grounded answers | Every factual claim in the curated demo questions has supporting evidence or is marked unsupported |
| Evidence retrieval usability | PM can locate a recommendation's supporting passage without chat |
| Workflow efficiency | Compare time to a reviewable portfolio with a manual baseline using identical inputs |

Do not claim a percentage productivity improvement or forecast accuracy without measured evidence. Evaluate future-demand forecasting through historical backtesting only when adequate historical data exists.

## 13. Delivery stages

| Stage | Deliverable |
| --- | --- |
| MVP | One context, curated ingestion, explicit scenarios, four portfolios, evidence inspection, grounded Q&A, recalculation and approval/export |
| Iteration 2 | Richer imports, historical forecasting, regional comparisons, sensitivity analysis and review triggers |
| Iteration 3 | Enterprise collaboration, access controls, approved external feeds and lifecycle-tool integration |

The companion MVP document defines the initial build contract and release gates.

## 14. Risks and open decisions

| Risk / question | Response |
| --- | --- |
| Sparse data creates false forecasting precision | Use transparent scenarios; distinguish assumptions from fitted forecasts |
| Correlated sources exaggerate demand | Deduplicate and retain source families and sampling caveats |
| Additive scores miss requirement interactions | Model dependencies, exclusions and shared costs explicitly |
| Weight choices predetermine a preferred option | Expose weights and compare all portfolios under common evaluation weights |
| Model invents cost or feasibility | Require supplied estimates or visible planning assumptions |
| Available BMW data is still unknown | Build import contracts and a labeled synthetic fixture first |
| BMW's approval process differs from the prototype | Validate owners, review gates and export format in the deep dive |
| “Engineering-ready” is overstated | Preserve draft targets, validation conditions and unresolved assumptions |

Before a pilot, confirm the intended PM workflow, permissible data use, cost basis, requirement schema, available historical trend data and the meaning of approval within BMW.
