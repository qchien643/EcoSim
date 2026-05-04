"""
SQLite metadata index — single source of truth cho metadata + routing.

Phase 10 storage architecture:
  • SQL (meta.db) là entry point cho mọi truy xuất metadata + path resolution
  • FalkorDB là worker cho graph data (multi-tenant: 1 graph per campaign + per sim)
  • Filesystem là blob storage; mỗi file path lưu trong meta.db column

Tables:
  campaigns(cid PK, kg_graph_name, kg_status, kg_*_count, paths...)
  simulations(sid PK, cid FK CASCADE, kg_graph_name, kg_parent_graph, kg_status, paths...)
  simulation_agents(sid FK, agent_id, mbti, ...)
  simulation_events(sid FK, round, action_type, count) — per-round summary
  sentiment_summaries(sid FK, round, positive, negative, neutral)

Views:
  campaign_stats        — per-campaign overview cho dashboard
  sim_stats             — per-sim summary cho list/overview
  sentiment_overview    — per-campaign avg sentiment cho chart

NGUYÊN TẮC:
  • Frontend gửi context {campaign_id, sim_id?} → backend query meta.db
    → resolve kg_graph_name + paths → query FalkorDB hoặc đọc file
  • Frontend KHÔNG bao giờ thấy graph_name hay file path
  • Filesystem là blob — meta.db biết chính xác path từng file
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .config import EcoSimConfig

logger = logging.getLogger("ecosim.meta")

SCHEMA_VERSION = 5

_lock = threading.RLock()
_initialized = False


SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS campaigns (
  -- Identity
  cid                   TEXT PRIMARY KEY,
  name                  TEXT,
  campaign_type         TEXT,
  market                TEXT,
  description           TEXT,

  -- Source upload
  source_filename       TEXT,
  source_size_bytes     INTEGER,

  -- Lifecycle
  status                TEXT DEFAULT 'created',
  created_at            TEXT DEFAULT (datetime('now')),

  -- Filesystem path tracking
  campaign_dir          TEXT,
  source_dir            TEXT,
  extracted_dir         TEXT,
  spec_path             TEXT,
  sections_path         TEXT,
  analyzed_path         TEXT,
  kg_dir                TEXT,
  build_meta_path       TEXT,
  sims_dir              TEXT,

  -- Knowledge Graph metadata (FalkorDB routing target)
  kg_graph_name         TEXT,
  kg_status             TEXT DEFAULT 'not_built',
  kg_built_at           TEXT,
  kg_last_modified_at   TEXT,
  kg_node_count         INTEGER DEFAULT 0,
  kg_edge_count         INTEGER DEFAULT 0,
  kg_episode_count      INTEGER DEFAULT 0,
  kg_embedding_model    TEXT,
  kg_embedding_dim      INTEGER,
  kg_extraction_model   TEXT
);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);
CREATE INDEX IF NOT EXISTS idx_campaigns_kg_status ON campaigns(kg_status);
CREATE INDEX IF NOT EXISTS idx_campaigns_created ON campaigns(created_at DESC);

CREATE TABLE IF NOT EXISTS simulations (
  -- Identity
  sid                   TEXT PRIMARY KEY,
  cid                   TEXT NOT NULL,

  -- Lifecycle
  status                TEXT DEFAULT 'created',
  created_at            TEXT DEFAULT (datetime('now')),
  started_at            TEXT,
  completed_at          TEXT,
  last_accessed_at      TEXT,

  -- Run config
  num_agents            INTEGER,
  num_rounds            INTEGER,
  current_round         INTEGER DEFAULT 0,
  enable_zep_runtime    INTEGER DEFAULT 0,

  -- Filesystem path tracking — NESTED dưới campaign
  sim_dir               TEXT,
  config_path           TEXT,
  profiles_path         TEXT,
  actions_path          TEXT,
  oasis_db_path         TEXT,
  progress_path         TEXT,
  memory_stats_path     TEXT,
  kg_dir                TEXT,
  zep_buffer_path       TEXT,
  posts_chroma_dir      TEXT,
  analysis_dir          TEXT,
  sentiment_path        TEXT,
  tracking_path         TEXT,
  report_dir            TEXT,
  report_log_path       TEXT,
  crisis_log_path       TEXT,
  crisis_pending_path   TEXT,
  simulation_log_path   TEXT,
  campaign_context_path TEXT,
  tracking_legacy_path  TEXT,

  -- Crisis bookkeeping (cached counts so list views don't have to parse files)
  crisis_count           INTEGER DEFAULT 0,  -- scheduled crises in config.json
  crisis_triggered_count INTEGER DEFAULT 0,  -- actually fired (updated by run_simulation)

  -- Knowledge Graph metadata (FalkorDB routing target)
  kg_graph_name         TEXT,
  kg_parent_graph       TEXT,
  kg_status             TEXT DEFAULT 'pending',
  kg_forked_at          TEXT,
  kg_last_modified_at   TEXT,
  kg_node_count         INTEGER DEFAULT 0,
  kg_edge_count         INTEGER DEFAULT 0,
  kg_episode_count      INTEGER DEFAULT 0,

  FOREIGN KEY (cid) REFERENCES campaigns(cid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sim_status ON simulations(status, last_accessed_at);
CREATE INDEX IF NOT EXISTS idx_sim_cid ON simulations(cid);
CREATE INDEX IF NOT EXISTS idx_sim_kg_status ON simulations(kg_status);
CREATE INDEX IF NOT EXISTS idx_sim_kg_parent ON simulations(kg_parent_graph);

CREATE TABLE IF NOT EXISTS simulation_agents (
  sid                   TEXT NOT NULL,
  agent_id              INTEGER NOT NULL,
  realname              TEXT,
  username              TEXT,
  mbti                  TEXT,
  gender                TEXT,
  age                   INTEGER,
  occupation            TEXT,
  base_persona          TEXT,
  evolved_persona       TEXT,
  interest_keywords     TEXT,
  posts_per_week        INTEGER,
  daily_hours           REAL,
  followers             INTEGER,
  PRIMARY KEY (sid, agent_id),
  FOREIGN KEY (sid) REFERENCES simulations(sid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_mbti ON simulation_agents(mbti);

CREATE TABLE IF NOT EXISTS simulation_events (
  sid                   TEXT NOT NULL,
  round_num             INTEGER NOT NULL,
  action_type           TEXT NOT NULL,
  count                 INTEGER DEFAULT 0,
  PRIMARY KEY (sid, round_num, action_type),
  FOREIGN KEY (sid) REFERENCES simulations(sid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_events_round ON simulation_events(sid, round_num);

CREATE TABLE IF NOT EXISTS sentiment_summaries (
  sid                   TEXT NOT NULL,
  round_num             INTEGER NOT NULL,
  positive              INTEGER DEFAULT 0,
  negative              INTEGER DEFAULT 0,
  neutral               INTEGER DEFAULT 0,
  PRIMARY KEY (sid, round_num),
  FOREIGN KEY (sid) REFERENCES simulations(sid) ON DELETE CASCADE
);

-- ──────────────────────────────────────────────
-- ANALYTICAL VIEWS
-- ──────────────────────────────────────────────
DROP VIEW IF EXISTS campaign_stats;
CREATE VIEW campaign_stats AS
SELECT
  c.cid                                                AS campaign_id,
  c.name                                               AS campaign_name,
  c.campaign_type,
  c.market,
  c.created_at,
  c.kg_status,
  c.kg_node_count,
  c.kg_edge_count,
  c.kg_episode_count,
  COUNT(DISTINCT s.sid)                                AS sim_count,
  SUM(CASE WHEN s.status='completed' THEN 1 ELSE 0 END) AS sim_completed,
  SUM(CASE WHEN s.status='running' THEN 1 ELSE 0 END)   AS sim_running,
  COALESCE(SUM(s.num_agents), 0)                       AS total_agents_generated,
  MAX(s.last_accessed_at)                              AS last_activity_at
FROM campaigns c
LEFT JOIN simulations s ON s.cid = c.cid
GROUP BY c.cid;

DROP VIEW IF EXISTS sim_stats;
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
GROUP BY s.sid;

DROP VIEW IF EXISTS sentiment_overview;
CREATE VIEW sentiment_overview AS
SELECT
  s.cid                                                AS campaign_id,
  COUNT(DISTINCT s.sid)                                AS sim_count,
  ROUND(AVG(ss.positive), 1)                           AS avg_positive,
  ROUND(AVG(ss.negative), 1)                           AS avg_negative,
  ROUND(AVG(ss.neutral), 1)                            AS avg_neutral,
  SUM(ss.positive + ss.negative + ss.neutral)          AS total_samples
FROM simulations s
JOIN sentiment_summaries ss ON ss.sid = s.sid
WHERE s.status = 'completed'
GROUP BY s.cid;
"""


