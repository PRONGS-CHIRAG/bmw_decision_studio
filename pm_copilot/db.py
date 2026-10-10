"""Requirement store + append-only audit trail (SQLite).

Requirements keep two layers: `computed` (rewritten by every pipeline run) and
`overrides` (PM edits, never touched by the pipeline). The effective requirement
is computed merged with overrides. Every change - pipeline or human - is written
to audit_log with actor, timestamp, old/new value and rationale.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,
    derivative TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    computed TEXT NOT NULL,
    overrides TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    actor_type TEXT NOT NULL,          -- system | ai | pm
    action TEXT NOT NULL,
    requirement_id TEXT,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    rationale TEXT
);
CREATE INDEX IF NOT EXISTS audit_req ON audit_log(requirement_id);
"""

STATUSES = ("Proposed", "Approved", "Rejected", "Changes requested", "Obsolete")
EDITABLE = ("title", "description", "acceptance_criteria", "priority_override", "tier_override", "owner_note")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _dump(v) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)


def log(con, actor: str, actor_type: str, action: str, requirement_id: str | None = None, field: str | None = None,
        old=None, new=None, rationale: str | None = None) -> None:
    con.execute("INSERT INTO audit_log (ts, actor, actor_type, action, requirement_id, field, old_value, new_value, "
                "rationale) VALUES (?,?,?,?,?,?,?,?,?)",
                (now(), actor, actor_type, action, requirement_id, field, _dump(old), _dump(new), rationale))


def effective(row: sqlite3.Row) -> dict:
    req = json.loads(row["computed"])
    overrides = json.loads(row["overrides"])
    req.update({k: v for k, v in overrides.items() if k in ("title", "description", "acceptance_criteria",
                                                             "owner_note")})
    if "priority_override" in overrides:
        req["priority"] = {**req["priority"], "score": float(overrides["priority_override"]), "overridden": True}
    if "tier_override" in overrides:
        req["priority"] = {**req["priority"], "tier": overrides["tier_override"], "overridden": True}
    req.update({"status": row["status"], "version": row["version"], "created_at": row["created_at"],
                "updated_at": row["updated_at"], "overrides": overrides})
    return req


def get(con, req_id: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM requirements WHERE id = ?", (req_id,)).fetchone()


def all_rows(con) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM requirements").fetchall()


def upsert_computed(con, req: dict, actor: str = "pipeline", actor_type: str = "ai") -> str:
    """Insert a new pipeline requirement or refresh its computed layer; returns what happened."""
    row = get(con, req["id"])
    payload = json.dumps(req, ensure_ascii=False, default=str)
    if row is None:
        con.execute("INSERT INTO requirements (id, derivative, type, status, computed, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?)", (req["id"], req["derivative"], req["type"], "Proposed", payload,
                                               now(), now()))
        log(con, actor, actor_type, "created", req["id"], new={"title": req["title"], "score": req["priority"]["score"],
                                                               "tier": req["priority"]["tier"]},
            rationale=f"Derived from {req['evidence_summary']['verbatims']} verbatims; {req['priority_rationale']}")
        return "created"
    old = json.loads(row["computed"])
    changes = {}
    for key, getter in (("score", lambda r: r["priority"]["score"]), ("tier", lambda r: r["priority"]["tier"]),
                        ("evidence", lambda r: r["evidence"]["level"]),
                        ("verbatims", lambda r: r["evidence_summary"]["verbatims"])):
        if getter(old) != getter(req):
            changes[key] = (getter(old), getter(req))
    status = row["status"]
    if status == "Obsolete":  # signal is back
        status = "Proposed"
        log(con, actor, actor_type, "reactivated", req["id"], "status", "Obsolete", "Proposed",
            "Signal present again after data refresh.")
    con.execute("UPDATE requirements SET computed = ?, status = ?, updated_at = ?, version = version + ? WHERE id = ?",
                (payload, status, now(), 1 if changes else 0, req["id"]))
    for key, (a, b) in changes.items():
        log(con, actor, actor_type, "rescored" if key in ("score", "tier") else "evidence_updated", req["id"], key,
            a, b, "Recomputed from refreshed data / weights.")
    return "updated" if changes else "unchanged"


def mark_obsolete(con, keep_ids: set[str], derivative_types: set[tuple[str, str]]) -> int:
    n = 0
    for row in all_rows(con):
        if (row["derivative"], row["type"]) in derivative_types and row["id"] not in keep_ids \
                and row["status"] == "Proposed":
            con.execute("UPDATE requirements SET status = 'Obsolete', updated_at = ? WHERE id = ?", (now(), row["id"]))
            log(con, "pipeline", "ai", "obsoleted", row["id"], "status", "Proposed", "Obsolete",
                "No longer meets the candidate thresholds after data refresh.")
            n += 1
    return n


def decide(con, req_id: str, status: str, actor: str, rationale: str) -> dict:
    row = get(con, req_id)
    if row is None:
        raise KeyError(req_id)
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status}")
    con.execute("UPDATE requirements SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                (status, now(), req_id))
    log(con, actor, "pm", "decision", req_id, "status", row["status"], status, rationale)
    return effective(get(con, req_id))


def edit(con, req_id: str, changes: dict, actor: str, rationale: str) -> dict:
    row = get(con, req_id)
    if row is None:
        raise KeyError(req_id)
    overrides = json.loads(row["overrides"])
    current = effective(row)
    for field, value in changes.items():
        if field not in EDITABLE:
            raise ValueError(f"Field '{field}' is not editable")
        old = overrides.get(field, current.get(field) if field in ("title", "description", "acceptance_criteria")
                            else None)
        if value in (None, ""):
            overrides.pop(field, None)
        else:
            overrides[field] = value
        log(con, actor, "pm", "edited", req_id, field, old, value, rationale)
    con.execute("UPDATE requirements SET overrides = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                (json.dumps(overrides, ensure_ascii=False), now(), req_id))
    return effective(get(con, req_id))


def audit(con, requirement_id: str | None = None, limit: int = 500) -> list[dict]:
    if requirement_id:
        rows = con.execute("SELECT * FROM audit_log WHERE requirement_id = ? ORDER BY seq DESC LIMIT ?",
                           (requirement_id, limit)).fetchall()
    else:
        rows = con.execute("SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("old_value", "new_value"):
            try:
                d[k] = json.loads(d[k]) if d[k] else d[k]
            except (TypeError, json.JSONDecodeError):
                pass
        out.append(d)
    return out
