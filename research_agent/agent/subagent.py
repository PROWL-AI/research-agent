"""Research sub-agents: parallel workers with a hard compression boundary.

Design rule (from the knowledge pack): a worker owns a contiguous slice of the
plan's data steps, executes them with its own LLM extraction calls, and the
ONLY things that cross back into shared state are ledger claims, raw-artifact
files on disk, and a compact per-step summary. Raw tool payloads never
accumulate in the lead's context — compression is not a summary the worker
writes home, it is the shape of what it is allowed to return.

Workers are cooperative, not isolated processes: they share the run's
``Checkpoint``, ``ArtifactStore``, ``Ledger`` and ``ProwlClient`` on one event
loop. Budget checks are advisory under concurrency — two workers can both pass
``_budget_stop_reason`` before either increments the counter, overshooting
``max_tool_calls`` by at most ``workers - 1`` calls; ``max_usd`` is checked
against the client's server-reported cost, which lags by in-flight calls.
Both are documented tolerances, not silent overspend: the stop lands on the
next check after any worker crosses.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from pydantic import BaseModel, Field

from research_agent.agent.orchestrator import PlanItem, TRANSFORM_TOOLS
from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import ArtifactStore, Checkpoint

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
    index: int
    step: str
    tool: str
    status: str  # done | skipped | failed
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
    extract_claims: Callable[[PlanItem, Any, Any, Ledger], Awaitable[int]] = field(
        repr=False, default=None  # wired by the lead; None only in tests that stub it
    )


def partition_workers(
    items: list[tuple[int, PlanItem]], n_workers: int
) -> list[list[tuple[int, PlanItem]]]:
    """Split a data segment into at most ``n_workers`` contiguous chunks.

    Contiguity keeps per-entity steps (one competitor's block) on one worker,
    so a worker's extraction calls see related artifacts together.
    """
    if n_workers <= 1 or len(items) <= 1:
        return [items]
    n = min(n_workers, len(items))
    base, extra = divmod(len(items), n)
    chunks: list[list[tuple[int, PlanItem]]] = []
    start = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        chunks.append(items[start : start + size])
        start += size
    return [chunk for chunk in chunks if chunk]


def split_segments(
    plan: list[PlanItem], completed: set[int]
) -> list[tuple[str, list[tuple[int, PlanItem]]]]:
    """Partition the remaining plan into ordered segments.

    Data steps between two transforms run concurrently; a transform is always
    its own segment and runs on the lead AFTER the whole preceding data
    segment finished — its "recent artifacts" context is deterministic again
    at that boundary.
    """
    segments: list[tuple[str, list[tuple[int, PlanItem]]]] = []
    pending: list[tuple[int, PlanItem]] = []
    for index, item in enumerate(plan):
        if index in completed:
            continue
        if item.tool.lower() in TRANSFORM_TOOLS:
            if pending:
                segments.append(("data", pending))
                pending = []
            segments.append(("transform", [(index, item)]))
        else:
            pending.append((index, item))
    if pending:
        segments.append(("data", pending))
    return segments


def _safe_save(checkpoint: Checkpoint, store: ArtifactStore, ledger: Ledger | None = None) -> None:
    """Persistence must not kill a worker: a disk error is logged and the run
    continues in memory — the alternative is one OSError wiping out every
    other worker's evidence via the gather boundary."""
    try:
        store.save_checkpoint(checkpoint)
    except Exception as exc:  # noqa: BLE001 — see docstring
        log.error("checkpoint save failed (continuing in memory): %s", exc)
    if ledger is not None:
        try:
            ledger.save()
        except Exception as exc:  # noqa: BLE001
            log.error("ledger save failed (continuing in memory): %s", exc)


async def run_worker(worker_id: int, items: list[tuple[int, PlanItem]], ctx: WorkerContext) -> WorkerSummary:
    """Execute one worker's slice. Never raises on content or tool grounds: a
    hard failure stops this worker (its remaining steps become skipped), marks
    the run partial, and leaves the other workers to finish — one dead worker
    must not cost the run the evidence the others already gathered."""
    summary = WorkerSummary(worker_id=worker_id)
    checkpoint = ctx.checkpoint
    for position, (index, item) in enumerate(items):
        stop_reason = ctx.orch._budget_stop_reason(ctx.budget, checkpoint)
        if stop_reason is not None:
            for j, rest in items[position:]:
                checkpoint.skipped_steps.append(
                    {"index": j, "step": rest.step, "tool": rest.tool, "reason": stop_reason}
                )
                checkpoint.completed_steps.append(j)
                summary.outcomes.append(
                    StepOutcome(index=j, step=rest.step, tool=rest.tool, status="skipped", note=stop_reason)
                )
            checkpoint.partial = True
            checkpoint.stop_reason = checkpoint.stop_reason or stop_reason
            _safe_save(checkpoint, ctx.store)
            log.warning("worker %d: budget exhausted (%s), %d step(s) skipped", worker_id, stop_reason, len(items) - position)
            return summary

        log.info("worker %d: step %d %s (%s)", worker_id, index, item.step, item.tool)
        try:
            result = await ctx.orch.prowl.call_tool(item.tool, item.arguments)
        except Exception as exc:
            # Failed dispatches are billed by the server — they spend the
            # tool-call budget even though they produce no data.
            checkpoint.counters["attempted_calls"] = checkpoint.counters.get("attempted_calls", 0) + 1
            if item.on_error_skip:
                log.warning("worker %d: step %d failed (on_error_skip): %s", worker_id, index, exc)
                checkpoint.skipped_steps.append(
                    {"index": index, "step": item.step, "tool": item.tool, "reason": str(exc)[:200]}
                )
                checkpoint.completed_steps.append(index)
                _safe_save(checkpoint, ctx.store)
                summary.outcomes.append(
                    StepOutcome(index=index, step=item.step, tool=item.tool, status="skipped", note=str(exc)[:120])
                )
                continue
            reason = f"step '{item.step}' failed: {exc}"
            checkpoint.partial = True
            checkpoint.stop_reason = checkpoint.stop_reason or reason
            # The failed step itself is NOT marked completed: a transient
            # error above the client's retries stays resumable. The steps
            # after it are — re-running them would double-bill.
            checkpoint.skipped_steps.append(
                {"index": index, "step": item.step, "tool": item.tool, "reason": reason}
            )
            summary.outcomes.append(
                StepOutcome(index=index, step=item.step, tool=item.tool, status="failed", note=str(exc)[:120])
            )
            for j, rest in items[position + 1:]:
                checkpoint.skipped_steps.append(
                    {"index": j, "step": rest.step, "tool": rest.tool, "reason": reason}
                )
                checkpoint.completed_steps.append(j)
                summary.outcomes.append(
                    StepOutcome(index=j, step=rest.step, tool=rest.tool, status="failed", note=str(exc)[:120])
                )
            _safe_save(checkpoint, ctx.store)
            log.error("worker %d: hard failure at step %d, worker stops: %s", worker_id, index, exc)
            return summary

        checkpoint.counters["attempted_calls"] = checkpoint.counters.get("attempted_calls", 0) + 1
        checkpoint.counters["data_calls"] = checkpoint.counters.get("data_calls", 0) + 1
        if ctx.orch.prowl.cost_usd is not None:
            checkpoint.counters["cost_usd"] = ctx.orch.prowl.cost_usd
        else:
            # Server gave no billing data: accumulate the catalog price hint so
            # max_usd still means something and the report can say "estimated".
            price = ctx.orch.prowl.tool_prices.get(item.tool)
            if price is not None:
                checkpoint.counters["cost_estimate_usd"] = round(
                    checkpoint.counters.get("cost_estimate_usd", 0.0) + price, 6
                )
        try:
            raw_path = ctx.store.save_raw(index, item.tool, result)
        except Exception as exc:  # noqa: BLE001 — keep the step's data in memory
            log.error("worker %d: raw artifact save failed for step %d: %s", worker_id, index, exc)
            raw_path = ctx.store.raw_dir / f"{index:02d}_{item.tool}.json"
        claims_added = 0
        try:
            claims_added = await ctx.extract_claims(item, result, raw_path, ctx.ledger) or 0
        except Exception as exc:
            log.warning("worker %d: claim extraction failed for step %d: %s", worker_id, index, exc)
        _safe_save(checkpoint, ctx.store, ctx.ledger)

        checkpoint.completed_steps.append(index)
        summary.outcomes.append(
            StepOutcome(
                index=index, step=item.step, tool=item.tool, status="done",
                claims=claims_added,
            )
        )
    return summary


def _crash_summary(
    worker_id: int,
    chunk: list[tuple[int, PlanItem]],
    exc: BaseException,
    ctx: WorkerContext,
) -> WorkerSummary:
    """A worker that escaped its own guards becomes a failed summary — the
    crash must never take the whole segment (and every other worker's
    evidence) down with it."""
    log.error("worker %d crashed outside its guard: %s", worker_id, exc)
    ctx.checkpoint.partial = True
    ctx.checkpoint.stop_reason = ctx.checkpoint.stop_reason or f"worker {worker_id} crashed: {exc}"
    return WorkerSummary(
        worker_id=worker_id,
        outcomes=[
            StepOutcome(
                index=j, step=rest.step, tool=rest.tool, status="failed",
                note=f"worker crash: {str(exc)[:120]}",
            )
            for j, rest in chunk
            if j not in ctx.checkpoint.completed_steps
        ],
    )


async def run_data_segment(items: list[tuple[int, PlanItem]], ctx: WorkerContext, n_workers: int) -> list[WorkerSummary]:
    """Fan a data segment out to workers and merge their summaries. A worker
    that somehow still raises becomes a failed summary — it must never take
    the whole segment (and every other worker's evidence) down with it."""
    chunks = partition_workers(items, n_workers)
    if len(chunks) == 1:
        try:
            return [await run_worker(0, chunks[0], ctx)]
        except Exception as exc:  # noqa: BLE001 — same crash boundary as fan-out
            return [_crash_summary(0, chunks[0], exc, ctx)]
    log.info("data segment: %d steps across %d workers", len(items), len(chunks))
    results = await asyncio.gather(
        *(run_worker(worker_id, chunk, ctx) for worker_id, chunk in enumerate(chunks)),
        return_exceptions=True,
    )
    summaries: list[WorkerSummary] = []
    for worker_id, outcome in enumerate(results):
        if isinstance(outcome, BaseException):
            summaries.append(_crash_summary(worker_id, chunks[worker_id], outcome, ctx))
        else:
            summaries.append(outcome)
    return summaries
