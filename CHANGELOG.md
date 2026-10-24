# Changelog

One version for the package, the service's well-known document and MCP `initialize`:
`research_agent.__version__` (`tests/test_version.py`). Row ids (B-NNN, KA-NN, FD-NN) are in
[`docs/evidence/backlog.md`](docs/evidence/backlog.md).

## 0.3.3 (2026-10-24)

- A job waiting for approval links the operator to the request in Fabric Dashboards
  (`fabric-dashboards://service/prowl-research.default?path=...`), not to an HTTP page; `AGENTS.md` pins the rule
  that the service's pages open only in Fabric Dashboards (operator rule 2026-10-24).

## 0.3.2 (2026-10-24)

- 0.3.0 and 0.3.1 committed a `build/` directory by mistake, and setuptools installed that `build/lib` in place of
  the sources (it held the 0.3.0 code, so both installs ran 0.3.0 code and 0.3.1 reported version 0.3.0). The
  directory is removed and ignored, the installer drops build output from the archive before installing, and a test
  fails if one is tracked again.

## 0.3.1 (2026-10-24)

- The installer waits for the service on a 600 s wall-clock deadline (`--ready-timeout`) instead of 120 s of tries, so
  a good install on a loaded machine no longer fails; a timeout names the readiness check (B-093).

## 0.3.0 (2026-10-24)

Everything merged since 0.2.0 (commit `4cb25c2`, 2026-10-10): pull requests #1 to #40.

**Runs and evidence**
- Run ownership with a lock and orphan reconciliation; checkpoint v2 with step identity, a durable attempt ledger and
  resume that re-sends an unknown outcome under its own key (#1, #2, B-082 in #36).
- Ledger v2: claims tied to their evidence, verified quotes only (KA-07, KA-08, KA-09, B-007; #3).
- LLM budget with a writer reserve, metered judge spend, and the `budget_llm` stop (KA-G01; #4, #6).
- One refused step no longer ends the run; a run stops on an empty wallet, the service's limit, an unknown outcome or
  five refusals in a row (B-049; #16).

**Planning and tools**
- `{{name}}` placeholders resolved by an earlier transform, never sent unresolved; template text and known-refused
  values are never sent (B-065, B-070, B-071; #29, #31).
- `{{output:<step>}}` hands a whole earlier result to a later step under a 16 000-character cap per step (B-074, B-085;
  #35, #36).
- Steps that read an earlier output keep their tool call under a tool budget; unrelated steps yield only while that
  still buys a forward, never after the run stopped (B-086, B-087, B-089, B-090; #36, #38, #39).
- Peers see a worker crash and a run-wide refusal before their next step (B-091, B-092; #40).
- A truncated plan is retried once at a larger limit (B-048; #13).

**Report quality**
- The judge vetoes by code (unverified tags, quote gaps, false positives fixed); the writer repairs the defects the judge
  proves, line by line, with reasoning off (B-045 to B-047, B-052 to B-064, B-068; #8, #9, #18 to #30).

**Fabric service and dashboard**
- Fabric contract revision 6: delegation callee side, service resume, job errors inside the pinned schema
  (`data.terminalCode`), lifecycle events in the file log (B-075, B-077, B-080; #5, #32, #33).
- Dashboard on `fabric-dashboard-kit@1.1.3`: Russian copy, readable failures with «Подробности», spend windows,
  source coverage on every job, no cut navigation or tabs at 360 to 390 px (B-066, B-076, B-078, B-083, B-084;
  #34, #36, #37).
- Kit 1.1.3's Fabric button is not loaded: its labels are English only (B-088, decided).

**Verification**
- Mutation check over the certified defences (85 mutants, all killed), WebKit dashboard check at 1440, 390 and 360 px,
  installed-service smoke per build.
