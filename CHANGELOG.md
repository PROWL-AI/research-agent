# Changelog

One version for the package, the service's well-known document and MCP `initialize`:
`research_agent.__version__` (`tests/test_version.py`). Row ids (B-NNN, KA-NN, FD-NN) are in
[`docs/evidence/backlog.md`](docs/evidence/backlog.md).

## 0.6.3 (2026-11-13)

- Client keys of the cloud instance have a class (K1, the operator's word of 2026-11-13): `interactive` for a person
  or an agent a person calls has no daily ceiling, its paid job starts at once and its decision records who spent;
  `automated` (the default, and every key issued before) keeps its ceiling. `client add --class`, `client.issue` with
  `class`; a missing ceiling reads as `null`, never 0 ([CLOUD.md](docs/CLOUD.md), scenario CORE-26).

## 0.6.2 (2026-11-13)

- The service installs on a space of a shared Mac with no GUI login, the Mac Studio (B-106): `install-fabric-service.py
  --background --port <port>` writes a system daemon definition that runs as the account, labelled per account, into
  the space's background folder and loads it through studio-agent's door; the first load is the administrator's (exit
  77 with the line to run). A port another listener holds is refused. `scripts/mcp_headers.py` gives Claude Code the
  bearer header from the agent token file, so no token sits in a client configuration ([FABRIC.md](docs/FABRIC.md)).

## 0.6.1 (2026-11-13)

- Text from pages and tools is fenced with the agents database pattern `untrusted-fence` 1.2.1 (B-102): every prompt
  that quotes a raw draws its own fence token, which the text never contains, so a page carrying the old closing marker
  can no longer end the fence early; forged fence lines and data tags are neutralised and hidden characters removed
  before a model reads the text. A suspected injection is recorded as the event `untrusted.suspected` and the raw stays
  data; a value found only in a raw flagged as an injection is never bound into a later tool call. A quote copied
  without the hidden characters is still found in the stored raw (basis `visible`).
- Service tests no longer read the machine's free disk: a full disk under a test run had held a job (B-114) and timed
  a cancel test out.

## 0.6.0 (2026-11-13)

- The strong model (planner, writer, repair) is `moonshotai/kimi-k3.1-pro`, the operator's model map (B-107): measured
  against `xiaomi/mimo-v2.6-pro` on the same three runs' evidence, 0.76 against 0.52 on the judge, no defect against 11
  ([report](docs/reports/2026-11-13-strong-model-measure/README.md)). A service keeps the model its settings name.
- `scripts/configure_service.py` changes a running service's settings through its own API (login code, session, the
  form's revision check): the operator's settings change needs no click, on the local service and on a cloud one.
- A writer draft that comes back empty because reasoning took the whole output budget is asked once more with
  reasoning off, instead of losing the report (B-122).
- An issuing desk on the cloud instance (B-121): `client add-desk` gives a team's key steward a `keys.issue` key; it
  issues, rotates, revokes and lists only its own keys through the MCP tools `client.issue|rotate|revoke|list`, within
  the grants and ceiling its desk was given. The tool descriptions now state the allowance rule.
- A full disk pauses a job instead of failing it (B-114): under 1 GiB free a job waits in the queue; a run stopped by a
  full disk is `disk_low` and the service continues it by itself once space is back, without paying again for what
  was recorded.
- The CLI's messages and the evidence-only report heading read without an em dash (B-108, rule R30).
- The dashboard reads without internal ids or raw JSON on its first views (B-120): inputs and settings are labelled
  facts, phases are in Russian, the JSON view is the «Технические данные» tab.
- `metrics.json` and `scripts/measure_metrics.py` (B-114, rule R31): the research template's metrics, measured from local
  files; the first baseline is a verified claim share of 0.411 over 3355 claims of 14 runs.
- A runbook runs at an exact version: `research.run` with `runbook: "market-pulse@1.0"` takes the current text or the
  shipped one kept in `versions/` (B-110, rule R28).
- Reports render with `base.v2.html.j2`: the partial-run banner reads without an em dash (B-108, rule R30). The shipped
  `base.html.j2` stays byte for byte (rule R28) and the add-only lock gained the new name.
- The dashboard's settings carry the agents' daily allowance, and its «Ключи и разрешения» callout, SECURITY.md and
  FABRIC.md describe the 0.5.0 approval rule instead of «every paid job waits» (B-109).
- A one-off cloud command (`client add`) no longer hangs behind the web dyno (B-119): reads of client keys end their
  transaction, and the 0.5.0 column is added only when it is missing.
- The remote descriptor `scripts/cloud.py register` writes passes Fabric Dashboards (B-118): residency, data class and
  runner in the peer block.
- The cloud instance runs one worker whatever `WEB_CONCURRENCY` says (B-117): Heroku's buildpack default of 2 made
  uvicorn exit with status 3 on boot.
- The cloud deploy gate passes again (B-116): a test that asks git what is tracked skips in the extracted archive the
  gate runs, which has no index; every cloud deploy since 0.4.0 had been refused.

## 0.5.0 (2026-11-12)

