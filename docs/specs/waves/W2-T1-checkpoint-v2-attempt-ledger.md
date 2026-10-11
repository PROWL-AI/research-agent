# W2-T1 — checkpoint v2: step identity, step state machine, durability, attempt ledger

Wave 2 of [`../2026-10-11-waves-canvas.md`](../2026-10-11-waves-canvas.md). **Read §2 N-STATE and
N-COST in full — they are the contract.** Closes KA-03, KA-04, KA-05, KA-10, KA-11, KA-12, B-006,
B-008, B-025. Builds on wave 1 (`research_agent/evidence/runlock.py`, `terminal.py`, `events.py`,
`Checkpoint.terminal_code`, `tests/test_ka_contracts.py`) — read what wave 1 shipped first
(`git log --oneline -5`, the files above).

Repository `/Users/sshlg/DATA/0xDEV/research-agent`, Python 3.11, `.venv`. **Do not commit or push**;
no paid calls; do not read `.env`; do not restart services. Disk is tight — no large temp files.

## The defects (all reproduced at `c0dfb6e`; line numbers are at that revision — re-locate them)

- **KA-03** step identity = index in a plan re-filtered by `validate_plan` on every attempt
  (`agent/orchestrator.py:340`); index-keyed consumers: `split_segments` (`agent/subagent.py:126-128`),
  raw names `NN_tool.json` (`evidence/store.py:72,89`), idempotency key `run:index:tool`
  (`subagent.py:188`), `skipped_steps[].index`, resume filter (`orchestrator.py:319-323`),
  `_skip_remaining` (`:547-557`). A catalog/allowlist change between attempts shifts later steps.
- **KA-04** `completed_steps.append(j)` for never-started steps after a hard failure
  (`subagent.py:219-227`) and for budget-stopped steps (`:166-171`); on_error_skip marks a failed
  step completed (`:194-205`; transform `orchestrator.py:571-578`). One flat set mixes four meanings.
- **KA-05** success path order: dispatch (:186) → counters in memory (:232-248) → `save_raw` (:250)
  → extract (:256) → `_safe_save` (:259) → `completed_steps.append` (:261, after the save). Transform
  same (`orchestrator.py:586-594`; `save_markdown` non-atomic `store.py:95`). `_safe_save` swallows
  write errors (`subagent.py:141-153`).
- **KA-10** raw-save failure invents a `raw_path` that does not exist (`subagent.py:249-253`);
  extraction failure swallowed (:255-258); step still marked done; terminal status from
  `checkpoint.partial` only (`orchestrator.py:363`).
- **KA-11** `_budget_stop_reason` (`orchestrator.py:642-648`) uses `prowl.cost_usd` once any
  server cost exists, else the estimate — never both; worker updates one or the other
  (`subagent.py:234-248`).
- **KA-12** `_invoke` adds a billed failure's cost to `client.cost_usd` then raises
  (`prowl_client.py:180-184, 206`); worker `except` never persists cost (`subagent.py:190-230`);
  stats read the counter (`orchestrator.py:370`) → `None`; resume seeds a new client from `None`
  (`:306-310`); `CancelledError` skips even `attempted_calls`.
- **B-006** `save_markdown` non-atomic; its `OSError` escapes `_execute_transform` and fails the run.
- **B-008** a failed transform is not saved until the next segment.
- **B-025** `raw_ref` absolute under the service, CWD-relative under CLI.

Probes that must turn green and move into `tests/test_ka_contracts.py` (no xfail):
- deep: `docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py` —
  `test_ka10_evidence_failure_cannot_report_complete[raw_write|extraction]`,
  `test_ka11_known_cost_does_not_discard_previous_estimates`,
  `test_ka12_billed_failure_cost_survives_resume`; keep the 3 controls green.
