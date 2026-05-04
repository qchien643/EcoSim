"""
Zep Cloud hybrid KG writer — extract via Zep server-side, mirror vào FalkorDB.

Pipeline:
  1. Init AsyncZep client (ZEP_API_KEY env)
  2. Tạo/verify graph trên Zep với graph_id = campaign_id
  3. add_batch sections → server-side parallel LLM extract
  4. Poll episode.get(uuid_).processed cho tất cả episodes
  5. Fetch nodes + edges + episodes (rich attrs, temporal validity)
  6. Re-embed local (Zep KHÔNG expose embeddings — phải tự embed cho FalkorDB)
  7. Cypher MERGE vào FalkorDB graph campaign_id với:
     - Multi-label `:Entity:<canonical>` (mapped from Zep labels)
     - Attributes dict spread thành properties
     - Edges với valid_at, invalid_at, expired_at, episodes back-refs
     - :Episodic nodes với entity_edges array
  8. Build Graphiti vector indexes
  9. Write embedding meta

Speedup vs Graphiti add_episode (legacy 60min): ~30-60s tổng (Zep server-side).
Info gain vs direct write: rich attributes + temporal validity + cross-section
semantic dedup + episode-edge traceability.

Cost: ~30-35 credits/build (free tier 1000/mo). Re-embed local ~$0.0004/build.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ecosim_common.llm_client import LLMClient
from ecosim_common.zep_client import make_async_zep_client, ZepKeyMissing
from ecosim_common.zep_label_map import (
    zep_labels_to_canonical,
    is_safe_cypher_label,
)

if TYPE_CHECKING:
    from campaign_knowledge import AnalyzedSection

logger = logging.getLogger("sim-svc.zep_kg_writer")

# Canonical edge types (sync với apps/simulation/campaign_knowledge.py)
CANONICAL_EDGE_TYPES = frozenset({
    "INVESTS_IN", "COMPETES_WITH", "SUPPLIES_TO", "REGULATES", "CONSUMES",
    "REPORTS_ON", "PARTNERS_WITH", "AFFECTS", "RUNS", "TARGETS",
    "PRODUCES", "EMPLOYS",
})


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _normalize_edge_type(zep_name: Optional[str]) -> str:
    """Zep edge.name (vd "competes_with", "is part of", "Dùng nhiều") →
    canonical Cypher label safe ASCII (vd "COMPETES_WITH").

    Vietnamese diacritics (Ù, Ề, ...) bị strip vì FalkorDB Cypher chỉ chấp
    nhận ASCII [A-Za-z0-9_]. ASCII transliteration đơn giản qua NFD
    decomposition + filter combining marks. Fallback "RELATES_TO".
    """
    if not zep_name:
        return "RELATES_TO"
    import unicodedata
    # NFD decompose: "Ù" → "U" + combining mark; filter Mn (combining marks)
    nfd = unicodedata.normalize("NFD", zep_name.strip())
    ascii_only = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # Now uppercase + replace non-ASCII-alphanum với _ (handles Đ → still
    # non-ASCII, will be replaced).
    upper = ascii_only.upper()
    cleaned = re.sub(r"[^A-Z0-9]+", "_", upper).strip("_")
    if not cleaned or not cleaned[0].isalpha():
        return "RELATES_TO"
    if not is_safe_cypher_label(cleaned):
        return "RELATES_TO"
    return cleaned  # canonical match optional, valid ASCII edge_type


def _safe_attr_value(value: Any) -> Any:
    """Convert attribute value sang FalkorDB-safe type. Dict/list → JSON string."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        # Check if homogeneous primitive list (FalkorDB ok)
        if all(isinstance(v, (str, int, float, bool)) for v in value):
            return list(value)
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _to_iso(dt) -> Optional[str]:
    """Convert datetime → ISO string. None passthrough."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


# ──────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────
async def write_kg_via_zep(
    graph_name: str,
    sections: "List[AnalyzedSection]",
    llm: LLMClient,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
    extracted_dir: Optional[Path] = None,
    source_description: str = "Campaign document",
    reference_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Hybrid build: Zep extract → FalkorDB mirror.

    Args:
        graph_name: FalkorDB graph name = Zep graph_id (= campaign_id).
        sections: Stage 1 parsed AnalyzedSection list. Chỉ dùng `original.content`
            + `original.title` — Zep tự extract entities/facts, KHÔNG dùng
            output Stage 2 entities/facts (Zep extract chất lượng cao hơn).
        llm: LLMClient cho re-embed local (Zep không expose embeddings).
        extracted_dir: Optional path để cache zep_response.json snapshot.

    Returns:
        Stats dict {method, nodes_merged, edges_merged, episodes_written,
                    elapsed_ms, zep_credits_used (estimated)}.

    Raises:
        ZepKeyMissing: ZEP_API_KEY env chưa set.
        TimeoutError: Episodes vẫn processing sau 3 phút.
        Exception: Network/API errors.
    """
    from zep_cloud.types.episode_data import EpisodeData
    from build_progress import update as _bp_update

    t_start = _time.time()
    ref_time = reference_time or datetime.now(timezone.utc)
    now_iso = ref_time.isoformat()

    n_sections = len(sections)
    logger.info(
        "🚀 Zep hybrid KG build START | graph=%s | %d sections",
        graph_name, n_sections,
    )

    # ── Cache check: load extracted/zep_response.json nếu có để skip Zep ──
    snapshot_path = Path(extracted_dir) / "zep_response.json" if extracted_dir else None
    cached_snapshot: Optional[Dict[str, Any]] = None
    if snapshot_path and snapshot_path.exists():
        try:
            with open(snapshot_path, "r", encoding="utf-8") as f:
                cached_snapshot = json.load(f)
            logger.info(
                "💾 Loaded zep_response.json cache (%d nodes, %d edges) — skipping Zep API",
                len(cached_snapshot.get("nodes", [])),
                len(cached_snapshot.get("edges", [])),
            )
            _bp_update(
                graph_name, "zep_cache_hit", 70,
                f"Loaded Zep snapshot từ cache (skip API): "
                f"{len(cached_snapshot.get('nodes', []))} nodes",
            )
        except Exception as e:
            logger.warning("Failed to load zep_response.json cache: %s — re-fetch", e)
            cached_snapshot = None

    # `submitted_uuids` track số episodes Zep extract (cho stats result).
    # Cache hit → ước tính = len(cached episodes). Fresh fetch → từ add_batch.
    submitted_uuids: List[str] = []

    if cached_snapshot is not None:
        # ── Cache hit: skip Zep API, reconstruct from JSON ──────────────
        from zep_cloud.types.entity_node import EntityNode
        from zep_cloud.types.entity_edge import EntityEdge
        from zep_cloud.types.episode import Episode
        nodes = [EntityNode.model_validate(d) for d in cached_snapshot.get("nodes", [])]
        edges = [EntityEdge.model_validate(d) for d in cached_snapshot.get("edges", [])]
        episodes = [Episode.model_validate(d) for d in cached_snapshot.get("episodes", [])]
        # Cache → assume tất cả episodes đã processed (since cache only saved sau done)
        submitted_uuids = [ep.uuid_ for ep in episodes if ep.uuid_]
        logger.info(
            "Reconstructed from cache: %d nodes, %d edges, %d episodes",
            len(nodes), len(edges), len(episodes),
        )
    else:
        # ── Step 1-5: Zep API calls (full path) ──────────────────────────
        _bp_update(graph_name, "zep_init", 5, "Initializing Zep Cloud client...")
        zep = make_async_zep_client()

        # ── Step 2: Create graph (idempotent) ─────────────────────────────
        _bp_update(
            graph_name, "zep_create_graph", 10,
            f"Creating Zep graph '{graph_name}'...",
        )
        try:
            await zep.graph.create(
                graph_id=graph_name,
                name=graph_name,
                description=source_description[:500],
            )
            logger.info("Created Zep graph: %s", graph_name)
        except Exception as e:
            msg = str(e).lower()
            if "exist" in msg or "duplicate" in msg or "409" in msg:
                logger.info("Zep graph %s exists, reusing", graph_name)
            else:
                logger.warning("graph.create failed: %s — continue (might exist)", e)

        # ── Step 2b: Apply EcoSim ontology trước add_batch ───────────────
        # Zep extract LLM tuân theo ontology để output canonical labels +
        # rich attributes. Không có bước này → labels=[] + attrs={"name": ...}.
        _bp_update(
            graph_name, "zep_set_ontology", 15,
            "Applying EcoSim ontology (14 entity types + 12 edge types)...",
        )
        from zep_ontology import apply_ontology
        await apply_ontology(zep, graph_name)

        # ── Step 3: Submit episodes ───────────────────────────────────────
        _bp_update(
            graph_name, "zep_add_batch", 20,
            f"Submitting {n_sections} sections to Zep (server-side parallel extract)...",
        )
        episodes_data = []
        for s in sections:
            body = (s.original.content or "").strip()
            if not body:
                continue
            body = body[:9500]
            title = (s.original.title or f"section_{s.original.index}")[:200]
            episodes_data.append(EpisodeData(
                data=body,
                type="text",
                source_description=f"{source_description} - {title}",
            ))

        if not episodes_data:
            raise ValueError("No non-empty sections to submit to Zep")

        submitted = await zep.graph.add_batch(
            graph_id=graph_name,
            episodes=episodes_data,
        )
        submitted_uuids = [ep.uuid_ for ep in submitted if ep.uuid_]
        logger.info("Submitted %d episodes to Zep, awaiting processing", len(submitted_uuids))

        # ── Step 4: Poll until all processed ──────────────────────────────
        _bp_update(
            graph_name, "zep_polling_tasks", 30,
            f"Waiting for Zep to process {len(submitted_uuids)} episodes (LLM extract)...",
        )
        pending = list(submitted_uuids)
        poll_timeout_s = 240
        poll_interval = 3
        elapsed = 0
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
            if len(still) != len(pending):
                done_count = len(submitted_uuids) - len(still)
                pct = 30 + int(40 * done_count / max(1, len(submitted_uuids)))
                _bp_update(
                    graph_name, "zep_polling_tasks", pct,
                    f"Zep processed {done_count}/{len(submitted_uuids)} episodes",
                )
            pending = still

        if pending:
            raise TimeoutError(
                f"Zep extraction timed out: {len(pending)}/{len(submitted_uuids)} "
                f"episodes still processing after {poll_timeout_s}s"
            )
        logger.info("All %d episodes processed by Zep", len(submitted_uuids))

        # ── Step 5: Fetch nodes + edges + episodes ────────────────────────
        _bp_update(
            graph_name, "zep_fetch_nodes", 75,
            "Fetching extracted nodes + edges + episodes from Zep...",
        )
        nodes = await zep.graph.node.get_by_graph_id(graph_name, limit=1000)
        edges = await zep.graph.edge.get_by_graph_id(graph_name, limit=1000)
        eps_resp = await zep.graph.episode.get_by_graph_id(graph_name, lastn=1000)
        episodes = getattr(eps_resp, "episodes", None) or []
        logger.info(
            "Fetched from Zep: %d nodes, %d edges, %d episodes",
            len(nodes), len(edges), len(episodes),
        )

        # ── Step 6: Cache snapshot to extracted/zep_response.json ─────────
        if snapshot_path:
            try:
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot = {
                    "graph_id": graph_name,
                    "fetched_at": _to_iso(ref_time),
                    "nodes": [n.model_dump(mode="json") for n in nodes],
                    "edges": [e.model_dump(mode="json") for e in edges],
                    "episodes": [ep.model_dump(mode="json") for ep in episodes],
                }
                with open(snapshot_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
                logger.info("💾 Saved zep_response.json (%d KB)", snapshot_path.stat().st_size // 1024)
            except Exception as e:
                logger.warning("Failed to cache zep_response.json: %s", e)

    # ── Step 7: Re-embed local (4 batch calls, sequential w/ retry) ──
    # Đã thử parallel via asyncio.gather nhưng trên Windows asyncio +
    # httpx pool, batch cuối hay bị cancelled (TimeoutError) sau khi đã
    # chạy nhiều API calls (zep + embed). Sequential với per-call timeout
    # + 1 retry stable hơn — total ~4-8s cho 4 batches nhỏ.
    _bp_update(
        graph_name, "zep_re_embedding", 80,
        f"Re-embedding {len(nodes)} entities + {len(edges)} edges + {len(episodes)} episodes locally...",
    )
    _embed_t0 = _time.time()

    async def _embed_seq(label: str, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        last_exc = None
        for attempt in range(2):
            try:
                _bp_update(
                    graph_name, "zep_re_embedding", 80,
                    f"Embedding {label} (n={len(texts)}, attempt {attempt + 1})...",
                )
                return await asyncio.wait_for(
                    llm.embed_batch_async(texts), timeout=60.0,
                )
            except (asyncio.TimeoutError, Exception) as e:
                last_exc = e
                logger.warning(
                    "Embed batch '%s' attempt %d failed: %s (will %s)",
                    label, attempt + 1, type(e).__name__,
                    "retry" if attempt < 1 else "give up",
                )
                # Brief pause before retry để httpx pool reset
                await asyncio.sleep(1.0)
        raise last_exc or RuntimeError(f"embed batch {label} failed")

    name_texts = [n.name for n in nodes] if nodes else []
    summary_texts = [(n.summary or n.name) for n in nodes] if nodes else []
    fact_texts = [e.fact or e.name or "" for e in edges] if edges else []
    body_texts = [(ep.content or "")[:8000] for ep in episodes] if episodes else []

    name_embs = await _embed_seq("names", name_texts)
    summary_embs = await _embed_seq("summaries", summary_texts)
    fact_embs = await _embed_seq("facts", fact_texts)
    body_embs = await _embed_seq("bodies", body_texts)
    logger.info(
        "Re-embeddings done in %.1fs | names=%d summaries=%d facts=%d bodies=%d",
        _time.time() - _embed_t0,
        len(name_embs), len(summary_embs), len(fact_embs), len(body_embs),
    )

    # ── Step 8: Cypher MERGE into FalkorDB ────────────────────────────
    _bp_update(
        graph_name, "zep_cypher_mirror", 88,
        "Mirroring to FalkorDB (Cypher MERGE entities + edges + episodics)...",
    )
    from falkordb import FalkorDB

    fdb = FalkorDB(host=falkor_host, port=int(falkor_port))
    g = fdb.select_graph(graph_name)

    # 8a. MERGE entities với multi-label + attributes spread
    entities_written = 0
    n_total_entities = len(nodes)
    for node_idx, (node, name_emb, sum_emb) in enumerate(zip(nodes, name_embs, summary_embs)):
        # Update progress mỗi 25 entities để user thấy tiến độ Cypher loop
        if node_idx % 25 == 0:
            _bp_update(
                graph_name, "zep_cypher_mirror", 88,
                f"Cypher MERGE entities {node_idx}/{n_total_entities}...",
            )
        canonical = zep_labels_to_canonical(node.labels)
        label_clause = "Entity" if canonical == "Entity" else f"Entity:{canonical}"

        # Base entity properties
        params: Dict[str, Any] = {
            "uuid": node.uuid_,
            "name": node.name or "",
            "summary": node.summary or "",
            "name_emb": name_emb,
            "sum_emb": sum_emb,
            "etype": canonical,
            "labels": list(node.labels or []),
            "gid": graph_name,
            "created": _to_iso(node.created_at),
        }
        # vecf32() wrap so FalkorDB stores Vectorf32 (required by Graphiti's
        # vec.cosineDistance search at runtime — list-typed properties error).
        cypher = (
            f"MERGE (n:{label_clause} {{uuid: $uuid}}) "
            "SET n.name = $name, "
            "    n.summary = $summary, "
            "    n.name_embedding = vecf32($name_emb), "
            "    n.summary_embedding = vecf32($sum_emb), "
            "    n.entity_type = $etype, "
            "    n.zep_labels = $labels, "
            "    n.group_id = $gid, "
            "    n.created_at = coalesce(n.created_at, $created)"
        )
        g.query(cypher, params)
        entities_written += 1

        # Spread attributes as separate properties (tránh Cypher injection
        # qua property name — chỉ accept safe identifiers).
        attrs = node.attributes or {}
        if attrs:
            safe_attrs = {
                k: _safe_attr_value(v)
                for k, v in attrs.items()
                if is_safe_cypher_label(k) and v is not None
            }
            if safe_attrs:
                # Build dynamic SET với mỗi key safe — không inject value.
                set_clauses = ", ".join(f"n.{k} = ${k}" for k in safe_attrs.keys())
                attr_cypher = (
                    f"MATCH (n {{uuid: $uuid}}) SET {set_clauses}"
                )
                g.query(attr_cypher, {"uuid": node.uuid_, **safe_attrs})

    logger.info("MERGEd %d entities", entities_written)

    # 8b. MERGE edges với temporal + episodes
    # Group by edge_type cho UNWIND batch
    edges_by_type: Dict[str, List[Dict]] = {}
    for edge, fact_emb in zip(edges, fact_embs):
        etype = _normalize_edge_type(edge.name)
        if not is_safe_cypher_label(etype):
            etype = "RELATES_TO"
        edges_by_type.setdefault(etype, []).append({
            "uuid": edge.uuid_,
            "src": edge.source_node_uuid,
            "dst": edge.target_node_uuid,
            "fact": edge.fact or "",
            "fact_emb": fact_emb,
            "predicate": edge.name or "",
            "valid_at": _to_iso(edge.valid_at),
            "invalid_at": _to_iso(edge.invalid_at),
            "expired_at": _to_iso(edge.expired_at),
            "episodes": list(edge.episodes or []),
            "created": _to_iso(edge.created_at),
        })

    edges_written = 0
    for etype, batch in edges_by_type.items():
        cypher = (
            "UNWIND $batch AS e "
            "MATCH (a {uuid: e.src}), (b {uuid: e.dst}) "
            f"MERGE (a)-[r:{etype} {{uuid: e.uuid}}]->(b) "
            "SET r.fact = e.fact, "
            "    r.fact_embedding = vecf32(e.fact_emb), "
            "    r.predicate = e.predicate, "
            "    r.valid_at = e.valid_at, "
            "    r.invalid_at = e.invalid_at, "
            "    r.expired_at = e.expired_at, "
            "    r.episodes = e.episodes, "
            "    r.edge_type = $etype, "
            "    r.group_id = $gid, "
            "    r.created_at = coalesce(r.created_at, e.created)"
        )
        g.query(cypher, {"batch": batch, "etype": etype, "gid": graph_name})
        edges_written += len(batch)
    logger.info("MERGEd %d edges across %d types", edges_written, len(edges_by_type))

    # 8c. MERGE :Episodic nodes
    episodes_written = 0
    for ep, body_emb in zip(episodes, body_embs):
        params = {
            "uuid": ep.uuid_,
            "name": getattr(ep, "name", None) or f"Episode {ep.uuid_[:8]}",
            "content": (ep.content or "")[:5000],
            "name_emb": body_emb,
            "source": getattr(ep, "source", "text"),
            "sd": getattr(ep, "source_description", "") or "",
            "gid": graph_name,
            "ref": now_iso,
            "created": _to_iso(ep.created_at),
        }
        cypher = (
            "MERGE (e:Episodic {uuid: $uuid}) "
            "SET e.name = $name, "
            "    e.content = $content, "
            "    e.name_embedding = vecf32($name_emb), "
            "    e.source = $source, "
            "    e.source_description = $sd, "
            "    e.group_id = $gid, "
            "    e.valid_at = $ref, "
            "    e.created_at = coalesce(e.created_at, $created)"
        )
        g.query(cypher, params)
        episodes_written += 1
    logger.info("MERGEd %d episodes", episodes_written)

    # 8d. :MENTIONS edges từ Episodic → Entities (qua edge.episodes back-refs)
    # Mỗi edge có episodes[] = list episode uuids → tạo :MENTIONS từ episode
    # tới cả 2 endpoints của edge. Batch UNWIND để tránh N+1 round-trips.
    _bp_update(graph_name, "zep_cypher_mirror", 92, "Building :MENTIONS edges...")
    mentions_written = 0
    # Build episode_uuid → set of entity_uuids xuất hiện
    epi_to_entities: Dict[str, set] = {}
    for edge in edges:
        for ep_uuid in (edge.episodes or []):
            s = epi_to_entities.setdefault(ep_uuid, set())
            if edge.source_node_uuid:
                s.add(edge.source_node_uuid)
            if edge.target_node_uuid:
                s.add(edge.target_node_uuid)

    # Batch UNWIND tất cả mentions trong 1 query (thay vì N queries)
    mention_pairs = [
        {"eid": epi_uuid, "nid": ent_uuid}
        for epi_uuid, ent_uuids in epi_to_entities.items()
        for ent_uuid in ent_uuids
    ]
    if mention_pairs:
        g.query(
            "UNWIND $pairs AS p "
            "MATCH (e:Episodic {uuid: p.eid}), (n {uuid: p.nid}) "
            "MERGE (e)-[m:MENTIONS]->(n) "
            "SET m.group_id = $gid, "
            "    m.created_at = coalesce(m.created_at, $now)",
            {"pairs": mention_pairs, "gid": graph_name, "now": now_iso},
        )
        mentions_written = len(mention_pairs)
    logger.info("MERGEd %d :MENTIONS edges (batch UNWIND)", mentions_written)

    # ── Step 9: Build Graphiti vector + lookup indexes ────────────────
    _bp_update(
        graph_name, "zep_indexes", 96,
        "Building Graphiti indexes (HNSW vector + lookup)...",
    )
    indexes_built = False
    try:
        from ecosim_common.graphiti_factory import (
            make_graphiti, make_falkor_driver,
        )
        driver = make_falkor_driver(
            host=falkor_host, port=falkor_port, database=graph_name,
        )
        graphiti = make_graphiti(driver, llm=llm)
        from ecosim_common.graphiti_factory import build_indices_with_retry
        indexes_built = await build_indices_with_retry(graphiti, max_retries=3)
        await graphiti.close()
        if not indexes_built:
            logger.warning("Graphiti index build failed sau retry — search may degrade")
    except Exception as e:
        logger.warning("Graphiti index build failed: %s — search may degrade", e)

    # ── Step 10: Embedding meta vào FalkorDB :Meta node ─────────────
    try:
        from sim_graph_clone import write_embedding_meta
        write_embedding_meta(graph_name)
    except Exception as e:
        logger.warning("Failed to write embedding meta: %s", e)

    # ── Step 11: Sync meta.db kg_status ─────────────────────────────
    # Phase 10: FalkorDB là source of truth — không còn JSON snapshot/chroma.
    try:
        _bp_update(graph_name, "syncing_metadata", 98, "Syncing meta.db...")
        from ecosim_common.metadata_index import update_campaign_kg_status
        update_campaign_kg_status(
            graph_name,
            status="ready",
            node_count=entities_written,
            edge_count=edges_written,
            episode_count=episodes_written,
            embedding_model=getattr(llm, "embedding_model", "text-embedding-3-small"),
            embedding_dim=len(name_embs[0]) if name_embs else 1536,
            extraction_model="zep_cloud",
            set_built_at=True,
        )
    except Exception as e:
        logger.warning("Failed to sync meta.db kg_status for %s: %s", graph_name, e)

    # ── Done ──────────────────────────────────────────────────────────
    elapsed_ms = int((_time.time() - t_start) * 1000)
    result = {
        "method": "zep_hybrid",
        "nodes_merged": entities_written,
        "edges_merged": edges_written,
        "episodes_written": episodes_written,
        "mentions_written": mentions_written,
        "embedding_calls": 4,  # name + summary + fact + body batches
        "indexes_built": indexes_built,
        "elapsed_ms": elapsed_ms,
        "zep_episodes_submitted": len(submitted_uuids),
        "credit_estimate": len(submitted_uuids),  # rough — 1 episode ~1 credit/350 bytes
    }
    logger.info(
        "✅ Zep hybrid done in %.1fs | %d entities + %d edges + %d episodes + %d mentions",
        elapsed_ms / 1000, entities_written, edges_written, episodes_written, mentions_written,
    )
    return result
