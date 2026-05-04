"""
Graph API — Knowledge Graph operations for Simulation Service.

Endpoints:
  POST /api/graph/ingest   — Ingest campaign document → FalkorDB  
  GET  /api/graph/search   — Semantic search on unified graph
  GET  /api/graph/stats    — Graph statistics (nodes, edges)
  GET  /api/graph/entities — List entities from graph
  POST /api/graph/build    — Build KG from text chunks
  DELETE /api/graph/clear  — Clear graph
"""
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("sim-svc.graph")

router = APIRouter(prefix="/api/graph", tags=["Knowledge Graph"])

# ── Config ──
# __file__ = apps/simulation/api/graph.py → dirname x4 = EcoSim/
ECOSIM_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
UPLOAD_DIR = os.path.join(ECOSIM_ROOT, os.getenv("UPLOAD_DIR", "uploads"))
FALKOR_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKOR_PORT = int(os.getenv("FALKORDB_PORT", "6379"))


# ── Request Models ──
class IngestRequest(BaseModel):
    doc_path: str
    group_id: str = ""
    source_description: str = ""

class BuildRequest(BaseModel):
    campaign_id: str = ""
    text: str = ""
    campaign_type: str = ""
    # Default empty (không phải "default") để fallback chain
    # `req.group_id or req.campaign_id` chọn được campaign_id khi caller
    # không pass group_id. Master+fork architecture: graph name = campaign_id.
    group_id: str = ""

class SearchRequest(BaseModel):
    q: str
    group_id: str = ""
    num_results: int = 10


# ── POST /api/graph/ingest ──
@router.post("/ingest")
async def ingest_campaign_doc(req: IngestRequest):
    """Ingest a campaign document into FalkorDB knowledge graph.
    
    Uses the 3-stage pipeline: Parse → LLM Analyze → Load episodes.
    """
    from campaign_knowledge import CampaignKnowledgePipeline
    from pathlib import Path
    
    doc_path = req.doc_path
    if not os.path.isabs(doc_path):
        doc_path = os.path.join(UPLOAD_DIR, doc_path)
    
    if not os.path.exists(doc_path):
        raise HTTPException(404, f"Document not found: {doc_path}")
    
    group_id = req.group_id or Path(doc_path).stem.lower().replace(" ", "_").replace("-", "_")
    
    pipeline = CampaignKnowledgePipeline(
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini"),
        falkor_host=FALKOR_HOST,
        falkor_port=FALKOR_PORT,
        group_id=group_id,
    )
    
    result = await pipeline.run(
        document_path=doc_path,
        source_description=req.source_description or f"Campaign: {Path(doc_path).name}",
    )
    
    return {
        "status": "ingested",
        "document": doc_path,
        **result,
    }


