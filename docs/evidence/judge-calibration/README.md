# Judge calibration — evidence (W6-T1, KA-G02 offline half, B-017, B-041)

Packet: [W6-T1](../../specs/waves/W6-T1-judge-calibration.md). Scenario: CORE-13 in
[`docs/ux/scenarios.md`](../../ux/scenarios.md).

| Gate | Result | Evidence |
|---|---|---|
| A lenient model (0.95 on every dimension) fails every planted-defect fixture | PASS — 5 / 5 planted fail, 3 / 3 honest pass, agreement 1.0 | [offline calibration](offline-calibration.log); `tests/test_judge_calibration.py` |
| Each code check is load-bearing | 13 / 13 planted mutations killed | veto, each defect kind, quotation backing, figure reading, scale suffix, judge meter, completeness cap |
| The judge's own spend is checked before each call and recorded beside the run | PASS (offline, mocked provider) | `test_the_judge_spend_is_recorded_beside_the_run_not_in_it`, `test_the_judge_refuses_to_spend_above_its_ceiling` |
| The checks on real reports | surveyed, see below | [survey](local-runs-survey.json) |
| Agreement of the configured judge model with the labels (`--live`) | NOT_RUN — no LLM key for this service yet | B-042; the fixtures and the harness are ready, the run costs under USD 0.50 per fixture by the judge's own ceiling |
| Labelled agreement with a human on real runs | NOT_RUN — needs live runs | KA-G02 live half, wave 6 |

## The checks on real reports

The code checks ran over the six reports in this checkout's local `runs/` (pre-wave-3 runs; their
ledgers are loaded as schema 2, so statuses are recomputed). Counts per kind are in the survey file;
the run directories are local and not published. The first pass produced false positives, each
reviewed and fixed before this receipt:

- a number in a name ("Fortune 500") read as a figure — figures now follow the writer lint's own
  definition of a metric;
- `$4B`, `$30K`, `1.5 million` read without their scale — the scale right after a number is read;
- a source title quoted beside a backed quotation, a headline restated in the claim's words, a
  typographic apostrophe — a sentence passes when any of its quotations is backed (70 % of word
  stems, typography normalized);
- a partial run disclosed in the preamble rather than the title — the disclosure may sit anywhere
  before the first section.

What remains on those reports after the fixes was read and is a real disagreement between the report
and its ledger: 43 citations of a claim the ledger holds in conflict without `CONFLICT` (often marked
`VERIFIED` in the report), 9 quotations the cited claim does not carry (ad copy and user quotes the
ledger never recorded, two mis-citations), 1 percentage cited to a claim about another quantity.
These reports predate ledger schema 2 and the writer's conflict rule; a new live run is the test of
whether the current writer avoids them — the live half of KA-G02.
