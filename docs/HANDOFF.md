# Research-agent handoff

## Current entry — wave program, updated 2026-10-17 (supersedes "Exact next task" below)

Objective: close every open item of this agent in its final form, in waves
(`/task-pipeline waves`), each followed by independent verification.

- Plan: [`specs/2026-10-11-waves-canvas.md`](specs/2026-10-11-waves-canvas.md) — target state, seams,
  waves with exit criteria, §7a wave status, operator questions (§8).
- Inventory: [`specs/2026-10-11-waves-inventory.json`](specs/2026-10-11-waves-inventory.json)
  (`python3 scripts/plan/assign_waves.py --check`; 28 of 55 open). Board: [`evidence/backlog.md`](evidence/backlog.md).
- **Wave 1 closed** (merged to `main` by PR #1): run-lock ownership (KA-06, B-009, B-010),
  terminal_code, structured events, honest docs, CORE scenarios, nightly CI.
- **Wave 2 closed** on branch `wip/wave2-checkpoint-v2` (PR #2): checkpoint schema 2 — immutable
  step ids, step states, durable evidence order, attempt ledger as the budget source, v1→v2
  migration with `needs_attention` (KA-03/04/05/10/11/12, B-006, B-008, B-025). Crash injection
  at every durable write (`tests/test_durability.py`). Suite 402 passed; deep probes 4 failed
  (KA-07/08/09 + the superseded cwd-relative control) / 8 passed.
- **Upgrade is one-way per run dir** (checkpoint.v1.json kept): restart stdio client sessions and
  reinstall the Fabric service (still `891fbc9`) before resuming runs a v2 build has touched —
  scheduled for wave 5.
- **Wave 3 closed** (PR from `feat/wave3-ledger-v2`, build `86e313e`, fix round `5fcf2f4`): ledger
  schema 2 — status recomputed per subject group (order-independent), `verified` only by a quote
  located in the stored raw or by two independent sources (publisher of a URL the raw names, or an
  upstream dataset; one step is one delivery; transforms and LLM-answer tools are no source);
  KA-07/08/09, B-007, B-024 closed. Suite 450 passed; deep probes 11/12 (superseded cwd control).
  The fix round also repaired a wave-2 seam break (MCP status/report serialization).
- **Exact next task:** [`specs/waves/W4-T1-llm-budget-service-parity.md`](specs/waves/W4-T1-llm-budget-service-parity.md)
  (KA-G01, B-003, B-004, B-005, B-029, B-035, B-036, B-038), then the wave-4 close pass (its seam
  tier also re-reads wave 3's fix round).
- Operator decisions (canvas §8) answered 2026-10-12: Q1 PR-per-wave merges, Q2 kit in wave 5,
  Q4 USD 15, Q5 host update at wave 6, Q6 no history rewrite. Q3 closed from sources.
- Cross-agent: B-001 (model profiles, waits on Fabric T1–T3), B-020 (the contract owner adds
  our adoption row with its PR #113), B-033 (this folder is not a Fabric project yet — operator step).

---

## Kimi and deep agent audits, 2026-10-10

Objective: independently verify the Kimi session's deliverables and correct the
documentation. This checkout belongs to `PROWL-AI/research-agent`; it is separate
from `PROWL-AI/prowl-app`, and is not its registered submodule.

## Source and verification

Audited source: [`1dced8e381e63db2b61dbcd854b44d41450ed455`](https://github.com/PROWL-AI/research-agent/tree/1dced8e381e63db2b61dbcd854b44d41450ed455).
Parent source: [`92f49d18dcd98df89a46448eac9818de74b8b7f6`](https://github.com/PROWL-AI/prowl-app/tree/92f49d18dcd98df89a46448eac9818de74b8b7f6).

- `.venv/bin/python -m pytest tests/ -q`: **304 passed**, exit 0.
- `.venv/bin/python -m research_agent validate`: **14 runbooks valid**, exit 0; local catalog check.
- Three additional expected-contract probes failed on the audited source. Their
  source and captured output live in the central report below; they are outside
  the default test collection and are not hidden by xfail.
- Real provider research/judges for finance/subscription and Fabric host admission:
  **NOT_RUN in this audit**. The previous session's final live command failed at
  argument parsing before research began.

Central report and exact reproduction commands (requires access to the parent
repository): [RPT prowl.chat/2026-10-10-kimi-session-audit](https://github.com/PROWL-AI/prowl-app/blob/audit/kimi-20261010/docs/reports/2026-10-10-kimi-session-audit/README.md).
The central handoff records both delivered branch SHAs and receipts. Runtime code
and Fabric manifest were not changed; documentation and explicit offline diagnostic probes are delivered.

## Confirmed resume defects and repair packets

| ID | Source at audited revision | Required behavior |
|---|---|---|
| KA-03 | [`orchestrator.py:338`](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/orchestrator.py#L338) re-filters the plan; completion indices are reused at line 478 | Catalog changes must not change a step's identity or make an unexecuted step appear complete. |
| KA-04 | [`subagent.py:219`](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/subagent.py#L219) marks the unstarted chunk tail completed | Resume must execute never-started steps; distinguish them from intentionally skipped, completed and dispatch-uncertain steps. |
| KA-05 | [`subagent.py:259`](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/subagent.py#L259) saves before completion is appended | Commit durable completion before returning; recover already-paid raw data after a crash without another dispatch. |

## Deep audit and execution plan

[Additional report](reports/2026-10-10-agent-deep-audit/README.md) adds seven open
findings KA-06…KA-12: lifecycle ownership, evidence verification and cost persistence.
It contains nine failing contract checks and three passing controls; all are
synthetic offline trials, not live-provider acceptance. KA-03…KA-05 stay OPEN.

[Canonical cross-repository plan](https://github.com/PROWL-AI/prowl-app/blob/audit/kimi-20261010/docs/superpowers/plans/2026-10-10-kimi-remediation.md)
owns order, dependencies, module contracts and acceptance for all twelve defects.
That link intentionally tracks the working branch; runtime source links above are immutable.

**Exact next task in this repository: KA-06.** Move all lifecycle mutation behind
run ownership, including MCP error/cancel handlers and startup reconciliation.
Make both `test_ka06_non_owner_cannot_mutate_locked_checkpoint` cases pass, preserve
the unlocked-orphan control, then verify with two real CLI/MCP processes sharing
one runs directory. No provider key is needed for the offline tests.

Next bounded packet: KA-03/04/05/10 together (step identity, resumable state,
durable raw/claims/completion), coordinated with parent KA-01 execution replay.
KA-07/08/09 cover evidence truth; KA-11/12 cover attempt costs. See the plan for
acceptance rather than treating a green baseline suite as closure.

Prerequisites: Python >=3.11, test dependencies, clone/access to the central audit
probes. No provider key is needed for offline reproduction. Do not clone the
unrelated `~/DATA/research-agent` project as this dependency.

Open product acceptance: LLM budget enforcement is not implemented (`Budget`
contains tool calls, USD and minutes only); README correctly separates LLM usage.
After money/resume fixes, run finance and subscription acceptance with explicit
run and judge exit codes, cost receipts and then Fabric host evidence. A public
manifest alone is not evidence of admission.

## Delivery boundary

Documentation branch: `audit/kimi-20261010`. A pushed branch is a handoff, not a
merge or deployment. The central report owns statuses and the source-to-receipt
mapping. Full private session export, local credentials, caches and `runs/` remain
local-only and are not part of this documentation delivery.