# ── GET /api/graph/search ──
@router.get("/search")
async def search_graph(
    q: str = Query(..., description="Search query"),
    group_id: str = Query("", description="Graph group ID"),
    num_results: int = Query(10, description="Number of results"),
    mode: str = Query("cypher", description="Search mode: 'cypher' (fast) or 'semantic' (LLM-powered)"),
):
    """Search the knowledge graph.
    
    Modes:
    - cypher: Direct FalkorDB text search (fast, no external API needed)
    - semantic: Graphiti hybrid search with cross-encoder (requires OpenAI)
    """
    if not q:
        raise HTTPException(400, "Query parameter 'q' is required")
    
    db_name = group_id or "default"
    
    # ── Mode: semantic (graphiti, may fail) ──
    if mode == "semantic":
        try:
            from ecosim_common.graphiti_factory import make_graphiti, make_falkor_driver

            driver = make_falkor_driver(host=FALKOR_HOST, port=FALKOR_PORT, database=db_name)
            graphiti = make_graphiti(driver)
            try:
                group_ids = [group_id] if group_id else None
                # graphiti_core removed the unified `SearchMethod` enum;
                # `search()` defaults already use combined hybrid + cross-encoder.
                results = await graphiti.search(
                    query=q, num_results=num_results, group_ids=group_ids,
                )
                return {
                    "query": q, "group_id": db_name, "mode": "semantic",
                    "count": len(results),
                    "results": [
                        {
                            "type": "edge",
                            "name": getattr(r, "name", ""),
                            "fact": getattr(r, "fact", ""),
                            "source_description": getattr(r, "source_description", ""),
                        }
                        for r in results
                    ],
                }
            finally:
                await graphiti.close()
        except Exception as e:
            logger.warning(f"Semantic search failed, falling back to cypher: {e}")
            # Fall through to cypher search
    
    # ── Mode: cypher (primary, always works) ──
    from falkordb import FalkorDB
    
    fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
    graphs = fdb.list_graphs()
    
    if db_name not in graphs:
        raise HTTPException(404, f"Graph '{db_name}' not found. Available: {graphs}")
    
    g = fdb.select_graph(db_name)
    q_lower = q.lower()
    results = []
    
    # Search entities by name and summary
    try:
        entity_query = (
            "MATCH (n) "
            "WHERE toLower(toString(n.name)) CONTAINS $q "
            "   OR toLower(toString(n.summary)) CONTAINS $q "
            "RETURN n.name, n.summary, labels(n) "
            f"LIMIT {num_results}"
        )
        r = g.query(entity_query, {"q": q_lower})
        for row in r.result_set:
            name = row[0] or ""
            summary = str(row[1] or "")
            labels = row[2] if len(row) > 2 else []
            # Highlight which field matched
            matched_in = "name" if q_lower in (name or "").lower() else "summary"
            results.append({
                "type": "entity",
                "name": name,
                "fact": summary[:300],
                "source_description": f"Entity ({', '.join(labels) if labels else 'Node'}) — matched in {matched_in}",
            })
    except Exception as e:
        logger.warning(f"Entity search failed: {e}")
    
    # Search edges/relationships by fact
    remaining = max(0, num_results - len(results))
    if remaining > 0:
        try:
            edge_query = (
                "MATCH (a)-[r]->(b) "
                "WHERE toLower(toString(r.fact)) CONTAINS $q "
                "   OR toLower(toString(r.name)) CONTAINS $q "
                "RETURN a.name, r.name, r.fact, b.name, type(r) "
                f"LIMIT {remaining}"
            )
            r = g.query(edge_query, {"q": q_lower})
            for row in r.result_set:
                src = row[0] or "?"
                rel_name = row[1] or ""
                fact = str(row[2] or "")
                target = row[3] or "?"
                rel_type = row[4] or ""
                results.append({
                    "type": "edge",
                    "name": rel_name or f"{src} → {target}",
                    "fact": fact[:300] or f"{src} —[{rel_type}]→ {target}",
                    "source_description": f"Relationship: {src} → {target}",
                })
        except Exception as e:
            logger.warning(f"Edge search failed: {e}")
    
    return {
        "query": q,
        "group_id": db_name,
        "mode": "cypher",
        "count": len(results),
        "results": results,
    }


# ── GET /api/graph/entities ──
@router.get("/entities")
async def get_entities(
    group_id: str = Query("default", description="Graph group ID"),
    limit: int = Query(100, description="Max entities to return"),
):
    """List entities from the knowledge graph.

    Trả empty list khi graph chưa tồn tại (vd đang build, FalkorDB chưa có
    graph) — frontend poll endpoint này ~2s khi isBuilding=true để show
    real-time growing graph; không nên throw 404 vì sẽ làm vỡ poll loop.
    """
    from falkordb import FalkorDB

    fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
    graphs = fdb.list_graphs()

    if group_id not in graphs:
        return {"group_id": group_id, "entities": [], "count": 0}

    g = fdb.select_graph(group_id)
    # Phase 13: KG chỉ chứa SimAgent + Entity (master clone + Zep extract).
    # Filter `:Episodic` + `:Meta`.
    r = g.query(
        "MATCH (n) "
        "WHERE NOT n:Episodic AND NOT n:Meta AND n.name IS NOT NULL "
        "RETURN n.name, "
        "  COALESCE(n.summary, n.description, ''), "
        "  labels(n) "
        f"LIMIT {limit}"
    )

    entities = []
    for row in r.result_set:
        name, desc, labels = row[0], row[1], row[2]
        non_entity = [lab for lab in (labels or []) if lab != "Entity"]
        etype = non_entity[0] if non_entity else "Entity"
        entities.append({
            "name": name,
            "type": etype,
            "summary": str(desc or "")[:200],
        })

    return {"group_id": group_id, "entities": entities, "count": len(entities)}


