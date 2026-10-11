"""Parse the German BMW price lists (OptionList PDFs) into an equipment table.

Each equipment line ends with one availability mark per model variant:
  ■ = standard, □ = optional, (blank) = not available for that variant.
The lists are the German market edition, so they serve as the EU baseline of
"what the car offers today"; other markets are not covered by the provided data.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

STD, OPT = "■", "□"
_PRICE = re.compile(r"(\d{1,3}(?:\.\d{3})*),[–-]")
_FREE = re.compile(r"[–-],[–-]")  # "–,–": option without extra charge
_SA_CODE = re.compile(r"\d[A-Z0-9]{2}|[A-Z]{4}")  # option code, e.g. 248, 7EW, KSFU
# Column headers listing model variants ("i5 eDrive40", "530e xDrive", "M135 xDrive", ...)
_VARIANT = r"(?:i\d (?:[a-z]?Drive\d+|M\d+ xDrive)|M?\d{3}[a-z]{0,2}(?: [xse]?Drive\d*)?)"
_VARIANT_PREFIX = re.compile(rf"^(?:{_VARIANT}(?:\s+|$))+")
_CONDITION = ("In Verbindung", "Nicht in Verbindung", "Nur in Verbindung", "Im Umfang", "Ausstattung abhängig",
              "Ausstattungsalternative")
_SECTION = re.compile(r"^[A-ZÄÖÜ /&\-]{4,}$")
_SKIP = re.compile(r"^(SA-Nr\.|EUR inkl|19 % MwSt|\[EUR ohne|MwSt\.\]|■ Serienausstattung|"
                   r"AUSGEWÄHL ?TE SERIEN|SONDERAUSSTATTUNGEN\.|FARBWEL ?T|\d+ [A-Z])")
_SPECS = {
    "electric_range_wltp_km": r"Elektrische Reichweite, WL ?TP in km\d?\s+(.+)",
    "dc_charging_kw": r"Maximale Ladeleistung DC in kW\s+(.+)",
    "dc_10_80_min": r"Minimale Ladedauer DC 10[–-]80 % Ladezustand in min\s+(.+)",
    "luggage_l": r"Gepäckraumvolumen in l\s+(.+)",
    "accel_0_100_s": r"Beschleunigung 0[–-]100 km/h in s\s+(.+)",
    "power_kw_ps": r"Leistung (?:Gesamtfahrzeugantrieb )?in K?W \(PS\)\d?\s+(.+)",
}


def _section_kind(text: str) -> str | None:
    if "SERIENAUSSTATTUNG" in text.replace(" ", ""):
        return "standard"
    if "SONDERAUSSTATTUNGEN" in text.replace(" ", "") or "AUSSTATTUNGSPAKETE" in text:
        return "options"
    if "FARBWELT" in text.replace(" ", ""):
        return "colours_trims"
    return None


def parse_option_list(path: Path, derivative: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    reader = PdfReader(str(path))
    items: list[dict] = []
    specs: list[dict] = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for key, pattern in _SPECS.items():
            for m in re.finditer(pattern, text):
                specs.append({"derivative": derivative, "spec": key, "values": m.group(1).strip(),
                              "page": page_no, "source": path.name})
        kind = _section_kind(text)
        if kind is None:
            continue
        section = ""
        buffer: list[str] = []
        for raw in text.splitlines():
            line = _strip_variant_header(raw.strip())
            if not line or _SKIP.match(line):
                continue
            marks = [ch for ch in line if ch in (STD, OPT)]
            if not marks:
                if _SECTION.match(line) and len(line) < 45:
                    section, buffer = line.title(), []
                else:
                    buffer.append(line)
                continue
            head = line.split(STD)[0].split(OPT)[0].strip()
            lines = [l for l in buffer + ([head] if head else []) if not l.startswith("[")]
            buffer = []
            item = _item_from_lines(lines, section)
            if item is None:
                continue
            leftovers, item = item
            if leftovers and items:  # content lines of the previous package
                items[-1]["details"] = "; ".join(filter(None, [items[-1]["details"], *leftovers]))[:400]
            if item.get("variant"):
                continue  # price variant of the previous item ("In Verbindung mit ...")
            items.append({
                "derivative": derivative, "kind": kind, "section": section, **item,
                "n_standard": marks.count(STD), "n_optional": marks.count(OPT),
                "page": page_no, "source": path.name,
            })
    return pd.DataFrame(items), pd.DataFrame(specs)


def _strip_variant_header(line: str) -> str:
    """Drop model-variant column headers; keep lines that merely start with an SA code."""
    m = _VARIANT_PREFIX.match(line)
    if m and (m.end() == len(line) or len(re.findall(_VARIANT, m.group(0))) >= 2):
        return line[m.end():].strip()
    return line


def _has_anchor(line: str) -> bool:
    """A line carrying the option's price or SA code."""
    return bool(_PRICE.search(line) or _FREE.search(line) or _SA_CODE.fullmatch(line.split()[-1]))


