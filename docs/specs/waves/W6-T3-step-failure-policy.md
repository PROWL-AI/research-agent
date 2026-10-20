# W6-T3: step-failure policy (B-049)

Wave 6 of [`../2026-10-11-waves-canvas.md`](../2026-10-11-waves-canvas.md), node N-ACC. Public repository:
no absolute home paths or private names.

## Why

Live run `accept-finance-20261018b` (2026-10-18) executed 3 of 44 planned steps. Its first required step,
`google_finance` for the scoping quote, was answered «Google Finance didn't return any results»
(`unknown_error`); the worker treated that definite refusal as a hard failure
(`research_agent/agent/subagent.py:382` at `eb31bd3`), set `checkpoint.stop_reason`, and the segment loop
then skipped every later segment (`research_agent/agent/orchestrator.py:796`). Another tool in the same
segment (`dataforseo_serp_google_finance_quote`) had returned the quote. One empty answer cost the run.

## Source ledger

| Source | What it gave |
|---|---|
| `docs/evidence/backlog.md` B-049 | the defect and its live receipt |
| `research_agent/agent/subagent.py:309-385`, `orchestrator.py:470-500,780-800` | today's semantics: a definite refusal of a required step stops the worker; any stop_reason stops later segments; resume resets `failed` required steps to `pending` |
| `research_agent/prowl_client.py:43-56,217-238` | `ToolCallError` (definite), `DispatchOutcomeUnknown` (maybe executed); a refusal envelope carries `error_class` |
| prowl-app `mcp_server/tool_errors.py:21-48`, `mcp_server/tools.py:1472,1520,1614,1621` (`4328ad09`) | the server's error classes; only `insufficient_funds` repeats for every later call: `forbidden` is also sent for one provider's credentials, a denylisted tool or one tool outside the key's scope |
| `research_agent/service/runtime.py:67,73` | local refusals before dispatch: the service call limit, an unavailable call journal |
| `research_agent/evidence/terminal.py` | closed terminal codes; `step_failed` meant "a step failed hard"; restated by this change |
| `docs/ux/scenarios.md` CORE-01…16 | no scenario covers a refused step; CORE-11 covers lost evidence |
| retro, verification ledger, code graph | none found in this repository |

## Decisions (closed from the sources; the operator's standing rule: decide, record, continue)

- **D1.** A definite refusal of one data step is evidence of absence, not a broken run: the step is
  recorded (`failed` when required, `skipped_on_error` when optional) with the server's reason, and the
  worker takes its next step; later segments run.
- **D2.** A refusal that will repeat for every later call still stops: `insufficient_funds`, `forbidden`,
  and the service's local refusals (nothing was sent). So does an unknown dispatch outcome
  (`outcome_unknown`, unchanged) and every budget stop (unchanged).
- **D3.** Five definite refusals in a row inside one worker stop that worker: a cascade (a provider down
  for every tool) must not walk the whole plan.
- **D4.** A run in which a required step failed ends `partial` with terminal code `step_failed`; its
  `stop_reason` names the failed steps, and it is set before the writer runs, so the report discloses it.
- **D5.** Resume is unchanged: a `failed` required step runs again (a new attempt), completed and
  skipped steps never do.

## Decisions revised after certification (2026-10-20)

Three blind readings of `b9674fd` (unit pass, seam pass with risks, product fail) changed four decisions and
added three; the fix round implements them with tests in `tests/test_step_failure_policy.py`.

- **D2'.** Only `insufficient_funds` stops the run among server classes; `forbidden` fails one step (seam:
  the server sends it for a single provider or tool). The service's local refusals still stop.
- **D3'.** The refusals-in-a-row cap counts required steps only, across every worker of the run
  (`WorkerContext.refusals_in_row`); any successful dispatch resets it; optional refusals neither count nor
  reset (product: five optional fan-out refusals in a row must not end a run).
- **D4'.** A budget stop that follows a refusal keeps its own terminal code; its `stop_reason` also names
  the refused steps. Each step is named once, with the server's reason.
- **D5'.** Resume resets every `failed` step to `pending` with its reason cleared, optional ones included (a
  failed optional step exists only after a refusal that stopped the run).
- **D6.** The writer is told which steps were refused and why, separately from steps that did not run.
- **D7.** A transform is told which data steps before it returned no data.
- **D8.** A ledger-only report after an LLM-budget stop names `max_llm_usd` even when the run's code is
  `step_failed`.

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| REQ-1 | A definite refusal of a required data step marks it `failed` with the reason; the worker continues and later segments run | `test_a_refused_required_step_does_not_stop_the_run` |
| REQ-2 | An optional step's refusal stays `skipped_on_error`; a run whose only failures are optional ends `complete` | existing `test_on_error_skip_inside_worker` |
| REQ-3 | `insufficient_funds` and the service's local refusals stop the worker and the later segments (`forbidden` fails one step, D2') | `test_a_refusal_that_repeats_for_every_call_still_stops_the_run` |
| REQ-4 | An unknown dispatch outcome still stops the worker (unchanged) | existing outcome-unknown tests (`test_ka_contracts.py`) |
| REQ-5 | Five refusals of required steps in a row, across the run, stop it (D3') | `test_five_refusals_in_a_row_stop_the_worker` |
| REQ-6 | A failed required step makes the run `partial`/`step_failed`, with the failed steps named in `stop_reason` before the writer runs | `test_a_refused_required_step_does_not_stop_the_run` |
| REQ-7 | Resume asks every failed step again (D5'), never a completed one | `test_resume_after_a_refused_step_runs_only_that_step` |
| REQ-8 | Docs: CORE-17 scenario, README "How it works", board B-049 and the inventory | `docs/ux/lint.py` where present; review |
| REQ-9 | Live: the finance acceptance run on the fix executes past its first refused step | live run receipt in the board |
| REQ-10 | D2' to D8 | `test_forbidden_fails_one_step_and_the_run_goes_on`, `test_optional_refusals_neither_count_nor_stop`, `test_the_refusal_cap_is_shared_by_every_worker`, `test_a_budget_stop_after_a_refusal_keeps_its_code_and_names_the_refusal`, `test_a_failed_optional_step_after_a_stopping_refusal_runs_again_on_resume`, `test_the_writer_is_told_which_steps_were_refused_and_why`, `test_a_transform_is_told_which_steps_before_it_were_refused`, `test_an_llm_budget_stop_after_a_refusal_still_names_the_llm_budget` |

## Plan

1. Tests for REQ-1, 3, 5, 6, 7 (watched failing on `eb31bd3`).
2. `ToolCallError.stops_run` (class default False); the client sets it for `insufficient_funds`
   (D2'), the service runtime for its local refusals. `error_class` kept on the error.
3. Worker: a definite refusal that does not stop the run records the step and continues; a stopping one,
   or the fifth in a row, keeps today's stop.
4. Orchestrator: after execution, a run with failed required steps and no stop reason records
   `stop_reason` naming them (D4).
5. Adjust tests that pinned the old stop, each named in the change; full suite; docs; live run.