@contextmanager
def get_conn():
    """Thread-safe SQLite connection. Auto-commit on context exit, rollback on error.

    PRAGMA tuning:
      • foreign_keys=ON       — enforce FK cascade
      • journal_mode=WAL      — concurrent reads + 1 writer
      • synchronous=NORMAL    — WAL với NORMAL an toàn + nhanh hơn FULL ~2-3×
      • cache_size=-20000     — 20MB cache
      • mmap_size=268435456   — 256MB mmap
      • busy_timeout=10000    — 10s wait nếu DB locked
    """
    db_path = EcoSimConfig.meta_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -20000")
        conn.execute("PRAGMA mmap_size = 268435456")
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_schema() -> None:
    """Idempotent schema init. Tạo tất cả tables + views nếu chưa có,
    rồi chạy migration runner để bring an existing DB lên SCHEMA_VERSION
    hiện tại (v.d. v3 → v4 thêm crisis_*_path columns).

    Lưu ý: `executescript(SCHEMA_SQL)` với `CREATE TABLE IF NOT EXISTS`
    KHÔNG sửa table đã có — nếu schema cũ thiếu cột, ta phải dựa vào
    `metadata_migrations.apply_migrations` để ALTER TABLE. Vì vậy migration
    runner BẮT BUỘC chạy sau executescript.
    """
    global _initialized
    if _initialized:
        return
    from .metadata_migrations import apply_migrations
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        cur = conn.execute("SELECT COUNT(*) FROM schema_version")
        if cur.fetchone()[0] == 0:
            # Fresh DB → SCHEMA_SQL đã tạo sẵn ở phiên bản mới nhất
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        else:
            # Existing DB → chạy migration chain nếu chưa lên v hiện tại
            applied = apply_migrations(conn, SCHEMA_VERSION)
            if applied:
                logger.info("Applied %d migration(s) bringing DB to v%d", applied, SCHEMA_VERSION)
    _initialized = True
    logger.info("Metadata DB schema v%d ready: %s", SCHEMA_VERSION, EcoSimConfig.meta_db_path())


