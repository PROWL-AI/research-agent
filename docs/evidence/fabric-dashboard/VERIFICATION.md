# Prowl Research × Fabric — verification, 2026-10-10

Runtime source and installed build: **891fbc995cb382ec6ccaed5f1b91611918b931c7**. Later handoff commits contain documentation, probes and screenshots only. No hosted CI suite was dispatched; no merge or public release was performed. Receipts below normalize the local home directory to `~`; they contain no tokens. Screenshot databases are synthetic and disposable.

| Gate | Result | Evidence |
|---|---|---|
| Whole Python suite | PASS — 328 tests, exit 0 | [pytest](raw/pytest-891fbc9.log); `.venv/bin/python -m pytest -q --tb=short` |
| Adapter negative controls | Included in that suite — 24 tests | `tests/test_service.py`: token roles, CSRF/origin, duplicate/stale/expired requests, terminal cancel, restart, price unknown, billed failures, artifact path, exclusive lock, queue overbooking |
| Browser behavior | PASS — WebKit, 1440×1000 and 390×844; zero page errors | [browser receipt](raw/webkit-891fbc9.log); `npm run test:dashboard` |
| External contract schemas | PASS, exit 0, exact clean 623bf61358c339cb10297807b3f024b5d9f1f327 | [contract](raw/contract-891fbc9.json); `scripts/verify-fabric-contract.py` |
| Adapter declaration | Local structure and declaration PASS | [bundle checker](raw/bundle-adaptation.json); readiness-for-admission is not admission |
| Installed service | 27 PASS, 5 NOT_RUN, 0 FAIL | [service probe](raw/service-probe-891fbc9.json); own MCP credential deliberately unavailable to descriptor-token probe |
| Own MCP / gateway transport | PASS for initialize/list/read; anonymous and wrong-role both 401 | [gateway SDK](raw/gateway-sdk.log); 7 tools, 14 runbooks |
| Installed end-to-end tutorial | PASS — gateway → service job → operator session decision → 3 rows, stable trace; 0 provider calls | [installed tutorial](raw/installed-tutorial.log); synthetic receipts excluded from real usage |
| Fabric Dashboards host | available 0.6.7; resolver and OS dispatch accepted | [host receipt](raw/fabric-host.log) |
| Native page rendering | NOT_VERIFIED | `cua.getApp("Fabric Dashboards")` twice timed out at 30 seconds. No browser fallback was used as a replacement host acceptance |
| Fabric delegation, callee side | PASS (offline, test key) | `tests/test_delegation.py`; [FD-12 packet](HUB-PACKET.md) |
| Fabric host chain (issuer → caller → service) | NOT_RUN — host issuer absent | hub `fabric-hub/0.1` publishes no JWKS (404, 2026-10-17); KA-G03, wave 6 |
| Paid provider acceptance | NOT_RUN | New supervised service has no provider credentials; no funds spent by these probes |
| UX docs | PASS, exit 0 | `python3 <super-ux-0.59.1>/scripts/ux_lint.py` returned `OK — docs/ux is consistent` |
| Hosted CI | NOT_RUN | `.github/workflows/nightly.yml` now exists (added 2026-10-11, B-031): nightly schedule plus manual dispatch, no push/PR triggers, per the estate nightly CI policy. First scheduled run pending; stays NOT_RUN until a run is read green. GitHub runs a schedule from the default branch only, so the file on this unmerged branch does not run until it reaches the default branch |

## Wave 5 — Fabric contract revision 6, 2026-10-17

Code commit **198a227** (fix round after the three blind certifications of `77a0621`). Receipts are from that commit; home and temporary paths normalized to `~` / `<tmp>`; no tokens.

