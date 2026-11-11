# Changelog

One version for the package, the service's well-known document and MCP `initialize`:
`research_agent.__version__` (`tests/test_version.py`). Row ids (B-NNN, KA-NN, FD-NN) are in
[`docs/evidence/backlog.md`](docs/evidence/backlog.md).

## Unreleased

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
