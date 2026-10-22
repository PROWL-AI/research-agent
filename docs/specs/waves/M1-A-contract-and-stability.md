# M1-A: contract and stability (B-075, B-077, B-079, B-080)

Wave A of [`../2026-10-22-milestone-m1.md`](../2026-10-22-milestone-m1.md). Public repository: no absolute home paths
or private names. Route: `/task-pipeline`, full flow (a public contract changes: the job error shape).

## Source ledger

| Source | What it gave |
|---|---|
| `docs/evidence/backlog.md` B-075, B-077, B-079, B-080 | the rows and their evidence |
| `fabric-agent-contract` at `7a14a48` `schemas/interop-common.schema.json` `$defs/error` | `required: [code, message]`, properties `code`, `message`, `data: true`, `additionalProperties: false` |
| `research_agent/service/runtime.py:319-340` | `_with_terminal` adds `terminalCode` beside `code` and `message` on `interrupted`, `timeout`, `execution-failed` |
| `research_agent/service/store.py:173` | restart marks a working job `interrupted` with `{code, message}` only |
| `scripts/verify-fabric-contract.py:44-52` | validates a completed tutorial job only; no failed job is ever checked against `interop-job` |
| `tests/test_ka_contracts.py:719,735` | pin `record["error"]["terminalCode"]` |
| `docs/FABRIC.md:103,105` | documents `+ terminalCode` in the job phase table |
| `research_agent/service/store.py:182-193` | `event()` writes service and job events to SQLite only |
| `research_agent/service/cli.py:28-53` | `events.log` receives the `research_agent` logger; job lifecycle never reaches it |
| `research_agent/agent/orchestrator.py:714`, `research_agent/agent/subagent.py:402`, `tests/test_not_sent_arguments.py` | B-077's three follow-ups |
| `dashboard_kit.py status` | kit files 1.1.1, current 1.1.2 |
| retro, verification ledger | none in this repository |

Contradictions: none between the sources. `docs/FABRIC.md` describes the shape the contract forbids; it changes with the code.

## Decisions (closed from the sources)

- **D1 (B-075).** The run's terminal code moves to `error.data.terminalCode`. `data` is the schema's open slot, so a
  strict reader accepts it and the information stays. A stored job from an earlier build that carries a top-level
  `terminalCode` is shown in the new shape when read (`job_view`), so no stored row breaks a reader.
- **D2 (B-075).** `scripts/verify-fabric-contract.py` also validates a failed research job's view, so the next drift
  of this kind fails the contract check, not a reader in production. An offline test pins that every error the
  service writes has only `code`, `message`, `data`.
- **D3 (B-080).** Every `Store.event()` also writes one INFO line (`job.*`, `service.*`) to the `research_agent.service`
  logger, which `events.log` carries; the line holds kind, level, subject id and the event text, nothing else (the
  text is already person-facing and secret-free). SQLite stays the dashboard's source.
- **D4 (B-077).** The evidence-only fallback report prints the person-facing coverage `statement`; a re-send of an
  `outcome_unknown` step without `bound_arguments` sends `record.arguments`; tests pin that the dispatch-time limit
  check runs before any Prowl connection and that the refusal message is cut at 300 characters.
- **D5 (B-079).** Upgrade the vendored kit to 1.1.2 with the kit's own script; the WebKit dashboard check reruns.
  The kit 1.1.2 install also adds `fabric-button.js` (Fabric's button, DEC-0040); the page does not link it, and
  adopting it is a change to what the page shows, so it is left out here and belongs to wave B if anywhere.

## REQ

| REQ | Requirement | Verified by |
|---|---|---|
| A-1 | A failed research job's error validates against the pinned `interop-common` `$defs/error` | `scripts/verify-fabric-contract.py <contract checkout at 7a14a48>` exit 0, run failing once on the old code |
| A-2 | Every service-written job error has only `code`, `message`, `data` | new test in `tests/test_service.py` |
| A-3 | A legacy stored error with top-level `terminalCode` is served in the new shape | new test |
| A-4 | Job lifecycle and service start/stop reach `events.log` | new test on `Store.event` with the rotating handler |
| A-5 | B-077 (a), (b), (c) | tests named in the build |
| A-6 | Kit current | `dashboard_kit.py status`; `node scripts/test-dashboard.mjs` PASS |
| A-7 | Docs true | `docs/FABRIC.md` table, README logs line, backlog rows closed with the commit |
