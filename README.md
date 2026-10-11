# Prowl Research Agent

Runbook-driven research agent. It follows structured **research runbooks** (SaaS
competitor teardowns, ads & creative research, subscription-app audits, market
sizing, equity research, SEO, AI visibility and more), calls the
[Prowl](https://prowl.chat) MCP tool bank (440+ data tools: SEO, ads libraries,
reviews, scraping, app intelligence, LLM cross-checks), stores extracted claims in an
**evidence ledger**, and produces reports with source citations and verification disclosures.

It is a CLI for humans and has two MCP surfaces for agents:

- the **Fabric service** (`prowl-research-service`, HTTP MCP at
  `http://127.0.0.1:18764/mcp`, the connection `fabric-agent.json` declares) —
  7 tools: `research.run`, `research.tools.call`, `research.tutorial`,
  `research.list_runbooks`, `research.artifact.get`, `fabric.job.get`,
  `fabric.job.cancel` (see [Fabric service](#fabric-service-and-operator-dashboard));
- the legacy local **stdio MCP server** (`prowl-research mcp`) — 4 tools:
  `research.run`, `research.list_runbooks`, `research.get_status`,
  `research.get_report`.

## Quick start for a new teammate

### Install

```bash
git clone https://github.com/PROWL-AI/research-agent.git
cd research-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure

Two keys, both via environment (key names only — values never in the repo):

- `PROWL_API_KEY` — your Prowl API key (`prowl_…`), billed per tool call.
  Get one at https://prowl.chat.
- `OPENROUTER_API_KEY` — the agent's own LLM (planning, synthesis, writing).
  Any OpenAI-compatible endpoint works: set `RESEARCH_LLM_BASE_URL` /
  `RESEARCH_LLM_API_KEY` / `RESEARCH_LLM_MODEL` to override.

Other environment knobs (all optional):

- `PROWL_MCP_URL` — Prowl MCP endpoint (default `https://prowl.chat/mcp`).
- `RESEARCH_LLM_MODEL_STRONG` — the strong-tier model (planning, writing,
  repair); `RESEARCH_LLM_MODEL` covers the cheap tier.
- `RESEARCH_RUNS_DIR` — where runs are written, for the stdio MCP server and
  every CLI command alike (`run`, `status`, `report`, `rewrite`, `export`,
  `prune`). Default `./runs` relative to the process; set it explicitly in MCP
  client configs.
- `RESEARCH_NO_SUBAGENTS=1` — force sequential execution (no worker fan-out).
- `RESEARCH_PROWL_CALL_TIMEOUT_S` — read timeout in seconds for each Prowl
  MCP call (default 180; a hung server fails the call instead of parking it).

CLI subcommands: `run <runbook> [--run-id <id>] [--key value …]`,
`list-runbooks`, `status <run_id>`, `report <run_id>`, `rewrite <run_id>`,
`export <run_id> [--format html|md]`, `prune [--older-than 30d] [--keep-last N]
[--yes]`, `validate [--online]`, `mcp`.

Exit codes: `run` exits 1 when the run ends `partial` (budget or failure —
the report says why); `rewrite` exits 1 when lint issues remain; `validate`
exits 0 when all runbooks are valid, 1 when a runbook fails validation, 2 on
usage or network/config errors (CI can tell "runbook invalid" apart from
"catalog unreachable"); other input and usage errors exit 2.
`list-runbooks`, `status`, `report`, `export`, `prune` exit 0 on success; `mcp`
serves on stdio until stopped.

`runs/` grows forever unless you prune it: `prune` lists runs older than
`--older-than` (by checkpoint `created_at`, default 30d) without deleting
anything; pass `--yes` to actually delete. `--keep-last N` always spares the N
newest runs, and any run whose `.lock` is held by a live process is skipped.

### MCP

Register the agent as an MCP server (stdio) in any MCP client:

```json
{
  "mcpServers": {
    "research-agent": {
      "command": "prowl-research",
      "args": ["mcp"],
      "env": { "PROWL_API_KEY": "prowl_…", "OPENROUTER_API_KEY": "…" }
    }
  }
}
```

The stdio server exposes four tools: `research.run`, `research.list_runbooks`,
`research.get_status`, `research.get_report`. It is the legacy local surface;
the Fabric bundle points at the HTTP service, which exposes seven (listed at
the top of this file).

Proving tool call (verifies install and registration; needs **no keys** and
makes **no billed calls**):

```
research.list_runbooks()
```

Expected: the runbook list (`saas-competitor-teardown`, …) with inputs and
budgets. `research.get_status` and `research.get_report` are key-free too —
only `research.run` requires the keys above (it fails fast, naming the missing
env var, before spending anything).

Runs take minutes, so for long runs prefer the job pattern: call
`research.run` with `wait=false` (the default) to get `{run_id, status:
"running"}` back immediately, then poll `research.get_status(run_id)` until
the checkpoint shows `complete`, `partial`, `failed`, or `interrupted`.
`failed`/`interrupted` require inspecting the checkpoint; a report may not exist.
For `complete`/`partial`, fetch the result with
`research.get_report(run_id)`. Use `wait=true` only when the caller can block
for the whole run.

Next to `status`, every terminal state carries a `terminal_code` saying *why*
the run stopped (`null` while it is live). The set is closed:

| `terminal_code` | `status` | meaning |
|---|---|---|
| `completed` | `complete` (or `partial` on a resume that kept earlier skip disclosures) | every step ran |
| `budget_tools` / `budget_usd` / `budget_minutes` | `partial` | a runbook budget ran out; the report marks what is missing |
| `budget_llm` | `partial` | LLM-spend budget (reserved; not set yet) |
| `step_failed` | `partial` | a step failed hard or a worker crashed |
| `evidence_incomplete` | — | evidence could not be persisted (reserved; not set yet) |
| `cancelled` | `partial` | any cancellation of the owning task: a caller or service cancel, the service timeout (job error `timeout`), Ctrl-C, a client closing its session or a graceful service shutdown |
| `error` | `failed` | an exception escaped the run; `stop_reason` carries it |
| `interrupted` | `interrupted` | the owning process died without a terminal write (a hard kill or crash); written by reconciliation, resumable |

Run state has exactly one writer: the process holding the run's lock
(`runs/<id>/.lock`). The orchestrator records `cancelled`/`error` itself before
releasing the lock; a second process on the same run is refused
(`run … is locked by another process`) and writes nothing — on stdio MCP the
refusal is returned synchronously, also for `wait=false`. `get_status` reports
`active` (some process holds the run lock) and `orphaned` (`running`, no
live owner anywhere). `interrupted` is
written by reconciliation — at stdio server start, at CLI `run`/`status`, and
at Fabric service start — and only for a `running` checkpoint whose lock is
free. `get_status` also reports `has_checkpoint`: `false` while a run accepted
by this server is still starting, or when it failed or was cancelled before it
took the run lock (the status then comes from the in-process job and
disappears with it).

First real run (makes billed Prowl calls; see budget limits below):

```bash
prowl-research run saas-competitor-teardown --competitors example.com,rival.com
```

Expected: a markdown report under `runs/<id>/report.md` plus an HTML export,
with a source log and confidence ladder.

### Develop

```bash
pytest                                  # unit tests + runbook validation (offline)
python scripts/validate_runbooks.py --online  # frontmatter + tool names vs live Prowl catalog (needs PROWL_API_KEY)
python evals/judge.py --run runs/<id>   # 5-dimension quality rubric for a finished run
```

Authoring a new runbook: `docs/runbook-authoring.md`.
Architecture decisions and inherited traps: `docs/knowledge-pack.md`.

## How it works

```
runbook (SKILL.md)  →  brief  →  plan  →  parallel research sub-agents
                     (data segments; transforms stay on the lead)
                     →  evidence ledger  →  writer + citation-repair loop
                     →  citation verification pass  →  markdown + HTML
```

- Runbooks ask for sourced numbers and triangulation. The writer consumes the
  evidence ledger and runs citation repair/verification, but this is not a
  guarantee that every fact is true or has two independent sources. Inspect
  the report's verification disclosures and source evidence before relying on it.
- Runbooks declare their **tool allowlist** and **budget**
  (`max_tool_calls` / `max_usd` / `max_minutes`). On budget exhaustion the agent
  emits a partial report that marks what is missing — it never fails silently.
  Budgets cap **Prowl tool calls only**: the agent's own LLM usage (planning,
  claim extraction, transforms, writing, citation repair) is billed by your
  LLM provider on top of `max_usd` — it is metered, not capped, and reported
  under `stats.llm_usage` in every run's output.
- Charts are rendered deterministically from ledger data, never described by
  the LLM.

## Current verification and resume limits

The [deep agent audit](docs/reports/2026-10-10-agent-deep-audit/README.md) adds
seven defects: lifecycle ownership (KA-06 — addressed in wave 1 by the
run-lock ownership above; certification pending), false evidence verification, hidden artifact/extraction failures and
budget accounting across mixed receipts/resume.
Its explicit probes (`PYTHONPATH=tests:. .venv/bin/python -m pytest -q docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py`) are expected to fail until waves 2–3 close KA-07…KA-12; the KA-06 cases and the three controls pass.
The [2026-10-10 handoff](docs/HANDOFF.md) links the remediation plan and records the audited source revision,
checks and next repair tasks. The offline suite is `.venv/bin/python -m pytest
tests/ -q` (network-free); its pass count is a fact about one revision, so it is
recorded with that revision in the handoff rather than here. A green run does
not establish live provider quality or Fabric host acceptance.

Resume currently has confirmed gaps: pruning a changed tool catalog can shift
step indices and skip pending work; a worker failure marks unstarted tail steps
completed; and a worker writes its checkpoint before adding successful completion.
These can omit work or replay a previously executed step after a crash. Inspect
checkpoint, raw artifacts and remaining steps before resuming a paid run. A stable
caller idempotency key alone does not guarantee exactly-once execution or billing.
See the handoff for source locations and reproducible acceptance tests.

Finance/subscription live acceptance remains unverified. `max_usd` limits the
Prowl tool-call budget, with concurrent in-flight calls potentially overshooting
it; it is not a cap on the separate LLM provider spend.

## Fabric service and operator dashboard

The separate `prowl-research-service` entry point adds durable jobs, observed tool/LLM receipts, human decisions and a service-owned dashboard for Fabric Dashboards. It reuses the existing research core. See [Fabric setup and architecture](docs/FABRIC.md), [dashboard design](docs/design/fabric-dashboard.md), and [current verification/handoff](docs/evidence/fabric-dashboard/HANDOFF.md). Legacy CLI/stdio and their existing run directories remain separate entry points.

## License

MIT — see [LICENSE](LICENSE).
