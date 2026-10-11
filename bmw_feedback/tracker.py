"""Decision tracker: every recorded decision, its lifecycle, and whether the market has moved since.

    decision (data/decisions.jsonl)          what the PM decided, with the system's recommendation at the time
    events   (data/decision_events.jsonl)    append-only: lifecycle status changes and reviews
    today    = DecisionEngine.evaluate(feature, the decision's own stored policy, its scope) on the current data
    baseline = the snapshot of the latest review, else the snapshot stored with the decision
    changes  = detect_changes(baseline, today): recommendation, score, overall score, rival equipment

The decision log is never rewritten; a review stores today's values as the new baseline in an event.
"""

import hashlib
import json
import re

import pandas as pd

from . import config
from .decision import MARKET_NAMES, PolicyError

STATUSES = ["Decided", "In development", "Launched", "Dropped"]
EVENT_TYPES = ("status", "reviewed")
CHANGE_THRESHOLD = 0.05
NO_RECOMMENDATION = ("Not sold", "Insufficient evidence")


def events_path():
    return config.ROOT / "data" / "decision_events.jsonl"


# ---------------------------------------------------------------------- snapshots
def snapshot_from_feature(fr: dict, competitor_data_hash: str | None = None) -> dict:
    """The comparable part of one evaluated feature: per cell recommendation, score, signal scores, rival statuses."""
    cells = []
    for c in fr["cells"]:
        sig = c.get("signals") or {}
        cp = sig.get("competitors") or {}
        rivals = None
        if cp.get("rivals"):
            rivals = {"item": cp["item"], "item_label": cp["item_label"],
                      "statuses": {r["model_id"]: r["status"] for r in cp["rivals"]},
                      "names": {r["model_id"]: r["name"] for r in cp["rivals"]}}
        cells.append({"model": c["model"], "market": c["market"], "recommendation": c["recommendation"],
                      "score": c.get("score"), "signals": {k: v.get("score") for k, v in sig.items()},
                      "rivals": rivals})
    return {"rollup_score": fr["rollup"]["score"], "cells": cells, "competitor_data_hash": competitor_data_hash}


def baseline(decision: dict, events: list) -> tuple[dict, dict]:
    """(snapshot, where it comes from): the latest review of this decision, else what was stored with it."""
    reviews = [e for e in events if e.get("type") == "reviewed" and e.get("decision_id") == decision["id"]]
    if reviews:
        r = max(reviews, key=lambda e: e["recorded_at"])
        return r["snapshot"], {"kind": "reviewed", "pm": r["pm"], "recorded_at": r["recorded_at"], "note": r["note"]}
    source = {"kind": "decision", "pm": decision.get("pm"), "recorded_at": decision.get("recorded_at")}
    if decision.get("snapshot"):
        return decision["snapshot"], source
    sr = decision.get("system_recommendation") or {}
    cells = [{"model": c["model"], "market": c["market"], "recommendation": c.get("recommendation"),
              "score": c.get("score"), "signals": {}, "rivals": None} for c in sr.get("cells", [])]
    return {"rollup_score": sr.get("rollup_score"), "cells": cells, "competitor_data_hash": None}, source


def scope(decision: dict) -> dict:
    """Series and markets the decision covered (stored, or read from its recommendation cells)."""
    if decision.get("scope"):
        return {"models": list(decision["scope"].get("models") or []),
                "markets": list(decision["scope"].get("markets") or [])}
    cells = (decision.get("system_recommendation") or {}).get("cells", [])
    return {"models": list(dict.fromkeys(c["model"] for c in cells)),
            "markets": list(dict.fromkeys(c["market"] for c in cells))}


# ---------------------------------------------------------------------- changes
def _where(c: dict) -> str:
    name = config.MODEL_NAMES.get(c["model"], c["model"]).split(" (")[0]
    return f"{name} {MARKET_NAMES.get(c['market'], c['market'])}"


def _moved(a, b, threshold) -> bool:
    return a is not None and b is not None and round(abs(b - a), 3) >= threshold - 1e-9


