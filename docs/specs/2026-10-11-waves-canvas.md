# research-agent — target-state canvas and wave plan

Date: 2026-10-11. Mode: `/task-pipeline waves`. Measured on `c0dfb6e`.
Inventory (every open item, machine-readable): [`2026-10-11-waves-inventory.json`](2026-10-11-waves-inventory.json),
waves assigned by [`scripts/plan/assign_waves.py`](../../scripts/plan/assign_waves.py) (`--check` exits 1 when stale).
Board: [`../evidence/backlog.md`](../evidence/backlog.md). Defect source: [deep audit](../reports/2026-10-10-agent-deep-audit/README.md)
and `PROWL-AI/prowl-app` `docs/superpowers/plans/2026-10-10-kimi-remediation.md` (canonical KA queue).

**The rule this canvas exists for:** every item is designed against the final shape of the whole
system first, and only then cut into waves. No wave builds a shape a later wave undoes.

## 0. Baseline (measured, not copied)

| Check | Result at `c0dfb6e` |
|---|---|
| `.venv/bin/python -m pytest tests/ -q` | 328 passed |
| deep probes `probe_agent_contracts.py` | 9 failed (KA-06×2, 07, 08, 09, 10×2, 11, 12), 3 controls passed |
| resume probes (prowl-app `probe_research_resume.py`) | 3 failed (KA-03, 04, 05) |
| `python -m research_agent validate` | all 14 runbooks valid |
| hosted CI | none exists (no `.github/workflows`) |
| Fabric service | installed at `891fbc9`, `degraded` (no Prowl key, no model key) |

## 1. Requirements (frozen; adding is free, removing needs the operator)

| REQ | In the operator's words (2026-10-11) | Verified by |
|---|---|---|
| REQ-01 | "решить все проблемы": every confirmed agent defect KA-03…KA-12 closed | each probe moved into `tests/` and green; full suite green on one SHA |
| REQ-02 | correct costs: an LLM spend limit (approved 2026-10-09 as `max_llm`) | test stops the next LLM call before the limit; retries/resume included |
| REQ-03 | "добавлены все логи": structured, secret-free logs for lifecycle, attempts, evidence, budget | `tests/test_events.py` asserts event names + no secret patterns |
| REQ-04 | "обновлена вся документация": docs match behaviour, same change as code | product-tier verification each wave; doc lint in close pass |
| REQ-05 | "пользоваться как человеку, так и агенту": CLI, stdio MCP, Fabric service and dashboard agree on states and money | scenarios CORE-* and SCN-* walked; service parity tests |
| REQ-06 | "связь с другими агентами": Fabric contract current (pin, DEC-0039 callee, kit, Observatory launch); cross-agent rows filed with owners | contract tests; owner acknowledgements recorded |
| REQ-07 | waves of build → independent validation (docs, business logic, implementation, seams, technical decision) → fix plan, until done | three blind tiers per node; close pass per wave; final independent observer |
| REQ-08 | "не останется багов": adjacent defects found by the survey fixed or recorded | inventory items B-003…B-031 closed or carried with a row |
| REQ-09 | the result proven against reality: calibrated judge, live finance + subscription runs, Fabric host chain | KA-G02 / KA-G03 receipts (needs operator: keys, money, host) |

## 2. Modules: as-is → to-be

### N-OWN — run ownership (wave 1)

**As-is.** The flock is held only inside `Orchestrator.run` (`orchestrator.py:225-269`). Terminal
writes happen outside it, keyed on checkpoint contents: MCP cancel/exception handlers
(`mcp_server.py:119-148`), startup reconciliation (`:327-354`, never checks the lock), CLI
`_mark_run_failed` (`__main__.py:163-182`), `rewrite_report` (`writer.py:463-492`). The lock
refusal itself lands in the MCP exception handler and rewrites the live owner's checkpoint to
`failed`. Service cancel/timeout (`service/runtime.py:186-190,221-226`) leaves
`runs/<job>/checkpoint.json` at `running` forever; nothing reconciles CLI or service run dirs.

