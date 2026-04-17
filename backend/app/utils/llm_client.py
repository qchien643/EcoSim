"""
LLM Client — OpenAI-compatible wrapper.
Supports: OpenAI, Groq, Ollama, Together AI (via base_url).
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ..config import Config

logger = logging.getLogger("ecosim.llm")


class LLMClient:
    """Thin wrapper around OpenAI SDK for chat + JSON extraction."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_retries: int = 3,
    ):
        self.model = model or Config.LLM_MODEL_NAME
        self.max_retries = max_retries
        self.client = OpenAI(
            api_key=api_key or Config.LLM_API_KEY,
            base_url=base_url or Config.LLM_BASE_URL,
        )
        logger.info(f"LLMClient initialized: model={self.model}")

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        response_format: Optional[Dict[str, str]] = None,
    ) -> str:
        """Simple chat completion → returns content string."""
        for attempt in range(1, self.max_retries + 1):
            try:
                kwargs = dict(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if response_format:
                    kwargs["response_format"] = response_format
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                logger.debug(
                    f"LLM response ({len(content)} chars, "
                    f"tokens: {response.usage.total_tokens if response.usage else '?'})"
                )
                return content
            except Exception as e:
                logger.warning(f"LLM attempt {attempt}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """Chat completion → parse response as JSON dict.

        Automatically strips markdown code fences if present.
        Uses response_format for structured JSON output.
        """
        content = self.chat(
            messages, temperature=temperature, max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        # Strip markdown code fences: ```json ... ``` or ``` ... ```
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json) and last line (```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse failed: {e}\nRaw content:\n{content[:500]}")
            raise ValueError(f"LLM returned invalid JSON: {e}") from e

    def chat_with_prompt(
        self,
        user_prompt: str,
        system_prompt: str = "You are a helpful assistant. Return pure JSON.",
        **kwargs,
    ) -> str:
        """Convenience: system + user prompt → content string."""
        return self.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **kwargs,
        )
