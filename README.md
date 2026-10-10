# BMW Product Idea Evaluation

Feature decisions for the BMW 1 Series (F70), 5 Series (G60) and 7 Series (G70), traced to the data in `BMW-Data/`: 10,128 customer comments, the 2025 customer studies (CN/EU and US), sales volumes 2024–2030 and the German price lists (July 2026).

A product manager types a feature idea ("make seat massage standard on the 5 Series in Europe"). Three agents and a deterministic decision engine answer it:

1. **Retriever agent** (`gpt-6-luna`) matches the idea to features in a **knowledge graph** of all processed data and model outputs, reads the scope (series, markets, move, price) and returns a validated Pydantic `IdeaSpec`. The PM confirms or edits it.
2. **Decision engine** (no LLM) computes every number: per series and market **Prioritise / Consider / Low priority / Insufficient evidence / Not sold** from complaints, breadth, requests, survey weakness and sales volume, plus the price-list position. It emits a bundle of facts, each with a stable ID and a pointer into the graph (table row, PDF page or model file).
3. **Explainer agent** (`gpt-6-terra`) writes a brief for product management in which every claim cites fact IDs.
4. **Verifier agent** (rules + `gpt-6-luna`) checks each claim: citations exist, every number matches a cited value, labels and quotes match, the series and markets named are covered, and the cited facts entail the claim. Failing claims go back for one rewrite and are removed if they still fail.

Weights and market emphasis are an explicit, hashed policy. Two PMs using the same policy and data get the same answer, and a PM override is logged with its rationale.

```
python -m bmw_feedback serve          # http://127.0.0.1:8000
```

The full analysis is in **[reports/REPORT.md](reports/REPORT.md)**.

---

## Quick start

```bash
pip install -r requirements.txt
# put the hackathon files in BMW-Data/ (git-ignored)

python -m bmw_feedback all            # build + train + knowledge graph + figures (~6 min)
cd frontend && npm install && npm run build && cd ..
python -m bmw_feedback serve          # API + web app on http://127.0.0.1:8000

python -m pytest tests -q             # graph, agents (scripted LLM, no network) and API checks
```

### OpenAI key and models

The explainer and verifier need an OpenAI key; without one the app still matches ideas (with transparent rules and TF-IDF) and shows all evidence, and says that the written brief is unavailable. Put the key in the environment or in a git-ignored `.env` in the repository root:

```
OPENAI_API_KEY=sk-...
OPENAI_RETRIEVER_MODEL=gpt-6-luna         # defaults shown; override any of them
OPENAI_EXPLAINER_MODEL=gpt-6-terra
OPENAI_VERIFIER_MODEL=gpt-6-luna
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

`python -m bmw_feedback agent --check` lists which configured models the key can use. A model the key cannot use is reported with the available ones; it is never swapped silently. `python -m bmw_feedback agent "your idea"` runs the whole pipeline in the terminal.

### BMW logo and font (local only)

The official BMW logo and BMW Type Next are BMW's trademark and licensed font. They are not in the repository. `frontend/scripts/fetch-brand-assets.cjs` fetches them from bmw.de into the git-ignored `frontend/public/brand` and `frontend/public/fonts` for local use (it needs Playwright). Without them the app shows a text wordmark and uses Barlow.

For frontend development, run `npm run dev` in `frontend/` (port 5173). It proxies `/api` to the server on port 8000.

Command-line access works without the app:

```bash
python -m bmw_feedback verdict --feature "head-up display"
python -m bmw_feedback verdict --text "The wireless charger keeps overheating my phone"
python -m bmw_feedback verdict --list
```

## The web app

One page, built for evaluating an idea:

| Section | What it shows |
|---|---|
| Idea | Free-text input, then the retriever's reading of it: candidate features (with how each was found: name/alias, classifier, semantic), series, markets, move and price, all editable before evaluation |
| Pipeline | The four steps (retriever, decision engine, explainer, verifier) with the model behind each and its result |
| Overview | Key figures: priority score, Prioritise / Consider cells, evidence coverage, customer verdict, claims verified |
| Explanation | The brief for product management; every claim has numbered citations that open the fact and its source and can jump to the node in the graph |
| Series × markets | Recommendation matrix with an evidence panel per cell (signals, weights, reasons, quotes, survey rows, price-list items) |
| Price & equipment | Price ladder across the three series and the linked technical data |
| Knowledge graph | The part of the graph this evaluation touched (cited nodes ringed) and a schema view of how all the data connects; a node inspector shows each node's source, attributes and relations |
| Verification | Every claim with the result of each rule and the entailment check; what was rewritten and what was removed |
| Decision | Adjustable decision policy and the decision record (accept / override with rationale, logged with policy and data hashes) |

Design: tokens measured on bmw.de (`--cta #1c69d4`, `--nba #262626`, `--border #e6e6e6`, status pairs, 3px controls, 84px navigation, 300/500/700 weights, uppercase stage headline, sticky in-page tab bar, technical-data fact rows). Content cards use 12–16px corners by product choice. See `frontend/src/styles/tokens.css`.