**To-be.**
- One module `research_agent/evidence/runlock.py` owns the lock: `RunLock(run_dir)` with
  `acquire(blocking=False) -> bool`, context manager, `is_held_elsewhere(run_dir) -> bool`.
  `Orchestrator._acquire_run_lock` and CLI `prune` (`__main__.py:358-372`) use it.
- **`Orchestrator.run` is the only writer of lifecycle state while a run is live.** It catches
  `asyncio.CancelledError` and `Exception` inside the lock and writes the terminal state
  (`partial` + `terminal_code=cancelled`, `failed` + `terminal_code=error`) **before** releasing
  the lock, then re-raises. The MCP handlers, CLI and service runtime only report.
- Every writer outside a live run (startup reconciliation in stdio MCP, a new reconciliation
  in the CLI `status`/`run` entry and in the service `Store.recover`, `rewrite_report`) takes
  `RunLock.acquire(blocking=False)`. Held → it writes nothing and reports `active`. Acquired →
  it may write (`interrupted` for an orphaned `running` checkpoint), under the lock.
- A lock refusal never writes. Status reads never write.
- `Checkpoint` gains `terminal_code` (enum below) next to the existing `status`, `stop_reason`,
  `partial`. Names stay: renaming `stop_reason` would be an intermediate state for wave 2.
- **Structured events (REQ-03) start here** — `research_agent/events.py`:
  `emit(logger, event: str, **fields)` writes one line `event=<name> k=v …` at INFO/WARNING;
  values are scalars, strings truncated to 200 chars, and keys matching
  `key|token|secret|authorization|password` are refused (raise in tests, dropped with a
  warning in production). Every later wave uses it; no ad-hoc lifecycle log lines.

`terminal_code` enum (closed set, documented in README and the output schema description):
`completed`, `budget_tools`, `budget_usd`, `budget_minutes`, `budget_llm` (wave 4),
`step_failed`, `evidence_incomplete` (wave 2), `cancelled`, `error`, `interrupted`.

### N-STATE — checkpoint v2: step identity, state machine, durability (wave 2)

**As-is.** A step is its index in a plan re-filtered by `validate_plan` on every attempt
(`orchestrator.py:340`). `completed_steps: list[int]` mixes done, deliberately skipped, never
started and budget-skipped (`subagent.py:166-171,194-205,219-227`). Completion is appended after
the save (`subagent.py:250-261`). Raw-save and extraction failures are logged and the step still
completes (`subagent.py:249-267`). Raw files are `NN_tool.json`; idempotency keys
`run_id:index:tool` (`subagent.py:188`); `raw_ref` is absolute under the service and
CWD-relative under CLI.

**To-be — `Checkpoint` schema_version 2** (`evidence/store.py`):

```
Checkpoint v2
  schema_version: 2, run_id, runbook, status, stop_reason, partial, terminal_code,
  brief, plan_raw (as planned), created_at, updated_at, migrated_from: int | None
  steps:    [StepRecord]      # the plan as executed; order = execution order
  attempts: [AttemptRecord]   # N-COST
  stats:    {...}             # derived on save, never the source of truth
StepRecord
  step_id        "s-" + sha256(canonical_json({raw_index, tool, arguments}))[:12]; assigned once
                 at plan time, never re-derived, never renumbered
  raw_index, kind (data|transform), tool, arguments, step (label), on_error_skip
  state          pending | dispatching | outcome_unknown | raw_saved | completed |
                 failed | skipped_on_error | skipped_budget | excluded
  reason         free text for failed / skipped_* / excluded (excluded = plan validation or
                 catalog/allowlist drop, with the validator's reason)
  raw_ref        run-dir-relative path "raw/<step_id>_<tool>.json"; raw_sha256
  extraction     {status: pending|ok|empty|failed, error, claim_ids: [...]}
```

Rules:
- Plan validation runs **once**, when the plan is made; drops become `excluded` steps with the
  reason. On resume the persisted steps are authoritative. A tool that left the catalog or
  allowlist since then marks *that* step `excluded` by id; nothing shifts.
