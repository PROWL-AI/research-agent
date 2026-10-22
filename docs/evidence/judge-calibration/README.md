# Judge veto proof and judge metering — evidence (W6-T1, KA-G02 offline half, B-017, B-041)

Packet: [W6-T1](../../specs/waves/W6-T1-judge-calibration.md). Scenario: CORE-13 in
[`docs/ux/scenarios.md`](../../ux/scenarios.md). This page proves that the judge's **code checks** reject
planted defects. It is not a calibration of a judge model: the fixtures were written with the checks
(in-sample), and the model in the offline run is a constant fake. The configured judge model's agreement with the fixture labels was measured live on 2026-10-19 (table below); its agreement with a person on real runs is still NOT_RUN.

| Gate | Result | Evidence |
|---|---|---|
| A lenient model (0.95 on every dimension) fails every planted-defect fixture (in-sample, author-written) | PASS: 6 / 6 planted fail, 5 / 5 honest pass (the fifth, `honest-real-shapes`, holds the four honest shapes a real report was falsely flagged for, B-055) | [offline run](offline-calibration.log); `tests/test_judge_calibration.py` |
| Each defence is load-bearing | 62 / 62 planted mutations killed (2026-10-22, tree of `550dc99`; the judge's own rows plus the dispatch guards of B-070/B-071) | [mutations](mutations.log); `python scripts/mutation_check.py` |
| The judge's own spend is checked by estimate before each call and recorded beside the run | PASS (offline, mocked provider) | `test_the_judge_spend_is_recorded_beside_the_run_not_in_it`, `test_the_judge_refuses_to_spend_above_its_ceiling` |
| A model that does not answer is a judge error (exit 2), and the judge needs no Prowl key | PASS (offline, unreachable provider) | `test_the_judge_needs_no_prowl_key_and_a_model_failure_is_exit_2` |
| The checks on real reports | surveyed, see below | [survey](local-runs-survey.json); `python evals/survey_runs.py` |
| The configured judge model on the fixtures (`evals/calibrate.py --live`) | PASS, 2026-10-19: `anthropic/claude-haiku-5.5`, agreement 1.0 on 10 fixtures (6 planted fail, 4 honest pass), no false alarms, judge spend USD 0.0077. The model's own totals: honest 0.81 to 0.92 (all above the 0.7 threshold, so the model raises no false alarm); planted 0.45 to 0.76, so the model alone rejects 4 of 6, and `hidden-conflict` (0.74) and `verified-mislabel` (0.76) fail only through the code checks' veto. Fixtures are in-sample (written with the checks) | [live run](live-calibration-2026-10-19.log), run by the operator |
| Labelled agreement with a person on real runs | NOT_RUN: the `prowl_` key exists since 2026-10-18 (B-043 closed), but a live run stops after 3 of 44 steps (B-049), so there is no complete real report to label yet | KA-G02 live half |

The judge's ceiling (`--max-usd`, default 0.50) is a check of each call's **estimate** before it is
sent, not a hard ceiling: an unlisted `RESEARCH_JUDGE_MODEL` is estimated at the top price
(`research_agent/pricing.py`), which can refuse a large report at the default. With the default judge
model a judging of the largest local report estimates at about USD 0.004.

## False positives found on a real report (B-055, 2026-10-20)

On the first complete live report (`accept-finance-20261020b`) the checks raised 19 defects; 15 were false. Fixed and
pinned by the `honest-real-shapes` fixture: a signed figure (`-1.06%`, `DKK -14.7 bn`: the number patterns drop the minus,
so the sign is not compared); a figure stated in a numeric claim's text (`+21%` beside a stored absolute value); a table
figure in its column's unit (12,000 in a `DKK m` column for a 12-billion claim, allowed only for figures of 1,000 or more,
so a lost scale letter like `$4` for `$4B` still fails); a conflict table whose header row carries `[CONFLICT]`. Thirteen
of the 19 came from claims about the search request itself (timestamps, detected locations), which extraction no
longer sees (B-054). The 4 left are real: a conflict cited in another section without its tag, and two quoted headlines
the cited claims do not hold.

