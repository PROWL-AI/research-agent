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

Proving tool call (verifies install + both keys end to end):

```bash
prowl-research list-runbooks
```

Expected: a table of runbooks (`saas-competitor-teardown`, `ads-creative-research`, …)
with their budgets. This makes no billed calls.

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
                     →  evidence ledger  →  one-shot writer
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