- Resume executes exactly the steps in `pending`, `outcome_unknown` (same idempotency key),
  `raw_saved` (extraction only, **no dispatch**) and `failed` when not `on_error_skip`.
  `completed`, `skipped_on_error`, `skipped_budget` (unless budget was raised), `excluded`
  never re-run.
- **Durable order per data step:** append AttemptRecord + `state=dispatching` + save →
  dispatch → finalize attempt in `finally` + save → atomic raw write (tmp + `os.replace`,
  sha256) → `raw_saved` + save → extract → ledger save (claim ids derived from
  `step_id` + ordinal, so a re-extraction replaces, never duplicates) → `completed` + save.
  A crash at any point leaves a state resume can act on without a second paid dispatch,
  except `dispatching` → `outcome_unknown`, which re-sends with the **same** key (KA-01
  replay at the parent makes that free once it lands; until then the attempt's cost is
  counted as unknown at its estimate — never as zero).
- Transform steps follow the same order (`save_markdown` becomes atomic; a failed transform is
  saved immediately — B-006, B-008).
- Terminal status: `complete` iff every step is `completed`, `skipped_on_error` (disclosed) —
  `excluded` and `skipped_budget` make it `partial` with their disclosure; any `failed`,
  `outcome_unknown`, `raw_saved`, `pending` or extraction `failed` makes it `partial`
  (`terminal_code=evidence_incomplete` when only evidence is missing).
- Idempotency key: `f"{run_id}:{step_id}:{attempt_no}"`. `attempt_no` increments only after a
  definite outcome (ok / refused / transport error with known cost); an `outcome_unknown`
  attempt is retried with the same number.
- Readers that used `completed_steps` (`mcp_server._status_dict:286`, `get_report:311`, CLI
  `status`, `report/render.py`, service `artifact()`) read `Checkpoint.step_counts()` /
  `completed_step_ids()`. v2 does not persist `completed_steps`.

**Migration v1 → v2** (`evidence/migrate.py`, run on load, writes `migrated_from: 1`):
rebuild the v1 validated list as `plan` minus its `plan_drop` raw indexes; map raw files
`NN_tool.json` to steps by position **and** tool. Refuse with a typed `CheckpointMigrationError`
(the run is reported `needs_attention`, never resumed) when: the `plan_drop` set grew across
attempts; a raw file's tool does not match the mapped step; a completed index has neither a raw
file nor a skip entry. Completed indexes with a `runtime_skip` failure/budget reason and no raw
file become `pending` (never dispatched).

### N-COST — attempt ledger (wave 2, same schema change as N-STATE)

**As-is.** Run aggregates only: either `counters.cost_usd` (server) or `cost_estimate_usd`
(`subagent.py:234-248`); the budget check uses one or the other (`orchestrator.py:642-648`);
a billed failure's cost never reaches the checkpoint (`subagent.py:190-230`); resume seeds a new
client from `None` (`orchestrator.py:306-310`). The service already journals every call with
cost in a `finally` (`service/runtime.py:60-83`) — that is the pattern to adopt, in the core.

**To-be.**
```
AttemptRecord
  attempt_id, step_id | "llm:<purpose>", kind (tool|llm), attempt_no, idempotency_key,
  started_at, ended_at, outcome (pending|ok|refused|transport_error|cancelled|unknown),
  cost {basis: actual|estimate|unknown, actual_usd, estimate_usd}, tokens_in, tokens_out, model
```
- Appended **before** dispatch, finalized in `finally` (including `CancelledError`), saved.
- `spend_usd(kind) = Σ actual + Σ estimate for attempts without actual`; `unknown` attempts count
  at their estimate and are disclosed (`stats.cost_unknown_attempts`). Never zero.
- The budget check reads the attempt ledger, not the client. Resume rebuilds spend from the
  persisted attempts before the first dispatch. `stats.cost_source` becomes
  `server|estimate|mixed`.