- resume (KA-03/04/05): fetch with
  `git -C /Users/sshlg/DATA/0xDEV show origin/audit/kimi-20261010:docs/reports/2026-10-10-kimi-session-audit/raw/probe_research_resume.py`
  (`test_catalog_change_does_not_skip_an_unexecuted_step`,
  `test_unstarted_steps_after_failure_remain_resumable`,
  `test_completed_step_is_persisted_before_worker_returns`).
  Port them; the probes assert on `completed_steps` — translate each assertion to the v2 model
  (`steps[].state`) **preserving its intent**, and state each translation in your report.

## Build order (each step: failing test first, then code)

1. **Schema.** `Checkpoint` v2 exactly as the canvas §2 N-STATE/N-COST (`StepRecord`,
   `AttemptRecord`, `steps`, `attempts`, `plan_raw`, `migrated_from`, keep `status`,
   `stop_reason`, `partial`, `terminal_code`, `brief`, `stats`, `transform_notes`). `SCHEMA_VERSION = 2`.
   `step_id = "s-" + sha256(canonical_json({raw_index, tool, arguments}))[:12]` (canonical =
   `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)`).
   Helpers: `step_counts()`, `completed_step_ids()`, `spend_usd(kind)`, `unknown_attempts(kind)`.
2. **Migration v1 → v2** in `research_agent/evidence/migrate.py`, invoked by
   `ArtifactStore.load_checkpoint` for `schema_version < 2`; typed `CheckpointMigrationError` with
   the three refusals and the `runtime_skip` rule from the canvas. Existing v1 fixtures in tests
   (`tests/test_subagents.py:304-322`, `tests/test_audit_r3_integrity.py:30`,
   `tests/test_audit_r3_contract.py:62`) become migration inputs. A refused migration reports the
   run as needing attention (status unchanged on disk, `research.run` / CLI / MCP refuse to resume
   it with the typed message) — never silently resumed.
3. **Plan once.** `validate_plan` runs when the plan is made; drops become `excluded` StepRecords
   with the validator's reason. On resume: persisted steps are authoritative; a tool now missing
   from catalog/allowlist marks *that* step `excluded` (reason `catalog_changed`), nothing shifts.
4. **Durable worker** (`agent/subagent.py`) with the canvas order: append AttemptRecord +
   `dispatching` + save → dispatch → `finally` finalize the attempt (outcome, cost basis,
   actual/estimate; `CancelledError` → `cancelled`, re-raise after saving) + save → atomic raw
   write with sha256, run-dir-relative `raw_ref` → `raw_saved` + save → extract → ledger save with
   claim ids derived from `step_id` + ordinal (re-extraction replaces) → `completed` + save. Save
   failures are no longer swallowed: a checkpoint write failure stops the run as
   `failed`/`error`; a raw write failure → step `failed` with reason `raw_write`, run `partial`,
   `terminal_code=evidence_incomplete`; an extraction failure → `extraction.status=failed`, step stays
   `raw_saved`, run `partial`/`evidence_incomplete`. On hard failure the never-started tail stays
   `pending`; budget stop → remaining steps `skipped_budget`; on_error_skip → `skipped_on_error`.
5. **Transforms** follow the same order; `save_markdown` atomic (reuse `_atomic_write_text`),
   named by `step_id`; failed transform saved immediately.
6. **Resume** executes `pending`, `outcome_unknown` (same idempotency key), `raw_saved`
   (extraction only — assert **zero** dispatches), `failed` when not on_error_skip. Idempotency
   key `f"{run_id}:{step_id}:{attempt_no}"`; `attempt_no` increments only after a definite outcome.
   Update `tests/test_audit_r3_contract.py:136-150` (pins the old key format) to the new contract.
