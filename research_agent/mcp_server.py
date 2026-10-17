"""FastMCP stdio server: the legacy local MCP surface.

The Fabric bundle does NOT point here: `fabric-agent.json` declares the HTTP
service (`research_agent.service`, connection `http://127.0.0.1:18764/mcp`).
This stdio server stays for local MCP clients that launch a process.

Tools: research.run, research.list_runbooks, research.get_status,
research.get_report. Keys (PROWL_API_KEY / LLM keys) are read from the
server process env; only research.run needs them.

Run lifecycle state is written only by the run's owner — the process holding
the run's lock (`Orchestrator.run`). The handlers here report outcomes; the
startup reconciliation takes each run's lock before marking it interrupted.

Runs live under RESEARCH_RUNS_DIR (default ./runs relative to the server
process CWD — set it explicitly in the MCP client config when the host
launches the server from another directory).
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from research_agent.agent.orchestrator import (
    InputError,
    Orchestrator,
    OrchestratorError,
    RunResult,
    build_brief,
)
from research_agent.config import Config, ConfigError
from research_agent.events import emit
from research_agent.evidence import terminal
from research_agent.evidence.runlock import is_locked_elsewhere, reconcile_orphans
from research_agent.evidence.store import ArtifactStore, CheckpointMigrationError, validate_run_id
from research_agent.llm import LLMClient
from research_agent.prowl_client import ProwlClient
from research_agent.runbook import RunbookError, get_runbook, list_runbooks

log = logging.getLogger(__name__)

TRACE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "research_trace_id", default=None
)

_base_record_factory = logging.getLogRecordFactory()


def _trace_record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _base_record_factory(*args, **kwargs)
    record.trace_id = TRACE_ID.get() or "-"
    return record


if not getattr(logging.getLogRecordFactory(), "_research_trace", False):
    _trace_record_factory._research_trace = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(_trace_record_factory)

mcp = FastMCP("prowl-research-agent")

_TASKS: dict[str, asyncio.Task] = {}

def _runs_root() -> Path:
    return Path(os.environ.get("RESEARCH_RUNS_DIR", "runs"))


def _config_from_env() -> Config:
    return Config.from_env()


def _make_prowl(config: Config) -> ProwlClient:
    return ProwlClient(api_key=config.prowl_api_key, mcp_url=config.prowl_mcp_url)


def _make_llm(config: Config) -> LLMClient:
    return LLMClient(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model_cheap=config.llm_model,
        model_strong=config.llm_model_strong,
    )


def _new_run_id(runbook_name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{runbook_name}-{uuid.uuid4().hex[:6]}"


def _validate_run_request(runbook: str, inputs: dict[str, Any]) -> None:
    try:
        rb = get_runbook(runbook)
    except RunbookError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be an object keyed by runbook input name")
    try:
        build_brief(rb, inputs)
    except InputError as exc:
        raise ValueError(str(exc)) from exc


async def _execute_run(
    runbook: str, inputs: dict[str, Any], run_id: str, trace_id: str | None
) -> RunResult:
    """Run one job and report its outcome. Writes nothing itself.

    The checkpoint — created before planning, and every terminal state of a
    run that got as far as taking its lock (cancelled → partial, exception →
    failed) — is written by `Orchestrator.run` under the run lock. A lock
    refusal writes nothing. A failure BEFORE the orchestrator is reached
    (config, client construction or connection) leaves no checkpoint at all:
    get_status then answers from the in-process task while it is still known
    (see `_status_dict`), and "unknown run_id" after that."""
    token = TRACE_ID.set(trace_id)
    try:
        emit(log, "mcp.run.accepted", run_id=run_id, runbook=runbook)
        config = _config_from_env()
        async with _make_prowl(config) as prowl, _make_llm(config) as llm:
            orchestrator = Orchestrator(prowl, llm, runs_root=_runs_root())
            result = await orchestrator.run(runbook, inputs, run_id=run_id)
        emit(
            log, "mcp.run.finished", run_id=run_id,
            status=result.status, terminal_code=result.terminal_code,
        )
        return result
    except asyncio.CancelledError:
        emit(log, "mcp.run.cancelled", logging.WARNING, run_id=run_id)
        raise
    except Exception as exc:
        emit(log, "mcp.run.failed", logging.ERROR, run_id=run_id, error=str(exc))
        raise
    finally:
        TRACE_ID.reset(token)


def _result_envelope(result: RunResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "report_path": result.report_path,
        "ledger_path": result.ledger_path,
        "stats": result.stats,
        "skipped_steps": result.skipped_steps,
        "terminal_code": result.terminal_code,
    }


@mcp.tool(name="research.run")
async def research_run(
    runbook: str,
    inputs: dict[str, Any],
    run_id: str | None = None,
    wait: bool = False,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Execute a research runbook. wait=false returns a job handle immediately."""
    _validate_run_request(runbook, inputs)
    try:
        _config_from_env()
    except ConfigError as exc:
        raise ValueError(f"research.run requires server-side keys: {exc}") from exc

    run_id = validate_run_id(run_id) if run_id else _new_run_id(runbook)
    # Reject a live duplicate before disk I/O can yield and let its task finish.
    # The second check below still protects two concurrent new submissions.
    if run_id in _TASKS and not _TASKS[run_id].done():
        raise ValueError(f"run '{run_id}' is already running in this server process")
    # A finished run_id on disk must be rejected before scheduling: the
    # orchestrator would refuse it anyway, and letting the failure surface
    # mid-task risks clobbering the finished run's checkpoint.
    try:
        existing = await asyncio.to_thread(
            ArtifactStore(_runs_root() / run_id).load_checkpoint
        )
    except CheckpointMigrationError as exc:
        raise ValueError(
            f"run '{run_id}' needs attention: {exc} — it is not resumed; start a new run_id"
        ) from exc
    except ValueError as exc:
        raise ValueError(f"run '{run_id}' checkpoint corrupt: {exc}") from exc
    if existing is not None and existing.runbook != runbook:
        raise ValueError(
            f"run '{run_id}' already belongs to runbook '{existing.runbook}'"
        )
    # Prune finished tasks so _TASKS does not grow for the server's lifetime.
    # From here to task registration there is no await: the duplicate check
    # and the registration are one atomic step on the event loop.
    for stale_id in [rid for rid, t in _TASKS.items() if t.done()]:
        _TASKS.pop(stale_id, None)
    if run_id in _TASKS and not _TASKS[run_id].done():
        raise ValueError(f"run '{run_id}' is already running in this server process")
    if existing is not None and existing.status == "complete":
        raise ValueError(
            f"run '{run_id}' already finished with status 'complete' — "
            "choose a new run_id"
        )
    # A run another process owns (a CLI run, another server) must be refused
    # here, synchronously: with wait=false the orchestrator's own refusal would
    # only reach this server's log, and the caller would be told "running".
    if await asyncio.to_thread(is_locked_elsewhere, _runs_root() / run_id):
        emit(log, "run.lock.refused", level=logging.WARNING, run_id=run_id, surface="mcp")
        raise OrchestratorError(f"run {run_id} is locked by another process")
    # running-without-a-live-task / partial / failed / interrupted with a
    # recorded plan: the orchestrator resumes from the checkpoint and
    # re-executes only the steps that never completed. Without a plan the run
    # died before planning finished — nothing was billed, so the orchestrator
    # re-plans over the empty run dir.

    if wait:
        current = asyncio.current_task()
        assert current is not None
        _TASKS[run_id] = current
        try:
            result = await _execute_run(runbook, inputs, run_id, trace_id)
        finally:
            _TASKS.pop(run_id, None)
        return _result_envelope(result)

    task = asyncio.create_task(_execute_run(runbook, inputs, run_id, trace_id))
    _TASKS[run_id] = task

    def _observe(done: asyncio.Task) -> None:
        # Retrieve the outcome: an unobserved task exception is an event-loop
        # warning AND a failure nobody recorded.
        if done.cancelled():
            log.warning("run %s task cancelled", run_id)
            return
        exc = done.exception()
        if exc is not None:
            log.error("run %s task failed: %s", run_id, exc)
        else:
            log.info("run %s task done", run_id)

    task.add_done_callback(_observe)
    return {"run_id": run_id, "status": "running"}