# ──────────────────────────────────────────────
# Campaign helpers
# ──────────────────────────────────────────────
def upsert_campaign(
    cid: str,
    *,
    name: str = "",
    campaign_type: str = "",
    market: str = "",
    description: str = "",
    source_filename: str = "",
    source_size_bytes: int = 0,
    created_at: Optional[str] = None,
    status: str = "created",
) -> None:
    """Insert or update campaign row. Idempotent.

    Auto-set kg_graph_name = cid + populate paths after upsert.
    """
    init_schema()
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO campaigns (cid, name, campaign_type, market, description,
                source_filename, source_size_bytes, created_at, status, kg_graph_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(cid) DO UPDATE SET
                 name = excluded.name,
                 campaign_type = excluded.campaign_type,
                 market = excluded.market,
                 description = COALESCE(NULLIF(excluded.description, ''), campaigns.description),
                 source_filename = excluded.source_filename,
                 source_size_bytes = excluded.source_size_bytes,
                 status = excluded.status""",
            (cid, name, campaign_type, market, description,
             source_filename, source_size_bytes, created_at, status, cid),
        )
    # Populate path columns (convention-based, idempotent)
    try:
        from .path_resolver import populate_campaign_paths
        populate_campaign_paths(cid)
    except Exception as e:
        logger.debug("populate_campaign_paths skip: %s", e)


def update_campaign_kg_status(
    cid: str,
    *,
    status: Optional[str] = None,
    node_count: Optional[int] = None,
    edge_count: Optional[int] = None,
    episode_count: Optional[int] = None,
    embedding_model: Optional[str] = None,
    embedding_dim: Optional[int] = None,
    extraction_model: Optional[str] = None,
    set_built_at: bool = False,
    set_modified_at: bool = True,
) -> None:
    """Update KG status fields cho campaign. Tất cả args optional → only update non-None."""
    init_schema()
    fields: List[str] = []
    params: List[Any] = []
    if status is not None:
        fields.append("kg_status = ?")
        params.append(status)
        # Auto-update top-level status nếu kg_status đổi sang ready/error
        if status == "ready":
            fields.append("status = 'ready'")
        elif status == "error":
            fields.append("status = 'failed'")
        elif status == "building":
            fields.append("status = 'building'")
    if node_count is not None:
        fields.append("kg_node_count = ?")
        params.append(node_count)
    if edge_count is not None:
        fields.append("kg_edge_count = ?")
        params.append(edge_count)
    if episode_count is not None:
        fields.append("kg_episode_count = ?")
        params.append(episode_count)
    if embedding_model is not None:
        fields.append("kg_embedding_model = ?")
        params.append(embedding_model)
    if embedding_dim is not None:
        fields.append("kg_embedding_dim = ?")
        params.append(embedding_dim)
    if extraction_model is not None:
        fields.append("kg_extraction_model = ?")
        params.append(extraction_model)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if set_built_at:
        fields.append("kg_built_at = ?")
        params.append(ts)
    if set_modified_at:
        fields.append("kg_last_modified_at = ?")
        params.append(ts)
    if not fields:
        return
    params.append(cid)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE campaigns SET {', '.join(fields)} WHERE cid = ?",
            params,
        )


def list_campaigns() -> List[Dict[str, Any]]:
    init_schema()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM campaigns ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_campaign(cid: str) -> Optional[Dict[str, Any]]:
    init_schema()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE cid = ?", (cid,)).fetchone()
        return dict(row) if row else None


def get_campaign_graph(cid: str) -> Optional[Dict[str, Any]]:
    """Lightweight query cho graph routing: chỉ kg_* fields."""
    init_schema()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT cid, kg_graph_name, kg_status, kg_built_at, kg_last_modified_at,
                      kg_node_count, kg_edge_count, kg_episode_count,
                      kg_embedding_model, kg_embedding_dim
               FROM campaigns WHERE cid = ?""",
            (cid,),
        ).fetchone()
        return dict(row) if row else None


