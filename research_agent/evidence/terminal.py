"""Terminal codes: why a run stopped, as one closed set of machine-readable names.

`Checkpoint.status` says *what* state a run is in (running, complete, partial,
failed, interrupted); `terminal_code` says *why* it got there. It is `None`
while a run is live and set on every terminal write. The set is closed: a
consumer may switch on it exhaustively.
"""

from __future__ import annotations

from typing import Any

#: Every planned step ran (on_error_skip disclosures included).
COMPLETED = "completed"
#: Budget stops — the run ended partial because a runbook budget ran out.
BUDGET_TOOLS = "budget_tools"
BUDGET_USD = "budget_usd"
BUDGET_MINUTES = "budget_minutes"
#: LLM-spend budget stop: the run's max_llm_usd left no room for the next call.
BUDGET_LLM = "budget_llm"
#: A step failed hard (not on_error_skip) or a worker crashed.
STEP_FAILED = "step_failed"
#: Evidence could not be persisted/extracted (declared now, set from wave 2).
EVIDENCE_INCOMPLETE = "evidence_incomplete"
#: The owning process cancelled the run (caller cancel, service cancel/timeout).
CANCELLED = "cancelled"
#: An exception escaped the run; stop_reason carries its message.
ERROR = "error"
#: The owning process exited without a terminal write; reconciliation under the
#: lock recorded it. 'interrupted' stays resumable.
INTERRUPTED = "interrupted"

TERMINAL_CODES = frozenset({
    COMPLETED, BUDGET_TOOLS, BUDGET_USD, BUDGET_MINUTES, BUDGET_LLM,
    STEP_FAILED, EVIDENCE_INCOMPLETE, CANCELLED, ERROR, INTERRUPTED,
})

#: The one vocabulary for budget stop texts: `budget_stop_text` writes them and
#: `code_for_stop_reason` reads them, so the two cannot drift apart.
_BUDGET_FIELD = {
    BUDGET_TOOLS: "max_tool_calls",
    BUDGET_USD: "max_usd",
    BUDGET_MINUTES: "max_minutes",
    BUDGET_LLM: "max_llm_usd",
}
_BUDGET_PREFIXES = tuple((f"{field}=", code) for code, field in _BUDGET_FIELD.items())


def budget_stop_text(code: str, limit: Any, note: str | None = None) -> str:
    """The stop_reason recorded for a budget stop, e.g. `max_usd=0.5`."""
    text = f"{_BUDGET_FIELD[code]}={limit}"
    return f"{text} ({note})" if note else text


def code_for_stop_reason(stop_reason: str | None) -> str:
    """The terminal code of a run that reached the writer.

    The execution engine records why it stopped as a `stop_reason` string:
    budget stops start with the budget name (`_budget_stop_reason`), every
    other stop is a hard step failure or a worker crash. No stop reason means
    every step ran — a resumed run may still be `partial` because completed
    on_error_skip steps keep their disclosures, but nothing stopped it.
    """
    if stop_reason is None:
        return COMPLETED
    for prefix, code in _BUDGET_PREFIXES:
        if stop_reason.startswith(prefix):
            return code
    return STEP_FAILED
