# W1-T2 — documentation honesty, core scenarios, nightly CI (B-013, B-015, B-016, B-030, B-031)

Wave 1 of [`../2026-10-11-waves-canvas.md`](../2026-10-11-waves-canvas.md). Read the canvas in full:
the core scenarios you write describe its **target** behaviour, marked `UNVERIFIED` until the wave
that ships each one flips it.

Repository: this checkout of PROWL-AI/research-agent. **Do not commit or push. Edit only the files
in the ownership list** — another agent is changing code, README.md and tests in parallel. No
paid calls, do not read `.env`, do not restart services.

## Tasks

1. **B-013 — `docs/FABRIC.md:81`** says new MCP registration belongs in
   `~/.config/agentgateway/servers.yaml`. That route is retired on this machine: new MCP servers go
   into each agent client's own config; a scoped gateway profile `dev.agentgateway.prowl` exists
   for this service (launchd label, running). Rewrite the paragraph to say what is true: where the
   `prowl-research` MCP entry lives (Claude/Cursor/OpenCode/Codex configs per
   `docs/evidence/fabric-dashboard/HANDOFF.md` and VERIFICATION), that the scoped gateway profile
   `prowl` fronts it, and that sessions started before the change need a restart. Do not include
   tokens, home paths beyond `~`, or machine secrets — **this repository is public**.
2. **B-016 — `docs/evidence/fabric-dashboard/BRIEF.md:37-47`** stops at FD-11. Add a status
   column (or a status table right after) for FD-01…FD-11 = `delivered locally; gates in
   VERIFICATION.md`, and rows FD-12 (callee side of DEC-0039 delegation tokens; host issuer not
   built — canvas §2 N-FAB, wave 5), FD-13 (provider wiring through an Observatory consumer;
   needs operator keys — wave 6), FD-14 (native panel rendering NOT_VERIFIED; host 0.6.7 vs 0.7.1
   — wave 6). Note that ADR-0144 (passioncode-ai/fabric, accepted 2026-10-11) retired the
   hub-forwarding route the original FD-12 assumed; HUB-PACKET is rewritten in wave 5 (B-014).
3. **B-030 — namespace note** in `docs/FABRIC.md` (short section "Names"): this provider's tools
   are `research.run`, `research.tools.call`, `research.list_runbooks`, `research.artifact.get`,
   `research.tutorial`, `fabric.job.get`, `fabric.job.cancel`; a different, unrelated agent on the
   estate also uses `research.*` names; always address this
   one as service `prowl-research.default` / repository `PROWL-AI/research-agent`. Names are not
   renamed because the provider's contentHash binds them. Do not name private agents' internals
   beyond what is needed to disambiguate (public repo).
4. **B-015 — core scenarios** in `docs/ux/scenarios.md`. Read the file's existing format
   (SCN-001…008, statuses, coverage lines) and `docs/ux/foundation.md`/`flows.md` for conventions,
   and keep them. Add a section of core-agent scenarios `CORE-01…` covering, against the canvas
   target: start a run (CLI / stdio MCP / Fabric `research.run`) → terminal state with
   `terminal_code`; a second process cannot change a live run (lock refusal, nothing written);
   orphan reconciliation → `interrupted` → resume; resume after a crash never pays twice for a
   step whose raw is saved; budget stops (tools, USD, minutes, LLM) with disclosure; billed
   failure counts toward the budget across resume; `verified` only with a quote found in the
   stored raw or two independent sources; a conflict stays a conflict; evidence loss → `partial`
   not `complete`; report rewrite refused while active; judge rejects a planted-bad report.
   Each scenario: id, actor (human operator / calling agent), trigger, steps, expected outcome,
   failure outcome, the wave that ships it (canvas §7), status `UNVERIFIED`, coverage `—`.
   Update `docs/ux/flows.md` only if a core flow is needed to make the scenarios readable.
5. **B-031 — nightly CI**: create `.github/workflows/nightly.yml` — schedule only
   (`cron: "0 21 * * *"` = 23:00 Europe/Warsaw in CEST; add a comment that it is 22:00 in winter
   — estate policy is nightly 23:00 Europe/Warsaw, GitHub cron is UTC) plus `workflow_dispatch`;
   **no push or pull_request triggers** (estate CI policy 2026-09-25). Job: ubuntu-latest,
   Python 3.11, `pip install -e '.[dev]'`, `python -m pytest tests/ -q`, `python -m research_agent
   validate`, `python scripts/plan/assign_waves.py --check`. Validate the YAML locally
   (`python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/nightly.yml'))"`).
   Then update `docs/evidence/fabric-dashboard/VERIFICATION.md:20` (Hosted CI row): the workflow
   now exists, first scheduled run pending — still NOT_RUN until a run is read green.

## Ownership (files you may change)

`docs/FABRIC.md`, `docs/evidence/fabric-dashboard/BRIEF.md`,
`docs/evidence/fabric-dashboard/VERIFICATION.md` (row 20 only), `docs/ux/scenarios.md`,
`docs/ux/flows.md`, new `.github/workflows/nightly.yml`.

## Done when

Report: each file changed with what was false before and what is true now (cite the evidence:
file:line or command output); the list of CORE scenario ids with their wave; the YAML validation
output; anything you found stale but outside your ownership (file:line), unfixed.
