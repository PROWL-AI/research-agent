# Prowl Research Agent

Runbook-driven research agent. It follows structured **research runbooks** (SaaS
competitor teardowns, ads & creative research, subscription-app audits, market
sizing, equity research, SEO, AI visibility and more), calls the
[Prowl](https://prowl.chat) MCP tool bank (440+ data tools: SEO, ads libraries,
reviews, scraping, app intelligence, LLM cross-checks), keeps every fact in an
**evidence ledger**, and produces reports where every number traces to a source.

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
- `RESEARCH_RUNS_DIR` — where runs are written (default `./runs` relative to
  the server process; set it explicitly in MCP client configs).
- `RESEARCH_NO_SUBAGENTS=1` — force sequential execution (no worker fan-out).

Exit codes: `run` exits 1 when the run ends `partial` (budget or failure —
the report says why); `rewrite` exits 1 when lint issues remain; input and
usage errors exit 2. `list-runbooks`, `status`, `report`, `export` exit 0 on
success.

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
the checkpoint shows `complete`/`partial`, and fetch the result with
`research.get_report(run_id)`. Use `wait=true` only when the caller can block
for the whole run.

First real run (makes billed Prowl calls, respects the runbook budget):

```bash
prowl-research run saas-competitor-teardown --competitors example.com,rival.com
```

Expected: a markdown report under `runs/<id>/report.md` plus an HTML export,
with a source log and confidence ladder.

### Develop

```bash
pytest                                  # unit tests + runbook validation (offline)
python scripts/validate_runbooks.py     # frontmatter + tool names vs live Prowl catalog (needs PROWL_API_KEY)
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

- Every number in a report must exist in the evidence ledger with a source
  (two independent sources or a verbatim quote). No ledger entry, no number.
- Runbooks declare their **tool allowlist** and **budget**
  (`max_tool_calls` / `max_usd` / `max_minutes`). On budget exhaustion the agent
  emits a partial report that marks what is missing — it never fails silently.
- Charts are rendered deterministically from ledger data, never described by
  the LLM.

## License

MIT — see [LICENSE](LICENSE).