## Knowledge graph and agents

`python -m bmw_feedback graph` writes `data/processed/knowledge_graph.json` (networkx, node-link; about 15,000 nodes and 58,000 edges) and `graph_schema.json`. The build checks node and edge counts against the source tables (224 features, 10,128 comments, 11,214 feature labels, 23 variants, 364 price-list items, 2,224 option fitment rows, 1,494 feature fitment rows, 1,442 survey answer shares, …) and fails on any mismatch. Dashboard re-exports, figure statistics and model internals are left out on purpose; the list is in `graph_schema.json`.

| Node types | From |
|---|---|
| Series, Variant, Powertrain, OptionItem, Package, FitmentSummary, TechSpec | price-list PDFs (page references) |
| Market, SalesVolume, FeedbackCoverage | sales_volumes.xlsx, market representativeness |
| Domain, Feature, Reason, ReasonFamily, Comment | feedback exports, taxonomy |
| SurveyAttribute, SurveyScore | customer studies |
| VerdictCell, ModelArtifact, EBMTerm | scoring, classifiers, complaint EBM, fitment re-ranker |
| Caveat | limits of the data, computed from it (e.g. "the G70 equipment tables cover 4 of 7 variants") |

```
bmw_feedback/graph/    build.py (graph + validation), store.py (load, node inspector), semantic.py (feature index)
bmw_feedback/agents/   contracts.py (Pydantic), retriever.py, facts.py, explainer.py, verifier.py, evidence.py, pipeline.py, llm.py
```

API: `POST /api/agent/interpret`, `POST /api/agent/evaluate`, `POST /api/agent/explain`, `GET /api/agent/status`, `GET /api/graph/schema`, `GET /api/graph/node/{id}`.

## Pipeline

```
BMW-Data/*.xlsx, *.PDF
   │  load.py            feedback, CN/EU + US surveys, sales volumes
   │  option_catalog.py  price-list PDFs: variants, base prices, ■/□ fitment per variant, option prices,
   │                     packages, technical data; validated on every build
   ▼
clean.py                 one row per comment + one row per label; strip label leakage and templates
taxonomy.py              11 domains ← 224 features ← 84 reasons; survey and price-list link maps
scoring.py               channel-adjusted complaint / praise / request indices with 95% intervals → verdict
classifier.py            TF-IDF + logistic regression: comment → type, domain, feature
                         (+ price-list fitment re-ranker when the car is known)
risk_model.py            explainable boosting machine: what drives complaints (glass box)
decision.py              idea → features → per series × market recommendation + suggested move
graph/                   knowledge graph of the processed tables and model outputs (validated against the sources;
                         the few deliberate exclusions are listed in graph_schema.json)
agents/                  retriever → decision engine facts → explainer → verifier
api.py                   FastAPI; serves frontend/dist
```

### What the price lists feed

The PDFs are parsed from glyph and text positions, not from text order. Every build checks that:
- all 1,889 ■/□ marks on the 32 table pages land in a variant column;
- all 1,128 option prices and 23 base prices satisfy gross = net × 1.19;
- power on the price pages matches the technical data for all 23 variants.

One printed anomaly (F70 p.17) is kept as printed. 106 feedback features are linked to price-list items through a curated keyword map, and each link shows the keyword that produced it.

| Layer | Use of the price lists | Measured effect |
|---|---|---|
| Feature classifier | Re-ranks candidates by the feature's fitment on the comment's car | +0.6 pp top-1 on comments about linked features (26 fixed, 4 broken, McNemar p = 0.0001) |
| Complaint model | Fitment tier, option price and % of base price as inputs | No held-out gain (AUC −0.0008, feature-grouped CV), so the production model uses context only; the price-list variant is kept for audit |
| Decision engine | Price ladder across series, standard vs optional vs not listed, suggested move | Deterministic, with page references |

## Outputs

| Path | What |
|---|---|
| `reports/REPORT.md` | Findings, method, roadmap |
| `reports/model_ablation.json` | Price-list ablations for both models, EBM shape functions |
| `reports/classifier_metrics.json`, `data_quality.json` | Classifier CV metrics, cleaning and PDF-validation counts |
| `data/processed/catalog_*.csv` | Parsed price lists: variants, items, fitment, packages, technical data, feature links |
| `data/processed/knowledge_graph.json`, `graph_schema.json` | Knowledge graph and its schema with the integrity checks |
| `data/decisions.jsonl` | Decision log written by the app (git-ignored) |

## Repository layout

```
bmw_feedback/     pipeline package, knowledge graph, agents and API
frontend/         React + Vite web app (built into frontend/dist)
tests/            graph, agent and API checks
docs/             design spec
reports/          report, figures, scorecards, metrics
BMW-Data/         raw hackathon data (not committed)
```

This repository previously held **Demandra**, our procurement demand-prediction solution for Challenge 2 of the Unite x TUM.ai Hackathon (1st place). The original code is in git history.
>>>>>>> 6f85e34 (Initial project setup and data exploration scaffold)
