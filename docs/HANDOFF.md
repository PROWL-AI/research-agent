# Research-agent handoff

## Current entry, 2026-10-23 morning: M1 tail done (supersedes every "Exact next task" below)

After «доделай» the rows M1 filed and this agent owns were closed in PR #36 (`843fdb8`): B-082 (v1 legacy-key resend
as sent), B-083 (usage covers 30 UTC days), B-085 (output cap per step), B-086 (tool-call reserve for steps that read an
earlier output, given back when unused), and the tab half of B-084. Installed release `843fdb8e5157` (`ready`,
`degraded: []`), smoke PASS; suite 737, mutation 76 of 76, WebKit PASS. Brief: `specs/waves/M1-T-tail.md`.

Open: B-081, job `pr-dd318bd6388795ffb26e` (`market-pulse`, LLM cap USD 0.50, tools USD 1.50) waits for the operator's
approval on the dashboard until 2026-10-23 08:05 UTC: it expired unapproved like the first and was cancelled (nothing
spent). Create the next one the same way (`research.run`, idempotency key with a new suffix) only when the operator
says they are at the dashboard, since an approval holds one hour. B-084 nav
half: kit owner, board thread `288afbce`. New row B-087 (not blocking). Owned elsewhere: B-001, B-017 person half,
B-020, B-042, B-067, B-073, KA-G03, FD-13, FD-14.

**Exact next task:** record B-081's outcome on its row when the job ends; nothing else is this agent's without an
operator priority.

## Current entry, 2026-10-23: milestone M1 reached (supersedes every "Exact next task" below)

Plan, stop line and result: [`specs/2026-10-22-milestone-m1.md`](specs/2026-10-22-milestone-m1.md) section 5.
`main` = `93bb2a7`; the service `prowl-research.default` runs release `93bb2a78fd2a` (`ready`, `degraded: []`),
smoke PASS. Checks on `main`: suite 722 passed, ruff clean, `validate` all runbooks valid, mutation check 70 of 70
killed, contract check with a failed job PASS at `7a14a48`, dashboard WebKit PASS (25 checks).

Done in M1 (PR #32 to #35): B-075 job error in `error.data.terminalCode`; B-077 dispatch follow-ups; B-079 kit 1.1.2;
B-080 service events in `events.log`; smoke key per build and test servers off the installed log; B-066 dashboard
readability (spend windows, attention only for now, failures in words first), B-078 coverage derived in Russian,
B-076 seeded browser check; B-074 `{{output:<step>}}`. Briefs: `specs/waves/M1-A-*.md`, `M1-B-*.md`, `M1-C-*.md`.

Open: B-081 job `pr-1125eff8d82f08e4895f` (`market-pulse`, LLM cap USD 0.50, tools USD 1.50 of the recorded
wave-6 USD 15) waits for the operator's approval on the dashboard; when it ends, record its outcome on B-081.
Rows filed in M1, none blocking a user: B-082, B-083, B-084, B-085, B-086. Owned elsewhere: B-001, B-017 person
half, B-020, B-042, B-067, B-073, KA-G03, FD-13, FD-14.

**Exact next task:** record B-081's outcome once the operator approves it; then stop: M2 starts from the
operator's priority among the open rows (the milestone grants no work past M1).

## Current entry, 2026-10-22 midday: milestone M1 (supersedes every "Exact next task" below)

Plan and stop line: [`specs/2026-10-22-milestone-m1.md`](specs/2026-10-22-milestone-m1.md). Review found `main` clean
at `f05cf07`, no worktrees, stashes or open PRs, the service `ready` on `1e9f1f182625`, board 23 of 98 open after three
new rows: B-079 (kit 1.1.2), B-080 (job lifecycle only in SQLite, `events.log` 0 bytes), B-081 (the installed service
never ran a research job). Waves: A (B-075, B-077, B-079, B-080), B (B-066, B-078, B-076 through `super-ux`),
C (B-074 design), Close (B-081, docs, board replies). Rows owned elsewhere and human acts are outside M1.

Wave A closed 2026-10-22: PR #32 (B-075 job error in `error.data.terminalCode`, B-077, B-079 kit 1.1.2, B-080 service
events in `events.log`) and PR #33 (smoke key per build; test servers log to their temp dir). Installed release
`6e7da4031bc9`, `ready`; smoke PASS; suite 703, mutation 65 of 65, contract check with a failed job PASS at `7a14a48`.
New row B-082 (v1 `legacy_key` resend). Note: `events.log` holds four lines from a dashboard test run of 12:59 UTC
(job `pr-7050c37886149a656b99`, before PR #33); they are not the installed service's jobs.

Wave B closed 2026-10-23: PR #34 (B-066 spend windows, attention only for now, failures in words first; B-078
coverage derived in Russian; B-076 seeded browser check). Installed release `2a9d470d0173`, smoke PASS. Rows filed:
B-083, B-084. Wave C (B-074 `{{output:<step>}}`) is on `feat/m1-wave-c`, seam round 1 fixed in `d4aecb3`.

