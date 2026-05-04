"""
Zep Cloud client factory — async + sync, lazy init từ ZEP_API_KEY env.

Zep Cloud là managed Graphiti server-side. EcoSim dùng cho KG extraction
(rich attributes + temporal validity + semantic dedup) khi `KG_BUILDER=zep_hybrid`.

Sau khi extract, fetch nodes/edges qua Zep API → mirror vào FalkorDB local
(re-embed locally vì Zep không expose embedding vectors). Xem
`apps/simulation/zep_kg_writer.py` cho pipeline đầy đủ.

Lifecycle:
- `make_async_zep_client()` → `AsyncZep` cho FastAPI sim service
- `make_sync_zep_client()` → `Zep` cho Flask Core service
- Cả 2 cache qua module-level dict; close khi service shutdown nếu cần
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .config import EcoSimConfig

if TYPE_CHECKING:
    from zep_cloud.client import AsyncZep, Zep

logger = logging.getLogger("ecosim_common.zep_client")

_async_client = None
_sync_client = None


class ZepKeyMissing(Exception):
    """Raised khi caller cần Zep client nhưng `ZEP_API_KEY` env chưa set.

    Caller (vd zep_kg_writer) bắt exception này → fallback sang `KG_BUILDER=direct`
    với log warning rõ ràng cho user.
    """
    pass


def make_async_zep_client():
    """Lazy-init shared `AsyncZep` instance.

    Raises ZepKeyMissing nếu ZEP_API_KEY chưa set.
    """
    global _async_client
    if _async_client is not None:
        return _async_client

    api_key = EcoSimConfig.zep_api_key()
    if not api_key:
        raise ZepKeyMissing(
            "ZEP_API_KEY env không set. Set trong .env hoặc switch "
            "KG_BUILDER=direct để dùng pipeline local."
        )

    try:
        from zep_cloud.client import AsyncZep
    except ImportError as e:
        raise ZepKeyMissing(
            "zep-cloud package chưa cài. Chạy: pip install zep-cloud"
        ) from e

    _async_client = AsyncZep(api_key=api_key)
    logger.info("AsyncZep client initialized (api_key=z_*** [redacted])")
    return _async_client


def make_sync_zep_client():
    """Lazy-init shared sync `Zep` instance cho Core service Flask handlers.

    Raises ZepKeyMissing nếu ZEP_API_KEY chưa set.
    """
    global _sync_client
    if _sync_client is not None:
        return _sync_client

    api_key = EcoSimConfig.zep_api_key()
    if not api_key:
        raise ZepKeyMissing(
            "ZEP_API_KEY env không set. Set trong .env hoặc switch "
            "KG_BUILDER=direct để dùng pipeline local."
        )

    try:
        from zep_cloud.client import Zep
    except ImportError as e:
        raise ZepKeyMissing(
            "zep-cloud package chưa cài. Chạy: pip install zep-cloud"
        ) from e

    _sync_client = Zep(api_key=api_key)
    logger.info("Sync Zep client initialized (api_key=z_*** [redacted])")
    return _sync_client


async def aclose_zep_client() -> None:
    """Đóng async client (FastAPI shutdown hook). Idempotent."""
    global _async_client
    if _async_client is not None:
        try:
            # zep-cloud SDK có thể có hoặc không close() — best effort
            close_method = getattr(_async_client, "close", None)
            if close_method is not None:
                if callable(close_method):
                    result = close_method()
                    if hasattr(result, "__await__"):
                        await result
        except Exception as e:
            logger.debug("Zep async client close error: %s", e)
        _async_client = None
