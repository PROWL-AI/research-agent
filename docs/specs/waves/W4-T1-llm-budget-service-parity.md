# W4-T1 — LLM budget and service parity (KA-G01, B-003, B-004, B-005, B-029, B-035)

Wave 4 of [`../2026-10-11-waves-canvas.md`](../2026-10-11-waves-canvas.md). **Read §2 N-LLMB and N-SVC in full —
they are the contract.** Builds on wave 2 (attempt ledger in the v2 checkpoint, `Checkpoint.spend_usd(kind)`,
`cost_source`) and wave 3 (ledger v2). Public repository: no absolute home paths or private agent names.

## Exit criteria (canvas §7, written before the wave)

A test stops the next LLM call before `max_llm_usd`, including across resume and retries; a missing
price is never 0; service parity tests (429 retry, reconnect, outcome mapping); full suite green.

## N-LLMB — one LLM route, every call an attempt

1. `Budget.max_llm_usd: float | None = None` (runbook front matter, `gt=0`). Run-level override, first
   wins: CLI `--max-llm-usd`, MCP/Fabric input `max_llm_usd`, env `RESEARCH_MAX_LLM_USD`, the runbook's
   value, `config.DEFAULT_MAX_LLM_USD` (stated in README; never unlimited).
2. `LLMClient` records each **completion attempt** (each HTTP request, retries included) in the run's
   attempt ledger as `kind="llm"` with the stage that made it (`planner`, `extract`, `transform`,
   `writer`, `repair`, `citations`, `judge`), the model, tokens, and cost: provider `usage.cost` when
   present, else a price-table estimate (`research_agent/pricing.py`, per model in/out USD per 1M tokens),
   else `unknown` at the most expensive known model's price — never 0. A failed or truncated response that
   the provider billed keeps its tokens and cost.
3. **Pre-call gate** in the client: `spend("llm") + estimate(next call) > max_llm_usd − writer_reserve`
   raises `LLMBudgetExceeded` for research stages; the orchestrator stops research with
   `terminal_code=budget_llm` (partial report, disclosed). The writer, repair and citation stages may spend
   into `writer_reserve` (config, documented) so a report is always produced from what was gathered; at the
   hard cap even they stop and the report is written from the draft so far or the run ends
   `budget_llm` with the evidence intact.
4. The estimate of the next call: prompt tokens ≈ chars/4 of the messages + `max_tokens` (or the stage
   default) priced at the route's model.
5. Resume reads LLM spend from the checkpoint's attempt ledger (survives restarts like KA-12).
6. `stats.llm_usage` keeps its token view and gains `cost_usd` + `cost_source`.
7. **Models** (the operator's model choice, 2026-10-14): defaults move to —
   strong tier (planner, writer, judge) `xiaomi/mimo-v2.6-pro`, cheap tier (extraction, transforms)
   `deepseek/deepseek-v4.1-flash`; the judge defaults to a **different vendor** than the writer
   (`qwen/qwen3.8-flash` when the writer is mimo). Env overrides stay. The price table carries these five plus
   the previous defaults (for old runs' estimates). B-001 replaces only the route resolver later.

## N-SVC — the service runs the same core

- **B-003** `ObservedLLM` stops being a second transport: it subclasses/observes `LLMClient.complete`
  (retries with Retry-After, `max_tokens`-scaled read timeout, `LLMError` mapping, truncation handling)
  and only adds the call journal row + traceparent header around each attempt.
- **B-004** `ObservedProwl._rpc` keeps the client's reconnect for **metadata** calls (catalog, prices);
  a paid `prowl_call_tool` dispatch is still one attempt per idempotency key (a lost reply is not
  permission to pay again).
- **B-005** `Runtime.envelope.outcome` derives from the research status / terminal_code: `complete` →
  `success`, `partial` → `partial`, failed → `failure`; tool and tutorial jobs keep theirs. Mapping table in
  `docs/FABRIC.md`.
- **B-029** `validate_runbooks` warns when a runbook names failover alternatives in its text that its
  allowlist does not carry.
- **B-035** the service configures logging: INFO events to a size-capped rotating file under the
  descriptor's log path (5 × 5 MB), stdout/stderr to the same handler; `doctor` reports the log path.

## Tests (TDD)

- LLM gate: a fake transport with fixed `usage.cost` stops the next research-stage call once the cap would
  be crossed; the writer still runs inside the reserve; resume reads prior LLM spend from the checkpoint;
  retries are each recorded and counted; a model with no price is estimated at the conservative price.
- Service: 429 then 200 → one journal row per attempt, success; reconnect on a dropped metadata session;
  outcome mapping table test; failover-allowlist warning; logging config writes INFO events to the file.
