"""Three-level category taxonomy for BMW customer feedback.

Level 1  domain   - 11 product areas a PM owns (hand-curated below)
Level 2  feature  - the VFC level-2 label shipped in the data (226 values)
Level 3  reason   - the VFC level-3 label, grouped into reason families

This mirrors the old Demandra abstraction ladder (E-Class -> +Manufacturer ->
+Feature cluster): verdicts are most robust at the domain level and most
actionable at the feature + reason level.
"""

# --------------------------------------------------------------------------
# Level 1: domain -> VFC level-2 features
# --------------------------------------------------------------------------
DOMAIN_FEATURES = {
    "Drivetrain & Performance": [
        "Drivetrain", "Transmission", "Engine acoustics / engine sound",
        "Automatic engine start-stop function (MSA)", "Launch Control", "Shift paddle",
        "Operate selector lever", "Starting engine", "Start engine/switch on drive readiness",
        "Exhaust system", "Fuel tank", "Fuel filler flap , open / close", "Cooling",
        "Brake Energy Regeneration / recuperation", "Pedals, operate",
    ],
    "Chassis & Driving Dynamics": [
        "Drive, driving dynamics and chassis, overall technology", "Handling / Riding",
        "Cushioning / damping vehicle", "Braking", "Steering", "Wheels / tires", "RSC tire",
        "Tirefit", "Tire pressure control", "Self-leveling suspension", "ground clearance",
        "Dynamic Stability Control", "Dynamic Stability Control (DSC)", "Automatic-hold",
        "Parking brake", "My Modes / driving experience", "Experience Modes",
    ],
    "EV Charging & Range": [
        "Electric Range", "Public charging / external providers", "Charge high-voltage battery",
        "High voltage battery", "Wallbox, charging / home charging",
        "Opening/closing charging socket cover", "Charging cable",
        "High voltage battery, preconditioning", "High-voltage charging power socket",
        "Route optimized for charging", "Bidirectional charging",
    ],
    "Driver Assistance & Safety": [
        "Driver assistance, automated driving, overall technology", "Highway assistant",
        "(Active) cruise control", "Parking Assistant", "Lane departure warning",
        "Rear view camera", "Park Distance Control (PDC)", "Steering and lane guide assist",
        "Surround View", "All-round view", "Speed Limit Assistant", "Back-up Assistant",
        "Blind spot monitoring", "Front collision warning", "Remote controlled parking",
        "Cross Traffic Warning Rear with Brake Intervention", "Fatigue Alert",
        "High-beam assistant", "Lane Change Assistant", "Side View", "Night Vision",
        "Traffic Light And Sign Warning", "Rear-end collision warning", "Traffic Jam Assistant",
        "Emergency Stop Assistant", "Intersection Warning with Brake Intervention",
        "Impression of safety", "Vehicle safety, overall technology", "Seat belts", "Airbags",
        "Emergency request", "Anti-theft alarm system", "Child safety latch",
        "Child restraint seat", "Child restraint seat, use", "Drive Recorder", "Interior camera",
    ],
    "Infotainment & HMI": [
        "ConnectedDrive and Infotainment, overall technology", "Touch screen, operation",
        "Operating concept, operating system", "Navigation", "Audio mode, sound",
        "Apple CarPlay", "Android Auto", "Intelligent Personal Assistant",
        "Intelligent Personal Assistant, activation word", "Voice control / speech recognition",
        "Instrument cluster", "Head-Up Display", "USB port", "Mobile device, wireless charging",
        "Radio function", "Rear seat entertainment", "Manage / pair mobile device (Bluetooth)",
        "Apps (in-car)", "Gesture control", "Controller operation",
        "Multi-function steering wheel operation", "Touch Command", "Priorities for telephones",
        "Video: playback / streaming", "CD / DVD changer, playback", "Map update",
        "Real Time Traffic Information (RTTI)", "Traffic Camera Information", "Smart POI search",
        "Screen mirroring", "Display, time", "Driver profile", "Light switch operating unit",
    ],
    "Connected Apps & Digital Services": [
        "My BMW App / MINI App", "Personal eSIM", "Remote Software Upgrade/RSU",
        "Remote Services & Remote Keyless Entry (My BMW App/MINI App)", "WiFi hotspot",
        "Wi-Fi connection", "Remote Engine Start (My BMW App / MINI App)",
        "ConnectedDrive services (smartphone) technology overall",
        "BMW ConnectedDrive upgrades/ MINI CONNECTED upgrades", "Remote 3D View (My BMW App / MINI App)",
        "Remote interior camera (My BMW App / MINI App)", "My BMW / MINI Portal",
        "Customer Account (My BMW / MINI Portal)", "Teleservices", "BMW Online / MINI Online",
        "Driver's Guide App", "Apps (smartphone)", "Caring Car",
    ],
    "Seats, Comfort & Climate": [
        "Seats", "Interior comfort", "Seating, ventilate / heat", "Seat massage", "Seat memory",
        "Headrest, adjust", "Headrests, rear", "Adjustment of lower lumbar support",
        "Vehicle, climatization", "Air conditioning, setting", "Air conditioning control panel",
        "Air conditioning, overall technology", "Blower function", "Heated steering wheel",
        "Panel heating", "Auxiliary heater function", "Heated rear window", "Interior acoustics",
        "Sun protection", "Center armrest, front", "Steering wheel",
    ],
    "Interior Design & Storage": [
        "Interior design", "Interior", "Space / spatial impression", "Instrument panel",
        "Center console, front", "Upholstery / interior trim", "Ambient light",
        "Vehicle interior, lighting", "Welcome Light Carpet", "Storage compartments", "Glove box",
        "Cupholder", "Floor mat", "Door, finisher panel, front", "Interior rearview mirror",
        "Grab handle", "Sun visor, front", "Roof function centre", "12 V connection",
        "Luggage compartment", "Through-loading facility", "Frunk", "Trunk light",
    ],
    "Exterior Design & Body": [
        "Exterior design", "Exterior", "Body equipment, overall technology", "Exterior lighting",
        "Exterior rearview mirror", "Radiator grille", "Hood", "Bumper, front", "Bumper, rear",
        "Roof", "Side sill trim panel", "Running board", "Windshield", "Windshield wiper",
        "Rear wiper", "Rain sensor mode", "Wash / wipe switch", "Fog light", "Flashing", "Horns",
        "Opening / closing convertible top / hardtop", "Panorama glass roof",
    ],
    "Doors, Access & Keys": [
        "Door, open / close", "Automatic doors", "Vehicle key", "Digital Key",
        "Vehicle, lock / unlock", "Comfort Access", "non-contact trunk lid opening",
        "Trunk lid, open / close", "Trunk lid", "Vehicle, access and exit",
        "Resting state after door opening", "Door, front", "Outer door handle, front",
        "Outer door handle, rear", "Side window, open / close", "Hood, open / close",
        "Garage door opener", "Interior mirror, garage door opener", "Display key",
        "Remote Engine Start (Vehicle Key )",
    ],
    "Ownership & Service": [
        "Owner's Manual", "Accessories / Parts", "General enquiry: customer feedback",
        "Vehicle battery", "Engine oil", "Washer fluid, top up", "Trailer, use", "Towing eye",
    ],
}

