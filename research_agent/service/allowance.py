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
- K1 (the operator's word of 2026-11-13, DEC-0074 of the Appvillis keys plan): a cloud client's `interactive` key, a
  person or an agent a person calls in that moment, has no ceiling. Its job starts at once, whatever it costs, and its
  decision keeps who spent (the principal) and the class. An `automated` key, and a key without a class, keeps its
  ceiling.
- B-103: every job the allowance approves also reserves its worst case in the month ledger (the agents database
  pattern `spend-ledger` 1.3.0, vendored unchanged): one UTC-month stop across all automated callers at 95 % of
  `agent_monthly_usd` (USD 100 by default, the operator's rule of 2026-11-07). A job that would cross it waits for the
  operator, as above the day ceiling. When the job ends the hold settles to what it cost (the worst case while a call
  is unpriced), or is released when it ended before any call. Every change is a line of a hash-chained journal,
  `spend-ledger.jsonl` in the data root. Interactive keys (K1) and the operator's own jobs are not held.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from research_agent.config import ConfigError, resolve_llm_cap
from research_agent.service.vendor import spend_ledger
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
#: The month ledger's journal in the data root (the cloud's snapshot keeps it with the job store).
LEDGER_FILE = "spend-ledger.jsonl"


def month_ledger(store) -> spend_ledger.SpendLedger | None:
    """The store's month ledger at the current `agent_monthly_usd`, or None when it is 0 (allowance off). Rebuilt when
    the setting changes; the journal file is the same."""
    limit = float((store.config() or {}).get("agent_monthly_usd", 100.0))
    if limit <= OFF:
        return None
    cached = getattr(store, "_month_ledger", None)
    if cached is not None and cached[0] == limit:
        return cached[1]
    if cached is not None:
        cached[1].close()
    ledger = spend_ledger.SpendLedger(spend_ledger.Policy(key_limit_usd=str(limit), on_month_exhaust="defer"),
                                      str(store.root / LEDGER_FILE), storage="jsonl")
    store._month_ledger = (limit, ledger)
    if not getattr(store, "_month_hooked", False):
        store.on_end.append(lambda job: settle(store, job))
        store._month_hooked = True
    return ledger


def settle(store, job: dict[str, Any]) -> None:
    """A held job ended: its hold settles to what it cost, or is released when it ended before any call."""
    if not (job.get("decision") or {}).get("monthLedger"):
        return
    ledger = month_ledger(store)
    if ledger is None:
        return
    calls = store.calls(job["id"])
    if not calls:
        try:
            ledger.release(job["id"], f"job ended {job['status']} before any call")
            return
        except ValueError:
            return  # already settled or released
    priced = all(c.get("costUsd") is not None for c in calls)
    cost = sum(c["costUsd"] for c in calls if c.get("costUsd") is not None)
    try:
        ledger.settle(job["id"], cost, confirmed=priced)
    except ValueError:
        pass  # a repeat: the first figure stays


def month_degraded(store) -> list[dict[str, Any]]:
    """The month ledger's own `degraded` entries: a reached stop, a halt, a torn or edited journal line. Unpriced
    calls are counted at their worst case and are not a fault of the service, so they are left out."""
    try:
        ledger = month_ledger(store)
    except (ValueError, OSError) as exc:
        return [{"source": "budget", "reason": f"the month ledger cannot open: {exc}"}]
    if ledger is None:
        return []
    return [d for d in ledger.degraded() if d.get("source") != "usage"]


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


def ceiling_for(job: dict[str, Any], settings: dict[str, Any]) -> float | None:
    """A cloud client's own ceiling (never below the floor), none for its interactive key (K1), else the service's
    setting for local agents."""
    delegation = job.get("delegation") or {}
    if delegation.get("tier") == "client":
        if delegation.get("keyClass") == "interactive":
            return None
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
    spent = spent_today(store, principal)
    if ceiling is None:  # an interactive key: measured and shown, never held (K1)
        return {"by": "allowance", "principal": principal, "worstCaseUsd": round(worst, 4),
                "spentTodayUsd": round(spent, 4), "ceilingUsd": None, "keyClass": "interactive"}
    if ceiling <= OFF:
        return None
    if spent + worst > ceiling:
        return None
    ledger = month_ledger(store)
    if ledger is None:
        return None
    held = ledger.reserve(job["id"], worst, scopes={"principal": principal}, label=job["request"].get("kind", ""))
    if not held.allowed:
        return None
    return {"by": "allowance", "principal": principal, "worstCaseUsd": round(worst, 4),
            "spentTodayUsd": round(spent, 4), "ceilingUsd": ceiling, "monthLedger": True,
            "monthCommittedUsd": float(ledger.committed("month")), "monthStopUsd": float(ledger.limit("month"))}
