---
name: competitor-seo
description: >-
  Offensive and defensive SEO analysis against 1-4 named competitor domains:
  difficulty-qualified keyword gap attack list, backlink gap confirmed by two
  independent indexes (DataForSEO + Majestic), SERP feature domination map,
  backlink velocity, and content-gap briefs. Use for SEO competitor analysis,
  keyword strategy, or link-building target lists — not for a single-domain
  technical audit (that is a different job).
version: "1.0"
inputs:
  - { name: target, type: "domain", required: true, doc: "Your/subject domain — the one we attack for and defend." }
  - { name: competitors, type: "list[domain]", required: true, max: 4, doc: "Named competitor domains, 1-4. Heavy SEO steps fan out over the top 3." }
  - { name: market, type: "string", required: false, doc: "Product category / niche and primary market, used for money-keyword phrasing and SERP location." }
tools:
  - spyfu_get_domain_stats
  - spyfu_get_top_pages
  - spyfu_get_most_valuable_keywords
  - spyfu_competing_seo_keywords
  - spyfu_where_they_outrank_you
  - spyfu_organic_outranking_keywords
  - spyfu_get_historic_rankings
  - spyfu_serp_analysis
  - dataforseo_labs_domain_rank_overview
  - dataforseo_labs_ranked_keywords
  - dataforseo_labs_domain_intersection
  - dataforseo_labs_bulk_keyword_difficulty
  - dataforseo_labs_search_intent
  - dataforseo_kw_google_ads_search_volume
  - dataforseo_labs_bulk_traffic_estimation
  - dataforseo_labs_historical_bulk_traffic_estimation
  - dataforseo_labs_relevant_pages
  - dataforseo_labs_historical_rank_overview
  - dataforseo_labs_historical_serps
  - dataforseo_bl_summary
  - dataforseo_bl_bulk_ranks
  - dataforseo_bl_bulk_spam_score
  - dataforseo_bl_domain_intersection
  - dataforseo_bl_referring_domains
  - dataforseo_bl_timeseries_summary
  - dataforseo_bl_timeseries_new_lost_summary
  - dataforseo_bl_bulk_new_lost_backlinks
  - dataforseo_bl_bulk_new_lost_referring_domains
  - majestic_get_index_item_info
  - majestic_get_ref_domains
  - dataforseo_serp_google_organic
  - dataforseo_serp_bing_organic
  - google_rank_tracking
  - serpapi_google_related_questions
  - dataforseo_content_search
  - dataforseo_content_sentiment
  - google_scholar
  - gemini_keyword_report
  - firecrawl_search
  - firecrawl_scrape_page_markdown
budget: { max_tool_calls: 60, max_usd: 2.50, max_minutes: 25 }
outputs: { report_template: competitor-seo, formats: [markdown, html] }
---

# Competitor SEO: Attack & Defend

**Goal:** a decision-ready offensive/defensive SEO plan against named rivals.
Not a keyword dump — a prioritized attack list where every opportunity is
qualified by difficulty and intent, a link-gap shortlist confirmed by two
independent indexes with outreach contact pages, a SERP domination map for
the money keywords, and content-gap briefs. Depth on 1-4 named competitors;
no discovery phase — the user already knows who they fight.

## Principles (read first)

- **A gap without difficulty is not a strategy.** Every keyword opportunity
  carries volume, difficulty, and intent before it reaches the report.
  "They rank, we don't" is an observation; "they rank for a 500-volume,
  22-difficulty, transactional keyword we can win in 90 days" is a plan.
- **Direction beats overlap.** `spyfu_where_they_outrank_you` /
  `spyfu_organic_outranking_keywords` give the attack/defend split; aggregate
  overlap lists do not. Run both directions before writing any verdict.
- **One index is an anecdote.** Link gaps and authority scores must survive
  two independent crawls (DataForSEO and Majestic). Prospects that surface in
  both are the shortlist; single-index finds are ASSUMED.
- **Velocity beats snapshots.** A domain adding referring domains every month
  is compounding; a bigger static profile that stopped growing is a castle
  under siege. Timeseries first, counts second.
- **Error bands or silence.** Traffic and authority estimates carry 30-50%
  error (>70% under ~100k monthly visits). Never print a bare estimate.

## Sequence

