# FD-12 — admit Prowl through Fabric hub

Status: BLOCKED_BY_HOST_CAPABILITY, not an operator permission request. Owner: passioncode-ai/fabric. Prowl service side is available on branch feat/fabric-dashboard-20261010, runtime commit 891fbc995cb382ec6ccaed5f1b91611918b931c7. This packet does not change Fabric's working tree, production pins or grants.

## Concrete blocking evidence

Fabric source inspected at `a7fa444cace6be4a38f0e42cdea659e43a2e7ed6`:

- [`apps/desktop/src/shared/access.ts:29`](https://github.com/passioncode-ai/fabric/blob/a7fa444cace6be4a38f0e42cdea659e43a2e7ed6/apps/desktop/src/shared/access.ts#L29): `CONNECTABLE_PRODUCTS = ['fabric-inbox']`.
- [`apps/desktop/src/main/hubCall.ts:305`](https://github.com/passioncode-ai/fabric/blob/a7fa444cace6be4a38f0e42cdea659e43a2e7ed6/apps/desktop/src/main/hubCall.ts#L305): other callees return `unknown-callee` before forwarding.
- [`apps/desktop/src/main/hub.ts:64`](https://github.com/passioncode-ai/fabric/blob/a7fa444cace6be4a38f0e42cdea659e43a2e7ed6/apps/desktop/src/main/hub.ts#L64): running app publishes hub.json and a separate door token. Local read on 2026-10-10 found no hub.json in the registry root. No credential was sent to a guessed port.

A service descriptor makes Prowl visible in Fabric Dashboards. It does not extend CONNECTABLE_PRODUCTS, authorize a new callee or install a trusted binding. Calling the service through the local agentgateway is demonstrated separately; do not label that call `Fabric agent.call`.

## Bounded host change

1. In an isolated Fabric checkout, define a generic registered-MCP service product adapter or an explicit Prowl adapter. Do not merely append a string to the allowlist: current resource/grant/forwarding semantics are Inbox-specific.
2. Specify the credential exchange: Prowl's descriptor token belongs only to the dashboard host. Agents use a separate token; supplying the host token to agent.call must still fail. Store the callee credential in the host's authorized vault/consumer mechanism, never a capability argument.
3. Bind the admitted manifest revision/hash and exact capability set. Preserve read vs charge effects, permitted runbooks/tools, caller identity, expiry and revocation. Decide which scopes allow unattended requests; current service intentionally requires operator session decisions before every job.
4. Carry authoritative caller/project/node/binding provenance and trace through submission, polling, cancellation and result collection. Keep untrusted caller labels separate.
5. Define delegated `inputResponses` authorization before enabling form approval from MCP. A model assertion that its operator said yes is not an approval receipt. UI decisions already work against an expiring proposal digest.
6. Enroll a disposable synthetic-only caller and execute: caller → research.tutorial → human decision → job result → next no-effect fixture step. Verify denied capability, expired/revoked binding, changed idempotency input, lost reply, cancellation and no automatic duplicate dispatch.
7. Only after that gate, request a concrete budgeted provider run. The known research-core audit defects must be assessed before presenting results as verified.

## Acceptance and handoff

Record host source/build commit, provider manifest/hash, binding revision, caller identity, invocation/job/trace ids, decisions, raw effect receipts and all denial controls. No secrets in the packet. A passing SDK call, installed configuration or opened dashboard is not the chain acceptance receipt. Keep this row open in the parent Kimi remediation queue under FD-12 / KA-G03.
