"""Append-only SQLite storage for frozen decision runs and explicit PM events.

These new tables coexist with the older application's tables. No migration edits,
replaces or drops existing requirements. The complete supplied run (including its
evidence snapshot when attached by the server) is serialized and hashed once.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .decision_core import canonical_json, content_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_runs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    parent_run_id TEXT REFERENCES decision_runs(id),
    input_hash TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    snapshot TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decision_runs_project ON decision_runs(project_id, seq);
CREATE TABLE IF NOT EXISTS decision_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL REFERENCES decision_runs(id),
    portfolio_id TEXT,
    action TEXT NOT NULL CHECK(action IN ('approved','rejected','revision_requested')),
    reviewer TEXT NOT NULL CHECK(length(trim(reviewer)) > 0),
    rationale TEXT NOT NULL CHECK(length(trim(rationale)) > 0),
    acknowledged_assumptions INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decision_events_run ON decision_events(run_id, seq);
CREATE TRIGGER IF NOT EXISTS decision_runs_no_update BEFORE UPDATE ON decision_runs
BEGIN SELECT RAISE(ABORT, 'decision_runs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS decision_runs_no_delete BEFORE DELETE ON decision_runs
BEGIN SELECT RAISE(ABORT, 'decision_runs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS decision_events_no_update BEFORE UPDATE ON decision_events
BEGIN SELECT RAISE(ABORT, 'decision_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS decision_events_no_delete BEFORE DELETE ON decision_events
BEGIN SELECT RAISE(ABORT, 'decision_events is append-only'); END;
"""

