"""Checkpoint version 1 → version 2 (docs/specs/2026-10-11-waves-canvas.md §2 N-STATE).

Version 1 identified a step by its index in a plan that was re-validated on every
attempt (KA-03), kept one flat `completed_steps` set that also held never-started
and budget-skipped steps (KA-04), and run-level cost counters (KA-11/12). This
module maps such a checkpoint onto step records without guessing: where the old
state is ambiguous it refuses with `CheckpointMigrationError`, and the run is
reported as needing attention instead of being resumed.

Mapping rules:

* `plan` (already validated when it was planned) becomes one StepRecord per item,
  `raw_index` = its position. A `plan_drop` entry that names an item of `plan`
  means a later attempt re-filtered the plan against a changed catalog, so the
  completed indexes no longer line up with `plan` — **refused**.
* A completed index with a raw artifact (`NN_tool.json`, `NN_transform.md`) whose
  tool matches the step → `completed`, raw ref kept. A raw artifact naming a
  different tool → **refused**.
* A completed index with a runtime skip entry and no raw: an `on_error_skip`
  failure → `skipped_on_error`; a budget stop or the tail after a hard failure →
  `pending` (it was never dispatched).
* A completed index with neither raw nor skip entry → **refused** (evidence may have
  been lost by a failed write — KA-10).
* A non-completed index with a hard-failure skip entry → `failed` (resumable);
  otherwise `pending`.
* Cost counters become synthetic `v1:aggregate` attempts: one per attempted call,
  the run's server cost (or catalog estimate) on the first, so the tool-call and
  USD budgets see the same spend as before.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from research_agent.events import emit
from research_agent.evidence.store import (
    COMPLETED,
    FAILED,
    PENDING,
    SKIPPED_ON_ERROR,
    AttemptRecord,
    Checkpoint,
    CheckpointMigrationError,
    StepRecord,
    make_step_id,
)

if TYPE_CHECKING:
    from research_agent.evidence.store import ArtifactStore

log = logging.getLogger(__name__)

_TRANSFORM_TOOLS = frozenset({"transform", "llm_transform"})
_RAW_NAME = re.compile(r"^(\d+)_(.+?)(?:_\d+)?\.(json|md)$")
_BUDGET_PREFIXES = ("max_tool_calls=", "max_usd=", "max_minutes=")


def _raw_by_index(store: "ArtifactStore") -> dict[int, tuple[str, str]]:
    """index → (tool or 'transform', run-dir-relative ref) of v1 raw artifacts."""
    found: dict[int, tuple[str, str]] = {}
    if not store.raw_dir.is_dir():
        return found
    for path in sorted(store.raw_dir.iterdir()):
        match = _RAW_NAME.match(path.name)
        if match is None:
            continue
        index, tool = int(match.group(1)), match.group(2)
        found.setdefault(index, (tool, f"raw/{path.name}"))
    return found


def migrate_v1(data: dict[str, Any], store: "ArtifactStore") -> Checkpoint:
    run_id = str(data.get("run_id") or store.run_dir.name)
    try:
        checkpoint = _migrate(data, store, run_id)
    except CheckpointMigrationError as exc:
        emit(log, "checkpoint.migration_refused", logging.WARNING, run_id=run_id, reason=str(exc))
        raise
    emit(log, "checkpoint.migrated", run_id=run_id, steps=len(checkpoint.steps),
         attempts=len(checkpoint.attempts))
    return checkpoint


def _migrate(data: dict[str, Any], store: "ArtifactStore", run_id: str) -> Checkpoint:
    plan = [item for item in data.get("plan") or [] if isinstance(item, dict)]
    completed = {int(i) for i in data.get("completed_steps") or []}
    skipped = [s for s in data.get("skipped_steps") or [] if isinstance(s, dict)]
    planned = {(str(item.get("step")), str(item.get("tool"))) for item in plan}
    regrown = [
        s for s in skipped
        if s.get("kind") == "plan_drop" and (str(s.get("step")), str(s.get("tool"))) in planned
    ]
    if regrown:
        raise CheckpointMigrationError(
            f"run {run_id}: a resume re-filtered the plan after it was made "
            f"({len(regrown)} planned step(s) dropped later), so completed step "
            "indexes no longer map to plan items — inspect the run, then start a new run_id"
        )
    runtime = {int(s["index"]): s for s in skipped
               if s.get("kind") != "plan_drop" and isinstance(s.get("index"), int)}
    raws = _raw_by_index(store)
    steps: list[StepRecord] = []
    for index, item in enumerate(plan):
        tool = str(item.get("tool") or "")
        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        kind = "transform" if tool.lower() in _TRANSFORM_TOOLS else "data"
        record = StepRecord(
            step_id=make_step_id(index, tool, arguments), raw_index=index, kind=kind,
            tool=tool, arguments=arguments, step=str(item.get("step") or ""),
            instruction=item.get("instruction"), on_error_skip=bool(item.get("on_error_skip")),
        )
        raw = raws.get(index)
        if raw is not None:
            expected = "transform" if kind == "transform" else tool
            if raw[0] != expected:
                raise CheckpointMigrationError(
                    f"run {run_id}: raw artifact {raw[1]} names tool '{raw[0]}' but plan step "
                    f"{index} is '{expected}' — indexes shifted between attempts"
                )
        skip = runtime.get(index)
        reason = str(skip.get("reason") or "") if skip else ""
        hard_tail = reason.startswith("step '") or reason.startswith("worker crash")
        if index in completed:
            if raw is not None:
                record.state = COMPLETED
                record.raw_ref = raw[1]
                record.extraction = {"status": "ok", "error": None, "claim_ids": [],
                                     "note": "migrated from v1"}
            elif skip is not None:
                if record.on_error_skip and not hard_tail and not reason.startswith(_BUDGET_PREFIXES):
                    record.state, record.reason = SKIPPED_ON_ERROR, reason or "failed (on_error_skip)"
                else:
                    record.state = PENDING  # never dispatched: budget stop or post-failure tail
            else:
                raise CheckpointMigrationError(
                    f"run {run_id}: step {index} ({tool}) is recorded completed but has no raw "
                    "artifact and no skip entry — its evidence may have been lost"
                )
        elif skip is not None and reason.startswith("step '") and not record.on_error_skip:
            record.state, record.reason = FAILED, reason
        steps.append(record)

    counters = data.get("counters") or {}
    attempted = int(counters.get("attempted_calls", counters.get("data_calls", 0)) or 0)
    cost = counters.get("cost_usd")
    estimate = counters.get("cost_estimate_usd")
    if cost is not None:
        basis, first_actual, first_estimate = "actual", float(cost), None
    elif estimate is not None:
        basis, first_actual, first_estimate = "estimate", None, float(estimate)
    else:
        basis, first_actual, first_estimate = "unknown", None, None  # v1 recorded no cost
    attempts = []
    for n in range(attempted):
        first = n == 0
        attempts.append(AttemptRecord(
            attempt_id=f"v1-{n}", step_id="v1:aggregate", kind="tool", attempt_no=n + 1,
            outcome="ok", cost_basis=basis,
            # The run total sits on the first synthetic attempt; the rest carry
            # zero so the total is counted once and the call count stays right.
            actual_usd=(first_actual if first else (0.0 if basis == "actual" else None)),
            estimate_usd=(first_estimate if first else (0.0 if basis != "actual" else None)),
        ))
    return Checkpoint(
        run_id=run_id, runbook=str(data.get("runbook") or ""), status=str(data.get("status") or "running"),
        created_at=data.get("created_at") or data.get("updated_at") or Checkpoint.model_fields["created_at"].default_factory(),
        updated_at=data.get("updated_at") or data.get("created_at") or Checkpoint.model_fields["updated_at"].default_factory(),
        brief=data.get("brief") or {}, plan_raw=plan, steps=steps, attempts=attempts,
        transform_notes=list(data.get("transform_notes") or []), stats=data.get("stats") or {},
        partial=bool(data.get("partial")), stop_reason=data.get("stop_reason"),
        terminal_code=data.get("terminal_code"), migrated_from=1,
    )
