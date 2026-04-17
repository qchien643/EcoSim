"""
Graph Builder — Build Knowledge Graph from campaign text chunks.

Architecture: Graphiti-first with FalkorDB backend.

Graphiti handles:
  - LLM-based entity/relationship extraction (via add_episode)
  - Deduplication and entity resolution
  - Embedding generation for hybrid search (BM25 + Vector + RRF)
  - Temporal awareness and versioning

Raw Cypher fallback:
  - Only used when Graphiti is unavailable
  - Manual LLM extraction + MERGE into FalkorDB
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any

from ..models.ontology import (
    ChunkExtractionResult,
    EntityEdge,
    EntityNode,
    EntityType,
    EdgeType,
    OntologySpec,
)
from ..utils.llm_client import LLMClient
from ..config import Config

logger = logging.getLogger("ecosim.graph_builder")

# ── Fallback extraction prompt (only used when Graphiti unavailable) ──
EXTRACTION_SYSTEM_PROMPT = """\
You are an expert at extracting economic entities and relationships from Vietnamese \
business/campaign documents for building a knowledge graph.

Given a text chunk and valid entity/edge types, extract entities and relationships.

Valid entity types: {entity_types}
Valid edge types: {edge_types}

Return JSON:
{{
    "entities": [
        {{"name": "Entity Name", "entity_type": "Company", "description": "Brief desc"}},
        ...
    ],
    "edges": [
        {{"source": "Entity A", "target": "Entity B", "edge_type": "COMPETES_WITH", "description": "A competes with B in..."}},
        ...
    ]
}}

CRITICAL RULES:
1. Entity names MUST be proper nouns or specific brand names, NOT generic words.
2. Use the EXACT entity_type and edge_type values from the valid lists.
3. Extract implicit relationships (e.g., "đối thủ của Shopee là Lazada" → COMPETES_WITH).
4. Deduplicate: same entity mentioned multiple times = one entry.

CLASSIFICATION RULES (VERY IMPORTANT):
- Social media platforms (Facebook, Instagram, TikTok, Zalo) → type "Company" ONLY if they are \
  a main business actor. If mentioned as marketing channels, DO NOT extract them as entities.
- Product features or sub-services (e.g., "Shopee Live", "Shopee Feed", "ShopeePay") → \
  DO NOT extract as separate entities. They are features of the parent company.
- Specific products (iPhone, Galaxy, AirPods, etc.) → type "Product", NOT "Campaign".
- Product promotions/deals → type "Campaign" ONLY for named campaign events (e.g., "Black Friday Sale 2026").
- Consumer segments (Gen Z, Millennial, etc.) → type "Consumer".
- KOL, Influencer → type "Person" if specific, otherwise DO NOT extract as entities.

NAMING RULES:
- Use the most common/canonical name: "Shopee" not "Shopee Việt Nam" (unless they are truly different).
- Product brand + model: "iPhone 16 Pro Max" not "Phone 16 Pro Max".
- If text is cut mid-word or seems incomplete, DO NOT create an entity from the fragment.

