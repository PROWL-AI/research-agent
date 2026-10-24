# Agent instructions: PROWL-AI/research-agent

Start at [`docs/HANDOFF.md`](docs/HANDOFF.md): its first entry names the exact next task. The board is
[`docs/evidence/backlog.md`](docs/evidence/backlog.md).

## Opening the dashboard (operator rule, 2026-10-24)

The service's pages open **only in Fabric Dashboards**, never in a browser (Safari, Dia or Chrome), in links you
give a person, in completion messages and in pages you open yourself.

1. The registered service key is `prowl-research.default`. Do not derive it from the project name or the port.
2. Get the link from the Fabric Dashboards MCP `link` (service + path) and hand over its `open_link`, for example
   `fabric-dashboards://service/prowl-research.default?path=%2Fdashboard%23%2Frequests%2F<job id>`. In code use
   `research_agent.service.protocol.dashboard_open_link(page)`; the approval link a job returns is built with it.
   To open a page yourself, use the MCP `open` with `fallback=never`.
3. A browser is allowed only when `host_status` confirms Fabric Dashboards is `not_installed`. An installed host
   that failed to open is an error to report, not a reason to open HTTP in a browser.
4. Links carry no token and no login code: the host authenticates.

The Playwright WebKit run in `scripts/test-dashboard.mjs` is a test harness against a throwaway server, not a page
opened for a person.

## Releasing and installing

- One version: `research_agent.__version__` (`tests/test_version.py`); record the release in `CHANGELOG.md`, tag
  `vX.Y.Z` on the merge commit, publish the GitHub release.
- Install with `python3 scripts/install-fabric-service.py --vault-project prowl-research-agent`, then
  `.venv/bin/python scripts/smoke-installed-service.py`. Never start, stop or kill the service by hand.
- Stage files by name. A local `pip wheel .` leaves `build/`; 0.3.0 committed it and installed stale code (B-094).
