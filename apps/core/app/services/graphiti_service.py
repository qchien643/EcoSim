"""
Graphiti Client Factory — per-graph cached Graphiti instances.

Trước đây là singleton hardcode `database="ecosim"` — dùng được khi cả hệ
thống chỉ có 1 graph chung. Sau master+fork architecture, mỗi campaign 1
master graph + N sim graphs → cần Graphiti instance riêng cho mỗi graph
(FalkorDriver `database=` được set per-instance).

Helper cache theo `graph_name` để tránh re-build indexes mỗi call. Lifecycle:
caller responsibility — gọi `close_graphiti_client(graph_name)` hoặc
`close_all_graphiti_clients()` ở service shutdown.

Embedder + entity-extraction LLM được route qua `ecosim_common.LLMClient` để
đồng bộ với chat env (xem libs/ecosim-common/src/ecosim_common/graphiti_factory.py).
"""

import logging
from typing import Dict

from ..config import Config

logger = logging.getLogger("ecosim.graphiti_service")

# Cache: graph_name → Graphiti instance (built lazily)
_clients: Dict[str, object] = {}
# graph_name nào đã thử init nhưng fail → skip retry trong cùng process
_failed: set = set()


async def get_graphiti_client(graph_name: str):
    """Get or create Graphiti client for a specific FalkorDB graph.

    Args:
        graph_name: FalkorDB graph name (vd `campaign_id` cho master, hoặc
            `sim_<sim_id>` cho per-sim). Bắt buộc — không có default vì
            sau master+fork architecture, không còn graph "ecosim" chung.

    Returns:
        Graphiti instance hoặc None nếu init failed (logged once).
    """
    if not graph_name:
        logger.error(
            "get_graphiti_client() called without graph_name. After master+fork "
            "architecture, mỗi caller phải biết rõ mình đọc graph nào."
        )
        return None

    if graph_name in _clients:
        return _clients[graph_name]
    if graph_name in _failed:
        return None

    try:
        # Import qua shared lib để dùng chung embedder + LLM config với Sim svc
        from ecosim_common.graphiti_factory import make_graphiti, make_falkor_driver

        driver = make_falkor_driver(
            host=Config.FALKORDB_HOST,
            port=int(Config.FALKORDB_PORT),
            database=graph_name,
        )
        client = make_graphiti(driver)
        _clients[graph_name] = client
        logger.info(
            "Graphiti client initialized for graph='%s' (FalkorDB @ %s:%s)",
            graph_name, Config.FALKORDB_HOST, Config.FALKORDB_PORT,
        )
        return client

    except ImportError:
        logger.warning(
            "graphiti-core[falkordb] not installed. "
            "Run: pip install graphiti-core[falkordb]"
        )
        _failed.add(graph_name)
        return None
    except Exception as e:
        logger.warning(f"Graphiti client init failed for {graph_name}: {e}")
        _failed.add(graph_name)
        return None


async def close_graphiti_client(graph_name: str) -> None:
    """Close 1 cached Graphiti client."""
    client = _clients.pop(graph_name, None)
    if client is not None:
        try:
            await client.close()
        except Exception as e:
            logger.debug(f"Graphiti close error for {graph_name}: {e}")
    _failed.discard(graph_name)


async def close_all_graphiti_clients() -> None:
    """Close tất cả cached Graphiti clients (FastAPI/Flask shutdown hook)."""
    for name in list(_clients.keys()):
        await close_graphiti_client(name)