@mcp.tool(name="research.list_runbooks")
async def research_list_runbooks() -> list[dict[str, Any]]:
    """List available runbooks with their inputs and budgets. No keys required."""
    return [
        {
            "name": rb.name,
            "description": rb.meta.description.strip(),
            "version": rb.meta.version,
            "inputs": [spec.model_dump() for spec in rb.meta.inputs],
            "budget": rb.meta.budget.model_dump(),
        }
        for rb in list_runbooks()
    ]


def _pre_checkpoint_status(run_id: str, task: asyncio.Task) -> dict[str, Any]:
    """Status of a run this server accepted whose orchestrator never created a
    checkpoint (still constructing clients, or it failed / was cancelled
    before taking the run lock). Read from the in-process task — nothing is
    written; once the task is pruned the id answers "unknown run_id"."""
    status, partial, stop_reason, code = "running", False, None, None
    if task.done():
        if task.cancelled():
            status, partial, stop_reason, code = "partial", True, "cancelled", terminal.CANCELLED
        else:
            exc = task.exception()
            if exc is not None:
                status, stop_reason, code = "failed", str(exc)[:300], terminal.ERROR
    return {
        "run_id": run_id,
        "runbook": None,
        "status": status,
        "partial": partial,
        "stop_reason": stop_reason,
        "terminal_code": code,
        "orphaned": False,
        "active": not task.done(),
        "has_checkpoint": False,
        "planned_steps": 0,
        "step_counts": {},
        "completed_steps": [],
        "skipped_steps": [],
        "counters": {},
        "duration_s": None,
    }


