# BMW Data Layer

This folder contains the cleaned and classified outputs derived from the BMW customer-feedback datasets.

## Folder structure
- `raw/` reserved for source material if copied into the repo
- `processed/` contains normalized datasets for product analysis and requirement generation

## Cleaned outputs
- `feedback_cleaned.csv`: cleaned customer feedback records with normalized columns, sentiment, category, and priority score
- `requirements_candidates.csv`: aggregated category-level signal for each derivative, ready for prioritization

## Data model
Each record in the cleaned customer-feedback dataset includes:
- `id`: source record identifier
- `source_file`: workbook name
- `derivative`: vehicle derivative (`F70`, `G60`, `G70`)
- `source`: origin of the feedback
- `country`: market/country location
- `feedback_type`: normalized type (`Positive`, `Negative`, `Opportunity`, `Unknown`)
- `sentiment`: `positive`, `negative`, `opportunity`, or `unknown`
- `category`: inferred issue category from the VFC text
- `customer_feedback_clean`: cleaned text for analysis
- `priority_score`: simple prioritization weight for downstream review

## Recommended next step
Use the processed tables to derive product requirements, validate top themes by derivative, and prepare the PM review workflow.