FEATURE_TO_DOMAIN = {f: d for d, feats in DOMAIN_FEATURES.items() for f in feats}
DOMAINS = list(DOMAIN_FEATURES)

# Short labels for charts
DOMAIN_SHORT = {
    "Drivetrain & Performance": "Drivetrain",
    "Chassis & Driving Dynamics": "Chassis & dynamics",
    "EV Charging & Range": "EV charging & range",
    "Driver Assistance & Safety": "Assistance & safety",
    "Infotainment & HMI": "Infotainment & HMI",
    "Connected Apps & Digital Services": "Connected apps",
    "Seats, Comfort & Climate": "Seats & climate",
    "Interior Design & Storage": "Interior & storage",
    "Exterior Design & Body": "Exterior & body",
    "Doors, Access & Keys": "Doors & access",
    "Ownership & Service": "Ownership & service",
}

# Umbrella labels: generic, car-level labels. Annotators file most praise here
# ('Exterior design' has 391 comments and 0 complaints) while complaints land on
# specific components. Specific features are therefore compared only with other
# specific features (see scoring.py). Chosen by name, not by sentiment.
UMBRELLA_FEATURES = {
    "Drive, driving dynamics and chassis, overall technology", "Body equipment, overall technology",
    "ConnectedDrive and Infotainment, overall technology", "Driver assistance, automated driving, overall technology",
    "Vehicle safety, overall technology", "Air conditioning, overall technology",
    "ConnectedDrive services (smartphone) technology overall", "Drivetrain", "Handling / Riding",
    "Exterior design", "Interior design", "Exterior", "Interior", "Interior comfort",
    "Space / spatial impression", "Impression of safety",
}