def detect_changes(base: dict, today: dict, threshold: float = CHANGE_THRESHOLD) -> list[dict]:
    """What differs between two snapshots, in plain words. Pure."""
    out = []
    now = {(c["model"], c["market"]): c for c in today.get("cells", [])}
    for b in base.get("cells", []):
        t = now.get((b["model"], b["market"]))
        if t is None:
            continue
        key = {"model": b["model"], "market": b["market"]}
        if b.get("recommendation") != t.get("recommendation"):
            out.append({"type": "recommendation", **key, "before": b.get("recommendation"),
                        "after": t.get("recommendation"),
                        "text": f"{_where(b)}: {b.get('recommendation')} -> {t.get('recommendation')}."})
        elif b.get("recommendation") not in NO_RECOMMENDATION and _moved(b.get("score"), t.get("score"), threshold):
            out.append({"type": "score", **key, "before": b["score"], "after": t["score"],
                        "text": f"{_where(b)}: priority score {b['score']:.2f} -> {t['score']:.2f}."})
        br, tr = b.get("rivals"), t.get("rivals")
        if br and tr and br.get("item") == tr.get("item"):
            for mid, before in br["statuses"].items():
                after = tr["statuses"].get(mid)
                if after is not None and after != before:
                    name = tr.get("names", {}).get(mid) or br.get("names", {}).get(mid) or mid
                    out.append({"type": "competitor", **key, "model_id": mid, "before": before, "after": after,
                                "text": f"{name}: {tr['item_label'].lower()} {before.replace('_', ' ')} -> "
                                        f"{after.replace('_', ' ')} (German equipment data)."})
    if _moved(base.get("rollup_score"), today.get("rollup_score"), threshold):
        out.append({"type": "rollup", "before": base["rollup_score"], "after": today["rollup_score"],
                    "text": f"Overall priority score {base['rollup_score']:.2f} -> {today['rollup_score']:.2f}."})
    return out


# ---------------------------------------------------------------------- lifecycle events
def lifecycle(decision_id: str, events: list) -> dict:
    history = [{k: e[k] for k in ("status", "pm", "note", "recorded_at", "id") if k in e}
               for e in events if e.get("type") == "status" and e.get("decision_id") == decision_id]
    return {"status": history[-1]["status"] if history else "Decided", "history": history}


def read_events() -> list:
    path = events_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def record_event(entry: dict, decision_ids: set) -> dict:
    """Validate and append one event. LookupError: unknown decision; ValueError: anything else invalid."""
    if entry.get("type") not in EVENT_TYPES:
        raise ValueError(f"event type must be one of {', '.join(EVENT_TYPES)}")
    if entry.get("decision_id") not in decision_ids:
        raise LookupError(f"no recorded decision {entry.get('decision_id')!r}")
    if not str(entry.get("pm") or "").strip():
        raise ValueError("a reviewer name is required")
    if len(str(entry.get("note") or "").strip()) < 3 or not re.search(r"\w", entry.get("note") or ""):
        raise ValueError("a note of at least 3 characters is required")
    if entry["type"] == "status" and entry.get("status") not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if entry["type"] == "reviewed" and not isinstance(entry.get("snapshot"), dict):
        raise ValueError("a review must store the snapshot it accepts")
    now = pd.Timestamp.now("UTC").isoformat()
    entry = {**entry, "pm": entry["pm"].strip(), "note": entry["note"].strip(), "recorded_at": now,
             "id": hashlib.sha256(json.dumps([entry, now], sort_keys=True, default=str).encode()).hexdigest()[:12]}
    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


# ---------------------------------------------------------------------- the tracker view
def today_snapshot(engine, decision: dict, competitor_data_hash: str | None) -> dict:
    """Recompute a decision with its own stored policy and scope on the current data."""
    if not decision.get("policy"):
        raise LookupError("no policy was stored with this decision, so it cannot be recomputed like for like")
    sc = scope(decision)
    res = engine.evaluate("", [decision["feature"]], decision.get("policy"), sc["models"] or None,
                          sc["markets"] or None)
    if not res["features"]:
        raise LookupError(f"'{decision['feature']}' is no longer a feature in the data")
    return snapshot_from_feature(res["features"][0], competitor_data_hash)


def view(engine, decisions: list, events: list, competitor_data_hash: str | None) -> dict:
    """Every decision (newest first) with lifecycle, baseline, today's values and what changed."""
    items = []
    for d in sorted(decisions, key=lambda d: d.get("recorded_at", ""), reverse=True):
        base, source = baseline(d, events)
        item = {"decision": d, "scope": scope(d), "lifecycle": lifecycle(d["id"], events),
                "baseline": {**base, "source": source}}
        try:
            today = today_snapshot(engine, d, competitor_data_hash)
        except (LookupError, PolicyError, KeyError) as e:
            items.append({**item, "status": "cannot_recompute", "reason": str(e).strip("'\""), "today": None,
                          "changes": [], "needs_review": False})
            continue
        changes = detect_changes(base, today)
        items.append({**item, "status": "ok", "today": today, "changes": changes, "needs_review": bool(changes)})
    return {"decisions": items, "n_needs_review": sum(i["needs_review"] for i in items),
            "competitor_data_hash": competitor_data_hash}
