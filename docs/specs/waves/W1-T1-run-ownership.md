# W1-T1 — run ownership spine (KA-06, B-009, B-010, B-012, B-011) + structured events

Wave 1 of [`../2026-10-11-waves-canvas.md`](../2026-10-11-waves-canvas.md) — read §2 **N-OWN** first;
it is the contract this task implements. Do not design anything the canvas contradicts; if the
code proves the canvas wrong, stop and report rather than improvise.

Repository: `/Users/sshlg/DATA/0xDEV/research-agent` (PROWL-AI/research-agent, Python 3.11,
venv `.venv`). Branch `feat/fabric-dashboard-20261010`. **Do not commit, push, or touch files
outside the ownership list below** — another agent edits docs in parallel. Do not restart the
installed launchd service `chat.prowl.research`, do not call any paid provider, do not read `.env`.

## Why

A non-owner process rewrites a live run's checkpoint. Reproduced at HEAD by
`docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py::test_ka06_non_owner_cannot_mutate_locked_checkpoint[run|startup]`
(both red). Mechanism: the flock is held only inside `Orchestrator.run`
(`research_agent/agent/orchestrator.py:225-269`); the lock refusal (`OrchestratorError` at :239)
lands in `mcp_server._execute_run`'s `except Exception` (`research_agent/mcp_server.py:132-148`),
which sees `status=="running"` + same runbook and writes `failed` into the **owner's** checkpoint.
Startup `_reconcile_orphaned_runs` (`mcp_server.py:327-354`) marks every `running` checkpoint
`interrupted` without checking the lock. Same pattern: CLI `_mark_run_failed`
(`research_agent/__main__.py:163-182`, called :222-228) and `writer.rewrite_report`
(`research_agent/agent/writer.py:463-492`, writes report.md + checkpoint with no lock). Ordering
race: `Orchestrator.run` releases the lock in `finally` before the MCP handlers write.
B-009: a crashed CLI run stays `running` until some stdio server starts; the Fabric service's
run dirs (`<service root>/runs`) are never reconciled; service cancel/timeout
(`research_agent/service/runtime.py:186-190, 221-226`) leaves `runs/<job>/checkpoint.json` at
`running` forever while `research.artifact.get` serves it (`service/protocol.py:80-91`).

## What to build (final form — wave 2 extends the checkpoint, it must not have to undo this)

1. **`research_agent/evidence/runlock.py`** — the one owner of the run lock:
   `class RunLock` (`__init__(run_dir)`, `acquire(blocking=False) -> bool`, `release()`,
   context manager raising `RunLocked` on failure), and `is_locked_elsewhere(run_dir) -> bool`
   (probe: try non-blocking, release immediately). Move `_acquire_run_lock`'s logic here;
   `Orchestrator.run` and CLI `prune` (`__main__.py:358-372, 415`) use it. Keep the
   `OrchestratorError("run … is locked by another process")` message for the refusal.
2. **`Orchestrator.run` owns every lifecycle write while live.** Inside the lock, catch
   `asyncio.CancelledError` → load the checkpoint, if `running` set `status="partial"`,
   `partial=True`, `stop_reason="cancelled"`, `terminal_code="cancelled"`, save, re-raise; catch
   `Exception` → `status="failed"`, `stop_reason=str(exc)[:300]`, `terminal_code="error"`, save,
   re-raise. Only then release the lock. The pre-planning checkpoint creation now in
   `mcp_server._execute_run` (:108-112, so `get_status` never answers "unknown run_id") moves
   inside `Orchestrator.run` under the lock (keep the behaviour: a checkpoint exists before
   planning starts). A lock refusal raises before any write.
3. **MCP handlers and CLI only report.** Remove the checkpoint writes from
   `mcp_server._execute_run`'s except blocks and delete CLI `_mark_run_failed`; both log and
   re-raise / exit non-zero. Verify every path that previously relied on them is now covered by
   (2) — including an exception thrown *before* `_run_locked` reaches planning (config/LLM client
   construction happens outside `Orchestrator.run` in `_execute_run`: a failure there must not
   leave a ghost `running` checkpoint — since the checkpoint is now created inside the lock, no
   checkpoint exists in that case; `get_status` must answer accordingly; adjust the docstring).
4. **Reconciliation under the lock**, one function `reconcile_orphans(runs_root) -> list[str]` in
   `runlock.py` (or `evidence/reconcile.py`): for each `running` checkpoint, `RunLock.acquire(False)`;
   held → skip (log event `run.reconcile.skipped_active`); acquired → `status="interrupted"`,
   `partial=True`, `stop_reason="process exited before completion"`,
   `terminal_code="interrupted"`, save, release. Corrupt checkpoint → log + skip (as today).
   Callers: stdio MCP startup (replaces `_reconcile_orphaned_runs`), CLI `run`/`status` entry,
   service `Store.recover()` path for `<service root>/runs`. 'interrupted' stays resumable.
5. **Service cancel/timeout**: cancellation must propagate into `Orchestrator.run` so (2) writes
   the terminal state; if the service kills a job whose orchestrator task already finished, do
   nothing. After a service process crash, (4) reconciles at the next start.
6. **`rewrite_report`** takes `RunLock.acquire(False)`; held → typed refusal
   (`OrchestratorError("run … is active; rewrite refused")`), no write.
