"""
Graph Query — Search and retrieve from the Knowledge Graph.

Architecture: Graphiti hybrid search (primary) + raw FalkorDB Cypher (listing).

Graphiti provides:
  - Hybrid search: BM25 + Vector + RRF reranking
  - Semantic entity/edge search

Raw Cypher provides:
  - Entity listing (get_all_entities)
  - Graph stats
  - Neighbor traversal
"""

import logging
from typing import Any, Dict, List, Optional

from ..config import Config

logger = logging.getLogger("ecosim.graph_query")


class GraphQuery:
    """Query interface for the Knowledge Graph.

    Primary: Graphiti hybrid search for semantic queries
    Direct: Raw FalkorDB Cypher for entity listing and graph traversal
    """

    def __init__(self):
        self._graph = None
        self._graphiti_client = None
        self._graphiti_available = None

    def _get_graph(self):
        """Get raw FalkorDB graph connection."""
        if self._graph is None:
            try:
                from falkordb import FalkorDB
                client = FalkorDB(
                    host=Config.FALKORDB_HOST,
                    port=Config.FALKORDB_PORT,
                )
                self._graph = client.select_graph("ecosim")
            except Exception as e:
                logger.warning(f"FalkorDB unavailable: {e}")
                return None
        return self._graph

    # ══════════════════════════════════════════════════
    # ENTITY LISTING (Raw Cypher)
    # ══════════════════════════════════════════════════

    def get_all_entities(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get campaign entity nodes from the graph.

        Uses Graphiti's EntityNode label when available,
        falls back to raw node scan with strict filtering.
        """
        graph = self._get_graph()
        if graph is None:
            return []

        entities = []

        # Try Graphiti EntityNode first (Graphiti creates these with proper labels)
        try:
            result = graph.query(
                "MATCH (n:Entity) "
                "WHERE n.name IS NOT NULL AND n.name <> '' "
                "RETURN n.name AS name, n.summary AS description "
                "LIMIT $limit",
                params={"limit": limit},
            )
            if result.result_set:
                for record in result.result_set:
                    name = record[0]
                    desc = record[1] or ""
                    if not name or name.strip().lower() in ("unknown", ""):
                        continue
                    # Extract type from Graphiti's summary or labels
                    etype = self._infer_type_from_summary(desc)
                    entities.append({
                        "name": name.strip(),
                        "type": etype,
                        "description": desc,
                    })
                if entities:
                    logger.info(f"get_all_entities: {len(entities)} from Graphiti EntityNode")
                    return entities
        except Exception as e:
            logger.debug(f"Graphiti EntityNode query not available: {e}")

        # Fallback: raw node scan (for manually created nodes)
        try:
            result = graph.query(
                "MATCH (n) "
                "WHERE NOT n:SimAgent AND NOT n:SimPost "
                "AND NOT n:Episodic "
                "AND n.name IS NOT NULL AND n.name <> '' "
                "RETURN n.name AS name, n.entity_type AS type, "
                "n.description AS description LIMIT $limit",
                params={"limit": limit},
            )
            for record in result.result_set:
                name = record[0]
                etype = record[1]
                # Strict filter: SKIP any entity with invalid name OR type
                if not name or name.strip().lower() in ("unknown", ""):
                    logger.debug(f"Skipping entity with invalid name: {name}")
                    continue
                if not etype or etype.strip().lower() in ("unknown", ""):
                    logger.debug(f"Skipping entity '{name}' with invalid type: {etype}")
                    continue
                entities.append({
                    "name": name.strip(),
                    "type": etype.strip(),
                    "description": record[2] or "",
                })
            return entities
        except Exception as e:
            logger.error(f"get_all_entities failed: {e}")
            return []

    def _infer_type_from_summary(self, summary: str) -> str:
        """Infer entity type from Graphiti's auto-generated summary."""
        summary_lower = summary.lower() if summary else ""
        type_keywords = {
            "Company": ["company", "corporation", "platform", "marketplace", "brand", "sàn"],
            "Product": ["product", "sản phẩm", "device", "phone", "laptop"],
            "Campaign": ["campaign", "chiến dịch", "sale", "khuyến mãi", "promotion"],
            "Consumer": ["consumer", "customer", "người tiêu dùng", "khách hàng", "gen z"],
            "Market": ["market", "thị trường", "industry", "ngành"],
            "Person": ["person", "cá nhân", "influencer", "kol", "reporter"],
        }
        for etype, keywords in type_keywords.items():
            if any(kw in summary_lower for kw in keywords):
                return etype
        return "Organization"  # Safe default for Graphiti entities

    def get_all_edges(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Get all relationships from the graph."""
        graph = self._get_graph()
        if graph is None:
            return []

        edges = []

        # Try Graphiti EntityEdge first
        try:
            result = graph.query(
                "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
                "RETURN a.name AS source, r.name AS rel_type, "
                "b.name AS target, r.fact AS description "
                "LIMIT $limit",
                params={"limit": limit},
            )
            if result.result_set:
                for record in result.result_set:
                    edges.append({
                        "source": record[0] or "",
                        "rel_type": record[1] or "RELATES_TO",
                        "target": record[2] or "",
                        "description": record[3] or "",
                    })
                if edges:
                    logger.info(f"get_all_edges: {len(edges)} from Graphiti EntityEdge")
                    return edges
        except Exception as e:
            logger.debug(f"Graphiti EntityEdge query not available: {e}")

        # Fallback: raw edge scan
        try:
            result = graph.query(
                "MATCH (a)-[r]->(b) "
                "WHERE a.name IS NOT NULL AND b.name IS NOT NULL "
                "RETURN a.name AS source, type(r) AS rel_type, "
                "b.name AS target, r.description AS description "
                "LIMIT $limit",
                params={"limit": limit},
            )
            for record in result.result_set:
                edges.append({
                    "source": record[0],
                    "rel_type": record[1],
                    "target": record[2],
                    "description": record[3] or "",
                })
            return edges
        except Exception as e:
            logger.error(f"get_all_edges failed: {e}")
            return []

    # ══════════════════════════════════════════════════
    # SEARCH (Graphiti hybrid or raw Cypher fallback)
    # ══════════════════════════════════════════════════

    def search_entities(
        self,
        query: str,
        entity_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search entities — tries Graphiti hybrid search first."""
        import asyncio

        # Try Graphiti search
        try:
            loop = asyncio.new_event_loop()
            results = loop.run_until_complete(
                self._graphiti_search_entities(query, limit)
            )
            loop.close()
            if results:
                return results
        except Exception as e:
            logger.debug(f"Graphiti search failed: {e}")

        # Fallback: raw Cypher string matching
        return self._cypher_search_entities(query, entity_type, limit)

    async def _graphiti_search_entities(
        self, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Search using Graphiti hybrid search (BM25 + Vector + RRF)."""
        from .graphiti_service import get_graphiti_client
        from graphiti_core.search.search_config_recipes import NODE_HYBRID_SEARCH_RRF

        client = await get_graphiti_client()
        if not client:
            return []

        config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
        config.limit = limit

        results = await client.search_(query=query, config=config)

        entities = []
        if results and hasattr(results, 'nodes'):
            for node in results.nodes:
                entities.append({
                    "name": getattr(node, 'name', ''),
                    "type": self._infer_type_from_summary(
                        getattr(node, 'summary', '')
                    ),
                    "description": getattr(node, 'summary', ''),
                })

        logger.info(f"Graphiti hybrid search '{query}': {len(entities)} results")
        return entities

    def _cypher_search_entities(
        self,
        query: str,
        entity_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Fallback: Search entities by raw Cypher string matching."""
        graph = self._get_graph()
        if graph is None:
            return []
        try:
            if entity_type:
                cypher = (
                    f"MATCH (n:{entity_type}) "
                    "WHERE toLower(n.name) CONTAINS toLower($query) "
                    "RETURN n.name AS name, n.entity_type AS type, "
                    "n.description AS description LIMIT $limit"
                )
            else:
                cypher = (
                    "MATCH (n) "
                    "WHERE toLower(n.name) CONTAINS toLower($query) "
                    "AND n.name IS NOT NULL "
                    "RETURN n.name AS name, n.entity_type AS type, "
                    "n.description AS description LIMIT $limit"
                )

            result = graph.query(cypher, params={"query": query, "limit": limit})
            entities = []
            for record in result.result_set:
                name = record[0]
                etype = record[1]
                if not name:
                    continue
                entities.append({
                    "name": name,
                    "type": etype if etype and etype.lower() != "unknown" else "Organization",
                    "description": record[2] or "",
                })
            return entities
        except Exception as e:
            logger.error(f"search_entities failed: {e}")
            return []

    # ══════════════════════════════════════════════════
    # GRAPH TRAVERSAL (Raw Cypher)
    # ══════════════════════════════════════════════════

    def get_neighbors(
        self,
        entity_name: str,
        direction: str = "both",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Get entity and all its neighbors (incoming + outgoing edges)."""
        graph = self._get_graph()
        if graph is None:
            return {"entity": entity_name, "outgoing": [], "incoming": [], "total_connections": 0}
        try:
            outgoing = []
            incoming = []

            if direction in ("out", "both"):
                result = graph.query(
                    "MATCH (a {name: $name})-[r]->(b) "
                    "RETURN type(r) AS rel, b.name AS target, "
                    "b.entity_type AS type, r.description AS desc "
                    "LIMIT $limit",
                    params={"name": entity_name, "limit": limit},
                )
                for record in result.result_set:
                    outgoing.append({
                        "relationship": record[0],
                        "target": record[1],
                        "target_type": record[2] or "",
                        "description": record[3] or "",
                    })

            if direction in ("in", "both"):
                result = graph.query(
                    "MATCH (a)-[r]->(b {name: $name}) "
                    "RETURN a.name AS source, a.entity_type AS type, "
                    "type(r) AS rel, r.description AS desc "
                    "LIMIT $limit",
                    params={"name": entity_name, "limit": limit},
                )
                for record in result.result_set:
                    incoming.append({
                        "source": record[0],
                        "source_type": record[1] or "",
                        "relationship": record[2],
                        "description": record[3] or "",
                    })

            return {
                "entity": entity_name,
                "outgoing": outgoing,
                "incoming": incoming,
                "total_connections": len(outgoing) + len(incoming),
            }
        except Exception as e:
            logger.error(f"get_neighbors failed: {e}")
            return {"entity": entity_name, "outgoing": [], "incoming": [], "total_connections": 0}

    def get_graph_stats(self) -> Dict[str, Any]:
        """Get graph statistics: node count, edge count, type distribution."""
        graph = self._get_graph()
        if graph is None:
            return {"nodes": 0, "edges": 0, "types": {}}
        try:
            node_result = graph.query("MATCH (n) RETURN count(n) AS cnt")
            node_count = node_result.result_set[0][0] if node_result.result_set else 0

            edge_result = graph.query("MATCH ()-[r]->() RETURN count(r) AS cnt")
            edge_count = edge_result.result_set[0][0] if edge_result.result_set else 0

            type_result = graph.query(
                "MATCH (n) WHERE n.entity_type IS NOT NULL "
                "RETURN n.entity_type AS type, count(n) AS cnt "
                "ORDER BY cnt DESC"
            )
            type_dist = {}
            for record in type_result.result_set:
                label = record[0] or "Unlabeled"
                if label.lower() != "unknown":
                    type_dist[label] = record[1]

            return {
                "nodes": node_count,
                "edges": edge_count,
                "types": type_dist,
            }
        except Exception as e:
            logger.error(f"get_graph_stats failed: {e}")
            return {"nodes": 0, "edges": 0, "types": {}}

    def raw_cypher(self, cypher: str) -> List[Dict]:
        """Execute raw Cypher query (for advanced use)."""
        graph = self._get_graph()
        if graph is None:
            return [{"error": "FalkorDB unavailable"}]
        try:
            result = graph.query(cypher)
            rows = []
            for record in result.result_set:
                rows.append({f"col_{i}": val for i, val in enumerate(record)})
            return rows
        except Exception as e:
            logger.error(f"Cypher query failed: {e}")
            return [{"error": str(e)}]
