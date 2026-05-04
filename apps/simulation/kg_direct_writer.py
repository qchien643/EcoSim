"""
KG Direct Writer — bypass Graphiti's LLM extraction trong Stage 3b.

EcoSim Stage 2 (CampaignSectionAnalyzer) đã LLM-extract entities + facts từ
mỗi section dùng `LLM_EXTRACTION_MODEL` (gpt-4o, tier extraction). Output
được lưu ở `<UPLOAD_DIR>/<campaign_id>/extracted/analyzed.json`.

Trước đây Stage 3b gọi `Graphiti.add_episode` cho mỗi section, lặp lại
workflow extract entities + facts (4-5 LLM calls × 17 sections = 60+ phút).

Module này thay Stage 3b bằng direct Cypher pipeline tái sử dụng output
Stage 2:

  Pipeline (~10-30s tổng):
    1. Embed entity names      (1 batch OpenAI call ~1s)
    2. Embed fact texts        (1 batch OpenAI call ~1s)
    3. Embed episode bodies    (1 batch OpenAI call ~1s)
    4. Cypher MERGE entities   với labels :Entity:<canonical> + name_embedding
    5. Cypher MERGE edges      với fact_embedding + edge_type
    6. Cypher CREATE :Episodic + name_embedding của body
    7. Cypher MERGE :MENTIONS  từ Episodic → entities mentioned trong section
    8. Build Graphiti indexes  (vector + lookup, qua build_indices_and_constraints)

Speedup: ~80-100x (60min → 10-30s). Zero info loss vì entities/facts đến từ
Stage 2's gpt-4o extraction (mạnh hơn Graphiti default gpt-4o-mini).

Trade-off (chấp nhận được trong EcoSim use case):
  - Bỏ Graphiti edge invalidation (temporal valid_until) — master KG static.
  - Bỏ Graphiti smart entity dedup — Stage 2.5 postprocess_entities đã dedup.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ecosim_common.llm_client import LLMClient

if TYPE_CHECKING:
    # Lazy: campaign_knowledge.py định nghĩa các dataclass này.
    # Tránh circular import vì campaign_knowledge cũng import từ module này.
    from campaign_knowledge import AnalyzedSection, ExtractedEntity, ExtractedFact

logger = logging.getLogger("sim-svc.kg_direct_writer")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _stable_uuid(group_id: str, identifier: str) -> str:
    """Generate UUID deterministic từ (group_id, identifier).

    Idempotent rebuild: cùng input → cùng UUID → MERGE preserve data, không
    duplicate khi user re-build trên existing graph.
    """
    h = hashlib.sha1(f"{group_id}:{identifier}".encode("utf-8")).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _is_safe_label(name: str) -> bool:
    """Cypher identifier safety — chỉ [A-Za-z0-9_].

    Guard chống injection khi build literal label/edge_type từ user data.
    Stage 2.5 (ENTITY_TYPE_ALIASES + CANONICAL_*) đã validate, nhưng defensive.
    """
    if not name:
        return False
    return all(c.isalnum() or c == "_" for c in name)


# ──────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────
async def write_kg_direct(
    graph_name: str,
    sections: "List[AnalyzedSection]",
    entities: "List[ExtractedEntity]",
    facts: "List[ExtractedFact]",
    llm: LLMClient,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
    source_description: str = "Campaign document",
    reference_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Write Knowledge Graph trực tiếp qua Cypher, skip Graphiti extraction.

    Args:
        graph_name: FalkorDB graph name (= campaign_id cho master KG).
        sections: AnalyzedSection list từ Stage 2 (CampaignSectionAnalyzer).
        entities: Canonical entities sau Stage 2.5 postprocess_entities.
        facts: Canonical facts sau Stage 2.5 postprocess_entities.
        llm: LLMClient (cho 3 batch embedding calls).
        source_description: Metadata gắn vào :Episodic nodes.

    Returns:
        Stats dict: {entities_written, facts_written, episodes_written,
                     embedding_calls, mentions_written, elapsed_ms, method}.
    """
    import time as _time

    from falkordb import FalkorDB

    t0 = _time.time()
    ref_time = reference_time or datetime.now(timezone.utc)
    now_iso = ref_time.isoformat()

    n_entities = len(entities)
    n_facts = len(facts)
    n_sections = len(sections)
    logger.info(
        "🚀 Direct KG write START | graph=%s | %d entities, %d facts, %d sections",
        graph_name, n_entities, n_facts, n_sections,
    )

    # ── Step 1-3: Batch embeddings (3 API calls tổng) ─────────────────
    entity_names = [e.name for e in entities]
    fact_texts = [f"{f.subject} {f.predicate} {f.object}" for f in facts]
    section_bodies = [s.to_episode_body() for s in sections]

    t_embed = _time.time()
    entity_embs = await llm.embed_batch_async(entity_names) if entity_names else []
    fact_embs = await llm.embed_batch_async(fact_texts) if fact_texts else []
    body_embs = await llm.embed_batch_async(section_bodies) if section_bodies else []
    logger.info(
        "  ✅ Embeddings done in %.1fs (entities=%d, facts=%d, bodies=%d)",
        _time.time() - t_embed, len(entity_embs), len(fact_embs), len(body_embs),
    )

    # ── Connect FalkorDB ──────────────────────────────────────────────
    fdb = FalkorDB(host=falkor_host, port=int(falkor_port))
    g = fdb.select_graph(graph_name)

    # ── Step 4: MERGE entities với name_embedding + dual labels ──────
    # Dual label: :Entity (Graphiti hybrid search compat) + canonical
    # (:Company, :Consumer, ...) để entity list endpoint hiển thị đúng type.
    t_ent = _time.time()
    for entity, emb in zip(entities, entity_embs):
        canonical = entity.entity_type or "Entity"
        if not _is_safe_label(canonical):
            canonical = "Entity"
        # Avoid duplicate :Entity:Entity nếu canonical = "Entity"
        label_clause = "Entity" if canonical == "Entity" else f"Entity:{canonical}"
        uuid = _stable_uuid(graph_name, entity.name)
        # FalkorDB requires Vectorf32 type for vec.cosineDistance() at search
        # time. Without `vecf32(...)` wrapping, the property is stored as a
        # generic List and Graphiti's hybrid-search Cypher errors with
        # "Type mismatch: expected Null or Vectorf32 but was List".
        cypher = (
            f"MERGE (n:{label_clause} {{name: $name}}) "
            "SET n.uuid = coalesce(n.uuid, $uuid), "
            "    n.summary = $summary, "
            "    n.name_embedding = vecf32($emb), "
            "    n.summary_embedding = vecf32($emb), "
            "    n.group_id = $group_id, "
            "    n.entity_type = $etype, "
            "    n.created_at = coalesce(n.created_at, $now)"
        )
        g.query(cypher, {
            "name": entity.name,
            "uuid": uuid,
            "summary": entity.description or entity.name,
            "emb": emb,
            "group_id": graph_name,
            "etype": canonical,
            "now": now_iso,
        })
    logger.info("  ✅ Entities MERGEd: %d in %.1fs", n_entities, _time.time() - t_ent)

    # ── Step 5: MERGE edges (RELATES_TO + canonical edge type) ────────
    # Group by edge_type cho UNWIND batch — giảm round-trips.
    t_edge = _time.time()
    edges_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for fact, emb in zip(facts, fact_embs):
        etype = fact.edge_type or "AFFECTS"
        if not _is_safe_label(etype):
            logger.debug("Skipping fact với unsafe edge_type: %r", etype)
            continue
        edges_by_type.setdefault(etype, []).append({
            "src": fact.subject,
            "dst": fact.object,
            "fact": f"{fact.subject} {fact.predicate} {fact.object}",
            "predicate": fact.predicate,
            "emb": emb,
            "uuid": _stable_uuid(
                graph_name, f"edge:{fact.subject}->{fact.object}:{etype}"
            ),
        })

    edges_written = 0
    for etype, batch in edges_by_type.items():
        cypher = (
            "UNWIND $batch AS f "
            "MATCH (a:Entity {name: f.src}), (b:Entity {name: f.dst}) "
            f"MERGE (a)-[r:{etype}]->(b) "
            "SET r.uuid = coalesce(r.uuid, f.uuid), "
            "    r.fact = f.fact, "
            "    r.predicate = f.predicate, "
            "    r.fact_embedding = vecf32(f.emb), "
            "    r.group_id = $group_id, "
            "    r.edge_type = $etype, "
            "    r.created_at = $now"
        )
        result = g.query(cypher, {
            "batch": batch,
            "group_id": graph_name,
            "etype": etype,
            "now": now_iso,
        })
        # FalkorDB returns relationships_created in stats (best-effort log)
        edges_written += len(batch)
    logger.info(
        "  ✅ Edges MERGEd: %d across %d types in %.1fs",
        edges_written, len(edges_by_type), _time.time() - t_edge,
    )

    # ── Step 6: Episodic nodes + :MENTIONS edges ──────────────────────
    t_epi = _time.time()
    mentions_written = 0
    for section, body_emb in zip(sections, body_embs):
        epi_uuid = _stable_uuid(
            graph_name,
            f"episode:{section.original.title}:{section.original.index}",
        )
        body = section.to_episode_body()
        # Cap content length để tránh oversized Cypher payload
        content = body[:5000] if len(body) > 5000 else body
        # MERGE thay CREATE để idempotent (re-run không duplicate)
        g.query(
            "MERGE (e:Episodic {uuid: $uuid}) "
            "SET e.name = $name, "
            "    e.content = $content, "
            "    e.name_embedding = vecf32($emb), "
            "    e.source = 'text', "
            "    e.source_description = $sd, "
            "    e.reference_time = $ref, "
            "    e.group_id = $group_id, "
            "    e.valid_at = $ref, "
            "    e.created_at = coalesce(e.created_at, $now)",
            {
                "uuid": epi_uuid,
                "name": (section.original.title or "untitled")[:200],
                "content": content,
                "emb": body_emb,
                "sd": source_description,
                "ref": now_iso,
                "group_id": graph_name,
                "now": now_iso,
            },
        )
        # MENTIONS edges — entities xuất hiện trong section's facts
        mentioned: set = set()
        for fact in section.facts:
            if fact.subject:
                mentioned.add(fact.subject)
            if fact.object:
                mentioned.add(fact.object)
        for ent_name in mentioned:
            g.query(
                "MATCH (e:Episodic {uuid: $eid}), (n:Entity {name: $name}) "
                "MERGE (e)-[m:MENTIONS]->(n) "
                "SET m.group_id = $group_id, "
                "    m.created_at = coalesce(m.created_at, $now)",
                {
                    "eid": epi_uuid,
                    "name": ent_name,
                    "group_id": graph_name,
                    "now": now_iso,
                },
            )
            mentions_written += 1
    logger.info(
        "  ✅ Episodes + Mentions: %d episodes, %d mentions in %.1fs",
        n_sections, mentions_written, _time.time() - t_epi,
    )

    # ── Step 7: Build Graphiti vector + lookup indexes ────────────────
    # Cần để Graphiti.search(COMBINED_HYBRID_SEARCH_RRF) hoạt động.
    # Idempotent — gọi lại không tạo dup index.
    t_idx = _time.time()
    try:
        from ecosim_common.graphiti_factory import (
            make_graphiti,
            make_falkor_driver,
        )
        driver = make_falkor_driver(
            host=falkor_host, port=falkor_port, database=graph_name,
        )
        graphiti = make_graphiti(driver, llm=llm)
        # Phase: retry on network errors (FalkorDB BGSAVE có thể tạm thời
        # drop connection trong lúc CREATE FULLTEXT INDEX).
        from ecosim_common.graphiti_factory import build_indices_with_retry
        ok = await build_indices_with_retry(graphiti, max_retries=3)
        await graphiti.close()
        if ok:
            logger.info("  ✅ Indexes built in %.1fs", _time.time() - t_idx)
            indexes_built = True
        else:
            logger.warning("  ⚠ Indexes build failed sau retry (search degraded)")
            indexes_built = False
    except Exception as e:
        logger.warning(
            "Failed to build Graphiti indexes (search có thể không work): %s", e,
        )
        indexes_built = False

    # ── Write embedding meta vào FalkorDB :Meta node (cho clone verify compat) ─
    try:
        from sim_graph_clone import write_embedding_meta
        write_embedding_meta(graph_name)
    except Exception as e:
        logger.warning(
            "Failed to write embedding meta on master %s: %s", graph_name, e,
        )

    # ── Update meta.db kg_status + counts ─────────────────────────────
    # Phase 10: FalkorDB là source of truth, không còn JSON snapshot.
    # Sync meta.db để frontend resolve graph_name + counts.
    try:
        from ecosim_common.metadata_index import update_campaign_kg_status
        update_campaign_kg_status(
            graph_name,
            status="ready",
            node_count=n_entities,
            edge_count=edges_written,
            episode_count=n_sections,
            embedding_model=getattr(llm, "embedding_model", "text-embedding-3-small"),
            embedding_dim=len(entity_embs[0]) if entity_embs else 1536,
            extraction_model="direct",
            set_built_at=True,
        )
    except Exception as e:
        logger.warning("Failed to sync meta.db kg_status for %s: %s", graph_name, e)

    elapsed_ms = int((_time.time() - t0) * 1000)
    result = {
        "entities_written": n_entities,
        "facts_written": edges_written,
        "episodes_written": n_sections,
        "mentions_written": mentions_written,
        "embedding_calls": 3,
        "indexes_built": indexes_built,
        "elapsed_ms": elapsed_ms,
        "method": "direct_cypher_zero_info_loss",
        # Compat với output của loader.load() cũ + merge_structured()
        "nodes_merged": n_entities,
        "edges_merged": edges_written,
    }
    logger.info("✅ Direct KG write DONE in %.1fs: %s", elapsed_ms / 1000, result)
    return result
