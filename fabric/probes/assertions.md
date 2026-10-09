# Admission probe assertions

Probe: `safe-shape-probe` with `fixtures/admission-input.json` (a minimal
`research.run` invocation, one competitor, `wait=false`).

`wait=false` is deliberate: the probe's `timeoutMs: 30000` cannot span a live
run (minutes of billed tool calls), and the job-handle return is the only
response bounded well under that ceiling. The probe therefore asserts the
envelope shape and the job-pattern round-trip, not a completed report.

What the probe proves when run:

- The result validates against `capability-output.schema.json`
  (`run_id` + `status: "running"`; the full envelope is only returned by
  `wait=true`, which no 30s probe window can observe on a live run).
- `run_id` in the result resolves to a checkpoint (`research.get_status`) and,
  on completion, a report (`research.get_report`) — the declared job pattern
  round-trips.
- Every number in the returned report traces to a ledger claim id `[C..]` in
  the run's `ledger.json` (writer gate, enforced by `lint_report`).
- Timeout/cancellation produce a typed partial checkpoint observable via
  `research.get_status` (`status: "partial"` with `skipped_steps`); the MCP
  call itself is cancelled and returns no result envelope.
- A run that fails outright surfaces as an MCP tool error, not a typed
  result — `status: "failed"` exists only on the checkpoint, which is why the
  output schema's status enum is `running | complete | partial`.

Side-effect ceiling — HONEST NOTE:

`research.run` is declared `effect: charge`: a live probe debits the operator's
Prowl wallet (billed MCP tool calls) and spends LLM tokens. The manifest's
probe ceiling `none` therefore **cannot be met by a live `research.run` probe**.
This probe is marked **NOT_RUN** until a Fabric host exists that can issue a
scoped grant for the charge. No receipt is faked: the only executed checks to
date are offline (unit tests with mocked MCP/LLM surfaces and the offline
runbook validator), which assert the envelope shape but make no billed calls.

When a host with a scoped grant is available, run the probe against the
smallest possible scope (the admission fixture: one competitor, wait=false)
and cap the runbook budget before admission.
