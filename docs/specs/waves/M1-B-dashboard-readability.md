# M1-B: dashboard readability (B-066, B-078, B-076)

Wave B of [`../2026-10-22-milestone-m1.md`](../2026-10-22-milestone-m1.md). Route: `/task-pipeline`, user-facing, so
`super-ux` scenarios first (`docs/ux/scenarios.md`), strings by the voice in `docs/brand/voice.md`, the look stays on
the kit (no new tokens or colours). Public repository: no absolute home paths or private names.

## Source ledger

| Source | What it gave |
|---|---|
| board thread 89bbc415 (operator request 2026-10-21, eight perception principles) | holds 1, 3, 6, 8; to change: 2, 4, 5, 7 (B-066) |
| `research_agent/service/static/app.js` `metrics()`, `overview()`, the request detail (error callout, «Охват источника») | today: one 31-day cost total, failures of all ages in «Требуют внимания», raw `error.message` first, coverage only on tool jobs and in the English `statement` |
| `research_agent/service/store.py` `usage()` | per-day `costUsd` (null when unpriced), `unpricedCalls`; tutorial calls excluded |
| `research_agent/agent/tool_limits.py` | one limit (`tiktok_ads_library` country) with `coverage` (writer) and `statement` (English, for a person) |
| `research_agent/service/runtime.py:381` | a direct tool job stores `coverage`; a research job stores none (B-078) |
| `research_agent/service/app.py` `GET /api/jobs/{id}` | serves the stored job and its calls; nothing derived |
| `scripts/test-dashboard.mjs` | no fixture with a limited tool (B-076) |
| `docs/ux/scenarios.md` SCN-001, SCN-003, SCN-006; `docs/brand/voice.md` | the scenarios to change; «ошибка объясняет, что произошло и следующий доступный шаг», unknown stays visible |

Contradictions: none.

## Decisions

- **D1 (principle 2).** «Расходы» on the overview shows today, 7 days and 30 days side by side, plus the cost per
  delivered report (sum of priced spend over 30 days / research jobs completed in 30 days); an unpriced call keeps the
  value marked as a lower bound («не меньше»), never 0. Tutorial jobs are already excluded from `usage()`.
- **D2 (principles 4 and 7).** «Требуют внимания» lists what waits now: decisions pending, and failures of the last
  3 days, tutorial and check jobs excluded (as the counters already do). Older failures fold into one counted line
  that links to the request list filtered by «Ошибка»: «Ещё N ошибок старше 3 дней» with the most frequent class.
- **D3 (principle 5).** A failed request's callout leads with what happened and the next step in words, by error
  code (`interrupted`, `timeout`, `execution-failed`, `request-rejected`, `cancelled`, unknown code: a neutral
  fallback); the raw message, code and run terminal code sit under «Подробности».
- **D4 (B-078).** Coverage on the dashboard is derived, not stored: `GET /api/jobs/{id}` adds `display.coverage`,
  the Russian statement of every limited tool the job used (a tool job: its tool; a research job: the tools of its
  completed steps from the run checkpoint). `tool_limits.ArgumentLimit` gains `statement_ru`. The callout shows on
  the data and sources tabs of both kinds; old jobs get the Russian text too. The stored English `coverage` of the
  API result stays as it is (callers are agents).
- **D5 (B-076).** `scripts/test-dashboard.mjs` gains a fixture job that used `tiktok_ads_library` and checks the
  callout text on a research job and a tool job.

## REQ

| REQ | Requirement | Verified by |
|---|---|---|
| B-1 | Spend shows today / 7 / 30 days and cost per delivered report; unknown stays visible | dashboard check (new) |
| B-2 | Attention holds only current items; older failures fold into one counted line; tutorials excluded | dashboard check (new) |
| B-3 | A failure reads class and next step first, raw text under «Подробности» | dashboard check (new) |
| B-4 | Research and tool jobs that used a limited tool show the Russian coverage callout | `tests/test_service.py` (new) and dashboard check |
| B-5 | Scenarios SCN-001, SCN-003, SCN-006 updated first; WebKit PASS at 1440/390/360 | `node scripts/test-dashboard.mjs` |