1. **Scope** — Transform: normalize domains (strip scheme/path/www), cap
   competitors at 4, fix the SEO working set as target + top-3 competitors.
   If `market` given, use it to phrase money keywords and SERP location;
   default location/language is US English and must be stated in the report.
2. **Baseline sweep** — Fan-out per domain (target + all competitors):
   `spyfu_get_domain_stats` with `past_n_months=12` +
   `dataforseo_labs_domain_rank_overview` + `spyfu_get_top_pages` +
   `spyfu_get_most_valuable_keywords` (target + top-2 only). Parallel bulk
   (one call each, all domains): `dataforseo_labs_bulk_traffic_estimation` +
   `dataforseo_bl_bulk_ranks` + `dataforseo_bl_bulk_spam_score`.
3. **Outranking matrix** — Fan-out target vs each top-3 competitor, both
   directions: `spyfu_where_they_outrank_you` +
   `spyfu_organic_outranking_keywords`. Transform: attack list (they outrank
   us) and defend list (we outrank them) — the skeleton of the report.
4. **Keyword gap** — Fan-out `dataforseo_labs_domain_intersection`
   (`target1=target`, `target2=competitor`, filter
   `["keyword_data.keyword_info.search_volume",">",100]`) +
   `spyfu_competing_seo_keywords`, target vs each top-3 competitor
   (on_error=skip). Transform: dedupe into one candidate gap set; also pull
   `dataforseo_labs_ranked_keywords` for the target (limit=200) as the
   owned-keyword reference.
5. **Difficulty & intent qualification** — Transform: top-30 gap/attack
   keywords → `dataforseo_labs_bulk_keyword_difficulty` +
   `dataforseo_labs_search_intent` + `dataforseo_kw_google_ads_search_volume`
   (volume + CPC + monthly trend). Transform: priority score = volume ×
   intent weight (transactional > commercial > informational) ÷ difficulty.
   Any keyword without a difficulty score is dropped from the attack list.
6. **Backlink gap — two indexes** — `dataforseo_bl_domain_intersection` with
   `targets=[competitors]` and `exclude_targets=[target]` (links to rivals,
   not to us) + `majestic_get_ref_domains` with target + top-3 competitors,
   `min_matches_required=2`, `order_by=13`, `order_dir=1` (TrustFlow desc).
   Transform: shortlist = domains in BOTH indexes, ranked by rank × number of
   competitors linked (3/3 links but not to us = top priority). Single-index
   finds go to a secondary list tagged ASSUMED.
7. **Authority cross-check** — `majestic_get_index_item_info` batched for all
   domains vs `dataforseo_bl_bulk_ranks` from step 2: disagreement >20 points
   on authority is a `[CONFLICT]` — report both, never average. Fan-out
   `dataforseo_bl_summary` per domain for referring domains, spam score,
   dofollow ratio (on_error=skip for the 4th competitor).
8. **Backlink velocity** — Fan-out `dataforseo_bl_timeseries_summary` per
   domain (12-month window). Parallel bulk:
   `dataforseo_bl_bulk_new_lost_backlinks` +
   `dataforseo_bl_bulk_new_lost_referring_domains` for all domains, and
   `dataforseo_bl_timeseries_new_lost_summary` for the target
   (on_error=skip). Transform: who is compounding (steady new > lost), who
   spiked (campaign or press event), who is decaying.
9. **SERP domination map** — Transform: pick 3-5 money keywords (highest
   value × transactional/commercial intent from steps 2-5). Fan-out per
   keyword: `dataforseo_serp_google_organic` (60+ feature types) +
   `spyfu_serp_analysis` + `google_rank_tracking` +
   `dataforseo_serp_bing_organic` (on_error=skip). For the top-2 keywords add
   `dataforseo_labs_historical_serps` (on_error=skip). Transform: per keyword
   per engine — who owns featured snippet, PAA, knowledge panel, sitelinks;
   unclaimed features = opportunities.
10. **Content gap** — Fan-out `dataforseo_labs_relevant_pages` per competitor
    (limit=50) + `serpapi_google_related_questions` for each money keyword.
    Transform: page topics and PAA questions competitors cover that the
    target lacks → 3-5 content-gap briefs (topic, target keyword set, intent,
    which competitor ranks, suggested format).
11. **E-E-A-T evidence** — `dataforseo_content_search` +
    `dataforseo_content_sentiment` per brand (target + top-2) +
    `google_scholar` for the category + `dataforseo_bl_referring_domains`
    filtered to `.edu`/`.gov` sources (on_error=skip). Transform: who holds
    institutional trust the target cannot fake quickly.
