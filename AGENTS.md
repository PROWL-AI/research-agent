# Agent instructions: PROWL-AI/research-agent

Start at [`docs/HANDOFF.md`](docs/HANDOFF.md): its first entry names the exact next task. The board is
[`docs/evidence/backlog.md`](docs/evidence/backlog.md).

## Add, never replace: rule R28 (operator, 2026-11-11)

Operator, 2026-11-11, verbatim (agents database rule R28, board request aed4e06a): «чтобы мы не испортили, типа, уже
существующие генерации, мы всегда только добавили, чтобы всегда можно было посмотреть, если мы какие-то стили меняем,
то это, типа, возможно, стоит клонировать и добавить, как новый стиль, чем меняет старый. только улучшали и все
изменения были логированы, основывались, и был типа бэклог, изменения велся. Это жесткое правило для агентов для работы
в этих репозиториях ... чтобы при, когда люди разные меняют агентов, они не ухудшали их.» It binds every agent and every
person of an organization working in this repository and in every copy of it (the team copy is built from this tree).

Never:

- change or delete what shipped: runbooks (at their `version`), report templates, recipes, formats, styles, prompts and
  the reports made with them stay readable and repeatable. A changed runbook bumps `version` and keeps the shipped
  text beside it, byte for byte, as `research_agent/runbooks/<name>/versions/<old version>.md`; a changed template is
  a new file. An entry leaves only by a mark in `catalog/retired.json` with its date and reason, and the file stays.
- accept a change without proof: a test, an acceptance or a before/after measurement shows it is no worse. A
  regression is rolled back first and fixed second.
- make a change, as an agent or as a person, without a row in [`docs/evidence/backlog.md`](docs/evidence/backlog.md)
  and a line in [`CHANGELOG.md`](CHANGELOG.md) that say why and on what basis.

The gate: `python scripts/check_add_only.py` (in the suite as `tests/test_add_only.py`, in the nightly with
`--base HEAD^1`) refuses an edited or deleted shipped entry and a lock that lost a name. After adding an entry, run
`python scripts/check_add_only.py --write`: it adds new names to `catalog/shipped.lock.json` and never rewrites one.

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
