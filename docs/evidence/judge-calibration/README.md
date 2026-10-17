# Judge veto proof and judge metering — evidence (W6-T1, KA-G02 offline half, B-017, B-041)

Packet: [W6-T1](../../specs/waves/W6-T1-judge-calibration.md). Scenario: CORE-13 in
[`docs/ux/scenarios.md`](../../ux/scenarios.md). This page proves that the judge's **code checks** reject
planted defects. It is not a calibration of a judge model: the fixtures were written with the checks
(in-sample), and the model in the offline run is a constant fake. Calibration — the configured judge
model's agreement with labels, then with a person on real runs — is the live half, still NOT_RUN.

| Gate | Result | Evidence |
|---|---|---|
| A lenient model (0.95 on every dimension) fails every planted-defect fixture (in-sample, author-written) | PASS — 5 / 5 planted fail, 3 / 3 honest pass | [offline run](offline-calibration.log); `tests/test_judge_calibration.py` |
| Each defence is load-bearing | 36 / 36 planted mutations killed | [mutations](mutations.log); `python scripts/mutation_check.py` |
| The judge's own spend is checked by estimate before each call and recorded beside the run | PASS (offline, mocked provider) | `test_the_judge_spend_is_recorded_beside_the_run_not_in_it`, `test_the_judge_refuses_to_spend_above_its_ceiling` |
| A model that does not answer is a judge error (exit 2), and the judge needs no Prowl key | PASS (offline, unreachable provider) | `test_the_judge_needs_no_prowl_key_and_a_model_failure_is_exit_2` |
| The checks on real reports | surveyed, see below | [survey](local-runs-survey.json); `python evals/survey_runs.py` |
| The configured judge model on the fixtures (`evals/calibrate.py --live`) | NOT_RUN — the LLM key exists (vault `prowl-research-agent/prod/RESEARCH_LLM_API_KEY`, USD 15 monthly ceiling), but a `--live` flag is a manual gate on the operator's machine | the operator runs it, or authorises live flags for the agent's session; command in [HANDOFF](../../HANDOFF.md) |
| Labelled agreement with a person on real runs | NOT_RUN — needs live runs, which need a `prowl_` key (B-043) | KA-G02 live half |

The judge's ceiling (`--max-usd`, default 0.50) is a check of each call's **estimate** before it is
sent, not a hard ceiling: an unlisted `RESEARCH_JUDGE_MODEL` is estimated at the top price
(`research_agent/pricing.py`), which can refuse a large report at the default. With the default judge
model a judging of the largest local report estimates at about USD 0.004.

## What the checks do not catch (named, not vetoed)

- An uncited figure: it lowers `citation_accuracy` through the lint cap; it is not a veto.
- A claim the ledger holds as `assumed` labelled `VERIFIED` in the report (CORE-09): no check yet — B-045.
- A wrong figure that happens to equal another bare number a cited claim carries, or one inside a
  sentence the writer marked "derived": the checks read figures and the derived mark, not meaning.
- A conflict cited under a heading or list lead-in that is a conflict register (the tag `CONFLICT`
  or the words "conflict register"): that is the disclosure the runbooks require, so a register that
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
"partial".

What remains — 25 `conflict_hidden`, 10 `quote_not_in_ledger`, 2 `value_mismatch` — was read: the
conflict hits cite claims the ledger groups as conflicting, mostly in one run whose pre-schema-2
subjects lumped different quantities together (a ledger-side cause, not the writer's); the quotations
are ad copy and user quotes the ledger never recorded verbatim; one mismatch cites a claim about
another quantity, the other quotes ad copy as "2M+ teams" where the cited claim records "3,000,000+". A new live run is the test of the current writer — the live half of KA-G02.