# ── GET /api/graph/edges ──
@router.get("/edges")
async def get_edges(
    group_id: str = Query("default", description="Graph group ID"),
    limit: int = Query(500, description="Max edges to return"),
):
    """List edges (relationships) from the knowledge graph.

    Trả empty list khi graph chưa tồn tại (real-time poll-while-building).
    """
    from falkordb import FalkorDB

    fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
    graphs = fdb.list_graphs()

    if group_id not in graphs:
        return {"group_id": group_id, "edges": [], "count": 0}

    g = fdb.select_graph(group_id)
    # Phase 13: tất cả node có .name (SimAgent + Entity), không cần synthesize.
    # Phase 16.fix: exclude :Episodic + :Meta — Episodic chỉ phục vụ Graphiti
    # hybrid search internal, không có giá trị user-facing trong graph viz.
    r = g.query(
        "MATCH (a)-[r]->(b) "
        "WHERE a.name IS NOT NULL AND b.name IS NOT NULL "
        "  AND NOT a:Episodic AND NOT b:Episodic "
        "  AND NOT a:Meta AND NOT b:Meta "
        "RETURN a.name, type(r), b.name, COALESCE(r.fact, '') "
        f"LIMIT {limit}"
    )

    edges = [
        {"source": row[0], "relation": str(row[1] or ""), "target": row[2], "fact": row[3]}
        for row in r.result_set
    ]

    return {"group_id": group_id, "edges": edges, "count": len(edges)}


# ── GET /api/graph/stats ──
@router.get("/stats")
async def graph_stats(
    group_id: str = Query("default", description="Graph group ID"),
):
    """Get graph statistics."""
    from falkordb import FalkorDB
    
    fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
    graphs = fdb.list_graphs()
    
    if group_id not in graphs:
        return {"group_id": group_id, "exists": False, "all_graphs": graphs}
    
    g = fdb.select_graph(group_id)
    
    r_nodes = g.query("MATCH (n) RETURN count(n)")
    r_edges = g.query("MATCH ()-[r]->() RETURN count(r)")
    r_labels = g.query("MATCH (n) RETURN labels(n), count(n)")
    r_types = g.query("MATCH ()-[r]->() RETURN DISTINCT type(r), count(r)")
    
    return {
        "group_id": group_id,
        "exists": True,
        "nodes": r_nodes.result_set[0][0],
        "edges": r_edges.result_set[0][0],
        "node_labels": {str(r[0]): r[1] for r in r_labels.result_set},
        "edge_types": {str(r[0]): r[1] for r in r_types.result_set},
        "all_graphs": graphs,
    }


# ── GET /api/graph/list ──
@router.get("/list")
async def list_graphs():
    """List all FalkorDB graphs."""
    from falkordb import FalkorDB
    
    fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
    graphs = fdb.list_graphs()
    
    result = []
    for gname in graphs:
        try:
            g = fdb.select_graph(gname)
            r = g.query("MATCH (n) RETURN count(n)")
            nodes = r.result_set[0][0]
            r = g.query("MATCH ()-[r]->() RETURN count(r)")
            edges = r.result_set[0][0]
            result.append({"name": gname, "nodes": nodes, "edges": edges})
        except Exception:
            result.append({"name": gname, "nodes": 0, "edges": 0})
    
    return {"graphs": result, "count": len(result)}


