"""Environment configuration."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Mapping

DEFAULT_PROWL_MCP_URL = "https://prowl.chat/mcp"
DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"
#: Model defaults: the cheap tier
#: (claim extraction, transforms — high volume) runs the lite model, the strong
#: tier (planner, writer) the strongest listed model, and the judge a model of a
#: DIFFERENT vendor, so a report is not graded by the family that wrote it.
DEFAULT_LLM_MODEL = "deepseek/deepseek-v4.1-flash"
DEFAULT_LLM_MODEL_STRONG = "xiaomi/mimo-v2.6-pro"
DEFAULT_JUDGE_MODEL = "anthropic/claude-haiku-5.5"
#: The run's LLM spend ceiling when neither the caller, the environment
#: (RESEARCH_MAX_LLM_USD) nor the runbook sets one — never unlimited.
DEFAULT_MAX_LLM_USD = 5.0
#: Share of the LLM ceiling held back for the writer, repair and citation
#: passes, so a run that spends its research allowance still writes a report.
WRITER_RESERVE_SHARE = 0.25
WRITER_RESERVE_MAX_USD = 1.0


class ConfigError(Exception):
    pass


def resolve_llm_cap(
    explicit: float | None, recorded: float | None, runbook_cap: float | None,
    environ: Mapping[str, str] | None = None,
) -> tuple[float, str]:
    """(cap, source): the caller's value, then RESEARCH_MAX_LLM_USD, then the
    cap a resumed run recorded, then the runbook's, then DEFAULT_MAX_LLM_USD."""
    env = os.environ if environ is None else environ

    def valid(value: object, name: str) -> float:
        # Finite and positive: an infinite cap is no cap (and does not even
        # serialize into the checkpoint).
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{name} is not a number: {value!r}") from exc
        if not (math.isfinite(number) and number > 0):
            raise ConfigError(f"{name} must be a finite number > 0, got {value!r}")
        return number

    if explicit is not None:
        return valid(explicit, "max_llm_usd"), "caller"
    raw = env.get("RESEARCH_MAX_LLM_USD", "").strip()
    if raw:
        return valid(raw, "RESEARCH_MAX_LLM_USD"), "env"
    if recorded is not None:
        return valid(recorded, "the run's recorded llm_cap_usd"), "checkpoint"
    if runbook_cap is not None:
        return valid(runbook_cap, "the runbook's budget.max_llm_usd"), "runbook"
    return DEFAULT_MAX_LLM_USD, "default"


def writer_reserve(cap: float) -> float:
    return round(min(WRITER_RESERVE_MAX_USD, cap * WRITER_RESERVE_SHARE), 6)


@dataclass(frozen=True)
class Config:
    prowl_api_key: str
    prowl_mcp_url: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_model_strong: str
    #: Independent judge model (RESEARCH_JUDGE_MODEL); unset means
    #: DEFAULT_JUDGE_MODEL, a vendor other than the default writer's.
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
            llm_model_judge=env.get("RESEARCH_JUDGE_MODEL", "").strip() or DEFAULT_JUDGE_MODEL,
        )
