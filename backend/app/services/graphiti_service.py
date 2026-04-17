"""
Graphiti Client Singleton — Shared Graphiti client for KG retrieval and agent seeding.

Uses FalkorDriver to connect to existing FalkorDB (port 6379).
Provides async client lifecycle management.
"""

import logging
from typing import Optional

from ..config import Config

logger = logging.getLogger("ecosim.graphiti_service")

_client = None
_initialized = False


async def get_graphiti_client():
    """Get or create singleton Graphiti client with FalkorDriver."""
    global _client, _initialized

    if _client is not None:
        return _client

    if _initialized:
        # Already tried and failed
        return None

    _initialized = True

    try:
        from graphiti_core import Graphiti
        from graphiti_core.driver.falkordb_driver import FalkorDriver

        driver = FalkorDriver(
            host=Config.FALKORDB_HOST,
            port=str(Config.FALKORDB_PORT),  # FalkorDriver expects string
            database="ecosim",  # MUST match graph_builder/graph_query select_graph("ecosim")
        )

        _client = Graphiti(graph_driver=driver)
        logger.info(
            f"Graphiti client initialized: FalkorDB @ "
            f"{Config.FALKORDB_HOST}:{Config.FALKORDB_PORT} database=ecosim"
        )
        return _client

    except ImportError:
        logger.warning(
            "graphiti-core[falkordb] not installed. "
            "Run: pip install graphiti-core[falkordb]"
        )
        return None
    except Exception as e:
        logger.warning(f"Graphiti client init failed: {e}")
        return None


async def close_graphiti_client():
    """Close the singleton Graphiti client."""
    global _client, _initialized

    if _client is not None:
        try:
            await _client.close()
        except Exception as e:
            logger.debug(f"Graphiti close error: {e}")
        _client = None

    _initialized = False
