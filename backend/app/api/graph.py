"""
Graph API — Build and query the Knowledge Graph.

E2E Flow:
  Build: API→OG→LLM (ontology) + API→GB→LLM→FDB (entities/edges)
  Query: API→GQ→FDB (Cypher)
"""

import json
import logging
import os

from flask import Blueprint, jsonify, request

from ..config import Config
from ..services.ontology_generator import OntologyGenerator
from ..services.graph_builder import GraphBuilder
from ..services.graph_query import GraphQuery

logger = logging.getLogger("ecosim.api.graph")

graph_bp = Blueprint("graph", __name__, url_prefix="/api/graph")


@graph_bp.route("/build", methods=["POST"])
def build_graph():
    """Build KG from a campaign's text chunks.

    Request JSON:
        campaign_id: str — previously parsed campaign
    OR:
        text: str — raw text to build from directly
        campaign_type: str — optional campaign type hint
    """
    data = request.get_json() or {}

    # Get text chunks — either from stored campaign or direct text
    chunks = []
    campaign_id = data.get("campaign_id", "")
    campaign_type = data.get("campaign_type", "")

    if "text" in data:
        # Direct text mode
        from ..utils.file_parser import FileParser
        fp = FileParser()
        chunks = fp.split_into_chunks(data["text"])
        logger.info(f"Direct text: {len(chunks)} chunks")

    elif campaign_id:
        # Load from stored campaign spec
        spec_path = os.path.join(
            Config.UPLOAD_DIR, f"{campaign_id}_spec.json"
        )
        if os.path.exists(spec_path):
            with open(spec_path, "r", encoding="utf-8") as f:
                spec_data = json.load(f)
            chunks = spec_data.get("chunks", [])
            campaign_type = campaign_type or spec_data.get("campaign_type", "")
            logger.info(f"Loaded campaign {campaign_id}: {len(chunks)} chunks")
        else:
            return jsonify({"error": f"Campaign {campaign_id} not found"}), 404
    else:
        return jsonify({
            "error": "Provide 'campaign_id' or 'text' in JSON body"
        }), 400

    if not chunks:
        return jsonify({"error": "No text chunks to process"}), 400

    try:
        # Step 1: Generate ontology
        full_text = "\n".join(chunks[:3])  # Use first 3 chunks for ontology
        og = OntologyGenerator()
        ontology = og.generate(full_text, campaign_type)

        # Step 2: Build graph
        gb = GraphBuilder()
        result = gb.build(chunks, ontology, campaign_id)

        # Include ontology info
        result["ontology"] = {
            "entity_types": [et.value for et in ontology.entity_types],
            "edge_types": [et.value for et in ontology.edge_types],
            "domain_description": ontology.domain_description,
        }

        return jsonify(result), 201

    except Exception as e:
        logger.error(f"Graph build failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@graph_bp.route("/entities", methods=["GET"])
def get_entities():
    """Get all entities from the KG.

    Query params:
        limit: int (default 100)
    """
    limit = request.args.get("limit", 100, type=int)
    gq = GraphQuery()
    entities = gq.get_all_entities(limit=limit)
    return jsonify({"entities": entities, "count": len(entities)})


@graph_bp.route("/edges", methods=["GET"])
def get_edges():
    """Get all edges from the KG."""
    limit = request.args.get("limit", 200, type=int)
    gq = GraphQuery()
    edges = gq.get_all_edges(limit=limit)
    return jsonify({"edges": edges, "count": len(edges)})


@graph_bp.route("/search", methods=["GET"])
def search():
    """Search entities by name.

    Query params:
        q: search query (required)
        type: entity type filter (optional)
        limit: int (default 20)
    """
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Provide 'q' query parameter"}), 400

    entity_type = request.args.get("type")
    limit = request.args.get("limit", 20, type=int)

    gq = GraphQuery()
    results = gq.search_entities(query, entity_type=entity_type, limit=limit)
    return jsonify({"query": query, "results": results, "count": len(results)})


@graph_bp.route("/neighbors/<entity_name>", methods=["GET"])
def get_neighbors(entity_name: str):
    """Get all connections of an entity.

    Query params:
        direction: in|out|both (default both)
    """
    direction = request.args.get("direction", "both")
    gq = GraphQuery()
    result = gq.get_neighbors(entity_name, direction=direction)
    return jsonify(result)


@graph_bp.route("/stats", methods=["GET"])
def graph_stats():
    """Get graph statistics."""
    gq = GraphQuery()
    stats = gq.get_graph_stats()
    return jsonify(stats)


@graph_bp.route("/clear", methods=["DELETE"])
def clear_graph():
    """Clear all nodes and edges from the graph. USE WITH CAUTION."""
    gb = GraphBuilder()
    result = gb.clear_graph()
    return jsonify(result)
