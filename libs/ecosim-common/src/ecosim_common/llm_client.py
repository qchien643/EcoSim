"""
LLM Client — OpenAI-compatible wrapper (sync + async).

Single point of LLM access cho cả Core Service (sync Flask) và Simulation
Service (async FastAPI). Tránh duplicate httpx code ở oasis/campaign_knowledge.

Hỗ trợ mọi endpoint OpenAI-compatible (OpenAI, Groq, Together AI, Ollama, ...)
qua `base_url`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI, OpenAI

from .config import EcoSimConfig

logger = logging.getLogger("ecosim_common.llm")


def _strip_code_fences(content: str) -> str:
    """Loại ```json ... ``` hoặc ``` ... ``` nếu LLM wrap JSON."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        cleaned = "\n".join(lines)
    return cleaned


class LLMClient:
    """Thin wrapper around OpenAI SDK — sync + async interface.

    Cung cấp cả chat completions lẫn embeddings qua cùng OpenAI-compatible API.
    Chat dùng `LLM_*` env (model + base_url + api_key); embeddings dùng
    `LLM_EMBEDDING_*` env (mặc định fallback về cùng base/api_key của chat).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_base_url: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
        max_retries: int = 3,
    ):
        self.model = model or EcoSimConfig.llm_model_name()
        self.max_retries = max_retries
        self._api_key = api_key or EcoSimConfig.llm_api_key()
        self._base_url = base_url or EcoSimConfig.llm_base_url()
        self._sync_client: Optional[OpenAI] = None
        self._async_client: Optional[AsyncOpenAI] = None

        # Embedding config — separate clients nếu base_url/api_key khác chat
        # (ví dụ chat = Groq, embeddings = OpenAI). Thường thì giống → reuse client.
        self.embedding_model = embedding_model or EcoSimConfig.llm_embedding_model()
        self._embedding_api_key = embedding_api_key or EcoSimConfig.llm_embedding_api_key()
        self._embedding_base_url = embedding_base_url or EcoSimConfig.llm_embedding_base_url()
        self._embed_sync_client: Optional[OpenAI] = None
        self._embed_async_client: Optional[AsyncOpenAI] = None
        self._embedding_dim: Optional[int] = EcoSimConfig.llm_embedding_dim_hint(self.embedding_model)

        logger.debug(
            "LLMClient configured: chat model=%s base=%s | embed model=%s base=%s dim=%s",
            self.model, self._base_url,
            self.embedding_model, self._embedding_base_url, self._embedding_dim,
        )

    # ──────────────────────────────────────────────
    # Lazy clients
    # ──────────────────────────────────────────────
    @property
    def client(self) -> OpenAI:
        if self._sync_client is None:
            self._sync_client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._sync_client

    @property
    def aclient(self) -> AsyncOpenAI:
        if self._async_client is None:
            self._async_client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._async_client

    @property
    def embed_client(self) -> OpenAI:
        """Sync OpenAI client cho embeddings. Reuse chat client nếu cùng config."""
        if self._embed_sync_client is None:
            same_creds = (
                self._embedding_api_key == self._api_key
                and self._embedding_base_url == self._base_url
            )
            self._embed_sync_client = self.client if same_creds else OpenAI(
                api_key=self._embedding_api_key, base_url=self._embedding_base_url
            )
        return self._embed_sync_client

    @property
    def embed_aclient(self) -> AsyncOpenAI:
        """Async OpenAI client cho embeddings. Reuse chat aclient nếu cùng config."""
        if self._embed_async_client is None:
            same_creds = (
                self._embedding_api_key == self._api_key
                and self._embedding_base_url == self._base_url
            )
            self._embed_async_client = self.aclient if same_creds else AsyncOpenAI(
                api_key=self._embedding_api_key, base_url=self._embedding_base_url
            )
        return self._embed_async_client

    @property
    def embedding_dim(self) -> int:
        """Trả dim của embedding model. Probe 1 call nếu không biết trước.

        Cache vĩnh viễn sau lần probe đầu — model + base_url không đổi runtime.
        """
        if self._embedding_dim is None:
            # Probe: embed 1 token để lấy dim
            try:
                vec = self.embed("dim_probe")
                self._embedding_dim = len(vec)
                logger.info(
                    "Probed embedding dim for model %s: %d", self.embedding_model, self._embedding_dim,
                )
            except Exception as e:
                logger.error("Failed to probe embedding dim: %s", e)
                # Fallback: assume OpenAI default 1536. Caller chịu trách nhiệm verify.
                self._embedding_dim = 1536
        return self._embedding_dim

    @property
    def embedding_base_url(self) -> str:
        return self._embedding_base_url

    @property
    def embedding_api_key(self) -> str:
        return self._embedding_api_key

    # ──────────────────────────────────────────────
    # Sync API
    # ──────────────────────────────────────────────
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        response_format: Optional[Dict[str, str]] = None,
        model: Optional[str] = None,
    ) -> str:
        """Chat completion sync → content string, retry với exponential backoff.

        `model` override per-call (vd cho extraction tier dùng gpt-4o thay
        cho main gpt-4o-mini). None → dùng `self.model` đã config ở __init__.
        """
        use_model = model or self.model
        for attempt in range(1, self.max_retries + 1):
            try:
                kwargs: Dict[str, Any] = dict(
                    model=use_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if response_format:
                    kwargs["response_format"] = response_format
                response = self.client.chat.completions.create(**kwargs)
                return response.choices[0].message.content or ""
            except Exception as e:
                logger.warning(
                    "LLM attempt %d/%d failed (model=%s): %s",
                    attempt, self.max_retries, use_model, e,
                )
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                else:
                    raise

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Chat → parse JSON, tự strip code fences. `model` override per-call."""
        content = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            model=model,
        )
        cleaned = _strip_code_fences(content)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("JSON parse failed: %s\nRaw: %s", e, content[:500])
            raise ValueError(f"LLM returned invalid JSON: {e}") from e

    def chat_with_prompt(
        self,
        user_prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        **kwargs,
    ) -> str:
        return self.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **kwargs,
        )

    # ──────────────────────────────────────────────
    # Async API (cho FastAPI Simulation Service)
    # ──────────────────────────────────────────────
    async def chat_async(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        response_format: Optional[Dict[str, str]] = None,
        model: Optional[str] = None,
    ) -> str:
        """Chat completion async — giống chat() nhưng không block event loop.

        `model` override per-call. None → self.model.
        """
        use_model = model or self.model
        for attempt in range(1, self.max_retries + 1):
            try:
                kwargs: Dict[str, Any] = dict(
                    model=use_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if response_format:
                    kwargs["response_format"] = response_format
                response = await self.aclient.chat.completions.create(**kwargs)
                return response.choices[0].message.content or ""
            except Exception as e:
                logger.warning(
                    "LLM async attempt %d/%d failed (model=%s): %s",
                    attempt, self.max_retries, use_model, e,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(2**attempt)
                else:
                    raise

    async def chat_json_async(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        content = await self.chat_async(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            model=model,
        )
        cleaned = _strip_code_fences(content)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("JSON parse (async) failed: %s\nRaw: %s", e, content[:500])
            raise ValueError(f"LLM returned invalid JSON: {e}") from e

    # ──────────────────────────────────────────────
    # Embeddings (sync + async, single + batch)
    # ──────────────────────────────────────────────
    def embed(self, text: str) -> List[float]:
        """Sync embed 1 text → vector. Retry với exponential backoff."""
        result = self.embed_batch([text])
        return result[0] if result else []

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Sync batch embed (OpenAI API hỗ trợ tới ~2048 inputs/call).

        Empty strings filter trước khi gọi (OpenAI reject empty input).
        Trả list cùng length với input, vector rỗng `[]` cho input rỗng.
        """
        if not texts:
            return []
        # Filter empties + remember positions để khôi phục output đúng vị trí
        non_empty: List[tuple[int, str]] = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
        if not non_empty:
            return [[] for _ in texts]

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.embed_client.embeddings.create(
                    model=self.embedding_model,
                    input=[t for _, t in non_empty],
                )
                vectors = [d.embedding for d in resp.data]
                # Build output list theo order gốc
                output: List[List[float]] = [[] for _ in texts]
                for (idx, _), vec in zip(non_empty, vectors):
                    output[idx] = vec
                return output
            except Exception as e:
                logger.warning(
                    "Embedding attempt %d/%d failed (model=%s, n=%d): %s",
                    attempt, self.max_retries, self.embedding_model, len(non_empty), e,
                )
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                else:
                    raise

    async def embed_async(self, text: str) -> List[float]:
        """Async embed 1 text."""
        result = await self.embed_batch_async([text])
        return result[0] if result else []

    async def embed_batch_async(self, texts: List[str]) -> List[List[float]]:
        """Async batch embed."""
        if not texts:
            return []
        non_empty: List[tuple[int, str]] = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
        if not non_empty:
            return [[] for _ in texts]

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = await self.embed_aclient.embeddings.create(
                    model=self.embedding_model,
                    input=[t for _, t in non_empty],
                )
                vectors = [d.embedding for d in resp.data]
                output: List[List[float]] = [[] for _ in texts]
                for (idx, _), vec in zip(non_empty, vectors):
                    output[idx] = vec
                return output
            except Exception as e:
                logger.warning(
                    "Embedding async attempt %d/%d failed (model=%s, n=%d): %s",
                    attempt, self.max_retries, self.embedding_model, len(non_empty), e,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(2**attempt)
                else:
                    raise

    async def aclose(self) -> None:
        """Đóng async clients (FastAPI shutdown hook). Idempotent."""
        chat = self._async_client
        embed = self._embed_async_client
        # Capture references first vì sẽ set None sau
        same = chat is embed
        if chat is not None:
            await chat.close()
            self._async_client = None
        if embed is not None and not same:
            await embed.close()
        self._embed_async_client = None
