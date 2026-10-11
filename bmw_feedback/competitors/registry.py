"""Fixed vocabularies of the competitor data: markets, segments, record fields, spec attributes, equipment items.

Everything a research agent may write into a record is checked against these lists by records.validate().
"""

from .. import config

DATA_DIR = config.ROOT / "competitor-data"
RAW_DIR = DATA_DIR / "raw"              # one folder per downloaded source: body.<ext> + meta.json (git-ignored)
TEXT_DIR = DATA_DIR / "text"            # normalised text of each source, what evidence quotes are checked against (git-ignored)
EXTRACTED_DIR = DATA_DIR / "extracted"  # the value rows the research produced, one JSONL file per batch (tracked)

MARKETS = ["EU", "US", "CN", "RoW"]
MARKET_NAMES = {"EU": "Europe", "US": "United States", "CN": "China", "RoW": "Rest of world"}

# Prices are compared inside one market, one country, one currency and one tax basis. Europe uses Germany so the
# competitors line up with BMW's own DE price list; the rest of the world is represented by Australia.
REFERENCE = {
    "EU": {"country": "DE", "country_name": "Germany", "currency": "EUR"},
    "US": {"country": "US", "country_name": "United States", "currency": "USD"},
    "CN": {"country": "CN", "country_name": "China", "currency": "CNY"},
    "RoW": {"country": "AU", "country_name": "Australia", "currency": "AUD"},
}
CURRENCY_SYMBOL = {"EUR": "EUR", "USD": "USD", "CNY": "CNY", "AUD": "AUD"}

# BMW series -> competitor segment, and the BMW "self" model id used for web rows about BMW (prices outside
# Germany, same-source sales and reviews). In Germany BMW's own price list is used instead of web prices.
SEGMENTS = {
    "compact_premium": "Premium compact (C segment)",
    "compact": "Compact, mainstream brands (C segment)",
    "executive": "Executive / upper-medium (E segment)",
    "large": "Large / upper-medium, mainstream brands (D/E segment)",
    "luxury": "Luxury / full-size (F segment)",
    "midsize_premium": "Premium mid-size (D segment; 3 Series class, not compared here)",
    "suv": "SUVs and crossovers (not compared with these hatchbacks and saloons)",
}
# A model competes in a premium segment only if its brand is positioned as premium; otherwise it moves to the
# mainstream segment of its size class (and can enter a BMW's set only as a publisher-named rival).
PREMIUM_BRANDS = {"audi", "mercedes-benz", "mercedes-maybach", "mercedes-amg", "bmw", "lexus", "genesis", "cadillac",
                  "volvo", "polestar", "porsche", "tesla", "lucid", "jaguar", "maserati", "ds automobiles", "alfa romeo",
                  "lotus", "bentley", "rolls-royce", "aston martin", "lincoln", "infiniti", "acura", "nio", "zeekr",
                  "hongqi", "maextro", "yangwang", "denza", "avatr", "luxeed", "stelato", "im motors", "voyah", "aito",
                  "li auto", "lynk & co"}
MAINSTREAM_OF = {"compact_premium": "compact", "executive": "large", "luxury": "large"}
SERIES_SEGMENT = {"F70": "compact_premium", "G60": "executive", "G70": "luxury"}
# Where a market has fewer than five same-segment models with a sales figure, the set is filled with models that
# publishers name as rivals of the BMW, from these segments only (and flagged as such).
FALLBACK_SEGMENTS = {"F70": ["compact_premium", "compact"], "G60": ["executive", "luxury", "large"],
                     "G70": ["luxury", "executive"]}
BMW_SELF = {"F70": "bmw-1-series", "G60": "bmw-5-series", "G70": "bmw-7-series"}
SELF_SERIES = {v: k for k, v in BMW_SELF.items()}
# BMW model ids some sources list separately; added to the series figure when the same source table has both rows
BMW_TWINS = {"bmw-5-series": ["bmw-i5"], "bmw-7-series": ["bmw-i7"], "bmw-1-series": []}
BMW_GROUP_BRANDS = {"bmw", "bmw m", "bmw i", "mini", "rolls-royce", "alpina"}    # never a competitor of a BMW
N_COMPETITORS = 5
MIN_SHARE_OF_BMW = 0.02     # a rival ranked by sales must sell at least 2% of the BMW's units in the same table

TABLES = ["model", "sales", "price", "spec", "equipment", "review", "rating", "rival"]
POWERTRAINS = ["ICE", "MHEV", "HEV", "PHEV", "BEV", "EREV"]
SALES_BASIS = ["registrations", "deliveries", "retail", "wholesale", "insurance_registrations", "sales"]
SOURCE_TIERS = ["official", "manufacturer", "aggregator", "press"]
TIER_RANK = {t: i for i, t in enumerate(SOURCE_TIERS)}      # lower = more authoritative
PRICE_TYPES = ["list_price", "msrp", "guide_price", "drive_away"]
REVIEW_KINDS = ["owner_review", "expert_pro", "expert_con", "expert_verdict"]
RATING_KINDS = ["owner_average", "expert_score"]
EQUIPMENT_STATUS = ["standard", "optional", "package", "not_available"]

