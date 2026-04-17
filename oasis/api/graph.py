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
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("sim-svc.graph")

router = APIRouter(prefix="/api/graph", tags=["Knowledge Graph"])

# ── Config ──
# __file__ = oasis/api/graph.py → dirname x3 = EcoSim/
ECOSIM_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    group_id: str = "default"

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
            from graphiti_core import Graphiti
            from graphiti_core.driver.falkordb_driver import FalkorDriver
            from graphiti_core.search.search_config_recipes import SearchMethod
            
            driver = FalkorDriver(host=FALKOR_HOST, port=FALKOR_PORT, database=db_name)
            graphiti = Graphiti(graph_driver=driver)
            try:
                group_ids = [group_id] if group_id else None
                results = await graphiti.search(
                    query=q, num_results=num_results, group_ids=group_ids,
                    search_method=SearchMethod.COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
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
    """List entities from the knowledge graph."""
    from falkordb import FalkorDB
    
    fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
    graphs = fdb.list_graphs()
    
    if group_id not in graphs:
        raise HTTPException(404, f"Graph '{group_id}' not found. Available: {graphs}")
    
    g = fdb.select_graph(group_id)
    r = g.query(f"MATCH (n:Entity) RETURN n.name, n.summary LIMIT {limit}")
    
    entities = [
        {"name": row[0], "summary": str(row[1] or "")[:200]}
        for row in r.result_set
    ]
    
    return {"group_id": group_id, "entities": entities, "count": len(entities)}


# ── GET /api/graph/edges ──
@router.get("/edges")
async def get_edges(
    group_id: str = Query("default", description="Graph group ID"),
    limit: int = Query(500, description="Max edges to return"),
):
    """List edges (relationships) from the knowledge graph."""
    from falkordb import FalkorDB
    
    fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
    graphs = fdb.list_graphs()
    
    if group_id not in graphs:
        raise HTTPException(404, f"Graph '{group_id}' not found. Available: {graphs}")
    
    g = fdb.select_graph(group_id)
    r = g.query(f"MATCH (a)-[r]->(b) RETURN a.name, type(r), b.name LIMIT {limit}")
    
    edges = [
        {"source": row[0], "relation": str(row[1] or ""), "target": row[2]}
        for row in r.result_set
        if row[0] and row[2]
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


# ── POST /api/graph/build ──
@router.post("/build")
async def build_graph(req: BuildRequest):
    """Build KG from campaign text chunks (uses Graphiti add_episode)."""
    from campaign_knowledge import CampaignDocumentParser, CampaignSectionAnalyzer
    from graphiti_core import Graphiti
    from graphiti_core.driver.falkordb_driver import FalkorDriver
    from graphiti_core.nodes import EpisodeType
    
    text = req.text
    if not text and req.campaign_id:
        spec_path = os.path.join(UPLOAD_DIR, f"{req.campaign_id}_spec.json")
        if os.path.exists(spec_path):
            with open(spec_path, "r", encoding="utf-8") as f:
                spec = json.load(f)
            text = "\n".join(spec.get("chunks", []))
    
    if not text:
        raise HTTPException(400, "Provide 'text' or 'campaign_id'")
    
    # Use campaign knowledge parser for section-based splitting
    parser = CampaignDocumentParser()
    sections = parser._parse_plaintext(text)
    
    # Connect to FalkorDB
    driver = FalkorDriver(host=FALKOR_HOST, port=FALKOR_PORT, database=req.group_id)
    graphiti = Graphiti(graph_driver=driver)
    await graphiti.build_indices_and_constraints()
    
    episodes_loaded = 0
    try:
        for i, section in enumerate(sections):
            await graphiti.add_episode(
                name=f"build_section_{i}_{section.title[:30]}",
                episode_body=section.content,
                source=EpisodeType.text,
                reference_time=datetime.now(timezone.utc),
                source_description=f"KG Build: {req.campaign_type or 'campaign'}",
                group_id=req.group_id,
            )
            episodes_loaded += 1
    finally:
        await graphiti.close()
    
    return {
        "status": "built",
        "group_id": req.group_id,
        "sections": len(sections),
        "episodes_loaded": episodes_loaded,
    }


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
