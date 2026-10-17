# Prowl Research in Fabric

Entry point for the Fabric adapter. Design: [dashboard specification](design/fabric-dashboard.md). Behavioral truth: [scenarios](ux/scenarios.md). Verification and remaining gates: [handoff](evidence/fabric-dashboard/HANDOFF.md).

## Ownership and architecture

The product's original `orchestrator_agent/` lives in the parent prowl-app repository. This separate repository has its own `research_agent/agent/orchestrator.py`. The service adapter calls that existing core (`service/runtime.py::Runtime.live`); it does not add another research engine. CLI and legacy stdio remain usable but their runs are not automatically imported into the service database.

```mermaid
flowchart LR
 A[Operator / Fabric Dashboards] --> D[Service-owned dashboard]
 F[Fabric hub / agent chain] --> M[Authenticated MCP]
 D --> S[SQLite jobs / decisions / receipts]
 M --> S
 S --> R[Existing Prowl Research Orchestrator]
 S --> T[One direct Prowl tool call]
 R --> P[Prowl MCP tool bank]
 R --> L[Configured LLM provider]
 T --> P
 P --> E[Readable result + raw artifact]
 L --> E
 E --> S
 S --> F
```

Fabric owns ordering between agents. Prowl owns one bounded job. The journal keeps caller-declared requester/project/chain/node/parent and W3C trace context; these strings are not an admission receipt. Another agent consumes `job.result.output`, then calls the next agent through Fabric `agent.call`. The new service is `prowl-research.default`, distinct from the unrelated private Research Agent installation.

## Tools and parameters

| MCP tool | Input | Result |
|---|---|---|
| `research.run` | runbook, inputs, idempotencyKey, optional context | durable job handle |
| `research.tools.call` | tool, params, idempotencyKey, optional context | durable job handle |
| `research.tutorial` | idempotencyKey, optional context | synthetic job handle; no provider traffic |
| `research.list_runbooks` | empty object | result envelope containing local runbooks and input definitions |
| `research.artifact.get` | id, name | bounded report.md / ledger.json / checkpoint.json / result.json |
| `fabric.job.get` | id | state, decision link or result envelope |
| `fabric.job.cancel` | id | terminal cancellation; no promise of upstream refund |

Exact schemas: `fabric/schemas/research.*.json`, generated from `service/protocol.py` by `PYTHONPATH=. python scripts/build-fabric-manifest.py`. The schemas are resolved locally by `$id`; their URI identifiers are not a promise of hosted schema publication. Contract revision is pinned in `fabric-contract.lock.json`. The service supports modern per-request MCP metadata and legacy initialization; this does not upgrade the separate legacy stdio server's protocol claim.

Every paid request initially requires the operator's authenticated dashboard session. Agent credentials cannot approve their own requests; `fabric.job.get` with `inputResponses` is refused. The job uses URL elicitation to reach operator authentication. Delegated Fabric form approvals and unattended grants remain a separate gate; do not claim that this adapter already supports them.

```json
{
  "name": "research.tools.call",
  "arguments": {
    "tool": "<actual Prowl tool name>",
    "params": {"domain": "example.org"},
    "idempotencyKey": "market-review-node-3-attempt-1",
    "context": {"requester": "growth-agent", "chain": "market-review", "node": "research", "parent": "discovery"}
  }
}
```

`params` accepts the selected tool's input object. Upstream schema, credentials and authorization still apply. Parameters are not shell commands. Same idempotencyKey and request returns the same job; changed request with the same key is rejected. Keys are local to this service instance, not a claim of upstream exactly-once execution.

## Install and operate

From a clean committed checkout on macOS, with uv and Python 3.11 available:

```sh
python3 scripts/install-fabric-service.py
prowl-research-service doctor --json
```

The installer creates an immutable commit release under `~/.local/share/prowl-research/releases/`, a launchd label `chat.prowl.research`, a loopback listener on 18764, and `prowl-research.default.json` in the Fabric service registry. It preserves an explicitly disabled launchd label and retains the current and previous release. It does not install credentials or alter other Research Agent services. Use the release's `venv/bin/prowl-research-service` if the entry point is not on PATH.

Data: `~/Library/Application Support/prowl-research/` (SQLite and runs). Logs: `~/Library/Logs/prowl-research/`. Host token and agent token are separate owned 0600 files. Back up the data directory with the service stopped; do not commit it. The service takes its exclusive lock before creating tokens or reconciling jobs. Startup marks interrupted paid work for inspection; it never automatically resubmits it.

For foreground development only:

```sh
prowl-research-service serve --root /absolute/private/test-data --port 18765
```

Open through Fabric Dashboards' resolved `open_link`; direct HTTP without host login is intentionally unauthenticated. Fabric host main process exchanges its token for a single-use login code. Browser sessions last eight hours; restarting does not silently approve pending jobs. Decisions expire after one hour and are tied to the exact request/config snapshot.

