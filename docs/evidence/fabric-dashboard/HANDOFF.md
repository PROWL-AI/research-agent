<sub>ssheleg skills — task-pipeline · super-ux · sheleg-design · copywriting · brand-voice · adapting-projects-to-fabric · building-fabric-services · agent-interop · agent-evals · agent-sync</sub>

# Prowl Research × Fabric — implementation handoff

Status: installed local service + dashboard + gateway verified; Fabric hub admission remains open. Objective, authority and requirement IDs: [BRIEF](BRIEF.md). Design entry: [dashboard specification](../../design/fabric-dashboard.md). User explicitly chose a working interface in Fabric, without a separate Figma mockup.

Implemented modules and operating guide: [FABRIC](../../FABRIC.md). Existing research core is reused; separate direct-tool jobs accept tool parameters. SQLite stores jobs, config snapshots, exact-proposal decisions, call receipts and host events. The operator dashboard provides overview, searchable jobs, readable result tables/report/source ledger/raw output, chain attribution, costs, model/worker/timeout settings and a safe tutorial.

## Delivery and evidence

Installed runtime **891fbc995cb382ec6ccaed5f1b91611918b931c7**. Full local suite: 328 passed. WebKit desktop/mobile, exact pinned schemas and installed service checks pass. Gateway discovery/read and an installed synthetic job through operator approval also pass. [Verification ledger](VERIFICATION.md) distinguishes each gate and retains limitations.

Operator entry: `fabric-dashboards://service/prowl-research.default` (resolved by installed host MCP; OS accepted dispatch). Native page rendering remains unverified because UI automation timed out. The service is intentionally degraded until provider credentials are connected through an authorized secret consumer. A completed tutorial remains available in its request journal.

Agent configurations now have the named MCP server through a scoped gateway profile. New agent sessions can discover 7 tools; the existing running sessions were not restarted. No provider traffic, emails, posts or agent-to-agent messages were sent by acceptance probes.

## Open work and exact next task

**FD-12 / KA-G03: Fabric hub support and admission.** Start with [HUB-PACKET](HUB-PACKET.md), which names the exact host allowlist and forwarding code. The current host supports only fabric-inbox as a connected callee and no hub.json was active. Do not relabel a gateway call as a Fabric hub chain. A descriptor, manifest and successful discovery are insufficient.

Next gates: delegated human approval with authoritative bindings; scoped unattended grants if requested; Observatory provider wiring and a concrete budgeted live run; native host page acceptance. Existing KA-01…KA-12 remediation remains prioritized in the parent repository, and these local adapter controls do not close the original core defects globally. No merge or deployment of the parent Prowl product occurred.

## Repositories and resume

- Child owner: `https://github.com/PROWL-AI/research-agent`, branch `feat/fabric-dashboard-20261010`, entry this file. Runtime source above; final delivery commit is the branch tip containing this handoff.
- Parent owner: `https://github.com/PROWL-AI/prowl-app`, branch `audit/kimi-20261010`, central queue `docs/superpowers/plans/2026-10-10-kimi-remediation.md`. The child is a separate checkout, not a submodule; no production pin is changed.
- Host owner: `https://github.com/passioncode-ai/fabric` at inspected `a7fa444cace6be4a38f0e42cdea659e43a2e7ed6`, read-only. Preserve its existing workspace submodule modifications.

Checks to reproduce are in ../../FABRIC.md and VERIFICATION.md. Do not copy credentials or machine configurations into Git. Raw outputs normalize home paths; synthetic screenshots are not production data.

---

**Made with [ssheleg skills](https://github.com/ssheleg/sshlg-skills)**

- [`task-pipeline`](https://github.com/ssheleg/task-pipeline) — implementation and delivery
- [`super-ux`](https://github.com/ssheleg/super-ux) — scenarios and flows
- [`sheleg-design`](https://github.com/ssheleg/sheleg-design-skill) — operator dashboard
- [`copywriting`](https://github.com/ssheleg/super-ux) — interface wording
- [`brand-voice`](https://github.com/ssheleg/super-ux) — inherited brand pack
- `adapting-projects-to-fabric` — capability bundle — not a skill this family ships
- `building-fabric-services` — lifecycle and service contract — not a skill this family ships
- [`agent-interop`](https://github.com/ssheleg/agent-stack) — MCP jobs and traces
- [`agent-evals`](https://github.com/ssheleg/agent-stack) — failure controls
- [`agent-sync`](https://github.com/ssheleg/agent-sync) — parent handoff ownership

<sub>A star on [the bundle](https://github.com/ssheleg/sshlg-skills) helps.</sub>