def _strip_anchor(line: str) -> tuple[str, str | None, float | None]:
    price = _PRICE.search(line)
    words = _FREE.sub("", _PRICE.sub("", line)).split()
    if words and words[-1] == "Serie":
        words = words[:-1]
    code = None
    if words and _SA_CODE.fullmatch(words[-1]):
        code, words = words[-1], words[:-1]
    return " ".join(words).strip(" –-"), code, float(price.group(1).replace(".", "")) if price else None


def _item_from_lines(lines: list[str], section: str) -> tuple[list[str], dict] | None:
    if not lines:
        return None
    anchors = [i for i, l in enumerate(lines) if not l.startswith(_CONDITION) and _has_anchor(l)]
    leftovers: list[str] = []
    code = price = None
    if anchors:
        i = anchors[-1]
        anchor_name, code, price = _strip_anchor(lines[i])
        if sum(ch.isalpha() for ch in anchor_name) >= 3:
            # "COMFORT PAKET 7VB 2.750,-": everything above belongs to the previous item
            leftovers = [l.lstrip("–- ") for l in lines[:i]]
            name, rest = anchor_name, lines[i + 1:]
        else:
            # "Sonnenschutzrollos / description / 416 600,-": name is the first plain line;
            # bullets above it are the previous package's content
            body = lines[:i]
            idx = next((j for j, l in enumerate(body) if not l.startswith(("–", "-") + _CONDITION)), None)
            if idx is None:
                return [l.lstrip("–- ") for l in body], {"variant": True}
            leftovers = [l.lstrip("–- ") for l in body[:idx] if not l.startswith(_CONDITION)]
            if idx and body[idx - 1].startswith(_CONDITION):
                return leftovers, {"variant": True}  # "Ausstattungsalternative: ..." price variant
            name, rest = body[idx], body[idx + 1:]
    else:
        if lines[0].startswith(_CONDITION):
            return [], {"variant": True}
        name = next((l for l in lines if not l.startswith(("–", "-") + _CONDITION)), "")
        rest = [l for l in lines if l != name]
        name, code, price = _strip_anchor(name) if name else ("", None, None)
    if name.startswith(_CONDITION):
        return leftovers, {"variant": True}
    if name.lower().startswith(("bestehend aus", "inkl.")):
        name = section  # package rows: the package title is the section header
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) < 3:
        return None
    details = [l.lstrip("–- ").strip() for l in rest if not l.startswith(_CONDITION)]
    return leftovers, {"name": name, "sa_code": code, "price_eur": price,
                       "details": "; ".join(details)[:400]}


def equipment_status(rows: pd.DataFrame, n_variants: int) -> str:
    """Summarise availability of matched equipment rows for one derivative."""
    if rows.empty:
        return "not in price list"
    std = int(rows["n_standard"].max())
    if std and std >= n_variants:
        return "standard on all variants"
    if std:
        return "standard on some variants, optional on others" if rows["n_optional"].max() else \
            "standard on some variants"
    return "optional (extra cost)" if rows["n_optional"].max() else "listed"
