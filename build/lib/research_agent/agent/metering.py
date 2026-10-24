"""One way to put a run under its LLM ceiling — the run and `rewrite` share it."""

from __future__ import annotations

import logging
from typing import Any

from research_agent.config import resolve_llm_cap, writer_reserve
from research_agent.events import emit
from research_agent.evidence.store import ArtifactStore, AttemptRecord, Checkpoint
from research_agent.llm import LlmMeter

log = logging.getLogger(__name__)


def attach_run_meter(llm: Any, checkpoint: Checkpoint, store: ArtifactStore,
                     runbook_cap: float | None, explicit: float | None) -> LlmMeter:
    """Resolve the cap (config.resolve_llm_cap), record it on the checkpoint and
    attach a meter over the checkpoint's attempt ledger to `llm`. The caller
    detaches it (`llm.meter = None`) when the run or rewrite ends."""
    cap, source = resolve_llm_cap(explicit, checkpoint.llm_cap_usd, runbook_cap)
    checkpoint.llm_cap_usd = cap
    counter = {"n": sum(1 for a in checkpoint.attempts if a.kind == "llm")}

    def new_id() -> str:
        counter["n"] += 1
        return f"llm#{counter['n']}"

    meter = LlmMeter(max_usd=cap, reserve_usd=writer_reserve(cap), attempts=checkpoint.attempts,
                     persist=lambda: store.save_checkpoint(checkpoint), record_type=AttemptRecord,
                     new_id=new_id)
    llm.meter = meter
    emit(log, "llm.budget", run_id=checkpoint.run_id, max_llm_usd=cap, source=source,
         reserve_usd=meter.reserve_usd, spent_usd=meter.spend())
    return meter


def budget_stats(meter: LlmMeter, checkpoint: Checkpoint) -> dict[str, Any]:
    return {
        "max_llm_usd": meter.max_usd,
        "writer_reserve_usd": meter.reserve_usd,
        "spend_usd": meter.spend(),
        "cost_source": checkpoint.cost_source("llm"),
        "attempts": sum(1 for a in checkpoint.attempts if a.kind == "llm"),
        "refused_stages": list(meter.refusals),
    }