# ── Phase 10: Resolver — frontend gửi context, backend resolve graph_name ──
def _resolve_graph_name(
    campaign_id: Optional[str],
    sim_id: Optional[str],
) -> tuple[str, str]:
    """Returns (graph_name, kind). Raise HTTPException nếu không sẵn sàng.

    Priority: sim_id > campaign_id (sim chiếm ưu tiên nếu cả 2 có).
    """
    from ecosim_common.metadata_index import get_campaign_graph, get_sim_graph
    if sim_id:
        sim = get_sim_graph(sim_id)
        if not sim:
            raise HTTPException(404, f"sim {sim_id} không tồn tại")
        if sim["kg_status"] not in ("ready", "mutating", "completed"):
            raise HTTPException(
                422, f"sim {sim_id} kg chưa sẵn sàng (status={sim['kg_status']})"
            )
        return (sim["kg_graph_name"], "simulation")
    if campaign_id:
        camp = get_campaign_graph(campaign_id)
        if not camp:
            raise HTTPException(404, f"campaign {campaign_id} không tồn tại")
        if camp["kg_status"] != "ready":
            raise HTTPException(
                422,
                f"campaign {campaign_id} kg chưa sẵn sàng (status={camp['kg_status']})",
            )
        return (camp["kg_graph_name"], "campaign")
    raise HTTPException(400, "cần campaign_id hoặc sim_id")


# ── GET /api/graph/cache-status ──
@router.get("/cache-status")
async def get_cache_status(
    campaign_id: Optional[str] = Query(default=None),
    sim_id: Optional[str] = Query(default=None),
):
    """Phase 10: trả status từ meta.db (không hit FalkorDB).

    Returns:
        {kind, owner_id, kg_graph_name, kg_status, node_count, edge_count,
         episode_count, built_at|forked_at, last_modified_at}
    """
    from ecosim_common.metadata_index import get_campaign_graph, get_sim_graph
    if sim_id:
        sim = get_sim_graph(sim_id)
        if not sim:
            raise HTTPException(404, f"sim {sim_id} không tồn tại")
        return {
            "kind": "simulation",
            "owner_id": sim["sid"],
            "campaign_id": sim["cid"],
            "kg_graph_name": sim["kg_graph_name"],
            "kg_status": sim["kg_status"],
            "node_count": sim["kg_node_count"] or 0,
            "edge_count": sim["kg_edge_count"] or 0,
            "episode_count": sim["kg_episode_count"] or 0,
            "forked_at": sim["kg_forked_at"],
            "last_modified_at": sim["kg_last_modified_at"],
        }
    if campaign_id:
        camp = get_campaign_graph(campaign_id)
        if not camp:
            raise HTTPException(404, f"campaign {campaign_id} không tồn tại")
        return {
            "kind": "campaign",
            "owner_id": camp["cid"],
            "kg_graph_name": camp["kg_graph_name"],
            "kg_status": camp["kg_status"],
            "node_count": camp["kg_node_count"] or 0,
            "edge_count": camp["kg_edge_count"] or 0,
            "episode_count": camp["kg_episode_count"] or 0,
            "built_at": camp["kg_built_at"],
            "last_modified_at": camp["kg_last_modified_at"],
            "embedding_model": camp["kg_embedding_model"],
            "embedding_dim": camp["kg_embedding_dim"],
        }
    raise HTTPException(400, "cần campaign_id hoặc sim_id")