Provider secrets must be supplied by an Observatory-managed consumer launch, outside Git, dashboard fields and plist values. Required names: PROWL_API_KEY and RESEARCH_LLM_API_KEY (or OPENROUTER_API_KEY). No keys means degraded-but-usable tutorial/inspection, not a healthy paid runtime. Local install intentionally does not copy parent `.env` files or reuse unrelated agent credentials.

MCP registration: the `prowl-research` entry lives in each agent client's own configuration — on the operator's machine, Claude Code, Cursor, OpenCode and Codex (see [verification, machine integration footprint](evidence/fabric-dashboard/VERIFICATION.md#machine-integration-footprint)). Registering new servers in a shared gateway file (`~/.config/agentgateway/servers.yaml`) is a retired route on that machine; do not add this service there. Each client entry points at a scoped gateway profile named `prowl` (launchd label `dev.agentgateway.prowl`), which fronts this service with the service's agent token. The host token never goes into a client or gateway configuration. Client configurations, gateway configuration and tokens are machine-local and are not committed here. A client session started before its entry was added does not see the tools; restart it, and a new session discovers the 7 tools listed above. A gateway route is not Fabric hub admission.

## Names

This provider is service `prowl-research.default`, repository `PROWL-AI/research-agent`, provider id `https://prowl.chat/fabric/providers/research-agent` (`fabric-agent.json`). Its tools are `research.run`, `research.tools.call`, `research.list_runbooks`, `research.artifact.get`, `research.tutorial`, `fabric.job.get` and `fabric.job.cancel`. The legacy stdio server (`prowl-research mcp`) is a separate surface of the same core and exposes `research.run`, `research.list_runbooks`, `research.get_status` and `research.get_report`.

Other agents on the same estate may also publish `research.*` tools, so a bare tool name is ambiguous: always address this one by its service id or repository, never by the tool name alone. The names are not renamed, because the provider revision's `contentHash` binds them; a rename would be a new provider revision every caller has to re-pin.

## Job phase and run terminal state

A research job (`fabric.job.get`) and the run checkpoint it drives (`research.artifact.get` → `checkpoint.json`) answer different questions. The job phase says what happened to the request; the checkpoint's `status` and `terminal_code` (README, "Run status") say what happened to the research. They agree on the outcome but not always on the word: a job cancelled by its caller or stopped by a service shutdown shows `cancelled` / `interrupted` on the job, while the owning orchestrator writes `partial` + `terminal_code=cancelled` on the checkpoint before releasing the run lock; a job past its wall-clock timeout fails with error code `timeout` and the checkpoint again reads `cancelled`. A service crash leaves the job `working` until restart recovery marks it interrupted, and the checkpoint `running` until reconciliation under the run lock marks it `interrupted` (resumable). The full mapping table lands with the service-parity wave (canvas N-SVC).

## Accounting and intervention

- `Store.calls` is the single source of request and service usage. Tool failures retain actual billed cost; LLM receipts are written before truncated/null completion validation. Unknown price stays null; tutorial receipts never enter the Fabric usage report.
- Per-run actual costs are separate from legacy estimates. The service does not advertise an enforced monetary cap. Runbook budgets cover tools only; models are additional. Maximum 256 paid calls per request, configurable wall-clock timeout 1–60 minutes, workers 1–5, shared concurrent jobs 1–4.
- Configuration changes use revision checks and a visible diff. Existing jobs keep their model/worker/timeout snapshots; the shared scheduler's parallel-job setting is current service policy.
- Cancellation interrupts future work and preserves receipts. A request that lost an upstream reply may have been charged. Inspect first; a new request is a new spending decision.
- Ledger classifications follow schema 2 (wave 3, KA-07…KA-09 from the [deep audit](reports/2026-10-10-agent-deep-audit/README.md)): `verified` only for a quote located in the stored raw or two independent sources; the service output's `quality` string says the rules are tested offline only and live acceptance is pending (wave 6). `research.artifact.get` for `ledger.json` returns the file as stored: a run written before schema 2 shows its v1 statuses until `rewrite_report` re-saves it. Run ownership (KA-06, wave 1) and the core's step states, durable evidence and attempt ledger (KA-03…KA-05, KA-10…KA-12, wave 2) are in the shared core that service research jobs run on; service-path acceptance (a service job through crash and resume) belongs to the service-parity wave (N-SVC). A local refusal before anything is sent (the 256-call limit, an unavailable call journal) is recorded as a definite, free refusal; the service call journal and the checkpoint's attempt ledger record the same calls from two sides (one source is the service-parity wave, N-SVC).

## Verification commands

```sh
python -m pytest -q
PYTHONPATH=. python scripts/verify-fabric-contract.py /path/to/clean/pinned/fabric-agent-contract
npm ci --ignore-scripts
npx playwright install webkit
npm run test:dashboard
```

The browser check uses a disposable service/data directory and WebKit. It never requires provider keys or calls paid providers. Native host discovery/open, schema checks, local execution and paid-provider acceptance are separate receipts.