7. **`Checkpoint.terminal_code: str | None`** (`research_agent/evidence/store.py`), set on every
   terminal write; `None` while running. Enum (string constants in one place, e.g.
   `research_agent/evidence/terminal.py`): `completed, budget_tools, budget_usd, budget_minutes,
   budget_llm, step_failed, evidence_incomplete, cancelled, error, interrupted`. In this task set:
   `completed` for a clean finish, the existing budget stops → the matching `budget_*`, hard step
   failure → `step_failed`, plus the four above. (`budget_llm`, `evidence_incomplete` are used by
   waves 4 and 2 — declare them now.) Expose it in `mcp_server._status_dict`, the CLI `status`
   output, the service job view/`artifact()` where checkpoint status is shown. Schema version
   stays 1 in this task (wave 2 owns v2); the field is additive with default `None` so old
   checkpoints load.
8. **`research_agent/events.py`** — `emit(logger, event, level=logging.INFO, **fields)`: one line
   `event=<name> k=v …` (values: str/int/float/bool/None; strings repr-quoted if they contain
   spaces, truncated to 200 chars). A field key matching `(?i)key|token|secret|authorization|password|cookie`
   raises `ValueError` when `RESEARCH_EVENTS_STRICT=1` (tests set it via conftest) and is dropped
   with a WARNING otherwise. Use it for every lifecycle transition you touch:
   `run.started`, `run.terminal` (fields run_id, status, terminal_code, partial), `run.lock.refused`,
   `run.reconcile.interrupted`, `run.reconcile.skipped_active`, `run.rewrite.refused`. Keep the
   existing trace_id log format working (`mcp_server.serve` formatter uses `%(trace_id)s`).
9. **B-012**: fix `mcp_server.py:1-9` docstring — the Fabric bundle points at the HTTP service
   (`fabric-agent.json` connection `http://127.0.0.1:18764/mcp`); this stdio server is the legacy
   local surface.
10. **README** (you own it in this task): the status/terminal contract (`README.md:52, 99-103`)
    gains `terminal_code`; the "offline suite passed 304 tests at 1dced8e" line (`:155`) becomes a
    statement that does not rot (point at the command, not a number) — B-011; the tool-count lines
    (`:10-12, :81`) say 4 for the stdio server **and** 7 for the Fabric service (count both from
    code: `grep -c "@mcp.tool\|mcp.tool(" research_agent/mcp_server.py` and the service tool list in
    `research_agent/service/protocol.py`); move the Fabric section before License. Do not touch
    other docs files.

## Tests (TDD — write each failing test first, watch it fail, then fix)

- New `tests/test_ka_contracts.py`: port **both** `test_ka06_*` cases from the probe file verbatim
  in intent (helpers it needs, e.g. `ScriptedClient`, go to `tests/conftest.py`). They must fail
  before your change and pass after. Do not port the other KA probes yet (their fixes land in
  waves 2–3); do not use xfail.
- Control (must stay green): an unlocked true orphan is reconciled to `interrupted`.
- Cancellation test: cancelling `Orchestrator.run` mid-run leaves `partial` + `cancelled` written
  by the owner; a second, non-owner cancel/exception path writes nothing.
- `rewrite_report` refused while locked.
- `events.py`: format, truncation, secret-key refusal under strict mode.
- **Real two-process smoke** `tests/test_two_process_lock.py`: spawn two `python -m research_agent`
  subprocesses (or a subprocess holding `RunLock` + the in-process MCP path) on one temp runs dir
  with `FakeProwl`/`FakeLLM` wiring available to the CLI via an env hook if one exists — if the CLI
  cannot run offline, use a helper subprocess that holds the lock and assert the in-process MCP
  `research_run` refusal leaves the checkpoint bytes unchanged. Assert the loser's write is absent
  (compare checkpoint file bytes before/after).
- Update the tests that pin removed behaviour (`tests/test_audit_r3_contract.py:96-105, 280-296`,
  `tests/test_audit_batch_c.py:122`, `tests/test_audit_r3_integrity.py:161-190`, any test calling
  `_reconcile_orphaned_runs` / `_mark_run_failed`) to the new contract — change assertions only
  where the old behaviour was the defect; say which in your report.

## Ownership (files you may change)

`research_agent/agent/orchestrator.py`, `research_agent/mcp_server.py`, `research_agent/__main__.py`,
`research_agent/agent/writer.py` (rewrite_report only), `research_agent/evidence/store.py`,
new `research_agent/evidence/runlock.py`, new `research_agent/evidence/terminal.py`,
new `research_agent/events.py`, `research_agent/service/runtime.py`, `research_agent/service/store.py`,
`research_agent/service/protocol.py` (status exposure only), `research_agent/report/render.py`
(only if it renders status), `tests/**`, `README.md`.

## Done when (run these, paste the outputs)

```sh
.venv/bin/python -m pytest tests/ -q                                  # all green
.venv/bin/python -m pytest tests/test_ka_contracts.py -q -k ka06      # 2 passed
PYTHONPATH=tests:. .venv/bin/python -m pytest -q docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py -k ka06   # 2 passed (the historical probe now agrees)
.venv/bin/python -m research_agent validate
ruff check research_agent tests 2>/dev/null || true                   # report findings, if ruff is installed
```

Report back: files changed with a one-line why each; every test whose assertion you changed and
why the old behaviour was the defect; the exact command outputs above; anything in the canvas the
code contradicted; anything you noticed but did not fix (with file:line).