def _needs_attention_status(run_id: str, exc: Exception) -> dict[str, Any]:
    """A version-1 checkpoint that cannot be migrated without guessing: the
    run is reported, its report stays readable, and it is never resumed."""
    import json as _json

    raw: dict[str, Any] = {}
    try:
        raw = _json.loads((_runs_root() / run_id / "checkpoint.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {
        "run_id": run_id, "runbook": raw.get("runbook"), "status": "needs_attention",
        "partial": bool(raw.get("partial")), "stop_reason": str(exc)[:300],
        "terminal_code": None, "orphaned": False, "active": False,
        "has_checkpoint": True, "planned_steps": len(raw.get("plan") or []),
        "step_counts": {}, "completed_steps": [], "skipped_steps": [],
        "counters": {}, "duration_s": None,
    }


def _status_dict(run_id: str) -> dict[str, Any]:
    """Status of a run from its checkpoint. A read: it never writes."""
    validate_run_id(run_id)
    try:
        checkpoint = ArtifactStore(_runs_root() / run_id).load_checkpoint()
    except CheckpointMigrationError as exc:
        # Readable, never resumed: the run's files stay as they are.
        return _needs_attention_status(run_id, exc)
    except ValueError as exc:
        log.error("run %s checkpoint corrupt: %s", run_id, exc)
        raise ValueError(f"run '{run_id}' checkpoint corrupt: {exc}") from exc
    if checkpoint is None:
        task = _TASKS.get(run_id)
        if task is not None:
            return _pre_checkpoint_status(run_id, task)
        raise ValueError(f"unknown run_id '{run_id}' (no checkpoint at runs/{run_id})")
    try:
        created = datetime.fromisoformat(checkpoint.created_at)
        updated = datetime.fromisoformat(checkpoint.updated_at)
        duration_s: float | None = round((updated - created).total_seconds(), 1)
    except ValueError:
        duration_s = None
    # A checkpoint left 'running' with no live task behind it (e.g. the server
    # restarted mid-run) is orphaned, not in progress.
    # Liveness is the run lock, not this process's task table: a run another
    # process is executing is active, never orphaned.
    task = _TASKS.get(run_id)
    live_here = task is not None and not task.done()
    active = live_here or is_locked_elsewhere(_runs_root() / run_id)
    orphaned = checkpoint.status == "running" and not active
    return {
        "run_id": run_id,
        "runbook": checkpoint.runbook,
        "status": checkpoint.status,
        "partial": checkpoint.partial,
        "stop_reason": checkpoint.stop_reason,
        "terminal_code": checkpoint.terminal_code,
        "orphaned": orphaned,
        "active": active,
        "has_checkpoint": True,
        "planned_steps": checkpoint.planned_steps,
        "step_counts": checkpoint.step_counts(),
        "completed_steps": checkpoint.completed_steps,
        "skipped_steps": checkpoint.skipped_steps,
        "counters": dict(checkpoint.counters),  # a MappingProxyType does not serialize over MCP
        "duration_s": duration_s,
    }


@mcp.tool(name="research.get_status")
async def research_get_status(run_id: str) -> dict[str, Any]:
    """Status of a run: from its checkpoint (steps, counters, duration, terminal_code,
    active = some process holds the run lock), or — before a checkpoint exists — from
    this server's in-process job (has_checkpoint=false: still starting, or failed /
    cancelled before it took the run lock)."""
    return await asyncio.to_thread(_status_dict, run_id)


@mcp.tool(name="research.get_report")
async def research_get_report(run_id: str) -> dict[str, Any]:
    """The finished report markdown plus run stats."""
    validate_run_id(run_id)
    run_dir = _runs_root() / run_id
    if not run_dir.is_dir():
        raise ValueError(f"unknown run_id '{run_id}'")
    report_path = run_dir / "report.md"
    status = await asyncio.to_thread(_status_dict, run_id)
    if not report_path.is_file():
        raise ValueError(
            f"run '{run_id}' has no report yet (status={status['status']}, "
            f"completed {len(status['completed_steps'])}/{status['planned_steps']} steps)"
        )
    result: dict[str, Any] = {
        "run_id": run_id,
        "report_markdown": await asyncio.to_thread(
            report_path.read_text, encoding="utf-8"
        ),
        "status": status,
    }
    if status["status"] == "needs_attention":
        result["checkpoint_status"] = f"needs_attention: {status['stop_reason']}"
    elif status["status"] not in ("complete", "partial"):
        # report.md exists but the checkpoint never reached a terminal state —
        # the file may be mid-write (or the run orphaned mid-write).
        result["checkpoint_status"] = f"{status['status']} (report may be mid-write)"
    return result


def _reconcile_orphaned_runs() -> list[str]:
    """Startup reconciliation of this server's runs root.

    Delegates to `reconcile_orphans`: a 'running' checkpoint whose lock is
    free (its owner exited) becomes 'interrupted'; one whose lock is held — a
    live CLI run, another server — is left alone. 'interrupted' is not
    terminal: research.run accepts the run_id again and the orchestrator
    resumes from the recorded plan — a restart must not force the caller to
    pay for a fresh run."""
    return reconcile_orphans(_runs_root())


def serve() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s [trace=%(trace_id)s]: %(message)s",
    )
    _reconcile_orphaned_runs()
    mcp.run()
