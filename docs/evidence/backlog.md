# Backlog — PROWL-AI/research-agent (prowl-research.default)

> **The board.** Mutable: priority is re-derived, state changes, rows close. A row never
> disappears silently — a closed row moves to *Closed* with the commit that closed it.
> Defects KA-01…KA-12 and gates KA-G01…KA-G04 keep their ids in the canonical plan
> (`PROWL-AI/prowl-app` `docs/superpowers/plans/2026-10-10-kimi-remediation.md`);
> FD-01…FD-14 keep theirs in [`fabric-dashboard/BRIEF.md`](fabric-dashboard/BRIEF.md).
> This board issues `B-NNN` for work no other register owns. The wave inventory
> (`docs/specs/*-inventory.json`) lists every open item from every register.

| id | What | Source | Size | Sev | Blast | Age | Prio | State | Home |
|---|---|---|---|---|---|---|---|---|---|
| B-001 | LLM model slots move from env-configured role models to named estate model profiles resolved by the fabric kit; the LLM limit (KA-G01) becomes the profile's key route with an Observatory key and its model allow-list | cross-session request from an estate agent, 2026-10-11 (operator's request); runner and model-profile proposal (private estate document) | M | 2 | 3 | 0 | 6 | waived — revisit: Fabric's ADR, contract DEC CT-05 and the kit resolver (T1–T3) land | — |
| B-024 | Contract probes live outside tests/ (deep probes in docs/reports, resume probes only in prowl-app); move each into tests/ as its fix lands, keep the diagnostic cut | wave-0 survey 2026-10-11 · `docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py; prowl-app probe_research_resume.py` | S | 1 | 2 | 0 | 2 | in-flight — KA-06 contracts in tests/ (675e769); remaining probes move with waves 2–3 | wave 1 |
| B-007 | Transform claims (an LLM summary of tool X) corroborate X itself | wave-0 survey 2026-10-11 · `research_agent/evidence/ledger.py:201-203; orchestrator.py:586-589` | S | 3 | 2 | 0 | 6 | open | wave 3 |
| B-003 | ObservedLLM duplicates LLMClient without retries, max_tokens-scaled timeout or LLMError mapping; one 429 fails a paid service run | wave-0 survey 2026-10-11 · `research_agent/service/runtime.py:91-122; llm.py:144-149` | S | 3 | 2 | 0 | 6 | open | wave 4 |
| B-004 | ObservedProwl._rpc never reconnects; meta calls lose the client's retry under the service | wave-0 survey 2026-10-11 · `research_agent/service/runtime.py:51-58` | S | 2 | 2 | 0 | 4 | open | wave 4 |
| B-005 | Runtime.envelope hard-codes outcome partial; research status is buried in output.research.status | wave-0 survey 2026-10-11 · `research_agent/service/runtime.py:278` | S | 2 | 3 | 0 | 6 | open | wave 4 |
| B-029 | validate_runbooks does not warn when a runbook's allowlist misses its declared failover alternatives | wave-0 survey 2026-10-11 · `scripts/validate_runbooks.py:14` | S | 1 | 1 | 0 | 1 | open | wave 4 |
| B-014 | HUB-PACKET and HANDOFF describe a hub-forwarding route ADR-0144 retired; hub.json now exists (Fabric 0.3.4). Rewrite around DEC-0039 direct calls with delegation tokens | wave-0 survey 2026-10-11 · `docs/evidence/fabric-dashboard/HUB-PACKET.md; passioncode-ai/fabric docs/adr/0144; fabric-agent-contract DECISIONS.md:1364` | S | 2 | 3 | 0 | 6 | open | wave 5 |
| B-021 | Contract pin 623bf613 → fabric-agent-contract 8e49fbd (DEC-0036…0040 additive, contractVersion stays 0.1.0) | wave-0 survey 2026-10-11 · `fabric-contract.lock.json` | S | 2 | 3 | 0 | 6 | open | wave 5 |
| B-019 | Installer launches the service without an Observatory consumer (vault-only serve) | wave-0 survey 2026-10-11 · `scripts/install-fabric-service.py:71; ~/Library/LaunchAgents/chat.prowl.research.plist` | S | 3 | 3 | 0 | 9 | open | wave 5 |
| B-002 | Dashboard has no fabric-dashboard-kit (1.0.0, DEC-0036): legacy 480px; nav 208/160px and horizontal mobile nav break ED-3 | wave-0 survey 2026-10-11 · `SessionStart notice; dashboard_kit.py status → no kit copy; docs/design/fabric-dashboard.md:19` | M | 1 | 2 | 0 | 2 | open — operator go given 2026-10-12 (wave 5) | wave 5 |
| B-017 | Judge uncalibrated: FakeLLM fixed scores, no planted-bad control, no labelled agreement; KA-G02 requires the judge to reject planted bad output first | wave-0 survey 2026-10-11 · `evals/judge.py:35-49,206; tests/test_judge.py:72-94` | M | 3 | 2 | 0 | 6 | open | wave 6 |
| B-027 | No spend policy for prowl-research; one durable budget request with a concrete amount for wave 6 live acceptance | wave-0 survey 2026-10-11 · `estate authority record (L1 asked once at first paid run)` | S | 3 | 3 | 0 | 9 | decided — USD 15 for wave-6 live acceptance (operator, 2026-10-12) | wave 6 |
| B-020 | prowl-research has no row in the Fabric delegation-model adoption plan (step 4: callee adopts) | wave-0 survey 2026-10-11 · `Fabric delegation-model adoption plan (estate document)` | S | 2 | 3 | 0 | 6 | in-flight — contract owner (fabric-agent-contract) accepted 2026-10-16: a 2026-10-16 cut of `docs/evidence/adoption.md` adds PROWL-AI/research-agent (pin `623bf61`, DEC-0001…0031; DEC-0039 not in pin → B-021); lands with its PR #113, commit to follow | Fabric delegation plan row (pending) |
| B-032 | Server-side dedupe of a same-key resend is unverified offline (Prowl retry window, 15 min default); CORE-14 | wave-2 product certification 2026-10-12 | S | 3 | 3 | 0 | 9 | open | wave 6 |
| B-033 | This checkout is not a Fabric project: `fabric_whoami` refuses, so the project board (`com.*`) and work claims are unreachable; this file stays the board | `fabric_whoami` 2026-10-16 | S | 2 | 2 | 0 | 4 | open — operator step in Fabric: + Project → Open a project | external |
| B-034 | Observatory attributes 3 critical leaked-unrotated keys (`CIVITAI_API_TOKEN`, `HF_TOKEN`, `REPLICATE_API_TOKEN`, slot `0xDEV/local`, seen 2026-09-14) to this project; research-agent uses none of them | `observatory_findings` project:prowl-research 2026-10-16 | S | 3 | 1 | 1 | 4 | open — owner is the `0xDEV/local` slot: rotate via Observatory doors + `vault.py settle`, or re-scope the finding | external |
| B-035 | Service configures no logging: INFO events (`claim.*`, `budget.stop`, `evidence.incomplete` below WARNING) never reach `service.log`, and the launchd stdout/stderr file has no size cap or rotation | infra check 2026-10-17 · `research_agent/service/cli.py` (no logging setup); launchd plist StandardOutPath; `service.log` 0 B after 6 days | S | 2 | 2 | 0 | 4 | open | wave 4 |

