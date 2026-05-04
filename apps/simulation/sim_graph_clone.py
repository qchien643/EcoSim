"""
Sim Graph Clone — clone campaign master KG sang sim graph trong FalkorDB.

Phase 10: replacement cho kg_fork.py. Khác biệt chính:
  • KHÔNG còn auto-restore từ snapshot.json (no snapshot — FalkorDB là SoT)
  • Update meta.db kg_status thay vì write JSON
  • Embedding compat verify từ meta.db (kg_embedding_model + dim)

API chính:
  clone_campaign_graph_in_falkor(cid, sid) → {nodes, edges, episodes, ms}
  drop_sim_graph(sid)
  drop_master_graph(cid)
  drop_campaign_graphs(cid, sim_ids)
  sim_graph_name(sid) → "sim_<sid>"
  write_embedding_meta(graph_name)

Pure FalkorDB Cypher copy — không re-embed, không Graphiti add_episode.
Cost = ~2-5s cho graph 100 nodes / 300 edges.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from typing import Dict, List, Tuple

logger = logging.getLogger("sim-svc.sim_graph_clone")

_BATCH_SIZE = 500
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ──────────────────────────────────────────────
# Naming + client helpers
# ──────────────────────────────────────────────
def sim_graph_name(sim_id: str) -> str:
    """Canonical name FalkorDB graph cho sim. Idempotent với prefix."""
    if not sim_id:
        raise ValueError("sim_id required")
    s = sim_id.strip()
    return s if s.startswith("sim_") else f"sim_{s}"


def _falkor_client():
    from falkordb import FalkorDB
    host = os.environ.get("FALKORDB_HOST", "localhost")
    port = int(os.environ.get("FALKORDB_PORT", 6379))
    return FalkorDB(host=host, port=port)


def _is_safe_identifier(s: str) -> bool:
    return bool(s and _SAFE_IDENT.match(s))


# ──────────────────────────────────────────────
# Embedding meta (write/read trong FalkorDB :Meta node)
# ──────────────────────────────────────────────
def write_embedding_meta(graph_name: str) -> None:
    """MERGE (m:Meta {kind: 'embedding_config'}) on graph với current LLM env."""
    from datetime import datetime
    from ecosim_common.config import EcoSimConfig

    model = EcoSimConfig.llm_embedding_model()
    dim = EcoSimConfig.llm_embedding_dim_hint(model) or 0
    base_url = EcoSimConfig.llm_embedding_base_url()
    ts = datetime.now().isoformat(timespec="seconds")

    fdb = _falkor_client()
    g = fdb.select_graph(graph_name)
    g.query(
        "MERGE (m:Meta {kind: 'embedding_config'}) "
        "SET m.model = $model, m.dim = $dim, m.base_url = $base_url, "
        "    m.created_at = coalesce(m.created_at, $ts), m.updated_at = $ts",
        {"model": model, "dim": dim, "base_url": base_url, "ts": ts},
    )
    logger.info("Wrote :Meta to graph %s (model=%s, dim=%d)", graph_name, model, dim)


def verify_embedding_compat(graph_name: str) -> Tuple[bool, str]:
    """Compare graph's :Meta {embedding_config} with current env. (ok, reason)."""
    from ecosim_common.config import EcoSimConfig

    fdb = _falkor_client()
    try:
        g = fdb.select_graph(graph_name)
        r = g.query(
            "MATCH (m:Meta) WHERE m.kind = 'embedding_config' "
            "RETURN m.model, m.dim LIMIT 1"
        )
    except Exception as e:
        return False, f"Failed to read :Meta from {graph_name}: {e}"

    if not r.result_set:
        return True, "no embedding_config meta on graph (legacy/fresh build)"

    stored_model, stored_dim = r.result_set[0]
    cur_model = EcoSimConfig.llm_embedding_model()
    cur_dim = EcoSimConfig.llm_embedding_dim_hint(cur_model) or stored_dim

    if stored_model != cur_model:
        return False, (
            f"Embedding model mismatch: graph='{stored_model}' env='{cur_model}'. "
            f"Rebuild master KG hoặc revert env."
        )
    if stored_dim != cur_dim:
        return False, (
            f"Embedding dim mismatch: graph={stored_dim}, env={cur_dim}."
        )
    return True, ""


# ──────────────────────────────────────────────
# Stats — count nodes/edges/episodes trong 1 graph
# ──────────────────────────────────────────────
def graph_stats(graph_name: str) -> Dict[str, int]:
    """Return {node_count, edge_count, episode_count} cho graph trong FalkorDB.

    Returns 0 cho missing graph (idempotent).
    """
    fdb = _falkor_client()
    if graph_name not in fdb.list_graphs():
        return {"node_count": 0, "edge_count": 0, "episode_count": 0}
    g = fdb.select_graph(graph_name)
    try:
        n = g.query("MATCH (n) RETURN count(n)").result_set[0][0]
        e = g.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
        ep = g.query("MATCH (n:Episodic) RETURN count(n)").result_set[0][0]
        return {"node_count": int(n), "edge_count": int(e), "episode_count": int(ep)}
    except Exception as ex:
        logger.warning("graph_stats(%s) fail: %s", graph_name, ex)
        return {"node_count": 0, "edge_count": 0, "episode_count": 0}


