"""Central configuration: paths, market mapping, and every tunable weight of the
prioritization logic. Anything a PM might want to challenge lives here so the
scoring stays explainable and reproducible (the weights version is written to
the audit trail on every build)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "BMW-Data"
DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
EXTERNAL_DIR = DATA_DIR / "external"
RESEARCH_DIR = EXTERNAL_DIR / "research"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "pm_copilot.db"
FRONTEND_DIR = ROOT / "frontend"

# --------------------------------------------------------------------------
# Markets
# --------------------------------------------------------------------------
# Sales volumes are reported for four regions; verbatim feedback is reported by
# country. Every country is folded into the sales region it is planned under.
REGIONS = ["EU", "CN", "US", "RoW"]
REGION_NAMES = {"EU": "Europe", "CN": "China", "US": "USA", "RoW": "Rest of World"}
EUROPE = {"GB", "FR", "SE", "DK", "FI", "NO", "ES", "LV", "DE", "IT", "NL", "BE",
          "AT", "CH", "PL", "PT", "IE", "CZ"}
COUNTRY_TO_REGION = {**{c: "EU" for c in EUROPE}, "US": "US", "CN": "CN"}
DEFAULT_REGION = "RoW"  # JP, KR, CA, AU, ZA, ...


def region_of(country: str) -> str:
    return COUNTRY_TO_REGION.get(str(country).strip().upper(), DEFAULT_REGION)


# --------------------------------------------------------------------------
# Vehicles
# --------------------------------------------------------------------------
# G68 is the long-wheelbase China version of the 5 Series: it shares the G60
# sales sheet and is the 5 Series column of the China customer study.
DERIVATIVES = {
    "F70": {"name": "BMW 1 Series", "segment": "premium compact hatchback",
            "sales_sheet": "F70", "survey_models": {"EU": "F70"}},
    "G60": {"name": "BMW 5 Series", "segment": "executive sedan (incl. i5; G68 LWB in China)",
            "sales_sheet": "G60_G68", "survey_models": {"EU": "G60", "US": "G60", "CN": "G68"}},
    "G70": {"name": "BMW 7 Series", "segment": "luxury sedan (incl. i7)",
            "sales_sheet": "G70", "survey_models": {"EU": "G70", "US": "G70", "CN": "G70"}},
}
HORIZONS = ["2024", "2025", "2030"]
DEFAULT_HORIZON = "2030"  # requirements are for the successor vehicle

# --------------------------------------------------------------------------
# Signal model
# --------------------------------------------------------------------------
# How hard each kind of customer statement pushes on priority.
SIGNAL_WEIGHT = {"defect": 1.0, "usability": 0.7, "request": 0.6, "praise": 0.0}
# Source C (quality survey) states its own severity; scale those findings.
SEVERITY_MULTIPLIER = {"very serious": 1.5, "serious": 1.25, "": 1.0,
                       "minor": 0.8, "very minor": 0.6}
SOURCE_KIND = {
    "Source A": "public_review",     # owner reviews (GB, US, JP, KR, SE, ...)
    "Source B": "dealer_report",     # "Customer stated ..." contact notes (US)
    "Source C": "quality_survey",    # "I had a serious problem with ..." (US)
    "Source D": "loyalty_survey",    # "the one thing I love most about ..." (US)
}

# Small regional samples are pulled toward the vehicle-wide rate (empirical
# Bayes shrinkage). PRIOR_STRENGTH = how many pseudo-verbatims the prior is worth.
PRIOR_STRENGTH = 50
MIN_REGION_BASE = 30  # below this many verbatims a region counts as "not covered"

# --------------------------------------------------------------------------
# Prioritization
# --------------------------------------------------------------------------
WEIGHTS_VERSION = "2026-10-10.1"
# Requirement types:
#   FIX     - customers complain about something that exists (defect / hard to use)
#   ADD     - customers ask for something they do not have (request / unmet need)
#   PROTECT - customers love it; the successor must not lose it
#   FEATURE - created by a PM from the Feature Explorer
PRIORITY_WEIGHTS = {
    "FIX":     {"customer_signal": 0.35, "market_reach": 0.25, "survey_gap": 0.20,
                "competitive": 0.05, "feasibility": 0.15},
    "ADD":     {"customer_signal": 0.30, "market_reach": 0.25, "survey_gap": 0.10,
                "competitive": 0.20, "feasibility": 0.15},
    "PROTECT": {"customer_signal": 0.40, "market_reach": 0.30, "survey_gap": 0.20,
                "competitive": 0.10, "feasibility": 0.00},
}
PRIORITY_WEIGHTS["FEATURE"] = PRIORITY_WEIGHTS["ADD"]
# Signal intensity that saturates the customer_signal factor: severity-weighted
# verbatims per 1,000 verbatims of the vehicle (log-scaled below this point).
SIGNAL_SATURATION_PER_1000 = 40.0
# Evidence moderates the score instead of hiding weak-but-loud topics:
# final = raw * (EVIDENCE_FLOOR + (1 - EVIDENCE_FLOOR) * evidence_score)
EVIDENCE_FLOOR = 0.75
TIERS = [("P1", 55.0), ("P2", 38.0), ("P3", 0.0)]
EVIDENCE_LEVELS = [("High", 0.70), ("Medium", 0.45), ("Low", 0.0)]
# Candidate generation thresholds (unique verbatims per vehicle and component).
MIN_FINDINGS = {"FIX": 4, "ADD": 3, "PROTECT": 12}
PROTECT_MIN_PRAISE_SHARE = 0.70
# Praise counts less than a complaint when sizing a "keep" (PROTECT) requirement.
PROTECT_PRAISE_WEIGHT = 0.35

# Purchase-decision sensitivity used in the sales-at-stake scenario. These are
# assumptions, surfaced in the UI and overridable per request.
DECISION_SENSITIVITY = {
    "Must-be": 0.10, "Unmet need": 0.06, "Performance": 0.05,
    "Attractive": 0.03, "Indifferent": 0.0, "Insufficient signal": 0.0,
}

# --------------------------------------------------------------------------
# Claude (optional: competitor web research, challenge answers)
# --------------------------------------------------------------------------
CLAUDE_MODEL = "claude-opus-5-5"
