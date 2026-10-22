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
- Budgets are enforced before every dispatch from the run's attempt ledger.
  `max_tool_calls` counts every dispatched `prowl_call_tool` attempt — failed
  ones included (the server charges them too), and in-flight ones, because an
  attempt is recorded before it is sent. `max_minutes` is wall time since the
  run was created, across resumes. `max_usd` is checked against spend = the
  server-reported actual cost of each attempt plus an estimate for every
  attempt without one (the catalog price hint, else `max_usd / max_tool_calls`
  — never zero); a known cost never discards the other attempts' estimates, and
  a billed failure's cost survives a resume. Under worker fan-out the USD check
  can still overshoot by the in-flight calls' unknown cost. All three budgets
  cap **Prowl tool spend** — the agent's own LLM calls (planning, claim
  extraction, transforms, writing, citation repair) are capped by the optional
  `max_llm_usd` budget key (a caller or `RESEARCH_MAX_LLM_USD` overrides it; the
  default is USD 5) and reported under `stats.llm_budget`; `max_usd` does not
  bound them. Set `max_llm_usd` when a runbook's synthesis is heavy (many
  transforms, long reports) so the default does not stop it early. Size budgets
  for the scenario's real cost, not aspirationally, and give the runbook a drop
  order for the day the fan-out outgrows them.

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
   steps the report can do without. No single refused step stops a run
   (B-049): a required step that is refused leaves the report `partial` and is
   asked again on resume; an optional one (`on_error=skip`) lets the run end
   `complete` and is not asked again. Only an empty wallet, the service's own
   limit, an unknown outcome, five required refusals in a row or a budget stop
   the run. Steps are imperative and specific ("Extract top 5 by
   organic traffic"), never vague ("analyze competitors"). Prefer one batched
   call over per-item fan-out for bulk-capable tools. Transform steps are
   first-class: they run as LLM passes over prior artifacts and cost no tool
   calls. When a later step needs a value only an earlier step returns (a
   store id, a package name), say in the runbook which step resolves it and
   that a Transform hands it on: the planner writes the argument as
   `{{name}}` and the transform returns it; an unresolved placeholder is
   not sent (B-065), and neither is any other template text in an
   argument (B-070). When a provider refuses a value its schema does not
   rule out, add the limit, with its source, to
   `research_agent/agent/tool_limits.py` rather than to one runbook: every
   planner that may call the tool is told it (B-071). When the limit also
   narrows what a result covers (a market, a period), fill its `coverage`
   (an instruction to the writer, which never sees step arguments) and its
   `statement` (the same fact for a person: the dashboard's «Охват
   источника», a direct result's `coverage` and `notVerified`, and the
   evidence-only fallback report's «Source coverage» lines).
4. `## Verification (hard rules)` — the numeric disciplines: triangulation
   (>=2 independent sources for key numbers), error bands on estimates,
   VERIFIED/ASSUMED tags, [CONFLICT] instead of silent averaging, LLM output
   never a primary source. Reference, don't re-derive. The ledger enforces the
   meaning of VERIFIED (schema 2): a claim is verified only when its quote is
   found in the step's stored raw with the value inside it (one source saying
   it), or when two agreeing claims from different steps come from
   **different publishers** (registrable domain of a URL the raw names) or
   **different upstream data providers** (e.g. `spyfu` vs `dataforseo`; two
   delivery vendors of one Google dataset — `google_trends` and
   `serpapi_google_trends` — are ONE source). Two tools reading one URL and two
   endpoints of one provider are one source; a transform and an LLM-answer tool
   count as NO source. Design triangulation steps across providers or
   publishers, not across delivery tools of one upstream.
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
exits 0 (PASS: weighted total >= 0.7 and no code-proven defect). A runbook that has never been run is a draft.
