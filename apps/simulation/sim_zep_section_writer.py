"""
Phase 15: Section-per-action sim runtime path qua Zep cloud.

Mỗi cuối round trong sim:
  1. Filter content traces (create_post / create_comment, content >=30 chars)
  2. Enrich agent metadata (name, role) — KHÔNG dùng MBTI
  3. Convert mỗi trace → 1 section text natural Vietnamese
  4. Build EpisodeData(type="text") list
  5. zep.graph.add_batch + poll until processed
  6. Fetch nodes/edges/episodes từ Zep (cumulative state)
  7. Filter delta — loại entities trùng master campaign KG
  8. Re-embed local (4 batch OpenAI) — Zep KHÔNG expose embeddings
  9. Cypher MERGE → FalkorDB sim_<sid> (multi-label, rich attrs, episodes back-ref)
 10. Reroute extracted Agent entities → seeded SimAgent (idempotent)

Sim COMPLETED hook (chạy 1 lần ở run_simulation.py):
 11. graphiti.build_indices_and_constraints (HNSW + lookup)
 12. delete sim Zep graph (free credit quota)

Pattern đối xứng với master KG `apps/simulation/zep_kg_writer.write_kg_via_zep`.
Reuse module-level helpers `_normalize_edge_type`, `_safe_attr_value`, `_to_iso`.

Cost: ~5-15 Zep credits/round × 5-10 rounds = 25-150 credits/sim.
Free tier 1000/mo cho ~7-20 sims.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sim-svc.sim_zep_section_writer")

CONTENT_ACTIONS = frozenset({"create_post", "create_comment"})
MIN_CONTENT_CHARS = 30
SECTION_BODY_CAP = 9500  # cap giống master path
PARENT_CONTENT_CAP = 300  # truncate nội dung bài gốc trong comment section
POST_CONTENT_CAP = 2000  # truncate post/comment content trong section body


def _resolve_sim_graph_name(sim_id: str) -> Tuple[str, Optional[str]]:
    """Resolve canonical sim graph name + master cid qua meta.db.

    Single source of truth: meta.db column `simulations.kg_graph_name` được
    set ở /api/sim/prepare. Tránh compute từ sim_id local (có thể lệch nếu
    schema đổi).

    Args:
        sim_id: raw sim id (vd "a3b9c1") hoặc đã prefixed ("sim_a3b9c1").

    Returns:
        (graph_name, master_cid). Fallback compute nếu DB miss.
    """
    sid_clean = sim_id[4:] if sim_id.startswith("sim_") else sim_id
    try:
        from ecosim_common.metadata_index import get_sim_graph
        row = get_sim_graph(sid_clean)
        if row:
            graph_name = row.get("kg_graph_name") or f"sim_{sid_clean}"
            master_cid = row.get("cid")
            return graph_name, master_cid
    except Exception as e:
        logger.debug("meta.db lookup failed for sim %s: %s — fallback compute", sid_clean, e)
    return f"sim_{sid_clean}", None


# ──────────────────────────────────────────────
# Sim Zep graph lifecycle (Node 0 + 12)
# ──────────────────────────────────────────────
async def create_sim_zep_graph(sim_id: str, master_cid: Optional[str] = None) -> bool:
    """Tạo sim Zep graph với sim ontology. Idempotent. Gọi ở prepare flow.

    Args:
        sim_id: sim identifier (raw uuid hoặc "sim_<uuid>").
        master_cid: optional master campaign_id, dùng cho metadata.

    Returns: True nếu OK (kể cả already_exists), False nếu fail.
    """
    from ecosim_common.zep_client import make_async_zep_client, ZepKeyMissing
    from ecosim_common.sim_zep_ontology import apply_sim_ontology

    sim_graph_id, _ = _resolve_sim_graph_name(sim_id)

    try:
        zep = make_async_zep_client()
    except ZepKeyMissing:
        logger.warning("ZEP_API_KEY missing — sim Zep graph init skipped")
        return False

    try:
        await zep.graph.create(graph_id=sim_graph_id)
        logger.info("Created Zep sim graph: %s", sim_graph_id)
    except Exception as e:
        msg = str(e).lower()
        if "already" in msg or "exists" in msg or "409" in msg:
            logger.info("Zep sim graph %s already exists — reuse", sim_graph_id)
        else:
            logger.error("Zep graph.create failed for %s: %s", sim_graph_id, e)
            return False

    return await apply_sim_ontology(zep, sim_graph_id)


async def delete_sim_zep_graph(sim_id: str) -> bool:
    """Cleanup sim Zep graph (Node 12). Idempotent."""
    from ecosim_common.zep_client import make_async_zep_client, ZepKeyMissing

    sim_graph_id, _ = _resolve_sim_graph_name(sim_id)

    try:
        zep = make_async_zep_client()
    except ZepKeyMissing:
        return False

    try:
        await zep.graph.delete(graph_id=sim_graph_id)
        logger.info("Deleted Zep sim graph: %s (quota freed)", sim_graph_id)
        return True
    except Exception as e:
        logger.warning("Zep graph.delete failed for %s: %s", sim_graph_id, e)
        return False


# ──────────────────────────────────────────────
# Node 1-3: Filter + enrich + convert traces → sections
# ──────────────────────────────────────────────
def _format_post_section(name: str, role: str, round_num: int, ts: str, content: str) -> str:
    """Section text cho create_post action. KHÔNG include MBTI."""
    role_part = f" ({role})" if role else ""
    return (
        f"{name}{role_part} đăng bài viết tại Round {round_num} ({ts}):\n\n"
        f"{content[:POST_CONTENT_CAP]}"
    )


def _format_comment_section(
    name: str, role: str, round_num: int, ts: str, content: str,
    parent_name: str, parent_content: str,
) -> str:
    """Section text cho create_comment action. KHÔNG include MBTI."""
    role_part = f" ({role})" if role else ""
    parts = [
        f"{name}{role_part} bình luận tại Round {round_num} ({ts}) trên bài viết của {parent_name}:",
        f"\n{content[:POST_CONTENT_CAP]}",
    ]
    if parent_content:
        parts.append(
            f"\nNội dung bài gốc của {parent_name}:\n{parent_content[:PARENT_CONTENT_CAP]}"
        )
    return "\n".join(parts)


def build_round_sections(
    traces: List[Dict[str, Any]],
    agent_names: Dict[int, str],
    agent_profiles: Dict[int, Dict[str, str]],
    round_num: int,
    sim_graph_id: str,
) -> List[Dict[str, str]]:
    """Node 1-3: filter content traces + enrich + format thành sections.

    Returns: List[{title, body, source_description}] — ready cho Node 4.
    Empty list nếu round không có content action nào đạt min length.
    """
    import json

    sections = []
    for trace in traces:
        atype = (trace.get("action_type") or "").lower()
        if atype not in CONTENT_ACTIONS:
            continue

        info = trace.get("info") or {}
        if isinstance(info, str):
            try:
                info = json.loads(info)
            except (ValueError, TypeError):
                continue
        if not isinstance(info, dict):
            continue

        content = (info.get("content") or "").strip()
        if len(content) < MIN_CONTENT_CHARS:
            continue

        try:
            uid = int(trace.get("user_id") or trace.get("agent_id") or 0)
        except (TypeError, ValueError):
            continue

        prof = agent_profiles.get(uid, {}) if agent_profiles else {}
        name = agent_names.get(uid, f"Agent#{uid}") if agent_names else f"Agent#{uid}"
        role = prof.get("role", "") or prof.get("entity_type", "")
        ts = trace.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds")

        if atype == "create_post":
            body = _format_post_section(name, role, round_num, ts, content)
            title = f"r{round_num}_post_{uid}"
        else:  # create_comment
            parent_name = info.get("post_author_name", "agent khác")
            parent_content = info.get("post_content", "")
            body = _format_comment_section(
                name, role, round_num, ts, content, parent_name, parent_content,
            )
            title = f"r{round_num}_comment_{uid}"

        sections.append({
            "title": title,
            "body": body[:SECTION_BODY_CAP],
            "source_description": f"Sim {sim_graph_id} - {title}",
        })

    return sections


# ──────────────────────────────────────────────
# Node 5: Submit + poll
# ──────────────────────────────────────────────
async def _submit_and_poll(
    zep, sim_graph_id: str, sections: List[Dict[str, str]],
    poll_timeout_s: int = 180,
) -> List[str]:
    """Node 5: zep.graph.add_batch + poll until processed.

    Returns: list submitted episode uuids. Raises TimeoutError nếu không xong.
    """
    from zep_cloud.types.episode_data import EpisodeData

    episodes_data = [
        EpisodeData(
            data=s["body"],
            type="text",
            source_description=s["source_description"],
        )
        for s in sections
    ]

    submitted = await zep.graph.add_batch(
        graph_id=sim_graph_id,
        episodes=episodes_data,
    )
    submitted_uuids = [ep.uuid_ for ep in submitted if getattr(ep, "uuid_", None)]
    logger.info(
        "Zep batch submit: %d sections → graph %s",
        len(submitted_uuids), sim_graph_id,
    )

    # Poll
    pending = list(submitted_uuids)
    elapsed = 0
    poll_interval = 3
    while pending and elapsed < poll_timeout_s:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        still = []
        for u in pending:
            try:
                ep = await zep.graph.episode.get(u)
                if not getattr(ep, "processed", False):
                    still.append(u)
            except Exception as e:
                logger.warning("episode.get(%s) failed: %s", u, e)
                still.append(u)
        pending = still

    if pending:
        raise TimeoutError(
            f"Zep extraction timed out: {len(pending)}/{len(submitted_uuids)} "
            f"still processing after {poll_timeout_s}s"
        )
    return submitted_uuids


# ──────────────────────────────────────────────
# Node 6: Fetch
# ──────────────────────────────────────────────
async def _fetch_zep_data(zep, sim_graph_id: str) -> Tuple[List, List, List]:
    """Node 6: fetch tất cả nodes + edges + episodes (cumulative state)."""
    nodes = await zep.graph.node.get_by_graph_id(sim_graph_id, limit=1000)
    edges = await zep.graph.edge.get_by_graph_id(sim_graph_id, limit=1000)
    eps_resp = await zep.graph.episode.get_by_graph_id(sim_graph_id, lastn=1000)
    episodes = getattr(eps_resp, "episodes", None) or []
    nodes = list(nodes or [])
    edges = list(edges or [])
    logger.info(
        "Zep fetch (cumulative): %d nodes, %d edges, %d episodes",
        len(nodes), len(edges), len(episodes),
    )
    return nodes, edges, episodes


# ──────────────────────────────────────────────
# Node 7: Filter master overlap
# ──────────────────────────────────────────────
def _filter_master_overlap(
    nodes: List, master_cid: str,
    falkor_host: str, falkor_port: int,
) -> Tuple[List, int]:
    """Node 7: loại nodes có (name, type) đã tồn tại trong master campaign graph."""
    from falkordb import FalkorDB
    from ecosim_common.zep_label_map import zep_labels_to_canonical

    master_by_name = set()
    try:
        fdb = FalkorDB(host=falkor_host, port=int(falkor_port))
        if master_cid in fdb.list_graphs():
            g = fdb.select_graph(master_cid)
            r = g.query(
                "MATCH (n:Entity) WHERE n.name IS NOT NULL "
                "RETURN n.name, coalesce(n.entity_type, 'Entity')"
            )
            master_by_name = {(row[0], row[1]) for row in r.result_set if row[0]}
    except Exception as e:
        logger.warning("Master entity query fail (cid=%s): %s", master_cid, e)

    delta = []
    skipped = 0
    for n in nodes:
        canonical = zep_labels_to_canonical(getattr(n, "labels", None) or [])
        if (n.name, canonical) in master_by_name:
            skipped += 1
            continue
        delta.append(n)
    return delta, skipped


# ──────────────────────────────────────────────
# Node 8: Re-embed local
# ──────────────────────────────────────────────
async def _re_embed(llm, delta_nodes, delta_edges, delta_eps) -> Tuple[List, List, List, List]:
    """Node 8: 4 batch OpenAI embedding calls."""
    name_texts = [n.name for n in delta_nodes]
    summary_texts = [(n.summary or n.name) for n in delta_nodes]
    fact_texts = [(getattr(e, "fact", None) or e.name or "") for e in delta_edges]
    body_texts = [(ep.content or "")[:8000] for ep in delta_eps]

    async def _embed(label: str, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        try:
            return await asyncio.wait_for(llm.embed_batch_async(texts), timeout=60.0)
        except Exception as e:
            logger.warning("Embed %s failed: %s — fallback zeros", label, e)
            return [[0.0] * 1536 for _ in texts]

    return (
        await _embed("names", name_texts),
        await _embed("summaries", summary_texts),
        await _embed("facts", fact_texts),
        await _embed("bodies", body_texts),
    )


# ──────────────────────────────────────────────
# Node 9: Cypher MERGE
# ──────────────────────────────────────────────
def _cypher_merge_delta(
    g, delta_nodes, delta_edges, delta_eps,
    name_embs, sum_embs, fact_embs, body_embs,
    sim_graph_id: str, ref_iso: str,
) -> Dict[str, int]:
    """Node 9: Cypher MERGE entities + edges + episodics + mentions."""
    from zep_kg_writer import _normalize_edge_type, _safe_attr_value, _to_iso
    from ecosim_common.zep_label_map import zep_labels_to_canonical, is_safe_cypher_label

    stats = {"entities": 0, "edges": 0, "episodes": 0, "mentions": 0}

    # 9a. Entities (multi-label + attributes)
    for node, name_emb, sum_emb in zip(delta_nodes, name_embs, sum_embs):
        canonical = zep_labels_to_canonical(getattr(node, "labels", None) or [])
        label_clause = "Entity" if canonical == "Entity" else f"Entity:{canonical}"
        params = {
            "uuid": node.uuid_,
            "name": node.name or "",
            "summary": node.summary or "",
            "name_emb": name_emb,
            "sum_emb": sum_emb,
            "etype": canonical,
            "labels": list(getattr(node, "labels", None) or []),
            "gid": sim_graph_id,
            "created": _to_iso(getattr(node, "created_at", None)),
        }
        try:
            # vecf32() so FalkorDB stores Vectorf32 (Graphiti search at
            # runtime calls vec.cosineDistance on these → must be typed).
            g.query(
                f"MERGE (n:{label_clause} {{uuid: $uuid}}) "
                "SET n.name = $name, n.summary = $summary, "
                "    n.name_embedding = vecf32($name_emb), "
                "    n.summary_embedding = vecf32($sum_emb), "
                "    n.entity_type = $etype, n.zep_labels = $labels, "
                "    n.group_id = $gid, "
                "    n.source = coalesce(n.source, 'zep_extract'), "
                "    n.created_at = coalesce(n.created_at, $created)",
                params,
            )
            stats["entities"] += 1
            attrs = getattr(node, "attributes", None) or {}
            if attrs:
                safe_attrs = {
                    k: _safe_attr_value(v) for k, v in attrs.items()
                    if is_safe_cypher_label(k) and v is not None
                }
                if safe_attrs:
                    set_clauses = ", ".join(f"n.{k} = ${k}" for k in safe_attrs.keys())
                    g.query(
                        f"MATCH (n {{uuid: $uuid}}) SET {set_clauses}",
                        {"uuid": node.uuid_, **safe_attrs},
                    )
        except Exception as e:
            logger.debug("Skip entity %s: %s", node.name, e)

    # 9b. Edges (group by edge_type, UNWIND batch)
    edges_by_type: Dict[str, List[Dict]] = {}
    for edge, fact_emb in zip(delta_edges, fact_embs):
        etype = _normalize_edge_type(getattr(edge, "name", None))
        if not is_safe_cypher_label(etype):
            etype = "RELATES_TO"
        edges_by_type.setdefault(etype, []).append({
            "uuid": edge.uuid_,
            "src": edge.source_node_uuid,
            "dst": edge.target_node_uuid,
            "fact": getattr(edge, "fact", None) or "",
            "fact_emb": fact_emb,
            "predicate": edge.name or "",
            "valid_at": _to_iso(getattr(edge, "valid_at", None)),
            "invalid_at": _to_iso(getattr(edge, "invalid_at", None)),
            "expired_at": _to_iso(getattr(edge, "expired_at", None)),
            "episodes": list(getattr(edge, "episodes", None) or []),
            "created": _to_iso(getattr(edge, "created_at", None)),
        })

    for etype, batch in edges_by_type.items():
        try:
            g.query(
                "UNWIND $batch AS e "
                "MATCH (a {uuid: e.src}), (b {uuid: e.dst}) "
                f"MERGE (a)-[r:{etype} {{uuid: e.uuid}}]->(b) "
                "SET r.fact = e.fact, r.fact_embedding = vecf32(e.fact_emb), "
                "    r.predicate = e.predicate, r.valid_at = e.valid_at, "
                "    r.invalid_at = e.invalid_at, r.expired_at = e.expired_at, "
                "    r.episodes = e.episodes, r.edge_type = $etype, "
                "    r.group_id = $gid, "
                "    r.created_at = coalesce(r.created_at, e.created)",
                {"batch": batch, "etype": etype, "gid": sim_graph_id},
            )
            stats["edges"] += len(batch)
        except Exception as e:
            logger.debug("Skip edge batch %s: %s", etype, e)

    # 9c. Episodic
    for ep, body_emb in zip(delta_eps, body_embs):
        try:
            g.query(
                "MERGE (e:Episodic {uuid: $uuid}) "
                "SET e.name = $name, e.content = $content, "
                "    e.name_embedding = vecf32($name_emb), e.source = $source, "
                "    e.source_description = $sd, e.group_id = $gid, "
                "    e.valid_at = $ref, "
                "    e.created_at = coalesce(e.created_at, $created)",
                {
                    "uuid": ep.uuid_,
                    "name": getattr(ep, "name", None) or f"Episode {ep.uuid_[:8]}",
                    "content": (ep.content or "")[:5000],
                    "name_emb": body_emb,
                    "source": getattr(ep, "source", "text"),
                    "sd": getattr(ep, "source_description", "") or "",
                    "gid": sim_graph_id,
                    "ref": ref_iso,
                    "created": _to_iso(getattr(ep, "created_at", None)),
                },
            )
            stats["episodes"] += 1
        except Exception as e:
            logger.debug("Skip episode %s: %s", ep.uuid_, e)

    # 9d. :MENTIONS edges (Episodic → Entities) qua edge.episodes back-refs
    epi_to_entities: Dict[str, set] = {}
    for edge in delta_edges:
        for ep_uuid in (getattr(edge, "episodes", None) or []):
            s = epi_to_entities.setdefault(ep_uuid, set())
            if edge.source_node_uuid:
                s.add(edge.source_node_uuid)
            if edge.target_node_uuid:
                s.add(edge.target_node_uuid)

    mention_pairs = [
        {"eid": epi_uuid, "nid": ent_uuid}
        for epi_uuid, ent_uuids in epi_to_entities.items()
        for ent_uuid in ent_uuids
    ]
    if mention_pairs:
        try:
            g.query(
                "UNWIND $pairs AS p "
                "MATCH (e:Episodic {uuid: p.eid}), (n {uuid: p.nid}) "
                "MERGE (e)-[m:MENTIONS]->(n) "
                "SET m.group_id = $gid, "
                "    m.created_at = coalesce(m.created_at, $now)",
                {"pairs": mention_pairs, "gid": sim_graph_id, "now": ref_iso},
            )
            stats["mentions"] = len(mention_pairs)
        except Exception as e:
            logger.debug("MENTIONS batch fail: %s", e)

    return stats


# ──────────────────────────────────────────────
# Node 10: Reroute extracted Agent → seeded SimAgent
# ──────────────────────────────────────────────
def _reroute_extracted_agents(g, sim_graph_id: str) -> Dict[str, int]:
    """Node 10: MATCH (e:Entity {name=X}) ↔ (:SimAgent {name=X, sim_id})
    → reroute edges + DETACH DELETE Zep-extracted Agent duplicates.

    Idempotent: chạy nhiều lần (mỗi cuối round) OK.
    """
    from ecosim_common.zep_label_map import is_safe_cypher_label

    rerouted_out = 0
    rerouted_in = 0
    deleted = 0

    try:
        # Outgoing: extracted Agent → target  =>  SimAgent → target
        out = g.query(
            "MATCH (e:Entity)-[r]->(t) "
            "WHERE 'Agent' IN labels(e) AND e.source = 'zep_extract' "
            "MATCH (a:SimAgent {sim_id: $gid, name: e.name}) "
            "RETURN a.agent_id, type(r), properties(r), t.uuid",
            {"gid": sim_graph_id},
        )
        for row in (out.result_set or []):
            agent_id, rel_type, props, target_uuid = row
            if not is_safe_cypher_label(rel_type) or not target_uuid:
                continue
            try:
                g.query(
                    f"MATCH (a:SimAgent {{agent_id: $aid, sim_id: $gid}}), (t {{uuid: $tid}}) "
                    f"MERGE (a)-[r:{rel_type}]->(t) "
                    "SET r += $props",
                    {"aid": int(agent_id), "gid": sim_graph_id,
                     "tid": target_uuid, "props": props or {}},
                )
                rerouted_out += 1
            except Exception as ex:
                logger.debug("Reroute out (%s) fail: %s", rel_type, ex)

        # Incoming: source → extracted Agent  =>  source → SimAgent
        in_q = g.query(
            "MATCH (s)-[r]->(e:Entity) "
            "WHERE 'Agent' IN labels(e) AND e.source = 'zep_extract' "
            "MATCH (a:SimAgent {sim_id: $gid, name: e.name}) "
            "RETURN s.uuid, type(r), properties(r), a.agent_id",
            {"gid": sim_graph_id},
        )
        for row in (in_q.result_set or []):
            source_uuid, rel_type, props, agent_id = row
            if not is_safe_cypher_label(rel_type) or not source_uuid:
                continue
            try:
                g.query(
                    f"MATCH (s {{uuid: $sid}}), (a:SimAgent {{agent_id: $aid, sim_id: $gid}}) "
                    f"MERGE (s)-[r:{rel_type}]->(a) "
                    "SET r += $props",
                    {"sid": source_uuid, "aid": int(agent_id),
                     "gid": sim_graph_id, "props": props or {}},
                )
                rerouted_in += 1
            except Exception as ex:
                logger.debug("Reroute in (%s) fail: %s", rel_type, ex)

        # DETACH DELETE Zep Entity:Agent duplicates đã có SimAgent counterpart.
        # FalkorDB không hỗ trợ Cypher subquery `EXISTS { MATCH ... }` — thay
        # bằng JOIN thông thường: match đồng thời (e:Entity) và (a:SimAgent),
        # constraint a.name = e.name. Pattern này đã work ở 2 query trên (line
        # 533, 557) nên FalkorDB parser chắc chắn nhận.
        del_resp = g.query(
            "MATCH (e:Entity), (a:SimAgent {sim_id: $gid}) "
            "WHERE 'Agent' IN labels(e) AND e.source = 'zep_extract' "
            "  AND a.name = e.name "
            "WITH DISTINCT e DETACH DELETE e RETURN count(*)",
            {"gid": sim_graph_id},
        )
        if del_resp.result_set:
            deleted = del_resp.result_set[0][0]
    except Exception as e:
        logger.warning("Reroute fail: %s", e)

    return {
        "rerouted_out": rerouted_out,
        "rerouted_in": rerouted_in,
        "deleted_duplicates": deleted,
    }


# ──────────────────────────────────────────────
# Public entry — Node 1-10 cho mỗi cuối round
# ──────────────────────────────────────────────
async def write_round_sections_via_zep(
    round_num: int,
    traces: List[Dict[str, Any]],
    agent_names: Dict[int, str],
    agent_profiles: Dict[int, Dict[str, str]],
    sim_id: str,
    llm,
    *,
    master_cid: Optional[str] = None,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
    poll_timeout_s: int = 180,
) -> Dict[str, Any]:
    """End-of-round dispatch: Node 1-10.

    Args:
        round_num: round number vừa kết thúc.
        traces: list trace dict của round (từ read_new_traces).
        agent_names: {agent_id: name}.
        agent_profiles: {agent_id: {role, ...}} — KHÔNG dùng MBTI.
        sim_id: sim identifier ("sim_<uuid>" hoặc raw uuid). Graph name resolved
            qua meta.db (`simulations.kg_graph_name`); fallback compute nếu DB miss.
        master_cid: optional override cho master campaign_id. Nếu None,
            resolve qua meta.db join `simulations.cid`. Cho Node 7 filter overlap.
        llm: LLMClient cho Node 8 re-embed.

    Returns: stats dict {sections_submitted, entities_added, edges_added, ...}.
    Empty round (no content actions) → returns status="skipped".
    """
    from ecosim_common.zep_client import ZepKeyMissing

    sim_graph_id, db_master_cid = _resolve_sim_graph_name(sim_id)
    if not master_cid:
        master_cid = db_master_cid or ""

    # Node 1-3: build sections (sync, no LLM)
    sections = build_round_sections(
        traces, agent_names, agent_profiles, round_num, sim_graph_id,
    )
    if not sections:
        return {"status": "skipped", "reason": "no_content_actions", "round": round_num}

    try:
        result = await _run_zep_section_pipeline(
            sections=sections,
            sim_graph_id=sim_graph_id,
            master_cid=master_cid,
            llm=llm,
            falkor_host=falkor_host,
            falkor_port=falkor_port,
            poll_timeout_s=poll_timeout_s,
            label=f"Round {round_num}",
        )
    except ZepKeyMissing:
        return {"status": "skipped", "reason": "zep_key_missing", "round": round_num}
    result["round"] = round_num
    return result


# ──────────────────────────────────────────────
# Generic Zep pipeline — Nodes 5-10 reused bởi round + agent seed
# ──────────────────────────────────────────────
async def _run_zep_section_pipeline(
    *,
    sections: List[Dict[str, str]],
    sim_graph_id: str,
    master_cid: str,
    llm,
    falkor_host: str,
    falkor_port: int,
    poll_timeout_s: int,
    label: str,
) -> Dict[str, Any]:
    """Generic pipeline: submit sections → poll → fetch → filter → embed → merge → reroute.

    Reused bởi cả per-round dispatch (write_round_sections_via_zep) lẫn
    agent seed dispatch (seed_agents_via_zep). Yêu cầu sections đã build sẵn.
    """
    from ecosim_common.zep_client import make_async_zep_client

    t_start = time.time()
    zep = make_async_zep_client()  # raises ZepKeyMissing nếu env thiếu

    # Node 5: submit + poll
    try:
        submitted_uuids = await _submit_and_poll(
            zep, sim_graph_id, sections, poll_timeout_s=poll_timeout_s,
        )
    except Exception as e:
        logger.error("%s Zep submit/poll failed: %s", label, e)
        return {
            "status": "submit_failed",
            "sections_attempted": len(sections),
            "error": str(e)[:200],
        }

    # Node 6: fetch
    try:
        nodes, edges, episodes = await _fetch_zep_data(zep, sim_graph_id)
    except Exception as e:
        logger.error("%s Zep fetch failed: %s", label, e)
        return {"status": "fetch_failed", "error": str(e)[:200]}

    # Node 7: filter master overlap
    delta_nodes, skipped_master = _filter_master_overlap(
        nodes, master_cid, falkor_host, falkor_port,
    )
    delta_edges = list(edges)
    delta_eps = list(episodes)

    # Node 8: re-embed local
    name_embs, sum_embs, fact_embs, body_embs = await _re_embed(
        llm, delta_nodes, delta_edges, delta_eps,
    )

    # Node 9: Cypher MERGE
    from falkordb import FalkorDB
    fdb = FalkorDB(host=falkor_host, port=int(falkor_port))
    g = fdb.select_graph(sim_graph_id)
    ref_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    merge_stats = _cypher_merge_delta(
        g, delta_nodes, delta_edges, delta_eps,
        name_embs, sum_embs, fact_embs, body_embs,
        sim_graph_id, ref_iso,
    )

    # Node 10: reroute extracted Agent → SimAgent (idempotent)
    reroute_stats = _reroute_extracted_agents(g, sim_graph_id)

    elapsed_ms = int((time.time() - t_start) * 1000)
    logger.info(
        "✅ %s Zep done in %.1fs | sections=%d submitted=%d | "
        "+%d entities +%d edges +%d eps +%d mentions | reroute out=%d in=%d del=%d | "
        "master overlap skip=%d",
        label, elapsed_ms / 1000,
        len(sections), len(submitted_uuids),
        merge_stats["entities"], merge_stats["edges"],
        merge_stats["episodes"], merge_stats["mentions"],
        reroute_stats["rerouted_out"], reroute_stats["rerouted_in"],
        reroute_stats["deleted_duplicates"], skipped_master,
    )
    return {
        "status": "ok",
        "sections_submitted": len(submitted_uuids),
        "entities_added": merge_stats["entities"],
        "edges_added": merge_stats["edges"],
        "episodes_added": merge_stats["episodes"],
        "mentions_added": merge_stats["mentions"],
        "rerouted_out": reroute_stats["rerouted_out"],
        "rerouted_in": reroute_stats["rerouted_in"],
        "cleaned_zep_agents": reroute_stats["deleted_duplicates"],
        "master_overlap_skipped": skipped_master,
        "elapsed_ms": elapsed_ms,
    }


# ──────────────────────────────────────────────
# Agent seed sections (Phase 15 prepare flow)
# ──────────────────────────────────────────────
def build_agent_seed_sections(
    profiles: List[Dict[str, Any]],
    sim_graph_id: str,
) -> List[Dict[str, str]]:
    """Convert agent profiles → section text natural Vietnamese (1 section/agent).

    Format giống Phase 15 round dispatch — KHÔNG include MBTI.
    """
    import json as _json
    sections = []
    for prof in profiles:
        try:
            aid = int(prof.get("agent_id", 0))
        except (TypeError, ValueError):
            continue
        name = prof.get("name") or prof.get("realname") or f"Agent#{aid}"
        role = prof.get("entity_type") or prof.get("role") or ""
        bio = (prof.get("bio") or "").strip()
        persona = (prof.get("persona") or prof.get("user_char") or "").strip()
        topics = prof.get("topics") or prof.get("interests") or []
        if isinstance(topics, str):
            try:
                topics = _json.loads(topics)
            except (ValueError, TypeError):
                topics = [t.strip() for t in topics.split(",") if t.strip()]
        if not isinstance(topics, list):
            topics = []
        topics_str = ", ".join(str(t) for t in topics[:10]) if topics else ""

        role_part = f" ({role})" if role else ""
        body_lines = [
            f"Agent {name}{role_part} là một người dùng trong simulation EcoSim."
        ]
        if bio:
            body_lines.append(f"\nTiểu sử: {bio[:600]}")
        if persona:
            body_lines.append(f"\nCá tính: {persona[:600]}")
        if topics_str:
            body_lines.append(f"\nSở thích chính: {topics_str}")
        body = "\n".join(body_lines)

        title = f"agent_seed_{aid}"
        sections.append({
            "title": title,
            "body": body[:SECTION_BODY_CAP],
            "source_description": f"Sim {sim_graph_id} - {title}",
        })
    return sections


async def seed_agents_via_zep(
    sim_id: str,
    profiles: List[Dict[str, Any]],
    llm,
    *,
    master_cid: Optional[str] = None,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
    poll_timeout_s: int = 180,
) -> Dict[str, Any]:
    """Phase 15 agent seed dispatch — bắt chước round dispatch.

    Mỗi agent profile → 1 section text → batch submit Zep → mirror entities/edges
    về sim graph. Stage 5e reroute đảm bảo Zep extract Agent entities (vd
    `:Entity:Agent {name: 'Đào Phúc Xuân'}`) merge với seeded `:SimAgent` đã
    tạo bởi `seed_agents_to_sim_graph` (Cypher anchors).

    Yêu cầu: `seed_agents_to_sim_graph(sim_id, profiles)` chạy TRƯỚC để có
    SimAgent anchor nodes (Step 1-3). create_sim_zep_graph chạy TRƯỚC để
    có sim Zep graph với ontology áp dụng.

    Returns: stats dict.
    """
    from ecosim_common.zep_client import ZepKeyMissing

    if not profiles:
        return {"status": "skipped", "reason": "no_profiles"}

    sim_graph_id, db_master_cid = _resolve_sim_graph_name(sim_id)
    if not master_cid:
        master_cid = db_master_cid or ""

    sections = build_agent_seed_sections(profiles, sim_graph_id)
    if not sections:
        return {"status": "skipped", "reason": "no_sections_built"}

    try:
        return await _run_zep_section_pipeline(
            sections=sections,
            sim_graph_id=sim_graph_id,
            master_cid=master_cid,
            llm=llm,
            falkor_host=falkor_host,
            falkor_port=falkor_port,
            poll_timeout_s=poll_timeout_s,
            label=f"Agent seed ({len(profiles)} agents)",
        )
    except ZepKeyMissing:
        return {"status": "skipped", "reason": "zep_key_missing"}


# ──────────────────────────────────────────────
# Public entry — Node 11-12 cho sim COMPLETED
# ──────────────────────────────────────────────
async def finalize_sim_post_run(
    sim_id: str,
    *,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
) -> Dict[str, Any]:
    """Sim COMPLETED hook: build indices + delete Zep graph.

    Gọi 1 lần sau khi tất cả rounds đã chạy write_round_sections_via_zep.
    """
    from ecosim_common.graphiti_factory import (
        make_graphiti, make_falkor_driver, build_indices_with_retry,
    )
    from ecosim_common.llm_client import LLMClient

    sim_graph_id, _ = _resolve_sim_graph_name(sim_id)

    # Node 11: build indices on FalkorDB sim graph
    indices_built = False
    try:
        llm = LLMClient()
        driver = make_falkor_driver(falkor_host, falkor_port, sim_graph_id)
        graphiti = make_graphiti(driver, llm=llm)
        indices_built = await build_indices_with_retry(graphiti, max_retries=3)
        await graphiti.close()
    except Exception as e:
        logger.warning("Build indices failed for %s: %s", sim_graph_id, e)

    # Node 12: delete Zep sim graph (free quota)
    zep_deleted = await delete_sim_zep_graph(sim_id)

    logger.info(
        "Finalize sim %s: indices_built=%s zep_deleted=%s",
        sim_graph_id, indices_built, zep_deleted,
    )
    return {
        "status": "finalized",
        "sim_id": sim_id,
        "indices_built": indices_built,
        "zep_graph_deleted": zep_deleted,
    }
