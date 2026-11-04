"""Archived v0 persistence; not used by the backend-v1 runtime."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simulation.personas.relationship import transition_relationship


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    config_snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    UNIQUE(run_id, session_no)
);
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    source_persona_id TEXT,
    persona_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS run_agents (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    ordinal INTEGER NOT NULL,
    PRIMARY KEY(run_id, agent_id),
    UNIQUE(run_id, ordinal)
);
CREATE TABLE IF NOT EXISTS run_agent_relationships (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    organization_id TEXT NOT NULL,
    brand_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    PRIMARY KEY(run_id, agent_id, organization_id, brand_id)
);
CREATE TABLE IF NOT EXISTS run_agent_relationship_states (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    organization_id TEXT NOT NULL,
    brand_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    last_event_id TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(run_id, agent_id, organization_id, brand_id)
);
CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    shop_id TEXT,
    content_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shops (
    shop_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL REFERENCES shops(shop_id),
    product_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_session_posts (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    post_id TEXT NOT NULL REFERENCES posts(post_id),
    position INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    PRIMARY KEY(run_id, session_id, post_id),
    UNIQUE(run_id, session_id, position)
);
CREATE TABLE IF NOT EXISTS run_products (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    shop_id TEXT NOT NULL REFERENCES shops(shop_id),
    product_id TEXT NOT NULL REFERENCES products(product_id),
    position INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    PRIMARY KEY(run_id, shop_id, product_id),
    UNIQUE(run_id, shop_id, position)
);
CREATE TABLE IF NOT EXISTS model_calls (
    call_id TEXT PRIMARY KEY,
    stage_key TEXT NOT NULL,
    event_id TEXT,
    attempt_no INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT,
    input_hash TEXT NOT NULL,
    validation_status TEXT,
    error_code TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(stage_key, attempt_no)
);
CREATE TABLE IF NOT EXISTS stage_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    encounter_no INTEGER NOT NULL,
    stage TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    action TEXT,
    normalized_score REAL,
    parent_event_id TEXT REFERENCES stage_events(event_id),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, session_id, agent_id, sequence_no)
);
CREATE TABLE IF NOT EXISTS event_tags (
    event_id TEXT NOT NULL REFERENCES stage_events(event_id),
    tag_id TEXT NOT NULL,
    normalized_score REAL NOT NULL,
    rank INTEGER NOT NULL,
    selected INTEGER NOT NULL,
    description TEXT NOT NULL,
    PRIMARY KEY(event_id, tag_id)
);
CREATE TABLE IF NOT EXISTS agent_stage_states (
    state_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    latest_session_id TEXT NOT NULL,
    latest_encounter_no INTEGER NOT NULL,
    latest_event_id TEXT NOT NULL REFERENCES stage_events(event_id),
    last_action TEXT,
    last_status TEXT NOT NULL,
    last_score REAL,
    UNIQUE(run_id, agent_id, object_type, object_id, stage)
);
CREATE TABLE IF NOT EXISTS state_tags (
    state_id TEXT NOT NULL REFERENCES agent_stage_states(state_id),
    tag_id TEXT NOT NULL,
    normalized_score REAL NOT NULL,
    rank INTEGER NOT NULL,
    PRIMARY KEY(state_id, tag_id)
);
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    cursor_json TEXT NOT NULL,
    last_event_id TEXT REFERENCES stage_events(event_id),
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id, session_id, agent_id)
);
CREATE TABLE IF NOT EXISTS session_metrics (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),
    agents_processed INTEGER NOT NULL DEFAULT 0,
    posts_attended INTEGER NOT NULL DEFAULT 0,
    products_bought INTEGER NOT NULL DEFAULT 0,
    unresolved_stages INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS metric_snapshots (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    session_no INTEGER NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    numerator REAL NOT NULL,
    denominator REAL,
    session_value REAL,
    cumulative_numerator REAL NOT NULL,
    cumulative_denominator REAL,
    cumulative_value REAL,
    calculation_version TEXT NOT NULL,
    PRIMARY KEY (
        run_id, session_id, scope_type, scope_id, metric_name,
        calculation_version
    )
);
CREATE TABLE IF NOT EXISTS stage_contexts (
    stage_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    snapshot_json TEXT NOT NULL
);
"""


