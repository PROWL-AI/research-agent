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

| ID | Deliverable | Observable |
|---|---|---|
| FD-01 | Fabric service discovery, lifecycle, auth and build identity | Exact schemas; denied cross-origin/tokenless mutations; one process and persistent state |
| FD-02 | Agent capabilities with durable jobs, cancellation and trace | Real local MCP requests create/read/cancel jobs; same request cannot duplicate execution |
| FD-03 | Operator overview and searchable request list | State, freshness, requester, chain, spend and next action visible; empty/error/offline states |
| FD-04 | Request inspection and readable results | Input, steps, raw/data table, sources and report accessible without leaving request |
| FD-05 | Chain participation | Project/chain/node/parent/requester/trace retained; distinguish caller-declared links from Fabric-verified binding |
| FD-06 | Billing | Tool vs LLM, actual vs estimated vs unknown, per run/model/day; fixtures excluded |
| FD-07 | Model and orchestrator settings | Validated revisioned config; diff before apply; active run keeps captured config |
| FD-08 | Human intervention | Bound proposal, approve/reject, expiry, stale revision refusal; cancel is explicit and audited |
| FD-09 | Tutorials | Safe sample request with labeled synthetic results, no provider calls or real spend |
| FD-10 | Detailed design, responsive keyboard UI | Scenarios, screen states, token source, browser walkthrough with receipts |
| FD-11 | Delivery and operator entry point | Tests, schema/semantic/runtime gate table, registered service/host link or exact unresolved gate |

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