# ── POST /api/graph/build ──
@router.post("/build")
async def build_graph(req: BuildRequest):
    """Build KG từ campaign text — full pipeline.

    Flow (Option A — manual primary + Graphiti auxiliary):
      1. Parse text → sections (Markdown / plaintext, size-guarded)
      2. LLM analyze từng section với prompt Vietnamese business domain
      3. Post-process: dedup, fragment filter, sub-service → parent
      4. MERGE structured nodes/edges vào FalkorDB với canonical labels (:Company, ...)
      5. Graphiti add_episode song song để có hybrid search (BM25 + Vector + RRF)
    """
    from campaign_knowledge import CampaignKnowledgePipeline

    from ecosim_common.config import EcoSimConfig
    from ecosim_common.atomic_io import atomic_write_json

    from ecosim_common.path_resolver import compute_campaign_paths
    from ecosim_common.metadata_index import update_campaign_kg_status
    from pathlib import Path as _Path

    text = req.text
    doc_name = req.campaign_id or "campaign_text"
    extracted_dir = None
    source_filename = ""
    paths = None
    if req.campaign_id:
        paths = compute_campaign_paths(req.campaign_id)
        if not text:
            spec_path = _Path(paths["spec_path"])
            if not spec_path.exists():
                raise HTTPException(
                    404,
                    f"Campaign {req.campaign_id} chưa upload (spec.json không tồn tại tại {spec_path})",
                )
            with open(spec_path, "r", encoding="utf-8") as f:
                spec = json.load(f)
            text = spec.get("raw_text") or "\n\n".join(spec.get("chunks", []))
            doc_name = spec.get("name", doc_name)
        # Lookup file gốc để build_meta record
        source_dir = _Path(paths["source_dir"])
        if source_dir.exists():
            source_files = list(source_dir.iterdir())
            if source_files:
                source_filename = source_files[0].name
        extracted_dir = _Path(paths["extracted_dir"])

    if not text:
        raise HTTPException(400, "Provide 'text' or 'campaign_id' (with uploaded spec)")

    # Group isolation invariant: mỗi campaign 1 FalkorDB graph riêng.
    group_id = req.group_id or req.campaign_id or "default"
    if group_id == "default":
        logger.warning(
            "build_graph called without group_id or campaign_id — falling back "
            "to 'default' graph. This breaks campaign isolation!"
        )

    # Phase 10: mark kg_status='building' trước khi pipeline chạy
    if req.campaign_id:
        try:
            update_campaign_kg_status(req.campaign_id, status="building")
        except Exception as e:
            logger.debug("update kg_status='building' skip: %s", e)

    pipeline = CampaignKnowledgePipeline(
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini"),
        falkor_host=FALKOR_HOST,
        falkor_port=FALKOR_PORT,
        group_id=group_id,
        extracted_dir=extracted_dir,  # cache sections.json + analyzed.json
    )

    try:
        result = await pipeline.run_from_text(
            text=text,
            doc_name=doc_name,
            source_description=f"KG Build: {req.campaign_type or 'campaign'}",
        )
    except Exception as e:
        # Mark build progress = failed để frontend hiển thị error message
        try:
            from build_progress import failed as _bp_failed
            _bp_failed(group_id, str(e))
        except Exception:
            pass
        if req.campaign_id:
            try:
                update_campaign_kg_status(req.campaign_id, status="error")
            except Exception:
                pass
        raise

    # Write kg/build_meta.json — provenance only (graph data ở FalkorDB)
    if req.campaign_id and paths:
        try:
            from datetime import datetime as _dt
            kg_dir = _Path(paths["kg_dir"])
            kg_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(_Path(paths["build_meta_path"]), {
                "campaign_id": req.campaign_id,
                "group_id": group_id,
                "built_at": _dt.now().isoformat(timespec="seconds"),
                "extraction_model": EcoSimConfig.llm_extraction_model_name(),
                "embedding_model": EcoSimConfig.llm_embedding_model(),
                "source_filename": source_filename,
                "nodes_merged": result.get("nodes_merged", 0),
                "edges_merged": result.get("edges_merged", 0),
                "episodes_written": result.get("episodes_written", 0),
                "sections_parsed": result.get("sections_parsed", 0),
                "entities_canonical": result.get("entities_canonical", 0),
                "facts_canonical": result.get("facts_canonical", 0),
            })
        except Exception as e:
            logger.warning("Failed to write build_meta.json: %s", e)

    # Note: kg_status='ready' + counts đã được kg_direct_writer / zep_kg_writer
    # update vào meta.db ở cuối pipeline.run_from_text(). Không cần update lại.

    return {
        "status": "built",
        **result,
    }


