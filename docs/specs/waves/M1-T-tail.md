# M1 tail: the milestone's own findings (B-082 to B-086)

Operator instruction of 2026-10-23, «доделай», after M1 was reached: close the rows this agent owns that M1 itself
filed, then stop again. Rows owned elsewhere and human acts stay out (milestone section 2). Route: `/task-pipeline`.

## Decisions

- **D1 (B-082).** A v1-migrated step whose next attempt reuses its v1 key is a re-send: it goes out with the planned
  arguments, neither rewritten to the provider's spelling nor judged by a rule learned since, because the server may
  already hold that key with those params.
- **D2 (B-083).** `Store.usage` covers 30 UTC days including today, the window the overview calls «30 дней», so the
  costs tab and the overview add up.
- **D3 (B-084).** The request-detail tabs wrap instead of clipping. The half-cut section nav at 390 px is the kit's
  `foldNav` (it sets the More label after measuring and does not re-run when `aria-current` moves); reported to the kit
  owner on the board (thread `288afbce`), not patched in the vendored copy. The row stays open on that half.
- **D4 (B-085).** The 16 000-character cap is per step: several references share it.
- **D5 (B-086).** While a block has later levels (steps that read an earlier output), each earlier segment leaves one
  tool call per such step: an unrelated step that would take one of them is `skipped_budget` with a reason saying so,
  and the run's `budget_tools` stop is applied after the block's last level, so the forwarding steps still run.
  Only `max_tool_calls` is reserved; `max_usd` and `max_minutes` stop as before.
- **D6 (seam round 1 on the tail).** The reserve counts only later steps that take a new call (not a re-send of an
  unknown outcome, not saved raw) plus the producers of the current segment still pending; a producer never yields,
  and a step whose outcome is unknown never yields either (its next send must reuse its key). The deferred stop emits
  `budget.stop` like every other budget stop. The 16 000-character cap is shared by every occurrence of a reference
  in a step, and the planner is told so.

## REQ

| REQ | Requirement | Verified by |
|---|---|---|
| T-1 | v1 legacy-key step sent as v1 sent it | `tests/test_m1_tail.py::test_a_v1_step_resent_under_its_legacy_key_goes_out_as_v1_sent_it` |
| T-2 | usage covers 30 UTC days | `tests/test_service.py::test_usage_covers_the_same_30_utc_days_as_the_overview` |
| T-3 | detail tabs wrap at 360 px | WebKit frame `failure-open-360-dark.png` |
| T-4 | one cap per step | `test_several_output_references_share_one_cap_per_step` |
| T-6 | the reserve skips neither a producer (placed last) nor an unknown-outcome step; `budget.stop` is emitted | `test_the_reserve_never_skips_the_producer_of_a_later_level`, `test_the_reserve_never_skips_a_step_whose_outcome_is_unknown`, `test_one_reference_written_twice_still_shares_one_cap` |
| T-5 | a forwarding step keeps its call under a tool budget, at 1 and 3 workers, and the run still ends `budget_tools` | `test_a_forwarding_step_keeps_its_call_under_a_tool_budget` |
