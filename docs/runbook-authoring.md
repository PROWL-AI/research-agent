# Authoring a runbook

A runbook is a complete research playbook for one scenario. The agent's
planner reads it as doctrine; the validator checks it against the live tool
catalog; the judge scores its output sections. Write all three audiences at
once.

## File layout

```
research_agent/runbooks/<name>/
└── SKILL.md            # required; frontmatter + body
    references/         # optional; per-step detail loaded on demand
    scripts/            # optional; deterministic helpers
```

## Frontmatter contract

```yaml
---
name: <same as directory>
description: >- 
  What it does + WHEN to use it, for an agent choosing among runbooks.
  2-4 sentences. Name the trigger phrasings users would say.
version: "1.0"
inputs:
  - { name: target, type: "domain", required: true, doc: "..." }
tools: [exact, tool, names]        # allowlist — only these may be planned
budget: { max_tool_calls: 60, max_usd: 2.00, max_minutes: 25 }
outputs: { report_template: <kebab>, formats: [markdown, html] }
effort: deep                    # optional: lookup | comparison | deep
---
```

`effort` controls sub-agent fan-out: data steps between two Transform
markers run in parallel workers (`lookup` = 1 inline agent, `comparison` = 3,
`deep` = 5). Omit it to derive the class from `max_tool_calls` (≤15 lookup,
≤45 comparison, above that deep) — declaring it is for runbooks whose budget
misleads (a 60-call runbook of strictly serial steps wants `effort: lookup`).
Set `RESEARCH_NO_SUBAGENTS=1` to force sequential execution for a run.

Rules:

- Input types: `domain`, `string`, `list[domain]`. Quote any type containing
  brackets (YAML flow-mapping pitfall).
- Every tool name must exist in the live Prowl catalog —
  `python scripts/validate_runbooks.py --online` is authoritative; the
  default `--offline` mode uses `evals/fixtures/live_catalog_snapshot.json`.
- The allowlist is the tool-selection mechanism: ~20-60 tools that cover the
  scenario, nothing more — lean lookup runbooks may go lower, broad audits a
  few higher. If you need a tool that doesn't exist, that's a
  finding — report it, don't plan around it.
- Budgets are enforced per step on `max_tool_calls` (every billed
  `prowl_call_tool` dispatch — failed ones included, the server charges them
  too) and on `max_minutes` (wall time since the run was created, across
  resumes). Under worker fan-out the tool-call check is advisory: racing
  workers can overshoot by at most `workers − 1` calls before the stop
  lands. `max_usd` is enforced on the server's billing data, falling back to
  catalog price hints (marked "estimated" in stats) when the server returns
  none. All three budgets cap **Prowl tool spend only** — the agent's own LLM
  calls (planning, claim extraction, transforms, writing, citation repair)
  are metered separately and reported under `stats.llm_usage`; `max_usd` does
  not bound them. Size budgets for the scenario's real cost, not
  aspirationally, and give the runbook a drop order for the day the fan-out
  outgrows them.

## Body grammar

Follow the flagship (`saas-competitor-teardown/SKILL.md`):

1. `# <Title>` + `**Goal:**` — one paragraph: the decision this research
   feeds, not the data it collects.
2. `## Principles (read first)` — 3-5 bullets of domain doctrine: what
   separates a great report from a generic one in this domain. These are the
   quality bar.
3. `## Sequence` — numbered steps. Each step: **Bold name** — tools in
   backticks with literal parameters where they matter;
   `Parallel:` / `Fan-out` / `Transform:` markers; `(on_error=skip)` on
   anything non-fatal. Steps are imperative and specific ("Extract top 5 by
   organic traffic"), never vague ("analyze competitors"). Prefer one batched
   call over per-item fan-out for bulk-capable tools. Transform steps are
   first-class: they run as LLM passes over prior artifacts and cost no tool
   calls.
4. `## Verification (hard rules)` — the numeric disciplines: triangulation
   (>=2 independent sources for key numbers), error bands on estimates,
   VERIFIED/ASSUMED tags, [CONFLICT] instead of silent averaging, LLM output
   never a primary source. Reference, don't re-derive.
5. `## Output instructions` — numbered required report sections. The first
   section is the decision summary; the last is always the Source log (tool +
   retrieval date per figure, confidence ladder, [CONFLICT] register, refresh
   recommendation). Every section should produce something someone acts on.
6. `## Guards (failure modes to refuse)` — 3-6 named shallow-research failure
   modes for this domain and the explicit refusal behavior. This is where
   institutional knowledge about bad research lives.

## The doctrine checklist (what makes a runbook great)

- **Order is the framework**: understand → quantify → risk → synthesis.
  Verdicts never precede evidence sections.
- **Behavioral signals beat stated signals**: sustained ad spend > traffic;
  review velocity > rating; footnotes > narrative.
- **Benchmarks only with their qualifiers** (trial conversion without paywall
  type is meaningless; capture rate without horizon is meaningless).
- **Historical data or it didn't happen**: 12-month trends; a snapshot is a
  pulse-less diagnosis.
- **The output is a decision artifact** — battlecard, testable brief,
  defensible SOM, priced bear case — plus a refresh cadence.

## Before committing a runbook

```bash
python scripts/validate_runbooks.py --offline   # frontmatter + tool names
python -m pytest -q                              # engine + fixture suite
```

Then one real run on a small input and `python evals/judge.py --run runs/<id>`
>= 0.7. A runbook that has never been run is a draft.