- `ProwlClient._invoke` returns/raises with the billed cost attached (`ProwlError.cost_usd`),
  so the worker can record it in `finally` without reading client totals.

### N-EVID — ledger v2: evidence truth (wave 3)

**As-is.** Status is set incrementally from the incoming claim; a valueless claim counts as
corroboration and overwrites peers to `verified` (`ledger.py:169-209`). `verbatim` is a bool from
the LLM and yields `verified` unconditionally (`orchestrator.py:684-697`, `ledger.py:183-199`).
Independence = distinct `source_tool` (`ledger.py:201-207`); transform claims corroborate their
own inputs.

**To-be.**
```
Claim v2 (+ fields)
  step_id, quote (verbatim text the extractor claims to have read), quote_span [start, end]
  in the stored raw text, source {delivery_tool, origin_url (normalized), publisher
  (registrable domain or provider dataset), document_sha256, independence_key}
  verification {method: span | corroboration | none, detail}
```
- `Ledger.recompute(subject_key)` recomputes the whole group, order-independent, on every add
  and on load.
- `verified` requires either (a) **span verification**: the quote is found in the stored raw
  (whitespace-normalized; the raw is read from `raw_ref` + checked against `raw_sha256`) and the
  claim's value occurs inside the quote; or (b) **corroboration**: ≥2 valued claims that agree
  within the existing tolerance and carry distinct, known `independence_key`s.
- `independence_key` = normalized origin URL's registrable domain + document hash when known;
  `unknown` never corroborates. Two tools fetching one URL share a key. A transform claim
  inherits the keys of its inputs (never independent of them).
- Conflict: ≥2 distinct values among valued claims → every claim in the group `conflict`,
  whatever arrives later. A valueless claim neither corroborates nor resolves.
- v1 ledgers load through recompute: v1 `verbatim` claims without a quote are downgraded to
  `assumed` with `verification.detail="v1 verbatim without quote"` — disclosed, not hidden.
- Consumers updated in the same change: writer prompt (`writer.py:89-90`), citations
  (`citations.py:82`), judge (`evals/judge.py:122-127`), charts, runbook-authoring
  (`docs/runbook-authoring.md:85-86`).

### N-LLMB — LLM budget (wave 4)

**As-is.** `Budget` (`runbook.py:36-43`, `extra="forbid"`) has tool calls, USD, minutes.
`LLMClient._usage` is in-memory tokens, no USD (`llm.py:58-99`).

**To-be.**
- `Budget.max_llm_usd: float | None` (runbook field) with a run-level override
  (`RESEARCH_MAX_LLM_USD` env / CLI `--max-llm-usd` / MCP & Fabric input `max_llm_usd`).
  Default when unset: `config.DEFAULT_MAX_LLM_USD` (stated in README; not unlimited).
- Every LLM call (planner, transform, extraction, writer draft/repair, citations, judge) goes
  through one `LlmRoute` (model, base_url, key name, `max_usd`) and records an `llm` attempt in
  the N-COST ledger with provider-reported cost (`usage.cost`) or a price-table estimate;
  missing pricing → `unknown` at a conservative estimate, never 0.
- Pre-call check: `llm_spend + estimate(next) > max_llm_usd − writer_reserve` stops research
  stages with `terminal_code=budget_llm`; the writer may spend into the reserve so a report is
  always produced from what was gathered (`writer_reserve` = config, documented).
- **B-001 compatibility:** the limit belongs to the route, not to the call sites, so the later
  estate model profiles replace only the route resolver (B-001, waived until T1–T3).

### N-SVC — service runtime parity (wave 4)

- `ObservedLLM` becomes a thin observer around `LLMClient` (retries, `max_tokens`-scaled read
  timeout, `LLMError` mapping) instead of a second transport (B-003).
- `ObservedProwl` observes `ProwlClient._rpc` with its retry/reconnect (B-004).
- `Runtime.envelope` derives `outcome` from the research status/terminal_code (B-005);
  mapping table in FABRIC.md.
- The service call journal and the core attempt ledger agree: the journal is fed from attempts
  (one source), and `research.artifact.get` reads the v2 checkpoint.