12. **Link-target enrichment** — Transform: top-10 of the two-index shortlist
    → `firecrawl_search("{domain} contact OR \"write for us\" OR submit")`
    (on_error=skip); confirm the best contact/contribute URL per prospect
    with `firecrawl_scrape_page_markdown` on at most 5 (on_error=skip).
    A shortlist without a contact path is not actionable.
13. **Trajectory overlay** — `dataforseo_labs_historical_bulk_traffic_estimation`
    for all domains (12 months) + `dataforseo_labs_historical_rank_overview`
    for target and top-1 competitor + `spyfu_get_historic_rankings` for the
    single most contested money keyword (on_error=skip). Transform: rising /
    flat / falling verdict per domain — required before any "who is winning"
    claim.
14. **Synthesis** — `gemini_keyword_report` over the full keyword set for
    topic clustering; final attack/defend matrix with priority scores; the
    top-10 keyword gaps named explicitly (never "see appendix"); the
    two-index link shortlist with contact pages; content-gap briefs. Verdicts
    come last and cite step evidence.

## Verification (hard rules)

- Key numbers (traffic, authority, keyword volume): ≥2 independent sources or
  tag ASSUMED. LLM output (Gemini clustering) is never a primary source — it
  organizes evidence, it does not create it.
- DataForSEO vs Majestic authority disagreement >20 points → `[CONFLICT]`,
  both values reported, no silent averaging; expect ≤2× divergence on raw
  counts — wider means the claim is unsafe to state as fact.
- Every keyword in the attack list carries volume + difficulty + intent, or
  it is cut. Every traffic figure carries its error band.
- A 12-month trend (keywords, traffic, or links) is mandatory before any
  trajectory verdict. Static snapshots alone → tag the whole scorecard
  ASSUMED.
- Link-gap shortlist requires presence in both indexes; single-index
  prospects are labeled and ranked below.

## Output instructions

Template `competitor-seo`. Required sections:

1. **Executive summary** — who we can realistically outrank in 90 days, who
   is compounding away from us, the single biggest threat — one line each,
   with evidence.
2. **Competitive scorecard** — per domain: authority (both indexes, error
   band), traffic estimate with band, spam score, 12-month trend verdict.
3. **Attack/defend matrix** — keywords where each rival outranks us vs where
   we outrank them, with positions and priority scores.
4. **Top-10 keyword gaps** — named explicitly, each with volume, difficulty,
   intent, which competitor owns it, and why it is winnable.
5. **Link-gap shortlist** — two-index confirmed prospects with contact
   pages; secondary ASSUMED list below; per-prospect competitor-link count.
6. **Backlink velocity** — new/lost referring domains per month per domain;
   who is compounding, spikes annotated with likely cause.
7. **SERP domination map** — per money keyword: feature ownership (snippet,
   PAA, knowledge panel) per engine; unclaimed features flagged.
8. **Content-gap briefs** — 3-5 briefs: topic, keywords, intent, rival proof,
   suggested format.
9. **E-E-A-T evidence** — citations, sentiment, scholarly/institutional
   links per brand.
10. **Source log** — every figure with tool + retrieval date; confidence
    ladder; `[CONFLICT]` register; refresh recommendation (monthly for
    velocity, quarterly for gaps).

## Guards (failure modes to refuse)

- Bare authority scores: any "DR 72 vs 58" style claim from a single index —
  refuse to rank competitors on it until step 7's cross-check exists.
- Difficulty-free gap lists: a keyword gap table without difficulty + intent
  columns is an observation dump, not a strategy — do not ship it.
- Snapshot-only verdicts: if velocity and 12-month history all failed
  (on_error=skip everywhere), say the trajectory sections are ASSUMED in the
  summary — never present static data as momentum.
- Averaging conflicts: two sources disagreeing >2× on traffic or >20 points
  on authority must surface as `[CONFLICT]` with both numbers — never merged.
- One-index link gap: presenting `dataforseo_bl_domain_intersection` alone as
  "the" outreach list — Majestic confirmation is required for the shortlist.
- Discovery creep: the user named the competitors; do not expand to "the top
  20 SERP players" — if a step suggests a bigger threat, note it as a
  follow-up recommendation instead.
