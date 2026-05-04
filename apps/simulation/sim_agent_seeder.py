"""
Sim Agent Seeder — insert agent profiles vào sim graph trong FalkorDB.

Phase 10: chạy sau `clone_campaign_graph_in_falkor()` trong sim/prepare flow.
Mỗi profile → (:SimAgent) node + optional links tới KG entities + Graphiti
episode cho hybrid search.

Tách khỏi `apps/core/app/services/graph_memory_updater.py` (Core's GraphMemoryUpdater)
vì sim service chạy ở venv riêng — relative import `from ..config` không reachable.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("sim-svc.agent_seeder")


def _falkor_client():
    from falkordb import FalkorDB
    return FalkorDB(
        host=os.environ.get("FALKORDB_HOST", "localhost"),
        port=int(os.environ.get("FALKORDB_PORT", 6379)),
    )


def _truncate(value: object, n: int) -> str:
    s = "" if value is None else str(value)
    return s[:n]


async def seed_agents_to_sim_graph(
    sim_id: str,
    profiles: List[Dict],
    *,
    kg_edges: Optional[List[Dict]] = None,
    use_graphiti_episodes: bool = False,
) -> Dict:
    """Seed agent profiles vào sim graph (`sim_<sid>`) — Cypher anchors only.

    Phase 15: Step 4 (Graphiti add_episode) đổi default sang False. Caller
    nên dùng `sim_zep_section_writer.seed_agents_via_zep()` thay thế — submit
    agent profiles dưới dạng section text qua Zep cloud, đối xứng với round
    dispatch + master KG path. Reasons:
      • Zep batch nhanh hơn 5-10× so với 5 Graphiti add_episode tuần tự
      • Tận dụng sim ontology rich (Brand, Sentiment, ...) thay vì :Entity chung
      • Symmetric với round dispatch (cùng pipeline, cùng cache, cùng debug)

    Steps:
      1. Raw Cypher MERGE (:SimAgent {agent_id, sim_id, name, role, bio,
         topics, persona_summary})
      2. Link `(:SimAgent)-[:REPRESENTS]->(:Entity)` nếu name match KG entity
      3. Optional: `(:SimAgent)-[:KNOWS]->(:SimAgent)` từ kg_edges
      4. (DEPRECATED) Graphiti add_episode — chỉ chạy nếu use_graphiti_episodes=True

    Returns: {agents_seeded, represents_linked, knows_linked, episodes_added}
    """
    if not sim_id:
        raise ValueError("sim_id required")
    graph_name = sim_id if sim_id.startswith("sim_") else f"sim_{sim_id}"

    fdb = _falkor_client()
    g = fdb.select_graph(graph_name)

    stats = {
        "agents_seeded": 0,
        "represents_linked": 0,
        "knows_linked": 0,
        "episodes_added": 0,
    }

    # ── Step 1: MERGE SimAgent nodes ──────────────────────────────────
    for prof in profiles:
        aid = prof.get("agent_id", 0)
        name = prof.get("name") or prof.get("realname") or f"Agent_{aid}"
        entity_type = prof.get("entity_type") or prof.get("role") or ""
        topics = prof.get("topics") or prof.get("interests") or []
        if isinstance(topics, str):
            try:
                topics = json.loads(topics)
            except (json.JSONDecodeError, ValueError):
                topics = []
        bio = _truncate(prof.get("bio"), 300)
        persona = _truncate(prof.get("persona") or prof.get("user_char"), 500)
        mbti = _truncate(prof.get("mbti"), 4)

        try:
            g.query(
                "MERGE (a:SimAgent {agent_id: $aid, sim_id: $sid}) "
                "SET a.name = $name, a.role = $role, a.entity_type = $etype, "
                "    a.bio = $bio, a.persona_summary = $persona, "
                "    a.mbti = $mbti, a.topics = $topics, "
                "    a.created_at = coalesce(a.created_at, $ts)",
                params={
                    "aid": int(aid), "sid": sim_id,
                    "name": name, "role": entity_type, "etype": entity_type,
                    "bio": bio, "persona": persona, "mbti": mbti,
                    "topics": json.dumps(topics, ensure_ascii=False)
                              if isinstance(topics, list) else str(topics),
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
            )
            stats["agents_seeded"] += 1
        except Exception as e:
            logger.warning("MERGE SimAgent fail (aid=%s, name=%s): %s", aid, name, e)

    # ── Step 2: link SimAgent → Entity (KG entity matching by name) ──
    for prof in profiles:
        name = prof.get("name") or prof.get("realname") or ""
        if not name:
            continue
        aid = prof.get("agent_id", 0)
        try:
            r = g.query(
                "MATCH (a:SimAgent {agent_id: $aid, sim_id: $sid}) "
                "MATCH (e:Entity {name: $name}) "
                "MERGE (a)-[:REPRESENTS]->(e) "
                "RETURN count(e) AS cnt",
                params={"aid": int(aid), "sid": sim_id, "name": name},
            )
            if r.result_set and r.result_set[0][0] > 0:
                stats["represents_linked"] += 1
        except Exception:
            pass

    # ── Step 3: KNOWS edges từ KG relationships ──────────────────────
    if kg_edges:
        name_to_id = {
            (p.get("name") or p.get("realname") or ""): p.get("agent_id")
            for p in profiles
        }
        for edge in kg_edges:
            src_name = edge.get("source", "")
            tgt_name = edge.get("target", "")
            src_id = name_to_id.get(src_name)
            tgt_id = name_to_id.get(tgt_name)
            if src_id is None or tgt_id is None:
                continue
            try:
                g.query(
                    "MATCH (a:SimAgent {agent_id: $src, sim_id: $sid}) "
                    "MATCH (b:SimAgent {agent_id: $tgt, sim_id: $sid}) "
                    "MERGE (a)-[:KNOWS {rel_type: $rel}]->(b)",
                    params={
                        "src": int(src_id), "tgt": int(tgt_id), "sid": sim_id,
                        "rel": edge.get("rel_type", "RELATED_TO"),
                    },
                )
                stats["knows_linked"] += 1
            except Exception:
                pass

    # ── Step 4: Graphiti episodes cho hybrid search ───────────────────
    if use_graphiti_episodes:
        try:
            from ecosim_common.graphiti_factory import (
                make_graphiti, make_falkor_driver,
            )
            from graphiti_core.nodes import EpisodeType

            driver = make_falkor_driver(
                host=os.environ.get("FALKORDB_HOST", "localhost"),
                port=int(os.environ.get("FALKORDB_PORT", 6379)),
                database=graph_name,
            )
            client = make_graphiti(driver)
            now = datetime.now(timezone.utc)
            for prof in profiles:
                name = prof.get("name") or prof.get("realname") or ""
                if not name:
                    continue
                role = prof.get("entity_type") or prof.get("role") or ""
                bio = prof.get("bio") or ""
                persona = (prof.get("persona") or prof.get("user_char") or "")[:500]
                topics = prof.get("topics") or prof.get("interests") or []
                if isinstance(topics, str):
                    try:
                        topics = json.loads(topics)
                    except (json.JSONDecodeError, ValueError):
                        topics = []
                topics_str = ", ".join(topics) if isinstance(topics, list) else str(topics)
                episode_text = (
                    f"{name} is a {role}. {bio} "
                    f"Interests: {topics_str}. {persona}"
                )
                try:
                    await client.add_episode(
                        name=f"Agent: {name}",
                        episode_body=episode_text,
                        source_description="EcoSim agent profile",
                        source=EpisodeType.text,
                        reference_time=now,
                        group_id=sim_id,
                    )
                    stats["episodes_added"] += 1
                except Exception as e:
                    logger.debug("Graphiti add_episode fail (agent=%s): %s", name, e)
            await client.close()
        except Exception as e:
            logger.warning(
                "Graphiti episode seed skipped: %s (raw Cypher SimAgent đã xong)", e,
            )

    logger.info("Seeded agents to %s: %s", graph_name, stats)
    return stats