def delete_campaign(cid: str) -> None:
    """Cascade delete (campaign + sims + agents + events). Filesystem KHÔNG đụng."""
    init_schema()
    with get_conn() as conn:
        conn.execute("DELETE FROM campaigns WHERE cid = ?", (cid,))


# ──────────────────────────────────────────────
# Simulation helpers
# ──────────────────────────────────────────────
def upsert_simulation(
    sid: str,
    cid: str,
    *,
    status: str = "created",
    num_agents: int = 0,
    num_rounds: int = 0,
    current_round: int = 0,
    created_at: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    last_accessed_at: Optional[str] = None,
    enable_zep_runtime: Optional[bool] = None,
) -> None:
    """Insert/update sim row. Auto-set kg_graph_name='sim_<sid>' + kg_parent_graph=cid."""
    init_schema()
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if last_accessed_at is None:
        last_accessed_at = created_at
    zep_int = int(bool(enable_zep_runtime)) if enable_zep_runtime is not None else 0
    # Sim graph name canonical = "sim_" + sid (sid không có prefix sẵn)
    kg_graph_name = sid if sid.startswith("sim_") else f"sim_{sid}"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO simulations (sid, cid, status, num_agents, num_rounds,
                  current_round, created_at, started_at, completed_at,
                  last_accessed_at, enable_zep_runtime,
                  kg_graph_name, kg_parent_graph, kg_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(sid) DO UPDATE SET
                 status = excluded.status,
                 num_agents = excluded.num_agents,
                 num_rounds = excluded.num_rounds,
                 current_round = excluded.current_round,
                 started_at = COALESCE(excluded.started_at, simulations.started_at),
                 completed_at = COALESCE(excluded.completed_at, simulations.completed_at),
                 last_accessed_at = excluded.last_accessed_at,
                 enable_zep_runtime = excluded.enable_zep_runtime""",
            (sid, cid, status, num_agents, num_rounds, current_round,
             created_at, started_at, completed_at, last_accessed_at,
             zep_int, kg_graph_name, cid, "pending"),
        )
    # Populate path columns from convention (REQUIRES cid for nested layout)
    try:
        from .path_resolver import populate_simulation_paths
        populate_simulation_paths(sid, cid)
    except Exception as e:
        logger.debug("populate_simulation_paths skip: %s", e)


def update_sim_status(
    sid: str,
    status: str,
    *,
    current_round: Optional[int] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> None:
    init_schema()
    fields = ["status = ?"]
    params: List[Any] = [status]
    if current_round is not None:
        fields.append("current_round = ?")
        params.append(current_round)
    if started_at is not None:
        fields.append("started_at = ?")
        params.append(started_at)
    if completed_at is not None:
        fields.append("completed_at = ?")
        params.append(completed_at)
    fields.append("last_accessed_at = ?")
    params.append(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    params.append(sid)
    with get_conn() as conn:
        conn.execute(f"UPDATE simulations SET {', '.join(fields)} WHERE sid = ?", params)


def update_sim_kg_status(
    sid: str,
    *,
    status: Optional[str] = None,
    node_count: Optional[int] = None,
    edge_count: Optional[int] = None,
    episode_count: Optional[int] = None,
    set_forked_at: bool = False,
    set_modified_at: bool = True,
) -> None:
    """Update KG status fields cho sim."""
    init_schema()
    fields: List[str] = []
    params: List[Any] = []
    if status is not None:
        fields.append("kg_status = ?")
        params.append(status)
    if node_count is not None:
        fields.append("kg_node_count = ?")
        params.append(node_count)
    if edge_count is not None:
        fields.append("kg_edge_count = ?")
        params.append(edge_count)
    if episode_count is not None:
        fields.append("kg_episode_count = ?")
        params.append(episode_count)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if set_forked_at:
        fields.append("kg_forked_at = ?")
        params.append(ts)
    if set_modified_at:
        fields.append("kg_last_modified_at = ?")
        params.append(ts)
    if not fields:
        return
    params.append(sid)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE simulations SET {', '.join(fields)} WHERE sid = ?",
            params,
        )


def update_sim_crisis_status(
    sid: str,
    *,
    crisis_count: Optional[int] = None,
    triggered_count: Optional[int] = None,
) -> None:
    """Update cached crisis counts on a sim row.

    `crisis_count` is set once at /prepare from the length of `crisis_events`
    in config.json. `triggered_count` is updated by run_simulation each time
    a crisis fires (matches `len(crisis_engine.triggered_log)`). Both are
    cheap to keep in sync and let list views render "1/3 crises triggered"
    badges without parsing crisis_log.json.
    """
    init_schema()
    fields: List[str] = []
    params: List[Any] = []
    if crisis_count is not None:
        fields.append("crisis_count = ?")
        params.append(int(crisis_count))
    if triggered_count is not None:
        fields.append("crisis_triggered_count = ?")
        params.append(int(triggered_count))
    if not fields:
        return
    params.append(sid)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE simulations SET {', '.join(fields)} WHERE sid = ?",
            params,
        )


def touch_sim_access(sid: str) -> None:
    """Update `last_accessed_at`. Best-effort, silent fail."""
    init_schema()
    try:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with get_conn() as conn:
            conn.execute("UPDATE simulations SET last_accessed_at = ? WHERE sid = ?", (ts, sid))
    except Exception as e:
        logger.debug("touch_sim_access skip: %s", e)


def list_simulations(
    *,
    cid: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    init_schema()
    sql = "SELECT * FROM simulations"
    where = []
    params: List[Any] = []
    if cid:
        where.append("cid = ?")
        params.append(cid)
    if status:
        where.append("status = ?")
        params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_simulation(sid: str) -> Optional[Dict[str, Any]]:
    init_schema()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM simulations WHERE sid = ?", (sid,)).fetchone()
        return dict(row) if row else None


def get_sim_graph(sid: str) -> Optional[Dict[str, Any]]:
    """Lightweight query cho graph routing: kg_* fields + parent campaign join."""
    init_schema()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT s.sid, s.cid, s.kg_graph_name, s.kg_parent_graph, s.kg_status,
                      s.kg_forked_at, s.kg_last_modified_at,
                      s.kg_node_count, s.kg_edge_count, s.kg_episode_count,
                      c.kg_embedding_model, c.kg_embedding_dim
               FROM simulations s
               LEFT JOIN campaigns c ON s.cid = c.cid
               WHERE s.sid = ?""",
            (sid,),
        ).fetchone()
        return dict(row) if row else None


