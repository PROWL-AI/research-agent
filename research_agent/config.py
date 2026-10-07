"""Environment configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

DEFAULT_PROWL_MCP_URL = "https://prowl.chat/mcp"
DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LLM_MODEL = "google/gemini-2.5-flash"
DEFAULT_LLM_MODEL_STRONG = "anthropic/claude-sonnet-4.5"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    prowl_api_key: str
    prowl_mcp_url: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_model_strong: str

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None, *, require_prowl: bool = True
    ) -> "Config":
        env = os.environ if environ is None else environ

        prowl_api_key = env.get("PROWL_API_KEY", "").strip()
        if require_prowl and not prowl_api_key:
            raise ConfigError(
                "PROWL_API_KEY is not set — get a key at https://prowl.chat and export it"
            )

        llm_api_key = (
            env.get("RESEARCH_LLM_API_KEY", "").strip()
            or env.get("OPENROUTER_API_KEY", "").strip()
        )
        if not llm_api_key:
            raise ConfigError(
                "no LLM key found — set RESEARCH_LLM_API_KEY or OPENROUTER_API_KEY"
            )

        return cls(
            prowl_api_key=prowl_api_key,
            prowl_mcp_url=env.get("PROWL_MCP_URL", DEFAULT_PROWL_MCP_URL).strip()
            or DEFAULT_PROWL_MCP_URL,
            llm_base_url=env.get("RESEARCH_LLM_BASE_URL", DEFAULT_LLM_BASE_URL).strip()
            or DEFAULT_LLM_BASE_URL,
            llm_api_key=llm_api_key,
            llm_model=env.get("RESEARCH_LLM_MODEL", DEFAULT_LLM_MODEL).strip()
            or DEFAULT_LLM_MODEL,
            llm_model_strong=env.get("RESEARCH_LLM_MODEL_STRONG", DEFAULT_LLM_MODEL_STRONG).strip()
            or DEFAULT_LLM_MODEL_STRONG,
        )