# Spec attribute -> (unit, label). Only these may be recorded, always in this unit.
SPEC_ATTRIBUTES = {
    "power_kw": ("kW", "Power"),
    "torque_nm": ("Nm", "Torque"),
    "accel_0_100_s": ("s", "0-100 km/h"),
    "top_speed_kmh": ("km/h", "Top speed"),
    "length_mm": ("mm", "Length"),
    "width_mm": ("mm", "Width"),
    "wheelbase_mm": ("mm", "Wheelbase"),
    "boot_l": ("l", "Boot volume"),
    "range_km_wltp": ("km", "Electric range (WLTP)"),
    "battery_kwh_net": ("kWh", "Battery (net)"),
    "dc_charge_kw": ("kW", "Max. DC charging"),
}

# Concrete equipment items compared in the German market, each tied to a feature of the feedback taxonomy.
# `bmw` is a regular expression on BMW's own DE price-list item names (catalog_option_items.csv); the BMW side
# of every comparison comes from that price list, never from the web.
EQUIPMENT_ITEMS = {
    "hud": {"label": "Head-up display", "feature": "Head-Up Display", "bmw": r"Head-Up"},
    "acc": {"label": "Adaptive cruise control with stop & go", "feature": "(Active) cruise control",
            "bmw": r"Driving Assistant Plus|Aktive Geschwindigkeitsregelung"},
    "hands_off": {"label": "Hands-off motorway assistant", "feature": "Highway assistant",
                  "bmw": r"Driving Assistant Professional"},
    "pano_roof": {"label": "Panoramic glass roof", "feature": "Panorama glass roof", "bmw": r"Panorama"},
    "massage": {"label": "Front seat massage", "feature": "Seat massage", "bmw": r"Massage"},
    "ventilated_seats": {"label": "Ventilated front seats", "feature": "Seating, ventilate / heat",
                         "bmw": r"Sitzbelüftung|Aktivsitzbelüftung"},
    "heated_wheel": {"label": "Heated steering wheel", "feature": "Heated steering wheel", "bmw": r"Lenkradheizung"},
    "surround_view": {"label": "360-degree camera", "feature": "Surround View",
                      "bmw": r"Parking Assistant Plus|Surround View"},
    "auto_parking": {"label": "Automated parking assistant", "feature": "Parking Assistant",
                     "bmw": r"Parking Assistant(?! Plus)|Parking Assistant Professional"},
    "wireless_charging": {"label": "Wireless phone charging", "feature": "Mobile device, wireless charging",
                          "bmw": r"[Kk]abellos|Smartphone Ablage|induktiv"},
    "premium_audio": {"label": "Premium branded sound system", "feature": "Audio mode, sound",
                      "bmw": r"Harman|Bowers"},
    "ambient_light": {"label": "Ambient lighting", "feature": "Ambient light", "bmw": r"Ambiente"},
    "keyless": {"label": "Keyless entry (comfort access)", "feature": "Comfort Access", "bmw": r"Komfortzugang"},
    "power_tailgate": {"label": "Power tailgate / boot lid", "feature": "Trunk lid, open / close",
                       "bmw": r"Heckklappe"},
    "soft_close": {"label": "Soft-close doors", "feature": "Door, open / close", "bmw": r"Soft-Close"},
    "auto_doors": {"label": "Power-opening doors", "feature": "Automatic doors", "bmw": r"Automatische Türen|Komforttür"},
    "rear_entertainment": {"label": "Rear-seat entertainment screens", "feature": "Rear seat entertainment",
                           "bmw": r"Theatre|Rear-Seat|Fond-Entertainment"},
    "air_suspension": {"label": "Air suspension", "feature": "Cushioning / damping vehicle", "bmw": r"Luftfeder"},
    "rear_steering": {"label": "Rear-axle steering", "feature": "Steering", "bmw": r"Integral-Aktivlenkung"},
    "matrix_lights": {"label": "Adaptive matrix LED / laser headlights", "feature": "Exterior lighting",
                      "bmw": r"Adaptive LED|Matrix|Laserlicht|Iconic Glow"},
    "dashcam": {"label": "Built-in dashcam (drive recorder)", "feature": "Drive Recorder", "bmw": r"Drive Recorder"},
    "digital_key": {"label": "Smartphone digital key", "feature": "Digital Key", "bmw": r"Digital Key"},
}
FEATURE_ITEMS: dict[str, list[str]] = {}
for _key, _item in EQUIPMENT_ITEMS.items():
    FEATURE_ITEMS.setdefault(_item["feature"], []).append(_key)

# English glosses for segment labels printed in other languages (shown next to the original)
SEGMENT_GLOSS = {
    "中大型车": "mid-large cars", "豪华中大型车": "luxury mid-large cars", "豪华大型轿车": "luxury large sedans",
    "70万元以上超豪华轿车": "ultra-luxury sedans above CNY 700,000", "车型销量排行榜 (all models)": "all-model sales ranking",
    "KBA segment Kompaktklasse": "German official segment: compact class",
    "KBA segment Mittelklasse": "German official segment: mid-size class",
    "KBA segment Obere Mittelklasse": "German official segment: upper mid-size class",
    "KBA segment Oberklasse": "German official segment: luxury class",
}


def segment_text(label) -> str | None:
    """'中大型车 (mid-large cars)': the source's label with an English gloss where one is needed."""
    if not isinstance(label, str) or not label:
        return None
    gloss = SEGMENT_GLOSS.get(label)
    return f"{label} ({gloss})" if gloss else label


def segment_english(label) -> str | None:
    """The English gloss alone where the label is not in Latin script (for the PDF, which prints WinAnsi only)."""
    if not isinstance(label, str) or not label:
        return None
    return SEGMENT_GLOSS.get(label, label) if any(ord(ch) > 0x24F for ch in label) else label


MODEL_ID_RE = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