class SqliteSimulationStore:
    """The only module in the runtime that knows SQL and transactions."""

    def __init__(self, path: str | Path = ":memory:"):
        self.database_path = str(path)
        self.connection = sqlite3.connect(self.database_path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self._migrate_checkpoints()

    def _migrate_checkpoints(self) -> None:
        columns = {row["name"] for row in self.connection.execute(
            "PRAGMA table_info(checkpoints)")}
        if "agent_id" in columns:
            return
        # Keep the old session-wide cursor intact for audit; derive per-agent
        # cursors from committed events, never guess from the overwritten cursor.
        start = SCHEMA.index("CREATE TABLE IF NOT EXISTS checkpoints")
        end = SCHEMA.index(";", start) + 1
        with self.connection:
            self.connection.execute("ALTER TABLE checkpoints RENAME TO checkpoints_legacy_v1")
            self.connection.execute(SCHEMA[start:end])
            events = self.connection.execute(
                "SELECT e.* FROM stage_events e WHERE e.sequence_no=("
                "SELECT MAX(x.sequence_no) FROM stage_events x WHERE "
                "x.run_id=e.run_id AND x.session_id=e.session_id AND x.agent_id=e.agent_id)"
            ).fetchall()
            for event in events:
                cursor = {key: event[key] for key in (
                    "session_id", "agent_id", "object_type", "object_id", "stage")}
                self.connection.execute(
                    "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, 'committed', ?)",
                    (str(uuid.uuid4()), event["run_id"], event["session_id"],
                     event["agent_id"], _json(cursor), event["event_id"], event["created_at"]),
                )

    def close(self) -> None:
        self.connection.close()

    def run_snapshot(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT config_snapshot_json FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown run")
        return json.loads(row[0])

    def context_snapshot(self, stage_key: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT snapshot_json FROM stage_contexts WHERE stage_key=?", (stage_key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_context(self, stage_key: str, run_id: str, snapshot: dict[str, Any]) -> None:
        serialized = _json(snapshot)
        with self.connection:
            row = self.connection.execute(
                "SELECT snapshot_json FROM stage_contexts WHERE stage_key=?", (stage_key,)
            ).fetchone()
            if row is not None:
                if row[0] != serialized:
                    raise ValueError("Conflicting context for the same stage key")
                return
            self.connection.execute(
                "INSERT INTO stage_contexts VALUES (?, ?, ?)",
                (stage_key, run_id, serialized),
            )

    def history_watermark(self, run_id: str) -> int:
        return self.connection.execute(
            "SELECT COALESCE(MAX(rowid), 0) FROM stage_events WHERE run_id=?", (run_id,)
        ).fetchone()[0]

    def history_before(self, run_id: str, agent_id: str, watermark: int) -> list[dict]:
        # ponytail: one sequential writer; add targeted history queries for large runs.
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM stage_events WHERE run_id=? AND agent_id=? AND rowid<=? "
            "ORDER BY rowid", (run_id, agent_id, watermark),
        )]

    def event(self, event_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM stage_events WHERE event_id=?", (event_id,)
        ).fetchone()
        return dict(row) if row else None

    def product_encounter(self, run_id: str, agent_id: str, product_id: str,
                          visit_event_id: str) -> int:
        row = self.connection.execute(
            "SELECT encounter_no FROM stage_events WHERE run_id=? AND agent_id=? "
            "AND object_type='product' AND object_id=? AND stage='B1' "
            "AND parent_event_id=?", (run_id, agent_id, product_id, visit_event_id),
        ).fetchone()
        return row[0] if row else self.next_encounter(run_id, agent_id, "product", product_id)

    @staticmethod
    def stage_key(run_id: str, session_id: str, agent_id: str,
                  object_type: str, object_id: str, encounter_no: int,
                  stage: str) -> str:
        return "|".join(map(str, (
            run_id, session_id, agent_id, object_type, object_id, encounter_no, stage
        )))

    def create_run(self, run_id: str, scenario_id: str, policy_version: str,
                   config_snapshot: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, 'running')",
            (run_id, scenario_id, policy_version, _json(config_snapshot)),
        )
        self.connection.commit()

    def add_session(self, run_id: str, session_id: str, session_no: int) -> None:
        self.connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, 'pending')",
            (session_id, run_id, session_no),
        )
        self.connection.commit()

    def add_agent(self, run_id: str, agent_id: str, ordinal: int,
                  source_persona_id: str | None = None,
                  persona: dict[str, Any] | None = None) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO agents VALUES (?, ?, ?)",
            (agent_id, source_persona_id, _json(persona or {})),
        )
        self.connection.execute(
            "INSERT INTO run_agents VALUES (?, ?, ?)",
            (run_id, agent_id, ordinal),
        )
        self.connection.commit()

    def add_relationship(self, run_id: str, assignment: dict[str, Any]) -> None:
        state = assignment["state"]
        with self.connection:
            self.connection.execute(
                "INSERT INTO run_agent_relationships VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    assignment["agent_id"],
                    assignment["organization_id"],
                    assignment["brand_id"],
                    assignment["group_id"],
                    _json(state),
                    _json(assignment.get("provenance", {})),
                ),
            )
            self.connection.execute(
                "INSERT INTO run_agent_relationship_states VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (
                    run_id,
                    assignment["agent_id"],
                    assignment["organization_id"],
                    assignment["brand_id"],
                    _json(state),
                    _now(),
                ),
            )

    def relationship(self, run_id: str, agent_id: str,
                     organization_id: str, brand_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM run_agent_relationships "
            "WHERE run_id=? AND agent_id=? AND organization_id=? AND brand_id=?",
            (run_id, agent_id, organization_id, brand_id),
        ).fetchone()
        if row is None:
            return None
        state_row = self.connection.execute(
            "SELECT state_json, last_event_id, updated_at "
            "FROM run_agent_relationship_states "
            "WHERE run_id=? AND agent_id=? AND organization_id=? AND brand_id=?",
            (run_id, agent_id, organization_id, brand_id),
        ).fetchone()
        return {
            "run_id": row["run_id"],
            "agent_id": row["agent_id"],
            "organization_id": row["organization_id"],
            "brand_id": row["brand_id"],
            "group_id": row["group_id"],
            "initial_state": json.loads(row["state_json"]),
            "state": json.loads(state_row["state_json"])
            if state_row is not None else json.loads(row["state_json"]),
            "provenance": json.loads(row["provenance_json"]),
            "last_event_id": state_row["last_event_id"]
            if state_row is not None else None,
            "updated_at": state_row["updated_at"] if state_row is not None else None,
        }

    def relationships(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM run_agent_relationships WHERE run_id=? ORDER BY agent_id",
            (run_id,),
        ).fetchall()
        return [
            self.relationship(
                run_id, row["agent_id"], row["organization_id"], row["brand_id"]
            )
            for row in rows
        ]

    def _relationship_brand_id(self, run_id: str, object_type: str,
                               object_id: str) -> str | None:
        snapshot = self.run_snapshot(run_id)
        collection = snapshot["posts"] if object_type == "article" else snapshot["products"]
        key = "post_id" if object_type == "article" else "product_id"
        item = next((value for value in collection if value.get(key) == object_id), None)
        return item.get("brand_id") if item else None

    def _relationship_brand_identity_visible(
        self, stage_key: str, stage: str, action: str | None,
    ) -> bool:
        if stage == "A5" and action in {"visit", "visit_again"}:
            return True
        context = self.context_snapshot(stage_key)
        if not context:
            return False
        visible_tags = context.get("input", {}).get("visible_tags", [])
        return any(
            isinstance(tag, dict)
            and str(tag.get("tag_id", "")).startswith("enterprise.")
            for tag in visible_tags
        )

    def _advance_relationship(
        self, *, run_id: str, agent_id: str, object_type: str,
        object_id: str, stage_key: str, stage: str, action: str | None,
        status: str, event_id: str, selected_tags: list[dict[str, Any]],
    ) -> None:
        if status != "resolved":
            return
        brand_id = self._relationship_brand_id(run_id, object_type, object_id)
        snapshot = self.run_snapshot(run_id)
        if not brand_id:
            return
        relationship = self.relationship(
            run_id, agent_id, snapshot["organization_id"], brand_id
        )
        if relationship is None:
            return
        next_state = transition_relationship(
            relationship["state"],
            {
                "stage": stage,
                "action": action,
                "status": status,
                "brand_identity_visible": self._relationship_brand_identity_visible(
                    stage_key, stage, action
                ),
                "tags": selected_tags,
            },
        )
        self.connection.execute(
            "UPDATE run_agent_relationship_states SET state_json=?, "
            "last_event_id=?, updated_at=? WHERE run_id=? AND agent_id=? "
            "AND organization_id=? AND brand_id=?",
            (
                _json(next_state), event_id, _now(),
                run_id, agent_id, snapshot["organization_id"], brand_id,
            ),
        )

    def add_shop(self, shop_id: str, profile: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO shops VALUES (?, ?)", (shop_id, _json(profile))
        )
        self.connection.commit()

    def add_post(self, post_id: str, shop_id: str | None,
                 content: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO posts VALUES (?, ?, ?)",
            (post_id, shop_id, _json(content)),
        )
        self.connection.commit()

    def add_product(self, product_id: str, shop_id: str,
                    product: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO products VALUES (?, ?, ?)",
            (product_id, shop_id, _json(product)),
        )
        self.connection.commit()

    def schedule_post(self, run_id: str, session_id: str, post_id: str,
                      position: int, snapshot: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO run_session_posts VALUES (?, ?, ?, ?, ?)",
            (run_id, session_id, post_id, position, _json(snapshot)),
        )
        self.connection.commit()

    def schedule_product(self, run_id: str, shop_id: str, product_id: str,
                         position: int, snapshot: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO run_products VALUES (?, ?, ?, ?, ?)",
            (run_id, shop_id, product_id, position, _json(snapshot)),
        )
        self.connection.commit()

    def sessions(self, run_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM sessions WHERE run_id = ? ORDER BY session_no",
            (run_id,),
        ).fetchall()

    def session(self, session_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()

    def set_session_status(self, session_id: str, status: str) -> None:
        self.connection.execute(
            "UPDATE sessions SET status=? WHERE session_id=?", (status, session_id)
        )
        self.connection.commit()

    def agents(self, run_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT a.* FROM run_agents ra JOIN agents a ON a.agent_id = ra.agent_id "
            "WHERE ra.run_id = ? ORDER BY ra.ordinal",
            (run_id,),
        ).fetchall()

    def posts(self, run_id: str, session_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT rsp.*, p.shop_id, p.content_json FROM run_session_posts rsp "
            "JOIN posts p ON p.post_id = rsp.post_id "
            "WHERE rsp.run_id = ? AND rsp.session_id = ? ORDER BY rsp.position",
            (run_id, session_id),
        ).fetchall()

    def products(self, run_id: str, shop_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT rp.*, p.product_json FROM run_products rp "
            "JOIN products p ON p.product_id = rp.product_id "
            "WHERE rp.run_id = ? AND rp.shop_id = ? ORDER BY rp.position",
            (run_id, shop_id),
        ).fetchall()

    def next_encounter(self, run_id: str, agent_id: str,
                       object_type: str, object_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(encounter_no), 0) + 1 AS next_no "
            "FROM stage_events WHERE run_id=? AND agent_id=? AND object_type=? AND object_id=?",
            (run_id, agent_id, object_type, object_id),
        ).fetchone()
        return int(row["next_no"])

    def article_encounter(self, run_id: str, session_id: str,
                          post_id: str) -> int:
        row = self.connection.execute(
            "SELECT s.session_no FROM sessions s "
            "JOIN run_session_posts rsp ON rsp.session_id=s.session_id "
            "WHERE rsp.run_id=? AND rsp.session_id=? AND rsp.post_id=?",
            (run_id, session_id, post_id),
        ).fetchone()
        if row is None:
            raise ValueError("Post is not scheduled in this session")
        count = self.connection.execute(
            "SELECT COUNT(*) AS total FROM run_session_posts rsp "
            "JOIN sessions s ON s.session_id=rsp.session_id "
            "WHERE rsp.run_id=? AND rsp.post_id=? AND s.session_no <= ?",
            (run_id, post_id, row["session_no"]),
        ).fetchone()
        return int(count["total"])

    def shop_encounter(self, run_id: str, session_id: str,
                       post_position: int, shop_id: str) -> int:
        current = self.connection.execute(
            "SELECT session_no FROM sessions WHERE session_id=? AND run_id=?",
            (session_id, run_id),
        ).fetchone()
        if current is None:
            raise ValueError("Unknown session")
        count = self.connection.execute(
            "SELECT COUNT(*) AS total FROM run_session_posts rsp "
            "JOIN sessions s ON s.session_id=rsp.session_id "
            "JOIN posts p ON p.post_id=rsp.post_id "
            "WHERE rsp.run_id=? AND p.shop_id=? "
            "AND (s.session_no < ? OR "
            "(s.session_no = ? AND rsp.position <= ?))",
            (run_id, shop_id, current["session_no"], current["session_no"],
             post_position),
        ).fetchone()
        return int(count["total"])

    def event_by_key(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM stage_events WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    def events_until_session(self, run_id: str, session_no: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT e.*, mc.response_json AS model_response_json "
            "FROM stage_events e "
            "JOIN sessions s ON s.session_id=e.session_id "
            "LEFT JOIN model_calls mc ON mc.call_id=("
            " SELECT call_id FROM model_calls WHERE event_id=e.event_id "
            " ORDER BY attempt_no DESC, call_id LIMIT 1) "
            "WHERE e.run_id=? AND s.session_no<=? "
            "ORDER BY s.session_no, e.agent_id, e.sequence_no",
            (run_id, session_no),
        ).fetchall()
        events = {row["event_id"]: {**dict(row), "tags": []} for row in rows}
        tags = self.connection.execute(
            "SELECT t.* FROM event_tags t "
            "JOIN stage_events e ON e.event_id=t.event_id "
            "JOIN sessions s ON s.session_id=e.session_id "
            "WHERE e.run_id=? AND s.session_no<=? ORDER BY t.rank",
            (run_id, session_no),
        )
        for tag in tags:
            events[tag["event_id"]]["tags"].append(dict(tag))
        return list(events.values())

    def model_usage(self, run_id: str) -> dict[str, Any]:
        """Aggregate provider-reported token usage for a completed run."""
        rows = self.connection.execute(
            "SELECT mc.response_json, s.session_id, s.session_no "
            "FROM model_calls mc "
            "JOIN stage_events e ON ("
            "mc.stage_key=e.idempotency_key OR "
            "mc.stage_key LIKE e.idempotency_key || '#%') "
            "JOIN sessions s ON s.session_id=e.session_id "
            "WHERE e.run_id=? "
            "ORDER BY s.session_no, mc.call_id",
            (run_id,),
        ).fetchall()
        summary = {
            "attempts": len(rows),
            "usage_records": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
            "cost_records": 0,
            "by_session": [],
        }
        by_session: dict[str, dict[str, Any]] = {}
        for row in rows:
            session = by_session.setdefault(row["session_id"], {
                "session_id": row["session_id"],
                "session_no": row["session_no"],
                "attempts": 0,
                "usage_records": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
                "cost_records": 0,
            })
            session["attempts"] += 1
            payload = json.loads(row["response_json"] or "{}")
            usage = payload.get("usage")
            if not isinstance(usage, dict):
                continue
            summary["usage_records"] += 1
            session["usage_records"] += 1
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int) and value >= 0:
                    summary[key] += value
                    session[key] += value
            cost = usage.get("cost")
            if isinstance(cost, (int, float)) and cost >= 0:
                summary["cost"] += float(cost)
                summary["cost_records"] += 1
                session["cost"] += float(cost)
                session["cost_records"] += 1
        summary["by_session"] = sorted(
            by_session.values(), key=lambda item: item["session_no"]
        )
        return summary

    def save_session_projection(self, run_id: str, session_id: str,
                                snapshots: list[dict[str, Any]],
                                summary: dict[str, int], *, complete: bool) -> None:
        """Publish metrics and completion together; a failed write rolls back both."""
        if not snapshots:
            raise ValueError("A session projection must contain metrics")
        session = self.session(session_id)
        if session is None or session["run_id"] != run_id:
            raise ValueError("Unknown run/session")
        for item in snapshots:
            if (item["run_id"], item["session_id"], item["session_no"]) != (
                    run_id, session_id, session["session_no"]):
                raise ValueError("Metric scope does not match the session")
        with self.connection:
            for item in snapshots:
                self.connection.execute(
                    """
                    INSERT INTO metric_snapshots (
                        run_id, session_id, session_no, scope_type, scope_id,
                        metric_name, numerator, denominator, session_value,
                        cumulative_numerator, cumulative_denominator,
                        cumulative_value, calculation_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (
                        run_id, session_id, scope_type, scope_id, metric_name,
                        calculation_version
                    ) DO UPDATE SET
                        session_no=excluded.session_no,
                        numerator=excluded.numerator,
                        denominator=excluded.denominator,
                        session_value=excluded.session_value,
                        cumulative_numerator=excluded.cumulative_numerator,
                        cumulative_denominator=excluded.cumulative_denominator,
                        cumulative_value=excluded.cumulative_value
                    """,
                    (
                        item["run_id"], item["session_id"], item["session_no"],
                        item["scope_type"], item["scope_id"], item["metric_name"],
                        item["numerator"], item["denominator"],
                        item["session_value"], item["cumulative_numerator"],
                        item["cumulative_denominator"], item["cumulative_value"],
                        item["calculation_version"],
                    ),
                )
            self.connection.execute(
                "INSERT INTO session_metrics VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "agents_processed=excluded.agents_processed, "
                "posts_attended=excluded.posts_attended, "
                "products_bought=excluded.products_bought, "
                "unresolved_stages=excluded.unresolved_stages",
                (session_id, summary["agents_processed"], summary["posts_attended"],
                 summary["products_bought"], summary["unresolved_stages"]),
            )
            if complete:
                self.connection.execute(
                    "UPDATE sessions SET status='completed' WHERE session_id=?",
                    (session_id,),
                )

    def metric_snapshots(
        self, run_id: str, calculation_version: str,
        session_id: str | None = None, metric_name: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["m.run_id=?", "m.calculation_version=?", "s.status='completed'"]
        values: list[Any] = [run_id, calculation_version]
        if session_id is not None:
            clauses.append("m.session_id=?")
            values.append(session_id)
        if metric_name is not None:
            clauses.append("m.metric_name=?")
            values.append(metric_name)
        rows = self.connection.execute(
            "SELECT m.* FROM metric_snapshots m "
            "JOIN sessions s ON s.session_id=m.session_id WHERE " +
            " AND ".join(clauses) + " ORDER BY m.session_no, m.metric_name",
            values,
        ).fetchall()
        return [dict(row) for row in rows]

    def has_action(self, run_id: str, agent_id: str, object_type: str,
                   object_id: str, stage: str, actions: set[str]) -> bool:
        marks = ",".join("?" for _ in actions)
        values = [run_id, agent_id, object_type, object_id, stage, *sorted(actions)]
        row = self.connection.execute(
            f"SELECT 1 FROM stage_events WHERE run_id=? AND agent_id=? "
            f"AND object_type=? AND object_id=? AND stage=? AND action IN ({marks}) LIMIT 1",
            values,
        ).fetchone()
        return row is not None

    def history(self, run_id: str, agent_id: str, object_type: str,
                object_id: str, stage: str) -> dict[str, Any]:
        rows = self.connection.execute(
            "SELECT e.action FROM stage_events e "
            "JOIN sessions s ON s.session_id=e.session_id "
            "WHERE e.run_id=? AND e.agent_id=? AND e.object_type=? "
            "AND e.object_id=? AND e.stage=? AND e.status='resolved' "
            "ORDER BY s.session_no, e.sequence_no",
            (run_id, agent_id, object_type, object_id, stage),
        ).fetchall()
        actions = [row["action"] for row in rows if row["action"]]
        if stage == "A4":
            reaction = None
            for action in actions:
                if action == "like":
                    reaction = "like"
                elif action == "dislike":
                    reaction = "dislike"
                elif action == "remove_reaction":
                    reaction = None
            return {"current_reaction": reaction}
        if stage == "A5":
            return {"shop_visit_count": sum(action in {"visit", "visit_again"}
                                            for action in actions)}
        if stage == "B3":
            return {"purchase_count": sum(action in {"buy", "buy_again"}
                                          for action in actions)}
        if stage in {"A1", "A1R", "B1", "B1R"}:
            return {
                "attention_count": sum(
                    action in {"attend", "attend_again"} for action in actions
                )
            }
        return {}

    def latest_state(self, run_id: str, agent_id: str, object_type: str,
                     object_id: str, stage: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM agent_stage_states WHERE run_id=? AND agent_id=? "
            "AND object_type=? AND object_id=? AND stage=?",
            (run_id, agent_id, object_type, object_id, stage),
        ).fetchone()
        if row is None:
            return None
        tags = self.connection.execute(
            "SELECT tag_id, normalized_score, rank FROM state_tags "
            "WHERE state_id=? ORDER BY rank",
            (row["state_id"],),
        ).fetchall()
        return {
            "run_id": run_id,
            "agent_id": agent_id,
            "object_type": object_type,
            "object_id": object_id,
            "stage": stage,
            "encounter_no": row["latest_encounter_no"],
            "status": row["last_status"],
            "score": row["last_score"],
            "action": row["last_action"],
            "tags": [dict(tag) for tag in tags],
        }

    def event_state(self, event_id: str | None) -> dict[str, Any] | None:
        if event_id is None:
            return None
        row = self.connection.execute(
            "SELECT * FROM stage_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            return None
        tags = self.connection.execute(
            "SELECT tag_id, normalized_score, rank FROM event_tags "
            "WHERE event_id=? AND selected=1 ORDER BY rank",
            (event_id,),
        ).fetchall()
        return {
            "run_id": row["run_id"],
            "agent_id": row["agent_id"],
            "object_type": row["object_type"],
            "object_id": row["object_id"],
            "stage": row["stage"],
            "encounter_no": row["encounter_no"],
            "status": row["status"],
            "score": row["normalized_score"],
            "action": row["action"],
            "tags": [dict(tag) for tag in tags],
        }

    def start_model_call(self, stage_key: str, request: dict[str, Any],
                         provider: str, model: str) -> tuple[str, int]:
        with self.connection:
            row = self.connection.execute(
                "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS next_no "
                "FROM model_calls WHERE stage_key=?",
                (stage_key,),
            ).fetchone()
            attempt_no = int(row["next_no"])
            call_id = str(uuid.uuid4())
            now = _now()
            input_hash = hashlib.sha256(_json(request).encode()).hexdigest()
            self.connection.execute(
                "INSERT INTO model_calls "
                "(call_id, stage_key, attempt_no, provider, model, request_json, "
                "input_hash, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?, ?)",
                (call_id, stage_key, attempt_no, provider, model, _json(request),
                 input_hash, now, now),
            )
            return call_id, attempt_no

    def commit_model_attempt(self, call_id: str, response: dict[str, Any],
                             validation_status: str) -> None:
        with self.connection:
            now = _now()
            self.connection.execute(
                "UPDATE model_calls SET response_json=?, validation_status=?, "
                "status='responded', updated_at=? WHERE call_id=?",
                (_json(response), validation_status, now, call_id),
            )

    def set_model_identity(self, call_id: str, provider: str, model: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE model_calls SET provider=?, model=?, updated_at=? WHERE call_id=?",
                (provider, model, _now(), call_id),
            )

    def fail_model_attempt(self, call_id: str, error_code: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE model_calls SET error_code=?, status='failed', updated_at=? "
                "WHERE call_id=?",
                (error_code, _now(), call_id),
            )

    def commit_stage(self, *, call_id: str, stage_key: str, response: dict[str, Any],
                     result: dict[str, Any], run_id: str, session_id: str,
                     agent_id: str, object_type: str, object_id: str,
                     encounter_no: int, stage: str, parent_event_id: str | None,
                     cursor: dict[str, Any]) -> dict[str, Any]:
        with self.connection:
            return self._commit_stage(
                call_id=call_id, stage_key=stage_key, response=response,
                result=result, run_id=run_id, session_id=session_id,
                agent_id=agent_id, object_type=object_type, object_id=object_id,
                encounter_no=encounter_no, stage=stage,
                parent_event_id=parent_event_id, cursor=cursor,
            )

    def _commit_stage(self, *, call_id: str, stage_key: str, response: dict[str, Any],
                      result: dict[str, Any], run_id: str, session_id: str,
                      agent_id: str, object_type: str, object_id: str,
                      encounter_no: int, stage: str, parent_event_id: str | None,
                      cursor: dict[str, Any]) -> dict[str, Any]:
        existing = self.connection.execute(
            "SELECT * FROM stage_events WHERE idempotency_key=?",
            (stage_key,),
        ).fetchone()
        if existing is not None:
            return dict(existing)

        now = _now()
        validation = result["status"]
        self.connection.execute(
            "UPDATE model_calls SET response_json=?, validation_status=?, status=?, "
            "updated_at=? WHERE call_id=?",
            (_json(response), validation, "responded", now, call_id),
        )
        seq_row = self.connection.execute(
            "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_no FROM stage_events "
            "WHERE run_id=? AND session_id=? AND agent_id=?",
            (run_id, session_id, agent_id),
        ).fetchone()
        sequence_no = int(seq_row["next_no"])
        event_id = str(uuid.uuid4())
        action = result.get("action")
        event_status = result["status"]
        self.connection.execute(
            "INSERT INTO stage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id, run_id, session_id, agent_id, object_type, object_id,
                encounter_no, stage, sequence_no, event_status, action,
                result.get("normalized_score"), parent_event_id, stage_key, now,
            ),
        )

        scores = result.get("scores", [])
        for rank, item in enumerate(scores, start=1):
            selected = any(
                chosen["tag_id"] == item["tag_id"]
                for chosen in result.get("selected_tags", [])
            )
            self.connection.execute(
                "INSERT INTO event_tags VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, item["tag_id"], item["score"], rank, int(selected),
                 item["description"]),
            )

        state_id = str(uuid.uuid4())
        previous = self.connection.execute(
            "SELECT state_id FROM agent_stage_states WHERE run_id=? AND agent_id=? "
            "AND object_type=? AND object_id=? AND stage=?",
            (run_id, agent_id, object_type, object_id, stage),
        ).fetchone()
        if previous is None:
            self.connection.execute(
                "INSERT INTO agent_stage_states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    state_id, run_id, agent_id, object_type, object_id, stage,
                    session_id, encounter_no, event_id, action, event_status,
                    result.get("normalized_score"),
                ),
            )
        else:
            state_id = previous["state_id"]
            self.connection.execute(
                "UPDATE agent_stage_states SET latest_session_id=?, "
                "latest_encounter_no=?, latest_event_id=?, last_action=?, "
                "last_status=?, last_score=? WHERE state_id=?",
                (
                    session_id, encounter_no, event_id, action, event_status,
                    result.get("normalized_score"), state_id,
                ),
            )
            self.connection.execute(
                "DELETE FROM state_tags WHERE state_id=?", (state_id,)
            )
        for rank, item in enumerate(result.get("selected_tags", []), start=1):
            self.connection.execute(
                "INSERT INTO state_tags VALUES (?, ?, ?, ?)",
                (state_id, item["tag_id"], item["score"], rank),
            )

        self._advance_relationship(
            run_id=run_id,
            agent_id=agent_id,
            object_type=object_type,
            object_id=object_id,
            stage_key=stage_key,
            stage=stage,
            action=action,
            status=event_status,
            event_id=event_id,
            selected_tags=result.get("selected_tags", []),
        )
        self.connection.execute(
            "UPDATE model_calls SET event_id=? WHERE call_id=?",
            (event_id, call_id),
        )
        self.connection.execute(
            "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, 'committed', ?)"
            " ON CONFLICT(run_id, session_id, agent_id) DO UPDATE SET "
            "cursor_json=excluded.cursor_json, last_event_id=excluded.last_event_id, "
            "status=excluded.status, updated_at=excluded.updated_at",
            (str(uuid.uuid4()), run_id, session_id, agent_id, _json(cursor),
             event_id, now),
        )
        return {
            "event_id": event_id,
            "sequence_no": sequence_no,
            "status": event_status,
            "action": action,
            "stage": stage,
            "object_id": object_id,
        }

    def finish_run(self, run_id: str, status: str = "completed") -> None:
        self.connection.execute("UPDATE runs SET status=? WHERE run_id=?",
                                (status, run_id))
        self.connection.commit()

    def run_status(self, run_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT status FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return row["status"] if row else None

    def events_for_agent(self, run_id: str, agent_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT e.* FROM stage_events e "
            "JOIN sessions s ON s.session_id=e.session_id "
            "WHERE e.run_id=? AND e.agent_id=? "
            "ORDER BY s.session_no, e.sequence_no",
            (run_id, agent_id),
        ).fetchall()
        return [dict(row) for row in rows]
