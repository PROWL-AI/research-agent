# Prowl Research Agent

Runbook-driven research agent. It follows structured **research runbooks** (SaaS
competitor teardowns, ads & creative research, subscription-app audits, market
sizing, equity research, SEO, AI visibility and more), calls the
[Prowl](https://prowl.chat) MCP tool bank (440+ data tools: SEO, ads libraries,
reviews, scraping, app intelligence, LLM cross-checks), stores extracted claims in an
**evidence ledger**, and produces reports with source citations and verification disclosures.

It is both a CLI for humans and an **MCP server** for agents
(`research.run`, `research.list_runbooks`, `research.get_report`,
`research.get_status`).

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
- `RESEARCH_RUNS_DIR` — where runs are written (MCP server only; the CLI
  always uses `./runs`). Default `./runs` relative to the server process;
  set it explicitly in MCP client configs.
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

The server exposes four tools: `research.run`, `research.list_runbooks`,
`research.get_status`, `research.get_report`.

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

The [2026-10-10 handoff](docs/HANDOFF.md) records the audited source revision,
checks and next repair tasks. The offline suite passed 304 tests at `1dced8e`;
this does not establish live provider quality or Fabric host acceptance.

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

## License

MIT — see [LICENSE](LICENSE).
