"""
FalkorDB Graph Searcher — query Graphiti hybrid search trên FalkorDB graph.

Consumed by:
  • apps/simulation/agent_cognition.py GraphCognitiveHelper
    (round loop social context queries cho posts/comments/reflection)
  • Post-sim Report/Interview/Survey ReACT tools

Phase 15: tách khỏi falkor_graph_memory.py (đã xóa). FalkorGraphMemoryUpdater
runtime queue path không còn cần — Phase 15 dùng end-of-round Zep section
dispatch ở `sim_zep_section_writer.py`. FalkorGraphSearcher (read-only) vẫn
cần thiết cho cognitive helper + post-sim analysis.
"""

import logging

logger = logging.getLogger("ecosim.graph_searcher")


class FalkorGraphSearcher:
    """Query the FalkorDB knowledge graph after simulation.

    Provides hybrid search (BM25 + vector + cross-encoder reranking) qua
    Graphiti SDK. Caller chịu trách nhiệm gọi `await searcher.connect()`
    trước khi query và `await searcher.close()` khi xong.
    """

    def __init__(
        self,
        falkor_host: str = "localhost",
        falkor_port: int = 6379,
        database: str = "default_db",
    ):
        self.falkor_host = falkor_host
        self.falkor_port = falkor_port
        self.database = database
        self._graphiti = None

    async def connect(self):
        from ecosim_common.graphiti_factory import make_graphiti, make_falkor_driver
        driver = make_falkor_driver(
            host=self.falkor_host, port=self.falkor_port,
            database=self.database,
        )
        self._graphiti = make_graphiti(driver)

    async def close(self):
        if self._graphiti:
            await self._graphiti.close()

    async def search(
        self, query: str, group_id: str = None, num_results: int = 10,
    ):
        """Hybrid search over the knowledge graph, returns a list of edges (facts).

        Uses Graphiti's basic `search()` which combines vector + BM25 with
        cross-encoder reranking under the hood. Older callers passed a
        `search_method=...` kwarg sourced from `SearchMethod` — that enum
        was removed from `graphiti_core.search.search_config_recipes` (the
        recipes are now per-layer: `EdgeSearchMethod`, `NodeSearchMethod`,
        etc.). For an advanced multi-layer config, use `search_` instead.

        Returns:
            list[EntityEdge] — each has `.fact` (string) and graph metadata.
        """
        return await self._graphiti.search(
            query=query,
            num_results=num_results,
            group_ids=[group_id] if group_id else None,
        )

    async def get_nodes(self, query: str, num_results: int = 10,
                        group_id: str = None):
        """Return entity nodes matching the query.

        Old API was `Graphiti.retrieve_nodes(...)`, removed in current
        graphiti_core. Replacement: call `search_` with a node-only recipe
        and read `.nodes` off the returned `SearchResults` object.
        """
        import copy
        from graphiti_core.search.search_config_recipes import (
            NODE_HYBRID_SEARCH_RRF,
        )
        cfg = copy.deepcopy(NODE_HYBRID_SEARCH_RRF)
        cfg.limit = num_results
        results = await self._graphiti.search_(
            query=query,
            config=cfg,
            group_ids=[group_id] if group_id else None,
        )
        return getattr(results, "nodes", []) or []

    async def get_episodes(self, query: str, num_results: int = 10):
        return await self._graphiti.retrieve_episodes(
            query=query,
            num_results=num_results,
        )