def delete_simulation(sid: str) -> None:
    init_schema()
    with get_conn() as conn:
        conn.execute("DELETE FROM simulations WHERE sid = ?", (sid,))


# ──────────────────────────────────────────────
# Agent + event helpers
# ──────────────────────────────────────────────
def upsert_agents(sid: str, agents: Iterable[Dict[str, Any]]) -> int:
    """Bulk replace agents cho 1 sim từ profiles.json. Returns count inserted."""
    init_schema()
    rows = []
    for a in agents:
        interest = a.get("interest_keywords") or a.get("topics") or []
        if isinstance(interest, list):
            interest_str = json.dumps(interest, ensure_ascii=False)
        else:
            interest_str = str(interest)
        rows.append((
            sid, int(a.get("agent_id", 0)),
            (a.get("realname") or a.get("name") or "")[:200],
            (a.get("username") or "")[:200],
            (a.get("mbti") or "")[:4],
            (a.get("gender") or "")[:10],
            int(a.get("age") or 0),
            (a.get("occupation") or a.get("entity_type") or a.get("role") or "")[:200],
            (a.get("base_persona") or a.get("persona") or "")[:2000],
            (a.get("evolved_persona") or "")[:2000],
            interest_str,
            int(a.get("posts_per_week") or 0),
            float(a.get("daily_hours") or 0.0),
            int(a.get("followers") or 0),
        ))
    if not rows:
        return 0
    with get_conn() as conn:
        conn.execute("DELETE FROM simulation_agents WHERE sid = ?", (sid,))
        conn.executemany(
            """INSERT INTO simulation_agents (sid, agent_id, realname, username,
                  mbti, gender, age, occupation, base_persona, evolved_persona,
                  interest_keywords, posts_per_week, daily_hours, followers)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


def upsert_event_summary(sid: str, round_num: int, action_type: str, count: int) -> None:
    """Insert/update per-round action count summary."""
    init_schema()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO simulation_events (sid, round_num, action_type, count)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(sid, round_num, action_type) DO UPDATE SET
                 count = excluded.count""",
            (sid, round_num, action_type, count),
        )


