"""Minimal async OpenAI-compatible chat client."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

Tier = Literal["cheap", "strong"]

_TIMEOUT = httpx.Timeout(120.0)
_MAX_ATTEMPTS = 2


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_cheap: str,
        model_strong: str,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_cheap = model_cheap
        self.model_strong = model_strong
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def model_for(self, tier: Tier) -> str:
        return self.model_strong if tier == "strong" else self.model_cheap

    async def complete(
        self,
        messages: list[dict[str, str]],
        tier: Tier = "cheap",
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model_for(tier),
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._client.post(
                    f"{self.base_url}/chat/completions", json=payload
                )
                if response.status_code >= 500 or response.status_code == 429:
                    raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:300]}")
                if response.status_code >= 400:
                    raise LLMError(
                        f"LLM HTTP {response.status_code} (not retrying): {response.text[:300]}"
                    )
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except (httpx.TransportError, LLMError) as exc:
                if isinstance(exc, LLMError) and "not retrying" in str(exc):
                    raise
                last_error = exc
                if attempt < _MAX_ATTEMPTS:
                    log.warning("LLM call failed (attempt %d): %s; retrying", attempt, exc)
                    await asyncio.sleep(1.0)
        raise LLMError(f"LLM call failed after {_MAX_ATTEMPTS} attempts: {last_error}")
