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
| Fabric hub chain/admission | BLOCKED_BY_HOST_CAPABILITY | [FD-12 packet](HUB-PACKET.md): hub only connects fabric-inbox; no active hub.json observed |
| Paid provider acceptance | NOT_RUN | New supervised service has no provider credentials; no funds spent by these probes |
| UX docs | PASS, exit 0 | `python3 <super-ux-0.59.1>/scripts/ux_lint.py` returned `OK — docs/ux is consistent` |
| Hosted CI | NOT_RUN | Existing nightly policy retained; unmerged branch is outside its snapshot |

## Corrections discovered during verification

- Browser navigation initially rendered a form before its pending refresh completed, which erased a typed model. Navigation now presents a loading state until that refresh finishes; the WebKit dirty-settings regression passes.
- The old stdio duplicate-run check followed awaited checkpoint I/O; a live task could finish during that await and admit another submission from stale checkpoint state. It now also rejects live duplicates before yielding. Broader KA-06 ownership hazards remain open.
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