# ──────────────────────────────────────────────
# Clone (master → sim)
# ──────────────────────────────────────────────
async def clone_campaign_graph_in_falkor(cid: str, sid: str) -> Dict:
    """Clone master KG (graph=cid) sang sim graph (sim_<sid>) bằng pure Cypher.

    Steps:
      1. Verify master tồn tại trong FalkorDB.
      2. Verify embedding compat.
      3. Drop sim graph nếu đã tồn tại.
      4. Read all nodes batch → group by labels → CREATE vào sim graph.
      5. Read all edges → group by relationship type → CREATE.
      6. Rebuild Graphiti indexes trên sim graph.

    Returns:
      {node_count, edge_count, episode_count, vector_index_built, elapsed_ms,
       src_graph, dst_graph}
    """
    t0 = time.time()
    src_graph = cid
    dst_graph = sim_graph_name(sid)

    # ── Step 1: verify master exists ──
    try:
        fdb = _falkor_client()
        available = fdb.list_graphs()
    except Exception as e:
        logger.exception("Clone[Step1]: FalkorDB connect/list_graphs fail")
        raise RuntimeError(f"FalkorDB connect failed: {type(e).__name__}: {e}") from e

    if src_graph not in available:
        raise ValueError(
            f"Master KG '{src_graph}' không tồn tại trong FalkorDB. "
            f"Build KG trước khi prepare sim. Available: {available}"
        )

    # ── Step 2: verify embedding compat ──
    try:
        ok, reason = verify_embedding_compat(src_graph)
    except Exception as e:
        logger.exception("Clone[Step2]: verify_embedding_compat(%s) fail", src_graph)
        raise RuntimeError(f"verify_embedding_compat: {type(e).__name__}: {e}") from e
    if not ok:
        raise ValueError(f"Embedding compat check failed: {reason}")
    if reason:
        logger.info("Embedding compat: %s", reason)

    # ── Step 3: drop existing sim graph if any ──
    if dst_graph in available:
        try:
            logger.info("Dropping existing sim graph %s before re-clone", dst_graph)
            fdb.select_graph(dst_graph).delete()
        except Exception as e:
            logger.exception("Clone[Step3]: drop %s fail", dst_graph)
            raise RuntimeError(f"drop existing sim graph: {type(e).__name__}: {e}") from e

    src = fdb.select_graph(src_graph)
    dst = fdb.select_graph(dst_graph)

    # ── Step 4a: read all master nodes ──
    try:
        r = src.query("MATCH (n) RETURN labels(n) AS labels, properties(n) AS props")
    except Exception as e:
        logger.exception("Clone[Step4a]: read nodes from master %s fail", src_graph)
        raise RuntimeError(f"read master nodes: {type(e).__name__}: {e}") from e

    nodes_by_labels: Dict[Tuple[str, ...], List[Dict]] = defaultdict(list)
    for row in r.result_set:
        labels, props = row[0], row[1]
        label_tuple = tuple(sorted(labels)) if labels else ()
        props_dict = dict(props)
        props_dict["origin"] = "master_clone"
        nodes_by_labels[label_tuple].append(props_dict)

    total_nodes = sum(len(ns) for ns in nodes_by_labels.values())
    logger.info(
        "Clone %s → %s: read %d nodes across %d label groups",
        src_graph, dst_graph, total_nodes, len(nodes_by_labels),
    )

    # ── Step 4b: CREATE nodes vào sim graph (per label group, batched) ──
    nodes_created = 0
    for labels_tuple, props_list in nodes_by_labels.items():
        safe_labels = [lab for lab in labels_tuple if _is_safe_identifier(lab)]
        if labels_tuple and not safe_labels:
            logger.warning("Skipping nodes with unsafe labels: %r", labels_tuple)
            continue
        label_str = (":" + ":".join(safe_labels)) if safe_labels else ""
        for i in range(0, len(props_list), _BATCH_SIZE):
            batch = props_list[i : i + _BATCH_SIZE]
            cypher = f"UNWIND $batch AS p CREATE (n{label_str}) SET n = p RETURN count(n)"
            try:
                dst.query(cypher, {"batch": batch})
                nodes_created += len(batch)
            except Exception as e:
                logger.exception(
                    "Clone[Step4b]: CREATE node batch fail | labels=%r batch_idx=%d "
                    "batch_size=%d sample_props_keys=%r",
                    labels_tuple, i, len(batch),
                    list(batch[0].keys())[:10] if batch else [],
                )
                raise RuntimeError(
                    f"CREATE nodes (labels={labels_tuple}, batch_idx={i}): "
                    f"{type(e).__name__}: {e}"
                ) from e

    # ── Step 5a: read all master edges ──
    try:
        r = src.query(
            "MATCH (a)-[r]->(b) "
            "RETURN a.uuid AS src_uuid, b.uuid AS dst_uuid, type(r) AS rtype, "
            "       properties(r) AS props"
        )
    except Exception as e:
        logger.exception("Clone[Step5a]: read edges from master %s fail", src_graph)
        raise RuntimeError(f"read master edges: {type(e).__name__}: {e}") from e

    edges_by_type: Dict[str, List[Dict]] = defaultdict(list)
    dropped = 0
    for row in r.result_set:
        src_uuid, dst_uuid, rtype, props = row[0], row[1], row[2], row[3]
        if not src_uuid or not dst_uuid:
            dropped += 1
            continue
        edges_by_type[rtype].append({
            "src": src_uuid,
            "dst": dst_uuid,
            "props": dict(props) if props else {},
        })

    total_edges = sum(len(es) for es in edges_by_type.values())
    logger.info(
        "Read %d edges across %d types (dropped %d missing uuid)",
        total_edges, len(edges_by_type), dropped,
    )

    # ── Step 5b: CREATE edges vào sim graph (per rtype, batched) ──
    edges_created = 0
    for rtype, edge_list in edges_by_type.items():
        if not _is_safe_identifier(rtype):
            logger.warning("Skipping edges with unsafe type: %r", rtype)
            continue
        for i in range(0, len(edge_list), _BATCH_SIZE):
            batch = edge_list[i : i + _BATCH_SIZE]
            cypher = (
                f"UNWIND $batch AS e "
                f"MATCH (a {{uuid: e.src}}), (b {{uuid: e.dst}}) "
                f"CREATE (a)-[r:{rtype}]->(b) SET r = e.props RETURN count(r)"
            )
            try:
                dst.query(cypher, {"batch": batch})
                edges_created += len(batch)
            except Exception as e:
                logger.exception(
                    "Clone[Step5b]: CREATE edge batch fail | rtype=%s batch_idx=%d "
                    "batch_size=%d",
                    rtype, i, len(batch),
                )
                raise RuntimeError(
                    f"CREATE edges (rtype={rtype}, batch_idx={i}): "
                    f"{type(e).__name__}: {e}"
                ) from e

    # ── Step 6: rebuild Graphiti indexes ──
    vector_index_built = False
    try:
        from ecosim_common.graphiti_factory import (
            make_graphiti, make_falkor_driver, build_indices_with_retry,
        )
        driver = make_falkor_driver(
            host=os.environ.get("FALKORDB_HOST", "localhost"),
            port=int(os.environ.get("FALKORDB_PORT", 6379)),
            database=dst_graph,
        )
        graphiti = make_graphiti(driver)
        vector_index_built = await build_indices_with_retry(graphiti, max_retries=3)
        await graphiti.close()
        if vector_index_built:
            logger.info("Built Graphiti indexes on %s", dst_graph)
    except Exception as e:
        logger.error("Failed rebuild indexes on %s: %s", dst_graph, e)

    # Episode count for return
    ep_count = 0
    try:
        ep_count = int(dst.query("MATCH (n:Episodic) RETURN count(n)").result_set[0][0])
    except Exception:
        pass

    elapsed_ms = int((time.time() - t0) * 1000)
    result = {
        "node_count": total_nodes,
        "edge_count": total_edges,
        "episode_count": ep_count,
        "vector_index_built": vector_index_built,
        "elapsed_ms": elapsed_ms,
        "src_graph": src_graph,
        "dst_graph": dst_graph,
    }
    logger.info("Clone done: %s", result)
    return result


# ──────────────────────────────────────────────
# Drop helpers
# ──────────────────────────────────────────────
def drop_sim_graph(sim_id: str) -> bool:
    """Drop FalkorDB graph cho sim. Idempotent."""
    name = sim_graph_name(sim_id)
    fdb = _falkor_client()
    if name not in fdb.list_graphs():
        return False
    fdb.select_graph(name).delete()
    logger.info("Dropped sim graph %s", name)
    return True


def drop_master_graph(cid: str) -> bool:
    """Drop FalkorDB master graph của campaign. Idempotent."""
    fdb = _falkor_client()
    if cid not in fdb.list_graphs():
        return False
    fdb.select_graph(cid).delete()
    logger.info("Dropped master graph %s", cid)
    return True


def drop_campaign_graphs(cid: str, sim_ids: List[str]) -> Dict[str, int]:
    """Cascade drop: all sim graphs + master. Idempotent."""
    sims_dropped = sum(1 for sid in sim_ids if drop_sim_graph(sid))
    master_dropped = 1 if drop_master_graph(cid) else 0
    return {"sims_dropped": sims_dropped, "master_dropped": master_dropped}