ACTIONS = {
    "approve": "approved", "approved": "approved",
    "reject": "rejected", "rejected": "rejected",
    "request revision": "revision_requested", "request_revision": "revision_requested",
    "revision_requested": "revision_requested", "changes requested": "revision_requested",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        raise ValueError("Limit must be an integer from 1 to 1000")
    return value


def _run(row) -> dict:
    if row is None:
        raise KeyError("Decision run does not exist")
    result = json.loads(row["snapshot"])
    if content_hash(result) != row["snapshot_hash"]:
        raise ValueError("Stored decision snapshot failed its integrity check")
    return {**result, "id": row["id"], "run_id": row["id"], "project_id": row["project_id"],
            "created_at": row["created_at"], "parent_run_id": row["parent_run_id"],
            "snapshot_hash": row["snapshot_hash"]}


def _event(row) -> dict:
    if row is None:
        raise KeyError("Decision event does not exist")
    result = dict(row)
    result["acknowledged_assumptions"] = bool(result["acknowledged_assumptions"])
    return result


class DecisionStore:
    def __init__(self, path: str | Path | None = None):
        if path is None:
            from .config import DB_PATH
            path = DB_PATH
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_run(self, run: dict, parent_run_id: str | None = None) -> dict:
        # Metadata belongs to this insertion, not to a previously loaded run.
        snapshot = {key: value for key, value in run.items() if key not in {
            "id", "run_id", "project_id", "created_at", "parent_run_id", "snapshot_hash",
        }}
        serialized = canonical_json(snapshot)
        project_id = snapshot.get("context", {}).get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("A stored run requires an explicit project_id in its context")
        if not snapshot.get("input_hash") or not snapshot.get("algorithm_version"):
            raise ValueError("A stored run requires input hashes and an algorithm version")
        identifier = "run-" + uuid4().hex
        with self._connect() as connection:
            if parent_run_id is not None:
                parent = connection.execute("SELECT project_id FROM decision_runs WHERE id = ?", (parent_run_id,)).fetchone()
                if parent is None:
                    raise KeyError("Parent decision run does not exist")
                if parent["project_id"] != project_id:
                    raise ValueError("A draft revision cannot change its parent project")
            connection.execute(
                "INSERT INTO decision_runs(id, project_id, created_at, parent_run_id, input_hash, snapshot_hash, snapshot) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (identifier, project_id, _now(), parent_run_id, snapshot["input_hash"], content_hash(snapshot), serialized),
            )
            return _run(connection.execute("SELECT * FROM decision_runs WHERE id = ?", (identifier,)).fetchone())

    def get_run(self, run_id: str) -> dict:
        with self._connect() as connection:
            return _run(connection.execute("SELECT * FROM decision_runs WHERE id = ?", (run_id,)).fetchone())

    def list_runs(self, project_id: str | None = None, limit: int = 50) -> list[dict]:
        limit = _limit(limit)
        with self._connect() as connection:
            where, parameters = ("WHERE project_id = ?", [project_id]) if project_id is not None else ("", [])
            rows = connection.execute(f"SELECT * FROM decision_runs {where} ORDER BY seq DESC LIMIT ?", [*parameters, limit]).fetchall()
            summaries = []
            for row in rows:
                run = _run(row)
                latest = connection.execute("SELECT * FROM decision_events WHERE run_id = ? ORDER BY seq DESC LIMIT 1", (row["id"],)).fetchone()
                summaries.append({key: run.get(key) for key in (
                    "id", "run_id", "project_id", "created_at", "parent_run_id", "input_hash",
                    "snapshot_hash", "algorithm_version", "context", "status",
                )} | {"latest_decision": _event(latest) if latest is not None else None})
            return summaries

    def latest_run(self, project_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM decision_runs WHERE project_id = ? ORDER BY seq DESC LIMIT 1", (project_id,)).fetchone()
            return None if row is None else _run(row)

    def decide(self, run_id: str, portfolio_id: str | None, action: str, reviewer: str,
               rationale: str, acknowledge_assumptions: bool = False) -> dict:
        if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("Every decision requires a reviewer name and rationale")
        normalized = ACTIONS.get(action.strip().lower()) if isinstance(action, str) else None
        if normalized is None:
            raise ValueError("Decision action must approve, reject or request revision")
        if not isinstance(acknowledge_assumptions, bool):
            raise ValueError("Assumption acknowledgement must be an explicit boolean")
        with self._connect() as connection:
            run = _run(connection.execute("SELECT * FROM decision_runs WHERE id = ?", (run_id,)).fetchone())
            portfolio = next((item for item in run.get("portfolios", []) if item["id"] == portfolio_id), None)
            if normalized == "approved" and run.get("status") != "ready":
                raise ValueError("Only a ready run with a feasible reviewed portfolio can be approved")
            if portfolio_id is not None and portfolio is None:
                raise ValueError("The selected portfolio does not belong to this frozen run")
            if normalized == "approved":
                if portfolio is None or portfolio.get("feasible") is not True:
                    raise ValueError("Approval requires a feasible portfolio from this frozen run")
                if not acknowledge_assumptions:
                    raise ValueError("Explicitly acknowledge the PM planning assumptions before approval")
            identifier = "decision-" + uuid4().hex
            connection.execute(
                "INSERT INTO decision_events(id, run_id, portfolio_id, action, reviewer, rationale, acknowledged_assumptions, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (identifier, run_id, portfolio_id, normalized, reviewer.strip(), rationale.strip(), int(acknowledge_assumptions), _now()),
            )
            return _event(connection.execute("SELECT * FROM decision_events WHERE id = ?", (identifier,)).fetchone())

    def get_decision(self, event_id: str) -> dict:
        with self._connect() as connection:
            return _event(connection.execute("SELECT * FROM decision_events WHERE id = ?", (event_id,)).fetchone())

    def history(self, project_id: str | None = None, run_id: str | None = None, limit: int = 100) -> list[dict]:
        clauses, parameters = [], []
        if project_id is not None:
            clauses.append("r.project_id = ?")
            parameters.append(project_id)
        if run_id is not None:
            clauses.append("e.run_id = ?")
            parameters.append(run_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT e.* FROM decision_events e JOIN decision_runs r ON r.id = e.run_id {where} ORDER BY e.seq DESC LIMIT ?",
                [*parameters, _limit(limit)],
            ).fetchall()
            return [_event(row) for row in rows]

    def get_history(self, project_id: str | None = None, run_id: str | None = None, limit: int = 100) -> list[dict]:
        return self.history(project_id=project_id, run_id=run_id, limit=limit)

    def export_decision(self, event_id: str) -> dict:
        event = self.get_decision(event_id)
        if event["action"] != "approved":
            raise ValueError("Only approved decisions can be exported as an approved planning package")
        run = self.get_run(event["run_id"])
        portfolio = next(item for item in run["portfolios"] if item["id"] == event["portfolio_id"])
        return {"decision": event, "run": run, "portfolio": portfolio,
                "label": "Approved planning decision; PM assumptions are preserved, not engineering certification"}