# ── GET /api/graph/build-progress ──
@router.get("/build-progress")
async def get_build_progress(
    campaign_id: str = Query("", description="Campaign ID (= group_id master)"),
):
    """Đọc progress của build đang chạy / vừa kết thúc.

    Frontend poll endpoint này 1.5s khi isBuilding=true để hiển thị stage
    message granular (vd "Stage 2: analyze 5/17 sections") thay vì chỉ
    "Building..." chung chung.

    Trả `{stage, percent, message, status, started_at, updated_at, error}`.
    Status: "running" | "done" | "failed" | "idle" (chưa bao giờ build).
    """
    if not campaign_id:
        raise HTTPException(400, "campaign_id required")
    from build_progress import read as _bp_read
    progress = _bp_read(campaign_id)
    if progress is None:
        return {
            "stage": "",
            "percent": 0,
            "message": "",
            "status": "idle",
            "campaign_id": campaign_id,
        }
    return {**progress, "campaign_id": campaign_id}


# ── DELETE /api/graph/clear ──
@router.delete("/clear")
async def clear_graph(
    group_id: str = Query("default", description="Primary graph to clear"),
    clear_all: bool = Query(True, description="Clear ALL FalkorDB graphs (recommended)"),
):
    """Clear FalkorDB graphs to remove stale data.
    
    By default clears ALL graphs to prevent agent episodes from previous
    simulations persisting (they may be in different databases than the
    campaign graph due to Graphiti's internal naming).
    """
    from falkordb import FalkorDB
    
    fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
    all_graphs = fdb.list_graphs()
    cleared = []
    failed = []
    
    graphs_to_clear = all_graphs if clear_all else [group_id]
    
    for gname in graphs_to_clear:
        if gname not in all_graphs:
            continue
        try:
            g = fdb.select_graph(gname)
            g.delete()
            cleared.append(gname)
            logger.info(f"Dropped graph: {gname}")
        except Exception as e:
            # Fallback: try node-level delete
            try:
                g = fdb.select_graph(gname)
                g.query("MATCH (n) DETACH DELETE n")
                cleared.append(f"{gname}(partial)")
            except Exception as e2:
                failed.append(gname)
                logger.warning(f"Failed to clear graph {gname}: {e2}")
    
    return {
        "status": "cleared",
        "cleared_graphs": cleared,
        "failed": failed,
        "mode": "all" if clear_all else "single",
    }


# ── DELETE /api/campaign/{campaign_id} ──
# Đặt ở Sim service (không phải Core) vì cần FalkorDB access cho cascade.
# Caddy gateway có matcher route DELETE /api/campaign/* sang upstream_sim.
# Phải prefix /api/campaign vì FastAPI router prefix là /api/graph.
from fastapi import APIRouter as _APIRouter
campaign_router = _APIRouter(prefix="/api/campaign", tags=["Campaign Lifecycle"])


