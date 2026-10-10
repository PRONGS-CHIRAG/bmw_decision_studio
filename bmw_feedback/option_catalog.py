"""Coordinate-aware parser for the German BMW price lists (Preisliste, Juli 2026).

Each PDF is a DE-market catalogue for one series:
    FAHRZEUGPREISE      per variant: powertrain, power, WLTP, base price (horizontal table)
    SERIENAUSSTATTUNGEN standard equipment, one column of ■ per variant
    RÄDER / FARBWELT    wheels, paints, upholstery, trims: SA code, price, ■/□ per variant
    SONDERAUSSTATTUNGEN optional equipment: SA code, price(s), ■/□ per variant
    TECHNISCHE WERTE    technical data per variant (horizontal table)

Text extraction alone loses the table grid, so this parser works on positions:
column headers (rotated variant names, or the header row of a horizontal table),
horizontal rules (row bands) and the ■/□ glyphs. A row can carry several price
lines, each with its own mark row (e.g. 3G3: 1.520,– for ICE, 300,– for i5);
marks are bound to the price line at the same height.

Every output row keeps (model, page) provenance. `validate()` asserts that
every ■/□ glyph on a table page was assigned to a cell and that every price
pair satisfies gross = net x 1.19 (German VAT).

Requires PyMuPDF (`pip install pymupdf`).
"""

import re
from dataclasses import dataclass, field

import pandas as pd

from . import config

VAT = 1.19
MARKS = {"■": "standard", "□": "optional"}
NAME_COLOR = 0x474847          # dark grey: item names, conditions, notes
DESC_COLOR = 0x717372          # light grey: descriptions
CONDITION_PREFIXES = ("Nur in Verbindung", "Nicht in Verbindung", "In Verbindung", "Nicht verfügbar",
                      "Nur für", "Für ", "Hinweis", "Nicht kombinierbar", "Ersetzt", "Entfällt", "Im Umfang",
                      "Serienmäßig", "Ausstattungsalternative", "(Ausstattungsalternative")
POWERTRAIN_HEADINGS = {"BENZINER": "Petrol", "DIESEL": "Diesel", "VOLLELEKTRISCH": "Electric",
                       "PLUG-IN-HYBRID": "Plug-in hybrid"}
# Feedback data uses ICE / BEV / PHEV; the price list's petrol and diesel variants are ICE
# (some with 48 V mild-hybrid assistance), i-models are BEV, 'e' models are PHEV.
POWERTRAIN_TO_ENGINE = {"Petrol": "ICE", "Diesel": "ICE", "Electric": "BEV", "Plug-in hybrid": "PHEV"}
TABLE_PAGE_TYPES = {
    "AUSGEWÄHLTE SERIENAUSSTATTUNGEN.": "standard_equipment",
    "RÄDER UND REIFEN.": "wheels",
    "FARBWELT EXTERIEUR.": "paint",
    "FARBWELT INTERIEUR.": "interior_colour",
    "SONDERAUSSTATTUNGEN.": "optional_equipment",
}
PRICE_TEXT = re.compile(r"^(?:\d{1,3}(?:\.\d{3})*,(?:[–-]|\d{2})|[–-],[–-]|Serie)$")
NET_TEXT = re.compile(r"^\[(\d{1,3}(?:\.\d{3})*,\d{2})\]$")


# --------------------------------------------------------------------------- primitives
@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    color: int
    size: float

    @property
    def xc(self):
        return (self.x0 + self.x1) / 2

    @property
    def yc(self):
        return (self.y0 + self.y1) / 2


def normalise(text: str) -> str:
    text = text.replace("\xad", "").replace(" ", " ").replace(" ", " ").replace(" ", " ")
    text = text.replace("T echn", "Techn").replace("L TE", "LTE")
    return re.sub(r"\s+", " ", text).strip()


