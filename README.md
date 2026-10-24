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
  repair; default `xiaomi/mimo-v2.6-pro`); `RESEARCH_LLM_MODEL` covers the cheap
  tier (claim extraction, transforms, citation checks; default
  `deepseek/deepseek-v4.1-flash`); `RESEARCH_JUDGE_MODEL` the eval judge (default
  `anthropic/claude-haiku-5.5` — another vendor than the default writer, so a
  report is not graded by the family that wrote it; keep that true if you change
  the writer). Defaults apply to new installs and the environment: an installed
  service keeps the models saved in its settings. Judge scores before and after
  the judge default changed (2026-10-17, from the strong model) are not
  comparable. Prices for the cost estimate are in `research_agent/pricing.py`
  (OpenRouter catalog, read 2026-10-17; `scripts/check_prices.py` re-reads it).
- `RESEARCH_MAX_LLM_USD` — the run's LLM spend ceiling (see "How it works").
  Claim extraction and citation checks send `reasoning: {enabled: false}` to OpenRouter: on the cheap
  tier reasoning could spend the whole 2000-token output budget before any JSON, and an answer cut that
  way is not retried, because the same request is cut the same way (B-050, measured 2026-10-18/20).
- `RESEARCH_RUNS_DIR` — where runs are written, for the stdio MCP server and
  every CLI command alike (`run`, `status`, `report`, `rewrite`, `export`,
  `prune`). Default `./runs` relative to the process; set it explicitly in MCP
  client configs.
- `RESEARCH_NO_SUBAGENTS=1` — force sequential execution (no worker fan-out).
- `RESEARCH_PROWL_CALL_TIMEOUT_S` — read timeout in seconds for each Prowl
  MCP call (default 180; a hung server fails the call instead of parking it).

