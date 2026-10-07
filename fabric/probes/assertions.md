# Admission probe assertions

Probe: `safe-shape-probe` with `fixtures/admission-input.json` (a minimal
`research.run` invocation, one competitor, `wait=true`).

What the probe proves when run:

- The result validates against `capability-output.schema.json`
  (`run_id` + `status` always present; full envelope on `wait=true`).
- `run_id` in the result resolves to a checkpoint (`research.get_status`) and,
  on completion, a report (`research.get_report`) — the declared job pattern
  round-trips.
- Every number in the returned report traces to a ledger claim id `[C..]` in
  the run's `ledger.json` (writer gate, enforced by `lint_report`).
- Timeout and cancellation return a typed partial result (`status: "partial"`
  with `skipped_steps`), never a silent failure.

Side-effect ceiling — HONEST NOTE:

`research.run` is declared `effect: charge`: a live probe debits the operator's
Prowl wallet (billed MCP tool calls) and spends LLM tokens. The manifest's
probe ceiling `none` therefore **cannot be met by a live `research.run` probe**.
This probe is marked **NOT_RUN** until a Fabric host exists that can issue a
scoped grant for the charge. No receipt is faked: the only executed checks to
date are offline (unit tests with mocked MCP/LLM surfaces and the offline
runbook validator), which assert the envelope shape but make no billed calls.

When a host with a scoped grant is available, run the probe against the
smallest possible scope (the admission fixture: one competitor, wait=true) and
cap the runbook budget before admission.
