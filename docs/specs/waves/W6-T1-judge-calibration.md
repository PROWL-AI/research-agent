# W6-T1 — judge calibration and judge metering (B-017, KA-G02 offline half, B-041)

Wave 6 of [`../2026-10-11-waves-canvas.md`](../2026-10-11-waves-canvas.md), §2 N-ACC. Builds on waves 1–5
(merged at `12ad137`). Public repository: no absolute home paths or private names.

The live half of wave 6 — a labelled agreement number from a real judge model, live finance and
subscription runs (KA-G02), the host chain (KA-G03), the native panel (FD-14), server dedupe (CORE-14)
and the heavy-runbook cap (B-040) — needs keys (B-042, B-043), the hub's JWKS and the operator's host
update. This packet is the part that closes offline, so the live half starts from a judge that is
already known to reject planted defects.

## Exit criteria

- The judge fails **every** planted-bad fixture even when its model is maximally lenient (scores
  0.95 on every dimension): each planted defect is caught by a code check, not by the model's mercy.
- The good fixtures still pass under the same lenient model (no check fires on an honest report).
- Every judge LLM attempt is checked against the judge's own USD ceiling before it is sent and
  recorded in a judge ledger beside the run (`judge-ledger.json`), never in the run's checkpoint; a
  refusal is a judge error (exit 2), never a FAIL.
- A calibration harness (`evals/calibrate.py`) runs the judge over the fixture set and prints the
  verdict per fixture and the agreement with the labels; offline it runs with the lenient fake, live
  it runs with the configured judge model once a key exists.

## Items, in build order

1. **Code-confirmed defects (vetoes).** `programmatic_signals` adds `defects`: a list of
   `{kind, claim, text}` the code proves, each one a veto — `passed` is false whatever the scores:
   - `missing_ref` — a citation that names no ledger claim (the lint already finds it);
   - `quote_not_in_ledger` — a sentence citing exactly one claim quotes text (three words or more) and
     none of its quotations is backed by that claim's quote or text (70 % of word stems; a source title
     beside the backed quotation is fine);
   - `value_mismatch` — a sentence citing exactly one numeric claim carries numbers, none of which is
     the claim's value (1 % tolerance; figures read as the writer's lint reads them, plus `$4B`,
     `$30K`, `1.5 million`; a number in a name such as "Fortune 500" is not a figure);
   - `conflict_hidden` — a claim in status `conflict` is cited in a sentence without `CONFLICT`;
   - `partial_undisclosed` — the run is partial and the report does not say so before its first
     section (title or preamble).
   Uncited numbers keep their existing cap (`citation_health_cap`) and are not a veto: a report can
   have a stray figure without being false. Caps added: `completeness` ≤ covered/required sections,
   `source_quality` ≤ the primary-source ratio.
2. **Fixtures.** `evals/fixtures/planted/*.json`: one honest report and one fixture per defect kind
   (CORE-13's list: invented citation, invented quote, unconfirmed number, hidden conflict,
   undisclosed partial run), each with its label and expected defect kinds.
3. **Harness.** `evals/calibrate.py [--live]`: builds each fixture into a temporary run, judges it,
   prints a table, the agreement and the judge spend; exit 1 when a planted-bad fixture passes or an
   honest one fails, 2 on a judge error.
4. **Judge metering (B-041).** `judge_run(..., max_usd)` attaches an `LlmMeter` over a judge ledger;
   the CLI takes `--max-usd` (default 0.50) and prints the judge's spend.

## Out of scope here

The labelled-set agreement with a human on real runs (needs a live model), KA-G02's live runs,
KA-G03, FD-14, CORE-14, B-040, B-044 re-probe.
