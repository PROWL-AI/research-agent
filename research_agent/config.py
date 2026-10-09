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
    #: Independent judge model (RESEARCH_JUDGE_MODEL) — empty means "use the
    #: strong model", so a report need not be graded by the model that wrote it.
    llm_model_judge: str = ""

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        require_prowl: bool = True,
        require_llm: bool = True,
    ) -> "Config":
        """Build a Config from the environment.

        ``require_prowl=False`` is for LLM-only flows (e.g. ``rewrite``);
        ``require_llm=False`` is for Prowl-only flows (e.g. online runbook
        validation) — the returned ``llm_api_key`` is then empty and unusable.
        """
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
        if require_llm and not llm_api_key:
            raise ConfigError(
                "no LLM key found — set RESEARCH_LLM_API_KEY or OPENROUTER_API_KEY"
            )

        model_strong = env.get("RESEARCH_LLM_MODEL_STRONG", DEFAULT_LLM_MODEL_STRONG).strip() or DEFAULT_LLM_MODEL_STRONG

        return cls(
            prowl_api_key=prowl_api_key,
            prowl_mcp_url=env.get("PROWL_MCP_URL", DEFAULT_PROWL_MCP_URL).strip()
            or DEFAULT_PROWL_MCP_URL,
            llm_base_url=env.get("RESEARCH_LLM_BASE_URL", DEFAULT_LLM_BASE_URL).strip()
            or DEFAULT_LLM_BASE_URL,
            llm_api_key=llm_api_key,
            llm_model=env.get("RESEARCH_LLM_MODEL", DEFAULT_LLM_MODEL).strip()
            or DEFAULT_LLM_MODEL,
            llm_model_strong=model_strong,
            llm_model_judge=env.get("RESEARCH_JUDGE_MODEL", "").strip() or model_strong,
        )
