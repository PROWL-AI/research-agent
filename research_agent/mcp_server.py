"""FastMCP server: the live surface the Fabric bundle declares (stdio).

Tools: research.run, research.list_runbooks, research.get_status,
research.get_report. Keys (PROWL_API_KEY / LLM keys) are read from the
server process env; only research.run needs them.

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
    RunResult,
    build_brief,
)
from research_agent.config import Config, ConfigError
from research_agent.evidence.store import ArtifactStore, Checkpoint, validate_run_id
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
    token = TRACE_ID.set(trace_id)
    try:
        log.info("run %s starting (runbook=%s)", run_id, runbook)
        # Persist the run's existence BEFORE planning: a planner/list_tools
        # failure must not leave get_status answering "unknown run_id" for an
        # id this server just handed out.
        store = ArtifactStore(_runs_root() / run_id)
        if store.load_checkpoint() is None:
            store.save_checkpoint(Checkpoint(run_id=run_id, runbook=runbook))
        config = _config_from_env()
        async with _make_prowl(config) as prowl, _make_llm(config) as llm:
            orchestrator = Orchestrator(prowl, llm, runs_root=_runs_root())
            result = await orchestrator.run(runbook, inputs, run_id=run_id)
        log.info("run %s finished: %s", run_id, result.status)
        return result
    except asyncio.CancelledError:
        # Cancellation is a typed partial outcome, not a ghost "running"
        # checkpoint: whatever evidence was gathered stays on disk.
        checkpoint = ArtifactStore(_runs_root() / run_id).load_checkpoint()
        if checkpoint is not None:
            checkpoint.status = "partial"
            checkpoint.partial = True
            checkpoint.stop_reason = "cancelled"
            store.save_checkpoint(checkpoint)
        log.warning("run %s cancelled", run_id)
        raise
    except Exception as exc:
        checkpoint = ArtifactStore(_runs_root() / run_id).load_checkpoint()
        if checkpoint is not None:
            checkpoint.status = "failed"
            checkpoint.stop_reason = str(exc)[:300]
            store.save_checkpoint(checkpoint)
        log.error("run %s failed: %s", run_id, exc)
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
    # Prune finished tasks so _TASKS does not grow for the server's lifetime.
    for stale_id in [rid for rid, t in _TASKS.items() if t.done()]:
        _TASKS.pop(stale_id, None)
    if run_id in _TASKS and not _TASKS[run_id].done():
        raise ValueError(f"run '{run_id}' is already running in this server process")

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


def _status_dict(run_id: str) -> dict[str, Any]:
    validate_run_id(run_id)
    checkpoint = ArtifactStore(_runs_root() / run_id).load_checkpoint()
    if checkpoint is None:
        raise ValueError(f"unknown run_id '{run_id}' (no checkpoint at runs/{run_id})")
    try:
        created = datetime.fromisoformat(checkpoint.created_at)
        updated = datetime.fromisoformat(checkpoint.updated_at)
        duration_s: float | None = round((updated - created).total_seconds(), 1)
    except ValueError:
        duration_s = None
    return {
        "run_id": run_id,
        "runbook": checkpoint.runbook,
        "status": checkpoint.status,
        "partial": checkpoint.partial,
        "stop_reason": checkpoint.stop_reason,
        "planned_steps": len(checkpoint.plan),
        "completed_steps": checkpoint.completed_steps,
        "skipped_steps": checkpoint.skipped_steps,
        "counters": checkpoint.counters,
        "duration_s": duration_s,
    }


@mcp.tool(name="research.get_status")
async def research_get_status(run_id: str) -> dict[str, Any]:
    """Status of a run from its checkpoint: steps, counters, duration."""
    return _status_dict(run_id)


@mcp.tool(name="research.get_report")
async def research_get_report(run_id: str) -> dict[str, Any]:
    """The finished report markdown plus run stats."""
    validate_run_id(run_id)
    run_dir = _runs_root() / run_id
    if not run_dir.is_dir():
        raise ValueError(f"unknown run_id '{run_id}'")
    report_path = run_dir / "report.md"
    if not report_path.is_file():
        status = _status_dict(run_id)
        raise ValueError(
            f"run '{run_id}' has no report yet (status={status['status']}, "
            f"completed {len(status['completed_steps'])}/{status['planned_steps']} steps)"
        )
    return {
        "run_id": run_id,
        "report_markdown": report_path.read_text(encoding="utf-8"),
        "status": _status_dict(run_id),
    }


def serve() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s [trace=%(trace_id)s]: %(message)s",
    )
    mcp.run()
