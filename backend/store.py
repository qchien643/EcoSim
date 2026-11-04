"""SQLite persistence for the new ecoSim backend schema.

This module intentionally does not migrate the old experiment databases.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator
import uuid

from .contracts import issues_for


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def hash_json(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS persona_datasets (
    dataset_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    revision TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    usage_notice TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_name, revision)
);

CREATE TABLE IF NOT EXISTS industry_profiles (
    industry_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    bundle_hash TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(industry_id, profile_version)
);

CREATE TABLE IF NOT EXISTS persona_cohorts (
    cohort_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES persona_datasets(dataset_id),
    industry_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    size INTEGER NOT NULL CHECK(size > 0),
    content_hash TEXT NOT NULL,
    selection_policy_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(industry_id, profile_version)
        REFERENCES industry_profiles(industry_id, profile_version)
);

CREATE TABLE IF NOT EXISTS cohort_members (
    cohort_id TEXT NOT NULL REFERENCES persona_cohorts(cohort_id),
    cohort_persona_id TEXT NOT NULL,
    source_persona_id TEXT NOT NULL,
    persona_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    field_provenance_json TEXT NOT NULL,
    cohort_bucket TEXT,
    PRIMARY KEY(cohort_id, cohort_persona_id),
    UNIQUE(cohort_id, source_persona_id)
);

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    brief TEXT NOT NULL,
    internal_notes TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL CHECK(revision > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
    name TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    status TEXT NOT NULL CHECK(status IN ('draft', 'ready')),
    setup_json TEXT NOT NULL,
    frozen_snapshot_json TEXT,
    snapshot_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
    scenario_revision INTEGER NOT NULL,
    snapshot_hash TEXT NOT NULL,
    input_snapshot_json TEXT NOT NULL,
    execution_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ready', 'running', 'completed', 'failed')),
    execution_epoch INTEGER NOT NULL DEFAULT 0 CHECK(execution_epoch >= 0),
    failure_code TEXT,
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_sessions (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_no INTEGER NOT NULL CHECK(session_no > 0),
    session_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    snapshot_json TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    PRIMARY KEY(run_id, session_no)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','inactive')),
    PRIMARY KEY(run_id, session_id, agent_id),
    FOREIGN KEY(run_id, agent_id) REFERENCES run_agents(run_id, agent_id),
    FOREIGN KEY(session_id) REFERENCES run_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS run_agents (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    cohort_id TEXT NOT NULL,
    cohort_persona_id TEXT NOT NULL,
    source_persona_id TEXT NOT NULL,
    persona_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    field_provenance_json TEXT NOT NULL,
    PRIMARY KEY(run_id, agent_id),
    UNIQUE(run_id, ordinal),
    FOREIGN KEY(cohort_id, cohort_persona_id)
        REFERENCES cohort_members(cohort_id, cohort_persona_id)
);

CREATE TABLE IF NOT EXISTS run_agent_relationships (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_id TEXT NOT NULL,
    brand_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    current_state_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    last_event_id TEXT,
    PRIMARY KEY(run_id, agent_id, brand_id),
    FOREIGN KEY(run_id, agent_id) REFERENCES run_agents(run_id, agent_id)
);

CREATE TABLE IF NOT EXISTS run_updates (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    commit_seq INTEGER NOT NULL CHECK(commit_seq > 0),
    update_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(run_id, commit_seq)
);

CREATE TABLE IF NOT EXISTS stage_contexts (
    stage_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_id TEXT NOT NULL REFERENCES run_sessions(session_id),
    agent_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    encounter_no INTEGER NOT NULL,
    stage TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id, session_id, agent_id)
        REFERENCES agent_sessions(run_id, session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS model_calls (
    call_id TEXT PRIMARY KEY,
    stage_key TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    request_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    response_json TEXT,
    validation_status TEXT,
    status TEXT NOT NULL,
    error_code TEXT,
    event_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    elapsed_ms REAL,
    UNIQUE(stage_key, attempt_no)
);

CREATE TABLE IF NOT EXISTS stage_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    encounter_no INTEGER NOT NULL,
    stage TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    action TEXT,
    normalized_score REAL,
    parent_event_id TEXT REFERENCES stage_events(event_id),
    stage_key TEXT NOT NULL UNIQUE REFERENCES stage_contexts(stage_key),
    created_at TEXT NOT NULL,
    UNIQUE(run_id, session_id, agent_id, object_type, object_id, encounter_no, stage),
    UNIQUE(run_id, session_id, agent_id, sequence_no),
    FOREIGN KEY(run_id, session_id, agent_id)
        REFERENCES agent_sessions(run_id, session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS event_tags (
    event_id TEXT NOT NULL REFERENCES stage_events(event_id),
    tag_id TEXT NOT NULL,
    normalized_score REAL NOT NULL,
    rank INTEGER NOT NULL,
    selected INTEGER NOT NULL CHECK(selected IN (0, 1)),
    description TEXT NOT NULL,
    PRIMARY KEY(event_id, tag_id)
);

CREATE TABLE IF NOT EXISTS agent_stage_states (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    latest_event_id TEXT NOT NULL REFERENCES stage_events(event_id),
    PRIMARY KEY(run_id, agent_id, object_type, object_id, stage),
    FOREIGN KEY(run_id, agent_id) REFERENCES run_agents(run_id, agent_id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    cursor_json TEXT NOT NULL,
    last_event_id TEXT,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id, session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_id TEXT NOT NULL,
    session_no INTEGER NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    numerator REAL,
    denominator REAL,
    session_value REAL,
    cumulative_numerator REAL,
    cumulative_denominator REAL,
    cumulative_value REAL,
    calculation_version TEXT NOT NULL,
    PRIMARY KEY(run_id, session_id, scope_type, scope_id, metric_name,
                calculation_version)
);

CREATE TABLE IF NOT EXISTS session_metrics (
    session_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agents_processed INTEGER NOT NULL,
    posts_attended INTEGER NOT NULL,
    products_bought INTEGER NOT NULL,
    unresolved_stages INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cohort_members_cohort
    ON cohort_members(cohort_id, cohort_persona_id);
CREATE INDEX IF NOT EXISTS idx_runs_scenario
    ON runs(scenario_id, created_at);
CREATE INDEX IF NOT EXISTS idx_run_updates_stream
    ON run_updates(run_id, commit_seq);
CREATE INDEX IF NOT EXISTS idx_stage_events_agent
    ON stage_events(run_id, agent_id, session_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_model_calls_event
    ON model_calls(event_id, attempt_no, call_id);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_run
    ON runs((1)) WHERE status='running';
"""


class BackendValidationError(ValueError):
    def __init__(self, issues: list[dict[str, str]]):
        self.issues = issues
        super().__init__("; ".join(f"{i['path']}: {i['message']}" for i in issues))


class BackendConflictError(ValueError):
    pass


class BackendNotFoundError(ValueError):
    pass


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise BackendValidationError([{
            "path": field, "code": "REQUIRED_STRING",
            "message": "A non-empty string is required.",
        }])
    return value.strip()


