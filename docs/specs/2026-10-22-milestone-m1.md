# Milestone M1: everything this agent can close, closed (2026-10-22)

Owner: the coding session on `main` (Fabric task 63ddbc80, claim cdff2936). Operator request of 2026-10-22:
review the state, bring docs and planning up to date, then close the open work in waves (one or two
sub-agents at most) and stop at the nearest milestone. This file is that milestone and its stop line.

## 0. Baseline (measured 2026-10-22 12:20 UTC)

| Fact | Value | Source |
|---|---|---|
| `main` | `f05cf07` (docs on top of PR #31 `1e9f1f1`), clean, only branch on the remote | `git status -sb`, `git branch -a` |
| Worktrees, stashes, open PRs | none, none, none | `git worktree list`, `git stash list`, `gh pr list` |
| Installed service | `prowl-research.default` build `1e9f1f182625`, `ready`, no reasons | fabric-dashboards `service_status` |
| Board inventory | 20 of 95 open | `python3 scripts/plan/assign_waves.py --check` exit 0 |
| Dashboard kit | files 1.1.1, current kit 1.1.2 | `dashboard_kit.py status` |
| Jobs ever run by the installed service | 3 (tutorial and smoke), 0 research runs | `service.sqlite3` `jobs` table |
| `~/Library/Logs/prowl-research/events.log` | 0 bytes since 2026-10-17 (only research runs emit there) | `ls -la`; `research_agent/service/cli.py:28` |
| Project board | 55 unread; threads 7e3ea949, 2031b147, e905f4b7, fdd50181 have no reply from us | `com.list`, `docs/HANDOFF.md:60,70` |

## 1. In scope (the agent closes these)

| Wave | Rows | Exit check |
|---|---|---|
| **A: contract and stability** | B-075 (`terminalCode` outside the pinned error schema), B-077 (dispatch follow-ups), B-079 (kit 1.1.2), B-080 (job lifecycle in the file log) | failed job's error validates against `fabric-agent-contract@7a14a48` `interop-common` `$defs/error`; the three B-077 tests pinned; `dashboard_kit.py status` reports current; a tool job writes a line to `events.log`; suite, ruff, `validate`, mutation check green |
| **B: dashboard through the UX chain** | B-066 (principles 2, 4, 5, 7), B-078 (coverage on research jobs, wording), B-076 (browser check of the callout) | scenarios updated first (`docs/ux/scenarios.md`, status `UNVERIFIED`), then `app.js`; `scripts/test-dashboard.mjs` covers the callout; WebKit PASS at 1440/390/360; strings through `copywriting` |
| **C: analysis input design** | B-074 (hand a whole earlier output to an LLM-analysis tool) | spec in `docs/specs/`, one bounded build (artifact binding under a size cap) with tests, or the spec alone if the build exceeds one pass; the decision is recorded either way |
| **Close** | B-081 (a research run through the installed service, as a user) | each wave merged by PR, service reinstalled from the merge, `scripts/smoke-installed-service.py` PASS; handoff, README, FABRIC.md and the inventory updated; board replies sent |

Each wave: build with tests first, full suite, blind readings (unit, seam, product), at most **two** fix rounds,
docs in the same change, PR merged by the agent, install, smoke.

## 2. Out of scope (the stop line)

Not done in M1, whatever turns up:

- Rows owned elsewhere: B-067 and B-073 (prowl-app), B-020 (contract owner), KA-G03 (hub JWKS), B-042 (registry
  owner), B-001 (Fabric model profiles), FD-13, FD-14 (host).
- Human acts: B-017 person half (the operator labels one report), the approval of B-081's paid run.
- New capabilities, new runbooks, new providers, a broad refactor. A refactor is in scope only where a wave's
  own row needs it; anything else found becomes a board row with its evidence.

## 3. Stop criteria (M1 is reached when all hold)

1. Every row of section 1 is closed on the board with the commit that closed it, or (B-074, B-081) carries a
   recorded decision or a named human gate.
2. `main` carries every wave; the installed service runs the last merge; smoke PASS; `degraded: []`.
3. Two consecutive verification rounds on the last wave found nothing blocking.
4. HANDOFF has one current entry with the exact next task, which is **prioritising M2**, not continuing.

Hard limits: two fix rounds per wave; no paid live run except B-081 (one run, inside the operator's recorded
wave-6 budget of USD 15, `docs/specs/2026-10-11-waves-canvas.md` section 8 Q4); no work on a row from section 2.
A finding that blocks nothing becomes a row, not more work.

## 4. Status

| Wave | State | Commits |
|---|---|---|
| A | **closed** | PR #32 (`6e7da40`) and #33 (`04d9df4`); installed release `6e7da4031bc9`, smoke PASS (`pr-01cfe46d5b2d46dd0508`); seam pass, product fail on docs then fixed and rechecked; B-082 filed |
| B | **closed** | PR #34 (`2a9d470`): scenarios first, build, product round, visual rounds 1 (fail on evidence) and 2 (pass); installed release `2a9d470d0173`, smoke PASS; B-083, B-084 filed |
| C | **closed** | PR #35 (`93bb2a7`): build, seam rounds 1 to 3 (the last without a blocker); B-085, B-086 filed |
| Close | **reached, one human gate open** | installed release `93bb2a78fd2a` (`ready`, `degraded: []`), smoke PASS; suite 722, mutation 70 of 70; B-081 job `pr-1125eff8d82f08e4895f` (`market-pulse`, LLM cap USD 0.50, tools USD 1.50) waits for the operator's approval on the dashboard |

## 5. Result (2026-10-23)

M1 is reached by its stop criteria: every row of section 1 is closed with its PR (B-074, B-075, B-076, B-077, B-078,
B-079, B-080, B-066) or carries a named human gate (B-081: the paid run's approval); `main` = `93bb2a7` is installed;
the last reading of each wave found nothing blocking. Rows filed during the milestone, none blocking a user: B-082,
B-083, B-084, B-085, B-086. Open and owned elsewhere: B-001, B-017 (person half), B-020, B-042, B-067, B-073,
KA-G03, FD-13, FD-14. The next step is the operator's priority for M2, chosen from those rows; this file grants no
work past it.

## 6. Tail (operator «доделай», 2026-10-23)

The operator asked to finish: the rows M1 filed and this agent owns (B-082, B-083, B-085, B-086, the tab half of
B-084) are closed in PR #36 ([brief](waves/M1-T-tail.md)). Merged as PR #36 (`843fdb8`), installed release `843fdb8e5157`, smoke PASS; three seam readings, the last two without a
blocker; B-087 filed. The nav half of B-084 waits on the kit owner (board thread `288afbce`). B-081: the first job
expired unapproved (an approval is valid one hour) and was cancelled; the second, `pr-dd318bd6388795ffb26e`, waits for
the operator's approval until 2026-10-23 08:05 UTC. Nothing else in this repository's backlog is ours to do without
an outside owner or a person's act.

B-084's nav half closed on kit 1.1.3 in PR #37 (`1b74778`), installed `1b747787c767`, smoke PASS; B-088 filed.
