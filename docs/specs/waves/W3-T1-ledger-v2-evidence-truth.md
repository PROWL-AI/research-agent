# W3-T1 — ledger v2: evidence truth (KA-07, KA-08, KA-09, B-007)

Wave 3 of [`../2026-10-11-waves-canvas.md`](../2026-10-11-waves-canvas.md). **Read §2 N-EVID in full — it
is the contract.** Builds on wave 2 (checkpoint v2: `StepRecord.step_id`, run-dir-relative `raw_ref`,
`raw_sha256`, claim ids derived from `step_id`; read `git log --oneline -8` and the wave-2 code first).

Repository: this checkout of PROWL-AI/research-agent, Python 3.11, `.venv`. **Do not commit or push**;
no paid calls; no `.env`; do not restart services. Public repository: no absolute home paths or private
agent names in anything you write.

## The defects (reproduced at `c0dfb6e`; re-locate lines — wave 2 moved code)

- **KA-07** `Ledger._apply_status` (`research_agent/evidence/ledger.py`, ~:169-209 at `c0dfb6e`) sets
  status incrementally from the incoming claim. A valueless claim leaves `contradictory` empty, falls
  into the corroboration branch (counts distinct `source_tool`, ignores values) and overwrites every
  peer to `verified` — 100 vs 200 become verified after a third claim with `value=None`.
- **KA-08** `verbatim=bool(raw_claim.get("verbatim"))` straight from the extractor LLM
  (`agent/orchestrator.py` `_extract_claims`); verbatim ⇒ `verified` unconditionally, even inside a
  conflict. `Claim` has no quote/span field — nothing checks the claim against the stored raw. The
  extractor sees only the first 12k chars of the raw.
- **KA-09** independence = distinct `source_tool` (`ledger.py` ~:201-207); `source_url` is stored but
  never compared. web_search + page_scraper of one URL = two "independent" sources.
- **B-007** a transform claim (`source_tool="transform"`, an LLM summary of tool X) corroborates X.

Probes to port into `tests/test_ka_contracts.py` (no xfail) from
`docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py`:
`test_ka07_valueless_claim_cannot_erase_numeric_conflict`, `test_ka08_fabricated_verbatim_is_not_verified`,
`test_ka09_same_document_is_not_two_independent_sources`. Translate assertions to the v2 API only where
the API moved, preserving intent; state each translation.

## What to build (canvas §2 N-EVID)

1. **Claim v2** fields: `step_id`, `quote: str | None`, `quote_span: tuple[int, int] | None` (offsets in
   the stored raw text), `source: SourceIdentity` (`delivery_tool`, `origin_url` normalized,
   `publisher` = registrable domain or provider dataset id, `document_sha256`, `independence_key`),
   `verification: {method: span|corroboration|none, detail: str}`. Keep `id`, `claim`, `value`, `unit`,
   `subject`, `retrieved_at`, `raw_ref`, `status`. `verbatim` is removed from the persisted model (a v1
   field read only by migration). `Ledger.SCHEMA_VERSION = 2`.
2. **URL normalization + registrable domain** without new heavy dependencies: lowercase scheme/host,
   strip `www.`, default ports, fragments, tracking params (`utm_*`, `gclid`, `fbclid`), trailing slash;
   registrable domain by a small built-in public-suffix subset covering common multi-part suffixes
   (`co.uk`, `com.au`, `co.jp`, …) — document the limitation in the module docstring. If you judge a
   dependency necessary (e.g. `tldextract` with an offline snapshot), say why in the report instead of
   adding it.
3. **Span verification** at extraction: the extractor prompt asks for `quote` (exact text) instead of a
   `verbatim` bool; the orchestrator reads the stored raw via `raw_ref` (checks `raw_sha256`), searches the
   quote whitespace-normalized over the **whole** raw text (not only the first 12k chars the extractor
   saw), records `quote_span`, and checks the claim's value occurs inside the quote (numeric tolerance as
   the ledger's existing normalization). Found → `verification.method="span"`. Not found → the claim
   stays `assumed` with `verification.detail="quote not found in stored raw"`; never `verified`.
