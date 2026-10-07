# Fabric conformance

Contract: `fabric-agent-contract` 0.1.0 at `23f9fda4c05f8a3852246ee98d4f2adf74ed0875`
(local checkout `/tmp/fabric-contract-0.1.0`, lockfile `fabric-contract.lock.json`).

| Gate | Status | Receipt / next action |
|---|---|---|
| localStructure | PASS | `fabric-agent.json` + `fabric/` bundle validated structurally by `adapt_project.py check . --contract /tmp/fabric-contract-0.1.0`, 2026-10-07. |
| declarationShape | PASS | Manifest validated by selected contract schema at 23f9fda4c05f8a3852246ee98d4f2adf74ed0875, 2026-10-07. |
| protocolNegotiation | NOT_VERIFIED | Requires a Fabric host to negotiate the pinned revision (0.1.0 @ 23f9fda4) over MCP stdio. The server speaks MCP via `mcp` 1.x FastMCP; negotiation unproven. |
| semanticProbes | NOT_RUN | Probe is `effect: charge` — a live `research.run` debits a wallet and requires a scoped grant from a Fabric host. See `fabric/probes/assertions.md`; no receipt faked. |
| bindingReadiness | NOT_VERIFIED | Requires an admitted capability and a Fabric host runtime. |

The live surface the bundle declares exists and is testable offline:
`research.run` / `research.list_runbooks` / `research.get_status` /
`research.get_report` in `research_agent/mcp_server.py` (stdio,
`prowl-research mcp`). Offline coverage: `tests/test_mcp_server.py` exercises
all four tools with mocked MCP/LLM surfaces; `python scripts/validate_runbooks.py
--offline` passes. These receipts assert behavior, not host interop.

## Canary binding expectation

When a Fabric host admits this provider, it enters under a canary binding — a
checker on its output and a budget cap — regardless of who wrote it.
Unsupervised operation is a later, recorded promotion citing eval results and
run history.
