"""
Schema migration runner cho meta.db.

Phase 10: schema v3 là baseline mới. Không có migration nào tới v3 vì wipe
toàn bộ data trước khi deploy. Module này giữ skeleton cho future migrations
(v3 → v4 sau khi schema đổi).

Pattern:
  - Mỗi migration (from_v, to_v) là 1 fn(conn) wrap trong transaction
  - Runner detect current version → apply chain forward
  - Idempotent (CREATE TABLE IF NOT EXISTS, ALTER ... với try/except dup)
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Dict, Tuple

logger = logging.getLogger("ecosim.meta.migrations")


# ──────────────────────────────────────────────
# Migration registry
# ──────────────────────────────────────────────
# Format: (from_version, to_version) → migration_fn(conn)
# Add migration mới: register vào MIGRATIONS dict + bump SCHEMA_VERSION ở
# metadata_index.py.


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """v4: track crisis paths + cached counts on the simulations row.

    Before v4, the only place "this sim has crisis X scheduled / triggered" was
    encoded was inside two JSON files on disk (config.json + crisis_log.json).
    The frontend dashboard had to either parse those files via an API call or
    not know at all. v4 lifts the paths + counts into meta.db so list/overview
    views can render crisis state from a single SELECT, and the API resolves
    the actual file location through the row instead of recomputing it.
    """
    # ALTER TABLE ADD COLUMN — idempotent guard via try/except: re-running the
    # migration on a partially-applied DB shouldn't fail.
    add_columns = [
        ("crisis_log_path", "TEXT"),
        ("crisis_pending_path", "TEXT"),
        ("crisis_count", "INTEGER DEFAULT 0"),
        ("crisis_triggered_count", "INTEGER DEFAULT 0"),
    ]
    for col, ddl in add_columns:
        try:
            conn.execute(f"ALTER TABLE simulations ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise

    # Recreate sim_stats view to expose the new counts. CREATE VIEW IF NOT
    # EXISTS won't replace an existing view, so DROP first.
    conn.execute("DROP VIEW IF EXISTS sim_stats")
    conn.execute(
        """\
CREATE VIEW sim_stats AS
SELECT
  s.sid                                                AS sim_id,
  s.cid                                                AS campaign_id,
  s.status                                             AS sim_status,
  s.num_agents,
  s.num_rounds,
  s.current_round,
  s.created_at,
  s.completed_at,
  s.kg_graph_name,
  s.kg_status,
  s.kg_node_count,
  s.kg_edge_count,
  s.crisis_count,
  s.crisis_triggered_count,
  COUNT(DISTINCT sa.agent_id)                          AS agent_count_actual,
  (SELECT positive FROM sentiment_summaries
     WHERE sid = s.sid ORDER BY round_num DESC LIMIT 1) AS latest_positive,
  (SELECT negative FROM sentiment_summaries
     WHERE sid = s.sid ORDER BY round_num DESC LIMIT 1) AS latest_negative,
  (SELECT neutral FROM sentiment_summaries
     WHERE sid = s.sid ORDER BY round_num DESC LIMIT 1) AS latest_neutral
FROM simulations s
LEFT JOIN simulation_agents sa ON sa.sid = s.sid
GROUP BY s.sid"""
    )


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """v5: add 3 new sim path columns (simulation.log, campaign_context.txt,
    legacy agent_tracking.txt) and rewrite `oasis_db_path` for existing rows.

    The previous resolver convention had `oasis_db_path = oasis.db`, but the
    actual file written by run_simulation is `oasis_simulation.db`. Most
    consumers were hardcoding the correct name and bypassing the column;
    after this migration the column matches reality, so frontend-facing
    endpoints can resolve it from meta.db without surprise.
    """
    add_columns = [
        ("simulation_log_path", "TEXT"),
        ("campaign_context_path", "TEXT"),
        ("tracking_legacy_path", "TEXT"),
    ]
    for col, ddl in add_columns:
        try:
            conn.execute(f"ALTER TABLE simulations ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise

    # Rewrite oasis_db_path for any existing row that points to the old
    # `oasis.db` name. Use REPLACE on the trailing filename so we don't
    # accidentally touch other paths.
    conn.execute(
        "UPDATE simulations SET oasis_db_path = REPLACE(oasis_db_path, "
        "'oasis.db', 'oasis_simulation.db') "
        "WHERE oasis_db_path LIKE '%oasis.db'"
    )


MIGRATIONS: Dict[Tuple[int, int], Callable[[sqlite3.Connection], None]] = {
    (3, 4): _migrate_v3_to_v4,
    (4, 5): _migrate_v4_to_v5,
}


def get_current_version(conn: sqlite3.Connection) -> int:
    """Returns current schema_version, hoặc 0 nếu table chưa có."""
    try:
        cur = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0


def apply_migrations(conn: sqlite3.Connection, target_version: int) -> int:
    """Apply migrations từ current → target_version. Returns count applied.

    No-op nếu already at target. Skip nếu missing migration (warn).
    """
    current = get_current_version(conn)
    if current >= target_version:
        return 0
    if current == 0:
        # Schema chưa init — caller (init_schema()) đã CREATE TABLE IF NOT EXISTS
        # và set version trực tiếp, không cần migration runner.
        return 0

    applied = 0
    while current < target_version:
        next_v = current + 1
        key = (current, next_v)
        if key not in MIGRATIONS:
            logger.warning(
                "No migration registered cho %d → %d. Skip — schema có thể không sync.",
                current, next_v,
            )
            break
        try:
            logger.info("Applying migration %d → %d", current, next_v)
            MIGRATIONS[key](conn)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (next_v,))
            applied += 1
            current = next_v
        except Exception as e:
            logger.error("Migration %d → %d FAILED: %s", current, next_v, e)
            raise
    return applied
