# Prowl Research × Fabric — implementation handoff

Status: local implementation under verification; native installation and gateway receipts pending. Objective, authority and requirement IDs: [BRIEF](BRIEF.md). Design entry: [dashboard specification](../../design/fabric-dashboard.md). User explicitly chose a working interface in Fabric, without a separate Figma mockup.

Implemented modules and operating guide: [FABRIC](../../FABRIC.md). Existing research core is reused; separate direct-tool jobs accept tool parameters. SQLite stores jobs, config snapshots, exact-proposal decisions, call receipts and host events. The operator dashboard provides overview, searchable jobs, readable result tables/report/source ledger/raw output, chain attribution, costs, model/worker/timeout settings and a safe tutorial.

## Checks so far

- Focused adapter suite: 23 passed (pre-install source; final frozen-commit replay pending).
- Earlier whole suite: 321 passed before the last six adapter regressions and subsequent changes; not a receipt for final HEAD.
- External Fabric contract schemas at 623bf61358c339cb10297807b3f024b5d9f1f327: manifest, tool inputs/outputs, input-required/completed jobs, envelope, events, usage and well-known passed before final freeze.
- Playwright WebKit desktop 1440×1000 and mobile 390×844: tutorial/approval, step history, readable data, report, fixture exclusion from spend, chain view, dirty settings, revision save, search empty and offline snapshot passed before final freeze. Raw screenshots are synthetic examples, not production activity.
- UX linter: exit 0, no findings after adding complete scenario/index metadata.

## Explicit open gates

1. Install committed source, probe supervised lifecycle, obtain host_status/list_services/link/open receipts. A dispatched link is not native page readiness.
2. Register this MCP service through the local gateway, preserving all unrelated configuration; verify transport and role denial. No upstream/provider keys are copied from other products.
3. Fabric hub admission, authoritative caller/binding provenance and delegated form approval are not implemented by a descriptor. Current jobs require operator authentication in this dashboard; an MCP caller cannot approve itself.
4. Live providers and paid research are NOT_RUN. Known KA-03…KA-12 research-core defects remain on the prior audit queue. Cost receipts in this adapter do not close legacy checkpoint defects globally.
5. Cross-agent chain acceptance must use a real admitted caller and exact binding; no such proof is inferred from synthetic context.

## Next task

Finish local contract/browser/lifecycle verification on one frozen code commit, install it, record exact host and gateway receipts in VERIFICATION.md, push this branch and update the parent audit handoff index. Then resolve scoped hub admission/provider wiring as the next independently verifiable gate; do not make paid test calls without a concrete spending instruction.