**Exact next task:** finish wave C (seam round 2, PR, install), then the Close wave of the milestone.

## Current entry, 2026-10-22 (supersedes every "Exact next task" below)

Status: `main` is `1e9f1f1` (PR #31); the Fabric service `prowl-research.default` runs release `1e9f1f182625`
(`ready`, `degraded: []`, kit `fabric-dashboard-kit@1.1.1`; `scripts/smoke-installed-service.py` PASS through the
gateway, 0 provider calls). The installer keeps the previous release `10853dfe8e54` for rollback, by design.
Checks on `main`: `ruff check .` clean (the repository's own config now), suite 691 passed, `validate` all runbooks
valid, `scripts/plan/assign_waves.py --check` exit 0 (open 20 of 95), mutation check 62 of 62 killed
([receipt](evidence/judge-calibration/mutations.log)), dashboard WebKit PASS
([receipt](evidence/fabric-dashboard/raw/webkit-kit-1.1.1.json)). Branches: only `main` remains on the remote; every
deleted branch was an ancestor of `main` (32 in all; GitHub had removed 20 after their merges).

Done in PR #31 (six verification rounds: unit, seam and product tiers; the last two seam rounds and the last
product round found nothing blocking):
- **B-069** ruff read the parent folder's `0xDEV/pyproject.toml` (another repository): three false `F821`, 95
  findings unseen, no lint anywhere. Own `[tool.ruff]`, all findings fixed, lint in the nightly; every check after a
  successful install runs whatever an earlier one said.
- **B-070** template text other than `{{name}}` (`[substitute ...]`, `<id from ...>`, `{step.field}`,
  `PLACEHOLDER_...`) is never sent: 12 of 342 saved data steps carried one, 8 refused and billed, 4 "completed" on
  the literal text. A dispatched `outcome_unknown` step is re-sent as it was, never judged again.
- **B-071** measured provider limits (`research_agent/agent/tool_limits.py`; `tiktok_ads_library` country: `all` or a
  European code, US refused) are told to the planner, enforced before dispatch on both paths (planned steps and
  `research.tools.call`), sent in the provider's spelling, and their coverage reaches the writer (`Source coverage`),
  the fallback report, the direct result (`coverage`, `notVerified`) and the dashboard («Охват источника»). The
  writer reports a not-sent step as a gap of the run, in a partial and in a complete run.
- **B-072** dashboard kit 1.1.1. Docs: README, FABRIC.md (both keys in the vault since 2026-10-18; the refusal
  shape), runbook-authoring, CORE-19, CORE-17 count, ads-creative-research (TikTok is Europe-only).

Open and who holds it (board: [`evidence/backlog.md`](evidence/backlog.md)): B-067 (prowl-app: the app-store
resolver returns another brand's app; blocks a correct subscription audit), B-073 (prowl-app: TikTok schema offers
'US'), B-017 person half (the operator labels one report), B-020 (fabric-agent-contract, thread 3b4bd63d, no reply),
B-042 (registry owner), KA-G03 (hub JWKS), FD-13, FD-14, B-074 (design: hand a whole earlier output to an
LLM-analysis tool), B-075 (job errors carry `terminalCode`, which the pinned interop error schema forbids), B-066 and
B-078 (dashboard, through the UX chain), B-076 and B-077 (small follow-ups).

**Exact next task:** B-075 (a contract breach on every failed research job read strictly), then B-066 with B-078
through `super-ux` (scenarios first). Re-run `subscription-app-audit` once prowl-app fixes B-067.

## Current entry, 2026-10-21 evening (supersedes every "Exact next task" below)

Status: `main` carries B-065 (PR #29, `a8af16e`) and B-068 (PR #30, `10853df`); the Fabric service
`prowl-research.default` runs release `10853df` (`ready`, `degraded: []`); only that release is kept.
Board: 14 of 85 open (`python3 scripts/plan/assign_waves.py --check` exits 0). Suite 645 passed; ruff on
`research_agent/` unchanged (5 pre-existing).

Done since 2026-10-20 (PRs #23 to #29 plus this one): B-049 to B-064 (step-failure policy, reasoning off on cheap
stages, one escalation on a cut answer, line-patch repair, judge false positives, transport error recorded as
`error`, verifier re-vendored to DEC-0045), B-032 and B-040 closed live, then:
- **B-065** a value only an earlier step returns (an app's store id) is planned as `{{name}}`; a transform returns it
  in a `bindings` block, kept only when a raw artifact states it verbatim; an unresolved placeholder is never sent.
  Found on `accept-subscription-20261021`, where 20 of 26 skipped steps were the provider refusing the literal text.
- **KA-G02 subscription receipt** `accept-subscription-20261021b` (local `runs/`): 26 data calls, USD 0.30 tools,
  `partial`/`step_failed` (the Apple ids the resolver never returned stayed unsent), judge PASS 0.78 (USD 0.0096).
  The report opens with an identity warning: the resolver gave Headspace the Balance app (B-067).
- **B-067** (owner prowl-app, open): `resolve_app_store_ids` keeps the best fuzzy match across query variants, so a
  rival with the same generic words wins and no brand or publisher check applies; no Apple ids at all.
- **B-068** drafting residue inside a citation (`[C186? no, …]`) is now a lint issue the repair pass rewrites.
- **B-066** (open): dashboard against the eight perception principles; 2, 4, 5 and 7 to change through the UX chain.
- Board replies sent: roll call (thread fa6af7fb), dashboard principles (thread 89bbc415, row B-066).

Open and who holds it: B-017 person half (the operator labels one report: `runs/accept-subscription-20261021b/report.md`
or `runs/accept-finance-20261021/report.md`, local); B-020 (fabric-agent-contract, thread 3b4bd63d, no reply as of
21:24 UTC; their last merge #136 has no row); KA-G03 (hub JWKS); KA-01, KA-02, KA-G04, B-067 (prowl-app); FD-13;
FD-14 (the host 0.7.19 accepted `open` for `/dashboard`, but its window was off screen and no capture could be taken;
take it when the host shows this service); B-042 (registry owner); B-066.

**Exact next task:** B-066 through `super-ux` (scenarios first, then `app.js` `metrics()`/`overview()`), then re-run
`subscription-app-audit` once prowl-app fixes B-067 (or with an app whose store title is distinctive) to show the
Apple half bound. Reply on thread 7e3ea949 (released) and 2031b147 (verified) when B-066 lands.

## Current entry — wave program, updated 2026-10-17 (supersedes "Exact next task" below)

Objective: close every open item of this agent in its final form, in waves
(`/task-pipeline waves`), each followed by independent verification.

- Plan: [`specs/2026-10-11-waves-canvas.md`](specs/2026-10-11-waves-canvas.md) — target state, seams,
  waves with exit criteria, §7a wave status, operator questions (§8).
- Inventory: [`specs/2026-10-11-waves-inventory.json`](specs/2026-10-11-waves-inventory.json)
  (`python3 scripts/plan/assign_waves.py --check`; 17 of 64 open). Board: [`evidence/backlog.md`](evidence/backlog.md).
- **Wave 1 closed** (merged to `main` by PR #1): run-lock ownership (KA-06, B-009, B-010),
  terminal_code, structured events, honest docs, CORE scenarios, nightly CI.
- **Wave 2 closed** on branch `wip/wave2-checkpoint-v2` (PR #2): checkpoint schema 2 — immutable
  step ids, step states, durable evidence order, attempt ledger as the budget source, v1→v2
  migration with `needs_attention` (KA-03/04/05/10/11/12, B-006, B-008, B-025). Crash injection
  at every durable write (`tests/test_durability.py`). Suite 402 passed; deep probes 4 failed
  (KA-07/08/09 + the superseded cwd-relative control) / 8 passed.
- **Upgrade is one-way per run dir** (checkpoint.v1.json kept): restart stdio client sessions and
  reinstall the Fabric service (still `891fbc9`) before resuming runs a v2 build has touched —
  scheduled for wave 5.
- **Wave 3 closed** (PR from `feat/wave3-ledger-v2`, build `86e313e`, fix round `5fcf2f4`): ledger
  schema 2 — status recomputed per subject group (order-independent), `verified` only by a quote
  located in the stored raw or by two independent sources (publisher of a URL the raw names, or an
  upstream dataset; one step is one delivery; transforms and LLM-answer tools are no source);
  KA-07/08/09, B-007, B-024 closed. Suite 450 passed; deep probes 11/12 (superseded cwd control).
  The fix round also repaired a wave-2 seam break (MCP status/report serialization).
- **Wave 4 closed** (PR from `feat/wave4-llm-budget`, build `b045dca`, fix round `dfe395b`): every LLM
  attempt is checked against `max_llm_usd` before it is sent and recorded in the attempt ledger
  (provider cost, else the price table, never 0); research stops with `budget_llm`, the writer
  keeps a reserve, `rewrite` spends from the same ledger. The service runs the core's transports;
  envelope outcome follows the run; events go to a rotating `events.log`. KA-G01, B-003/004/005/
  029/035/036/038 closed; B-040/B-041 filed for wave 6. Suite 490 passed.
- **Wave 5 closed** (PR from `feat/wave5-fabric-contract`, build `eb1751b` + `77a0621`, fix round
  `198a227`): contract pin `7a14a48`, manifest revision 6 (`research.run` gains `max_llm_usd` ≤ 1000 and
  `resumeJobId`); callee side of DEC-0039 by trust tier — own token from loopback is T0, any other
  caller presents a delegation token (verified offline, DL-19 refusals, chain recorded on the job,
  per-principal job isolation and idempotency); loopback-only bind; service resume (B-039) with chain
  rules; dashboard on fabric-dashboard-kit 1.1.0 (estate themes, «Ещё», 360 px, verified initiator,
  service chip); installer under `use_secret.py serve --consumer chat.prowl.research`. Suite 515
  passed; mutations 12/12; WebKit PASS. Receipts: `evidence/fabric-dashboard/VERIFICATION.md` § Wave 5.
- **Wave 5 merged** (PR #5, `12ad137`) and installed from the merge: release `12ad13770223`, adapter probe
  29 PASS / 8 NOT_RUN / 1 FAIL — `well-known.fast` under machine load average 175–250 (B-044);
  every NOT_RUN named in VERIFICATION § Wave 5. B-037 closed (the pre-wave-3 build no longer runs).
- **W6-T1 offline half** (branch `feat/wave6-acceptance`): code-proven defects veto the judge, the judge's
  spend is metered into `<run>/judge-ledger.json`, `evals/calibrate.py` + planted fixtures, `scripts/mutation_check.py`
  (46/46). Three certification rounds; their fixes also closed two wave-5 seam findings (a replayed resume
  returns its job; an operator resume stays the operator's act and records the chain's owner, `chainOwner`). Evidence:
  `evidence/judge-calibration/README.md`. The LLM key is issued into vault `prowl-research-agent` (B-042).
- **Wave 6 offline half merged** (PR #6, `d868706`) and installed from the merge with the LLM key
  (vault `prowl-research-agent`): adapter probe 30 PASS / 8 NOT_RUN / 0 FAIL; health degraded for Prowl only.
- **Exact next task:** nothing offline remains in wave 6: B-045/B-046/B-047 closed. The rest waits on the operator (live judge calibration, host update) and external owners (B-043 `prowl_` key door, KA-G03 hub JWKS, B-020 contract PR, B-033 Fabric project registration). Re-check those at each resume. The installed service (`d868706`) carries every service change: later merges (#8, #9) touched the judge, tests, installer and docs only (`git diff d868706..e0f726a -- research_agent` is empty).
- **2026-10-18 problem pass** (branch `docs/b043-b042-b034-b017`): B-034 closed (Observatory marks the six leak
  findings `aboutThisProject: false`); B-042 cause measured and registry proposal `prop:098084032e734368` filed
  (`local_folders` = `0xDEV/research-agent`); B-043 path found: prowl.chat mints keys only from a signed-in web
  session, so the key is minted from the operator's own prowl.chat session in Safari (`POST /api/v1/keys`, total
  USD 10, daily USD 5), piped into vault `prowl-research-agent/prod/PROWL_API_KEY` and the service reinstalled.
  A session watcher waited for that sign-in; if this entry still says B-043 in-flight, the sign-in did not happen
  before it expired: sign in to prowl.chat in Safari and rerun the mint (the steps are in B-043's row).
  B-017 measured: the `sheleg-dev` hook refuses `--live` in an agent session unless the session was started with
  `SHELEG_DEV_LIVE_AUTHORISED=live-flag` exported.
- **2026-10-18 live runs:** with the `prowl_` key in place, `accept-finance-20261018` died at the planner (8k plan
  truncated, B-048, fixed in PR #13); `accept-finance-20261018b` on the fix planned and dispatched, then stopped after
  3 of 44 steps when one required tool returned no results (B-049), and cheap-tier citation checks returned null
  content (B-050). LLM spend USD 0.03, tool spend USD 0.021. Service reinstalled from `616ddc4`: `ready`, `degraded: []`.
  B-049 and B-050 were closed on 2026-10-20 (entry below).
- **2026-10-19 judge calibration (fixture half):** run by the operator, `anthropic/claude-haiku-5.5` agreed with all 10 fixture labels, no false alarms, USD 0.0077; two planted fixtures fail only through the code veto (evidence in `evidence/judge-calibration/`). The gate line below is done for the fixtures; agreement with a person on real runs waits on B-049.
- **2026-10-20 B-049, B-050, B-051 closed** (one PR, service reinstalled from the merge): a single refused step no longer
  stops a run (W6-T3 D1 to D8, CORE-17, three blind readings plus a second round); cheap JSON stages run with reasoning
  off and a length-cut null answer is not retried; a cut transform or extraction is asked once more, larger. Live
  receipts on `accept-finance-20261020` (local `runs/`): refused step went on (18 data calls vs 3), extraction cuts 35/43
  to 2/15, claims 51 to 157, no tool call paid twice; wave-6 spend so far about USD 0.46 of 15.
  B-053 closed the same day: `accept-finance-20261020b` ran the whole 44-step plan on the installed `00331bf`
  (17.5 min, LLM USD 0.131, tools USD 0.322, 247 claims). The judge fails that report; part of it is false positives.
  B-052, B-054, B-055, B-056 closed the same day (PR #18, installed `cf4de7e`) and confirmed live on
  `accept-finance-20261020c`: the judge's FAIL 0.57 there names only real writing defects.
  B-057 closed the same day: the repair pass gets the judge's code-proven defects (`report_checks.py`).
  B-058 closed the same day (shorter quotes, complete claims kept from a cut answer).
  Live check on the installed `52844a6` (`accept-finance-20261020d`): B-058 held; B-057 did not reach the model because
  the whole-report repair was cut at 24000 and thrown away (B-059); the judge raised three more false positives (B-060).
  B-059, B-060, B-061 closed on 2026-10-21 (repair by line patches; three more honest shapes; delegation verifier
  re-vendored with a small-order forgery test). This folder is a Fabric project since 2026-10-21 (B-033 closed).
  **Exact next task:** a live finance run on the installed build to confirm B-059, then the operator labels that
  report for B-017's person half; B-020 is asked on the project board. Then the operator labels a report for B-017's person half (a person's
  act; latest report `runs/accept-finance-20261020c/report.md`, local).
  Machine note 2026-10-20: the disk filled (swap 27 GB with 39 sessions) and killed one run mid-way; the run resumed
  without paying twice. Free space then 3.6 GB; Observatory's disk guard and cleanup freed little; swap shrinks only
  when sessions close or the machine restarts.
- **Human gate (one line):** the live judge calibration — the operator runs
  `python "$(project-observatory full-path)/tools/use_secret.py" run --vault-only --env prod prowl-research-agent RESEARCH_LLM_API_KEY -- .venv/bin/python evals/calibrate.py --live`
  in this checkout (≤ USD 0.50 per fixture, 8 fixtures, key ceiling USD 15), or authorises live flags for
  the agent's session (an operator setting on this machine) so the agent may run it.
- Live acceptance: the `prowl_` key is in place (B-043 closed 2026-10-18, service `ready`); still waits on the hub's JWKS (KA-G03); FD-14 host is 0.7.12 and the native panel rendered the service, a dashboard-tab capture is still owed (take it only when the host shows this service; never commit a capture of another service).
- Operator decisions (canvas §8) answered 2026-10-12: Q1 PR-per-wave merges, Q2 kit in wave 5,
  Q4 USD 15, Q5 host update at wave 6, Q6 no history rewrite. Q3 closed from sources.
- Cross-agent: B-001 (model profiles, waits on Fabric T1–T3), B-020 (the contract owner adds
  our adoption row with its PR #113), B-033 (this folder is not a Fabric project yet — operator step).

---

## Kimi and deep agent audits, 2026-10-10

Objective: independently verify the Kimi session's deliverables and correct the
documentation. This checkout belongs to `PROWL-AI/research-agent`; it is separate
from `PROWL-AI/prowl-app`, and is not its registered submodule.

## Source and verification

Audited source: [`1dced8e381e63db2b61dbcd854b44d41450ed455`](https://github.com/PROWL-AI/research-agent/tree/1dced8e381e63db2b61dbcd854b44d41450ed455).
Parent source: [`92f49d18dcd98df89a46448eac9818de74b8b7f6`](https://github.com/PROWL-AI/prowl-app/tree/92f49d18dcd98df89a46448eac9818de74b8b7f6).

- `.venv/bin/python -m pytest tests/ -q`: **304 passed**, exit 0.
- `.venv/bin/python -m research_agent validate`: **14 runbooks valid**, exit 0; local catalog check.
- Three additional expected-contract probes failed on the audited source. Their
  source and captured output live in the central report below; they are outside
  the default test collection and are not hidden by xfail.
- Real provider research/judges for finance/subscription and Fabric host admission:
  **NOT_RUN in this audit**. The previous session's final live command failed at
  argument parsing before research began.

Central report and exact reproduction commands (requires access to the parent
repository): [RPT prowl.chat/2026-10-10-kimi-session-audit](https://github.com/PROWL-AI/prowl-app/blob/audit/kimi-20261010/docs/reports/2026-10-10-kimi-session-audit/README.md).
The central handoff records both delivered branch SHAs and receipts. Runtime code
and Fabric manifest were not changed; documentation and explicit offline diagnostic probes are delivered.

## Confirmed resume defects and repair packets

| ID | Source at audited revision | Required behavior |
|---|---|---|
| KA-03 | [`orchestrator.py:338`](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/orchestrator.py#L338) re-filters the plan; completion indices are reused at line 478 | Catalog changes must not change a step's identity or make an unexecuted step appear complete. |
| KA-04 | [`subagent.py:219`](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/subagent.py#L219) marks the unstarted chunk tail completed | Resume must execute never-started steps; distinguish them from intentionally skipped, completed and dispatch-uncertain steps. |
| KA-05 | [`subagent.py:259`](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/subagent.py#L259) saves before completion is appended | Commit durable completion before returning; recover already-paid raw data after a crash without another dispatch. |

## Deep audit and execution plan

[Additional report](reports/2026-10-10-agent-deep-audit/README.md) adds seven open
findings KA-06…KA-12: lifecycle ownership, evidence verification and cost persistence.
It contains nine failing contract checks and three passing controls; all are
synthetic offline trials, not live-provider acceptance. KA-03…KA-05 stay OPEN.

[Canonical cross-repository plan](https://github.com/PROWL-AI/prowl-app/blob/audit/kimi-20261010/docs/superpowers/plans/2026-10-10-kimi-remediation.md)
owns order, dependencies, module contracts and acceptance for all twelve defects.
That link intentionally tracks the working branch; runtime source links above are immutable.

**Exact next task in this repository: KA-06.** Move all lifecycle mutation behind
run ownership, including MCP error/cancel handlers and startup reconciliation.
Make both `test_ka06_non_owner_cannot_mutate_locked_checkpoint` cases pass, preserve
the unlocked-orphan control, then verify with two real CLI/MCP processes sharing
one runs directory. No provider key is needed for the offline tests.

Next bounded packet: KA-03/04/05/10 together (step identity, resumable state,
durable raw/claims/completion), coordinated with parent KA-01 execution replay.
KA-07/08/09 cover evidence truth; KA-11/12 cover attempt costs. See the plan for
acceptance rather than treating a green baseline suite as closure.

Prerequisites: Python >=3.11, test dependencies, clone/access to the central audit
probes. No provider key is needed for offline reproduction. Do not clone the
unrelated `~/DATA/research-agent` project as this dependency.

Open product acceptance: LLM budget enforcement landed in wave 4 (`max_llm_usd`, README "How it works").
After money/resume fixes, run finance and subscription acceptance with explicit
run and judge exit codes, cost receipts and then Fabric host evidence. A public
manifest alone is not evidence of admission.

## Delivery boundary

Documentation branch: `audit/kimi-20261010`. A pushed branch is a handoff, not a
merge or deployment. The central report owns statuses and the source-to-receipt
mapping. Full private session export, local credentials, caches and `runs/` remain
local-only and are not part of this documentation delivery.
