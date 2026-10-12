"""Research sub-agents: parallel workers with a hard compression boundary.

Design rule (from the knowledge pack): a worker owns a contiguous slice of the
plan's data steps, executes them with its own LLM extraction calls, and the
ONLY things that cross back into shared state are ledger claims, raw-artifact
files on disk, and a compact per-step summary. Raw tool payloads never
accumulate in the lead's context — compression is not a summary the worker
writes home, it is the shape of what it is allowed to return.

Workers are cooperative, not isolated processes: they share the run's
``Checkpoint``, ``ArtifactStore``, ``Ledger`` and ``ProwlClient`` on one event
loop. Every dispatch is an ``AttemptRecord`` appended (and saved) BEFORE the call
and finalized in a ``finally`` block, so the tool-call budget counts in-flight
calls and a billed failure or a cancellation never loses its cost. The USD check
still lags by the in-flight calls' unknown cost (each counts at its estimate);
the stop lands on the next check after any worker crosses.

Durable order per step (docs/specs/2026-10-11-waves-canvas.md §2 N-STATE):
attempt + ``dispatching`` → dispatch → attempt finalized → atomic raw write
(``raw_saved``) → extraction → ledger save → ``completed``. A crash at any point
leaves a state a resume can act on without paying twice for saved evidence.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from pydantic import BaseModel, Field

from research_agent.agent.orchestrator import PlanItem
from research_agent.events import emit
from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import (
    COMPLETED,
    DISPATCHING,
    FAILED,
    OUTCOME_UNKNOWN,
    RAW_SAVED,
    SETTLED_STATES,
    SKIPPED_BUDGET,
    SKIPPED_ON_ERROR,
    ArtifactStore,
    AttemptRecord,
    Checkpoint,
    StepRecord,
)
from research_agent.prowl_client import ToolCallError

if TYPE_CHECKING:
    from research_agent.agent.orchestrator import Orchestrator

log = logging.getLogger(__name__)

#: Effort classes (plan, decision 2): lookup = one inline agent, comparison =
#: a few workers, deep = a wide fan-out. Worker counts are deliberately modest:
#: every worker's data call hits the same billed Prowl account.
EFFORT_WORKERS = {"lookup": 1, "comparison": 3, "deep": 5}


def effort_for(max_tool_calls: int, declared: str | None = None) -> str:
    """Resolve the run's effort class: the runbook's explicit ``effort`` wins,
    otherwise it is derived from the tool-call budget (<=15 lookup, <=45
    comparison, above that deep)."""
    if declared in EFFORT_WORKERS:
        return declared
    if max_tool_calls <= 15:
        return "lookup"
    if max_tool_calls <= 45:
        return "comparison"
    return "deep"


class StepOutcome(BaseModel):
    step_id: str
    step: str
    tool: str
    status: str  # done | skipped | failed | pending
    claims: int = 0
    note: str = ""


class WorkerSummary(BaseModel):
    worker_id: int
    outcomes: list[StepOutcome] = Field(default_factory=list)

    @property
    def claims_added(self) -> int:
        return sum(o.claims for o in self.outcomes)

    @property
    def done(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "done")


@dataclass
class WorkerContext:
    """Everything a worker may touch — assembled once by the lead."""

    orch: "Orchestrator"
    checkpoint: Checkpoint
    store: ArtifactStore
    ledger: Ledger
    budget: Any
    extract_claims: Callable[..., Awaitable[int]] = field(
        repr=False, default=None  # wired by the lead; None only in tests that stub it
    )


class CheckpointWriteError(Exception):
    """The run's state could not be persisted. Not a step failure: continuing
    would spend money no checkpoint records, so the run stops as `failed`."""


def partition_workers(items: list[StepRecord], n_workers: int) -> list[list[StepRecord]]:
    """Split a data segment into at most ``n_workers`` contiguous chunks.

    Contiguity keeps per-entity steps (one competitor's block) on one worker,
    so a worker's extraction calls see related artifacts together.
    """
    if n_workers <= 1 or len(items) <= 1:
        return [items]
    n = min(n_workers, len(items))
    base, extra = divmod(len(items), n)
    chunks: list[list[StepRecord]] = []
    start = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        chunks.append(items[start : start + size])
        start += size
    return [chunk for chunk in chunks if chunk]


def split_segments(steps: list[StepRecord]) -> list[tuple[str, list[StepRecord]]]:
    """Partition the steps still to run into ordered segments.

    Settled steps (completed, skipped, excluded) never run again. Data steps
    between two transforms run concurrently; a transform is always its own
    segment and runs on the lead AFTER the whole preceding data segment
    finished — its "recent artifacts" context is deterministic at that boundary.
    """
    segments: list[tuple[str, list[StepRecord]]] = []
    pending: list[StepRecord] = []
    for record in steps:
        if record.state in SETTLED_STATES:
            continue
        if record.kind == "transform":
            if pending:
                segments.append(("data", pending))
                pending = []
            segments.append(("transform", [record]))
        else:
            pending.append(record)
    if pending:
        segments.append(("data", pending))
    return segments


def save_state(checkpoint: Checkpoint, store: ArtifactStore, ledger: Ledger | None = None) -> None:
    """Persist the run's state; a failure is CheckpointWriteError, never
    swallowed — money spent after an unrecorded state is money nobody can see."""
    try:
        if ledger is not None:
            ledger.save()
        store.save_checkpoint(checkpoint)
    except Exception as exc:  # noqa: BLE001 — re-raised typed
        raise CheckpointWriteError(f"run state could not be saved: {exc}") from exc


def _set_state(checkpoint: Checkpoint, record: StepRecord, state: str, reason: str | None = None) -> None:
    previous = record.state
    record.state = state
    if reason is not None:
        record.reason = reason[:300]
    emit(log, "step.state", run_id=checkpoint.run_id, step_id=record.step_id,
         tool=record.tool, **{"from": previous, "to": state})


def plan_item(record: StepRecord) -> PlanItem:
    return PlanItem(step=record.step, tool=record.tool, arguments=record.arguments,
                    instruction=record.instruction, on_error_skip=record.on_error_skip)


def _estimate_usd(ctx: WorkerContext, tool: str) -> tuple[float | None, str]:
    """(estimate, basis) for an attempt without a server-reported cost: the
    catalog price, else the runbook's per-call share of max_usd — never zero."""
    price = (getattr(ctx.orch.prowl, "tool_prices", None) or {}).get(tool)
    if price is not None:
        return float(price), "estimate"
    budget = ctx.budget
    if budget is not None and getattr(budget, "max_tool_calls", 0):
        return round(float(budget.max_usd) / max(int(budget.max_tool_calls), 1), 6), "unknown"
    return None, "unknown"


def _new_attempt(ctx: WorkerContext, record: StepRecord) -> AttemptRecord:
    checkpoint = ctx.checkpoint
    previous = [a for a in checkpoint.attempts if a.step_id == record.step_id]
    if record.state == OUTCOME_UNKNOWN and previous:
        # The same logical attempt, re-sent with the same key so the server can
        # replay it: one record, counted once against the budget. A cost it
        # already reported is kept.
        attempt = previous[-1]
        attempt.outcome, attempt.ended_at = "pending", None
        return attempt
    attempt_no = (previous[-1].attempt_no + 1) if previous else 1
    estimate, _ = _estimate_usd(ctx, record.tool)
    # A step migrated from v1 whose dispatch may have reached the server is
    # first re-sent under its v1 key, so the server can still match it.
    key = record.legacy_key if (record.legacy_key and not previous) else \
        f"{checkpoint.run_id}:{record.step_id}:{attempt_no}"
    attempt = AttemptRecord(
        attempt_id=f"{record.step_id}#{len(previous) + 1}", step_id=record.step_id,
        kind="tool", attempt_no=attempt_no, idempotency_key=key,
        estimate_usd=estimate,
    )
    checkpoint.attempts.append(attempt)
    record.attempt_ids.append(attempt.attempt_id)
    return attempt


def _finish_attempt(ctx: WorkerContext, attempt: AttemptRecord, outcome: str,
                    cost: float | None, tool: str) -> None:
    attempt.outcome = outcome
    attempt.ended_at = datetime.now(timezone.utc).isoformat()
    if cost is not None:
        attempt.actual_usd, attempt.cost_basis = float(cost), "actual"
    elif attempt.actual_usd is None:
        # A resend that reports nothing keeps a cost reported earlier.
        _, basis = _estimate_usd(ctx, tool)
        attempt.cost_basis = basis
    emit(log, "attempt.finished", run_id=ctx.checkpoint.run_id, attempt_id=attempt.attempt_id,
         outcome=outcome, basis=attempt.cost_basis, actual_usd=attempt.actual_usd,
         estimate_usd=attempt.estimate_usd)


def _reported_cost(prowl: Any, key: str, before: float | None, exc: BaseException | None = None) -> float | None:
    """The billed cost of one dispatch: the error's own cost, else the client's
    per-key record, else (single-worker fakes) the change in its running total."""
    if exc is not None and getattr(exc, "cost_usd", None) is not None:
        return exc.cost_usd
    by_key = getattr(prowl, "cost_by_key", None)
    if isinstance(by_key, dict) and key in by_key:
        return by_key[key]
    after = getattr(prowl, "cost_usd", None)
    if after is not None and after != before:
        return round(after - (before or 0.0), 6)
    return None


async def extract_step(ctx: WorkerContext, record: StepRecord, result: Any | None) -> int:
    """Extraction for a step whose raw is saved; reads the raw from disk when
    the in-memory result is gone (resume). Marks completed only after the
    ledger is saved. Never dispatches."""
    checkpoint = ctx.checkpoint
    if result is None:
        text = ctx.store.read_artifact(record.raw_ref, record.raw_sha256)
        result = json.loads(text) if record.raw_ref.endswith(".json") else text
    # Claims of an earlier extraction of this step are replaced: found by the
    # ids the step recorded AND by their raw ref — a crash between the ledger
    # save and the checkpoint save leaves claims the step never recorded.
    stale = set(record.extraction.get("claim_ids") or [])
    raw_name = Path(record.raw_ref).name  # v1 claims carry cwd-relative or absolute refs
    stale |= {c.id for c in ctx.ledger.claims if c.raw_ref and Path(c.raw_ref).name == raw_name}
    ctx.ledger.remove_ids(sorted(stale))
    before_ids = {c.id for c in ctx.ledger.claims}
    try:
        added = await ctx.extract_claims(
            plan_item(record), result, Path(record.raw_ref), ctx.ledger, record.step_id
        ) or 0
    except Exception as exc:  # noqa: BLE001 — typed into the step, not swallowed
        record.extraction = {"status": "failed", "error": str(exc)[:300], "claim_ids": []}
        emit(log, "evidence.incomplete", logging.WARNING, run_id=checkpoint.run_id,
             step_id=record.step_id, reason="extraction", error=exc)
        save_state(checkpoint, ctx.store)
        return 0
    claim_ids = [c.id for c in ctx.ledger.claims if c.id not in before_ids]
    record.extraction = {"status": "ok" if added else "empty", "error": None, "claim_ids": claim_ids}
    _set_state(checkpoint, record, COMPLETED)
    save_state(checkpoint, ctx.store, ctx.ledger)
    return added


async def run_worker(worker_id: int, items: list[StepRecord], ctx: WorkerContext) -> WorkerSummary:
    """Execute one worker's slice. A hard failure stops this worker — its
    never-started steps stay `pending` (a resume runs them) — marks the run
    partial and leaves the other workers to finish."""
    summary = WorkerSummary(worker_id=worker_id)
    checkpoint = ctx.checkpoint
    for position, record in enumerate(items):
        if record.state == RAW_SAVED:
            # Paid for already: finish the evidence from the saved raw, no dispatch.
            claims = await extract_step(ctx, record, None)
            summary.outcomes.append(StepOutcome(step_id=record.step_id, step=record.step, tool=record.tool,
                                                status="done" if record.state == COMPLETED else "failed",
                                                claims=claims))
            continue

        stop_reason = ctx.orch._budget_stop_reason(ctx.budget, checkpoint)
        if stop_reason is not None:
            for rest in items[position:]:
                # outcome_unknown keeps its state so its next send reuses the key.
                if rest.state not in SETTLED_STATES and rest.state not in (RAW_SAVED, OUTCOME_UNKNOWN):
                    _set_state(checkpoint, rest, SKIPPED_BUDGET, stop_reason)
                    summary.outcomes.append(StepOutcome(step_id=rest.step_id, step=rest.step,
                                                        tool=rest.tool, status="skipped", note=stop_reason))
            checkpoint.partial = True
            checkpoint.stop_reason = checkpoint.stop_reason or stop_reason
            emit(log, "budget.stop", logging.WARNING, run_id=checkpoint.run_id, reason=stop_reason,
                 spend_usd=checkpoint.spend_usd("tool"))
            save_state(checkpoint, ctx.store)
            return summary

        attempt = _new_attempt(ctx, record)
        _set_state(checkpoint, record, DISPATCHING)
        save_state(checkpoint, ctx.store)
        emit(log, "attempt.started", run_id=checkpoint.run_id, attempt_id=attempt.attempt_id,
             step_id=record.step_id, tool=record.tool, attempt_no=attempt.attempt_no)
        before = getattr(ctx.orch.prowl, "cost_usd", None)
        try:
            result = await ctx.orch.prowl.call_tool(
                record.tool, record.arguments, idempotency_key=attempt.idempotency_key,
            )
        except asyncio.CancelledError as exc:
            # The call may have reached the server: the next attempt re-sends the
            # same key so the server can replay instead of billing twice.
            _finish_attempt(ctx, attempt, "cancelled",
                            _reported_cost(ctx.orch.prowl, attempt.idempotency_key, before, exc), record.tool)
            _set_state(checkpoint, record, OUTCOME_UNKNOWN, "cancelled during dispatch")
            save_state(checkpoint, ctx.store)
            raise
        except Exception as exc:
            # A refusal the server (or a local pre-dispatch limit) decided is
            # definite; a timeout or transport failure may have executed.
            definite = isinstance(exc, ToolCallError)
            _finish_attempt(ctx, attempt, "refused" if definite else "transport_error",
                            _reported_cost(ctx.orch.prowl, attempt.idempotency_key, before, exc), record.tool)
            if record.on_error_skip:
                log.warning("worker %d: step %s failed (on_error_skip): %s", worker_id, record.step_id, exc)
                _set_state(checkpoint, record, SKIPPED_ON_ERROR, str(exc))
                save_state(checkpoint, ctx.store)
                summary.outcomes.append(StepOutcome(step_id=record.step_id, step=record.step,
                                                    tool=record.tool, status="skipped", note=str(exc)[:120]))
                continue
            reason = f"step '{record.step}' failed: {exc}"
            # A refusal is a definite outcome (a resume tries again with a new
            # attempt number); a transport error may have executed server-side
            # (a resume re-sends the same key).
            _set_state(checkpoint, record, FAILED if definite else OUTCOME_UNKNOWN, reason)
            checkpoint.partial = True
            checkpoint.stop_reason = checkpoint.stop_reason or reason
            save_state(checkpoint, ctx.store)
            summary.outcomes.append(StepOutcome(step_id=record.step_id, step=record.step,
                                                tool=record.tool, status="failed", note=str(exc)[:120]))
            for rest in items[position + 1:]:
                summary.outcomes.append(StepOutcome(step_id=rest.step_id, step=rest.step,
                                                    tool=rest.tool, status="pending", note="never started"))
            log.error("worker %d: hard failure at step %s, worker stops: %s", worker_id, record.step_id, exc)
            return summary

        _finish_attempt(ctx, attempt, "ok",
                        _reported_cost(ctx.orch.prowl, attempt.idempotency_key, before), record.tool)
        save_state(checkpoint, ctx.store)
        try:
            record.raw_ref, record.raw_sha256 = ctx.store.save_raw(record.step_id, record.tool, result)
        except Exception as exc:  # noqa: BLE001 — typed into the step
            # The data was paid for but cannot be kept. An optional step is
            # skipped (a resume does not pay for it again); a required one is
            # `failed` and a resume fetches it again — a new, paid call.
            _set_state(checkpoint, record, SKIPPED_ON_ERROR if record.on_error_skip else FAILED,
                       f"raw_write: {exc}")
            checkpoint.partial = True
            emit(log, "evidence.incomplete", logging.WARNING, run_id=checkpoint.run_id,
                 step_id=record.step_id, reason="raw_write", error=exc)
            save_state(checkpoint, ctx.store)
            summary.outcomes.append(StepOutcome(step_id=record.step_id, step=record.step,
                                                tool=record.tool, status="failed", note="raw write failed"))
            continue
        _set_state(checkpoint, record, RAW_SAVED)
        save_state(checkpoint, ctx.store)
        claims = await extract_step(ctx, record, result)
        summary.outcomes.append(StepOutcome(
            step_id=record.step_id, step=record.step, tool=record.tool,
            status="done" if record.state == COMPLETED else "failed", claims=claims,
        ))
    return summary


def _crash_summary(
    worker_id: int,
    chunk: list[StepRecord],
    exc: BaseException,
    ctx: WorkerContext,
) -> WorkerSummary:
    """A worker that escaped its own guards becomes a failed summary — the
    crash must never take the whole segment (and every other worker's
    evidence) down with it. Its unreached steps keep their state (a resume
    runs them); a step caught mid-dispatch becomes outcome_unknown."""
    log.error("worker %d crashed outside its guard: %s", worker_id, exc)
    checkpoint = ctx.checkpoint
    checkpoint.partial = True
    checkpoint.stop_reason = checkpoint.stop_reason or f"worker {worker_id} crashed: {exc}"
    for record in chunk:
        if record.state == DISPATCHING:
            _set_state(checkpoint, record, OUTCOME_UNKNOWN, f"worker crash: {str(exc)[:120]}")
    save_state(checkpoint, ctx.store)
    return WorkerSummary(
        worker_id=worker_id,
        outcomes=[
            StepOutcome(step_id=r.step_id, step=r.step, tool=r.tool, status="failed",
                        note=f"worker crash: {str(exc)[:120]}")
            for r in chunk if r.state not in SETTLED_STATES
        ],
    )


async def run_data_segment(items: list[StepRecord], ctx: WorkerContext, n_workers: int) -> list[WorkerSummary]:
    """Fan a data segment out to workers and merge their summaries. A worker
    that somehow still raises becomes a failed summary — it must never take
    the whole segment (and every other worker's evidence) down with it."""
    chunks = partition_workers(items, n_workers)
    if len(chunks) == 1:
        try:
            return [await run_worker(0, chunks[0], ctx)]
        except CheckpointWriteError:
            raise
        except Exception as exc:  # noqa: BLE001 — same crash boundary as fan-out
            return [_crash_summary(0, chunks[0], exc, ctx)]
    log.info("data segment: %d steps across %d workers", len(items), len(chunks))
    results = await asyncio.gather(
        *(run_worker(worker_id, chunk, ctx) for worker_id, chunk in enumerate(chunks)),
        return_exceptions=True,
    )
    summaries: list[WorkerSummary] = []
    for outcome in results:
        if isinstance(outcome, (CheckpointWriteError, asyncio.CancelledError)):
            raise outcome
    for worker_id, outcome in enumerate(results):
        if isinstance(outcome, BaseException):
            summaries.append(_crash_summary(worker_id, chunks[worker_id], outcome, ctx))
        else:
            summaries.append(outcome)
    return summaries