CLI subcommands: `run <runbook> [--run-id <id>] [--max-llm-usd <usd>] [--key value …]`,
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
| `completed` | `complete` (or `partial` when a disclosed omission remains, e.g. a step excluded because its tool left the catalog) | every runnable step ran and its evidence was saved |
| `budget_tools` / `budget_usd` / `budget_minutes` | `partial` | a runbook budget ran out; the report marks what is missing |
| `budget_llm` | `partial` | the next LLM call would cross `max_llm_usd` (minus the writer reserve for research stages), or a report-stage call (writer, repair, citation check) was refused; the report is written from what was gathered, or is the evidence ledger listed |
| `step_failed` | `partial` | a required step failed: refused while the run went on to the writer (B-049), or a refusal that stopped the run (empty wallet, the service's own limit, five refusals of required steps in a row), or a worker crashed; `stop_reason` says which and names the steps |
| `evidence_incomplete` | `partial` | evidence is missing with no other stop: a claim extraction failed (the resume finishes it from the saved raw, no new paid call), or a required step's raw could not be written (the resume fetches it again — a new, paid call; an optional step is `skipped_on_error` instead) |
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
free. A run whose version-1 checkpoint cannot be migrated without guessing is
reported with `status: needs_attention` and the reason in `stop_reason`: its report
stays readable and exportable, it can be pruned, and `research.run` refuses to
resume it. `get_status` also reports `has_checkpoint`: `false` while a run accepted
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
python evals/judge.py --run runs/<id>   # 5-dimension quality rubric for a finished run (exit 0 pass, 1 fail, 2 judge error)
python evals/calibrate.py               # the judge against planted-defect fixtures (offline; --live spends)
```

The judge's verdict is vetoed by defects the code proves — a citation of no claim; a quotation no
cited claim backs; a sentence whose metric figure none of its cited claims carries (a sentence the writer marked
"derived" excepted); a conflicting claim cited on a line without the upper-case `CONFLICT` tag and
outside a conflict register (rows under a "Source log" heading are provenance, not findings); a
citation tagged VERIFIED whose claim the ledger does not hold as verified; a partial run that does not say "partial" before its first section — so a
lenient model cannot pass them. An uncited figure lowers the citation score instead. Each judge LLM
call is checked by estimate against `--max-usd` (default 0.50) before it is sent and recorded in
`<run>/judge-ledger.json`, never in the run's checkpoint. The judge needs only an LLM key.

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
- **The repair pass fixes what the judge would veto.** Besides the citation lint, the writer's repair pass gets the
  defects the eval judge proves by code (`research_agent/agent/report_checks.py`): a VERIFIED tag on a claim the ledger
  does not hold as verified, a conflict cited without its [CONFLICT] tag, a quotation no cited claim holds, a figure no
  cited claim carries. `lint_issues_before`/`lint_issues_after` count both (B-057). The repair pass sends only the lines
  at fault and patches the lines it gets back (`L<n>: …`), so a long report is not rewritten whole (B-059).
  The citation lint also flags drafting residue inside a citation (a question mark, a note or a nested bracket, such
  as `[C186? no, [C237]]`) as `malformed_citation`, which the repair pass rewrites to plain claim ids (B-068).
- **One refused step does not end the run.** A tool that is refused (no results, not found, a provider, scope or
  argument error) marks that step `failed` (or `skipped_on_error` when the plan marked it optional) with the
  server's reason, and the run goes on; with a refused required step it ends `partial` / `step_failed`, and the
  writer is told which steps were refused and why, so the report says what is missing. What still stops the run:
  an empty Prowl wallet (`insufficient_funds`), the service's own call limit or an unavailable call journal, a call
  whose outcome is unknown, five refusals of required steps in a row across the run (optional steps neither count
  nor reset it), and every budget. A budget stop keeps its own `terminal_code`; its `stop_reason` also names the
  refused steps. A resume asks every `failed` step again (a new attempt, which the provider may bill again).
  After an empty wallet or the service's own limit, the other workers send no further step (B-092), and a
  worker crash is recorded when it happens, so the others see the stop at once (B-091).
- **A value only an earlier step returns is a placeholder.** The plan is written before any tool runs, so an
  argument such as an app's numeric store id is planned as `{{headspace_apple_id}}`, with a transform before the
  step that names it. That transform ends its note with a fenced `bindings` block; a value is kept only when a raw
  artifact of the run states it verbatim (`checkpoint.bindings`), and the step sends the filled arguments
  (`bound_arguments`; `arguments` keeps the plan as written). A placeholder nobody resolved is never sent: the step
  is `skipped_on_error` (or `failed`, when required) with `not sent: no earlier step resolved {{name}}`, and it does
  not count toward the refusals in a row (B-065).
- **A whole earlier result is a reference.** A step that needs an earlier step's whole output (a scraped page for an
  analysis tool) writes `{{output:<step name in snake_case>}}`; the stored raw artifact of the completed data step of
  that name (sha256-checked; JSON compact and without the server's billing and timing) is sent in its place, cut at
  16 000 characters per step, shared by its references, with a `[cut: N more characters]` marker (`bindings.OUTPUT_CAP`). The referencing step runs one level
  after the step it names while the other steps keep running beside the producer, and a name two steps share leaves
  it unresolved (`names two steps`). The reference is judged as the plan wrote it, so provider text inside the output is never
  taken for template text; a reference to a step that did not complete is not sent (B-074).
- **Template text and known-refused values are not sent either.** Live runs showed the planner writing other shapes
  than `{{name}}` (`[substitute landing_page_url of ...]`, `<video_id from youtube_search ...>`,
  `{youtube_search.latest_video_id}`, `PLACEHOLDER_FROM_STEP_22`); providers billed each one, and an LLM-answer tool
  even "completed" on the literal text. Such a step is `skipped_on_error` (or `failed`) with `not sent: an argument
  holds template text, not a value: ...` (B-070). A value a provider is known to refuse while its schema is silent
  (`research_agent/agent/tool_limits.py`, each limit with its source: `tiktok_ads_library` takes `country` only as
  `all` or a European code) is told to the planner and, if planned anyway, not sent:
  `not sent: <tool> does not take country='US' (a known provider limit)` (B-071). Neither counts as a refusal, the
  writer reports such a step as a gap of the run (not the source's answer), in a partial run and in a complete one,
  and is told what a limited source covers (TikTok: Europe only); an accepted value is sent in the provider's spelling;
  `research.tools.call` refuses a known-refused value before a job exists and again at dispatch.
- Runbooks declare their **tool allowlist** and **budget**
  (`max_tool_calls` / `max_usd` / `max_minutes`). On budget exhaustion the agent
  emits a partial report that marks what is missing — it never fails silently.
  The budget is read from the run's **attempt ledger**: every dispatched call is
  recorded before it is sent (so in-flight calls count against `max_tool_calls`),
  and its cost is stored when it returns or fails — a billed failure costs money
  too. Spend = server-reported actual costs + estimates for calls without one
  (the catalog price, else the runbook's per-call share of `max_usd`, never zero);
  `stats.cost_source` says `server`, `mixed`, `estimate`, or `null` before any tool attempt.
  A step that reads an earlier step's whole output keeps one tool call: unrelated steps of its block yield it first
  (`skipped_budget`, the reason says so), never its producer or a step whose outcome is unknown, and the
  `budget_tools` stop lands after the block (B-086). They yield only while the calls left still reach one such
  step after its pending producers (a producer that will not be sent is not counted); with fewer, plan order
  stands (B-087), and nothing yields once another worker has stopped the run (B-090).
  The runbook budget caps **Prowl tool calls**; the agent's own LLM spend
  (planning, claim extraction, transforms, writing, repair, citation checks) is
  capped separately by **`max_llm_usd`**: `--max-llm-usd` / MCP `max_llm_usd`,
  else `RESEARCH_MAX_LLM_USD`, else the cap a resumed run recorded, else the
  runbook's `budget.max_llm_usd`, else **USD 5**. It is a check **before every
  LLM HTTP attempt** (retries included), against an estimate of that call: the
  last call it admits can overshoot by its actual cost minus its estimate, so
  `stats.llm_budget.spend_usd` can end slightly above the cap. Each attempt is
  recorded in the attempt ledger with the provider's `usage.cost` (OpenRouter is
  asked for it), else a price-table estimate (`research_agent/pricing.py`; an
  unlisted model is priced at USD 15 / 75 per 1M tokens, above every listed
  model — never 0); an HTTP error response (429, 5xx) is recorded as unbilled.
  Research stages stop at the cap minus a writer reserve (25%, at most USD 1)
  with `terminal_code=budget_llm`, and once a research call is refused no further
  tool is dispatched; the writer, repair and citation passes may spend the
  reserve — a refusal there also ends the run `partial` / `budget_llm` — and if
  even that is gone the report is the evidence ledger as gathered. A resume reads
  the spend and cap already recorded (also after a re-plan) and keeps an
  existing report when it gathered nothing new and cannot afford a writer.
  `rewrite --max-llm-usd` spends from the same ledger. `stats.llm_budget` reports
  cap, reserve, spend, cost source and refused stages; `stats.llm_usage` the
  tokens.
- **Evidence statuses (ledger schema 2).** A claim's status is recomputed over
  its whole subject group on every change and on load, so it never depends on
  arrival order. `verified` needs either:
  - **span** — the claim's quote is found in the step's whole stored raw (its
    values or its JSON, sha256-checked on resume; a bare number is not a quote)
    and the value sits inside the quote on number boundaries (1200 is not in
    11,200). A span-verified claim is one source saying it; or
  - **corroboration** — two agreeing claims from two different steps with
    distinct known sources: different publishers (registrable domain of a URL
    the raw or the request actually names — an extractor-supplied URL that the
    raw does not contain is dropped) or different upstream data providers
    (delivery wrappers removed: `google_trends` and `serpapi_google_trends` are
    one Google Trends source).

  Never a source: a transform note and an LLM-answer tool (Perplexity, Gemini,
  Google AI mode/overview, `*_responses`) — their own text never span-verifies
  and they add no independence; a web search/scrape claim without a URL; a
  claim whose quote was not found. Two values that disagree make every valued
  claim of the group `conflict` (a missing unit is compatible with any unit;
  `$` and `USD` are one unit); a claim without a value never confirms or
  resolves one, and a chart over a conflicting claim is rejected. The
  extractor's own word never verifies; a v1 ledger's `verbatim` claim without a
  quote loads as `assumed` with the reason in `verification.detail`. Reports
  written before schema 2 keep their old tags — regenerate them with
  `rewrite_report`, which also re-saves the ledger; judge status shares are
  not comparable across this change. Events: `claim.verified`,
  `claim.conflict`, `claim.quote_not_found` (with `run_id`; under the service
  they go to `~/Library/Logs/prowl-research/events.log`, rotated at 5 × 5 MB, beside the service's own `job.*`, `service.*` and `config.changed` events with their severity and job id; the person-facing text stays on the dashboard).
- Charts are rendered deterministically from ledger data, never described by
  the LLM.

## Current verification and resume limits

The [deep agent audit](docs/reports/2026-10-10-agent-deep-audit/README.md) adds
seven defects: lifecycle ownership (KA-06 — wave 1), hidden artifact/extraction
failures and budget accounting across mixed receipts/resume (KA-10…KA-12 — wave 2),
and false evidence verification (KA-07…KA-09 — wave 3, ledger schema 2). The ported
contracts live in `tests/test_ka_contracts.py`. The historical probe file stays as the
audit's cut: 11 of its 12 cases pass; its success control asserts a cwd-relative
`raw_ref`, which wave 2 replaced with a run-dir-relative one.
The [2026-10-10 handoff](docs/HANDOFF.md) links the remediation plan and records the audited source revision and
checks (its repair tasks are history; the handoff's first entry is current). The offline suite is `.venv/bin/python -m pytest
tests/ -q` (network-free); its pass count is a fact about one revision, so it is
recorded with that revision in the handoff rather than here. A green run does
not establish live provider quality or Fabric host acceptance.

Resume works from the checkpoint's step records (schema version 2, wave 2):
every step has an immutable `step_id` assigned when the plan is made, so a tool
leaving the catalog excludes that step by id and shifts nothing. A step's state is
`pending`, `dispatching`, `outcome_unknown`, `raw_saved`, `completed`, `failed`,
`skipped_on_error`, `skipped_budget` or `excluded`. A resume runs `pending` and
`failed` steps, finishes `raw_saved` steps from their saved raw **without a new
paid call**, and re-sends an `outcome_unknown` call with the **same idempotency
key** (`<run_id>:<step_id>:<attempt>`) so the server can replay it instead of
billing twice. A client read timeout counts as an unknown outcome, never as a
refusal, and a budget stop leaves such a step `outcome_unknown` so its key
survives. **The Prowl server deduplicates a re-sent key only within its retry
window (15 minutes by default):** a resume after that may be charged again, and
the re-send is still recorded as one attempt — the budget then undercounts by that
call. A step migrated from version 1 whose dispatch may have reached the server is
first re-sent under its v1 key (`<run_id>:<index>:<tool>`). Version-1 checkpoints are migrated on load; a v1 state that cannot be mapped
without guessing is reported `needs_attention` (above) and never resumed.
**The upgrade is one-way for a run directory:** the first save of a migrated run
keeps its v1 file as `checkpoint.v1.json`, but a pre-v2 build reading the new
`checkpoint.json` re-plans (and re-bills) the run. Restart stdio sessions and
reinstall the Fabric service before resuming runs a v2 build has touched; a build
refuses a checkpoint whose `schema_version` is newer than it understands.

**Status and checkpoint shape (schema 2).** `research.get_status` returns
`completed_steps` as step ids (not indexes), `planned_steps` without excluded
steps, `step_counts` per state, `skipped_steps` entries carrying `step_id`,
`index`, `step`, `tool`, `reason` and `state` (while a run is live, steps still in
flight are not listed), and `counters` with `data_calls`, `attempted_calls`,
`cost_usd`, `cost_estimate_usd`, `spend_usd` and `cost_unknown_attempts` (the same
keys appear in a run's `stats`). `stats.cost_source` is `server`, `mixed`,
`estimate` or `null` (no tool attempt yet). `checkpoint.json` (also what
`research.artifact.get` serves) holds `plan_raw`, `steps` and `attempts`; it no
longer persists `plan`, `completed_steps`, `skipped_steps` or `counters`.
Crash injection at every durable write is covered by `tests/test_durability.py`.

Finance/subscription live acceptance remains unverified. With several workers,
the USD check can still overshoot by the in-flight calls' unknown cost (each
counts at its estimate); `max_usd` is not a cap on the separate LLM provider
spend.

## Fabric service and operator dashboard

The separate `prowl-research-service` entry point adds durable jobs, observed tool/LLM receipts, human decisions and a service-owned dashboard for Fabric Dashboards. It reuses the existing research core. See [Fabric setup and architecture](docs/FABRIC.md), [dashboard design](docs/design/fabric-dashboard.md), the [current handoff](docs/HANDOFF.md) and [verification](docs/evidence/fabric-dashboard/VERIFICATION.md) (waves 1 to 5 history: [Fabric handoff](docs/evidence/fabric-dashboard/HANDOFF.md)). Legacy CLI/stdio and their existing run directories remain separate entry points. Other agents on this machine reach it through the `prowl` gateway profile with the service's own agent token from loopback (tier T0, no delegation token needed). The callee side of Fabric hub delegation tokens (DEC-0039) is built, but a presented token is refused until an issuer is configured, and the hub publishes no keys yet (KA-G03). An ended research job is continued with `research.run` + `resumeJobId` without paying again for what was already paid ([FABRIC.md](docs/FABRIC.md#resume-b-039)).

## License

MIT — see [LICENSE](LICENSE).
