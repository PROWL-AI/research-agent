# Knowledge pack — inherited patterns and traps

Distilled from the Prowl monorepo (`0xDEV`, PROWL-AI/prowl-app) before this
agent's first commit, per the Fabric new-agent intake. Every trap below has a
planted eval fixture in `evals/fixtures/` — knowledge transfers as a check,
not as prose.

## Sources

- `research_guidelines/*.md` — 13 modules (00-core … 95-verification), the
  source of truth for research doctrine in the parent project.
- `tools/manifest.yaml`, `tools/chains.yaml`, `tool_profiles/` — machine-readable
  registry of 442 active tools across 17 providers.
- `mcp_server/tools.py`, `mcp_server/session_tools.py` — the remote MCP surface
  this agent consumes (`prowl_search_tools`, `prowl_tool_info`,
  `prowl_call_tool`, async session tools, `prowl_generate_artifact`).
- `orchestrator_agent/` — the parent's planner → DAG → evidence → blueprint →
  report pipeline.
- External research (2026-10): Anthropic's multi-agent research system writeup,
  LangChain open_deep_research, GPT Researcher, Agent Skills spec,
  domain runbook frameworks (Klue, RevenueCat, Reforge, Data-Mania). URLs in
  each runbook's references.

## Patterns (what worked — borrowed deliberately)

1. **Guidelines as the planner's doctrine.** The parent injects
   `research_guidelines` modules into the planner prompt per query type.
   Here the same content becomes runbook bodies — imperative numbered steps,
   each naming its tools and its evidence output.
   Origin: `orchestrator_agent/prompts/__init__.py` (`_GUIDELINE_MODULE_MAP`).
2. **Verification protocols as hard rules.** Triangulation (≥2 sources, ≥3 for
   key numbers), hallucinated-precision guard, `[CONFLICT]` protocol,
   VERIFIED/ASSUMED tripwire, confidence ladder, "LLM is never a primary
   source". Origin: `research_guidelines/95-verification.md`.
3. **Machine-readable tool registry beside prose.** Manifest carries
   `chain_role`, `alternatives` (failover map), `chain_inputs`; chains carry
   extract paths. Here: runbook frontmatter `tools:` allowlist + budgets, and
   `scripts/validate_runbooks.py` checks names against the live catalog.
   Origin: `tools/manifest.yaml`, `tools/chains.yaml`.
4. **Evidence ledger between research and writing.** The parent's EvidenceAgent
   verifies claims before the report; external consensus (GPT Researcher
   source tracking, OpenAI inline citations, Anthropic CitationAgent) is the
   same idea. Here it is enforced structurally: the writer only sees ledger
   entries, and a separate citation-verification pass checks the draft against
   stored raw evidence. Origin: `orchestrator_agent/evidence.py` + external
   research.
5. **Error/fallback discipline.** On-error-skip annotations, provider failover
   maps, degraded flags, partial results instead of hard failure.
   Origin: `research_guidelines/00-core.md`, manifest `alternatives`.
6. **Cost-tier awareness.** Prefer cheap-first tool ordering; response-priced
   providers behind explicit budgets. Origin: `research_guidelines/05-tool-selection.md`.
7. **Orchestrator-worker with context isolation and mandatory compression at
   every agent boundary; one-shot writer; separate citation pass; model
   tiering by role.** Origin: external research (Anthropic multi-agent,
   LangChain open_deep_research) — the parent's parallel section writers work
   because a synthesis step reconciles them; LangChain's failure without one
   is the cautionary tale.

## Traps (recorded failures and dead ends — planted fixtures where one exists)

| # | Trap | Origin | Coverage |
|---|---|---|---|
| T1 | Guidelines described Apify as an active fallback, but the registry had **zero** Apify tools — an agent reading prose planned calls that could never run | `0xDEV` manifest vs guidelines audit, T-303 | `t1_nonexistent_tool.json` — `validate_runbooks.py` must FAIL on a runbook referencing an unregistered tool |
| T2 | Moz (29 tools) and Keywords Everywhere (14) fully registered but **never named in guidelines** — whole capability classes invisible to the planner | same audit | covered by design, not a fixture: the planner binds ONLY the live MCP catalog + the runbook allowlist, so catalog drift cannot hide or invent capability; the 2026-10 audit additionally closed the parent-side verification gap (T398) |
| T3 | Stale tool profiles for retired providers (Pinterest, google_events) left in `tool_profiles/` — response-shape docs for dead tools | same audit | `t3_retired_tool.json` — planner must reject a plan step naming a retired tool, with a clear error; the offline validator additionally fails runbooks naming retired tools since 2026-10-08 (clean catalog snapshot) |
| T4 | Wayback module existed with no registered tools; growth-signals referenced "archive.org homepage diff" that no agent could call | same audit | covered by T1 fixture (same failure class, different instance) |
| T5 | Three sources of truth for tool alternatives (`TOOL_ALTERNATIVES`, manifest `alternatives`, `serp_consolidation.py`) drifted apart | same audit | this repo has exactly one: the live MCP catalog + runbook allowlist |
| T6 | Traffic/estimate numbers quoted without error bands read as precision; guidelines cap them (30–50%, >70% under 50–100k visits) | `research_guidelines/80-market-sizing.md`, `70-channel-economics.md` | `t6_hallucinated_precision.json` — planted as a LINT test (`tests/test_writer.py`): a bare estimate without citation fails lint |
| T7 | Conflicting sources silently averaged instead of surfaced | `95-verification.md` | `t7_conflict_protocol.json` — a run with contradictory inputs must emit `[CONFLICT]`, not a blended number |
| T8 | Benchmark quoted without its qualifiers (trial conversion without paywall type/trial length; capture rate without horizon) | external research (RevenueCat, FirstPageSage) | encoded as runbook guards (subscription-app-audit requires quartile qualifiers); no judge/lint automation exists for this — do not cite this row as a check |

## What this agent deliberately does NOT inherit

- Provider secrets and in-process provider clients (`api_tools/`) — the agent
  is a billed MCP client; the parent owns the providers.
- Server-side artifact renderers (PDF/PPTX/video/audio) — available remotely
  via `prowl_generate_artifact` when a session exists; not reimplemented.
- Billing/auth — server-side concerns of the Prowl MCP; this agent declares
  its money effect (wallet spend) in its Fabric bundle instead.
