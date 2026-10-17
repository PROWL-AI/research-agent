# W5-T1 — Fabric contract (B-021, FD-12, B-019, FD-13, B-002, B-014, B-037, B-039)

Wave 5 of [`../2026-10-11-waves-canvas.md`](../2026-10-11-waves-canvas.md). **Read §2 N-FAB — it is the contract.**
Builds on waves 1–4 (merged at `119e2fd`). Public repository: no absolute home paths or private names.

**As built** (fix round `198a227`; canvas §9, 2026-10-17): pin `7a14a48` (item 1); the service binds
loopback only — the bind option was removed, so item 2's non-loopback clause is moot, and a loopback caller
without the own token is T2; resume (item 3) also requires the same inputs, refuses a rejected, waiting,
working or finished run and a second concurrent continuation, and every resume writes the chain's root run;
kit 1.1.0 instead of 1.0.0 (item 4); the consumer is `use_secret.py serve --consumer chat.prowl.research`,
not `run` (item 5); keys stay blocked (B-042, B-043); the reinstall (item 7) runs from the merge commit.

## Exit criteria (canvas §7, written before the wave)

Pin + contentHash re-derived and validated; delegation tests (good token, wrong audience, expired,
broken chain, own token still works); installer dry-run shows the vault-only consumer argv; service
reinstalled and `check_service.py` re-run with every NOT_RUN named.

## Items, in build order

1. **B-021 — contract pin** `623bf61` → the current `fabric-agent-contract` main (decided at build time,
   recorded in `fabric-contract.lock.json`). `scripts/verify-fabric-contract.py` runs against a separate local
   clone at the pin (never another session's working tree). The service's `research.run` input gains
   `max_llm_usd` (wave-4 deferral); the manifest is rebuilt once: provider `revision` 6, `contentHash`
   re-derived by `scripts/build-fabric-manifest.py`.
2. **FD-12 — callee side of DEC-0039 by trust tier.** Vendor the adapter kit's `fabric_delegation.py`
   (standard library Ed25519, DL-13 order, `JwksCache`) unchanged under `research_agent/service/vendor/`, with its
   source release and digest recorded. The service binds loopback → every caller is T0: a delegation token is
   optional; when present (`Fabric-Delegation`, else a delegation-JWT bearer) it is verified offline against
   `RESEARCH_DELEGATION_ISSUER` / `RESEARCH_DELEGATION_JWKS` and its principal/caller/chain are recorded on the
   job; an invalid token is refused with the contract's code (DL-19 shape); a token with no trusted issuer
   configured is refused (fail closed). Binding beyond loopback is refused at startup unless delegation is
   configured (T2 needs the whole profile). The own agent token keeps working. The well-known document declares
   `auth.delegation` when configured. Host-chain acceptance waits for the Fabric issuer (hub JWKS answers 404
   today) — KA-G03, wave 6.
3. **B-039 — service resume.** `research.run` with `resumeJobId` (an interrupted or failed research job of
   the same runbook) creates a new job that runs the orchestrator on the old run's directory: saved raw is
   extracted, `outcome_unknown` calls are re-sent with their keys, the attempt ledger continues; approval is
   still required (a resume can spend).
4. **B-002 — dashboard kit 1.0.0** (operator go 2026-10-12): `dashboard_kit.py install` into
   `research_agent/service/static/`, markup moved to `.fd-chrome/.fd-nav/.fd-page/.fd-grid/.fd-scroll`, the page's
   own CSS on the kit tokens, well-known `extensions` declared; the WebKit dashboard check and the kit's layout
   check pass at 360 / 390 / 1440 px.
5. **B-019 / FD-13 — keys through Observatory.** The installer launches `serve` through Observatory's vault-only
   consumer (`use_secret.py run --vault-only`, slots `PROWL_API_KEY`, `RESEARCH_LLM_API_KEY`); `--dry-run` prints
   the argv. The LLM key is issued through Observatory's OpenRouter door with a USD 15 limit (the wave-6 budget,
   operator Q4) into this project's vault slot; the `prowl_` key has no door — the issuing path is researched and
   the gap recorded as a board row, never filled with another agent's key.
6. **B-014** — HUB-PACKET/HANDOFF rewritten around direct calls with delegation tokens (DEC-0039).
7. **B-037** — reinstall the service from this build (the installed release predates waves 2–4), then
   `check_service.py` with every NOT_RUN named.

## Tests

Delegation: good token, wrong audience, expired, broken chain (bad signature / unknown kid), scope not granted,
no trusted issuer, own agent token still works, chain recorded on the job, non-loopback bind refused without
delegation. Resume: an interrupted job's run continues without re-dispatching a completed or raw-saved step.
Contract: verify script green at the pin; tool input schema == published schema.
