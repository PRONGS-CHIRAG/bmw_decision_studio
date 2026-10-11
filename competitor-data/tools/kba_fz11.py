"""Sales rows from the KBA FZ11 annual files: official German new registrations by KBA segment and model series.

    python -I competitor-data/tools/kba_fz11.py SOURCE_ID_2025 SOURCE_ID_2024 > competitor-data/extracted/kba_registrations.jsonl

Reads the saved normalised text of the December files (fetched with `competitors fetch`). Each row's
`segment_label` is the KBA segment (e.g. 'Obere Mittelklasse'), so a BMW's rivals in Germany can be ranked within
the official segment the BMW itself is registered in. Evidence = the column header, the segment's first row and
the model's row up to its Jan.-Dec. count. Model series that do not match one model id (e.g. Volvo '90' = S90 + V90)
are left out on purpose.
"""

import json
import re
import sys
from pathlib import Path

TEXT = Path(__file__).resolve().parent.parent / "text"

# KBA "BRAND MODEL" -> (model id, note)
MAP = {
    "AUDI A3": ("audi-a3", None), "AUDI A6": ("audi-a6", "KBA model series A6; no separate A6 e-tron row"),
    "AUDI A7": ("audi-a7", None), "AUDI A8": ("audi-a8", None), "AUDI E-TRON GT": ("audi-e-tron-gt", None),
    "BMW 1ER": ("bmw-1-series", None), "BMW 5ER": ("bmw-5-series", "KBA model series 5ER; no separate i5 row"),
    "BMW 7ER": ("bmw-7-series", "KBA model series 7ER; no separate i7 row"),
    "MERCEDES A-KLASSE": ("mercedes-a-class", None), "MERCEDES CLA-KLASSE": ("mercedes-cla", None),
    "MERCEDES CLE": ("mercedes-cle", None),
    "MERCEDES E-KLASSE": ("mercedes-e-class", "KBA model series E-KLASSE; KBA lists no separate EQE row"),
    "MERCEDES S-KLASSE": ("mercedes-s-class", "KBA model series S-KLASSE; KBA lists no separate EQS or Maybach row"),
    "PORSCHE PANAMERA": ("porsche-panamera", None), "PORSCHE TAYCAN": ("porsche-taycan", None),
    "VW GOLF": ("vw-golf", None), "VW ID.7": ("vw-id-7", None), "SKODA OCTAVIA": ("skoda-octavia", None),
    "OPEL ASTRA": ("opel-astra", None),
    "SEAT LEON": ("cupra-leon", "KBA files the Cupra Leon under SEAT LEON; the figure includes the Seat Leon"),
    "TESLA MODEL S": ("tesla-model-s", None), "LEXUS ES": ("lexus-es", None), "LEXUS LS": ("lexus-ls", None),
    "LUCID AIR": ("lucid-air", None), "MAZDA 3": ("mazda-3", None), "TOYOTA COROLLA": ("toyota-corolla", None),
    "TOYOTA MIRAI": ("toyota-mirai", None), "DS 4": ("ds-4", None), "DS DS4": ("ds-4", None),
    "NIO ET7": ("nio-et7", None), "POLESTAR 2": ("polestar-2", None), "MASERATI GHIBLI": ("maserati-ghibli", None),
    "HYUNDAI G80": ("genesis-g80", "KBA files Genesis models under HYUNDAI"),
    "HYUNDAI G90": ("genesis-g90", "KBA files Genesis models under HYUNDAI"),
    "ZEEKR 001": ("zeekr-001", None), "LOTUS EMEYA": ("lotus-emeya", None),
}


def rows(sid: str) -> list[dict]:
    lines = (TEXT / f"{sid}.txt").read_text().split("\n")
    head = next(l for l in lines if re.search(r"\| Januar ?- ?Dezember \d{4}", l))
    m = re.search(r"Januar ?- ?Dezember (\d{4})", head)
    year, col = int(m.group(1)), m.group(0)
    out, segment, first = [], None, None
    for line in lines:
        cells = [re.sub(r"\s+", " ", c).strip() for c in line.split("|")]
        if len(cells) < 9 or cells[2] in ("", "Modellreihe"):
            continue
        if cells[1] and not cells[1].endswith("ZUSAMMEN") and cells[1] != "Segment":
            segment, first = cells[1], f"{cells[1]} | {cells[2]}"
        if segment is None or cells[2] not in MAP or not re.fullmatch(r"\d+", cells[8]):
            continue
        mid, note = MAP[cells[2]]
        row = " | ".join(cells[2:9])
        evidence = f"{col} ... {segment} | {row}" if cells[1] else f"{col} ... {first} ... {row}"
        label = f"KBA segment {segment.title()}"
        out.append({"table": "sales", "model_id": mid, "market": "EU", "region": "Germany", "year": year, "period": "FY",
                    "units": int(cells[8]), "basis": "registrations", "tier": "official", "segment_label": label,
                    "source_id": sid, "evidence": evidence,
                    "note": "; ".join(x for x in (f"KBA FZ11 December {year}, column {col}", note) if x)})
    return out


if __name__ == "__main__":
    for sid in sys.argv[1:]:
        for r in rows(sid):
            print(json.dumps(r, ensure_ascii=False))