# Features that only exist on electrified cars (used to flag label noise on ICE)
EV_ONLY_FEATURES = set(DOMAIN_FEATURES["EV Charging & Range"])

# --------------------------------------------------------------------------
# Level 3: VFC level-3 reason -> reason family (the "why" shown to the PM)
# --------------------------------------------------------------------------
REASON_FAMILIES = {
    # positive
    "Function works well": ["Like: function", "Like: vehicle equipment"],
    "Performance & efficiency": ["Like: performance", "Like: responsiveness", "Like: Efficiency", "Like: Range"],
    "Easy to use": ["Like: usability"],
    "Design & craftsmanship": ["Look / design appeals", "Workmanship appeals"],
    "Comfort & space": ["Likes comfort", "Likes size", "Like: Space / spatial impression",
                        "Like: storage space", "Like: view/panoramic view", "Like: odor"],
    "Sound": ["Like: sound"],
    "Good value": ["Like: price-performance ratio"],
    # negative: usability
    "Hard to use / confusing": ["Not user-friendly", "Ergonomics do not appeal", "Size not user friendly",
                                "Installation and set-up: difficult", "Accidental triggering"],
    "Cannot be switched off": ["Permanent switch-off not possible", "Switch off not possible"],
    "Inaccurate information": ["Information / accuracy insufficient",
                               "Information / Accuracy insufficient (electric range)"],
    # negative: defects
    "Malfunction / software fault": ["Malfunction", "Connection fault", "Blank / frozen screen",
                                     "Communication fault", "Reception quality not OK",
                                     "Warning / notification active", "Installation: fault"],
    "Battery drain": ["Battery discharge", "Capacity loss"],
    "Build quality / damage": ["Damage", "Fitting fault", "Workmanship does not appeal", "Leak",
                               "Leak: water ingress/condensation", "Leak: air", "Condensation",
                               "Cavity sealant: wax residue", "Locking, detent: fault", "Dirty contamination",
                               "Stiff movement", "Opening, closing: not possible / not complete",
                               "Excessive opening", "Odor/smoke"],
    "Noise & vibration": ["Noise", "Wind noise", "Vibration, oscillation"],
    "Performance / range shortfall": ["Drive power/driving performance not OK", "Effect, power not OK",
                                      "Range, not OK", "Fuel / power consumption too high",
                                      "Response characteristics not OK", "Response characteristics: too sluggish",
                                      "Response characteristics: too fast",
                                      "Response characteristics: too jerky/too abrupt",
                                      "Shift characteristics not OK", "Too slow", "Drivability not OK",
                                      "Pulls to one side", "Light intensity not OK", "Operating force not OK",
                                      "Charging infrastructure inadequate"],
    "Uncomfortable / too small": ["Not comfortable", "insufficient storage space",
                                  "View/restricted panoramic view", "too few"],
    "Poor value / missing equipment": ["Dislike: price-performance ratio", "Vehicle equipment: not available",
                                       "Vehicle equipment: not standard / too costly"],
    # requests
    "Wants new function": ["Customer request: function", "Customer request: compatibility"],
    "Wants easier use": ["Customer request: usability"],
    "Wants different design / material": ["Customer request: design", "Customer request: material quality"],
    "Wants more performance / comfort": ["Customer request: performance", "Customer request: sound",
                                         "Customer request: comfort", "Customer request: space / spatial impression",
                                         "Customer request: size"],
}

REASON_TO_FAMILY = {r: fam for fam, reasons in REASON_FAMILIES.items() for r in reasons}

# Reason labels whose wording implies a polarity; used to impute the 18 rows
# that carry a real VFC label but no Feedback Type.
REASON_TO_FEEDBACK_TYPE_HINT = {
    "Not user-friendly": "Difficult to Use",
    "Malfunction": "Defect",
}


