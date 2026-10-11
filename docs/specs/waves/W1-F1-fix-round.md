# W1-F1 — wave-1 fix round (certification findings on 675e769)

Wave 1's three blind readings (unit pass; seam fail; product fail) found the items below. This is
the wave's single fix round. Contract: [`../2026-10-11-waves-canvas.md`](../2026-10-11-waves-canvas.md)
§2 N-OWN and [`W1-T1-run-ownership.md`](W1-T1-run-ownership.md). Repository root = this checkout;
Python 3.11 `.venv`. **Do not commit or push**; no paid calls; no `.env`; do not restart services.
This repository is **public**: no absolute home paths, no private agent names in anything you write.

Test-first for every code item: write the failing test, watch it fail, fix.

## Breaks (must close)

1. **Stdio refusal is invisible; "orphaned" contradicts the lock** (`research_agent/mcp_server.py`
   `research_run` ~:156-232, `_status_dict` ~:301-303). In `research_run`, after the existing
   checkpoint checks and before scheduling, refuse synchronously with
   `ValueError("run … is locked by another process")` when `is_locked_elsewhere(run_dir)` and the
   run is not this server's live task. In `_status_dict`: `orphaned = status == "running" and (no
   live task) and not is_locked_elsewhere(run_dir)`, and add `"active": bool` (lock held by any
   process). Test: a helper holds `RunLock`; `research_run(wait=False)` raises with the message,
   checkpoint bytes unchanged; `research.get_status` → `orphaned=False, active=True`.
2. **Published legacy output schema rejects the envelope** (`fabric/schemas/capability-output.schema.json`,
   `additionalProperties:false`). Add `terminal_code` (`["string","null"]`, enum = the ten codes in
   `research_agent/evidence/terminal.py` + null, description), fix the `interrupted` wording (the
   owning process exited with its lock free; graceful shutdown writes `cancelled`), and update
   `capability-input.schema.json` run_id description (a run whose lock is held is refused). Add a
   test validating `_result_envelope(...)` from a real `research_run(wait=True)` against the file.
   Check whether this schema participates in the provider `contentHash` (`fabric-agent.json`
   refs, `docs/FABRIC.md`, any hash script under `scripts/`/`fabric/`); report yes/no with evidence.
   Note the change in `fabric/FABRIC-CONFORMANCE.md` (one dated line).

## Risks (fix in this round)

3. `reconcile_orphans` (`research_agent/evidence/runlock.py` ~:139-161): catch `OSError` per run
   dir around acquire and save → `events.emit(..., "run.reconcile.failed", level=WARNING, …)` and
   continue. Test: a read-only run dir (chmod 0o500) does not stop a sibling orphan from being
   reconciled; restore permissions in teardown.
4. `events.py` key filter: anchor on key segments so `keyword`, `keywords`, `input_tokens`,
   `output_tokens`, `tokens_in`, `tokens_out` pass while `api_key`, `key`, `token`, `access_token`,
   `secret`, `authorization`, `password`, `cookie` are refused. Add value redaction for the `error`
   field: replace `Bearer <x>`, `sk-…`, `prowl_…` patterns with `[redacted]`. Tests for both.
5. Untested branches: `_pre_checkpoint_status` cancelled and still-running arms; prune's delete-time
   lock refusal; `_write_terminal` runbook-mismatch guard and its write-failure path. One test each.
6. Prune race (`research_agent/__main__.py` delete loop): under the lock, rename the run dir to
   `runs/.pruning-<id>-<ts>` then `rmtree` the tombstone; an `OSError` per dir is reported as
   skipped. Test.
7. Budget code coupling: `Orchestrator._budget_stop_reason` returns `(code, text)` (or builds text
   from constants shared with `terminal.py`); delete the string-prefix parser or make it the
   fallback only for v1 checkpoints. End-to-end tests for `budget_usd` and `budget_minutes`.
8. Service job vs checkpoint (`research_agent/service/runtime.py` ~:186-226): a timeout records job
   error code `timeout` (not `execution-failed`); for research jobs the job error/result carries the
   checkpoint's `terminal_code`. Graceful stop (`Runtime.close`) keeps job phase `interrupted` and
   the checkpoint keeps `cancelled` — document this in the README table. Tests for timeout and close.
9. One CLI runs root: `_cmd_run`, `rewrite`, `report`, `export`, `prune` use `_runs_root()`
   (`RESEARCH_RUNS_DIR` or `./runs`), same as `status`. Update README's `RESEARCH_RUNS_DIR` bullet.
   Test with `RESEARCH_RUNS_DIR=<tmp>`.
10. `tests/test_audit_r3_writer.py` `test_precondition_error_does_not_rewrite_finished_checkpoint`:
    drive the real orchestrator (patch `_plan`) like its sibling, so it tests the guard again.

## Documentation (same change)

11. README: the probe sentence (~:189) — point at the command instead of a number (or "seven
    failing, five passing at <this commit>"); KA-06 state = "addressed in wave 1, certification
    pending" (identical wording in `docs/evidence/fabric-dashboard/VERIFICATION.md` ~:25); widen
    the `cancelled` row (any cancellation of the owning task, incl. graceful shutdown);
    `has_checkpoint=false` covers "still starting" too; `research.get_status` tool description in
    `mcp_server.py` (~:323) says so as well.
12. `docs/ux/scenarios.md`: CORE-01, CORE-02 (wave-1 half), CORE-03, CORE-04 (wave-1 half),
    CORE-12 — name the tests in Coverage, set Status from what the tests prove (`PASS@<commit
    placeholder "W1-F1">` — the orchestrator stamps the SHA at commit), CORE-03/04 wording matches
    what the caller sees after item 1 (`active`), CORE-04 names the runs directory. Run super-ux
    `ux_lint.py` (find it with `ls ~/.claude/plugins/marketplaces/super-ux/plugins/super-ux/scripts/ux_lint.py`)
    and paste its output.

## Ownership

`research_agent/**`, `tests/**`, `README.md`, `fabric/schemas/*.json`, `fabric/FABRIC-CONFORMANCE.md`,
`fabric/probes/assertions.md`, `docs/ux/scenarios.md`, `docs/evidence/fabric-dashboard/VERIFICATION.md`.
**Not yours** (another agent edits them now): `docs/FABRIC.md`, `docs/HANDOFF.md`, `docs/specs/**`,
`docs/evidence/backlog.md`.

## Done when (paste outputs)

```sh
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m pytest tests/test_ka_contracts.py -q
PYTHONPATH=tests:. .venv/bin/python -m pytest -q docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py   # 7 failed, 5 passed expected (waves 2-3)
.venv/bin/python -m research_agent validate
git grep -n "/Users/" -- README.md research_agent tests fabric docs/ux   # no hits
```

Report: each item → files + test names; the contentHash answer; any item you could not close and why.
