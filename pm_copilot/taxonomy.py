"""Domain knowledge used to turn raw feedback into structured, comparable signals:

* signal mapping   - Feedback Type / VFC level 3  ->  praise | defect | usability | request
* domain mapping   - VFC level 2 (component)      ->  customer-facing domain
* survey links     - component                    ->  customer-study attributes
* feature catalog  - what a PM types              ->  components + text cues + equipment terms
* lexicons         - materials, competitors, previous-BMW references
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Signal mapping
# --------------------------------------------------------------------------
_REQUEST_ISSUES = {
    "vehicle equipment: not available", "too few", "vehicle equipment: not standard / too costly",
    "permanent switch-off not possible",
}
_COMPLAINT_ISSUES_UNDER_WANTS = {"workmanship does not appeal"}
PRICING_ISSUES = {"like: price-performance ratio", "dislike: price-performance ratio"}


def signal_of(feedback_type: str, issue: str) -> str:
    """Map a classified finding to one of praise / defect / usability / request / none."""
    ft = (feedback_type or "").strip().lower()
    iss = (issue or "").strip().lower()
    if iss in _COMPLAINT_ISSUES_UNDER_WANTS or iss == "dislike: price-performance ratio":
        return "usability"
    if iss.startswith("customer request") or iss in _REQUEST_ISSUES:
        return "request"
    if ft == "likes" or iss.startswith("like") or iss.endswith("appeals"):
        return "praise"
    if ft == "wants":
        return "request"
    if ft == "defect":
        return "defect"
    if ft == "difficult to use" or iss == "not user-friendly":
        return "usability"
    return "none"


COMPLAINT_SIGNALS = ("defect", "usability")

# Source D answers "the one thing I love most / could be most improved about the
# <aspect> of my vehicle" carry no VFC label; map the aspect onto a component.
SOURCE_D_ASPECTS = {
    "driving feel": "Drive, driving dynamics and chassis, overall technology",
    "driving comfort": "Handling / Riding",
    "interior": "Interior design",
    "engine/motor": "Drivetrain",
    "exterior styling": "Exterior design",
    "infotainment system": "ConnectedDrive and Infotainment, overall technology",
    "getting in/out": "Vehicle, access and exit",
    "setting up and starting": "Start engine/switch on drive readiness",
}
_SOURCE_D_RE = re.compile(
    r"one thing (?:do you |i )?(love most|could be most improved) about (?:the )?(.+?)(?: (?:of|in) my vehicle| my vehicle| each time|\.|$)",
    re.I)
_EMPTY_ANSWER = re.compile(r"^\s*(nothing|nothng|none|n/?a|no|everything)\W", re.I)


def classify_source_d(text: str) -> tuple[str, str] | None:
    """Return (signal, component) for a Source D answer, or None if it says nothing."""
    m = _SOURCE_D_RE.search(text or "")
    if not m or _EMPTY_ANSWER.match(text or ""):
        return None
    aspect = m.group(2).strip().lower()
    component = next((c for key, c in SOURCE_D_ASPECTS.items() if aspect.startswith(key)), None)
    if component is None:
        return None
    return ("praise" if m.group(1).lower() == "love most" else "request"), component


_SEVERITY_RE = re.compile(r"I had an? (very serious|serious|very minor|minor)? ?problem", re.I)


def severity_of(text: str) -> str:
    m = _SEVERITY_RE.search(text or "")
    return (m.group(1) or "").lower() if m else ""


# --------------------------------------------------------------------------
# Domains (first matching rule wins)
# --------------------------------------------------------------------------
DOMAIN_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Infotainment & Connectivity", ("mobile device",)),  # phone charging, not HV charging
    ("Charging & Range", ("charg", "electric range", "high voltage", "high-voltage", "wallbox",
                          "recuperation", "preconditioning", "vehicle battery", "fuel tank",
                          "fuel filler")),
    ("Access & Doors", ("key", "lock / unlock", "comfort access", "door", "trunk lid", "hood",
                        "access and exit", "child safety latch", "anti-theft", "side window",
                        "garage door", "grab handle", "running board", "towing eye")),
    ("Driver assistance & Parking", ("assist", "cruise control", "lane", "parking", "park distance",
                                     "surround view", "all-round view", "side view", "camera",
                                     "collision", "blind spot", "warning", "night vision", "fatigue",
                                     "automated driving", "drive recorder", "high-beam",
                                     "traffic light", "back-up", "dynamic stability", "vehicle safety",
                                     "impression of safety", "airbags", "seat belts", "emergency stop")),
    ("Infotainment & Connectivity", ("infotainment", "touch screen", "operating concept", "navigation",
                                     "carplay", "android auto", "app", "audio", "radio", "connecteddrive",
                                     "connected drive", "esim", "wifi", "wi-fi", "bluetooth",
                                     "mobile device", "usb", "voice", "personal assistant", "head-up",
                                     "instrument cluster", "display", "controller", "gesture",
                                     "touch command", "rear seat entertainment", "video", "cd / dvd",
                                     "screen mirroring", "map update", "software", "rtti",
                                     "traffic information", "traffic camera", "teleservices", "portal",
                                     "online", "telephone", "driver profile", "smart poi",
                                     "emergency request", "caring car", "customer account",
                                     "upgrades", "multi-function steering wheel")),
    ("Seats", ("seat", "headrest", "lumbar", "child restraint")),
    ("Climate & Comfort", ("climatization", "air conditioning", "blower", "heater", "heating",
                           "heated", "sun protection", "sun visor", "panorama", "roof", "cooling",
                           "interior comfort", "interior acoustics", "ambient light",
                           "interior, lighting", "welcome light")),
    ("Space & Storage", ("space", "luggage", "storage", "cupholder", "glove box", "frunk",
                         "through-loading", "trunk", "center console", "armrest", "12 v",
                         "floor mat", "trailer")),
    ("Exterior", ("exterior", "wheels", "tire", "tirefit", "grille", "bumper", "side sill",
                  "mirror", "windshield", "wiper", "lighting", "fog light", "flashing", "horns",
                  "ground clearance", "outer door handle", "convertible", "wash", "rain sensor",
                  "light switch")),
    ("Driving & Powertrain", ("drive", "driving", "drivetrain", "handling", "riding", "braking",
                              "brake", "steering", "transmission", "engine", "suspension",
                              "cushioning", "damping", "selector lever", "shift paddle", "modes",
                              "launch control", "pedals", "exhaust", "automatic-hold", "starting")),
    ("Interior", ("interior", "instrument panel", "upholstery", "finisher panel", "display, time")),
    ("Build quality", ("body equipment", "workmanship")),
]


def domain_of(component: str) -> str:
    c = (component or "").lower()
    for domain, keys in DOMAIN_RULES:
        if any(k in c for k in keys):
            return domain
    return "Ownership & Other"


# Rough effort / feasibility proxy per domain (0 = hard, 1 = easy). Used only as
# one weighted factor; the brief allows cost/effort as a rough prioritization input.
DOMAIN_FEASIBILITY = {
    "Infotainment & Connectivity": 0.80,  # largely software, OTA-deliverable
    "Climate & Comfort": 0.60, "Seats": 0.55, "Interior": 0.60, "Access & Doors": 0.60,
    "Driver assistance & Parking": 0.55, "Exterior": 0.50, "Driving & Powertrain": 0.40,
    "Charging & Range": 0.35, "Space & Storage": 0.30,  # packaging-bound
    "Build quality": 0.50,
    "Ownership & Other": 0.60,
}

OUT_OF_SCOPE_COMPONENTS = {
    "no_class_found": "unclassified",
    "General enquiry: customer feedback": "not a product attribute",
    "Accessories / Parts": "aftersales topic",
    "Engine oil": "service / engineering topic",
    "Airbags": "regulatory safety topic",
}

# --------------------------------------------------------------------------
# Survey links: component keyword -> attribute prefixes (CN/EU study, US study)
# --------------------------------------------------------------------------
SURVEY_LINKS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("seat massage", "seating, ventilate", "seats", "seat memory", "headrest", "lumbar"),
     ("Overall seating comfort", "Overall comfort of the seats", "Comfort of front seat",
      "Driver seat adjustability")),
    (("heated steering wheel", "climatization", "air conditioning", "blower", "heater", "panel heating",
      "heated rear window", "cooling"),
     ("Heating/ ventilation", "Overall performance of climate control", "Heater performance",
      "Air conditioner performance", "Operation of heater/ AC controls")),
    (("touch screen", "operating concept", "controller", "touch command", "gesture",
      "multi-function steering wheel", "instrument panel", "instrument cluster"),
     ("Easy to read and use instruments", "Easy to use information and entertainment",
      "Menu structure of infotainment", "Intuitiveness of controls",
      "Ease of reading and using screen interface", "Placement/ ease of reading")),
    (("connecteddrive and infotainment", "rear seat entertainment", "video", "radio", "apps (in-car)"),
     ("Features of information and entertainment", "Overall driver-vehicle interaction")),
    (("apple carplay", "android auto", "screen mirroring", "bluetooth", "mobile device", "usb port"),
     ("Smartphone integration", "Mirroring of smartphone content", "Bluetooth/ smartphone pairing",
      "Phone charging", "Place for phone")),
    (("navigation", "map update", "rtti", "smart poi", "traffic camera"),
     ("Integrated navigation system", "If applicable: Navigation system")),
    (("voice control", "intelligent personal assistant"), ("Performance of voice recognition",)),
    (("my bmw app", "remote", "connecteddrive services", "esim", "wifi", "teleservices", "upgrades",
      "digital key"),
     ("Connected services", "Vehicle's Mobile App", "WiFi hotspot in vehicle")),
    (("head-up",), ("Head-up Display", "Easy to read and use instruments")),
    (("audio mode", "sound"), ("Overall performance of sound system", "Audio clarity", "Bass performance")),
    (("interior acoustics", "wind noise"),
     ("Quietness when driving", "Overall noise/vibration/harshness", "Freedom from wind and road noise")),
    (("exterior design", "exterior", "radiator grille", "bumper", "exterior lighting"),
     ("Exterior styling", "Overall exterior styling", "Headlight/ taillight design", "Size/ proportions")),
    (("wheels",), ("Appearance of tires/ wheels",)),
    (("interior design", "upholstery", "finisher panel", "interior"),
     ("Interior styling", "Quality of interior and materials", "Overall interior styling",
      "Quality of interior materials", "Interior trim and finish")),
    (("ambient light", "interior, lighting", "welcome light"), ("Interior lighting", "Interior styling")),
    (("space / spatial",), ("Rear interior roominess", "Front interior roominess", "Interior roominess",
                            "2nd row seat roominess")),
    (("luggage", "trunk", "frunk", "through-loading"),
     ("Luggage capacity", "Ease of loading", "Cargo capacity", "Trunk lid/ tailgate")),
    (("storage", "cupholder", "glove box", "center console", "armrest"),
     ("Interior storage", "Cupholders", "Interior versatility")),
    (("handling", "cushioning", "self-leveling"), ("Quality of ride", "Riding comfort", "Roadholding")),
    (("drive, driving dynamics", "steering", "dynamic stability", "launch control", "my modes"),
     ("Roadholding", "Sportiness", "Handling/Maneuverability", "Overall driving performance",
      "Manoeuvrability")),
    (("drivetrain", "transmission", "engine", "start-stop", "starting", "selector lever", "shift paddle"),
     ("Acceleration", "Overall power and pickup", "Smoothness of transmission",
      "Fuel economy/ energy efficiency")),
    (("electric range", "high voltage battery", "charg", "wallbox", "recuperation"),
     ("Fuel economy/ energy efficiency", "Gas or electric mileage", "Environm. friendliness")),
    (("braking", "automatic-hold", "parking brake"), ("Braking",)),
    (("cruise control", "highway assistant", "steering and lane", "lane", "driver assistance",
      "speed limit", "traffic jam", "collision", "blind spot", "fatigue"),
     ("Adaptive driving assists", "Overall driver assist features", "Safety monitoring features", "Safety")),
    (("parking", "park distance", "surround view", "all-round view", "rear view camera", "side view",
      "back-up"),
     ("If applicable: Backup system", "All round visibility", "Rear visibility")),
    (("mirror", "windshield", "wiper"), ("All round visibility", "Front visibility", "Rear visibility")),
    (("door", "access and exit", "comfort access", "vehicle key", "lock / unlock", "automatic doors"),
     ("Ease of entry into and out of car", "Ease of front seat entry", "Exterior door handles",
      "Interior door handles")),
    (("panorama", "roof", "sun protection"), ("If applicable: Sunroof",)),
    (("body equipment, overall", "workmanship"),
     ("Overall build quality", "Freedom from faults", "Solid vehicle construction",
      "Overall interior workmanship")),
]


def survey_prefixes_for(component: str) -> list[str]:
    c = (component or "").lower()
    out: list[str] = []
    for keys, prefixes in SURVEY_LINKS:
        if any(k in c for k in keys):
            out.extend(p for p in prefixes if p not in out)
    return out


# --------------------------------------------------------------------------
# Feature catalog: what a PM types -> what to look for in the data
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    synonyms: tuple[str, ...]          # free-text cues searched in verbatims
    components: tuple[str, ...] = ()   # VFC level-2 components (labelled evidence)
    equipment_terms: tuple[str, ...] = ()  # German price-list terms
    survey: tuple[str, ...] = ()       # survey attribute prefixes
    material_relevant: bool = False
    climate: str | None = None         # 'cold' | 'hot' | 'both' -> context hint only
    component_text_filter: str | None = None  # narrows a shared component to this feature
    extra: dict = field(default_factory=dict)


FEATURES: list[Feature] = [
    Feature("heated_steering_wheel", "Heated steering wheel",
            ("heated steering wheel", "steering wheel heat", "heated wheel", "wheel heating"),
            ("Heated steering wheel",), ("Lenkradheizung",),
            ("Heating/ ventilation", "Heater performance"), True, "cold"),
    Feature("seat_ventilation", "Seat ventilation (cooled seats)",
            ("ventilated seat", "seat ventilation", "cooled seat", "cooling seat", "seat cooling",
             "air conditioned seat", "seat fan"),
            ("Seating, ventilate / heat",), ("Sitzbelüftung", "Comfort Paket"),
            ("Overall seating comfort", "Overall comfort of the seats", "Heating/ ventilation"),
            True, "hot", r"ventilat|cool|fan|cold air"),
    Feature("seat_heating", "Seat heating",
            ("heated seat", "seat heating", "seat heater", "seat warmer"),
            ("Seating, ventilate / heat",), ("Sitzheizung", "Comfort Paket"),
            ("Overall seating comfort", "Overall comfort of the seats", "Heater performance"),
            True, "cold", r"heat|warm"),
    Feature("seat_massage", "Seat massage", ("massage",), ("Seat massage",), ("Massage",),
            ("Overall seating comfort", "Overall comfort of the seats")),
    Feature("seat_comfort", "Seat comfort & adjustability",
            ("seat comfort", "comfortable seat", "uncomfortable seat", "lumbar", "headrest", "seat memory",
             "thigh support", "bolster"),
            ("Seats", "Adjustment of lower lumbar support", "Headrest, adjust", "Seat memory", "Headrests, rear"),
            ("Komfortsitz", "Sportsitz", "Sitzverstellung"),
            ("Overall seating comfort", "Overall comfort of the seats", "Comfort of front seat",
             "Comfort of 2nd row seat", "Driver seat adjustability", "Driving position"), True),
    Feature("panorama_roof", "Panoramic glass roof",
            ("panorama", "panoramic roof", "sunroof", "moonroof", "glass roof", "sky lounge"),
            ("Panorama glass roof", "Roof", "Roof function centre"), ("Panorama Glasdach", "Sky Lounge"),
            ("If applicable: Sunroof",), False, "both"),
    Feature("hud", "Head-Up Display", ("head-up", "head up display", "hud", "heads up"),
            ("Head-Up Display",), ("Head-Up Display",), ("Head-up Display", "Easy to read and use instruments")),
    Feature("wireless_charging", "Wireless phone charging",
            ("wireless charg", "phone charg", "charging pad", "phone overheat", "phone gets hot"),
            ("Mobile device, wireless charging",), ("Wireless Charging",),
            ("Phone charging", "Place for phone", "Smartphone integration")),
    Feature("carplay", "Apple CarPlay / Android Auto",
            ("carplay", "car play", "android auto", "phone mirroring", "screen mirroring"),
            ("Apple CarPlay", "Android Auto", "Screen mirroring", "Manage / pair mobile device (Bluetooth)"),
            ("Smartphone Integration",),
            ("Mirroring of smartphone content", "Smartphone integration", "Bluetooth/ smartphone pairing")),
    Feature("controls", "Touchscreen, menus & physical controls",
            ("touchscreen", "touch screen", "idrive", "too many menus", "menus", "physical button",
             "buttons", "knob", "physical controls", "haptic", "capacitive"),
            ("Touch screen, operation", "Operating concept, operating system", "Controller operation",
             "Touch Command", "Gesture control", "Multi-function steering wheel operation",
             "Air conditioning control panel"),
            ("BMW Operating System", "Curved Display", "Controller", "Interaction Bar"),
            ("Easy to use information and entertainment", "Menu structure of infotainment",
             "Intuitiveness of controls", "Ease of reading and using screen interface",
             "Easy to read and use instruments", "Operation of heater/ AC controls")),
    Feature("voice_assistant", "Voice assistant",
            ("voice", "speech", "hey bmw", "personal assistant", "alexa", "voice command"),
            ("Voice control / speech recognition", "Intelligent Personal Assistant",
             "Intelligent Personal Assistant, activation word"),
            ("Intelligent Personal Assistant",), ("Performance of voice recognition",)),
    Feature("navigation", "Navigation & maps",
            ("navigation", "sat nav", "satnav", "maps", "route guidance", "gps"),
            ("Navigation", "Map update", "Real Time Traffic Information (RTTI)", "Smart POI search",
             "Traffic Camera Information"),
            ("Navigation", "BMW Maps"), ("Integrated navigation system", "If applicable: Navigation system")),
    Feature("app", "My BMW App & remote services",
            ("my bmw app", "bmw app", "the app", "remote start", "remote services", "pre-condition",
             "precondition"),
            ("My BMW App / MINI App", "Remote Services & Remote Keyless Entry (My BMW App/MINI App)",
             "Remote Engine Start (My BMW App / MINI App)", "Remote 3D View (My BMW App / MINI App)",
             "Remote interior camera (My BMW App / MINI App)",
             "ConnectedDrive services (smartphone) technology overall"),
            ("Remote Services", "ConnectedDrive"), ("Vehicle's Mobile App", "Connected services")),
    Feature("digital_key", "Digital key & keyless entry",
            ("digital key", "key card", "phone as key", "keyless", "comfort access", "key fob"),
            ("Digital Key", "Vehicle key", "Comfort Access", "Vehicle, lock / unlock", "Display key"),
            ("Komfortzugang", "Digital Key"), ("Connected services", "Ease of entry into and out of car")),
    Feature("sound_system", "Sound system",
            ("sound system", "speakers", "bowers", "harman", "b&w", "stereo", "bass", "audio quality"),
            ("Audio mode, sound", "Radio function"), ("Bowers & Wilkins", "harman/kardon", "HiFi"),
            ("Overall performance of sound system", "Audio clarity", "Bass performance",
             "Design and integration of speakers")),
    Feature("ambient_light", "Ambient lighting",
            ("ambient light", "ambient lighting", "interior lighting", "welcome light", "light bar"),
            ("Ambient light", "Vehicle interior, lighting", "Welcome Light Carpet"),
            ("Ambientes Licht", "Interaction Bar"), ("Interior lighting", "Interior styling")),
    Feature("rear_seat_entertainment", "Rear-seat entertainment / Theatre Screen",
            ("rear seat entertainment", "theater screen", "theatre screen", "rear screen",
             "rear entertainment", "back seat screen"),
            ("Rear seat entertainment", "Video: playback / streaming"),
            ("Theatre Screen", "Fond", "Rear-Seat"), ("Features of information and entertainment",)),
    Feature("automatic_doors", "Automatic doors & soft close",
            ("automatic door", "doors open", "door opens", "soft close", "door closer", "power door"),
            ("Automatic doors", "Door, open / close", "Resting state after door opening"),
            ("Automatische Türen", "Soft-Close", "Türen"), ("Ease of entry into and out of car",)),
    Feature("driving_assistant", "Driving assistant & cruise control",
            ("cruise control", "adaptive cruise", "lane keep", "lane keeping", "highway assist",
             "autopilot", "self driving", "self-driving", "hands-free", "hands free", "lane change"),
            ("(Active) cruise control", "Highway assistant", "Steering and lane guide assist",
             "Driver assistance, automated driving, overall technology", "Lane departure warning",
             "Lane Change Assistant", "Speed Limit Assistant", "Traffic Jam Assistant"),
            ("Driving Assistant", "Autobahnassistent"),
            ("Adaptive driving assists", "Overall driver assist features", "Safety monitoring features")),
    Feature("parking_assistant", "Parking assistant & cameras",
            ("parking", "park assist", "surround view", "360", "parking sensor", "reverse camera",
             "backup camera", "rear camera", "self park"),
            ("Parking Assistant", "Park Distance Control (PDC)", "Surround View", "All-round view",
             "Rear view camera", "Remote controlled parking", "Back-up Assistant", "Side View"),
            ("Parking Assistant",), ("If applicable: Backup system", "Rear visibility")),
    Feature("start_stop", "Auto start-stop",
            ("start-stop", "start stop", "auto stop", "auto start", "engine stops"),
            ("Automatic engine start-stop function (MSA)",), (), ("Overall power and pickup",)),
    Feature("range", "Electric range",
            ("range", "miles per charge", "range anxiety", "km of range"),
            ("Electric Range", "High voltage battery"), (),
            ("Fuel economy/ energy efficiency", "Gas or electric mileage")),
    Feature("charging", "Charging speed & experience",
            ("charging", "charger", "charge time", "fast charg", "supercharger", "public charg",
             "home charg", "wallbox", "charging port"),
            ("Charge high-voltage battery", "Public charging / external providers",
             "Wallbox, charging / home charging", "Charging cable", "Opening/closing charging socket cover",
             "High voltage battery, preconditioning", "High-voltage charging power socket",
             "Bidirectional charging", "Route optimized for charging"),
            ("AC-Laden", "Ladekabel"), ("Fuel economy/ energy efficiency",)),
    Feature("luggage", "Luggage / trunk space",
            ("trunk", "boot space", "luggage", "cargo", "frunk", "golf bag", "suitcase"),
            ("Luggage compartment", "Trunk lid, open / close", "Trunk lid", "non-contact trunk lid opening",
             "Frunk", "Through-loading facility", "Trunk light"),
            ("Gepäckraum", "Heckklappe", "Durchlade"),
            ("Luggage capacity", "Ease of loading", "Cargo capacity", "Trunk lid/ tailgate")),
    Feature("storage", "Interior storage & cupholders",
            ("storage", "cupholder", "cup holder", "glove box", "sunglass", "cubby", "compartment",
             "door pocket", "place for phone"),
            ("Storage compartments", "Cupholder", "Glove box", "Center console, front", "Center armrest, front"),
            ("Ablage",), ("Interior storage", "Cupholders", "Interior versatility")),
    Feature("rear_space", "Rear legroom & interior space",
            ("rear seat", "back seat", "legroom", "leg room", "headroom", "rear space", "cramped",
             "roomy", "spacious"),
            ("Space / spatial impression",), (),
            ("Rear interior roominess", "2nd row seat roominess", "Interior roominess",
             "Front interior roominess")),
    Feature("interior_materials", "Interior materials & premium feel",
            ("material", "leather", "plastic", "wood", "trim", "alcantara", "veganza", "piano black",
             "premium feel", "cheap", "quality feel", "upholstery"),
            ("Interior design", "Upholstery / interior trim", "Interior", "Door, finisher panel, front",
             "Instrument panel"),
            ("Polster", "Leder", "Interieurleisten", "Veganza", "Alcantara"),
            ("Quality of interior and materials", "Quality of interior materials", "Quality of seat materials",
             "Interior trim and finish", "Overall interior workmanship"), True),
    Feature("exterior_design", "Exterior design & grille",
            ("grille", "kidney", "styling", "looks", "headlight", "exterior color", "paint", "design"),
            ("Exterior design", "Exterior", "Radiator grille", "Exterior lighting", "Bumper, front",
             "Bumper, rear"),
            ("Lackierung", "Iconic Glow", "Shadow Line"),
            ("Exterior styling", "Overall exterior styling", "Headlight/ taillight design", "Size/ proportions")),
    Feature("wheels", "Wheels & tyres",
            ("wheels", "rims", "tyres", "tires", "run flat", "run-flat", "flat tire", "spare tire"),
            ("Wheels / tires", "RSC tire", "Tirefit", "Tire pressure control"), ("Leichtmetallräder",),
            ("Appearance of tires/ wheels", "If applicable: Flat tire")),
    Feature("ride_comfort", "Ride comfort & suspension",
            ("ride quality", "suspension", "bumpy", "harsh ride", "comfortable ride", "air suspension",
             "smooth ride"),
            ("Handling / Riding", "Cushioning / damping vehicle", "Self-leveling suspension"),
            ("Fahrwerk", "Luftfederung"), ("Quality of ride", "Riding comfort")),
    Feature("driving_dynamics", "Driving dynamics & handling",
            ("handling", "sporty", "cornering", "steering feel", "agile", "fun to drive", "joy to drive"),
            ("Drive, driving dynamics and chassis, overall technology", "Steering", "Dynamic Stability Control",
             "Launch Control", "My Modes / driving experience"),
            ("Fahrwerk", "Integral-Aktivlenkung"),
            ("Roadholding", "Sportiness", "Handling/Maneuverability", "Overall driving performance")),
    Feature("performance", "Powertrain performance & efficiency",
            ("acceleration", "horsepower", "engine", "fuel economy", "mpg", "efficiency", "hybrid", "diesel"),
            ("Drivetrain", "Transmission", "Engine acoustics / engine sound", "Starting engine"), (),
            ("Acceleration", "Overall power and pickup", "Fuel economy/ energy efficiency",
             "Smoothness of transmission")),
    Feature("noise", "Cabin quietness (NVH)",
            ("noise", "quiet", "wind noise", "road noise", "rattle", "squeak"),
            ("Interior acoustics",), ("Akustikverglasung",),
            ("Quietness when driving", "Overall noise/vibration/harshness", "Freedom from wind and road noise",
             "Freedom from squeaks and rattles")),
    Feature("climate", "Climate control",
            ("air conditioning", "a/c", "climate control", "heater", "blower", "hvac", "defrost",
             "air vents"),
            ("Vehicle, climatization", "Air conditioning, setting", "Blower function",
             "Air conditioning control panel", "Air conditioning, overall technology",
             "Auxiliary heater function", "Panel heating", "Heated rear window", "Cooling"),
            ("Klimaautomatik", "Standheizung"),
            ("Heating/ ventilation", "Overall performance of climate control", "Heater performance",
             "Air conditioner performance", "Operation of heater/ AC controls"), False, "both"),
    Feature("sun_protection", "Sun protection blinds",
            ("sunshade", "sun shade", "sun blind", "roller blind", "sun visor", "privacy glass"),
            ("Sun protection", "Sun visor, front"), ("Sonnenschutz",), ("If applicable: Sunroof",),
            False, "hot"),
    Feature("usb_power", "USB ports & power outlets",
            ("usb", "usb-c", "12v", "power outlet"), ("USB port", "12 V connection"), ("USB",),
            ("Phone charging",)),
    Feature("owners_manual", "Owner's manual & onboarding",
            ("manual", "user manual", "owner's manual", "tutorial", "instructions"),
            ("Owner's Manual", "Driver's Guide App"), (), ()),
    Feature("ota", "Software updates (OTA)",
            ("software update", "over the air", "ota", "remote software upgrade", "upgrade"),
            ("Remote Software Upgrade/RSU", "BMW ConnectedDrive upgrades/ MINI CONNECTED upgrades"),
            ("Remote Software Upgrade",), ("Connected services",)),
    Feature("drive_recorder", "Drive recorder / dashcam",
            ("dashcam", "dash cam", "drive recorder"), ("Drive Recorder", "Interior camera"),
            ("Drive Recorder", "Innenraumkamera"), ()),
    Feature("visibility", "Visibility & mirrors",
            ("visibility", "blind spot", "mirror", "sightline"),
            ("Exterior rearview mirror", "Interior rearview mirror", "Blind spot monitoring", "Windshield"),
            ("Spiegel",), ("All round visibility", "Front visibility", "Rear visibility")),
    Feature("connectivity", "In-car Wi-Fi & eSIM",
            ("wifi", "wi-fi", "hotspot", "esim", "e-sim", "connectivity"),
            ("WiFi hotspot", "Personal eSIM", "Wi-Fi connection"), ("Personal eSIM", "WiFi"),
            ("WiFi hotspot in vehicle", "Connected services")),
]
FEATURES_BY_KEY = {f.key: f for f in FEATURES}

CLIMATE_HINTS = {
    "cold": "Context assumption: relevance usually rises in cold-winter markets (Nordics, Canada, "
            "Northern China, Korea). Not derived from BMW data - validate.",
    "hot": "Context assumption: relevance usually rises in hot / humid markets (US Sunbelt, Southern "
           "China, Middle East, Australia). Not derived from BMW data - validate.",
    "both": "Context assumption: relevant in both very hot and very cold markets. Not derived from "
            "BMW data - validate.",
}

# --------------------------------------------------------------------------
# Lexicons
# --------------------------------------------------------------------------
MATERIALS: dict[str, str] = {
    "Leather (Merino / Nappa)": r"\bleather\b(?!ette)|merino|vernasca|nappa",
    "Vegan leather (Veganza / Sensatec)": r"veganza|vegan leather|sensatec|leatherette|synthetic leather|"
                                          r"faux leather|artificial leather",
    "Alcantara / suede": r"alcantara|suede",
    "Wood trim": r"\bwood(?:en)?\b|walnut|\boak\b",
    "Carbon fibre": r"carbon fib|carbon trim|\bcarbon\b(?! emission| footprint| neutral)",
    "Aluminium / metal": r"alumin|brushed metal|metal trim|\bmetal\b(?!lic)",
    "Piano black / high gloss": r"piano black|gloss(?:y)? black|high.gloss|glossy",
    "Hard plastic": r"plastic",
    "Chrome": r"chrome",
    "Fabric / cloth": r"\bfabric|\bcloth\b|textile|\bwool",
    "Crystal / glass applications": r"crystal(?! clear)|craftedclarity|glass (?:knob|gear|selector|trim|controls?|applications?)",
}
MATERIAL_NEG = re.compile(r"cheap|scratch|fingerprint|dust|smudge|wear|worn|crack|peel|flak|hard|"
                          r"too much|squeak|creak|rattle|shiny|tacky|flimsy|disappoint|not premium|"
                          r"feels? (?:cheap|plasticky)|plasticky|stain|fade|hot in", re.I)
MATERIAL_POS = re.compile(r"beautiful|nice|love|premium|quality|soft|great|excellent|gorgeous|luxur|"
                          r"elegant|stunning|well made|solid|high.end|classy|lovely", re.I)

COMPETITORS: dict[str, str] = {
    "Mercedes-Benz": r"mercedes|\bbenz\b|\bmerc\b|\b[aces]-class\b|\bcla\b|\beq[es]\b|\bamg\b|maybach",
    "Audi": r"\baudi\b|\ba[3-8]\b|e-tron|\brs ?[3-7]\b",
    "Tesla": r"tesla|\bmodel [sy3x]\b",
    "Lexus": r"lexus",
    "Genesis": r"\bgenesis\b|\bg[89]0\b",
    "Porsche": r"porsche|taycan|panamera|macan|cayenne",
    "Volvo": r"volvo",
    "Volkswagen": r"\bvw\b|volkswagen|\bgolf (?:\d|gti|r\b|mk)|passat|arteon",
    "Toyota / Honda": r"toyota|camry|prius|honda|accord|civic",
    "Hyundai / Kia": r"hyundai|\bkia\b|ioniq|\bev[69]\b",
    "Lucid": r"\blucid\b",
    "Land Rover": r"range rover|land rover",
    "Cadillac": r"cadillac|lyriq|escalade",
    "Jaguar": r"jaguar",
    "Polestar": r"polestar",
    "Ford": r"\bford\b|mustang",
    # Chinese brands: none appear in the provided verbatims (no China verbatims);
    # kept so web-research results and future data are matched consistently.
    "BYD": r"\bbyd\b", "NIO": r"\bnio\b", "XPeng": r"xpeng", "Li Auto": r"li auto|lixiang",
    "Zeekr": r"zeekr", "Xiaomi": r"xiaomi|\bsu7\b", "Huawei HIMA": r"\baito\b|maextro|luxeed|huawei",
    "Hongqi": r"hongqi",
}
PREVIOUS_BMW = re.compile(
    r"\b(?:my|the|our) (?:old|previous|last|former|prior) (?:bmw|[1-8]\d\d[a-z]?\b|[1-8] series|x\d\b|i\d\b|"
    r"[1-8]er|car had)|previous (?:model|generation|bmw)|older bmw", re.I)
WANT_CUES = re.compile(r"\bwish\b|would like|would love|should (?:have|be|add)|\bmissing\b|\black(?:s|ing)?\b|"
                       r"doesn't have|does not have|no option|not available|please add|need(?:s)? (?:a|an|to)|"
                       r"bring back|why (?:no|not|isn't|doesn't)", re.I)


# --------------------------------------------------------------------------
# Car zones: where on the car a component lives (drives the clickable car map)
# --------------------------------------------------------------------------
ZONES: dict[str, str] = {
    "exterior": "Exterior design", "lights": "Lights & visibility", "wheels": "Wheels & ride comfort",
    "dynamics": "Driving dynamics & brakes", "powertrain": "Powertrain", "charging": "Charging & range",
    "assist": "Driver assistance & parking", "screens": "Screens, controls & navigation",
    "connect": "Phone, app & connectivity", "seats": "Seats", "climate": "Climate & cabin comfort",
    "roof": "Roof & ambient light", "interior": "Interior design & quality", "space": "Space & storage",
    "access": "Doors, keys & access", "ownership": "Manual & ownership",
}
# Component keyword -> zone, checked in order before the domain default.
ZONE_OVERRIDES: list[tuple[str, str]] = [
    ("heated steering wheel", "climate"), ("steering and lane", "assist"), ("multi-function steering", "screens"),
    ("steering wheel", "screens"), ("touch screen", "screens"), ("operating concept", "screens"),
    ("controller operation", "screens"), ("touch command", "screens"), ("gesture", "screens"),
    ("instrument cluster", "screens"), ("head-up", "screens"), ("navigation", "screens"), ("map update", "screens"),
    ("voice control", "screens"), ("intelligent personal assistant", "screens"),
    ("connecteddrive and infotainment", "screens"), ("radio function", "screens"), ("audio mode", "screens"),
    ("rear seat entertainment", "screens"), ("video", "screens"), ("cd / dvd", "screens"), ("smart poi", "screens"),
    ("rtti", "screens"), ("traffic camera", "screens"), ("display, time", "screens"),
    ("exterior lighting", "lights"), ("high-beam", "lights"), ("fog light", "lights"), ("light switch", "lights"),
    ("flashing", "lights"), ("exterior rearview mirror", "lights"), ("interior rearview mirror", "lights"), ("windshield", "lights"), ("wiper", "lights"),
    ("rain sensor", "lights"), ("wash", "lights"), ("night vision", "assist"),
    ("wheels / tires", "wheels"), ("rsc tire", "wheels"), ("tirefit", "wheels"), ("tire pressure", "wheels"),
    ("handling / riding", "wheels"), ("cushioning", "wheels"), ("self-leveling", "wheels"),
    ("ground clearance", "wheels"),
    ("drive, driving dynamics", "dynamics"), ("steering", "dynamics"), ("braking", "dynamics"),
    ("dynamic stability", "dynamics"), ("launch control", "dynamics"), ("automatic-hold", "dynamics"),
    ("parking brake", "dynamics"),
    ("panorama", "roof"), ("roof", "roof"), ("sun protection", "roof"), ("sun visor", "roof"),
    ("ambient light", "roof"), ("interior, lighting", "roof"), ("welcome light", "roof"),
]
DOMAIN_ZONE = {
    "Charging & Range": "charging", "Access & Doors": "access", "Driver assistance & Parking": "assist",
    "Infotainment & Connectivity": "connect", "Seats": "seats", "Climate & Comfort": "climate",
    "Space & Storage": "space", "Exterior": "exterior", "Driving & Powertrain": "powertrain",
    "Interior": "interior", "Build quality": "interior", "Ownership & Other": "ownership",
}


def zone_of(component: str, domain: str | None = None) -> str:
    c = (component or "").lower()
    for key, zone in ZONE_OVERRIDES:
        if key in c:
            return zone
    return DOMAIN_ZONE.get(domain or domain_of(component), "ownership")


FEATURE_ZONE = {f.key: zone_of(f.components[0]) if f.components else "ownership" for f in FEATURES}