@campaign_router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str):
    """Cascade delete campaign:
      1. List sims thuộc campaign (query meta.db)
      2. Drop FalkorDB graphs (master `<cid>` + tất cả `sim_<sid>`)
      3. rm -rf per-campaign folder (cascade xóa source/, extracted/, kg/, sims/)
      4. Cascade meta.db row (FK ON DELETE CASCADE → sims + agents + events + sentiment)

    Idempotent. Trả 404 nếu campaign không tồn tại trong meta.db và không có folder.
    """
    import shutil
    from sim_graph_clone import drop_master_graph, drop_sim_graph
    from ecosim_common.metadata_index import (
        get_campaign, list_simulations,
        delete_campaign as db_delete_campaign,
    )
    from ecosim_common.path_resolver import resolve_campaign_paths
    from pathlib import Path as _Path

    # Check existence: meta.db row HOẶC folder.
    db_row = get_campaign(campaign_id)
    paths = resolve_campaign_paths(campaign_id)
    campaign_dir = _Path(paths["campaign_dir"]) if paths.get("campaign_dir") else None
    has_dir = bool(campaign_dir and campaign_dir.exists())
    fdb = _falkor_client()
    has_master = campaign_id in fdb.list_graphs()
    if not (db_row or has_dir or has_master):
        raise HTTPException(404, f"Campaign {campaign_id} not found")

    # 1. List sims qua meta.db
    sims = list_simulations(cid=campaign_id) if db_row else []
    sim_ids = [s["sid"] for s in sims]

    # 2a. Drop sim graphs trong FalkorDB
    sims_dropped = []
    sims_failed = []
    for sid in sim_ids:
        try:
            drop_sim_graph(sid)
            try:
                from api.simulation import _simulations
                _simulations.pop(sid, None)
            except Exception:
                pass
            sims_dropped.append(sid)
        except Exception as e:
            logger.warning("Failed to drop sim graph %s: %s", sid, e)
            sims_failed.append(sid)

    # 2b. Drop master graph
    master_dropped = False
    try:
        master_dropped = drop_master_graph(campaign_id)
    except Exception as e:
        logger.warning("drop_master_graph(%s) failed: %s", campaign_id, e)

    # 3. rm -rf per-campaign folder (nested layout xóa luôn sim folders)
    dir_removed = False
    if has_dir and campaign_dir is not None:
        shutil.rmtree(str(campaign_dir), ignore_errors=True)
        dir_removed = True

    # 4. Cascade delete meta.db row → FK CASCADE xóa sims/agents/events/sentiment
    db_deleted = False
    try:
        db_delete_campaign(campaign_id)
        db_deleted = True
    except Exception as e:
        logger.warning("meta.db delete_campaign(%s) failed: %s", campaign_id, e)

    return {
        "campaign_id": campaign_id,
        "deleted": True,
        "master_dropped": master_dropped,
        "sims_dropped": sims_dropped,
        "sims_failed": sims_failed,
        "campaign_dir_removed": dir_removed,
        "db_row_deleted": db_deleted,
    }


def _falkor_client():
    from falkordb import FalkorDB
    return FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)


# ── POST /api/graph/cleanup-orphans (admin) ──
# Quét FalkorDB list_graphs() vs meta.db campaigns + simulations.
# Drop graphs không có row tương ứng trong meta.db.
@router.post("/cleanup-orphans")
async def cleanup_orphan_graphs():
    """Drop tất cả FalkorDB graphs không có row meta.db tương ứng.

    Match rules:
      • Graph name = <cid> trong campaigns table → KEEP
      • Graph name = sim_<sid> với sid trong simulations table → KEEP
      • Else (orphan or legacy default_db / ecosim_agent_memory) → DROP

    Returns: {graphs_listed, kept, dropped: [...], errors: [...]}
    """
    from ecosim_common.metadata_index import list_campaigns, list_simulations

    fdb = _falkor_client()
    all_graphs = set(fdb.list_graphs())

    valid_cids = {c["cid"] for c in list_campaigns()}
    valid_sim_graphs = {
        (s["sid"] if s["sid"].startswith("sim_") else f"sim_{s['sid']}")
        for s in list_simulations()
    }
    valid = valid_cids | valid_sim_graphs

    dropped: list[str] = []
    errors: list[dict] = []
    kept: list[str] = []
    for g in all_graphs:
        if g in valid:
            kept.append(g)
            continue
        try:
            fdb.select_graph(g).delete()
            dropped.append(g)
            logger.info("Cleanup: dropped orphan FalkorDB graph %s", g)
        except Exception as e:
            errors.append({"graph": g, "error": str(e)})
            logger.warning("Cleanup: failed to drop %s: %s", g, e)

    return {
        "graphs_listed": len(all_graphs),
        "kept": kept,
        "dropped": dropped,
        "errors": errors,
    }