Three more honest shapes from `accept-finance-20261020d` (B-060, 2026-10-21) joined `honest-real-shapes`: a figure that names a template item ("the 50% deterioration model"), a figure carrying the writer's assumption marker, and claim ids inside a conflict tag ("[CONFLICT w/ C32/C45]"), which name the rival readings rather than cite the line's figure. Each exemption has its own mutant (`assumption-marker`, `label-figure`, `conflict-tag-ids`).

## What the checks do not catch (named, not vetoed)

- An uncited figure: it lowers `citation_accuracy` through the lint cap; it is not a veto.
- A `VERIFIED` tag the status check does not read: in bold (`**(VERIFIED)**`), in a table's status
  column, or after the first of two adjacent blocks (`[C2][C1] (VERIFIED)` checks only `[C1]`).
- A wrong figure that happens to equal another bare number a cited claim carries, or one inside a
  sentence the writer marked "derived": the checks read figures and the derived mark, not meaning.
- A conflict cited under a heading or list lead-in that is a conflict register (the tag in brackets or
  parentheses, `[CONFLICT]` / `(CONFLICT)`, or the words "conflict register"; a status legend listing
  CONFLICT — a line naming two or more statuses, tagged or not — is not one): that is the disclosure the runbooks require, so a register that
  mislabels an unrelated claim is not caught.

## The checks on real reports

The checks ran over the six reports in this checkout's local `runs/` (pre-wave-3 runs; their ledgers
load as schema 2, so statuses are recomputed). The run directories are local and not published; the
survey file holds counts only. Two passes of false positives were reviewed and fixed before this
receipt — a number in a name ("Fortune 500"), scale suffixes (`$4B`, `1.5 million`), source titles and
headlines beside a backed quotation, typographic apostrophes, a preamble disclosure, the `[CONFLICT]`
register the runbooks require (heading or lead-in), Source-log rows, "vs." read as a sentence end, the
fidelity pass's composite `[UNVERIFIED, C2]`, quoted search phrases, bare numbers that carry a value
("interest 36 [C18]"), and the writer's "derived" figures. A second certification then tightened what the
first pass loosened: only the upper-case tag or a conflict-register heading or lead-in counts as
disclosure, "derived from" is not the derived mark, a number inside "$12M" carries no value, a
non-numeric co-citation no longer silences the value check, and "impartial" no longer reads as
"partial". A third round restored what the second over-tightened: a numbered or bold "Source log"
heading ("## 10. Source Log", as the runbooks number it) is provenance again, a claim stored in a
scaled unit (value 12, unit "million USD") matches "$12M", and "partially" discloses a partial run.
B-046 then accepted the parenthesised `(CONFLICT)` as a register marker and limited unit scaling to scale
words and a letter beside a currency ("USD m", "$M"), so a claim in metres or bytes is not read as millions.

What remains — 86 `status_mislabel`, 25 `conflict_hidden`, 10 `quote_not_in_ledger`, 2 `value_mismatch` — was
read. The status mislabels (the B-045 check) are citations the reports tag `VERIFIED` whose claims schema 2
does not hold as verified: 79 were verified in schema 1 only by the extractor's own "verbatim" flag, with no
quote (KA-08), 6 are single-source claims without a quote, 1 is a conflict. Of the rest: the conflict hits
cite claims the ledger groups as conflicting, mostly in one run whose pre-schema-2 subjects lumped different
quantities together (a ledger-side cause, not the writer's); the quotations are ad copy and user quotes the
ledger never recorded verbatim; one mismatch cites a claim about another quantity, the other quotes ad copy
as "2M+ teams" where the cited claim records "3,000,000+". A new live run is the test of the current writer
— the live half of KA-G02.