Prio = `Sev × Blast + age_bonus` (`age_bonus` 1 past 14 days, 2 past 30).

## Closed

- **B-009 · Orphans: a crashed CLI run stays running until a stdio server starts; service run dirs are never reconciled; service cancel/timeout leaves runs/<job>/checkpoint.json at running** — closed — 675e769 + 583f1d1, 2026-10-11
- **B-010 · rewrite_report writes report.md and the checkpoint without the run lock** — closed — 675e769, 2026-10-11
- **B-011 · README stale: 304 tests at 1dced8e, stdio tool count only (service has 7), Fabric section after License** — closed — 675e769 + 583f1d1, 2026-10-11
- **B-012 · mcp_server.py module docstring says the Fabric bundle declares stdio; the manifest points at the HTTP service** — closed — 675e769, 2026-10-11
- **B-013 · FABRIC.md says register MCP in ~/.config/agentgateway/servers.yaml — retired route (machine-03: new servers go in each agent's own config; scoped dev.agentgateway.prowl runs)** — closed — 675e769, 2026-10-11
- **B-015 · UX scenarios cover only the dashboard; core journeys (CLI/MCP run, resume, terminal states, verified semantics, budget stop, judge) have none** — closed — 675e769 (CORE-01..13); CORE-01/03/12 PASS@583f1d1, 2026-10-11
- **B-016 · BRIEF stops at FD-11; FD-12…FD-14 and every FD status live only in the parent plan and HANDOFF** — closed — 675e769, 2026-10-11
- **B-030 · Bare research.* tool names are ambiguous across the estate; document addressing by service id prowl-research.default / PROWL-AI/research-agent; no rename (provider contentHash binds names)** — closed — 675e769 + 12df501 (no private names), 2026-10-11
- **B-031 · No hosted CI workflow in this repository; VERIFICATION 'Hosted CI NOT_RUN' has no workflow behind it. Add a nightly-only workflow (estate policy 23:00 Europe/Warsaw, no push/PR triggers)** — closed — 675e769 (workflow file); hosted run NOT_RUN until it reaches main, 2026-10-11
- **B-006 · save_markdown is non-atomic and an OSError escapes _execute_transform, failing the whole run** — closed — wave 2; atomic save_markdown, raw-write failure typed, 2026-10-12
- **B-008 · A failed transform is not persisted until the next segment saves** — closed — wave 2; failed transform saved immediately, 2026-10-12
- **B-025 · raw_ref is absolute under the service and CWD-relative under CLI/MCP — not portable, blocks quote-to-raw checks** — closed — wave 2; run-dir-relative raw_ref, 2026-10-12
- **B-023 · audit/kimi-20261010 and feat/fabric-dashboard-20261010 are unmerged; origin/main is still 1dced8e** — closed — all three branches are ancestors of `origin/main` `985db4f` (PR #1, PR #2), measured 2026-10-16
- **B-026 · Observatory use_secret.py names prints its ambiguity message one character per line** — closed — installed engine `project-observatory 0.24.5` prints the ambiguity message on one line (`use_secret.py names prowl-research | wc -l` → 1), measured 2026-10-16
- **B-018 · No wiki project card and no agent-estate entry for prowl-research (global rule: read/update before agent planning)** — closed — vault commit `870ff961` is an ancestor of obsidian-memory-vault `origin/master` `bf2fd5cd`; card `projects/prowl-research/prowl-research.md` and one `prowl-research.default` row in `synthesis/agent-estate.md` present there, measured 2026-10-16

KA-06 closes in the canonical KA plan (prowl-app) with the same commits.
