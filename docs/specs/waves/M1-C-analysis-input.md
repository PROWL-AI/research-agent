# M1-C: hand a whole earlier output to an analysis tool (B-074)

Wave C of [`../2026-10-22-milestone-m1.md`](../2026-10-22-milestone-m1.md). Route: `/task-pipeline`; the change is in
the planner contract and the dispatch path, no user interface. Public repository: no absolute home paths or private names.

## Source ledger

| Source | What it gave |
|---|---|
| `docs/evidence/backlog.md` B-074; live run `accept-teardown-20261021b` (three steps); survey of 342 saved data steps (2026-10-22) | the planner wrote `[substitute full firecrawl_scrape_website output for clickup.com ...]` into `gemini_analyze_website`; since B-070 such a step is not sent, so the analysis is lost |
| `research_agent/agent/bindings.py` | `{{name}}` takes a short value a transform grounds in a raw artifact (B-065); any `{{...}}` with an invalid name counts as unresolved |
| `research_agent/agent/subagent.py` dispatch (`substitute`, `_not_sent_reason`, `bound_arguments`) | the filled arguments are judged, recorded as `bound_arguments` and re-sent as recorded on an unknown outcome |
| `research_agent/evidence/store.py` `read_artifact(raw_ref, sha256)` | a raw artifact is read back only when its recorded sha256 matches |
| `research_agent/agent/orchestrator.py` `_PLAN_INSTRUCTIONS` | the planner rules about placeholders |

Contradictions: none.

## Decisions

- **D1.** A reference is `{{output:<earlier step name in snake_case>}}`. Today such a placeholder already counts as
  unresolved (its name is not a binding name), so a plan written before this change behaves as before.
- **D2.** It is filled from the stored raw artifact of the last completed step of that name before this step,
  sha256-checked, cut at `bindings.OUTPUT_CAP` (16 000 characters) with `[cut: N more characters]`. The value is the
  artifact itself, so no grounding pass is needed and no model can invent it.
- **D3.** The not-sent checks (B-065, B-070, B-071) judge the arguments with each output reference replaced by a
  neutral marker: provider text inside an output may hold any template-like shape and is never taken for the plan's
  own template text.
- **D4.** A reference nothing fills is a missing placeholder: the step is not sent (`not sent: no earlier step
  resolved {{output:<name>}}`), with no attempt and no bill. The sent text is recorded as `bound_arguments`, so a
  re-send after an unknown outcome sends the same text.
- **D5.** Out of scope: picking a field out of the artifact (the whole raw is sent) and a per-tool cap.

## REQ

| REQ | Requirement | Verified by |
|---|---|---|
| C-1 | An output reference is filled from the earlier completed step's raw artifact and recorded as sent | `tests/test_plan_outputs.py::test_an_earlier_output_is_sent_in_place_of_the_reference` |
| C-2 | The output is cut at the cap with a marker | `test_output_refs_are_found_and_cut_with_a_marker`, `test_provider_text_inside_an_output_is_not_judged_as_template_text` |
| C-3 | Provider text inside the output is not judged as template text | `test_provider_text_inside_an_output_is_not_judged_as_template_text`; mutant `output-judged-as-planned` |
| C-4 | A reference to a step that did not complete is never sent | `test_a_reference_to_no_completed_step_is_never_sent` |
| C-5 | The planner is told the syntax and the cap | `test_the_planner_is_told_how_to_hand_over_an_output` |
| C-6 | Docs true | README, `docs/runbook-authoring.md`, CORE-18 |