def reason_polarity(reason: str):
    """Polarity implied by the wording of a level-3 reason (None if unknown)."""
    if not isinstance(reason, str):
        return None
    if reason.startswith(("Like", "Likes")) or reason in {"Look / design appeals", "Workmanship appeals"}:
        return "positive"
    if reason.startswith("Customer request"):
        return "request"
    return "negative"


# --------------------------------------------------------------------------
# Survey attribute <-> feedback feature map (hand-curated, used as a cross-check)
# --------------------------------------------------------------------------
US_SURVEY_TO_FEATURES = {
    "Overall exterior styling": ["Exterior design", "Exterior"],
    "Headlight/ taillight design": ["Exterior lighting"],
    "Riding comfort": ["Cushioning / damping vehicle", "Handling / Riding"],
    "Overall power and pickup": ["Drivetrain"],
    "Overall interior styling/ aesthetics": ["Interior design", "Interior"],
    "Overall comfort of the seats": ["Seats", "Seat massage", "Seating, ventilate / heat",
                                     "Adjustment of lower lumbar support"],
    "Interior storage": ["Storage compartments", "Glove box", "Center console, front"],
    "Cupholders": ["Cupholder"],
    "Ease of loading/unloading cargo": ["Luggage compartment"],
    "Trunk lid/ tailgate and liftgate operations": ["Trunk lid, open / close", "non-contact trunk lid opening", "Trunk lid"],
    "Overall performance of climate control system": ["Vehicle, climatization", "Air conditioning, setting",
                                                      "Blower function", "Air conditioning control panel"],
    "Operation of heater/ AC controls": ["Air conditioning, setting", "Air conditioning control panel"],
    "Overall performance of sound system": ["Audio mode, sound"],
    "Intuitiveness of controls": ["Touch screen, operation", "Operating concept, operating system",
                                  "Controller operation"],
    "Freedom from wind and road noise": ["Interior acoustics"],
    "Smoothness of transmission": ["Transmission"],
    "Braking": ["Braking"],
    "Overall driver assist features": ["Driver assistance, automated driving, overall technology",
                                       "Highway assistant", "(Active) cruise control"],
    "If applicable: Backup system (camera, sensors, etc.)": ["Rear view camera", "Park Distance Control (PDC)",
                                                             "Surround View", "Parking Assistant"],
    "Adaptive driving assists (lane keeping, cruise, braking)": ["(Active) cruise control", "Highway assistant",
                                                                 "Steering and lane guide assist",
                                                                 "Lane departure warning"],
    "If applicable: Navigation system": ["Navigation"],
    "Bluetooth/ smartphone pairing": ["Manage / pair mobile device (Bluetooth)"],
    "Mirroring of smartphone content on vehicle display": ["Apple CarPlay", "Android Auto"],
    "Phone charging": ["Mobile device, wireless charging", "USB port"],
    "Head-up Display": ["Head-Up Display"],
    "Menu structure of infotainment system": ["Operating concept, operating system", "Touch screen, operation"],
    "Performance of voice recognition": ["Voice control / speech recognition", "Intelligent Personal Assistant"],
    "Vehicle's Mobile App": ["My BMW App / MINI App"],
    "Gas or electric mileage (fuel economy)": ["Electric Range"],
    "If applicable: Sunroof/ moonroof": ["Panorama glass roof"],
}