def page_lines(page, horizontal=True):
    """Text lines with footnote superscripts removed (PyMuPDF span flag bit 0)."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            is_h = tuple(round(v) for v in line["dir"]) == (1, 0)
            if is_h != horizontal:
                continue
            spans = [s for s in line["spans"] if not (s["flags"] & 1)]
            text = normalise("".join(s["text"] for s in spans))
            if not text:
                continue
            first = spans[0]
            x0, y0, x1, y1 = line["bbox"]
            out.append(Line(text, x0, y0, x1, y1, first["color"], round(first["size"], 1)))
    return sorted(out, key=lambda l: (round(l.y0, 0), l.x0))


def page_marks(page):
    """■/□ glyph positions, excluding the legend line at the bottom of the page."""
    marks = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            line_text = "".join(c["c"] for s in line["spans"] for c in s["chars"])
            if "Serienausstattung" in line_text or "Sonderausstattung" in line_text:
                continue
            for span in line["spans"]:
                for ch in span["chars"]:
                    if ch["c"] in MARKS:
                        x0, y0, x1, y1 = ch["bbox"]
                        marks.append({"mark": ch["c"], "x": (x0 + x1) / 2, "y": (y0 + y1) / 2})
    return marks


def rule_segments(page, min_width=20):
    """Horizontal rules as (y, x0, x1), drawn as thin lines or thin rectangles."""
    segs = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.height < 1.5 and r.width >= min_width:
            segs.append((round(r.y0, 1), r.x0, r.x1))
    return segs


def rule_ys(segs, tol=1.0):
    ys = sorted({s[0] for s in segs})
    out = []
    for y in ys:
        if not out or y - out[-1] > tol:
            out.append(y)
    return out


def canon_label(text):
    """Comparable key for table labels ('Hubraum in cm³' == 'Hubraum in cm', 'KW' == 'kW')."""
    if not isinstance(text, str):
        return text
    t = text.replace("³", "").replace("cm3", "cm").replace("ABMESSUNGEN", "ABMESSUNG")
    t = re.sub(r"\s*/\s*", " / ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def page_title(lines):
    big = [l for l in lines if l.size >= 15]
    return big[0].text if big else ""


def parse_price(text):
    """'1.520,–' -> 1520.0; '–,–' and 'Serie' -> 0.0; '[1.277,31]' -> 1277.31."""
    text = text.strip()
    m = NET_TEXT.match(text)
    if m:
        text = m.group(1)
    if text in ("–,–", "-,-", "Serie"):
        return 0.0
    return float(text.replace(".", "").replace(",–", "").replace(",-", "").replace(",", "."))


def parse_number_range(text):
    """Numeric min / max from values like '6,3 – 5,8', '1.998', '250 (340)', '11 / 22'.

    Returns (min, max) of the leading numbers only; non-numeric values -> (None, None).
    """
    if not isinstance(text, str):
        return None, None
    lead = re.split(r"\s*\(|\s*/\s*", text)[0]
    nums = re.findall(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?", lead)
    vals = [float(n.replace(".", "").replace(",", ".")) for n in nums]
    if not vals:
        return None, None
    return min(vals), max(vals)


# --------------------------------------------------------------------------- column tables
@dataclass
class Item:
    model: str
    page: int
    page_type: str
    section: str
    name: str
    y_name: float
    description: list = field(default_factory=list)
    contents: list = field(default_factory=list)
    conditions: list = field(default_factory=list)
    sa_code: str = None
    mark_rows: list = field(default_factory=list)   # [{y, marks: {variant: status}, price, net, condition}]
    shares_marks_with: "Item" = None                # colour groups: one mark row for several SA codes


def _variant_columns(page):
    """Rotated header labels -> (variant columns, SA x, price x)."""
    rot = page_lines(page, horizontal=False)
    variants, sa_x, price_x = [], None, None
    for l in rot:
        if l.text.startswith("SA-Nr"):
            sa_x = l.xc
        elif any(t in l.text for t in ("EUR", "MwSt")):
            price_x = l.xc if price_x is None else min(price_x, l.xc)
        else:
            variants.append((l.text, l.xc))
    variants.sort(key=lambda v: v[1])
    header_bottom = max(l.y1 for l in rot) if rot else 0
    return variants, sa_x, price_x, header_bottom


def _nearest(x, columns, tol):
    best = min(columns, key=lambda c: abs(c[1] - x))
    return best[0] if abs(best[1] - x) <= tol else None


def parse_column_table(page, model, page_no, page_type):
    """Rows of a ■/□ table page -> list[Item] (+ count of glyphs left unassigned)."""
    variants, sa_x, price_x, header_bottom = _variant_columns(page)
    if not variants:
        return [], 0
    pitch = min(b[1] - a[1] for a, b in zip(variants, variants[1:])) if len(variants) > 1 else 20
    first_col = variants[0][1] - pitch / 2
    text_right = (sa_x - 12) if sa_x else first_col
    lines = [l for l in page_lines(page) if l.y0 > header_bottom and l.size < 15]
    marks = [m for m in page_marks(page) if m["y"] > header_bottom]
    ys = [y for y in rule_ys(rule_segments(page)) if y > header_bottom - 3]
    legend_top = min((l.y0 for l in page_lines(page) if "Serienausstattung" in l.text), default=page.rect.height)
    if not ys or ys[-1] < legend_top - 5:
        ys = ys + [legend_top - 1]

    # Split rule bands where a new SA-code cluster starts: colour groups are separated by a
    # blank line, not a rule, and each group has its own SA codes, price and mark row.
    bands = []
    for top, bottom in zip(ys, ys[1:]):
        codes = sorted((l for l in lines if top <= l.yc < bottom and sa_x and abs(l.xc - sa_x) < 14),
                       key=lambda l: l.y0)
        cuts = [c.y0 - 1.5 for prev, c in zip(codes, codes[1:]) if c.y0 - prev.y0 > 10]
        edges = [top] + cuts + [bottom]
        bands += list(zip(edges, edges[1:]))

    items, section, unassigned = [], None, 0
    for top, bottom in bands:
        band_lines = [l for l in lines if top <= l.yc < bottom]
        band_marks = [m for m in marks if top <= m["y"] < bottom]
        left = [l for l in band_lines if l.x0 < text_right and l.x1 <= text_right + 40]
        if sa_x:
            sa = [l for l in band_lines if abs(l.xc - sa_x) < 14 and l not in left]
        else:
            sa = []
        prices = [l for l in band_lines if price_x and abs(l.xc - price_x) < 24 and l not in left]
        if not left and not band_marks:
            continue
        if left and not band_marks and not sa and not prices and all(l.text == l.text.upper() for l in left):
            if len(left) == 1:
                section = left[0].text.title()
            continue
        # A band that only continues the previous item (notes / conditions split by a light rule)
        is_continuation = (items and not sa and left and left[0].text.startswith(CONDITION_PREFIXES)
                           and not any(p.text and PRICE_TEXT.match(p.text) for p in prices) and not band_marks)
        if is_continuation:
            items[-1].conditions += [l.text for l in left]
            continue
        if not left:            # marks without a name: attach to previous item (e.g. a second price row)
            if not items:
                unassigned += len(band_marks)
                continue
            item = items[-1]
        else:
            item = Item(model, page_no, page_type, section, left[0].text, left[0].yc)
            is_package = left[0].text == left[0].text.upper() and any(c.isalpha() for c in left[0].text)
            name_done, prev = False, left[0]
            for l in left[1:]:
                # a wrapped line continues the previous one: tight line spacing after a nearly full line
                wrapped = l.y0 - prev.y0 <= 8 and prev.x1 > text_right - 60
                if l.text.startswith("–"):
                    item.contents.append(l.text.lstrip("– ").strip())
                    name_done = True
                elif l.text.startswith(CONDITION_PREFIXES):
                    item.conditions.append(l.text)
                    name_done = True
                elif l.color == NAME_COLOR and not name_done and wrapped:
                    item.name = f"{item.name} {l.text}"
                elif item.conditions and l.color == NAME_COLOR and wrapped:
                    item.conditions[-1] = f"{item.conditions[-1]} {l.text}"
                elif is_package and l.color == NAME_COLOR:
                    item.contents.append(l.text)
                    name_done = True
                else:
                    item.description.append(l.text)
                    name_done = True
                prev = l
            item.sa_code = sa[0].text if sa else None
            items.append(item)

        # price lines: gross followed by [net]
        gross = [p for p in prices if PRICE_TEXT.match(p.text)]
        nets = [p for p in prices if NET_TEXT.match(p.text)]
        price_rows = []
        for g in gross:
            net = next((n for n in nets if 0 < n.y0 - g.y0 < 12), None)
            price_rows.append({"y": g.yc, "price": parse_price(g.text), "price_text": g.text,
                               "net": parse_price(net.text) if net else None})
        # mark rows: cluster glyphs by height
        rows = []
        for m in sorted(band_marks, key=lambda m: m["y"]):
            if rows and abs(m["y"] - rows[-1]["y"]) < 3:
                rows[-1]["glyphs"].append(m)
            else:
                rows.append({"y": m["y"], "glyphs": [m]})
        for r in rows:
            cells = {}
            for g in r["glyphs"]:
                v = _nearest(g["x"], variants, pitch / 2)
                if v is None:
                    unassigned += 1
                    continue
                cells[v] = MARKS[g["mark"]]
            pr = min(price_rows, key=lambda p: abs(p["y"] - r["y"]), default=None)
            if pr is not None and abs(pr["y"] - r["y"]) > 6:
                pr = None
            cond = next((l.text for l in left[1:] if abs(l.yc - r["y"]) < 4), None) if left else None
            item.mark_rows.append({"y": r["y"], "marks": cells,
                                   "price": pr["price"] if pr else None, "net": pr["net"] if pr else None,
                                   "price_text": pr["price_text"] if pr else None, "condition": cond})
        # Colour groups list several names, each with its own SA code, under one price / mark row
        if left and len(sa) > 1:
            for code in sa[1:]:
                twin = next((l for l in left if abs(l.yc - code.yc) < 2.5), None)
                if twin is None:
                    continue
                if twin.text in item.description:
                    item.description.remove(twin.text)
                items.append(Item(model, page_no, page_type, section, twin.text, twin.yc,
                                  conditions=list(item.conditions), sa_code=code.text,
                                  mark_rows=item.mark_rows, shares_marks_with=item))
    # Footnote text that sits inside the table area has neither an SA code nor marks
    items = [it for it in items if it.mark_rows or it.sa_code]
    return items, unassigned


# --------------------------------------------------------------------------- horizontal tables
def _bands(page, segs, y_min, y_max):
    ys = [y for y in rule_ys(segs) if y_min <= y <= y_max]
    return list(zip(ys, ys[1:]))


def parse_horizontal_table(page, page_no, model):
    """Price and technical-data pages -> long rows (block, variant, label, value)."""
    lines = [l for l in page_lines(page) if l.size < 15]
    segs = rule_segments(page)
    rows, block, columns, group = [], None, None, None
    title_lines = sorted([l for l in lines if l.size >= 9 and l.text.upper() == l.text
                          and l.text.rstrip(".") in POWERTRAIN_HEADINGS], key=lambda l: l.y0)
    footer_top = min((l.y0 for l in lines if l.text.startswith(("Dargestellt sind", "Die technischen Daten"))
                      or (l.x0 < 60 and re.match(r"^\d\s+[A-ZÄÖÜ][a-zäöü]", l.text))), default=page.rect.height)
    for top, bottom in _bands(page, segs, 0, footer_top):
        band = [l for l in lines if top <= l.yc < bottom]
        titles = [t for t in title_lines if top <= t.yc < bottom]
        if titles:
            block = POWERTRAIN_HEADINGS[titles[-1].text.rstrip(".")]
            columns = None
            continue
        if not band:
            continue
        # column boundaries from the rule segments that bound this band
        band_segs = sorted({(round(s[1]), round(s[2])) for s in segs if abs(s[0] - bottom) < 1.5})
        if len(band_segs) < 2:
            continue
        label_seg, value_segs = band_segs[0], band_segs[1:]
        label = " ".join(l.text for l in band if l.x1 <= label_seg[1] + 2)
        cells = []
        for x0, x1 in value_segs:
            cell = " ".join(l.text for l in sorted(band, key=lambda l: (round(l.y0), l.x0)) if x0 - 2 <= l.xc <= x1 + 2)
            cells.append(re.sub(r"–\s*–", "–", cell))
        if columns is None:
            # header row: variant names (the label cell may name the table, e.g. 'BMW 5er Benziner / Diesel')
            if any(cells):
                columns = [(c, seg) for c, seg in zip(cells, value_segs)]
                if block is None and label:
                    block = label
            continue
        if label and not any(cells):
            group = label
            continue
        for (variant, seg), value in zip(columns, cells):
            if variant and value:
                rows.append({"model": model, "page": page_no, "block": block, "group": group,
                             "variant": variant, "attribute": label, "value": value})
    return rows


# --------------------------------------------------------------------------- package pages
def parse_package_page(page, page_no, model, title):
    """'M SPORTPAKET.' style pages: package price lines + included SA items (text order)."""
    lines = page_lines(page)
    sa_header = next((l for l in lines if l.text == "SA-Nr."), None)
    if sa_header is None:
        return []
    rows = []
    sa_lines = [l for l in lines if abs(l.xc - sa_header.xc) < 14 and re.match(r"^[0-9A-Z]{3,4}$", l.text)]
    for sa in sa_lines:
        name = max((l for l in lines if l.x1 < sa_header.x0 - 5 and abs(l.y0 - sa.y0) < 2 and l.color == NAME_COLOR),
                   key=lambda l: l.x1, default=None)
        if name is None or name.text.startswith(CONDITION_PREFIXES):
            continue
        price = next((l for l in lines if l.x0 > sa.x1 + 5 and abs(l.y0 - sa.y0) < 2
                      and PRICE_TEXT.match(l.text.split(" [")[0])), None)
        rows.append({"model": model, "page": page_no, "package": title.rstrip(".").title(), "name": name.text,
                     "sa_code": sa.text, "price_text": price.text if price else None})
    return rows


# --------------------------------------------------------------------------- model level
def parse_model(model: str, path) -> dict:
    import pymupdf

    doc = pymupdf.open(str(path))
    items, horizontal, packages, stats = [], [], [], []
    for page_no, page in enumerate(doc, start=1):
        lines = page_lines(page)
        title = page_title(lines)
        if title in TABLE_PAGE_TYPES:
            page_items, unassigned = parse_column_table(page, model, page_no, TABLE_PAGE_TYPES[title])
            items += page_items
            n_glyphs = len(page_marks(page))
            n_cells = sum(len(r["marks"]) for it in page_items if it.shares_marks_with is None for r in it.mark_rows)
            stats.append({"model": model, "page": page_no, "page_type": TABLE_PAGE_TYPES[title],
                          "glyphs": n_glyphs, "cells": n_cells, "unassigned": unassigned, "items": len(page_items)})
        elif title in ("FAHRZEUGPREISE.", "TECHNISCHE WERTE."):
            for r in parse_horizontal_table(page, page_no, model):
                r["table"] = "prices" if title.startswith("FAHRZEUG") else "technical"
                horizontal.append(r)
        elif title.endswith(".") and "SPORTPAKET" in title or "xDRIVE." in title or "M SPORT DESIGN" in title:
            packages += parse_package_page(page, page_no, model, title)
    return {"items": items, "horizontal": horizontal, "packages": packages, "stats": stats}


def _item_frames(items):
    """Items -> (option_items, option_fitment) DataFrames."""
    it_rows, fit_rows = [], []
    counter = {}
    for it in items:
        key = (it.model, it.page)
        counter[key] = counter.get(key, 0) + 1
        item_id = f"{it.model}-p{it.page:02d}-{counter[key]:02d}"
        it_rows.append({"item_id": item_id, "model": it.model, "page": it.page, "page_type": it.page_type,
                        "section": it.section, "name": it.name, "sa_code": it.sa_code,
                        "description": " | ".join(it.description), "contents": " | ".join(it.contents),
                        "conditions": " | ".join(it.conditions)})
        for r in it.mark_rows:
            for variant, status in r["marks"].items():
                fit_rows.append({"item_id": item_id, "model": it.model, "page": it.page, "variant": variant,
                                 "status": status,
                                 "price_eur": r["price"] if status == "optional" else None,
                                 "price_net_eur": r["net"] if status == "optional" else None,
                                 "price_text": r["price_text"], "price_condition": r["condition"]})
    return pd.DataFrame(it_rows), pd.DataFrame(fit_rows)


def build_catalog() -> dict:
    """Parse all three price lists -> dict of DataFrames (see module docstring)."""
    parsed = {m: parse_model(m, p) for m, p in config.OPTION_LIST_FILES.items() if p.exists()}
    items = [it for v in parsed.values() for it in v["items"]]
    option_items, fitment = _item_frames(items)
    horizontal = pd.DataFrame([r for v in parsed.values() for r in v["horizontal"]])
    packages = pd.DataFrame([r for v in parsed.values() for r in v["packages"]])
    stats = pd.DataFrame([r for v in parsed.values() for r in v["stats"]])

    prices = horizontal[horizontal["table"] == "prices"].copy()
    technical = horizontal[horizontal["table"] == "technical"].copy()
    technical[["value_min", "value_max"]] = technical["value"].apply(lambda v: pd.Series(parse_number_range(v)))
    technical["attribute_key"] = technical["attribute"].map(canon_label)
    technical["group_key"] = technical["group"].map(canon_label)
    variants = _variants(prices)
    return {"variants": variants, "price_specs": prices, "technical": technical, "option_items": option_items,
            "fitment": fitment, "packages": packages, "page_stats": stats}


def _variants(prices: pd.DataFrame) -> pd.DataFrame:
    """One row per (model, variant) from the FAHRZEUGPREISE pages."""
    out = []
    for (model, variant), g in prices.groupby(["model", "variant"], sort=False):
        attr = dict(zip(g["attribute"], g["value"]))
        base = attr.get("FAHRZEUGGRUNDPREIS", "")
        m = re.match(r"^([\d.]+,[–-])\s*\[([\d.,]+)\]$", base)
        power = next((v for k, v in attr.items() if k.startswith("Leistung Gesamtfahrzeugantrieb")), "")
        pm = re.match(r"^(\d+)\s*\((\d+)\)", power)
        block = g["block"].iloc[0]
        out.append({"model": model, "variant": variant, "powertrain": block,
                    "engine": POWERTRAIN_TO_ENGINE.get(block), "page": int(g["page"].iloc[0]),
                    "transmission": attr.get("Getriebe"), "power_kw": float(pm.group(1)) if pm else None,
                    "power_ps": float(pm.group(2)) if pm else None,
                    "base_price_eur": parse_price(m.group(1)) if m else None,
                    "base_price_net_eur": parse_price(f"[{m.group(2)}]") if m else None})
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- validation
def validate(cat: dict) -> dict:
    """Hard checks; raises AssertionError with the offending rows."""
    report = {}
    st = cat["page_stats"]
    bad = st[(st["glyphs"] != st["cells"]) | (st["unassigned"] > 0)]
    assert bad.empty, f"■/□ glyphs not all assigned to cells:\n{bad}"
    report["table_pages"] = int(len(st))
    report["glyphs_assigned"] = int(st["cells"].sum())

    f = cat["fitment"].dropna(subset=["price_net_eur"])
    f = f[f["price_eur"] > 0]
    diff = (f["price_net_eur"] * VAT - f["price_eur"]).abs()
    assert (diff <= 1.0).all(), f"Option prices violate gross = net x 1.19 (parse error):\n{f[diff > 1.0].head(20)}"
    # Sub-euro gaps are printed that way in the source (e.g. 2.280,– [1.915,67]); report, don't fail
    anomalies = f[diff > 0.06].drop_duplicates(["item_id", "price_text"])
    report["option_price_pairs_checked"] = int(len(f))
    report["source_price_anomalies"] = [
        {"model": r.model, "page": int(r.page), "item_id": r.item_id, "gross": r.price_eur, "net": r.price_net_eur,
         "net_x_1_19": round(r.price_net_eur * VAT, 2)} for r in anomalies.itertuples()]

    v = cat["variants"].dropna(subset=["base_price_eur"])
    off = v[(v["base_price_net_eur"] * VAT - v["base_price_eur"]).abs() > 0.06]
    assert off.empty, f"Base prices violate gross = net x 1.19:\n{off}"
    report["base_prices_checked"] = int(len(v))

    # Power on the price page must match the technical-data page
    tech = cat["technical"]
    tp = tech[tech["attribute"].str.startswith("Leistung in", na=False)]
    mismatches = []
    for r in cat["variants"].itertuples():
        t = tp[(tp["model"] == r.model) & (tp["variant"].str.replace(" ", "") == r.variant.replace(" ", ""))]
        if t.empty or r.power_kw is None:
            continue
        kw, _ = parse_number_range(t["value"].iloc[0])
        if kw != r.power_kw:
            mismatches.append((r.model, r.variant, r.power_kw, t["value"].iloc[0]))
    assert not mismatches, f"Power differs between price and technical pages: {mismatches}"
    report["power_cross_checked"] = int(len(cat["variants"]))

    # Every variant column on the option pages must exist on the price pages
    known = set(zip(cat["variants"]["model"], cat["variants"]["variant"].str.replace(" ", "")))
    cols = set(zip(cat["fitment"]["model"], cat["fitment"]["variant"].str.replace(" ", "")))
    assert cols <= known, f"Variant columns without a price-page entry: {sorted(cols - known)}"
    return report


# --------------------------------------------------------------------------- feature link
LINK_PAGE_TYPES = ("standard_equipment", "optional_equipment", "wheels")


def _keyword_regex(keyword: str):
    if keyword.startswith("re:"):
        return re.compile(keyword[3:])
    return re.compile(r"(?<![A-Za-zÄÖÜäöüß])" + re.escape(keyword), re.I)


def match_features(cat: dict) -> pd.DataFrame:
    """Feedback feature -> price-list items, one row per (feature, item) with the keyword that matched.

    A match on the item name means the item *is* the feature; a match on its
    contents means the feature comes inside a package or system (e.g. the
    Head-Up Display inside the G60 Innovationspaket).
    """
    from . import taxonomy

    items = cat["option_items"]
    items = items[items["page_type"].isin(LINK_PAGE_TYPES)]
    rows = []
    for feature, keywords in taxonomy.FEATURE_TO_OPTION_KEYWORDS.items():
        regexes = [(k, _keyword_regex(k)) for k in keywords]
        for it in items.itertuples():
            parts = [("name", it.name)]
            parts += [("description", d) for d in (it.description or "").split(" | ") if d]
            parts += [("contents", c) for c in (it.contents or "").split(" | ") if c]
            hit = next(((k, where, text) for where, text in parts for k, rx in regexes if rx.search(text)), None)
            if hit is None:
                continue
            rows.append({"feature": feature, "model": it.model, "item_id": it.item_id, "option_name": it.name,
                         "sa_code": it.sa_code, "page": it.page, "page_type": it.page_type,
                         "matched_keyword": hit[0], "matched_in": hit[1], "matched_text": hit[2]})
    return pd.DataFrame(rows)


def feature_fitment(links: pd.DataFrame, cat: dict) -> pd.DataFrame:
    """Per (feature, model, variant): best availability over all linked items.

    status: 'standard' if any linked item is standard on the variant, else
    'optional' if any is optional, else 'not_listed'. price_min_eur is the
    cheapest listed price to get it as an option (package prices included,
    flagged by via_package).
    """
    fit, variants = cat["fitment"], cat["variants"]
    # Only variants that have a column in the equipment tables can be judged (G70: 4 of 7)
    covered = set(zip(fit["model"], fit["variant"]))
    variants = variants[[(m, v) in covered for m, v in zip(variants["model"], variants["variant"])]]
    rows = []
    for (feature, model), g in links.groupby(["feature", "model"]):
        f = fit[fit["item_id"].isin(g["item_id"])].merge(
            g[["item_id", "option_name", "sa_code", "page_type", "page"]], on=["item_id", "page"])
        is_pkg = f["option_name"].str.upper() == f["option_name"]
        f = f.assign(via_package=is_pkg)
        for v in variants[variants["model"] == model].itertuples():
            fv = f[f["variant"] == v.variant]
            std, opt = fv[fv["status"] == "standard"], fv[fv["status"] == "optional"]
            status = "standard" if len(std) else "optional" if len(opt) else "not_listed"
            priced = opt.dropna(subset=["price_eur"]).sort_values("price_eur")
            cheapest = priced.iloc[0] if len(priced) and status == "optional" else None
            rows.append({"feature": feature, "model": model, "variant": v.variant, "engine": v.engine,
                         "status": status,
                         "price_min_eur": float(cheapest["price_eur"]) if cheapest is not None else None,
                         "price_item": cheapest["option_name"] if cheapest is not None else None,
                         "price_sa_code": cheapest["sa_code"] if cheapest is not None else None,
                         "price_page": int(cheapest["page"]) if cheapest is not None else None,
                         "via_package": bool(cheapest["via_package"]) if cheapest is not None else None,
                         "standard_item": std["option_name"].iloc[0] if len(std) else None,
                         "standard_page": int(std["page"].iloc[0]) if len(std) else None,
                         "base_price_eur": v.base_price_eur})
    return pd.DataFrame(rows)


def fitment_summary(fv: pd.DataFrame, keys=("feature", "model")) -> pd.DataFrame:
    """Collapse variant-level fitment to a tier per (feature, model[, engine])."""
    keys = list(keys)

    def agg(g):
        n = len(g)
        n_std = int((g["status"] == "standard").sum())
        n_opt = int((g["status"] == "optional").sum())
        tier = ("standard_all" if n_std == n else "standard_some" if n_std > 0
                else "optional" if n_opt > 0 else "not_listed")
        price = g["price_min_eur"].dropna()
        base = g["base_price_eur"].dropna()
        cheapest = g.loc[price.idxmin()] if len(price) else None
        return pd.Series({"n_variants": n, "n_standard": n_std, "n_optional": n_opt, "tier": tier,
                          "price_item": cheapest["price_item"] if cheapest is not None else None,
                          "price_sa_code": cheapest["price_sa_code"] if cheapest is not None else None,
                          "price_via_package": bool(cheapest["via_package"]) if cheapest is not None else None,
                          "share_standard": n_std / n, "share_offered": (n_std + n_opt) / n,
                          "price_min_eur": float(price.min()) if len(price) else None,
                          "price_max_eur": float(price.max()) if len(price) else None,
                          "price_pct_of_base": float((g["price_min_eur"] / g["base_price_eur"]).min() * 100)
                          if len(price) and len(base) else None})
    return fv.groupby(keys).apply(agg, include_groups=False).reset_index()


def spec_context(cat: dict) -> pd.DataFrame:
    """Feature -> technical-data rows (verbatim values, per variant) via taxonomy.FEATURE_TO_SPECS."""
    from . import taxonomy

    tech = cat["technical"]
    rows = []
    for feature, keys in taxonomy.FEATURE_TO_SPECS.items():
        t = tech[tech["attribute_key"].isin(keys)]
        for r in t.itertuples():
            rows.append({"feature": feature, "model": r.model, "variant": r.variant, "attribute": r.attribute,
                         "value": r.value, "value_min": r.value_min, "value_max": r.value_max, "page": r.page})
    return pd.DataFrame(rows)