4. **`Ledger.recompute(subject_key)`** over the whole group, order-independent, called on every add and
   on load: conflict if ≥2 distinct normalized values among valued claims (all valued claims in the group
   → `conflict`, a span-verified one keeps `verification.method="span"` but its status is `conflict` —
   the report must surface the disagreement); else `verified` for span-verified claims and for valued
   claims with ≥2 distinct **known** `independence_key`s agreeing; else `assumed`. A valueless claim never
   corroborates and never resolves a conflict. `unknown` independence never counts. A transform claim's
   `independence_key` is the set of its inputs' keys (it never adds independence).
5. **v1 ledger load**: recompute with v2 rules; a v1 `verbatim=true` claim without a quote becomes
   `assumed` with `verification.detail="v1 verbatim without quote"` (disclosed, not hidden). Existing local
   `runs/*/ledger.json` must load.
6. **Consumers in the same change:** writer prompt (`agent/writer.py`, "VERIFIED or ASSUMED tag matching the
   ledger claim status" — add CONFLICT handling and say verified means span or independent corroboration),
   `agent/citations.py` (claim JSON fields), `evals/judge.py` (claim fields it reads), charts if they read
   `verbatim`, `Ledger.as_prompt_json` (replace `verbatim` with `verification`), report render.
7. **Events:** `claim.verified` (claim_id, method), `claim.conflict` (subject_key, values),
   `claim.quote_not_found` (claim_id, step_id).
8. **Docs:** `docs/runbook-authoring.md` (VERIFIED / independent-source rules, ~:85-86 at `c0dfb6e`),
   README evidence section, `docs/ux/scenarios.md` CORE-09 and CORE-10 → name the tests in Coverage and set
   `PASS@W3` (the orchestrator stamps the SHA), FABRIC.md note that the service output's `quality` string
   about KA-07..09 (`service/runtime.py`) is updated to what is now true.

## Tests (TDD)

- The three ported probes green.
- Order-independence: for a fixed set of claims (values 100, 200, None, a span-verified 100, two tools on
  one URL), every permutation of insertion gives identical final statuses (use `itertools.permutations`
  on a small set).
- Reload: save → load → statuses identical.
- Span: quote present beyond the first 12k chars → verified; quote absent → assumed; value not inside the
  quote → assumed; raw hash mismatch → assumed with detail.
- URL normalization table test.
- Transform claim + its input tool claim → not verified by corroboration.
- Update tests that pinned the old behaviour (`tests/test_ledger.py`, `tests/test_audit_batch_a.py`
  verbatim/two-tool tests) — say which assertion encoded which defect.

## Ownership

`research_agent/evidence/ledger.py`, new `research_agent/evidence/source.py` (URL/identity helpers),
`research_agent/agent/orchestrator.py` (`_extract_claims` and the extraction prompt only),
`research_agent/agent/writer.py`, `research_agent/agent/citations.py`, `research_agent/charts.py`,
`research_agent/report/render.py`, `research_agent/service/runtime.py` (`quality` string only),
`evals/judge.py`, `tests/**`, `README.md`, `docs/runbook-authoring.md`, `docs/FABRIC.md`, `docs/ux/scenarios.md`.

## Done when (paste outputs)

```sh
.venv/bin/python -m pytest tests/ -q
PYTHONPATH=tests:. .venv/bin/python -m pytest -q docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py   # all 12 pass (if the probe imports a removed field, report it and show the ported test instead)
.venv/bin/python -m research_agent validate
for f in runs/*/ledger.json; do .venv/bin/python -c "import sys; from pathlib import Path; from research_agent.evidence.ledger import Ledger; l=Ledger.load(Path(sys.argv[1])); print(sys.argv[1], len(l.claims))" "$f"; done
```

Report: files changed (why each), each probe translation, each changed old assertion and the defect it
encoded, local ledgers load result, anything noticed but not fixed (file:line).
