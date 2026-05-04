"""
Graphiti factory — DRY helper để khởi tạo Graphiti với cấu hình thống nhất.

Mọi nơi instantiate `Graphiti(...)` trong EcoSim phải đi qua đây để đảm bảo:
1. Embedder dùng cùng provider + model với LLMClient (1 vector space duy nhất).
2. LLM client cho entity extraction dùng cùng provider với chat (vd Groq/Together
   thay vì hardcode OpenAI default).
3. FalkorDriver luôn được pass `database=` (tránh silent bug ghi vào default_db).

Pattern dùng:
    from ecosim_common.graphiti_factory import make_graphiti, make_falkor_driver
    from ecosim_common.llm_client import LLMClient

    llm = LLMClient()
    driver = make_falkor_driver(host, port, database="my_graph")
    graphiti = make_graphiti(driver, llm=llm)
    await graphiti.build_indices_and_constraints()
"""

from __future__ import annotations

from typing import Optional

from .llm_client import LLMClient


def make_falkor_driver(host: str, port: int, database: str):
    """Tạo FalkorDriver với database name bắt buộc.

    Lý do bắt buộc `database`: nếu bỏ qua, FalkorDriver default về `default_db`
    → mọi write đi vào graph chung → silent isolation bug. Đây từng là bug
    nguy hiểm nhất ở apps/simulation/falkor_graph_memory.py:164 trước khi fix.
    """
    if not database:
        raise ValueError("FalkorDriver phải có `database` name (tên FalkorDB graph)")
    from graphiti_core.driver.falkordb_driver import FalkorDriver
    return FalkorDriver(host=host, port=str(port), database=database)


async def build_indices_with_retry(graphiti, *, max_retries: int = 3, backoff: float = 1.5):
    """Wrapper cho `graphiti.build_indices_and_constraints()` với retry on
    network/connection errors.

    Lý do: FalkorDB qua redis-py có thể drop connection lúc CREATE FULLTEXT
    INDEX (long ops + Redis BGSAVE concurrent). Graphiti internal tạo
    concurrent tasks → 1 task fail bằng ConnectionError → propagate up.

    Strategy: catch any exception có "ConnectionError" hoặc "network" trong str,
    retry với exponential backoff. Sau max_retries fail → re-raise.

    Returns: True nếu thành công, False nếu fail tất cả retries (caller
    quyết định coi đó có blocking hay không).
    """
    import asyncio
    import logging as _logging
    _log = _logging.getLogger("ecosim.graphiti")

    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            await graphiti.build_indices_and_constraints()
            if attempt > 0:
                _log.info("build_indices succeeded on retry %d", attempt + 1)
            return True
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            is_network = (
                "connection" in err_str
                or "network" in err_str
                or "timeout" in err_str
                or "broken pipe" in err_str
            )
            if not is_network or attempt == max_retries - 1:
                _log.warning(
                    "build_indices failed (attempt %d/%d, network=%s): %s",
                    attempt + 1, max_retries, is_network, e,
                )
                if attempt == max_retries - 1:
                    return False
                raise
            wait = backoff ** attempt
            _log.warning(
                "build_indices network error (attempt %d/%d), retry in %.1fs: %s",
                attempt + 1, max_retries, wait, e,
            )
            await asyncio.sleep(wait)
    if last_err:
        _log.error("build_indices exhausted retries: %s", last_err)
    return False


def make_openai_embedder(llm: LLMClient):
    """Tạo Graphiti OpenAIEmbedder dùng cùng config với LLMClient embeddings.

    Wraps `OpenAIEmbedderConfig(api_key, base_url, embedding_model, embedding_dim)`
    với values đến từ LLMClient (đã đọc env LLM_EMBEDDING_*).
    """
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    config = OpenAIEmbedderConfig(
        api_key=llm.embedding_api_key,
        base_url=llm.embedding_base_url,
        embedding_model=llm.embedding_model,
        embedding_dim=llm.embedding_dim,
    )
    return OpenAIEmbedder(config=config)


def make_graphiti_llm(llm: LLMClient):
    """Tạo Graphiti's internal LLMClient (cho entity extraction) routing qua
    cùng provider với chat.

    Graphiti default `OpenAIClient` dùng OPENAI_API_KEY + api.openai.com. Nếu
    user dùng Groq/Together làm primary, mặc định này fail. Inject explicit
    config để Graphiti gọi chat completions qua provider chính.
    """
    from graphiti_core.llm_client import LLMConfig, OpenAIClient
    config = LLMConfig(
        api_key=llm._api_key,
        base_url=llm._base_url,
        model=llm.model,
    )
    return OpenAIClient(config=config)


def make_graphiti(driver, llm: Optional[LLMClient] = None):
    """Tạo Graphiti instance với embedder + llm_client từ LLMClient.

    Args:
        driver: FalkorDriver (đã có database= set, dùng make_falkor_driver).
        llm: LLMClient instance. Nếu None → tự tạo default.

    Returns:
        Graphiti instance — chưa gọi build_indices_and_constraints, caller
        chịu trách nhiệm gọi sau (vì là async).
    """
    from graphiti_core import Graphiti
    if llm is None:
        llm = LLMClient()
    embedder = make_openai_embedder(llm)
    graphiti_llm = make_graphiti_llm(llm)
    return Graphiti(graph_driver=driver, llm_client=graphiti_llm, embedder=embedder)
