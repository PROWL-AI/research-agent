# Prowl Research in Fabric — brief, 2026-10-10

## Objective and authority

Operator requests a Fabric-adapted Prowl research agent, visible in dashboards,
usable by other agents in chains, with readable requests/results, charts, errors,
billing, model/orchestrator settings, tutorials and human intervention.
Implementation, local reversible service installation, focused verification and
branch delivery are in scope. No paid provider trials, publication, source merge
or changes to unrelated Fabric/Research Agent installations are assumed.
Model: current session model, inherited; no model switch. Execution: autonomous,
one implementation agent. Operator explicitly selected working UI in Fabric; no Figma copy. The selected pipeline profile is inspect → design
and contracts → implement → local verification → durable handoff. Every stage
carries scope, evidence, dependencies and resume. User request supplies the brief;
no further approval is needed for reversible implementation.

## Sources and contradictions

- Existing Prowl agent at 9a7f14bb: CLI, stdio MCP, Orchestrator, local run artifacts.
- Kimi remediation queue: 12 open defects; service adaptation does not silently
  close them or call baseline tests live acceptance.
- Fabric Agent Contract 0.1.0, pinned 623bf61358c339cb10297807b3f024b5d9f1f327:
  service + interop, jobs, trace context, descriptor, auth and usage.
- Fabric Dashboards source: host displays a service-owned same-origin dashboard;
  app never starts an arbitrary background process; launchd owns supervision.
- Prowl brandbook: editorial luxury tokens and quiet, specific operator copy.
- MCP official latest fetched 2026-10-10 resolves 2026-07-28:
  https://modelcontextprotocol.io/specification/2026-07-28.
- Contradictions: old manifest advertises 2026-07-28 over an SDK surface without
  proof of that revision. Existing result states and verified labels have known
  failure paths. No inference from a manifest or healthy HTTP response to admission.

## Requirements and observable checks

| ID | Deliverable | Observable | Status (2026-10-11) |
|---|---|---|---|
| FD-01 | Fabric service discovery, lifecycle, auth and build identity | Exact schemas; denied cross-origin/tokenless mutations; one process and persistent state | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-02 | Agent capabilities with durable jobs, cancellation and trace | Real local MCP requests create/read/cancel jobs; same request cannot duplicate execution | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-03 | Operator overview and searchable request list | State, freshness, requester, chain, spend and next action visible; empty/error/offline states | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-04 | Request inspection and readable results | Input, steps, raw/data table, sources and report accessible without leaving request | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-05 | Chain participation | Project/chain/node/parent/requester/trace retained; distinguish caller-declared links from Fabric-verified binding | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-06 | Billing | Tool vs LLM, actual vs estimated vs unknown, per run/model/day; fixtures excluded | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-07 | Model and orchestrator settings | Validated revisioned config; diff before apply; active run keeps captured config | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-08 | Human intervention | Bound proposal, approve/reject, expiry, stale revision refusal; cancel is explicit and audited | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-09 | Tutorials | Safe sample request with labeled synthetic results, no provider calls or real spend | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-10 | Detailed design, responsive keyboard UI | Scenarios, screen states, token source, browser walkthrough with receipts | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-11 | Delivery and operator entry point | Tests, schema/semantic/runtime gate table, registered service/host link or exact unresolved gate | delivered locally; gates in [VERIFICATION](VERIFICATION.md) |
| FD-12 | Callee side of DEC-0039 delegation tokens, by trust tier | On this machine and the operator's enrolled machines the operator's instruction is the authority: no delegation token is required; a token a local caller does send is verified and recorded for attribution only. A token is required only for callers across the machine boundary or another person's calls (Fabric ADR-0144 amendment 4, Fabric commit `19ad05ca`, operator decision 2026-10-11) | open — wave 5 ([canvas §2 N-FAB](../../specs/2026-10-11-waves-canvas.md)); Fabric host issuer not built yet; host-chain acceptance is KA-G03, wave 6 |
| FD-13 | Provider wiring through an Observatory consumer | Service launched vault-only with `PROWL_API_KEY` and `RESEARCH_LLM_API_KEY`; status leaves `degraded` | open — wave 5, agent work since the canvas revision of 2026-10-11: the LLM key is issued through an Observatory door; the `prowl_` key has no door yet, and wave 5 adds one or records the gap |
| FD-14 | Native panel rendering in the Fabric Dashboards host | The service page observed inside the host app, not a browser stand-in | NOT_VERIFIED — wave 6; installed host 0.6.7, current 0.7.1; host upgrade is the operator's administration |

FD-12 originally assumed a hub-forwarding route (the host relays a call to this service). Fabric ADR-0144 (passioncode-ai/fabric, accepted 2026-10-11) retired that route: the hub issues the delegation chain and callers call this service directly. [HUB-PACKET](HUB-PACKET.md) still describes the retired route and is rewritten in wave 5 (B-014).

## Architecture decisions

Service id: prowl-research. Separate from sshleg/research-agent. One service-owned
SQLite execution/event/config store outside the checkout; immutable installed
release. Existing Orchestrator executes research; no third research core.
Fabric owns cross-agent ordering; Prowl owns one bounded research job. Direct tool
requests are a separate capability. MCP service adapter speaks the pinned Fabric
profile; legacy stdio entry remains available with its own revision truth.
No automatic retries of ambiguous paid dispatch; restart marks interrupted work
for inspection. Existing raw files and ledger are evidence, not proof of truth.
Model/provider secrets remain outside dashboard/config/Git. Hosted credentials
are supplied by Observatory consumer references only. No outbound agent messaging
is needed to implement or validate the local protocol.

## Work packets and dependencies

1. UX + design + contracts: this brief, scenarios, API/event schema, capability map.
2. Persistent service/runtime: depends on schema and lifecycle contracts from 1.
3. Dashboard: consumes API/event/config contracts from 1 and live views from 2.
4. Verify/install: consumes immutable code + probes; local synthetic execution
   proves infrastructure only. Paid/provider and project-binding gates separate.
5. Handoff: exact commits, checks, service identity, deferred gaps, next task.

Resume: complete scenarios and screen design, implement service and client adapter,
then run one safe tutorial through real local MCP and inspect it in dashboard.
