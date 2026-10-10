# PM Idea Evaluator: knowledge graph + three-agent evaluation

Date: 2026-10-10. Status: approved by the user ("implement approach A and do everything").

## Goal

A BMW product manager types a feature idea. The app answers, per series (F70, G60, G70) and market (EU, US, CN, RoW),
whether to pursue it, explains why in plain language, and proves that every sentence comes from the processed data
or a trained model. The frontend has one job: evaluating that idea.

## Decisions taken with the user

| Topic | Decision |
|---|---|
| Approach | A: engine-grounded fact bundle. The LLM never computes a number. |
| LLM provider | OpenAI, key in `OPENAI_API_KEY` (env or repo-root `.env`, git-ignored) |
| Models | Retriever + verifier: `gpt-6-luna`. Explainer: `gpt-6-terra`. Each overridable by env var; checked against the account's model list at first use and never silently replaced. |
| PM input | Free text. The retriever extracts an `IdeaSpec`; the PM confirms or edits it before evaluation. |
| Verifier failure | One rewrite with the failures fed back, then unsupported claims are removed and listed. |
| Page content | Explanation, verification report, series x market matrix, evidence graph, decision record + policy. |
| Old pages | Page files deleted; their API endpoints stay (tests and the evaluation use them). |
| Design | Tokens measured on bmw.de (crawl 2026-10-10). Buttons/inputs 3px as on bmw.de; content cards rounder (12-16px) by user choice; floating panels 8px + shadow. |
| Brand assets | Official BMW logo SVGs and BMW Type Next woff2 fetched from bmw.de for local use; git-ignored; fetch script committed; Barlow is the fallback. |
| No key | Retrieval falls back to rules + TF-IDF and is labelled as such; evaluation works; the explanation panel says it is unavailable (no template prose). |

## Architecture

```
build:   processed CSVs + models/ + reports/*.json --graph/build.py--> data/processed/knowledge_graph.json
                                                                       data/processed/graph_schema.json
request: idea --Agent 1 Retriever--> IdeaSpec (validated) --PM confirms-->
         DecisionEngine.evaluate (unchanged maths) --> FactBundle + evidence subgraph   (rendered immediately)
         --Agent 2 Explainer--> claims citing fact IDs --Agent 3 Verifier--> retry once --> strip  (fills in)
```

## Knowledge graph (networkx MultiDiGraph, node-link JSON)

Every node: `id` (`type:key`, keys are the source names), `type`, `label`, attributes, `prov` (table + key, or file + page).
Every edge: `rel`, attributes, endpoints that must exist (the builder refuses to create nodes implicitly).

| Node type | Count source | Provenance |
|---|---|---|
| Series (F70, G60, G70, G68 survey-only) | config | config.py |
| Variant | catalog_variants.csv | `<series>_OptionList.PDF` page |
| Market | 4 | config.py |
| SalesVolume (series group x market x year) | sales.csv | sales_volumes.xlsx |
| Domain | taxonomy (11) | reports/domain_scorecard.csv |
| Feature | feature_scorecard.csv (224) | reports/feature_scorecard.csv |
| Reason, ReasonFamily | labels.csv (84, 21) | taxonomy.py |
| Comment | comments.csv (10,128) | `<series>_feedback_hackathon.xlsx` |
| SurveyAttribute, SurveyScore | survey_cn_eu.csv, survey_us_summary.csv | customer_studies.xlsx |
| OptionItem, Package, TechSpec | catalog_*.csv | PDF page |
| FitmentSummary (feature x series) | catalog_feature_fitment_summary.csv | derived from the PDFs |
| VerdictCell (feature; feature x series; feature x series x market; domain) | scoring.score | model output |
| ModelArtifact (3 classifiers, complaint EBM, fitment re-ranker) | reports/*.json, models/ | model output |
| EBMTerm | model_ablation.json | model output |
| Caveat | computed from the data (e.g. "G70 tables cover 4 of 7 variants") | derived |

Relations: IN_DOMAIN, MENTIONS {sentiment, feedback_type, reason}, ABOUT, FROM_MARKET, HAS_REASON {sentiment, count},
IN_FAMILY, MEASURES, SCORES_ATTRIBUTE, FOR_SERIES, IN_MARKET, LISTED_FOR, FITTED_ON {status, price_eur},
VARIANT_OF, LINKED_TO {matched_keyword}, HAS_SPEC, SPEC_OF, INCLUDES, FITMENT_OF, ON_SERIES, HAS_SALES,
SCORES, PREDICTED_AS {p, model}, TERM_OF, CONTRIBUTES {bin, score}, QUALIFIES, LONG_WHEELBASE_OF.

The build asserts counts against the source tables (features, domains, variants, items, fitment rows, links,
comments, feature labels, specs) and fails loudly on a mismatch.

## Agents (bmw_feedback/agents)

1. Retriever (`gpt-6-luna`). Candidates come from code only: alias/name/fuzzy matches and the trained feature
   classifier (`DecisionEngine.resolve_idea`) plus a semantic index over feature documents (OpenAI
   `text-embedding-3-small`, cached; TF-IDF without a key). The LLM picks among candidate names and extracts
   series, markets, move (fix_existing, make_standard, new_option, price_change, introduce_on_series, unspecified)
   and a proposed price. Output is validated by `IdeaSpec` (features must be candidates, enums enforced, price > 0,
   at most 3 features). On a validation error the errors are fed back for up to 2 retries.
2. Explainer (`gpt-6-terra`). Receives the `FactBundle` (facts with stable IDs, deterministic statements, values,
   provenance) and writes an `Explanation`: headline, customer evidence, market view, price and equipment, risks and
   caveats, next steps. Every claim cites fact IDs.
3. Verifier (rules first, then `gpt-6-luna`). Per claim: citations present; cited IDs exist; every number matches a
   cited value at the displayed precision (percent forms included); recommendation and verdict labels match cited
   values; quoted text is a substring of a cited comment; series and markets named are in the cited facts' scope;
   then an LLM entailment check for what rules cannot see. Failures go back to the explainer once; anything still
   failing is removed and listed in the report.

## API (added; existing endpoints unchanged)

`GET /api/agent/status`, `POST /api/agent/interpret`, `POST /api/agent/evaluate`, `POST /api/agent/explain`,
`GET /api/graph/schema`, `GET /api/graph/node/{id}`.

## Frontend

One route. bmw.de layout patterns: transparent nav over a dark hero, sticky in-page tab bar with active underline,
key-figure rows (light label over light value) with 12px grey source notes, full-bleed dark bands. Sections: idea
input -> extracted IdeaSpec (editable) -> key figures -> explanation with citation chips and verification marks ->
series x market matrix with evidence panel -> price ladder -> evidence graph (cytoscape, instance and schema views,
node inspector) -> verification report -> decision policy + decision record.

## Testing

pytest with a fake LLM client (no network): graph counts and integrity, IdeaSpec validation and retry, rules
fallback, verifier catching a fabricated number, a wrong series, a misquote, and the retry-then-strip loop; API
status/interpret/evaluate/explain. Frontend: `tsc` build plus a Playwright screenshot pass.