- A caller's daily allowance (B-100): a paid job an agent creates starts without a person when its worst case (the
  runbook's tool budget plus the run's LLM cap, 1 USD for one tool call, nothing for the tutorial) fits what is left of
  the caller's ceiling for the UTC day; above it, the job waits for the operator as before. A cloud client key carries
  its own ceiling, at least 10 USD per day and 10 by default (`client add --daily-usd`, `client limit`); local agents
  share the setting `agent_daily_usd` (10 by default, 0 turns it off). The dashboard's own requests still wait for the
  operator. Basis: the operator's word recorded in the agents database (intake in-20261112-996c34, research template
  1.6.0) and the delegation rules of 2026-11-05 and 2026-11-07; before, every paid job of every agent waited for a click.
  Each decision records who made it (`allowance` or `operator`), the worst case, the day's spend and the ceiling
  (`research_agent/service/allowance.py`, `tests/test_allowance.py`).
- `client add|rotate --raw` prints only the key, for a pipe straight into the holder's vault slot.
- Model prices re-read from OpenRouter on 2026-11-12: `deepseek/deepseek-v4.1-flash` is 0.30 / 1.20 USD per 1M tokens,
  not 0.04 / 0.70, so cheap-tier spend was under-counted; the operator's model map (Kimi K3.1 Pro, Sonnet 5.5, GLM 5.3,
  Gemini 3.1 Pro) is priced, so a switch to it is no longer estimated at the unknown price.
- The model key `prowl-research` monthly limit moved from 50 to 100 USD (the operator's default for every agent,
  2026-11-07).
- Audit of 2026-11-12 against the agents database template `research` 1.7.1, the Prowl product and the estate's
  rules: [docs/reports/2026-11-12-agent-audit/README.md](docs/reports/2026-11-12-agent-audit/README.md); its gaps are
  board rows B-106 to B-114.

- The awaiting-decision notice is no longer pushed when a request is created: the caller usually approves
  at once, and the operator was asked four times on 2026-11-12 about decisions already made. A request still
  undecided after `AWAITING_NOTICE_GRACE_SECONDS` (60) is pushed once, from the event read the host polls
  (`tests/test_awaiting_notice_grace.py`).
- Rule R28 of the agents database, add and never replace (B-105): what shipped is never changed or deleted.
  `catalog/shipped.lock.json` holds the hash of every runbook at its version and every report template;
  `scripts/check_add_only.py` (the database pattern `add-only-catalog` 1.0.0) refuses an edited or deleted entry and
  a lock that lost a name, in the suite and in the nightly. A changed runbook bumps its version and keeps the shipped
  text in `versions/`. The rule is in `AGENTS.md`.
- Quote verification follows the agents database research template 1.2.4 (B-101): a scale word is resolved
  before numbers are compared (1500000 is in "1.5 million", not in "1.5 billion"), and a quote cut right after a
  comparison written in words ("at least", "up to", "more than") or a sign, or inside a larger number, is not found.
  A claim that relied on such a cut now stays `assumed` instead of `verified`.

## 0.4.1 (2026-11-04)

- The team copy carries the Appvillis prefix (operator, 2026-11-04, relayed on the Fabric board): the service's id and
  name live in one module, `research_agent/service/identity.py`, which the copy builder rewrites to
  `appvillis-prowl-research` / «Appvillis Prowl Research»; the copy's README, runbook and team onboarding name the
  copy's service, Heroku app and MCP server. The original keeps no prefix and its page is byte for byte its file.
  Copy repository `appvillis-com/appvillis-prowl-research`, Heroku app `appvillis-prowl-research` (B-099).

## 0.4.0 (2026-11-04)

- The cloud instance, a team gateway (B-099): `prowl-research-service cloud-run` serves runbooks and every Prowl tool
  to teammates' Claude Code through `/mcp` with personal client keys (`prc_`, SHA-256 only, scopes `read`,
  `research.run`, `tools.call`, `client add|rotate|revoke|list`). It answers only its own https origin, keeps the
  well-known document behind the service token, records the client as each job's principal, and keeps its data
  folder in Postgres across dyno restarts. Paid jobs still wait for the operator. Without cloud variables the local
  service is unchanged. Operator scripts: `scripts/cloud.py deploy|config|register`, `scripts/build_team_copy.py`
  for the copy in `appvillis-com`. Runbook [docs/CLOUD.md](docs/CLOUD.md), onboarding
  [docs/TEAM-ONBOARDING.md](docs/TEAM-ONBOARDING.md).

## 0.3.7 (2026-11-02)

- A value the request itself names grounds a placeholder: a transform a later step waits on now sees the run's inputs
  and may bind a value they state verbatim, as it binds one an artifact states. On market-pulse run
  `pr-7bd2bc01ca789c51f668` the refused trends autocomplete (B-096) left `{{term1}}`..`{{term5}}` unbound and 15
  required trend steps unsent, SerpApi's included, although the brief named the market (B-098). A value neither
  source states is still discarded and never sent.

## 0.3.6 (2026-10-27)

- Dashboard on `fabric-dashboard-kit@1.1.5`, with Fabric's button: «Чат с Fabric о сервисе Prowl Research» opens a
  chat about this service in Fabric; the link carries the service id only (B-088).
