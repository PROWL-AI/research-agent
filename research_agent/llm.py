"""Minimal async OpenAI-compatible chat client."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

Tier = Literal["cheap", "strong"]

_MAX_ATTEMPTS = 3


class LLMError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


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
        # The agent's own LLM spend is real money the tool budgets never see;
        # it is accounted here and reported in run stats, not silently absent.
        self._usage: dict[str, Any] = {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "by_tier": {},
        }

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def model_for(self, tier: Tier) -> str:
        return self.model_strong if tier == "strong" else self.model_cheap

    def usage_snapshot(self) -> dict[str, Any]:
        return {
            "calls": self._usage["calls"],
            "prompt_tokens": self._usage["prompt_tokens"],
            "completion_tokens": self._usage["completion_tokens"],
            "by_tier": {tier: dict(row) for tier, row in self._usage["by_tier"].items()},
        }

    def _record_usage(self, tier: Tier, data: dict[str, Any]) -> None:
        usage = data.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        self._usage["calls"] += 1
        self._usage["prompt_tokens"] += prompt
        self._usage["completion_tokens"] += completion
        row = self._usage["by_tier"].setdefault(
            tier, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "model": self.model_for(tier)}
        )
        row["calls"] += 1
        row["prompt_tokens"] += prompt
        row["completion_tokens"] += completion

    @staticmethod
    def _extract(data: dict[str, Any]) -> str:
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM response has no choices: {str(data)[:300]}") from exc
        finish = choice.get("finish_reason")
        content = (choice.get("message") or {}).get("content")
        if content is None:
            raise LLMError(f"LLM response has null content (finish_reason={finish!r})")
        # A truncated draft must not flow into lint/repair as if it were the
        # whole report — retrying with the same max_tokens truncates the same
        # way, so this fails fast and loud instead.
        if finish == "length":
            raise LLMError(
                "LLM output truncated at max_tokens (finish_reason='length')",
                retryable=False,
            )
        return content

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
        response: httpx.Response | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._client.post(
                    f"{self.base_url}/chat/completions", json=payload
                )
                if response.status_code >= 500 or response.status_code == 429:
                    raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:300]}")
                if response.status_code >= 400:
                    raise LLMError(
                        f"LLM HTTP {response.status_code}: {response.text[:300]}",
                        retryable=False,
                    )
                try:
                    data = response.json()
                except ValueError as exc:
                    raise LLMError(f"LLM returned non-JSON body: {response.text[:200]}") from exc
                content = self._extract(data)
                self._record_usage(tier, data)
                return content
            except (httpx.TransportError, LLMError) as exc:
                if isinstance(exc, LLMError) and not exc.retryable:
                    raise
                last_error = exc
                if attempt < _MAX_ATTEMPTS:
                    delay = float(2 ** (attempt - 1))
                    retry_after = response.headers.get("retry-after") if response is not None else None
                    if retry_after:
                        try:
                            delay = max(delay, min(float(retry_after), 30.0))
                        except ValueError:
                            pass
                    log.warning("LLM call failed (attempt %d): %s; retrying in %.0fs", attempt, exc, delay)
                    await asyncio.sleep(delay)
        raise LLMError(f"LLM call failed after {_MAX_ATTEMPTS} attempts: {last_error}")