7. **Attempt ledger is the budget source.** `ProwlError` (and `ToolCallError`) carry `cost_usd`
   (billed cost or `None`); `ProwlClient._invoke` attaches it before raising. The worker records
   cost from the call result / exception, never from client totals. `_budget_stop_reason` reads
   `checkpoint.spend_usd("tool")` (Σactual + Σestimate-without-actual, unknown at estimate) — the
   estimate for an unknown attempt is the tool's price from `ProwlClient.tool_prices` or the
   runbook's per-call default; never 0. Resume rebuilds spend from persisted attempts before the
   first dispatch. `stats.cost_source ∈ {server, estimate, mixed}`, `stats.cost_unknown_attempts`.
   `stats` is derived on save — not the source of truth.
8. **Readers.** Everything that read `completed_steps`/`skipped_steps`/`counters` reads the v2
   helpers: `mcp_server._status_dict` and `get_report`, CLI `status`, `report/render.py`, service
   `protocol.artifact()` and job view, `__main__` export. The v2 checkpoint is what
   `research.artifact.get` serves.
9. **Events** (wave-1 `events.emit`): `step.state` (run_id, step_id, from, to), `attempt.started`,
   `attempt.finished` (outcome, basis, actual_usd, estimate_usd), `budget.stop` (kind, spend, limit),
   `checkpoint.migrated` / `checkpoint.migration_refused`, `evidence.incomplete` (step_id, reason).
10. **Docs in the same change** (you own them in this task): README status/resume/budget
    sections (`README.md` — exit codes & partial, status contract, budget scope, resume limits),
    `docs/runbook-authoring.md:53-65` budget semantics, `docs/FABRIC.md:85-89` accounting/KA
    status, `fabric/schemas/capability-input.schema.json:34` ("resumes from its last completed
    step" → the v2 resume rule) — **if you change any file under `fabric/`, run the repository's
    contentHash/declaration check (see `docs/FABRIC.md` / `scripts/`) and report whether the
    provider hash moved**; do not bump the provider revision yourself, report it. Code docstrings
    `agent/subagent.py:1-18`, `orchestrator.py` budget_scope string.

## Crash-injection test (required)

`tests/test_durability.py`: a `CrashAt` helper (a `BaseException` subclass raised by patched
`ArtifactStore.save_checkpoint` / `save_raw` / `Ledger.save` on the Nth call) driven over **every**
durable boundary of one data step and one transform step. After each crash: reload from disk,
resume with a `FakeProwl` that counts dispatches, and assert (a) no step is reported completed
without its raw + claims, (b) a step with saved raw is never dispatched again, (c) spend never
decreases and never double-counts, (d) final status is `complete` when everything eventually
succeeds.

## Ownership

`research_agent/evidence/store.py`, new `research_agent/evidence/migrate.py`,
`research_agent/evidence/ledger.py` (claim-id derivation and save only — wave 3 owns statuses),
`research_agent/agent/subagent.py`, `research_agent/agent/orchestrator.py`,
`research_agent/prowl_client.py`, `research_agent/mcp_server.py`, `research_agent/__main__.py`,
`research_agent/report/render.py`, `research_agent/service/*.py` (readers only),
`tests/**`, `README.md`, `docs/runbook-authoring.md`, `docs/FABRIC.md`, `fabric/schemas/*.json`
(description text only).

## Done when (paste outputs)

```sh
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m pytest tests/test_ka_contracts.py tests/test_durability.py -q
PYTHONPATH=tests:. .venv/bin/python -m pytest -q docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py   # expect only KA-07/08/09 red (wave 3)
.venv/bin/python -m research_agent validate
for d in runs/*/; do .venv/bin/python -c "import sys; from pathlib import Path; from research_agent.evidence.store import ArtifactStore; c=ArtifactStore(Path(sys.argv[1])).load_checkpoint(); print(sys.argv[1], c.schema_version if c else None, c.status if c else None)" "$d"; done   # existing local runs migrate or refuse with the typed error
```

Report: files changed (why each), every changed test assertion and the defect it encoded, each
probe-assertion translation, the migration result for each `runs/*` dir, whether any `fabric/`
hash moved, and anything you noticed but did not fix (file:line).
