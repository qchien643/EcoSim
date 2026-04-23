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
    """Thin wrapper around OpenAI SDK — sync + async interface."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_retries: int = 3,
    ):
        self.model = model or EcoSimConfig.llm_model_name()
        self.max_retries = max_retries
        self._api_key = api_key or EcoSimConfig.llm_api_key()
        self._base_url = base_url or EcoSimConfig.llm_base_url()
        self._sync_client: Optional[OpenAI] = None
        self._async_client: Optional[AsyncOpenAI] = None
        logger.debug("LLMClient configured: model=%s base_url=%s", self.model, self._base_url)

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

    # ──────────────────────────────────────────────
    # Sync API
    # ──────────────────────────────────────────────
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        response_format: Optional[Dict[str, str]] = None,
    ) -> str:
        """Chat completion sync → content string, retry với exponential backoff."""
        for attempt in range(1, self.max_retries + 1):
            try:
                kwargs: Dict[str, Any] = dict(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if response_format:
                    kwargs["response_format"] = response_format
                response = self.client.chat.completions.create(**kwargs)
                return response.choices[0].message.content or ""
            except Exception as e:
                logger.warning("LLM attempt %d/%d failed: %s", attempt, self.max_retries, e)
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                else:
                    raise

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """Chat → parse JSON, tự strip code fences."""
        content = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
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
    ) -> str:
        """Chat completion async — giống chat() nhưng không block event loop."""
        for attempt in range(1, self.max_retries + 1):
            try:
                kwargs: Dict[str, Any] = dict(
                    model=self.model,
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
                    "LLM async attempt %d/%d failed: %s", attempt, self.max_retries, e
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
    ) -> Dict[str, Any]:
        content = await self.chat_async(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        cleaned = _strip_code_fences(content)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("JSON parse (async) failed: %s\nRaw: %s", e, content[:500])
            raise ValueError(f"LLM returned invalid JSON: {e}") from e

    async def aclose(self) -> None:
        """Đóng async client (FastAPI shutdown hook)."""
        if self._async_client is not None:
            await self._async_client.close()
            self._async_client = None
