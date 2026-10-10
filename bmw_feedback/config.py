"""Paths and constants shared by the whole pipeline.

All paths resolve from the repository root so the pipeline runs on any machine.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RAW_DIR = ROOT / "BMW-Data"
PROCESSED_DIR = ROOT / "data" / "processed"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

MODELS = ["F70", "G60", "G70"]
MODEL_NAMES = {"F70": "1 Series (F70)", "G60": "5 Series (G60)", "G68": "5 Series LWB (G68)", "G70": "7 Series (G70)"}

FEEDBACK_FILES = {m: RAW_DIR / f"{m}_feedback_hackathon.xlsx" for m in MODELS}
OPTION_LIST_FILES = {m: RAW_DIR / f"{m}_OptionList.PDF" for m in MODELS}
SURVEY_FILE = RAW_DIR / "F70_G60_G68_G70_customer_studies.xlsx"
SALES_FILE = RAW_DIR / "sales_volumes.xlsx"

# Raw column name -> pipeline column name
FEEDBACK_COLUMNS = {
    "ID": "comment_id",
    "Source": "source",
    "Brand": "brand",
    "Sales Description": "sales_description",
    "Country": "country",
    "Derivate (e-code)": "model",
    "Engine Type": "engine",
    "Feedback Type": "feedback_type",
    "Customer Feedback": "text_raw",
    "Vfc level2 3 Name": "vfc_l2_l3",
    "Vfc level2 Name": "feature",
    "Vfc level3 Name": "reason",
}

ENGINE_NAMES = {"ICE": "ICE", "BEVE": "BEV", "PHEV": "PHEV"}

# Feedback Type -> sentiment class used by the verdict
SENTIMENT = {
    "Likes": "positive",
    "Defect": "negative",
    "Difficult to Use": "negative",
    "Wants": "request",
}
FEEDBACK_TYPES = ["Defect", "Difficult to Use", "Wants", "Likes"]

# Labels that say nothing about a specific feature; excluded from verdicts
NON_FEATURE_LABELS = {"no_class_found", "General enquiry: customer feedback"}

# Country -> sales market (sales_volumes.xlsx uses EU / CN / US / RoW)
COUNTRY_TO_MARKET = {
    "US": "US",
    "GB": "EU", "FR": "EU", "SE": "EU", "DK": "EU", "FI": "EU", "NO": "EU", "ES": "EU", "LV": "EU",
    "JP": "RoW", "KR": "RoW", "AU": "RoW", "CA": "RoW", "ZA": "RoW",
}

# Verdict thresholds (see scoring.py)
MIN_MENTIONS_FOR_VERDICT = 8       # below this the feature is "cold start" -> domain prior only
PRIOR_STRENGTH = 5.0               # pseudo-count pulling small features toward their domain
BAD_INDEX = 1.25                   # complaint index at/above which a feature is "Bad" (CI must exclude 1)
GOOD_NEG_INDEX = 0.8               # complaint index at/below which a feature is "Good" (CI must exclude 1)
LEAN_BAD_INDEX = 1.15              # point estimate only -> "Leaning bad"
LEAN_GOOD_NEG_INDEX = 0.87         # point estimate only -> "Leaning good" (1/1.15)
REQUEST_INDEX = 1.5                # request index above which a feature is an unmet need
RANDOM_STATE = 42
