"""
Agent memory graph — FalkorDB persistence cho FIFO + reflection trail.

Mục đích: persist `AgentMemory` (in-memory deque, agent_cognition.py:23) +
reflection insights vào graph riêng `ecosim_agent_memory`. Trước đây in-memory
only → mất khi subprocess exit. Giờ persistent + cross-sim queryable cho
post-sim Report/Interview.

Schema:
  (:AgentMemSummary {sim_id, agent_id, round, summary, created_at})
  (:Insight {sim_id, agent_id, round, text, created_at})
  (:AgentMemSummary)-[:REFLECTED_AS]->(:Insight)

Idempotent: gọi ensure_agent_memory_graph() nhiều lần không tạo duplicate.
Active chỉ khi `enable_graph_cognition=true` ở SIM_CONFIG.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

logger = logging.getLogger("sim-svc.agent_memory_graph")

AGENT_MEMORY_GRAPH = "ecosim_agent_memory"


def _falkor_graph(falkor_host: str = "localhost", falkor_port: int = 6379):
    """Lazy import FalkorDB + return graph handle. Returns None on failure."""
    try:
        from falkordb import FalkorDB
        fdb = FalkorDB(host=falkor_host, port=int(falkor_port))
        return fdb.select_graph(AGENT_MEMORY_GRAPH)
    except Exception as e:
        logger.warning("FalkorDB connection failed for %s: %s", AGENT_MEMORY_GRAPH, e)
        return None


def ensure_agent_memory_graph(
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
) -> bool:
    """Create graph + indexes nếu chưa có. Idempotent. Returns True on success.

    Index tạo trên (sim_id, agent_id, round) để query nhanh post-sim.
    """
    g = _falkor_graph(falkor_host, falkor_port)
    if g is None:
        return False

    try:
        # MERGE 1 dummy meta node để FalkorDB graph xuất hiện trong GRAPH.LIST.
        g.query(
            "MERGE (m:Meta {kind: 'agent_memory_graph'}) "
            "SET m.created_at = coalesce(m.created_at, $ts)",
            {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        )
        # Indexes — idempotent (FalkorDB silently no-op nếu đã có).
        for cypher in (
            "CREATE INDEX FOR (s:AgentMemSummary) ON (s.sim_id, s.agent_id, s.round)",
            "CREATE INDEX FOR (i:Insight) ON (i.sim_id, i.agent_id, i.round)",
        ):
            try:
                g.query(cypher)
            except Exception:
                pass  # already exists hoặc syntax variation
        logger.info("Ensured graph %s + indexes", AGENT_MEMORY_GRAPH)
        return True
    except Exception as e:
        logger.warning("ensure_agent_memory_graph failed: %s", e)
        return False


def write_round_summary(
    sim_id: str,
    agent_id: int,
    round_num: int,
    summary: str,
    *,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
) -> bool:
    """Persist 1 round summary cho 1 agent. Best-effort, silent fail."""
    if not summary or not summary.strip():
        return False
    g = _falkor_graph(falkor_host, falkor_port)
    if g is None:
        return False
    try:
        g.query(
            "MERGE (s:AgentMemSummary {sim_id: $sid, agent_id: $aid, round: $round}) "
            "SET s.summary = $summary, "
            "    s.created_at = coalesce(s.created_at, $ts)",
            {
                "sid": sim_id, "aid": int(agent_id), "round": int(round_num),
                "summary": summary[:2000],
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        return True
    except Exception as e:
        logger.warning("write_round_summary fail (sim=%s, agent=%s): %s",
                       sim_id, agent_id, e)
        return False


def write_reflection_insights(
    sim_id: str,
    agent_id: int,
    round_num: int,
    insights: Iterable[str],
    *,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
) -> int:
    """Persist reflection insights + link tới recent summary cùng round.

    Returns count of insights written (0 nếu fail).
    """
    g = _falkor_graph(falkor_host, falkor_port)
    if g is None:
        return 0
    written = 0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for idx, ins in enumerate(insights):
        if not ins or not str(ins).strip():
            continue
        try:
            g.query(
                "MERGE (i:Insight {sim_id: $sid, agent_id: $aid, round: $round, idx: $idx}) "
                "SET i.text = $text, i.created_at = coalesce(i.created_at, $ts) "
                "WITH i "
                "OPTIONAL MATCH (s:AgentMemSummary {sim_id: $sid, agent_id: $aid, round: $round}) "
                "FOREACH (x IN CASE WHEN s IS NULL THEN [] ELSE [s] END | "
                "  MERGE (x)-[:REFLECTED_AS]->(i))",
                {
                    "sid": sim_id, "aid": int(agent_id), "round": int(round_num),
                    "idx": idx, "text": str(ins)[:2000], "ts": ts,
                },
            )
            written += 1
        except Exception as e:
            logger.warning("write_reflection_insights fail (sim=%s, agent=%s, idx=%d): %s",
                           sim_id, agent_id, idx, e)
    return written


def query_recent_memory(
    sim_id: str,
    agent_id: int,
    *,
    limit: int = 10,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
) -> list:
    """Read recent summaries + insights cho 1 agent. Dùng cho Interview/Report
    post-sim khi cần extended memory context (vượt out 5-round FIFO buffer).
    """
    g = _falkor_graph(falkor_host, falkor_port)
    if g is None:
        return []
    try:
        r = g.query(
            "MATCH (s:AgentMemSummary {sim_id: $sid, agent_id: $aid}) "
            "OPTIONAL MATCH (s)-[:REFLECTED_AS]->(i:Insight) "
            "RETURN s.round, s.summary, collect(i.text) AS insights "
            "ORDER BY s.round DESC LIMIT $limit",
            {"sid": sim_id, "aid": int(agent_id), "limit": int(limit)},
        )
        return [
            {"round": row[0], "summary": row[1], "insights": row[2] or []}
            for row in r.result_set
        ]
    except Exception as e:
        logger.warning("query_recent_memory fail: %s", e)
        return []