def upsert_sentiment_round(sid: str, round_num: int,
                            positive: int, negative: int, neutral: int) -> None:
    init_schema()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sentiment_summaries (sid, round_num, positive, negative, neutral)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(sid, round_num) DO UPDATE SET
                 positive = excluded.positive,
                 negative = excluded.negative,
                 neutral = excluded.neutral""",
            (sid, round_num, positive, negative, neutral),
        )


# ──────────────────────────────────────────────
# Analytical view queries
# ──────────────────────────────────────────────
def get_campaign_stats(cid: Optional[str] = None) -> List[Dict[str, Any]]:
    """Query view campaign_stats. cid=None → list all campaigns."""
    init_schema()
    with get_conn() as conn:
        if cid:
            rows = conn.execute(
                "SELECT * FROM campaign_stats WHERE campaign_id = ?", (cid,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM campaign_stats ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_sim_stats(
    *, sid: Optional[str] = None, cid: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Query view sim_stats. Filter by sid (1 row) hoặc cid (all sims of campaign)."""
    init_schema()
    with get_conn() as conn:
        if sid:
            rows = conn.execute(
                "SELECT * FROM sim_stats WHERE sim_id = ?", (sid,)
            ).fetchall()
        elif cid:
            rows = conn.execute(
                "SELECT * FROM sim_stats WHERE campaign_id = ? ORDER BY created_at DESC",
                (cid,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sim_stats ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
        return [dict(r) for r in rows]


def get_sentiment_overview(cid: Optional[str] = None) -> List[Dict[str, Any]]:
    """Query view sentiment_overview."""
    init_schema()
    with get_conn() as conn:
        if cid:
            rows = conn.execute(
                "SELECT * FROM sentiment_overview WHERE campaign_id = ?", (cid,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM sentiment_overview").fetchall()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# Bootstrap — rebuild DB từ filesystem state
# ──────────────────────────────────────────────
def bootstrap_from_filesystem() -> Dict[str, int]:
    """Scan disk → populate meta.db. Idempotent.

    Phase 10 layout:
      data/campaigns/<cid>/{source/, extracted/, kg/build_meta.json, sims/<sid>/...}

    Cross-reference với FalkorDB (graph data SoT) để refresh kg_status:
      • Master KG: graph_name=cid → kg_status='ready' (else 'error')
      • Sim KG: graph_name=sim_<sid> → kg_status='ready' nếu graph tồn tại

    Returns: {"campaigns": N, "simulations": M, "agents": K}
    """
    init_schema()
    stats = {"campaigns": 0, "simulations": 0, "agents": 0}

    # Snapshot list FalkorDB graphs ONE TIME (avoid N+1 queries)
    falkor_graphs: set = set()
    try:
        import os as _os
        from falkordb import FalkorDB as _FalkorDB
        _fdb = _FalkorDB(
            host=_os.environ.get("FALKORDB_HOST", "localhost"),
            port=int(_os.environ.get("FALKORDB_PORT", 6379)),
        )
        falkor_graphs = set(_fdb.list_graphs())
        logger.info("Bootstrap: FalkorDB has %d graphs", len(falkor_graphs))
    except Exception as e:
        logger.warning("Bootstrap: FalkorDB unreachable, kg_status sẽ default 'pending': %s", e)

    campaigns_root = EcoSimConfig.campaigns_dir()
    if not campaigns_root.exists():
        logger.info("Bootstrap: no campaigns dir at %s", campaigns_root)
        return stats

    for cdir in campaigns_root.iterdir():
        if not cdir.is_dir():
            continue
        cid = cdir.name
        spec_path = cdir / "extracted" / "spec.json"
        if not spec_path.exists():
            continue
        try:
            with open(spec_path, "r", encoding="utf-8") as f:
                spec = json.load(f)
            # Source file
            source_dir = cdir / "source"
            src_name, src_size = "", 0
            if source_dir.exists():
                files = [f for f in source_dir.iterdir() if f.is_file()]
                if files:
                    src_name = files[0].name
                    src_size = files[0].stat().st_size
            # KG build_meta provenance
            kg_meta = cdir / "kg" / "build_meta.json"
            kg_built_at = None
            kg_meta_data: Dict[str, Any] = {}
            if kg_meta.exists():
                try:
                    with open(kg_meta, "r", encoding="utf-8") as f:
                        kg_meta_data = json.load(f) or {}
                    kg_built_at = kg_meta_data.get("built_at") or kg_meta_data.get("completed_at")
                except Exception:
                    pass
            created_at = spec.get("created_at") or datetime.fromtimestamp(
                cdir.stat().st_ctime, tz=timezone.utc
            ).isoformat(timespec="seconds")

            # Status: chưa biết FalkorDB còn graph hay không — boot scan ở phase
            # khác (sim_service startup) sẽ refresh kg_status từ FalkorDB.
            # Default: nếu có build_meta → kg_status='ready'
            campaign_status = "ready" if kg_built_at else "created"
            upsert_campaign(
                cid,
                name=spec.get("name", "") or cid,
                campaign_type=spec.get("campaign_type", ""),
                market=spec.get("market", ""),
                description=spec.get("description", ""),
                source_filename=src_name,
                source_size_bytes=src_size,
                created_at=created_at,
                status=campaign_status,
            )
            if kg_built_at:
                update_campaign_kg_status(
                    cid,
                    status="ready",
                    node_count=int(kg_meta_data.get("node_count", 0)),
                    edge_count=int(kg_meta_data.get("edge_count", 0)),
                    episode_count=int(kg_meta_data.get("episode_count", 0)),
                    embedding_model=kg_meta_data.get("embedding_model"),
                    embedding_dim=kg_meta_data.get("embedding_dim"),
                    extraction_model=kg_meta_data.get("extraction_model"),
                    set_built_at=False,  # Already in DB
                )
                # Set kg_built_at từ build_meta ts, không phải now()
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE campaigns SET kg_built_at = ? WHERE cid = ?",
                        (kg_built_at, cid),
                    )
            stats["campaigns"] += 1

            # Scan sims trong campaigns/<cid>/sims/
            sims_dir = cdir / "sims"
            if sims_dir.exists():
                for sdir in sims_dir.iterdir():
                    if not sdir.is_dir():
                        continue
                    sid = sdir.name
                    cfg_path = sdir / "config.json"
                    if not cfg_path.exists():
                        continue
                    try:
                        with open(cfg_path, "r", encoding="utf-8") as f:
                            cfg = json.load(f)
                        # Status từ progress.json (mặc định 'created' nếu sim chưa start).
                        prog_path = sdir / "progress.json"
                        progress_status = None
                        cur_round = 0
                        if prog_path.exists():
                            try:
                                with open(prog_path, "r", encoding="utf-8") as f:
                                    prog = json.load(f)
                                progress_status = prog.get("status")
                                cur_round = int(prog.get("current_round", 0))
                            except Exception:
                                pass

                        # PRESERVE top-level status nếu meta.db đã có row với status
                        # tốt hơn 'created' (vd 'ready' từ prepare hoặc 'completed').
                        # Bootstrap chỉ supply value mới khi progress.json có info,
                        # else giữ existing trong DB.
                        existing = get_simulation(sid)
                        if progress_status:
                            sim_status = progress_status
                        elif existing and existing.get("status") and existing["status"] != "created":
                            sim_status = existing["status"]  # preserve
                        else:
                            sim_status = "created"

                        upsert_simulation(
                            sid, cid,
                            status=sim_status,
                            num_agents=int(cfg.get("num_agents", 0)),
                            num_rounds=int(cfg.get("num_rounds", 0)),
                            current_round=cur_round,
                            created_at=cfg.get("created_at"),
                            enable_zep_runtime=cfg.get("enable_zep_runtime"),
                        )
                        stats["simulations"] += 1

                        # Refresh kg_status từ FalkorDB live state
                        sim_graph_name = sid if sid.startswith("sim_") else f"sim_{sid}"
                        if sim_graph_name in falkor_graphs:
                            # Graph tồn tại → query stats để có counts đúng
                            try:
                                import os as _osmod
                                from falkordb import FalkorDB as _FDB
                                _fdb = _FDB(
                                    host=_osmod.environ.get("FALKORDB_HOST", "localhost"),
                                    port=int(_osmod.environ.get("FALKORDB_PORT", 6379)),
                                )
                                _g = _fdb.select_graph(sim_graph_name)
                                _n = int(_g.query("MATCH (n) RETURN count(n)").result_set[0][0])
                                _e = int(_g.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0])
                                _ep = int(_g.query("MATCH (n:Episodic) RETURN count(n)").result_set[0][0])
                                # Map sim_status → kg_status hợp lý
                                if sim_status == "completed":
                                    kg_st = "completed"
                                elif sim_status == "running":
                                    kg_st = "mutating"
                                else:
                                    kg_st = "ready"
                                update_sim_kg_status(
                                    sid,
                                    status=kg_st,
                                    node_count=_n,
                                    edge_count=_e,
                                    episode_count=_ep,
                                )
                            except Exception as _ge:
                                logger.warning(
                                    "Bootstrap kg_status refresh sim %s fail: %s", sid, _ge,
                                )
                        elif falkor_graphs:
                            # FalkorDB available nhưng graph mất → mark error
                            update_sim_kg_status(sid, status="error")

                        # Agents từ profiles.json
                        prof_path = sdir / "profiles.json"
                        if prof_path.exists():
                            try:
                                with open(prof_path, "r", encoding="utf-8") as f:
                                    profiles = json.load(f)
                                n = upsert_agents(sid, profiles)
                                stats["agents"] += n
                            except Exception:
                                pass
                    except Exception as ex:
                        logger.warning("Bootstrap sim %s fail: %s", sid, ex)
        except Exception as ex:
            logger.warning("Bootstrap campaign %s fail: %s", cid, ex)

    logger.info("Bootstrap from filesystem: %s", stats)
    return stats