- No local user name or private-wiki name in the public tree (B-097, the tree part).

## 0.3.5 (2026-10-25)

- A failed call keeps its cause: the call journal stores a secret-free reason (at most 300 characters) for a failed
  tool or model call, and the request's «Шаги» tab shows it as «Причина: …». Before, a provider's `HTTP 429` reached
  only the log file and the receipt said «failed» (found on the first service research run, B-081).
- A status label away from its citation is checked too: `**Confidence: VERIFIED**` after a cited sentence, or
  `**Confidence:** VERIFIED [C37]`, is a `status_mislabel` when no claim the line cites is verified, and the writer
  repairs it. The first service research run (B-081) reached its report with two such labels on assumed claims.
- FD-14 closed: the dashboard tab captured inside the Fabric Dashboards host.
- B-096 filed: Prowl's SearchApi plan has used its monthly searches, so SearchApi engines answer `HTTP 429`.

## 0.3.4 (2026-10-25)

- Dashboard copy without em dashes: the spend note, the decision card's budget line, the ledger caption and the login
  page title read the same with ordinary punctuation.
- The learn tab says how agents call the service today: through the `prowl` gateway with the service's agent token;
  a hub delegation token is refused until the hub publishes keys (KA-G03). It no longer mentions `agent.call`.
- Documentation brought in line with the code and the board: the current handoff is linked as current, the service is
  described with both provider keys (FD-13 closed), delegation tokens are described as refused until the hub
  publishes keys (KA-G03), scenarios CORE-06, CORE-17 and SCN-004 describe the 0.3.0 and 0.3.3 behaviour, and B-020
  (the adoption-plan row exists) and B-027 (USD 15 decided) are closed.

## 0.3.3 (2026-10-24)

- A job waiting for approval links the operator to the request in Fabric Dashboards
  (`fabric-dashboards://service/prowl-research.default?path=...`), not to an HTTP page; `AGENTS.md` pins the rule
  that the service's pages open only in Fabric Dashboards (operator rule 2026-10-24).

## 0.3.2 (2026-10-24)

- 0.3.0 and 0.3.1 committed a `build/` directory by mistake, and setuptools installed that `build/lib` in place of
  the sources (it held the 0.3.0 code, so both installs ran 0.3.0 code and 0.3.1 reported version 0.3.0). The
  directory is removed and ignored, the installer drops build output from the archive before installing, and a test
  fails if one is tracked again.

## 0.3.1 (2026-10-24)

- The installer waits for the service on a 600 s wall-clock deadline (`--ready-timeout`) instead of 120 s of tries, so
  a good install on a loaded machine no longer fails; a timeout names the readiness check (B-093).

## 0.3.0 (2026-10-24)

Everything merged since 0.2.0 (commit `4cb25c2`, 2026-10-10): pull requests #1 to #40.

**Runs and evidence**
- Run ownership with a lock and orphan reconciliation; checkpoint v2 with step identity, a durable attempt ledger and
  resume that re-sends an unknown outcome under its own key (#1, #2, B-082 in #36).
- Ledger v2: claims tied to their evidence, verified quotes only (KA-07, KA-08, KA-09, B-007; #3).
- LLM budget with a writer reserve, metered judge spend, and the `budget_llm` stop (KA-G01; #4, #6).
- One refused step no longer ends the run; a run stops on an empty wallet, the service's limit, an unknown outcome or
  five refusals in a row (B-049; #16).

**Planning and tools**
- `{{name}}` placeholders resolved by an earlier transform, never sent unresolved; template text and known-refused
  values are never sent (B-065, B-070, B-071; #29, #31).
- `{{output:<step>}}` hands a whole earlier result to a later step under a 16 000-character cap per step (B-074, B-085;
  #35, #36).
- Steps that read an earlier output keep their tool call under a tool budget; unrelated steps yield only while that
  still buys a forward, never after the run stopped (B-086, B-087, B-089, B-090; #36, #38, #39).
- Peers see a worker crash and a run-wide refusal before their next step (B-091, B-092; #40).
- A truncated plan is retried once at a larger limit (B-048; #13).

**Report quality**
- The judge vetoes by code (unverified tags, quote gaps, false positives fixed); the writer repairs the defects the judge
  proves, line by line, with reasoning off (B-045 to B-047, B-052 to B-064, B-068; #8, #9, #18 to #30).

**Fabric service and dashboard**
- Fabric contract revision 6: delegation callee side, service resume, job errors inside the pinned schema
  (`data.terminalCode`), lifecycle events in the file log (B-075, B-077, B-080; #5, #32, #33).
- Dashboard on `fabric-dashboard-kit@1.1.3`: Russian copy, readable failures with «Подробности», spend windows,
  source coverage on every job, no cut navigation or tabs at 360 to 390 px (B-066, B-076, B-078, B-083, B-084;
  #34, #36, #37).
- Kit 1.1.3's Fabric button is not loaded: its labels are English only (B-088, decided).

**Verification**
- Mutation check over the certified defences (85 mutants, all killed), WebKit dashboard check at 1440, 390 and 360 px,
  installed-service smoke per build.
