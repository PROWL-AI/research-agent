"""LLM price table: the estimate behind every LLM attempt without a provider cost.

Prices are USD per 1M tokens (input, output), read from the OpenRouter catalog
(`GET https://openrouter.ai/api/v1/models`) on 2026-10-17. They change: a
provider-reported `usage.cost` always wins over this table, and a model missing
here is estimated at the most expensive listed price — never 0, so an unknown
model cannot slip past `max_llm_usd`.
"""

from __future__ import annotations

from typing import Any

PRICES_READ_AT = "2026-10-17"

#: model id → (input USD / 1M tokens, output USD / 1M tokens)
PRICES: dict[str, tuple[float, float]] = {
    "xiaomi/mimo-v2.6-pro": (0.435, 0.87),
    "anthropic/claude-haiku-5.5": (0.10, 0.50),
    "google/gemini-3.8-flash": (0.825, 4.125),
    "qwen/qwen3.8-flash": (0.15, 0.47),
    "deepseek/deepseek-v4.1-flash": (0.032, 0.144),
    "z-ai/glm-5.3-flash": (0.04, 0.20),
    # previous defaults, kept so old configurations estimate correctly
    "google/gemini-2.5-flash": (0.30, 2.50),
    "anthropic/claude-sonnet-4.5": (3.0, 15.0),
}

#: The conservative price for a model the table does not know.
UNKNOWN_PRICE: tuple[float, float] = max(PRICES.values(), key=lambda p: p[0] + p[1])

#: Characters per token for a prompt estimate before the provider counts it.
CHARS_PER_TOKEN = 4
#: Output tokens assumed when a call sets no max_tokens.
DEFAULT_OUTPUT_TOKENS = 2000


def price(model: str) -> tuple[tuple[float, float], bool]:
    """(price, known) — unknown models get UNKNOWN_PRICE."""
    known = PRICES.get(model)
    return (known, True) if known else (UNKNOWN_PRICE, False)


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> tuple[float, bool]:
    (p_in, p_out), known = price(model)
    return round(tokens_in * p_in / 1e6 + tokens_out * p_out / 1e6, 6), known


def estimate_call_usd(model: str, messages: list[dict[str, Any]], max_tokens: int | None) -> float:
    """Upper-bound estimate of one call before it is sent: the prompt at
    CHARS_PER_TOKEN and the whole output budget."""
    chars = sum(len(str(m.get("content", ""))) for m in messages)
    tokens_in = chars // CHARS_PER_TOKEN + 1
    tokens_out = max_tokens if max_tokens is not None else DEFAULT_OUTPUT_TOKENS
    return cost_usd(model, tokens_in, tokens_out)[0]