def _text(value: Any, field: str, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise BackendValidationError([{
            "path": field, "code": "INVALID_TEXT",
            "message": "A non-empty text value is required.",
        }])
    return value


def _json_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BackendValidationError([{
            "path": field, "code": "OBJECT_REQUIRED",
            "message": "An object is required.",
        }])
    return deepcopy(value)


class BackendStore:
    """Owns the v1 backend schema and its short SQLite transactions."""

    def __init__(self, path: str | Path = ":memory:", *, check_same_thread=True):
        self.database_path = str(path)
        self.connection = sqlite3.connect(
            self.database_path, timeout=30, check_same_thread=check_same_thread)
        self.connection.row_factory = sqlite3.Row
        tables = {row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if tables:
            version = self.connection.execute(
                "SELECT value FROM schema_meta WHERE key='version'"
            ).fetchone() if "schema_meta" in tables else None
            if version is None or version[0] != "backend-v2":
                self.connection.close()
                raise BackendConflictError("Not a backend-v2 database; use a new database path")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self.connection.execute(
            "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('version', 'backend-v2')"
        )
        self.connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self.connection.in_transaction:
            yield self.connection
        else:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                yield self.connection

    def close(self) -> None:
        self.connection.close()

    def _fetchone(self, sql: str, values: tuple[Any, ...]) -> dict[str, Any] | None:
        row = self.connection.execute(sql, values).fetchone()
        return dict(row) if row else None

    def _run_session_id(self, run_id: str, session_no: int) -> str:
        run = self.get_run(run_id)
        for item in run["sessions"]:
            if item["session_no"] == session_no:
                return item.get("session_id") or f"{run_id}_session_{session_no}"
        raise BackendNotFoundError("Unknown run session")

    def sessions(self, run_id: str) -> list[dict[str, Any]]:
        run = self.get_run(run_id)
        result = []
        for row in run["sessions"]:
            item = dict(row)
            item["snapshot"] = json.loads(item.pop("snapshot_json"))
            item["session_id"] = item["snapshot"].get(
                "session_id", f"{run_id}_session_{item['session_no']}"
            )
            item["posts"] = deepcopy(item["snapshot"].get("posts", []))
            item["active_agents"] = item["snapshot"].get(
                "active_agents", item["snapshot"].get("active_agent_ids")
            )
            result.append(item)
        return result

    def session(self, session_id: str) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM run_sessions WHERE session_id=?", (session_id,)
        )

    def _run_ids(self) -> list[str]:
        return [row["run_id"] for row in self.connection.execute(
            "SELECT run_id FROM runs ORDER BY created_at"
        ).fetchall()]

    def set_session_status(self, session_id: str, status: str) -> None:
        allowed = {"pending", "running", "completed", "failed"}
        if status not in allowed:
            raise BackendValidationError([{
                "path": "session.status", "code": "INVALID_STATUS",
                "message": "Unknown session status.",
            }])
        with self.transaction() as db:
            row = self.session(session_id)
            if row is None:
                raise BackendNotFoundError("Unknown run session")
            db.execute(
                "UPDATE run_sessions SET status=?, started_at=CASE "
                "WHEN ?='running' AND started_at IS NULL THEN ? ELSE started_at END, "
                "ended_at=CASE WHEN ? IN ('completed','failed') THEN ? ELSE ended_at END "
                "WHERE run_id=? AND session_no=?",
                (status, status, now(), status, now(), row["run_id"], row["session_no"]),
            )

    def agents(self, run_id: str) -> list[dict[str, Any]]:
        return self.run_agents(run_id)

    def posts(self, run_id: str, session_id: str) -> list[dict[str, Any]]:
        snapshot = self.run_snapshot(run_id)
        session = next(
            (item for item in snapshot["sessions"]
             if item["session_id"] == session_id), None
        )
        if session is None:
            raise BackendNotFoundError("Unknown run session")
        indexed = {item["post_id"]: item for item in snapshot["posts"]}
        result = []
        for scheduled in sorted(session.get("posts", []), key=lambda x: x["position"]):
            post = deepcopy(indexed[scheduled["post_id"]])
            post["position"] = scheduled["position"]
            result.append(post)
        return result

    def products(self, run_id: str, shop_id: str) -> list[dict[str, Any]]:
        snapshot = self.run_snapshot(run_id)
        return sorted(
            [deepcopy(item) for item in snapshot["products"]
             if item.get("shop_id") == shop_id],
            key=lambda item: item.get("position", 0),
        )

    def stage_key(self, run_id: str, session_id: str, agent_id: str,
                  object_type: str, object_id: str, encounter_no: int,
                  stage: str) -> str:
        return "|".join(map(str, (
            run_id, session_id, agent_id, object_type, object_id,
            encounter_no, stage,
        )))

    def context_snapshot(self, stage_key: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT snapshot_json FROM stage_contexts WHERE stage_key=?",
            (stage_key,),
        )
        return json.loads(row["snapshot_json"]) if row else None

    def save_context(self, stage_key: str, run_id: str,
                     snapshot: dict[str, Any]) -> None:
        serialized = dumps(snapshot)
        with self.transaction() as db:
            existing = db.execute(
                "SELECT snapshot_json FROM stage_contexts WHERE stage_key=?",
                (stage_key,),
            ).fetchone()
            if existing is not None:
                if existing["snapshot_json"] != serialized:
                    raise BackendConflictError("Conflicting context for stage key")
                return
            input_data = snapshot["input"]
            key_parts = stage_key.split("|")
            if len(key_parts) != 7:
                raise BackendValidationError([{
                    "path": "stage_key", "code": "INVALID_STAGE_KEY",
                    "message": "Stage key has an invalid shape.",
                }])
            db.execute(
                "INSERT INTO stage_contexts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    stage_key, run_id, key_parts[1],
                    input_data["scope"]["agent_id"], input_data["scope"]["object_type"],
                    input_data["scope"]["object_id"], input_data["encounter_no"],
                    input_data["stage"], serialized, now(),
                ),
            )

    def history_watermark(self, run_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(rowid), 0) AS watermark FROM stage_events "
            "WHERE run_id=?", (run_id,)
        ).fetchone()
        return int(row["watermark"])

    def history_before(self, run_id: str, agent_id: str,
                       watermark: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM stage_events WHERE run_id=? AND agent_id=? "
            "AND rowid<=? ORDER BY rowid", (run_id, agent_id, watermark)
        ).fetchall()
        return [dict(row) for row in rows]

    def events_until_session(self, run_id: str, session_no: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT e.*, mc.response_json AS model_response_json "
            "FROM stage_events e "
            "JOIN run_sessions s ON s.run_id=e.run_id AND s.session_id=e.session_id "
            "LEFT JOIN model_calls mc ON mc.event_id=e.event_id "
            "WHERE e.run_id=? AND s.session_no<=? "
            "ORDER BY s.session_no, e.agent_id, e.sequence_no",
            (run_id, session_no),
        ).fetchall()
        events = {row["event_id"]: {**dict(row), "tags": []} for row in rows}
        if not events:
            return []
        tag_rows = self.connection.execute(
            "SELECT t.* FROM event_tags t JOIN stage_events e ON e.event_id=t.event_id "
            "JOIN run_sessions s ON s.session_id=e.session_id "
            "WHERE e.run_id=? AND s.session_no<=? ORDER BY t.rank",
            (run_id, session_no),
        ).fetchall()
        for tag in tag_rows:
            events[tag["event_id"]]["tags"].append(dict(tag))
        return list(events.values())

    def events_for_agent(self, run_id: str, agent_id: str, *,
                         session_no: int | None = None,
                         object_type: str | None = None,
                         object_id: str | None = None,
                         stage: str | None = None) -> list[dict[str, Any]]:
        clauses = ["e.run_id=?", "e.agent_id=?"]
        values: list[Any] = [run_id, agent_id]
        if session_no is not None:
            clauses.append("s.session_no=?")
            values.append(session_no)
        if object_type is not None:
            clauses.append("e.object_type=?")
            values.append(object_type)
        if object_id is not None:
            clauses.append("e.object_id=?")
            values.append(object_id)
        if stage is not None:
            clauses.append("e.stage=?")
            values.append(stage)
        rows = self.connection.execute(
            "SELECT e.*, mc.response_json AS model_response_json "
            "FROM stage_events e "
            "JOIN run_sessions s ON s.run_id=e.run_id AND s.session_id=e.session_id "
            "LEFT JOIN model_calls mc ON mc.event_id=e.event_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY s.session_no, e.sequence_no",
            values,
        ).fetchall()
        events = {row["event_id"]: {**dict(row), "tags": []} for row in rows}
        if not events:
            return []
        placeholders = ",".join("?" for _ in events)
        tag_rows = self.connection.execute(
            "SELECT t.* FROM event_tags t "
            f"WHERE t.event_id IN ({placeholders}) ORDER BY t.rank",
            tuple(events),
        ).fetchall()
        for tag in tag_rows:
            events[tag["event_id"]]["tags"].append(dict(tag))
        return list(events.values())

    def recent_events(self, run_id: str, limit: int = 20) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise BackendValidationError([{
                "path": "limit", "code": "INVALID_LIMIT",
                "message": "limit must be 1..200.",
            }])
        self.get_run(run_id)
        rows = self.connection.execute(
            "SELECT e.*, mc.response_json AS model_response_json "
            "FROM stage_events e "
            "LEFT JOIN model_calls mc ON mc.event_id=e.event_id "
            "WHERE e.run_id=? ORDER BY e.rowid DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()
        events = {row["event_id"]: {**dict(row), "tags": []} for row in rows}
        if not events:
            return []
        placeholders = ",".join("?" for _ in events)
        tag_rows = self.connection.execute(
            "SELECT t.* FROM event_tags t JOIN stage_events e ON e.event_id=t.event_id "
            f"WHERE e.run_id=? AND t.event_id IN ({placeholders}) "
            "ORDER BY e.rowid DESC, t.rank",
            (run_id, *events),
        ).fetchall()
        for tag in tag_rows:
            events[tag["event_id"]]["tags"].append(dict(tag))
        return list(reversed(list(events.values())))

    def save_session_projection(self, run_id: str, session_id: str,
                                snapshots: list[dict[str, Any]],
                                summary: dict[str, int], *, complete: bool) -> None:
        session = self.session(session_id)
        if session is None or session["run_id"] != run_id:
            raise BackendNotFoundError("Unknown run session")
        with self.transaction() as db:
            if complete and db.execute(
                "SELECT 1 FROM agent_sessions WHERE run_id=? AND session_id=? "
                "AND status NOT IN ('completed','inactive') LIMIT 1",
                (run_id, session_id),
            ).fetchone():
                raise BackendConflictError("Session still has unfinished agents")
            for item in snapshots:
                db.execute(
                    """
                    INSERT INTO metric_snapshots (
                        run_id, session_id, session_no, scope_type, scope_id,
                        metric_name, numerator, denominator, session_value,
                        cumulative_numerator, cumulative_denominator,
                        cumulative_value, calculation_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, session_id, scope_type, scope_id, metric_name,
                                calculation_version)
                    DO UPDATE SET numerator=excluded.numerator,
                        denominator=excluded.denominator,
                        session_value=excluded.session_value,
                        cumulative_numerator=excluded.cumulative_numerator,
                        cumulative_denominator=excluded.cumulative_denominator,
                        cumulative_value=excluded.cumulative_value
                    """,
                    (
                        item["run_id"], item["session_id"], item["session_no"],
                        item["scope_type"], item["scope_id"], item["metric_name"],
                        item["numerator"], item["denominator"], item["session_value"],
                        item["cumulative_numerator"], item["cumulative_denominator"],
                        item["cumulative_value"], item["calculation_version"],
                    ),
                )
            db.execute(
                """
                INSERT INTO session_metrics
                    (session_id, run_id, agents_processed, posts_attended,
                     products_bought, unresolved_stages)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agents_processed=excluded.agents_processed,
                    posts_attended=excluded.posts_attended,
                    products_bought=excluded.products_bought,
                    unresolved_stages=excluded.unresolved_stages
                """,
                (
                    session_id, run_id, summary["agents_processed"],
                    summary["posts_attended"], summary["products_bought"],
                    summary["unresolved_stages"],
                ),
            )
            if complete and session["status"] != "completed":
                db.execute(
                    "UPDATE run_sessions SET status='completed', ended_at=? "
                    "WHERE run_id=? AND session_no=?",
                    (now(), run_id, session["session_no"]),
                )
                self._append_update(
                    db, run_id, "session_completed",
                    {"session_no": session["session_no"], "metrics_ready": True},
                )

    def metric_snapshots(self, run_id: str, calculation_version: str,
                         session_id: str | None = None,
                         metric_name: str | None = None) -> list[dict[str, Any]]:
        clauses = ["run_id=?", "calculation_version=?"]
        values: list[Any] = [run_id, calculation_version]
        if session_id is not None:
            clauses.append("session_id=?")
            values.append(session_id)
        if metric_name is not None:
            clauses.append("metric_name=?")
            values.append(metric_name)
        rows = self.connection.execute(
            "SELECT * FROM metric_snapshots WHERE " + " AND ".join(clauses) +
            " ORDER BY session_no, metric_name", values,
        ).fetchall()
        return [dict(row) for row in rows]

    def model_usage(self, run_id: str) -> dict[str, Any]:
        rows = self.connection.execute(
            "SELECT m.response_json FROM model_calls m JOIN stage_contexts c "
            "ON (m.stage_key=c.stage_key OR m.stage_key=c.stage_key || '#fallback') "
            "WHERE c.run_id=? ORDER BY m.created_at", (run_id,)
        ).fetchall()
        result = {
            "attempts": len(rows), "usage_records": 0,
            "input_tokens": None, "output_tokens": None, "total_tokens": None,
        }
        for row in rows:
            payload = json.loads(row["response_json"] or "{}")
            usage = payload.get("usage")
            if not isinstance(usage, dict):
                continue
            result["usage_records"] += 1
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                if type(usage.get(key)) is int and usage[key] >= 0:
                    result[key] = (result[key] or 0) + usage[key]
        result["usage_missing_attempts"] = result["attempts"] - result["usage_records"]
        return result

    def event(self, event_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM stage_events WHERE event_id=?", (event_id,)
        )
        return row

    def event_by_key(self, stage_key: str) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM stage_events WHERE stage_key=?", (stage_key,)
        )

    def event_state(self, event_id: str | None) -> dict[str, Any] | None:
        if event_id is None:
            return None
        row = self.event(event_id)
        if row is None:
            return None
        tags = self.connection.execute(
            "SELECT tag_id, normalized_score, rank "
            "FROM event_tags WHERE event_id=? AND selected=1 ORDER BY rank",
            (event_id,),
        ).fetchall()
        return {
            "run_id": row["run_id"], "agent_id": row["agent_id"],
            "object_type": row["object_type"], "object_id": row["object_id"],
            "stage": row["stage"], "encounter_no": row["encounter_no"],
            "status": row["status"], "score": row["normalized_score"],
            "action": row["action"], "tags": [dict(item) for item in tags],
        }

    def relationship(self, run_id: str, agent_id: str,
                     organization_id: str, brand_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM run_agent_relationships "
            "WHERE run_id=? AND agent_id=? AND organization_id=? AND brand_id=?",
            (run_id, agent_id, organization_id, brand_id),
        )
        if row is None:
            return None
        return {
            "run_id": row["run_id"], "agent_id": row["agent_id"],
            "organization_id": row["organization_id"], "brand_id": row["brand_id"],
            "group_id": row["group_id"],
            "initial_state": json.loads(row["state_json"]),
            "state": json.loads(row["current_state_json"]),
            "provenance": json.loads(row["provenance_json"]),
            "last_event_id": row["last_event_id"],
        }

    def next_encounter(self, run_id: str, agent_id: str,
                       object_type: str, object_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(encounter_no), 0) + 1 AS next_no "
            "FROM stage_events WHERE run_id=? AND agent_id=? "
            "AND object_type=? AND object_id=?",
            (run_id, agent_id, object_type, object_id),
        ).fetchone()
        return int(row["next_no"])

    def encounter(self, run_id: str, session_id: str, agent_id: str,
                  object_type: str, object_id: str, parent_event_id: str | None) -> int:
        """Reuse a reserved context after failure; count actual agent encounters."""
        rows = self.connection.execute(
            "SELECT encounter_no,snapshot_json FROM stage_contexts WHERE run_id=? "
            "AND session_id=? AND agent_id=? AND object_type=? AND object_id=? "
            "AND stage IN ('A1','B1') ORDER BY encounter_no",
            (run_id, session_id, agent_id, object_type, object_id),
        )
        for row in rows:
            if json.loads(row["snapshot_json"])["parent_event_id"] == parent_event_id:
                return row["encounter_no"]
        return self.next_encounter(run_id, agent_id, object_type, object_id)

    def agent_session_status(self, run_id, session_id, agent_id, status=None):
        with self.transaction() as db:
            row = db.execute(
                "SELECT status FROM agent_sessions WHERE run_id=? AND session_id=? AND agent_id=?",
                (run_id, session_id, agent_id),
            ).fetchone()
            if row is None:
                raise BackendNotFoundError("Unknown agent-session")
            if status is not None:
                db.execute(
                    "UPDATE agent_sessions SET status=? WHERE run_id=? AND session_id=? AND agent_id=?",
                    (status, run_id, session_id, agent_id),
                )
            return row["status"] if status is None else status

    def completed_agents(self, run_id, session_id):
        return self.connection.execute(
            "SELECT COUNT(*) FROM agent_sessions WHERE run_id=? AND session_id=? AND status='completed'",
            (run_id, session_id),
        ).fetchone()[0]

    def shop_encounter(self, run_id: str, session_id: str,
                       post_position: int, shop_id: str) -> int:
        session = self.session(session_id)
        if session is None:
            raise BackendNotFoundError("Unknown run session")
        snapshot = self.run_snapshot(run_id)
        current = session["session_no"]
        return sum(
            1 for item in snapshot["sessions"]
            if item["session_no"] < current or item["session_no"] == current
            for scheduled in item.get("posts", [])
            if item["session_no"] < current or scheduled["position"] <= post_position
            if next((p for p in snapshot["posts"]
                     if p["post_id"] == scheduled["post_id"]), {}).get("shop_id") == shop_id
        )

    def start_model_call(self, stage_key: str, request: dict[str, Any],
                         provider: str, model: str) -> tuple[str, int]:
        with self.transaction() as db:
            row = db.execute(
                "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS next_no "
                "FROM model_calls WHERE stage_key=?", (stage_key,)
            ).fetchone()
            attempt = int(row["next_no"])
            call_id = str(uuid.uuid4())
            timestamp = now()
            db.execute(
                "INSERT INTO model_calls VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, "
                "'started', NULL, NULL, ?, ?, NULL)",
                (call_id, stage_key, attempt, provider, model, dumps(request),
                 hash_json(request), timestamp, timestamp),
            )
            return call_id, attempt

    def model_response(self, stage_key, request, provider, model):
        row = self._fetchone(
            "SELECT * FROM model_calls WHERE stage_key=? AND status='responded' "
            "ORDER BY attempt_no DESC LIMIT 1", (stage_key,),
        )
        if row is None:
            return None
        if row["input_hash"] != hash_json(request):
            raise BackendConflictError("Input changed for an existing model response")
        if row["provider"] != provider or row["model"] != model:
            raise BackendConflictError("Provider changed; create a new run")
        return {**row, "output": json.loads(row["response_json"])}

    def set_model_identity(self, call_id: str, provider: str, model: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE model_calls SET provider=?, model=?, updated_at=? WHERE call_id=?",
                (provider, model, now(), call_id),
            )

    def commit_model_attempt(self, call_id: str, response: dict[str, Any],
                             validation_status: str, elapsed_ms=None) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE model_calls SET response_json=?, validation_status=?, "
                "status='responded', updated_at=?, elapsed_ms=? WHERE call_id=?",
                (dumps(response), validation_status, now(), elapsed_ms, call_id),
            )

    def fail_model_attempt(self, call_id: str, error_code: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE model_calls SET error_code=?, status='failed', updated_at=? "
                "WHERE call_id=?", (error_code, now(), call_id),
            )

    def _relationship_for_object(self, run_id: str, agent_id: str,
                                 object_type: str, object_id: str) -> dict[str, Any] | None:
        snapshot = self.run_snapshot(run_id)
        collection = snapshot["posts"] if object_type == "article" else snapshot["products"]
        key = "post_id" if object_type == "article" else "product_id"
        obj = next((item for item in collection if item.get(key) == object_id), None)
        if obj is None:
            return None
        return self.relationship(
            run_id, agent_id, snapshot["organization_id"], obj["brand_id"]
        )

    def _advance_relationship(self, run_id: str, agent_id: str,
                              object_type: str, object_id: str,
                              stage: str, action: str | None,
                              event_id: str) -> None:
        relationship = self._relationship_for_object(
            run_id, agent_id, object_type, object_id
        )
        if relationship is None:
            return
        from simulation.personas.relationship import transition_relationship
        next_state = transition_relationship(
            relationship["state"],
            {"stage": stage, "action": action, "status": "resolved",
             "brand_identity_visible": stage == "A3" and any(
                 t["tag_id"].startswith("enterprise.")
                 for t in self.context_snapshot(self.event(event_id)["stage_key"])["input"].get("visible_tags", [])
             )},
        )
        with self.transaction() as db:
            db.execute(
                "UPDATE run_agent_relationships SET current_state_json=?, "
                "last_event_id=? WHERE run_id=? AND agent_id=? AND brand_id=?",
                (dumps(next_state), event_id, run_id, agent_id,
                 relationship["brand_id"]),
            )

    def commit_stage(self, *, call_id: str, stage_key: str,
                     response: dict[str, Any], result: dict[str, Any],
                     run_id: str, session_id: str, agent_id: str,
                     object_type: str, object_id: str, encounter_no: int,
                     stage: str, parent_event_id: str | None,
                     cursor: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as db:
            existing = db.execute(
                "SELECT * FROM stage_events WHERE stage_key=?", (stage_key,)
            ).fetchone()
            if existing is not None:
                return dict(existing)
            row = db.execute(
                "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_no "
                "FROM stage_events WHERE run_id=? AND session_id=? AND agent_id=?",
                (run_id, session_id, agent_id),
            ).fetchone()
            sequence = int(row["next_no"])
            event_id = str(uuid.uuid4())
            timestamp = now()
            db.execute(
                "UPDATE model_calls SET event_id=? WHERE call_id=?",
                (event_id, call_id),
            )
            db.execute(
                "INSERT INTO stage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, run_id, session_id, agent_id, object_type, object_id,
                 encounter_no, stage, sequence, result["status"], result.get("action"),
                 result.get("normalized_score"), parent_event_id, stage_key, timestamp),
            )
            selected = {item["tag_id"] for item in result.get("selected_tags", [])}
            for rank, item in enumerate(result.get("scores", []), 1):
                db.execute(
                    "INSERT INTO event_tags VALUES (?, ?, ?, ?, ?, ?)",
                    (event_id, item["tag_id"], item["score"], rank,
                     int(item["tag_id"] in selected), item["description"]),
                )
            db.execute(
                "INSERT INTO agent_stage_states VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id,agent_id,object_type,object_id,stage) "
                "DO UPDATE SET latest_event_id=excluded.latest_event_id",
                (run_id, agent_id, object_type, object_id, stage, event_id),
            )
            db.execute(
                "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, 'committed', ?)"
                " ON CONFLICT(run_id, session_id, agent_id) DO UPDATE SET "
                "cursor_json=excluded.cursor_json, last_event_id=excluded.last_event_id, "
                "status=excluded.status, updated_at=excluded.updated_at",
                (str(uuid.uuid4()), run_id, session_id, agent_id, dumps(cursor),
                 event_id, timestamp),
            )
            if result["status"] == "resolved":
                self._advance_relationship(
                    run_id, agent_id, object_type, object_id,
                    stage, result.get("action"), event_id,
                )
            self._append_update(
                db, run_id, "stage_event",
                {
                    "event_id": event_id,
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "stage": stage,
                    "object_type": object_type,
                    "object_id": object_id,
                    "encounter_no": encounter_no,
                    "status": result["status"],
                    "action": result.get("action"),
                },
            )
            sequence_row = {"event_id": event_id, "sequence_no": sequence}
            return {**sequence_row, "status": result["status"],
                    "action": result.get("action"), "stage": stage,
                    "object_id": object_id}

    def register_dataset(
        self, *, dataset_id: str, source_name: str, revision: str,
        source_uri: str, schema_hash: str, manifest: dict[str, Any],
        usage_notice: str, status: str = "ready",
    ) -> None:
        values = (
            _id(dataset_id, "dataset_id"), _text(source_name, "source_name"),
            _text(revision, "revision"), _text(source_uri, "source_uri"),
            _text(schema_hash, "schema_hash"), dumps(manifest),
            _text(usage_notice, "usage_notice"), status, now(),
        )
        with self.transaction() as db:
            db.execute(
                "INSERT INTO persona_datasets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    def register_industry(
        self, *, industry_id: str, profile_version: str, bundle: dict[str, Any],
        bundle_hash: str | None = None, status: str = "ready",
    ) -> None:
        from simulation.personas.bundle import validate_bundle
        validate_bundle(bundle, industry_id, profile_version)
        computed_hash = hash_json(bundle)
        if bundle_hash is not None and bundle_hash != computed_hash:
            raise ValueError("Bundle hash does not match its contents")
        bundle_hash = computed_hash
        with self.transaction() as db:
            db.execute(
                "INSERT INTO industry_profiles VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _id(industry_id, "industry_id"),
                    _id(profile_version, "profile_version"),
                    bundle_hash, dumps(bundle), status, now(),
                ),
            )

    def register_cohort(
        self, *, cohort_id: str, dataset_id: str, industry_id: str,
        profile_version: str, members: list[dict[str, Any]],
        selection_policy: dict[str, Any], content_hash: str | None = None,
        status: str = "ready",
    ) -> None:
        if not members:
            raise BackendValidationError([{
                "path": "members", "code": "EMPTY_COHORT",
                "message": "A cohort must contain at least one member.",
            }])
        from simulation.personas.bundle import validate_persona
        bundle = self.industry_bundle(industry_id, profile_version)
        normalized: list[dict[str, Any]] = []
        for index, member in enumerate(members):
            path = f"members[{index}]"
            if not isinstance(member, dict):
                raise BackendValidationError([{
                    "path": path, "code": "OBJECT_REQUIRED",
                    "message": "Each member must be an object.",
                }])
            validate_persona(member.get("persona"), bundle)
            normalized.append({
                "cohort_persona_id": _id(member.get("cohort_persona_id"),
                                          f"{path}.cohort_persona_id"),
                "source_persona_id": _text(member.get("source_persona_id"),
                                         f"{path}.source_persona_id"),
                "persona": _json_object(member.get("persona"), f"{path}.persona"),
                "provenance": _json_object(member.get("provenance", {}),
                                           f"{path}.provenance"),
                "field_provenance": _json_object(
                    member.get("field_provenance", {}), f"{path}.field_provenance"
                ),
                "cohort_bucket": member.get("cohort_bucket"),
            })
        content_hash = content_hash or hash_json(normalized)
        with self.transaction() as db:
            db.execute(
                "INSERT INTO persona_cohorts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _id(cohort_id, "cohort_id"), _id(dataset_id, "dataset_id"),
                    _id(industry_id, "industry_id"),
                    _id(profile_version, "profile_version"), len(normalized),
                    content_hash, dumps(selection_policy), status, now(),
                ),
            )
            db.executemany(
                "INSERT INTO cohort_members VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        cohort_id, item["cohort_persona_id"],
                        item["source_persona_id"], dumps(item["persona"]),
                        dumps(item["provenance"]),
                        dumps(item["field_provenance"]), item["cohort_bucket"],
                    )
                    for item in normalized
                ],
            )

    def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = _json_object(payload, "campaign")
        campaign_id = payload.get("campaign_id") or f"campaign_{uuid.uuid4().hex[:12]}"
        record = {
            "campaign_id": _id(campaign_id, "campaign_id"),
            "name": _text(payload.get("name"), "name"),
            "brief": _text(payload.get("brief"), "brief"),
            "internal_notes": _text(
                payload.get("internal_notes", ""), "internal_notes", required=False
            ),
            "revision": 1,
        }
        timestamp = now()
        with self.transaction() as db:
            db.execute(
                "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record["campaign_id"], record["name"], record["brief"],
                    record["internal_notes"], 1, timestamp, timestamp,
                ),
            )
        return record

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        row = self._fetchone(
            "SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)
        )
        if row is None:
            raise BackendNotFoundError("Unknown campaign")
        return row

    def list_campaigns(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM campaigns ORDER BY created_at, campaign_id"
        ).fetchall()]

    def update_campaign(self, campaign_id, payload, expected_revision):
        errors = issues_for(payload, "CampaignInput")
        if errors:
            raise BackendValidationError(errors)
        self.get_campaign(campaign_id)
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE campaigns SET name=?, brief=?, internal_notes=?, "
                "revision=revision+1, updated_at=? WHERE campaign_id=? AND revision=?",
                (payload["name"], payload["brief"], payload.get("internal_notes", ""),
                 now(), campaign_id, expected_revision),
            )
            if changed.rowcount != 1:
                raise BackendConflictError("Campaign revision conflict")
        return self.get_campaign(campaign_id)

    def list_scenarios(self, campaign_id: str) -> list[dict[str, Any]]:
        self.get_campaign(campaign_id)
        rows = self.connection.execute(
            "SELECT * FROM scenarios WHERE campaign_id=? ORDER BY scenario_id",
            (campaign_id,),
        ).fetchall()
        return [self.get_scenario(row["scenario_id"]) for row in rows]

    def list_industries(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT industry_id, profile_version, bundle_hash, status, created_at "
            "FROM industry_profiles ORDER BY industry_id, profile_version"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_industry(self, industry_id, profile_version):
        row = self._fetchone(
            "SELECT * FROM industry_profiles WHERE industry_id=? AND profile_version=?",
            (industry_id, profile_version),
        )
        if row is None:
            raise BackendNotFoundError("Unknown industry profile")
        return {**row, "bundle": json.loads(row.pop("profile_json"))}

    def list_datasets(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT dataset_id, source_name, revision, schema_hash, usage_notice, manifest_json, status "
            "FROM persona_datasets ORDER BY created_at DESC"
        ).fetchall()
        return [{**dict(row), "manifest": json.loads(row["manifest_json"])}
                for row in rows]

    def list_cohorts(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT cohort_id, dataset_id, industry_id, profile_version, size, "
            "content_hash, selection_policy_json, status FROM persona_cohorts "
            "ORDER BY cohort_id"
        ).fetchall()
        return [{**dict(row), "selection_policy": json.loads(row["selection_policy_json"])}
                for row in rows]

    def cohort_members(self, cohort_id, limit=100, after=""):
        self._cohort(cohort_id)
        rows = self.connection.execute(
            "SELECT cohort_persona_id, source_persona_id, persona_json, provenance_json, "
            "field_provenance_json FROM cohort_members WHERE cohort_id=? "
            "AND cohort_persona_id>? ORDER BY cohort_persona_id LIMIT ?",
            (cohort_id, after, limit),
        ).fetchall()
        return [{
            "cohort_id": cohort_id,
            "cohort_persona_id": row["cohort_persona_id"],
            "source_persona_id": row["source_persona_id"],
            "persona": json.loads(row["persona_json"]),
            "provenance": json.loads(row["provenance_json"]),
            "field_provenance": json.loads(row["field_provenance_json"]),
        } for row in rows]

    def scenario_participants(self, scenario_id: str) -> list[dict[str, Any]]:
        scenario = self.get_scenario(scenario_id)
        report = self.validate_scenario(scenario_id)
        if not report["valid"]:
            raise BackendValidationError(report["issues"])
        setup = scenario["setup"]
        if scenario["frozen_snapshot"]:
            members = scenario["frozen_snapshot"]["setup"]["selected_members"]
        else:
            members = [{
                **row, "persona": json.loads(row["persona_json"]),
                "provenance": json.loads(row["provenance_json"]),
                "field_provenance": json.loads(row["field_provenance_json"]),
            } for row in self._members(
                setup["cohort_id"], setup["agent_count"], setup["selection_seed"]
            )]
        groups = self._assign_groups(
            [f"agent_{row['cohort_persona_id']}" for row in members],
            setup["relationship_groups"], setup["assignment_seed"],
        )
        return [{
            "ordinal": index,
            "agent_id": f"agent_{row['cohort_persona_id']}",
            "cohort_id": setup["cohort_id"],
            "cohort_persona_id": row["cohort_persona_id"],
            "source_persona_id": row["source_persona_id"],
            "persona": row["persona"],
            "provenance": row["provenance"],
            "field_provenance": row["field_provenance"],
            "group_id": groups[f"agent_{row['cohort_persona_id']}"]["group_id"],
            "initial_relationship": groups[f"agent_{row['cohort_persona_id']}"]["state"],
        } for index, row in enumerate(members, 1)]

    def run_sessions(self, run_id: str) -> list[dict[str, Any]]:
        self.get_run(run_id)
        return self.sessions(run_id)

    def run_objects(self, run_id: str) -> dict[str, list[dict[str, Any]]]:
        snapshot = self.run_snapshot(run_id)
        return {key: snapshot[key] for key in ("shops", "posts", "products")}

    def create_scenario(self, campaign_id: str, setup: dict[str, Any]) -> dict[str, Any]:
        self.get_campaign(campaign_id)
        setup = _json_object(setup, "setup")
        errors = issues_for(setup, "ScenarioSetup")
        if errors:
            raise BackendValidationError(errors)
        name = _text(setup.get("name"), "setup.name")
        scenario_id = f"scenario_{uuid.uuid4().hex[:12]}"
        scenario_id = _id(scenario_id, "scenario_id")
        timestamp = now()
        with self.transaction() as db:
            db.execute(
                "INSERT INTO scenarios VALUES (?, ?, ?, 1, 'draft', ?, NULL, NULL, ?, ?)",
                (scenario_id, campaign_id, name, dumps(setup), timestamp, timestamp),
            )
        return self.get_scenario(scenario_id)

    def get_scenario(self, scenario_id: str) -> dict[str, Any]:
        row = self._fetchone(
            "SELECT * FROM scenarios WHERE scenario_id=?", (scenario_id,)
        )
        if row is None:
            raise BackendNotFoundError("Unknown scenario")
        row["setup"] = json.loads(row.pop("setup_json"))
        frozen = row.pop("frozen_snapshot_json")
        row["frozen_snapshot"] = json.loads(frozen) if frozen else None
        return row

    def replace_scenario(
        self, scenario_id: str, setup: dict[str, Any], expected_revision: int,
    ) -> dict[str, Any]:
        current = self.get_scenario(scenario_id)
        if current["status"] != "draft":
            raise BackendConflictError("Only draft scenarios can be edited")
        if current["revision"] != expected_revision:
            raise BackendConflictError("Scenario revision conflict")
        setup = _json_object(setup, "setup")
        errors = issues_for(setup, "ScenarioSetup")
        if errors:
            raise BackendValidationError(errors)
        name = _text(setup.get("name"), "setup.name")
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE scenarios SET name=?, revision=revision+1, setup_json=?, "
                "updated_at=? WHERE scenario_id=? AND revision=? AND status='draft'",
                (name, dumps(setup), now(), scenario_id, expected_revision),
            )
            if changed.rowcount != 1:
                raise BackendConflictError("Scenario revision conflict")
        return self.get_scenario(scenario_id)

    def _cohort(self, cohort_id: str) -> dict[str, Any]:
        row = self._fetchone(
            "SELECT * FROM persona_cohorts WHERE cohort_id=?", (cohort_id,)
        )
        if row is None:
            raise BackendValidationError([{
                "path": "setup.cohort_id", "code": "UNKNOWN_COHORT",
                "message": f"Unknown cohort: {cohort_id}",
            }])
        return row

    def _members(
        self, cohort_id: str, count: int, seed: int,
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM cohort_members WHERE cohort_id=?",
            (cohort_id,),
        ).fetchall()
        if count > len(rows):
            raise BackendValidationError([{
                "path": "setup.agent_count", "code": "COHORT_TOO_SMALL",
                "message": "agent_count exceeds the selected cohort size.",
            }])
        ranked = sorted(
            rows,
            key=lambda row: (
                hashlib.sha256(
                    f"cohort-selection-v1|{cohort_id}|{seed}|"
                    f"{row['cohort_persona_id']}".encode()
                ).hexdigest(),
                row["cohort_persona_id"],
            ),
        )
        return [dict(row) for row in ranked[:count]]

    def _setup_issues(self, setup: dict[str, Any]) -> list[dict[str, str]]:
        structural = issues_for(setup, "ScenarioSetup")
        if structural:
            return structural
        issues: list[dict[str, str]] = []

        def issue(path: str, code: str, message: str) -> None:
            issues.append({"path": path, "code": code, "message": message})

        bundle = None
        if isinstance(setup.get("industry_id"), str) and isinstance(
            setup.get("profile_version"), str
        ):
            try:
                # The bundle is the authority for enterprise tag IDs and
                # stage visibility; do not validate against a mutable global.
                bundle = self._bundle_for_setup(setup)
            except Exception as error:
                issue(
                    "setup.profile_version",
                    "INVALID_INDUSTRY_PROFILE",
                    str(error),
                )

        for field in (
            "industry_id", "profile_version", "cohort_id", "policy_version",
            "business",
        ):
            if field not in setup:
                issue(f"setup.{field}", "REQUIRED", "Field is required to freeze.")
        business = setup.get("business")
        if not isinstance(business, dict):
            issue("setup.business", "OBJECT_REQUIRED", "Business context is required.")
        else:
            for field in (
                "organization_id", "organization_name",
                "organization_description", "brand_id", "brand_name",
                "brand_description", "tags",
            ):
                if field not in business:
                    issue(f"setup.business.{field}", "REQUIRED", "Field is required.")
            if not isinstance(business.get("tags"), list):
                issue("setup.business.tags", "LIST_REQUIRED", "Tags must be a list.")
            elif bundle is not None:
                self._validate_business_tags(
                    business, bundle, issues,
                )
        count = setup.get("agent_count")
        if type(count) is not int or not 1 <= count <= 100:
            issue("setup.agent_count", "INVALID_COUNT", "Use an integer from 1 to 100.")
        for field in ("selection_seed", "assignment_seed"):
            if type(setup.get(field)) is not int or setup[field] < 0:
                issue(f"setup.{field}", "INVALID_SEED", "Seed must be >= 0.")
        for field in ("shops", "posts", "products", "sessions", "relationship_groups"):
            if not isinstance(setup.get(field), list):
                issue(f"setup.{field}", "LIST_REQUIRED", "A list is required.")
        if not setup.get("shops"):
            issue("setup.shops", "EMPTY_SHOPS", "At least one shop is required.")
        if not setup.get("sessions"):
            issue("setup.sessions", "EMPTY_SESSIONS", "At least one session is required.")
        shops = setup.get("shops") if isinstance(setup.get("shops"), list) else []
        posts = setup.get("posts") if isinstance(setup.get("posts"), list) else []
        products = setup.get("products") if isinstance(setup.get("products"), list) else []
        sessions = setup.get("sessions") if isinstance(setup.get("sessions"), list) else []
        shop_ids: set[str] = set()
        for index, shop in enumerate(shops):
            if not isinstance(shop, dict):
                issue(f"setup.shops[{index}]", "OBJECT_REQUIRED", "Shop must be an object.")
                continue
            shop_id = shop.get("shop_id")
            if not isinstance(shop_id, str) or not shop_id.strip() or shop_id in shop_ids:
                issue(f"setup.shops[{index}].shop_id", "DUPLICATE_OR_EMPTY", "Shop ID must be unique.")
            elif shop_id not in shop_ids:
                shop_ids.add(shop_id)
            for field in ("name", "public_profile", "tags"):
                if field not in shop:
                    issue(f"setup.shops[{index}].{field}", "REQUIRED", "Field is required.")
            if bundle is not None:
                self._validate_object_tags(
                    shop, "shop", shop_id, bundle, issues,
                    f"setup.shops[{index}]",
                )
        post_ids: set[str] = set()
        for index, post in enumerate(posts):
            if not isinstance(post, dict):
                issue(f"setup.posts[{index}]", "OBJECT_REQUIRED", "Post must be an object.")
                continue
            post_id = post.get("post_id")
            if not isinstance(post_id, str) or not post_id.strip() or post_id in post_ids:
                issue(f"setup.posts[{index}].post_id", "DUPLICATE_OR_EMPTY", "Post ID must be unique.")
            elif post_id not in post_ids:
                post_ids.add(post_id)
            if post.get("shop_id") not in shop_ids:
                issue(f"setup.posts[{index}].shop_id", "UNKNOWN_SHOP", "Post shop is unknown.")
            for field in ("title", "preview", "article_content", "tags"):
                if field not in post:
                    issue(f"setup.posts[{index}].{field}", "REQUIRED", "Field is required.")
            if bundle is not None:
                self._validate_object_tags(
                    post, "post", post_id, bundle, issues,
                    f"setup.posts[{index}]",
                )
        product_ids: set[str] = set()
        product_positions: dict[str, set[int]] = {}
        for index, product in enumerate(products):
            if not isinstance(product, dict):
                issue(f"setup.products[{index}]", "OBJECT_REQUIRED", "Product must be an object.")
                continue
            product_id = product.get("product_id")
            if not isinstance(product_id, str) or not product_id.strip() or product_id in product_ids:
                issue(f"setup.products[{index}].product_id", "DUPLICATE_OR_EMPTY", "Product ID must be unique.")
            product_ids.add(product_id)
            shop_id = product.get("shop_id")
            if shop_id not in shop_ids:
                issue(f"setup.products[{index}].shop_id", "UNKNOWN_SHOP", "Product shop is unknown.")
            position = product.get("position")
            positions = product_positions.setdefault(shop_id, set())
            if type(position) is not int or position < 1 or position in positions:
                issue(f"setup.products[{index}].position", "INVALID_POSITION", "Product position must be unique per shop.")
            elif position not in positions:
                positions.add(position)
            for field in ("product_name", "listed_price", "product_description", "tags"):
                if field not in product:
                    issue(f"setup.products[{index}].{field}", "REQUIRED", "Field is required.")
            if bundle is not None:
                self._validate_object_tags(
                    product, "product", product_id, bundle, issues,
                    f"setup.products[{index}]",
                )
        session_numbers: list[int] = []
        for index, session in enumerate(sessions):
            if not isinstance(session, dict):
                issue(f"setup.sessions[{index}]", "OBJECT_REQUIRED", "Session must be an object.")
                continue
            number = session.get("session_no")
            if type(number) is not int or number < 1:
                issue(f"setup.sessions[{index}].session_no", "INVALID_SESSION", "Session number must be positive.")
            else:
                session_numbers.append(number)
            positions: set[int] = set()
            scheduled_posts = session.get("posts", [])
            if not isinstance(scheduled_posts, list):
                issue(f"setup.sessions[{index}].posts", "LIST_REQUIRED", "Scheduled posts must be a list.")
                scheduled_posts = []
            for post in scheduled_posts:
                if not isinstance(post, dict) or post.get("post_id") not in post_ids:
                    issue(f"setup.sessions[{index}].posts", "UNKNOWN_POST", "Scheduled post is unknown.")
                position = post.get("position") if isinstance(post, dict) else None
                if type(position) is not int or position < 1 or position in positions:
                    issue(f"setup.sessions[{index}].posts", "INVALID_POSITION", "Post position must be unique per session.")
                elif position not in positions:
                    positions.add(position)
        if session_numbers and sorted(session_numbers) != list(range(1, len(session_numbers) + 1)):
            issue("setup.sessions", "NON_CONTIGUOUS", "Session numbers must be 1..N.")
        groups = setup.get("relationship_groups")
        if isinstance(groups, list) and not groups:
            issue("setup.relationship_groups", "EMPTY_GROUPS", "At least one group is required.")
        if isinstance(groups, list):
            from simulation.personas.assignment import validate_initialization

            if type(count) is int and 1 <= count <= 100:
                issues.extend(
                    {"path": item.path, "code": item.code, "message": item.message}
                    for item in validate_initialization(
                        {"seed": setup.get("assignment_seed"), "groups": groups},
                        [str(i) for i in range(count)], path="setup.relationship_groups",
                    )
                )
            allocation_mode: str | None = None
            allocation_total = 0.0
            group_ids: set[str] = set()
            for index, group in enumerate(groups):
                path = f"setup.relationship_groups[{index}]"
                if not isinstance(group, dict):
                    issue(path, "OBJECT_REQUIRED", "Relationship group must be an object.")
                    continue
                group_id = group.get("group_id")
                if not isinstance(group_id, str) or not group_id.strip() or group_id in group_ids:
                    issue(f"{path}.group_id", "DUPLICATE_OR_EMPTY", "Group ID must be unique.")
                elif group_id not in group_ids:
                    group_ids.add(group_id)
                if not isinstance(group.get("state"), dict):
                    issue(f"{path}.state", "OBJECT_REQUIRED", "Relationship state is required.")
                has_count = "count" in group
                has_percentage = "percentage" in group
                if has_count == has_percentage:
                    issue(path, "ALLOCATION_SHAPE", "Use exactly one of count or percentage.")
                    continue
                mode = "count" if has_count else "percentage"
                if allocation_mode is not None and mode != allocation_mode:
                    issue("setup.relationship_groups", "MIXED_ALLOCATION_MODES",
                          "Use count for every group or percentage for every group.")
                allocation_mode = mode
                value = group.get(mode)
                valid = (
                    type(value) is int and value >= 0
                    if mode == "count"
                    else type(value) in (int, float) and 0 <= value <= 100
                )
                if not valid:
                    issue(f"{path}.{mode}", "INVALID_ALLOCATION", "Allocation value is invalid.")
                else:
                    allocation_total += float(value)
            if allocation_mode == "count" and type(count) is int and allocation_total != count:
                issue("setup.relationship_groups", "COUNT_SUM",
                      "Group counts must equal agent_count.")
            if allocation_mode == "percentage" and abs(allocation_total - 100.0) > 1e-6:
                issue("setup.relationship_groups", "PERCENTAGE_SUM",
                      "Group percentages must sum to 100.")
        return issues

    def _bundle_for_setup(self, setup: dict[str, Any]) -> dict[str, Any]:
        profile = setup.get("profile_version")
        industry = setup.get("industry_id")
        if not isinstance(industry, str) or not isinstance(profile, str):
            raise BackendValidationError([{
                "path": "setup.industry_id",
                "code": "INDUSTRY_REQUIRED",
                "message": "industry_id and profile_version are required.",
            }])
        return self.industry_bundle(industry, profile)

    @staticmethod
    def _validate_business_tags(
        business: dict[str, Any],
        bundle: dict[str, Any],
        issues: list[dict[str, str]],
    ) -> None:
        tags = bundle["tag_registry"]
        known = {item["id"]: item for item in tags.get("tags", [])}
        allowed_stages = set(tags["families"]["enterprise"]["stages"])
        organization_id = business.get("organization_id")
        brand_id = business.get("brand_id")
        for index, assignment in enumerate(business["tags"]):
            path = f"setup.business.tags[{index}]"
            if not isinstance(assignment, dict):
                issues.append({
                    "path": path, "code": "TAG_NOT_OBJECT",
                    "message": "Each business tag must be an object.",
                })
                continue
            if set(assignment) != {"tag_id", "source_ref", "visible_stages"}:
                issues.append({
                    "path": path, "code": "TAG_ASSIGNMENT_SHAPE",
                    "message": "Tag assignments must contain exactly tag_id, source_ref and visible_stages.",
                })
                continue
            tag_id = assignment["tag_id"]
            if tag_id not in known:
                issues.append({
                    "path": f"{path}.tag_id", "code": "UNKNOWN_TAG",
                    "message": "Tag is not in the selected industry registry.",
                })
            elif known[tag_id]["family"] != "enterprise":
                issues.append({
                    "path": f"{path}.tag_id", "code": "TAG_FAMILY_MISMATCH",
                    "message": "Business tags must belong to the enterprise family.",
                })
            source_ref = assignment["source_ref"]
            valid_refs = {
                f"organization:{organization_id}:organization_description",
                f"brand:{brand_id}:brand_description",
            }
            if source_ref not in valid_refs:
                issues.append({
                    "path": f"{path}.source_ref", "code": "TAG_SOURCE_REF",
                    "message": "Business tag source_ref must point to the public organization or brand description.",
                })
            visible = assignment["visible_stages"]
            if (
                not isinstance(visible, list)
                or not visible
                or any(not isinstance(stage, str) for stage in visible)
                or len(set(visible)) != len(visible)
                or any(stage not in allowed_stages for stage in visible)
            ):
                issues.append({
                    "path": f"{path}.visible_stages", "code": "TAG_VISIBILITY",
                    "message": "Business tag visibility must contain valid enterprise stages.",
                })

    @staticmethod
    def _validate_object_tags(
        owner: dict[str, Any],
        owner_type: str,
        owner_id: Any,
        bundle: dict[str, Any],
        issues: list[dict[str, str]],
        owner_path: str,
    ) -> None:
        if "industry_data" in owner:
            schema = bundle.get("object_schemas", {}).get(
                owner_type, {"type": "object", "additionalProperties": False})
            for error in issues_for(owner["industry_data"], schema):
                issues.append({**error, "path": f"{owner_path}.industry_data{error['path'][1:]}"})
        assignments = owner.get("tags")
        path = f"{owner_path}.tags"
        if not isinstance(assignments, list):
            return
        family = {
            "shop": "enterprise",
            "post": "article",
            "product": "product",
        }[owner_type]
        fields = {
            "shop": {"public_profile"},
            "post": {"preview", "article_content"},
            "product": {"product_name", "listed_price", "product_description"},
        }[owner_type]
        registry = bundle["tag_registry"]
        known = {item["id"]: item for item in registry.get("tags", [])}
        allowed_stages = set(registry["families"][family]["stages"])
        prefix = f"{owner_type}:{owner_id}:"
        seen: set[str] = set()
        for index, assignment in enumerate(assignments):
            item_path = f"{path}[{index}]"
            if not isinstance(assignment, dict):
                issues.append({
                    "path": item_path, "code": "TAG_NOT_OBJECT",
                    "message": "Each tag assignment must be an object.",
                })
                continue
            if set(assignment) != {"tag_id", "source_ref", "visible_stages"}:
                issues.append({
                    "path": item_path, "code": "TAG_ASSIGNMENT_SHAPE",
                    "message": "Tag assignments must contain exactly tag_id, source_ref and visible_stages.",
                })
                continue
            tag_id = assignment["tag_id"]
            if tag_id in seen:
                issues.append({
                    "path": f"{item_path}.tag_id", "code": "DUPLICATE_TAG",
                    "message": "A tag may be assigned only once to one object.",
                })
            seen.add(tag_id)
            definition = known.get(tag_id)
            if definition is None:
                issues.append({
                    "path": f"{item_path}.tag_id", "code": "UNKNOWN_TAG",
                    "message": "Tag is not in the selected industry registry.",
                })
            elif definition["family"] != family:
                issues.append({
                    "path": f"{item_path}.tag_id", "code": "TAG_FAMILY_MISMATCH",
                    "message": f"Tag must belong to the {family} family.",
                })
            source_ref = assignment["source_ref"]
            source_field = (
                source_ref[len(prefix):]
                if isinstance(source_ref, str) and source_ref.startswith(prefix)
                else None
            )
            if source_field not in fields or not isinstance(owner.get(source_field), str) \
                    or not owner[source_field].strip():
                issues.append({
                    "path": f"{item_path}.source_ref", "code": "TAG_SOURCE_REF",
                    "message": "Tag source_ref must point to a non-empty public field of this object.",
                })
            visible = assignment["visible_stages"]
            valid_visibility = (
                isinstance(visible, list)
                and bool(visible)
                and all(isinstance(stage, str) for stage in visible)
                and len(set(visible)) == len(visible)
                and all(stage in allowed_stages for stage in visible)
            )
            if not valid_visibility:
                issues.append({
                    "path": f"{item_path}.visible_stages", "code": "TAG_VISIBILITY",
                    "message": "Tag visibility must contain valid stages for its family.",
                })
            if isinstance(visible, list):
                if (
                    source_field == "article_content"
                    and any(stage in {"A1", "A2"} for stage in visible)
                ):
                    issues.append({
                        "path": f"{item_path}.visible_stages",
                        "code": "EARLY_FULL_CONTENT",
                        "message": "article_content cannot be visible before A3.",
                    })
                if source_field == "product_description" and "B1" in visible:
                    issues.append({
                        "path": f"{item_path}.visible_stages",
                        "code": "EARLY_PRODUCT_DETAILS",
                        "message": "product_description cannot be visible at B1.",
                    })

    def validate_scenario(self, scenario_id: str, expected_revision=None) -> dict[str, Any]:
        current = self.get_scenario(scenario_id)
        if expected_revision is not None and expected_revision != current["revision"]:
            raise BackendConflictError("Scenario revision conflict")
        issues = self._setup_issues(current["setup"])
        setup = current["setup"]
        if not issues and setup.get("cohort_id"):
            try:
                cohort = self._cohort(setup["cohort_id"])
                self._members(setup["cohort_id"], setup["agent_count"], setup["selection_seed"])
            except BackendValidationError as error:
                issues.extend(error.issues)
                cohort = None
            if cohort is None:
                return {"valid": False, "revision": current["revision"],
                        "issues": [{**i, "severity": "error"} for i in issues],
                        "group_counts": []}
            if cohort["status"] != "ready":
                issues.append({
                    "path": "setup.cohort_id", "code": "COHORT_NOT_READY",
                    "message": "The selected cohort is not ready.",
                })
            if cohort["industry_id"] != setup.get("industry_id") or \
                    cohort["profile_version"] != setup.get("profile_version"):
                issues.append({
                    "path": "setup.cohort_id", "code": "COHORT_PROFILE_MISMATCH",
                    "message": "Cohort and industry profile do not match.",
                })
            if not issues:
                members = self._members(
                    setup["cohort_id"], setup["agent_count"],
                    setup["selection_seed"],
                )
                selected_ids = {f"agent_{m['cohort_persona_id']}" for m in members}
                for index, session in enumerate(setup["sessions"]):
                    if set(session.get("active_agent_ids", [])) - selected_ids:
                        issues.append({
                            "path": f"setup.sessions[{index}].active_agent_ids",
                            "code": "UNKNOWN_AGENT", "message": "Active agent is outside the selected cohort.",
                        })
        group_counts = []
        if not issues:
            from simulation.personas.assignment import _allocation_counts
            for group, count in zip(setup["relationship_groups"],
                                    _allocation_counts(setup["relationship_groups"],
                                                       setup["agent_count"])):
                group_counts.append({
                    "group_id": group["group_id"],
                    "requested_count": group.get("count"),
                    "requested_percentage": group.get("percentage"),
                    "assigned_count": count,
                    "assigned_percentage": count * 100 / setup["agent_count"],
                })
        return {
            "valid": not issues,
            "revision": current["revision"],
            "issues": [{**i, "severity": "error"} for i in issues],
            "group_counts": group_counts,
        }

    def freeze_scenario(self, scenario_id: str, expected_revision: int) -> dict[str, Any]:
        with self.transaction():
            return self._freeze_scenario(scenario_id, expected_revision)

    def _freeze_scenario(self, scenario_id: str, expected_revision: int) -> dict[str, Any]:
        current = self.get_scenario(scenario_id)
        if current["status"] == "ready":
            if current["revision"] != expected_revision:
                raise BackendConflictError("Scenario revision conflict")
            return current
        if current["revision"] != expected_revision:
            raise BackendConflictError("Scenario revision conflict")
        report = self.validate_scenario(scenario_id)
        if not report["valid"]:
            raise BackendValidationError(report["issues"])
        setup = deepcopy(current["setup"])
        members = self._members(
            setup["cohort_id"], setup["agent_count"], setup["selection_seed"]
        )
        setup["selected_members"] = [
            {
                "cohort_persona_id": row["cohort_persona_id"],
                "source_persona_id": row["source_persona_id"],
                "persona": json.loads(row["persona_json"]),
                "provenance": json.loads(row["provenance_json"]),
                "field_provenance": json.loads(row["field_provenance_json"]),
                "cohort_bucket": row["cohort_bucket"],
            }
            for row in members
        ]
        snapshot = {
            "schema": "scenario-snapshot-v1",
            "scenario_id": scenario_id,
            "campaign_id": current["campaign_id"],
            "scenario_revision": current["revision"],
            "campaign": self.get_campaign(current["campaign_id"]),
            "bundle": self.industry_bundle(setup["industry_id"], setup["profile_version"]),
            "setup": setup,
        }
        snapshot_hash = hash_json(snapshot)
        with self.transaction() as db:
            db.execute(
                "UPDATE scenarios SET status='ready', frozen_snapshot_json=?, "
                "snapshot_hash=?, updated_at=? WHERE scenario_id=? AND revision=?",
                (dumps(snapshot), snapshot_hash, now(), scenario_id, expected_revision),
            )
        return self.get_scenario(scenario_id)

    def industry_bundle(self, industry_id, profile_version):
        row = self._fetchone(
            "SELECT * FROM industry_profiles WHERE industry_id=? AND profile_version=? AND status='ready'",
            (industry_id, profile_version),
        )
        if row is None:
            raise BackendNotFoundError("Unknown or disabled industry profile")
        bundle = json.loads(row["profile_json"])
        if hash_json(bundle) != row["bundle_hash"]:
            raise BackendConflictError("Industry bundle hash mismatch")
        return bundle

    def run_bundle(self, run_id):
        return self.get_run(run_id)["input_snapshot"]["bundle"]

    def create_run(
        self, scenario_id: str, execution: dict[str, Any],
        run_id: str | None = None, idempotency_key: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self.transaction():
            return self._create_run(
                scenario_id, execution, run_id, idempotency_key, expected_revision,
            )

    def _create_run(
        self, scenario_id, execution, run_id, idempotency_key, expected_revision,
    ):
        scenario = self.get_scenario(scenario_id)
        if scenario["status"] != "ready" or not scenario["frozen_snapshot"]:
            raise BackendConflictError("Scenario must be frozen before creating a run")
        if expected_revision is not None:
            if type(expected_revision) is not int or expected_revision != scenario["revision"]:
                raise BackendConflictError("Scenario revision conflict")
        execution = _json_object(execution, "execution")
        errors = issues_for(execution, "Execution")
        if errors:
            raise BackendValidationError(errors)
        mode = execution.get("mode")
        batch_size = execution.get("batch_size")
        if mode not in {"sequential", "parallel"} or type(batch_size) is not int or not 1 <= batch_size <= 8:
            raise BackendValidationError([{
                "path": "execution", "code": "INVALID_EXECUTION",
                "message": "mode must be sequential/parallel and batch_size must be 1..8.",
            }])
        if mode == "sequential" and batch_size != 1:
            raise BackendValidationError([{
                "path": "execution.batch_size", "code": "INVALID_SEQUENTIAL_BATCH",
                "message": "Sequential execution requires batch_size=1.",
            }])
        snapshot = scenario["frozen_snapshot"]
        requested_run_id = run_id
        if requested_run_id is not None:
            requested_run_id = _id(requested_run_id, "run_id")
        if idempotency_key is not None:
            if (
                not isinstance(idempotency_key, str)
                or not 1 <= len(idempotency_key.strip()) <= 128
            ):
                raise BackendValidationError([{
                    "path": "Idempotency-Key", "code": "INVALID_IDEMPOTENCY_KEY",
                    "message": "Idempotency-Key must contain 1..128 characters.",
                }])
            idempotency_key = idempotency_key.strip()
        request_hash = hash_json({
            "scenario_id": scenario_id,
            "execution": execution,
            "run_id": requested_run_id,
        })
        if idempotency_key is not None:
            existing = self._fetchone(
                "SELECT * FROM idempotency_keys WHERE idempotency_key=?",
                (idempotency_key,),
            )
            if existing is not None:
                if existing["operation"] != "create_run" or \
                        existing["request_hash"] != request_hash:
                    raise BackendConflictError(
                        "Idempotency-Key was already used with another request"
                    )
                return self.get_run(existing["resource_id"])
        run_id = requested_run_id or f"run_{uuid.uuid4().hex[:12]}"
        created = now()
        agents = snapshot["setup"]["selected_members"]
        sessions = snapshot["setup"]["sessions"]
        groups = snapshot["setup"]["relationship_groups"]
        business = snapshot["setup"]["business"]
        assignments = self._assign_groups(
            [f"agent_{item['cohort_persona_id']}" for item in agents],
            groups, snapshot["setup"]["assignment_seed"],
        )
        input_snapshot = deepcopy(snapshot)
        input_snapshot["execution"] = execution
        input_snapshot["run_id"] = run_id
        with self.transaction() as db:
            try:
                if idempotency_key is not None:
                    db.execute(
                        "INSERT INTO idempotency_keys VALUES (?, ?, ?, ?, ?)",
                        (
                            idempotency_key, "create_run", request_hash,
                            run_id, created,
                        ),
                    )
                db.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, 'ready', 0, NULL, NULL, NULL, ?, ?)",
                    (
                        run_id, scenario_id, scenario["revision"],
                        scenario["snapshot_hash"], dumps(input_snapshot),
                        dumps(execution), created, created,
                    ),
                )
                for session in sessions:
                    number = session["session_no"]
                    session_id = session.get("session_id", f"{run_id}_session_{number}")
                    db.execute(
                        "INSERT INTO run_sessions VALUES (?, ?, ?, 'pending', ?, NULL, NULL)",
                        (run_id, number, session_id, dumps(session)),
                    )
                for ordinal, member in enumerate(agents, start=1):
                    agent_id = f"agent_{member['cohort_persona_id']}"
                    db.execute(
                        "INSERT INTO run_agents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id, agent_id, ordinal, snapshot["setup"]["cohort_id"],
                            member["cohort_persona_id"], member["source_persona_id"],
                            dumps(member["persona"]), dumps(member["provenance"]),
                            dumps(member["field_provenance"]),
                        ),
                    )
                    group = assignments[agent_id]
                    db.execute(
                        "INSERT INTO run_agent_relationships VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id, agent_id, business["brand_id"],
                            business["organization_id"], group["group_id"],
                            dumps(group["state"]), dumps(group["state"]),
                            dumps(group["provenance"]), None,
                        ),
                    )
                    for session in sessions:
                        active = session.get(
                            "active_agents", session.get("active_agent_ids")
                        )
                        session_id = session.get(
                            "session_id", f"{run_id}_session_{session['session_no']}"
                        )
                        db.execute(
                            "INSERT INTO agent_sessions VALUES (?, ?, ?, ?)",
                            (run_id, session_id, agent_id,
                             "pending" if active is None or agent_id in active else "inactive"),
                        )
            except sqlite3.IntegrityError as error:
                raise BackendConflictError("Run materialization violates a database constraint") from error
        return self.get_run(run_id)

    @staticmethod
    def _assign_groups(
        agent_ids: list[str], groups: list[dict[str, Any]], seed: int,
    ) -> dict[str, dict[str, Any]]:
        def rank(agent_id: str) -> tuple[str, str]:
            return (
                hashlib.sha256(
                    f"relationship-assignment-v1|{seed}|{agent_id}".encode()
                ).hexdigest(),
                agent_id,
            )

        ranked = sorted(agent_ids, key=rank)
        from simulation.personas.assignment import _allocation_counts
        quotas = _allocation_counts(groups, len(agent_ids))
        result: dict[str, dict[str, Any]] = {}
        cursor = 0
        for group, quota in zip(groups, quotas):
            for agent_id in ranked[cursor:cursor + quota]:
                result[agent_id] = {
                    "group_id": group["group_id"],
                    "state": deepcopy(group["state"]),
                    "provenance": {
                        "seed": seed, "group_id": group["group_id"],
                        "allocation_value": group.get("count", group.get("percentage")),
                    },
                }
            cursor += quota
        return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM runs WHERE run_id=?", (run_id,))
        if row is None:
            raise BackendNotFoundError("Unknown run")
        row["input_snapshot"] = json.loads(row.pop("input_snapshot_json"))
        row["execution"] = json.loads(row.pop("execution_json"))
        row["sessions"] = [
            dict(item) for item in self.connection.execute(
                "SELECT * FROM run_sessions WHERE run_id=? ORDER BY session_no",
                (run_id,),
            ).fetchall()
        ]
        return row

    def run_snapshot(self, run_id: str) -> dict[str, Any]:
        """Return the immutable runtime shape derived from the run snapshot."""
        run = self.get_run(run_id)
        setup = deepcopy(run["input_snapshot"]["setup"])
        business = setup["business"]
        members = self.run_agents(run_id)
        agents = [
            {
                "agent_id": item["agent_id"],
                "source_persona_id": item["source_persona_id"],
                "persona": item["persona"],
                "persona_provenance": item["provenance"],
                "field_provenance": item["field_provenance"],
                "cohort_bucket": item.get("cohort_bucket"),
            }
            for item in members
        ]
        sessions = []
        for source in setup["sessions"]:
            number = source["session_no"]
            sessions.append({
                "session_id": source.get("session_id", f"{run_id}_session_{number}"),
                "session_no": number,
                "posts": deepcopy(source.get("posts", [])),
                **({"active_agents": deepcopy(
                    source.get("active_agents", source.get("active_agent_ids"))
                )} if ("active_agents" in source or "active_agent_ids" in source) else {}),
            })
        def owned(item: dict[str, Any]) -> dict[str, Any]:
            result = deepcopy(item)
            result.setdefault("organization_id", business["organization_id"])
            result.setdefault("brand_id", business["brand_id"])
            return result
        return {
            "run_id": run_id,
            "scenario_id": run["scenario_id"],
            "campaign_id": run["input_snapshot"]["campaign_id"],
            "organization_id": business["organization_id"],
            "brand_id": business["brand_id"],
            "industry_id": setup["industry_id"],
            "industry_profile_version": setup["profile_version"],
            "policy_version": setup["policy_version"],
            "business": business,
            "agents": agents,
            "sessions": sessions,
            "shops": [owned(item) for item in setup["shops"]],
            "posts": [owned(item) for item in setup["posts"]],
            "products": [owned(item) for item in setup["products"]],
        }

    def run_status(self, run_id: str) -> str | None:
        row = self._fetchone("SELECT status FROM runs WHERE run_id=?", (run_id,))
        return row["status"] if row else None

    def finish_run(self, run_id: str, status: str = "completed",
                   failure_code: str | None = None) -> None:
        if status not in {"completed", "failed"}:
            raise BackendValidationError([{
                "path": "run.status", "code": "INVALID_STATUS",
                "message": "A run can finish only as completed or failed.",
            }])
        current = self.get_run(run_id)
        if current["status"] != "running":
            if current["status"] == status:
                return
            raise BackendConflictError("Run is not running")
        with self.transaction() as db:
            if status == "completed" and db.execute(
                "SELECT 1 FROM run_sessions WHERE run_id=? AND status!='completed'",
                (run_id,),
            ).fetchone():
                raise BackendConflictError("Cannot finish before all sessions are published")
            timestamp = now()
            db.execute(
                "UPDATE runs SET status=?, failure_code=?, ended_at=?, updated_at=? WHERE run_id=?",
                (status, failure_code, timestamp, timestamp, run_id),
            )
            if status == "failed":
                db.execute(
                    "UPDATE run_sessions SET status='failed', ended_at=? "
                    "WHERE run_id=? AND status='running'", (timestamp, run_id),
                )
                db.execute(
                    "UPDATE agent_sessions SET status='failed' WHERE run_id=? AND status='running'",
                    (run_id,),
                )
            self._append_update(
                db, run_id, "run_completed" if status == "completed" else "run_failed",
                {"status": status, "execution_epoch": current["execution_epoch"],
                 "failure_code": failure_code},
            )

    def _append_update(self, db: sqlite3.Connection, run_id: str,
                       update_type: str, payload: dict[str, Any]) -> int:
        row = db.execute(
            "SELECT COALESCE(MAX(commit_seq), 0) + 1 AS next_seq "
            "FROM run_updates WHERE run_id=?", (run_id,)
        ).fetchone()
        sequence = int(row["next_seq"])
        db.execute(
            "INSERT INTO run_updates VALUES (?, ?, ?, ?, ?)",
            (run_id, sequence, update_type, dumps(payload), now()),
        )
        return sequence

    def updates_after(self, run_id: str, after: int = 0,
                      limit: int = 100) -> list[dict[str, Any]]:
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise BackendValidationError([{
                "path": "updates", "code": "INVALID_CURSOR",
                "message": "after must be non-negative and limit must be 1..200.",
            }])
        self.get_run(run_id)
        rows = self.connection.execute(
            "SELECT * FROM run_updates WHERE run_id=? AND commit_seq>? "
            "ORDER BY commit_seq LIMIT ?",
            (run_id, after, limit),
        ).fetchall()
        return [{
            "run_id": row["run_id"],
            "commit_seq": row["commit_seq"],
            "type": row["update_type"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        } for row in rows]

    def progress(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        latest = self.connection.execute(
            "SELECT COALESCE(MAX(commit_seq), 0) AS cursor FROM run_updates "
            "WHERE run_id=?", (run_id,)
        ).fetchone()["cursor"]
        sessions = self.sessions(run_id)
        return {
            "run_id": run_id,
            "status": run["status"],
            "execution_epoch": run["execution_epoch"],
            "cursor": int(latest),
            "sessions_completed": sum(s["status"] == "completed" for s in sessions),
            "sessions_total": len(sessions),
        }

    def run_agents(self, run_id: str) -> list[dict[str, Any]]:
        self.get_run(run_id)
        rows = self.connection.execute(
            "SELECT * FROM run_agents WHERE run_id=? ORDER BY ordinal", (run_id,)
        ).fetchall()
        return [
            {
                **{key: row[key] for key in (
                    "run_id", "agent_id", "ordinal", "cohort_id",
                    "cohort_persona_id", "source_persona_id",
                )},
                "persona": json.loads(row["persona_json"]),
                "provenance": json.loads(row["provenance_json"]),
                "field_provenance": json.loads(row["field_provenance_json"]),
            }
            for row in rows
        ]

    def run_relationships(self, run_id: str) -> list[dict[str, Any]]:
        self.get_run(run_id)
        rows = self.connection.execute(
            "SELECT * FROM run_agent_relationships WHERE run_id=? ORDER BY agent_id",
            (run_id,),
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "agent_id": row["agent_id"],
                "brand_id": row["brand_id"],
                "organization_id": row["organization_id"],
                "group_id": row["group_id"],
                "state": json.loads(row["current_state_json"]),
                "provenance": json.loads(row["provenance_json"]),
                "initial_state": json.loads(row["state_json"]),
                "last_event_id": row["last_event_id"],
            }
            for row in rows
        ]

    def set_run_status(self, run_id: str, status: str, failure_code: str | None = None) -> dict[str, Any]:
        if status not in {"ready", "running", "completed", "failed"}:
            raise ValueError("Invalid run status")
        current = self.get_run(run_id)
        allowed = {
            "ready": {"running"},
            "running": {"completed", "failed"},
            "failed": {"running"},
            "completed": set(),
        }
        if status not in allowed[current["status"]]:
            raise BackendConflictError(
                f"Invalid run transition {current['status']} -> {status}"
            )
        timestamp = now()
        with self.transaction() as db:
            db.execute(
                "UPDATE runs SET status=?, failure_code=?, execution_epoch=CASE "
                "WHEN ?='running' AND status='failed' THEN execution_epoch+1 "
                "ELSE execution_epoch END, started_at=CASE WHEN ?='running' "
                "AND started_at IS NULL THEN ? ELSE started_at END, ended_at=CASE "
                "WHEN ? IN ('completed','failed') THEN ? ELSE ended_at END, updated_at=? "
                "WHERE run_id=?",
                (
                    status, failure_code, status, status, timestamp, status,
                    timestamp, timestamp, run_id,
                ),
            )
        return self.get_run(run_id)

    def claim_run(self, run_id: str, *, resume: bool = False) -> dict[str, Any]:
        """Atomically claim a ready run, or a failed run when resuming."""
        current = self.get_run(run_id)
        allowed_status = "failed" if resume else "ready"
        if current["status"] != allowed_status:
            raise BackendConflictError(
                f"Run is not claimable from status {current['status']}"
            )
        timestamp = now()
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM runs WHERE status='running'").fetchone():
                raise BackendConflictError("RUNNER_BUSY")
            cursor = db.execute(
                "UPDATE runs SET status='running', failure_code=NULL, "
                "execution_epoch=CASE WHEN ?='failed' THEN execution_epoch+1 "
                "ELSE execution_epoch END, started_at=COALESCE(started_at, ?), "
                "updated_at=?, ended_at=NULL WHERE run_id=? AND status=?",
                (
                    current["status"], timestamp, timestamp,
                    run_id, allowed_status,
                ),
            )
            if cursor.rowcount != 1:
                raise BackendConflictError("Run was claimed by another worker")
            db.execute(
                "UPDATE model_calls SET status='interrupted', error_code='PROCESS_INTERRUPTED', "
                "updated_at=? WHERE status='started' AND stage_key IN ("
                "SELECT stage_key FROM stage_contexts WHERE run_id=?)", (timestamp, run_id),
            )
            self._append_update(db, run_id, "run_started", {
                "status": "running", "execution_epoch": self.get_run(run_id)["execution_epoch"],
            })
        return self.get_run(run_id)

    def claim_command(
        self, run_id: str, *, operation: str, idempotency_key: str,
        resume: bool = False,
    ) -> dict[str, Any]:
        if operation not in {"start_run", "resume_run"}:
            raise ValueError("Unsupported run command")
        if (
            not isinstance(idempotency_key, str)
            or not 1 <= len(idempotency_key.strip()) <= 128
        ):
            raise BackendValidationError([{
                "path": "Idempotency-Key", "code": "INVALID_IDEMPOTENCY_KEY",
                "message": "Idempotency-Key must contain 1..128 characters.",
            }])
        idempotency_key = idempotency_key.strip()
        request_hash = hash_json({
            "operation": operation, "run_id": run_id,
        })
        with self.transaction() as db:
            existing = db.execute(
                "SELECT * FROM idempotency_keys WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["operation"] != operation or \
                        existing["request_hash"] != request_hash:
                    raise BackendConflictError(
                        "Idempotency-Key was already used with another request"
                    )
                return {**self.get_run(existing["resource_id"]), "newly_claimed": False}
            self.claim_run(run_id, resume=resume)
            db.execute(
                "INSERT INTO idempotency_keys VALUES (?, ?, ?, ?, ?)",
                (idempotency_key, operation, request_hash, run_id, now()),
            )
        return {**self.get_run(run_id), "newly_claimed": True}
