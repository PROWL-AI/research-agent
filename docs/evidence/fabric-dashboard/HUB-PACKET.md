# FD-12 — callers reach Prowl Research directly, with delegation tokens (DEC-0039)

Status (2026-10-17, wave 5): **callee side built and tested; host-chain acceptance waits for the Fabric
issuer** (KA-G03, wave 6). This packet replaces the 2026-10-10 hub-forwarding packet: Fabric ADR-0144
(accepted 2026-10-11, amendment 4 at Fabric `19ad05ca`) retired forwarding — the hub **issues** the
delegation chain, and callers call this service **directly**.

## The route

```
caller agent ──token exchange──▶ Fabric hub (issuer) ──delegation token (≤10 min)──▶ caller
caller agent ──POST /mcp, Authorization: Bearer <token> (or Fabric-Delegation)──▶ prowl-research.default
prowl-research.default ──verify offline against the estate JWKS──▶ act for `sub`, record the chain on the job
```

## What this service does (contract `fabric-agent-contract` `7a14a48`, docs/specification/delegation.md)

| Caller | Tier (DL-25) | Needs a token | Behaviour |
|---|---|---|---|
| this machine, the service's own agent token | T0 | no | a token it also sends is verified and recorded; a bad one is refused |
| delegation token only, or a caller off the machine | T2 | yes | verified in DL-13 order; refused with the contract code (DL-19 shape) |
| a token with no trusted issuer configured | any | — | refused `issuer-unavailable` / `no-trusted-issuer` (fail closed) |

- Verifier: the adapter kit's `fabric_delegation.py`, vendored unchanged (`research_agent/service/vendor/`,
  digest in `VENDORED.md`); policy in `research_agent/service/delegation.py`.
- Configuration: `RESEARCH_DELEGATION_ISSUER` (`urn:fabric:estate:<id>`), `RESEARCH_DELEGATION_JWKS` (https,
  loopback http or a file), `RESEARCH_DELEGATION_AUDIENCE` (default `prowl-research.default`). Configured, the
  well-known document declares `auth.delegation` (DL-16); `surfaces.mcp.auth` stays `own` (the own agent token
  keeps working for T0 callers).
- The service binds loopback; `serve --host` beyond loopback is refused unless delegation is configured.
- A job started under a token records `{principal, caller, chain, kid, tier}` (never the token); a delegated
  caller reads and cancels only the jobs it started (`scope-not-granted` otherwise).
- Approval stays the operator's in the dashboard for every job; `approval/1` documents are not accepted from MCP
  yet (DL-17 support is a later step, not needed while every job waits for the dashboard decision).

Tests: `tests/test_delegation.py` (good token, wrong audience, expired, broken signature, unknown key, scope and
effect ceilings, no issuer, own token on loopback, T2 off the machine, job isolation, well-known declaration,
bind guard), tokens minted with a test Ed25519 key.

## What waits (KA-G03, wave 6)

The estate hub does not publish keys yet: `http://127.0.0.1:<hub>/.well-known/jwks.json` answered 404 on
2026-10-17 (`hub.json` protocol `fabric-hub/0.1`). When it does: set the issuer and JWKS on the service, have a
synthetic caller mint a token for `research.tutorial`, call directly, and record the host build, provider
manifest hash (`fabric-agent.json`, revision 6), token `kid`, job id, trace and the recorded chain. A descriptor,
a manifest or a passing local test is not that receipt.
