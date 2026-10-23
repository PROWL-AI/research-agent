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
- **D6 (seam round 1).** A step that refers to a pending step's output starts a new data segment, so it waits for it
  (chunks of one segment run at once: at 3 and 5 workers, which every shipped runbook gets, the reference was never
  filled). A `.json` raw is sent compact and without the server's `billing`/`execution_time_ms` and the provider's
  request metadata (the extractor's own strip), so our cost and markup never reach the next provider. Only a data
  step can be referenced, and two different steps whose names read as the same reference leave it unresolved. The
  extractor reads a forwarding step's planned arguments, so a URL inside the forwarded page is not request
  provenance. Filed: B-085 (the cap is per reference, not per step).
- **D7 (seam round 2).** The wait is per dependency, not per segment: between two transforms, a step runs one level
  after the steps it references and every other step stays at level 0 beside the producer, so an unrelated hard
  failure in a later level strands nothing. An ambiguous name gets its own reason (`names two steps (...)`). The
  extractor sees a forwarding step's plan with the bound `{{name}}` values filled and the output references left as
  written.
- **D8 (seam round 3).** A reused step name takes the deepest level of its steps, so a reference to it waits for the
  last one at any worker count. Accepted trade-off: a forwarding step runs after the unrelated steps of its group,
  so under a runtime budget stop it is the one left unsent, and it ends such a run `pending` rather than
  `skipped_budget` (the report, the disclosures and the resume read both the same). Reserving budget for planned
  forwarding steps is filed as B-086.
- **D5.** Out of scope: picking a field out of the artifact (the whole raw is sent) and a per-tool cap.

## REQ

| REQ | Requirement | Verified by |
|---|---|---|
| C-1 | An output reference is filled from the earlier completed step's raw artifact and recorded as sent | `tests/test_plan_outputs.py::test_an_earlier_output_is_sent_in_place_of_the_reference` |
| C-2 | The output is cut at the cap with a marker | `test_output_refs_are_found_and_cut_with_a_marker`, `test_provider_text_inside_an_output_is_not_judged_as_template_text` |
| C-3 | Provider text inside the output is not judged as template text | `test_provider_text_inside_an_output_is_not_judged_as_template_text`; mutant `output-judged-as-planned` |
| C-4 | A reference to a step that did not complete is never sent | `test_a_reference_to_no_completed_step_is_never_sent` |
| C-5 | The planner is told the syntax and the cap | `test_the_planner_is_told_how_to_hand_over_an_output` |
| C-7 | The referencing step waits at 1, 3 and 5 workers; no billing or timing is forwarded; ambiguous and transform references are not sent | `test_a_referencing_step_waits_for_the_step_it_names`, `test_the_forwarded_output_carries_no_billing_or_timing`, `test_an_ambiguous_or_transform_reference_is_not_sent`; mutants `output-waits-for-its-step`, `output-strips-billing` |
| C-8 | Only referencing steps wait; an unrelated failure strands nothing; the ambiguity reason names the steps; the extractor keeps bound values | `test_only_the_referencing_steps_wait_and_unrelated_steps_stay_with_the_producer`, `test_an_unrelated_hard_failure_does_not_strand_the_other_steps`, `test_an_ambiguous_reference_names_the_steps_it_could_mean`, `test_the_extractor_sees_bound_values_but_not_the_forwarded_page` |
| C-6 | Docs true | README, `docs/runbook-authoring.md`, CORE-18 |