# CN / EU survey (0-10 means, 2025) attribute -> feedback features. Hand-curated
# like the US map; attributes without a clear feature counterpart are left out.
CN_EU_SURVEY_TO_FEATURES = {
    "Exterior styling": ["Exterior design", "Exterior"],
    "Interior styling": ["Interior design", "Interior", "Ambient light"],
    "Quality of interior and materials used": ["Upholstery / interior trim", "Instrument panel"],
    "Safety": ["Vehicle safety, overall technology", "Impression of safety", "Airbags", "Seat belts"],
    "All round visibility": ["All-round view"],
    "Easy to read and use instruments/ controls/ displays": ["Instrument cluster", "Head-Up Display",
                                                             "Multi-function steering wheel operation"],
    "Smartphone integration/ connectivity": ["Apple CarPlay", "Android Auto", "Manage / pair mobile device (Bluetooth)",
                                             "Mobile device, wireless charging", "Screen mirroring"],
    "Features of information and entertainment system including in-car apps": [
        "ConnectedDrive and Infotainment, overall technology", "Apps (in-car)", "Audio mode, sound",
        "Radio function", "Video: playback / streaming", "Rear seat entertainment"],
    "Easy to use information and entertainment system including in-car apps": [
        "Touch screen, operation", "Operating concept, operating system", "Controller operation",
        "Voice control / speech recognition", "Intelligent Personal Assistant"],
    "Integrated navigation system": ["Navigation", "Map update", "Real Time Traffic Information (RTTI)"],
    "Overall seating comfort": ["Seats", "Seat massage", "Seating, ventilate / heat",
                                "Adjustment of lower lumbar support", "Headrest, adjust"],
    "Interior storage for small items": ["Storage compartments", "Glove box", "Cupholder", "Center console, front"],
    "Acceleration": ["Drivetrain"],
    "Roadholding": ["Handling / Riding", "Steering"],
    "Fuel economy/ energy efficiency": ["Electric Range"],
    "Braking": ["Braking"],
    "Sportiness": ["My Modes / driving experience"],
    "Quality of ride": ["Cushioning / damping vehicle", "Self-leveling suspension"],
    "Front interior roominess": ["Space / spatial impression"],
    "Rear interior roominess": ["Space / spatial impression"],
    "Ease of loading/ unloading luggage": ["Luggage compartment", "Trunk lid, open / close",
                                           "non-contact trunk lid opening", "Through-loading facility"],
    "Luggage capacity": ["Luggage compartment", "Frunk"],
    "Ease of entry into and out of car": ["Vehicle, access and exit", "Door, open / close", "Automatic doors"],
    "Heating/ ventilation/ air conditioning": ["Vehicle, climatization", "Air conditioning, setting",
                                               "Blower function", "Air conditioning control panel",
                                               "Auxiliary heater function"],
    "Quietness when driving": ["Interior acoustics"],
    "Driving position": ["Seats", "Steering wheel"],
    "Connected services": ["My BMW App / MINI App", "ConnectedDrive services (smartphone) technology overall",
                           "Remote Services & Remote Keyless Entry (My BMW App/MINI App)", "Personal eSIM",
                           "Remote Software Upgrade/RSU"],
}

