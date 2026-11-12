"""A caller's daily allowance (B-100): a paid job that fits it starts without a person.

The operator's recorded word (agents database intake in-20261112-996c34, two sources): every key that reads or
orders carries a daily USD ceiling of at least 10 USD per UTC day, 10 by default. Delegation rules of 2026-11-05 and
2026-11-07: an approval inside a task is the agent's, and the operator presses nothing. So a job an agent creates is
approved by its allowance when the job's worst case fits what is left of the caller's ceiling today; above it, the
job waits for the operator as before.

- The worst case of a job is what it may spend at most: a research run's tool budget (`budget.max_usd`) plus its
  LLM cap, one Prowl tool call's `TOOL_JOB_WORST_USD`, nothing for the tutorial. An unknown cost is never zero.
- A job counts against the day it was approved: its worst case until it ends with every call priced, then what it
  really cost. A job rejected or cancelled before approval costs nothing.
- The dashboard's own requests are the operator's: they wait for the operator's click as before.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from research_agent.config import ConfigError, resolve_llm_cap
from research_agent.runbook import RunbookError, get_runbook

#: The floor and default of a caller's ceiling, USD per UTC day (in-20261112-996c34).
DAILY_FLOOR_USD = 10.0
#: The most a single Prowl tool call may cost: the provider prices calls in cents, the reserve is generous.
TOOL_JOB_WORST_USD = 1.0
#: The worst case of a job whose runbook or cap cannot be read: above any ceiling, and still valid JSON.
UNREADABLE_WORST_USD = 1_000_000.0
#: Settings value that turns local agents' allowance off (every paid job waits for the operator).
OFF = 0.0

TERMINAL = {"completed", "failed", "cancelled"}


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def worst_case_usd(request: dict[str, Any]) -> float:
    """At most what the job may spend. A research job whose runbook or cap cannot be read is refused upstream; here
    it is priced above any ceiling so it never slips under one."""
    kind = request.get("kind")
    if kind == "tutorial":
        return 0.0
    if kind == "tool":
        return TOOL_JOB_WORST_USD
    try:
        runbook = get_runbook(request["runbook"])
        llm, _ = resolve_llm_cap(request.get("max_llm_usd"), None, runbook.meta.budget.max_llm_usd)
        return float(runbook.meta.budget.max_usd) + float(llm)
    except (RunbookError, ConfigError, KeyError):
        return UNREADABLE_WORST_USD


def principal_of(job: dict[str, Any]) -> str | None:
    """Who the job's money is counted for: the delegation's principal (a cloud client is `client:<name>`), the
    service's own agent token as `agent`, or None for the operator's dashboard."""
    if job.get("via") == "dashboard":
        return None
    delegation = job.get("delegation") or {}
    return delegation.get("principal") or "agent"


def job_cost(job: dict[str, Any], calls: list[dict[str, Any]]) -> float:
    if (job.get("decision") or {}).get("approved") is not True:
        return 0.0
    known = sum(c["costUsd"] for c in calls if c.get("costUsd") is not None)
    if job["status"] in TERMINAL and all(c.get("costUsd") is not None for c in calls):
        return known
    return max(known, float((job.get("decision") or {}).get("worstCaseUsd") or 0.0))


def spent_today(store, principal: str, day: str | None = None) -> float:
    day = day or today()
    total = 0.0
    for job in store.jobs():
        decision = job.get("decision") or {}
        if principal_of(job) != principal or not str(decision.get("at", "")).startswith(day):
            continue
        total += job_cost(job, store.calls(job["id"]))
    return total


def ceiling_for(job: dict[str, Any], settings: dict[str, Any]) -> float:
    """A cloud client's own ceiling (never below the floor), else the service's setting for local agents."""
    delegation = job.get("delegation") or {}
    if delegation.get("tier") == "client":
        return max(float(delegation.get("dailyUsd") or DAILY_FLOOR_USD), DAILY_FLOOR_USD)
    return float(settings.get("agent_daily_usd", DAILY_FLOOR_USD))


def verdict(store, job: dict[str, Any]) -> dict[str, Any] | None:
    """The allowance's decision for a new job, or None when the job waits for the operator."""
    principal = principal_of(job)
    if principal is None:
        return None
    worst = worst_case_usd(job["request"])
    if worst == 0.0:
        return {"by": "allowance", "principal": principal, "worstCaseUsd": 0.0, "reason": "free"}
    ceiling = ceiling_for(job, job.get("config") or {})
    if ceiling <= OFF:
        return None
    spent = spent_today(store, principal)
    if spent + worst > ceiling:
        return None
    return {"by": "allowance", "principal": principal, "worstCaseUsd": round(worst, 4),
            "spentTodayUsd": round(spent, 4), "ceilingUsd": ceiling}