| Gate | Result | Evidence |
|---|---|---|
| Whole Python suite | PASS — 515 tests | [pytest](raw/pytest-198a227.log); `.venv/bin/python -m pytest tests/ -q` |
| Planted mutations of the fix-round defenses | 12 / 12 killed | [mutations](raw/mutations-198a227.log): metadata authentication, artifact ownership, resume inputs / rejected / concurrent / chain root / owner, idempotency namespace, JWKS URI, envelope attribution, installer `serve` consumer, exact slot match |
| Browser behavior | PASS — WebKit, 1440×1000, 390×844, 360×740; zero page errors | [browser receipt](raw/webkit-198a227.log); `node scripts/test-dashboard.mjs` (screenshots to a temporary folder; this receipt's PNGs were not committed) |
| External contract schemas at the pin | PASS, clean `7a14a48` | [contract](raw/contract-198a227.json); `scripts/verify-fabric-contract.py <clean clone>` |
| Installer launch argv | dry run, no vault (degraded start) | [dry run](raw/installer-dry-run-198a227.json). With `--vault-project` the argv is `use_secret.py serve --env prod --consumer chat.prowl.research <folder> PROWL_API_KEY,RESEARCH_LLM_API_KEY -- …` under Observatory's interpreter (since the wave-6 fix round: with the slots the folder holds; `tests/test_installer.py`); no folder of this service holds both slots yet (B-042) |
| UX docs | PASS | super-ux 0.60.0 `ux_lint.py`: `OK — docs/ux is consistent` |
| Delegation, callee side | PASS (offline, test Ed25519 key) | `tests/test_delegation.py` |
| Host chain (issuer → caller → service) | NOT_RUN — host issuer publishes no JWKS | KA-G03, wave 6 |
| Installed service on revision 6 | 29 PASS, 8 NOT_RUN, 1 FAIL — installed from the merge `12ad137` | [service probe](raw/service-probe-12ad137.json), adapter 0.35.0 `check_service.py`, three runs. FAIL `well-known.fast`: median 112–217 ms against 100 ms while the machine's load average was 175–250 (other sessions' processes; in-process the handler answers in 4.4 ms when it gets the CPU) — B-044, re-probe under normal load. NOT_RUN, each with its reason: `configuration.declared` (the service declares no runner/model configuration to the host; its own settings are revisioned in the dashboard); `auth.delegation-declared` (no trusted issuer configured: the hub publishes no JWKS — KA-G03); `interop.output-schema-object`, `interop.tools-match`, `interop.job-tools`, `interop.unknown-job`, `interop.trace-propagation` (MCP `auth: own` refuses the host's token by design, DEC-0024; covered locally by the suite and the contract check above); `board.responder` (no board participation — B-033) |

### Installed from the wave-6 merge `d868706` (2026-10-18)

| Gate | Result | Evidence |
|---|---|---|
| Installed service | 30 PASS, 8 NOT_RUN, 0 FAIL (load average 36) | [service probe](raw/service-probe-d868706.json); same NOT_RUN reasons as wave 5 |
| LLM key reaches the service through the vault consumer | PASS — health `degraded` names only `prowl` | launched as `use_secret.py serve --consumer chat.prowl.research prowl-research-agent RESEARCH_LLM_API_KEY`; the plist holds slot names only (no key value: `grep -c sk-or` → 0) |

### M1 wave B: readability (2026-10-23, `5023b06`)

| Gate | Result | Evidence |
|---|---|---|
| WebKit, 1440/390/360, empty-state walk plus a seeded second service (`scripts/dashboard-fixtures.py`) | PASS, 25 checks, no page errors | [receipt](raw/webkit-m1-wave-b.json): spend today/7/30 days (UTC) and per report with the `≥` lower bound, attention holds only current items, three older failures folded into one counted line that opens the filtered list, a failure reads class and next step before «Подробности», «Охват источника» in Russian on a research job and on a tool job |
| Product reading | fail (5 blocking: copy claiming an internal cause, SCN-006, CORE-19, this receipt, the open rows), fixed in `af1ba38` | `docs/specs/waves/M1-B-dashboard-readability.md` |
| Visual reading | fail on evidence only (no surface class, no frames of the failure and research-coverage states), fixed in `5023b06`; frames in [m1-wave-b/](raw/m1-wave-b/) | `docs/specs/waves/M1-B-dashboard-readability.md` D9 |

## Corrections discovered during verification

- Browser navigation initially rendered a form before its pending refresh completed, which erased a typed model. Navigation now presents a loading state until that refresh finishes; the WebKit dirty-settings regression passes.
- The old stdio duplicate-run check followed awaited checkpoint I/O; a live task could finish during that await and admit another submission from stale checkpoint state. It now also rejects live duplicates before yielding. KA-06 (run-lock ownership) is addressed in wave 1; certification pending.
- Queue rank alone could overbook a slot when an older request was approved after a newer one started. Admission now counts executing jobs and admits only the next queued job into an available slot; regression passes.
- Cold install on this busy machine exceeded the original 20-second readiness poll. The installer now allows a bounded 120-second warm-up. Duplicate process locking happens before heavy imports.
- Initial service probe had a 150.1ms health median and a case-sensitive cookie spelling failure; final installed probe has no failures. The cookie is HttpOnly; SameSite=Strict, and a reused code is refused.
- Gateway SDK teardown logs `Session termination failed: 202`; operations and role-denial checks pass. This is retained as a transport teardown compatibility limitation, not hidden as a clean-session claim.

## Visual receipt scope

[Desktop overview](raw/overview-desktop.png), [decision](raw/approval-desktop.png), [readable data](raw/data-desktop.png), [mobile overview](raw/overview-mobile.png), [mobile learning](raw/learn-mobile.png). Reviewed for hierarchy, legibility, responsive overflow and explicit tutorial/unknown-cost labels. This is not an assistive-technology audit or live-provider result-quality acceptance. Daily spend chart has backend accounting controls; a populated live billing chart was not exercised with paid traffic.

## Machine integration footprint

- Service descriptor `prowl-research.default`, loopback 18764, launchd `chat.prowl.research`, immutable installed release under `~/.local/share/prowl-research/releases/891fbc995cb3/`.
- Data/credentials in `~/Library/Application Support/prowl-research/`; host and agent tokens separate. Provider keys absent.
- Gateway source adds only named server `prowl-research`, role/profile `prowl`; scoped process `dev.agentgateway.prowl`, data-plane 47845 and auxiliary ports 47846–47848. Dedicated profile sets upstream Host correctly without changing existing gateway instances.
- Targeted migration added only `prowl-research` entries in Claude, Cursor, OpenCode and Codex configs, with local 0600 backups. Running client sessions are not claimed to have reloaded.
- Source YAML, generated gateway config, tokens, client configs and launchd files are local machine configuration and intentionally excluded from Git.