# --------------------------------------------------------------------------
# Feedback feature <-> German price-list items (fitment / price join)
# --------------------------------------------------------------------------
# Hand-curated. A keyword matches an item name or one of its listed contents
# (the '– ...' lines under a package or system) when it starts at a word
# boundary; the right side is open so German compounds match ('Massage' ->
# 'Massagefunktion vorn'). Prefix 're:' for a raw regex. Only standard and
# optional equipment and wheels are searched; colours and upholstery are not.
# Every match is shown with the keyword that produced it, so a PM can audit it.
FEATURE_TO_OPTION_KEYWORDS = {
    # Infotainment & HMI
    "Head-Up Display": ["Head-Up"],
    "Touch screen, operation": ["Curved Display", "Touchbedienung", "Panoramic iDrive", "Control Display"],
    "Operating concept, operating system": ["BMW Operating System", "Panoramic iDrive"],
    "Instrument cluster": ["Instrumentendisplay", "Panoramic Vision"],
    "Controller operation": ["BMW Controller"],
    "Navigation": [r"re:\bNavigation\b", "Navigationsfunktion", "BMW Maps"],
    "Map update": ["Navigationskarten-Update"],
    "Intelligent Personal Assistant": ["Intelligent Personal Assistant"],
    "Apple CarPlay": ["Apple Car Play", "Apple CarPlay", "Smartphone Integration"],
    "Android Auto": ["Android Auto", "Smartphone Integration"],
    "Manage / pair mobile device (Bluetooth)": ["Bluetooth"],
    "Mobile device, wireless charging": ["Wireless Charging"],
    "USB port": ["USB"],
    "Touch Command": ["Touch Command"],
    "Audio mode, sound": ["Bowers & Wilkins", "harman/kardon", "HiFi Lautsprecher"],
    "Radio function": ["DAB", "Audio Tuner"],
    "Rear seat entertainment": ["Fond-Entertainment", "Theatre Screen"],
    "Video: playback / streaming": ["Videostreaming"],
    "Apps (in-car)": ["Vehicle Apps", "AirConsole"],
    # Connected apps & digital services
    "Remote Software Upgrade/RSU": ["Remote Software Upgrade"],
    "Remote Services & Remote Keyless Entry (My BMW App/MINI App)": ["Remote Services"],
    "Remote 3D View (My BMW App / MINI App)": ["Remote 3D View"],
    "Personal eSIM": ["eSIM"],
    "Teleservices": ["Teleservices", "TeleServices"],
    "BMW ConnectedDrive upgrades/ MINI CONNECTED upgrades": ["Digital Premium", "ConnectedDrive Store",
                                                             "Connected Drive Store"],
    "ConnectedDrive services (smartphone) technology overall": ["ConnectedDrive Services", "Connected Package"],
    # Driver assistance & safety
    "Highway assistant": ["Autobahnassistent", "Autobahn- & City-Assistent", "erweiterte Lenkunterstützung"],
    "(Active) cruise control": ["Aktive Geschwindigkeitsregelung", "Geschwindigkeitsregelung mit Bremsfunktion",
                                "Abstandsregelung"],
    "Steering and lane guide assist": ["Lenk- und Spurführungsassistent", "Lenk und Spurführungsassistent"],
    "Lane departure warning": ["Spurverlassenswarnung"],
    "Lane Change Assistant": ["Spurwechselassistent"],
    "Blind spot monitoring": ["Spurwechselwarnung"],
    "Front collision warning": ["Frontkollisionswarnung", "Frontkollisionwarnung", "Auffahr- und Personenwarnung"],
    "Rear-end collision warning": ["Heckkollisionswarnung", "Prävention Heckkollision"],
    "Cross Traffic Warning Rear with Brake Intervention": ["Querverkehrswarnung"],
    "Intersection Warning with Brake Intervention": ["Kreuzungswarnung", "Kreuzungsassistent",
                                                     "Linksabbiegewarnung"],
    "Traffic Light And Sign Warning": ["Ampelerkennung", "Ampelassistent"],
    "Speed Limit Assistant": ["Speed Limit Assist", "Speed Limit Info"],
    "Emergency Stop Assistant": ["Nothalteassistent"],
    "Traffic Jam Assistant": ["Stauassistent"],
    "Fatigue Alert": ["Aufmerksamkeitsassistent"],
    "High-beam assistant": ["Fernlichtassistent"],
    "Parking Assistant": ["Parking Assistant", "Parkassistent"],
    "Remote controlled parking": ["Ferngesteuertes Parken"],
    "Back-up Assistant": ["Rückfahrassistent"],
    "Rear view camera": ["Rückfahrkamera"],
    "Park Distance Control (PDC)": ["Park Distance Control", "Active PDC"],
    "Surround View": ["Surround View"],
    "Drive Recorder": ["Drive Recorder"],
    "Interior camera": ["Innenraumkamera"],
    "Anti-theft alarm system": ["Alarmanlage"],
    "Emergency request": ["Notruf"],
    "Airbags": ["Airbag"],
    "Seat belts": ["Sicherheitsgurte"],
    "Child restraint seat": ["Kindersitzbefestigung"],
    # Lighting, exterior & body
    "Ambient light": ["Ambientes Licht"],
    "Vehicle interior, lighting": ["Interieur Lichtpaket"],
    "Welcome Light Carpet": ["Light Carpet"],
    "Exterior lighting": ["Scheinwerfer", "Kristallscheinwerfer", "Iconic Glow"],
    "Radiator grille": ["Niere"],
    "Exterior rearview mirror": ["Außenspiegel"],
    "Interior rearview mirror": ["Innenspiegel"],
    "Garage door opener": ["Garagentoröffner"],
    "Interior mirror, garage door opener": ["Garagentoröffner"],
    "Panorama glass roof": ["Panorama Glasdach", "Panorama-Glasdach", "Sky Lounge"],
    "Sun protection": ["Sonnenschutz"],
    # Chassis & drivetrain
    "Cushioning / damping vehicle": ["Adaptives Fahrwerk", "Adaptives M Fahrwerk", "Adaptive Chassis Control",
                                     "Adaptive M Chassis Control", "Elektronisch geregelte Stoßdämpfer",
                                     "M Sportfahrwerk"],
    "Steering": ["Integral-Aktivlenkung"],
    "Steering wheel": ["Sportlenkrad", "Lederlenkrad", "Lenksäulenverstellung"],
    "Braking": ["Sportbremse", "Compound-Bremse"],
    "Wheels / tires": ["Leichtmetallräder", "Aerodynamikräder", "Schmiederäder"],
    "Tire pressure control": ["Reifendruck"],
    "Tirefit": ["Reifenpannenset", "Reifenreparatur"],
    "Transmission": ["Steptronic"],
    "Shift paddle": ["Schaltwippen"],
    "Launch Control": ["Launch Control"],
    "My Modes / driving experience": ["My Modes", "Fahrerlebnisschalter"],
    "Engine acoustics / engine sound": ["IconicSounds"],
    # Seats, comfort & climate
    "Seats": ["Sportsitze", "Komfortsitze", "Multifunktionssitze", "Aktivsitz", "Seriensitz",
              "Executive Lounge Seating"],
    "Seat memory": ["mit Memory"],
    "Seat massage": ["Massage"],
    "Seating, ventilate / heat": ["Sitzbelüftung", "Sitzheizung"],
    "Adjustment of lower lumbar support": ["Lordosenstütze"],
    "Heated steering wheel": ["Lenkradheizung"],
    "Panel heating": ["Wärmekomfortpaket"],
    "Vehicle, climatization": ["Klimaautomatik", "Standklimatisierung"],
    "Air conditioning, setting": ["Klimaautomatik"],
    "Auxiliary heater function": ["Standheizung"],
    "Interior acoustics": ["Komfortverglasung"],
    # Interior & storage
    "Storage compartments": ["Ablagemöglichkeiten", "Ablagefach"],
    "Center armrest, front": ["Armauflage vorne"],
    "Cupholder": ["Cupholder"],
    "Floor mat": ["Fußmatten"],
    "Luggage compartment": ["Gepäckraumtrennnetz"],
    "Through-loading facility": ["Durchladesystem", "Fondsitzlehne, Teilung"],
    "Trailer, use": ["Anhängerkupplung", "Anhängerassistent"],
    # Doors, access & keys
    "Comfort Access": ["Komfortzugang"],
    "Digital Key": ["Digital Key"],
    "Automatic doors": ["Automatiktüren"],
    "Door, open / close": ["Soft-Close", "Automatiktüren"],
    "Trunk lid, open / close": ["Automatische Heckklappenbetätigung"],
    "Outer door handle, front": ["Flächenintegrierte Türgriffe"],
    "Outer door handle, rear": ["Flächenintegrierte Türgriffe"],
    # EV charging
    "Charge high-voltage battery": ["AC-Laden", "Ladeleistung"],
    "Wallbox, charging / home charging": ["AC Laden für zuhause"],
    "Charging cable": ["Ladekabel"],
}

# Feedback feature <-> technical-data rows (Technische Werte), matched on the
# canonical German attribute label. Shown as spec context, never as a score.
FEATURE_TO_SPECS = {
    "Electric Range": ["elektrische reichweite, wltp in km"],
    "Luggage compartment": ["gepäckraumvolumen in l"],
    "High voltage battery": ["energieinhalt batterie in kwh, netto"],
    "Charge high-voltage battery": ["maximale ladeleistung dc in kw", "minimale ladedauer dc 10–80 % ladezustand in min",
                                    "maximale ladeleistung ac in kw"],
    "Public charging / external providers": ["maximale ladeleistung dc in kw",
                                             "minimale ladedauer dc 10–80 % ladezustand in min"],
    "Wallbox, charging / home charging": ["maximale ladeleistung ac in kw",
                                          "minimale ladedauer ac 0–100 % ladezustand in h"],
    "Drivetrain": ["leistung in kw (ps)", "drehmoment in nm", "beschleunigung 0–100 km/h in s"],
    "Fuel tank": ["tankinhalt in l"],
    "Trailer, use": ["maximale anhängelast gebremst, 12 % steigung / stützlast in kg"],
    "Transmission": ["getriebe"],
}