Return ONLY valid JSON. If no entities found, return {{"entities": [], "edges": []}}.
"""


class GraphBuilder:
    """Build a Knowledge Graph from campaign text chunks.

    Primary: Graphiti add_episode → auto entity extraction + hybrid search
    Fallback: Manual LLM extraction + raw Cypher to FalkorDB
    """

    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or LLMClient()
        self._graph = None
        self._graphiti_available = None  # None = not checked yet

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
                logger.info("FalkorDB graph connected: ecosim")
            except Exception as e:
                logger.warning(f"FalkorDB unavailable: {e}")
                return None
        return self._graph

    # ══════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════

    def build(
        self,
        chunks: List[str],
        ontology: OntologySpec,
        campaign_id: str = "",
    ) -> Dict[str, Any]:
        """Build KG from text chunks — Graphiti-first architecture.

        1. Try Graphiti add_episode() for each chunk
           → Graphiti auto-extracts entities + relationships via LLM
           → Auto-generates embeddings for hybrid search
           → Handles dedup + entity resolution
        2. Fallback: Manual LLM extraction + raw Cypher MERGE
        """
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self._async_build(chunks, ontology, campaign_id)
            )
            return result
        finally:
            loop.close()

    async def _async_build(
        self,
        chunks: List[str],
        ontology: OntologySpec,
        campaign_id: str = "",
    ) -> Dict[str, Any]:
        """Async build — tries Graphiti first, falls back to raw Cypher."""

        # ── Try Graphiti-first approach ──
        graphiti_client = await self._get_graphiti_client()

        if graphiti_client:
            logger.info("Using Graphiti for KG building (auto entity extraction)")
            return await self._build_with_graphiti(
                graphiti_client, chunks, ontology, campaign_id
            )
        else:
            logger.info("Graphiti unavailable, falling back to manual LLM + raw Cypher")
            return self._build_with_raw_cypher(chunks, ontology, campaign_id)

    # ══════════════════════════════════════════════════
    # GRAPHITI-FIRST PATH
    # ══════════════════════════════════════════════════

    async def _get_graphiti_client(self):
        """Get Graphiti client via shared singleton."""
        if self._graphiti_available is False:
            return None

        try:
            from .graphiti_service import get_graphiti_client
            client = await get_graphiti_client()
            self._graphiti_available = client is not None
            return client
        except Exception as e:
            logger.debug(f"Graphiti not available: {e}")
            self._graphiti_available = False
            return None

    async def _build_with_graphiti(
        self,
        client,
        chunks: List[str],
        ontology: OntologySpec,
        campaign_id: str,
    ) -> Dict[str, Any]:
        """Build KG using Graphiti add_episode — auto extracts entities/relationships.

        Graphiti internally:
        1. Uses LLM to extract entities + relationships from episode text
        2. Resolves entity duplicates via embedding similarity
        3. Creates nodes + edges in FalkorDB with proper labels
        4. Generates embeddings for hybrid search (BM25 + Vector + RRF)
        """
        from graphiti_core.nodes import EpisodeType

        group_id = campaign_id or "campaign"
        episodes_created = 0
        errors = 0

        # Phase 1: Build indices if needed (first-time setup)
        try:
            await client.build_indices_and_constraints()
            logger.info("Graphiti indices and constraints ensured")
        except Exception as e:
            logger.debug(f"Index setup note (may already exist): {e}")

        # Phase 2: Ingest each chunk as an episode
        # Graphiti will auto-extract entities + relationships via LLM
        for i, chunk in enumerate(chunks):
            try:
                result = await client.add_episode(
                    name=f"Campaign: {campaign_id} — Chunk {i+1}/{len(chunks)}",
                    episode_body=chunk,
                    source_description=f"Campaign document: {campaign_id}",
                    source=EpisodeType.text,
                    reference_time=datetime.now(timezone.utc),
                    group_id=group_id,
                )
                episodes_created += 1

                # Log extracted entities from this episode
                if hasattr(result, 'nodes') and result.nodes:
                    node_names = [n.name for n in result.nodes if hasattr(n, 'name')]
                    logger.info(
                        f"Chunk {i+1}/{len(chunks)}: {len(result.nodes)} entities extracted "
                        f"({', '.join(node_names[:5])}{'...' if len(node_names) > 5 else ''})"
                    )
                else:
                    logger.info(f"Chunk {i+1}/{len(chunks)}: episode ingested")

            except Exception as e:
                errors += 1
                logger.warning(f"Chunk {i+1}/{len(chunks)} failed: {e}")

        # Phase 3: Get stats from the graph after building
        stats = self._get_graph_stats_from_falkordb()

        result = {
            "campaign_id": campaign_id,
            "method": "graphiti",
            "total_chunks": len(chunks),
            "episodes_created": episodes_created,
            "errors": errors,
            "nodes_in_graph": stats.get("nodes", 0),
            "edges_in_graph": stats.get("edges", 0),
        }

        logger.info(
            f"Graphiti KG built: {episodes_created}/{len(chunks)} episodes → "
            f"{stats.get('nodes', '?')} nodes, {stats.get('edges', '?')} edges in FalkorDB"
        )
        return result

    def _get_graph_stats_from_falkordb(self) -> Dict[str, int]:
        """Quick stats from FalkorDB."""
        graph = self._get_graph()
        if not graph:
            return {}
        try:
            node_r = graph.query("MATCH (n) RETURN count(n)")
            edge_r = graph.query("MATCH ()-[r]->() RETURN count(r)")
            return {
                "nodes": node_r.result_set[0][0] if node_r.result_set else 0,
                "edges": edge_r.result_set[0][0] if edge_r.result_set else 0,
            }
        except Exception:
            return {}

    # ══════════════════════════════════════════════════
    # RAW CYPHER FALLBACK PATH
    # ══════════════════════════════════════════════════

    def _build_with_raw_cypher(
        self,
        chunks: List[str],
        ontology: OntologySpec,
        campaign_id: str,
    ) -> Dict[str, Any]:
        """Fallback: Manual LLM extraction + raw Cypher MERGE into FalkorDB."""
        all_entities = []
        all_edges = []
        entity_set = set()

        for i, chunk in enumerate(chunks):
            logger.info(f"[Fallback] Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")

            extraction = self._extract_from_chunk(chunk, ontology, i)

            for entity in extraction.entities:
                if entity.name.lower() not in entity_set:
                    entity_set.add(entity.name.lower())
                    all_entities.append(entity)

            all_edges.extend(extraction.edges)

        # Post-processing: clean & deduplicate entities
        all_entities, all_edges = self._postprocess_entities(all_entities, all_edges)

        # Write to FalkorDB
        nodes_created = self._write_nodes(all_entities)
        edges_created = self._write_edges(all_edges)

        result = {
            "campaign_id": campaign_id,
            "method": "raw_cypher_fallback",
            "total_chunks": len(chunks),
            "entities_extracted": len(all_entities),
            "edges_extracted": len(all_edges),
            "nodes_created": nodes_created,
            "edges_created": edges_created,
        }

        logger.info(
            f"[Fallback] Graph built: {len(all_entities)} entities, {len(all_edges)} edges → "
            f"{nodes_created} nodes, {edges_created} edges in FalkorDB"
        )
        return result

    def _extract_from_chunk(
        self,
        chunk: str,
        ontology: OntologySpec,
        chunk_index: int,
    ) -> ChunkExtractionResult:
        """Extract entities + edges from a single text chunk via LLM."""
        entity_types_str = ", ".join(et.value for et in ontology.entity_types)
        edge_types_str = ", ".join(et.value for et in ontology.edge_types)

        system_prompt = EXTRACTION_SYSTEM_PROMPT.format(
            entity_types=entity_types_str,
            edge_types=edge_types_str,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Extract entities and relationships:\n\n{chunk}"},
        ]

        result = self.llm.chat_json(messages, temperature=0.1, max_tokens=1500)

        # Parse entities — strict validation at extraction time
        entities = []
        for e in result.get("entities", []):
            try:
                name = (e.get("name") or "").strip()
                etype_str = (e.get("entity_type") or "").strip()

                # Strict: reject entities with invalid name
                if not name or name.lower() == "unknown" or len(name) < 2:
                    logger.debug(f"Rejected entity with invalid name: '{name}'")
                    continue

                # Strict: reject entities with invalid type
                if not etype_str or etype_str.lower() == "unknown":
                    logger.debug(f"Rejected entity '{name}' with invalid type: '{etype_str}'")
                    continue

                entities.append(EntityNode(
                    name=name,
                    entity_type=EntityType(etype_str),
                    description=e.get("description", ""),
                ))
            except (ValueError, KeyError) as err:
                logger.warning(f"Skipping invalid entity: {e} ({err})")

        # Parse edges
        edges = []
        for e in result.get("edges", []):
            try:
                edges.append(EntityEdge(
                    source=e["source"],
                    target=e["target"],
                    edge_type=EdgeType(e.get("edge_type", "AFFECTS")),
                    description=e.get("description", ""),
                ))
            except (ValueError, KeyError) as err:
                logger.warning(f"Skipping invalid edge: {e} ({err})")

        logger.debug(
            f"Chunk {chunk_index}: {len(entities)} entities, {len(edges)} edges"
        )

        return ChunkExtractionResult(
            entities=entities,
            edges=edges,
            chunk_index=chunk_index,
        )

    def _postprocess_entities(
        self,
        entities: List[EntityNode],
        edges: List[EntityEdge],
    ) -> tuple:
        """Post-process: deduplicate, clean, and validate entities."""
        if not entities:
            return entities, edges

        # Step 1: Filter invalid entities
        valid = []
        for e in entities:
            name = e.name.strip()
            if len(name) < 2:
                logger.info(f"Filtered garbage entity: '{name}'")
                continue
            if name and name[0].islower() and " " not in name:
                logger.info(f"Filtered fragment entity: '{name}'")
                continue
            valid.append(e)

        # Step 2: Canonical name dedup
        name_map = {}
        sorted_entities = sorted(valid, key=lambda e: len(e.name))

        deduped = []
        seen_canonical = {}

        for entity in sorted_entities:
            ename = entity.name
            ename_lower = ename.lower()

            merged = False
            for canonical_lower, canonical_entity in list(seen_canonical.items()):
                if canonical_lower in ename_lower and canonical_lower != ename_lower:
                    name_map[ename] = canonical_entity.name
                    merged = True
                    logger.info(f"Merged duplicate: '{ename}' -> '{canonical_entity.name}'")
                    break
                if ename_lower in canonical_lower and canonical_lower != ename_lower:
                    name_map[canonical_entity.name] = ename
                    seen_canonical[ename_lower] = entity
                    del seen_canonical[canonical_lower]
                    deduped = [e for e in deduped if e.name != canonical_entity.name]
                    deduped.append(entity)
                    merged = True
                    logger.info(f"Replaced duplicate: '{canonical_entity.name}' -> '{ename}'")
                    break

            if not merged:
                if ename_lower not in seen_canonical:
                    seen_canonical[ename_lower] = entity
                    deduped.append(entity)

        # Step 3: Filter sub-service entities
        SUB_SERVICE_PATTERNS = ["Live", "Feed", "Pay", "Mall", "NOW"]
        parent_names = {e.name.lower() for e in deduped}
        final_entities = []
        for entity in deduped:
            is_sub_service = False
            for pattern in SUB_SERVICE_PATTERNS:
                if pattern in entity.name:
                    base = entity.name.replace(pattern, "").strip()
                    if base.lower() in parent_names:
                        name_map[entity.name] = base
                        is_sub_service = True
                        logger.info(f"Filtered sub-service: '{entity.name}' (parent: '{base}')")
                        break
            if not is_sub_service:
                final_entities.append(entity)

        # Step 4: Fix edge references
        fixed_edges = []
        final_names = {e.name.lower() for e in final_entities}
        for edge in edges:
            src = name_map.get(edge.source, edge.source)
            tgt = name_map.get(edge.target, edge.target)
            if src.lower() in final_names and tgt.lower() in final_names:
                fixed_edges.append(EntityEdge(
                    source=src,
                    target=tgt,
                    edge_type=edge.edge_type,
                    description=edge.description,
                ))

        logger.info(
            f"Post-processing: {len(entities)} -> {len(final_entities)} entities, "
            f"{len(edges)} -> {len(fixed_edges)} edges "
            f"({len(name_map)} names merged)"
        )

        return final_entities, fixed_edges

    def _write_nodes(self, entities: List[EntityNode]) -> int:
        """MERGE entity nodes into FalkorDB."""
        graph = self._get_graph()
        count = 0
        for entity in entities:
            try:
                cypher = (
                    f"MERGE (n:{entity.entity_type.value} {{name: $name}}) "
                    f"SET n.description = $desc, n.entity_type = $etype "
                    f"RETURN n"
                )
                graph.query(
                    cypher,
                    params={
                        "name": entity.name,
                        "desc": entity.description,
                        "etype": entity.entity_type.value,
                    },
                )
                count += 1
            except Exception as e:
                logger.warning(f"Failed to create node '{entity.name}': {e}")
        return count

    def _write_edges(self, edges: List[EntityEdge]) -> int:
        """CREATE edges between existing nodes in FalkorDB."""
        graph = self._get_graph()
        count = 0
        for edge in edges:
            try:
                cypher = (
                    "MATCH (a {name: $source}), (b {name: $target}) "
                    f"MERGE (a)-[r:{edge.edge_type.value}]->(b) "
                    "SET r.description = $desc "
                    "RETURN r"
                )
                graph.query(
                    cypher,
                    params={
                        "source": edge.source,
                        "target": edge.target,
                        "desc": edge.description,
                    },
                )
                count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to create edge {edge.source}->{edge.target}: {e}"
                )
        return count

    def clear_graph(self) -> Dict[str, Any]:
        """Clear all nodes and edges from the graph."""
        graph = self._get_graph()
        if graph is None:
            return {"success": False, "error": "FalkorDB unavailable"}
        try:
            result = graph.query("MATCH (n) DETACH DELETE n")
            logger.info("Graph cleared")
            return {"success": True}
        except Exception as e:
            logger.error(f"Clear graph failed: {e}")
            return {"success": False, "error": str(e)}
