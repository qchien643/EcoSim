"""
KG Retriever — Dynamic context-aware knowledge retrieval from FalkorDB.

Upgraded to use Graphiti hybrid search (BM25 + Vector + RRF) when available,
with fallback to basic FalkorDB string matching.

Flow per round:
  1. Read recent posts from OASIS DB (what agents are seeing)
  2. Query Graphiti with hybrid search (or fallback to string match)
  3. Return compact context string for injection into agent prompt
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set

from ..config import Config

logger = logging.getLogger("ecosim.kg_retriever")


class KGRetriever:
    """Dynamic knowledge retrieval from FalkorDB campaign Knowledge Graph.

    Primary: Graphiti hybrid search (COMBINED_HYBRID_SEARCH_RRF)
    Fallback: Basic FalkorDB string matching (if Graphiti unavailable)
    """

    def __init__(self):
        self._graphiti_client = None
        self._graphiti_available = None  # None = not checked yet

        # Fallback: raw FalkorDB connection
        self._graph = None
        self._entity_cache: Dict[str, Dict] = {}
        self._entity_names: List[str] = []

    # ──────────────────────────────────────────────
    # Graphiti Hybrid Search (Primary)
    # ──────────────────────────────────────────────

    async def _get_graphiti_client(self):
        """Try to get Graphiti client (lazy, one-time check)."""
        if self._graphiti_available is False:
            return None
        if self._graphiti_client is not None:
            return self._graphiti_client

        try:
            from .graphiti_service import get_graphiti_client
            self._graphiti_client = await get_graphiti_client()
            self._graphiti_available = self._graphiti_client is not None
            if self._graphiti_available:
                logger.info("KGRetriever: Graphiti hybrid search enabled")
            return self._graphiti_client
        except Exception as e:
            logger.debug(f"Graphiti not available: {e}")
            self._graphiti_available = False
            return None

    async def retrieve_for_context(self, context_text: str, limit: int = 5) -> str:
        """Retrieve KG context using hybrid search.

        Tries Graphiti first (BM25 + Vector + RRF), falls back to string matching.

        Args:
            context_text: Text the agent is currently seeing
            limit: Max entities to return

        Returns:
            Formatted string of relevant KG knowledge, or "" if nothing found.
        """
        if not context_text:
            return ""

        # Try Graphiti hybrid search first
        client = await self._get_graphiti_client()
        if client:
            try:
                return await self._graphiti_search(client, context_text, limit)
            except Exception as e:
                logger.debug(f"Graphiti search failed, falling back: {e}")

        # Fallback: basic string matching
        return self._basic_search(context_text, limit)

    async def _graphiti_search(self, client, query: str, limit: int = 5) -> str:
        """Hybrid search using Graphiti COMBINED_HYBRID_SEARCH_RRF."""
        from graphiti_core.search.search_config_recipes import (
            COMBINED_HYBRID_SEARCH_RRF,
        )

        config = COMBINED_HYBRID_SEARCH_RRF.model_copy(deep=True)
        config.limit = limit

        results = await client._search(query=query, config=config)

        lines = ["[KG] Thông tin liên quan:"]

        # Nodes (entities)
        if results.nodes:
            for node in results.nodes:
                name = getattr(node, "name", "")
                summary = getattr(node, "summary", "")
                if name:
                    line = f"• {name}"
                    if summary:
                        line += f": {summary[:150]}"
                    lines.append(line)

        # Edges (facts/relationships)
        if results.edges:
            for edge in results.edges:
                fact = getattr(edge, "fact", "")
                if fact:
                    lines.append(f"  ↳ {fact[:150]}")

        return "\n".join(lines) if len(lines) > 1 else ""

    # ──────────────────────────────────────────────
    # Basic FalkorDB Search (Fallback)
    # ──────────────────────────────────────────────

    def _get_graph(self):
        """Lazy connection to FalkorDB campaign graph (fallback)."""
        if self._graph is None:
            from falkordb import FalkorDB
            client = FalkorDB(
                host=Config.FALKORDB_HOST,
                port=Config.FALKORDB_PORT,
            )
            self._graph = client.select_graph("ecosim")
            self._load_entity_index()
        return self._graph

    def _load_entity_index(self):
        """Pre-load all entity names for fast keyword matching."""
        graph = self._graph
        try:
            result = graph.query(
                "MATCH (n) RETURN n.name AS name, n.entity_type AS type, "
                "n.description AS desc"
            )
            for record in result.result_set:
                name = record[0]
                if name:
                    self._entity_names.append(name)
                    self._entity_cache[name.lower()] = {
                        "name": name,
                        "type": record[1] or "Unknown",
                        "description": record[2] or "",
                    }
            logger.info(f"KG entity index loaded: {len(self._entity_names)} entities")
        except Exception as e:
            logger.warning(f"Failed to load entity index: {e}")

    def _basic_search(self, context_text: str, limit: int = 5) -> str:
        """Fallback: basic string matching search."""
        self._get_graph()

        if not self._entity_names:
            return ""

        context_lower = context_text.lower()
        matched_entities = []

        for name in self._entity_names:
            if name.lower() in context_lower:
                entity = self._entity_cache.get(name.lower())
                if entity:
                    matched_entities.append(entity)

        if not matched_entities:
            keywords = self._extract_keywords(context_text)
            matched_entities = self._search_by_keywords(keywords, limit=limit)

        if not matched_entities:
            return ""

        enriched = []
        for ent in matched_entities[:limit]:
            neighbors = self._get_entity_neighbors(ent["name"])
            enriched.append({**ent, "neighbors": neighbors})

        return self._format_context(enriched)

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text for KG search."""
        stop_words = {
            "và", "là", "của", "cho", "với", "từ", "đến", "trong",
            "này", "đó", "có", "không", "được", "một", "các", "những",
            "the", "and", "for", "with", "that", "this", "are", "was",
        }
        words = re.findall(r'\b\w+\b', text.lower())
        keywords = [w for w in words if len(w) > 2 and w not in stop_words]
        cap_words = re.findall(r'\b[A-ZĐẮÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĨŨƠƯ][a-zđắàáâãèéêìíòóôõùúýăĩũơư]+\b', text)
        return cap_words + keywords[:10]

    def _search_by_keywords(self, keywords: List[str], limit: int = 5) -> List[Dict]:
        """Search KG entities by keyword substring match."""
        matched = []
        seen = set()
        for kw in keywords:
            kw_lower = kw.lower()
            for name_lower, entity in self._entity_cache.items():
                if kw_lower in name_lower and name_lower not in seen:
                    matched.append(entity)
                    seen.add(name_lower)
                    if len(matched) >= limit:
                        return matched
        return matched

    def _get_entity_neighbors(self, entity_name: str) -> List[str]:
        """Get 1-hop neighbors of an entity from KG."""
        graph = self._get_graph()
        neighbors = []
        try:
            result = graph.query(
                "MATCH (a {name: $name})-[r]->(b) "
                "RETURN type(r) AS rel, b.name AS target "
                "LIMIT 5",
                params={"name": entity_name},
            )
            for record in result.result_set:
                neighbors.append(f"{record[0]} → {record[1]}")

            result2 = graph.query(
                "MATCH (a)-[r]->(b {name: $name}) "
                "RETURN a.name AS source, type(r) AS rel "
                "LIMIT 3",
                params={"name": entity_name},
            )
            for record in result2.result_set:
                neighbors.append(f"{record[0]} {record[1]} →")
        except Exception:
            pass
        return neighbors

    def _format_context(self, enriched_entities: List[Dict]) -> str:
        """Format retrieved entities into a compact context string."""
        lines = ["[KG] Thông tin liên quan:"]
        for ent in enriched_entities:
            desc = ent.get("description", "")
            line = f"• {ent['name']} ({ent.get('type', '?')})"
            if desc:
                line += f": {desc[:80]}"
            lines.append(line)
            for nb in ent.get("neighbors", [])[:3]:
                lines.append(f"  ↳ {nb}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────
    # Agent-specific retrieval
    # ──────────────────────────────────────────────

    async def retrieve_for_agent(
        self, agent_role: str, feed_text: str, limit: int = 5
    ) -> str:
        """Retrieve KG context tailored for a specific agent role."""
        context_result = await self.retrieve_for_context(feed_text, limit=limit)
        if context_result:
            return context_result

        # Fallback: role-based retrieval
        return self._fallback_role_retrieval(agent_role, limit=limit)

    def _fallback_role_retrieval(self, role: str, limit: int = 5) -> str:
        """Fallback: retrieve entities relevant to agent role."""
        role_keywords = {
            "consumer": ["product", "company", "brand", "promotion"],
            "seller": ["competitor", "market", "platform"],
            "media": ["company", "campaign", "market"],
            "regulator": ["government", "policy", "company"],
        }
        keywords = role_keywords.get(role.lower(), ["company", "product"])
        entities = self._search_by_keywords(keywords, limit=limit)
        if entities:
            return self._format_context(entities)
        return ""
