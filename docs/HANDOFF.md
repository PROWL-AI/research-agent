# Research-agent handoff — Kimi audit, 2026-10-10

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
and Fabric manifest were not changed in this audit; only documentation changed here.

## Confirmed resume defects and repair packets

| ID | Source at audited revision | Required behavior |
|---|---|---|
| KA-03 | [`orchestrator.py:338`](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/orchestrator.py#L338) re-filters the plan; completion indices are reused at line 478 | Catalog changes must not change a step's identity or make an unexecuted step appear complete. |
| KA-04 | [`subagent.py:219`](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/subagent.py#L219) marks the unstarted chunk tail completed | Resume must execute never-started steps; distinguish them from intentionally skipped, completed and dispatch-uncertain steps. |
| KA-05 | [`subagent.py:259`](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/subagent.py#L259) saves before completion is appended | Commit durable completion before returning; recover already-paid raw data after a crash without another dispatch. |

**Exact next task:** establish immutable step identity and checkpoint-v1 migration
(KA-03), tracing that identity through completion, raw evidence and caller idempotency
keys. Coordinate with the parent execution/replay contract before changing those
keys. Then repair skipped-tail and persistence ordering together, using the three
red probes as acceptance tests. Add crash injection between raw, ledger and
checkpoint writes; an ordering-only fix is not an atomic multi-file commit.

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