- `validate_runbooks.py` warns when an allowlist misses declared failover alternatives (B-029).

### N-FAB — Fabric contract (wave 5)

- Contract pin `623bf613` → `8e49fbd` (B-021); re-derive `contentHash`, keep provider ids.
- **Callee side of DEC-0039, by trust tier** (FD-12; ADR-0144 amendment 4, Fabric `19ad05ca`,
  fabric-workspace `knowledge/authority.md` "Trust by machine"): the service binds loopback only,
  so every caller is T0 (this machine) — the operator's instruction is the authority and a
  delegation token is **optional, used for attribution only**: when present it is verified
  offline (EdDSA, audience = this provider, actor chain, ≤10 min expiry) and its actor chain is
  recorded on the job; a bad token is refused with the contract's DL code; absence is fine. Binding
  beyond loopback (T1/T2) **requires** delegation verification and is refused at startup without
  it. The own agent token stays for outside callers. Tests mint tokens with a test key. Host-chain
  acceptance waits for the Fabric issuer (Fabric 0.4.0 wave 4) — KA-G03.
- Installer launches the service through an Observatory consumer, vault-only (B-019); the
  required slots are named in FABRIC.md (`PROWL_API_KEY`, `RESEARCH_LLM_API_KEY`).
- **Provider wiring (FD-13) is agent work** (operator rule 2026-10-11: agents create every provider
  key through Observatory's doors): the LLM key is issued with
  `openrouter.py issue --name prowl-research --limit <USD> --to vault:<project>/prod/RESEARCH_LLM_API_KEY`;
  the `prowl_` key has no Observatory door yet — wave 5 researches the prowl.chat issuing path
  (an account the door already holds) and adds a door or records the gap; never another agent's key.
- Dashboard kit 1.0.0 (B-002, needs the operator's go): tokens, `.fd-grid`, `.fd-nav`,
  `.fd-scroll`, well-known `extensions` — removes the fixed 208/160 px nav.
- HUB-PACKET/HANDOFF rewritten around ADR-0144 (B-014); FABRIC.md gateway rule fixed (B-013,
  wave 1).

### N-DOCS — honesty, scenarios, knowledge (wave 1, then every wave)

README counts derived from code (B-011), stale docstrings (B-012), BRIEF FD-12…14 (B-016),
core scenarios `CORE-01…` in `docs/ux/scenarios.md` written against this canvas as
`UNVERIFIED` and flipped by the wave that ships them (B-015), wiki card + agent-estate entry
(B-018), namespace note (B-030), nightly CI (B-031), probe harness in `tests/` (B-024).

### N-ACC — acceptance (wave 6; needs the operator)

Judge calibration: planted-bad fixtures the judge must fail, then a small labelled set and the
agreement number (B-017). Live finance + subscription runs with separate run/judge exit codes,
SHA, attempt-ledger cost and human review (KA-G02). Native host panel (FD-14). Host chain with
delegation tokens (KA-G03).

## 3. Integration seams

| Seam | Owner here | Other side | What crosses | Wave |
|---|---|---|---|---|
| run dir ↔ CLI / stdio MCP / service | N-OWN | — (three entry points of this repo) | lock + checkpoint v2 | 1, 2 |
| attempt → `prowl_call_tool` | N-COST | prowl-app KA-01/02 (owner: prowl-app session) | idempotency key `run:step_id:attempt_no`, billed cost on error envelopes | 2 |
| ledger → writer / citations / judge | N-EVID | — | claim status + verification method | 3 |
| LLM route → provider | N-LLMB | B-001 estate model profiles (fabric kit, T1–T3) | route object; limit lives on the route | 4 |
| service ↔ Fabric host | N-FAB | passioncode-ai/fabric (issuer, hub.json), fabric-agent-contract DEC-0039 | delegation JWT, contract pin, provider contentHash | 5 |
| service ↔ Observatory | N-FAB | project-observatory (consumer launch, vault slots) | slot names, never values | 5 |
| dashboard ↔ fabric-dashboards host | N-FAB | fabric-dashboards (0.7.1) | kit tokens, well-known extensions | 5 |

## 4. REQ → module → wave

| REQ | Modules | Waves |
|---|---|---|
| REQ-01 | N-OWN, N-STATE, N-COST, N-EVID | 1, 2, 3 |
| REQ-02 | N-COST, N-LLMB | 2, 4 |
| REQ-03 | N-OWN (`events.py`), then every module | 1–5 |
| REQ-04 | N-DOCS + each module's docs | every wave |
| REQ-05 | N-OWN, N-SVC, N-DOCS (CORE scenarios) | 1, 4 |
| REQ-06 | N-FAB, N-EXT rows | 1 (asks), 5 |
| REQ-07 | the close pass of every wave + final observer | every wave |
| REQ-08 | B-003…B-031 | 1–5 |
| REQ-09 | N-ACC | 6 |

## 5. Deleted or superseded

| What goes | Replaced by | Wave |
|---|---|---|
| `Checkpoint.completed_steps` (persisted) and `skipped_steps` dicts | `steps[].state` / `reason` | 2 |
| per-attempt re-run of `validate_plan` on resume (`orchestrator.py:340`) | plan validated once; `excluded` steps | 2 |
| `NN_tool.json` raw names, index-based idempotency keys | `<step_id>_<tool>.json`, `run:step_id:attempt_no` | 2 (v1 files read by migration only) |
| run-level `cost_usd` / `cost_estimate_usd` as budget source | attempt ledger | 2 |
| `Claim.verbatim` as a bool from the LLM | `quote` + `quote_span` + span verification | 3 |
| tool-name corroboration | `independence_key` | 3 |
| `ObservedLLM` second HTTP transport | observer around `LLMClient` | 4 |
| MCP/CLI terminal writes outside the lock; `_mark_run_failed` | `Orchestrator.run` owns terminal writes | 1 |
| HUB-PACKET hub-forwarding plan | DEC-0039 callee packet | 5 |
| legacy dashboard layout (fixed nav widths) | fabric-dashboard-kit 1.0.0 | 5 (operator go) |
| probe files as the only home of the KA contracts | `tests/test_ka_contracts.py` (probes kept as the historical cut) | as each fix lands |

## 6. Questions closed from the sources (not asked)

| Question | Answer | Source |
|---|---|---|
| Is the live-acceptance spend approved? | Yes for finance + subscription gates (~$2–3 each) and a `max_llm` mechanism | kimi export 2026-10-09 :7310 "давай дальше — ок на все" |
| Where are new MCP servers registered? | Each agent's own config; the shared gateway route is retired | machine-03 (current rule); B-013 fixes FABRIC.md |
| Hub route or direct calls? | Direct calls with delegation tokens; hub issues, does not forward | passioncode-ai/fabric ADR-0144; contract DEC-0039 |
| Is the dashboard-kit upgrade mandatory? | No; additive, operator go-ahead required | DEC-0036; dashboard-kit.md:111-113 |
| May the service use the private research-agent's OpenRouter slot? | No — never spend another agent's key | global authority rule; Observatory `research-agent/prod` belongs to ssheleg/research-agent |
| Rename `research.*` tools to avoid the collision? | No; provider contentHash binds names; document owner-qualified ids | fabric-agent.json provider revision 5 |
| Hosted CI triggers? | Nightly only, 23:00 Europe/Warsaw; no push/PR triggers | operator CI policy 2026-09-25 |
| Keep `stop_reason` / `status` names in v2? | Yes; additive `terminal_code` avoids a wave-1 → wave-2 rename | this canvas, §2 N-OWN |

## 7. Waves

Each wave runs build (TDD per task, a review after each) → full suite → three blind certification
readings per node (unit / seam / product) → one fix round → docs → canvas marks → re-measure the
inventory and re-cut. Builds that share a seam run sequentially; research and verification fan out.

| Wave | Closes | Exit criteria (written before the wave) |
|---|---|---|
| **1 — ownership spine + honesty** | KA-06, B-009, B-010, B-011, B-012, B-013, B-015, B-016, B-018, B-024, B-030, B-031 (B-023 on the operator's answer) | both KA-06 tests in `tests/test_ka_contracts.py` green; a real two-process smoke (two `prowl-research run` processes on one runs dir) leaves the loser's write absent; `events.py` tests; README counts match `pytest --collect-only` and the tool registries; CORE scenarios drafted `UNVERIFIED`; nightly workflow file valid YAML; full suite green |
| **2 — checkpoint v2 + attempt ledger** | KA-03, KA-04, KA-05, KA-10, KA-11, KA-12, B-006, B-008, B-025 | the 3 resume + KA-10×2 + KA-11 + KA-12 contracts green in `tests/`; crash-injection test at every durable boundary (`CrashAt`) proves no second paid dispatch; v1 → v2 migration tests incl. the three refusals; existing `runs/` load or refuse with the typed error; full suite green |
| **3 — ledger v2** | KA-07, KA-08, KA-09, B-007 | KA-07/08/09 contracts green; order-independence property test; v1 ledger downgrade test; writer/citations/judge consume the new status; runbook-authoring updated; full suite green |
| **4 — LLM budget + service parity** | KA-G01, B-003, B-004, B-005, B-029 | test stops the next LLM call before `max_llm_usd` incl. resume and retries; missing price ≠ 0; service parity tests (429 retry, reconnect, outcome mapping); full suite green |
| **5 — Fabric contract** | B-014, B-021, FD-12 (callee side, by tier), B-019, FD-13 (LLM key via door; prowl key path), B-002 (operator go) | pin + contentHash re-derived and validated; delegation tests (good token, wrong audience, expired, broken chain, own token still works); installer dry-run shows the vault-only consumer argv; service reinstalled and `check_service.py` re-run with every NOT_RUN named |
| **6 — acceptance** | B-017, KA-G02, FD-14, KA-G03, B-027 | judge fails every planted-bad fixture; live finance + subscription receipts; native panel observed; host chain receipt. Each item waits for its operator step |

The final close (stages 9–10): docs + wiki + code graph, the ladder walk per REQ, the parent
plan's KA rows updated with SHAs and receipts, and an **independent observer** agent that reads
only the REQ table, this canvas and the repository and rules whether the system meets the goal.

## 8. Operator decisions (one batch)

Recorded in [`docs/evidence/backlog.md`](../evidence/backlog.md); a go that leaves one unanswered takes
the recommendation as **assumed**, and the waves that depend on it name it.

| # | Decision | Recommended | Consequence of the other answer | Waves |
|---|---|---|---|---|
| Q1 | Integration: PR to `main` per wave, merged by the agent once the wave's close pass is green | yes | branches keep diverging from `main` (`origin/main` = `1dced8e`) | B-023, all |
| Q2 | Dashboard kit 1.0.0 upgrade + the launchd restart it implies | yes, in wave 5 | dashboard stays legacy 480 px, B-002 waived | 5 |
| Q3 | ~~Keys for FD-13~~ — **resolved from the sources**: agents issue keys through Observatory doors (operator rule 2026-10-11); no operator action | — | — | 5 |
| Q4 | Wave-6 budget: USD 15 total (2 live runs × ~$3.5 tool+LLM, judge calibration ~$3, one re-run) | yes | name another amount | 6 |
| Q5 | Fabric Dashboards host 0.6.7 → 0.7.1 (your administration) and one look at the native panel | yes, at wave 6 | FD-14 stays NOT_VERIFIED | 6 |

## 9. Revisions

| Date | Change | Why |
|---|---|---|
| 2026-10-11 | canvas created from the wave-0 survey at `c0dfb6e` | first cut |
| 2026-10-11 | FD-12 scoped by trust tier (token optional on loopback, required beyond it); FD-13 moved to wave 5 as agent work; Q3 closed | ADR-0144 amendment 4 (`19ad05ca`); operator rule on key issuing (global instructions, 2026-10-11) |
