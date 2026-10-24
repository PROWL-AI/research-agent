---
name: saas-competitor-teardown
description: >-
  Deep-dive on 1-5 named competitor domains (or discover them from a target
  domain): positioning, pricing archaeology, SEO/keyword footprint, paid ads as
  a health signal, backlinks, reviews, hiring and trajectory signals, AI
  visibility. Output is a battlecard-grade report: where they win, where they
  are vulnerable, what to say. Use when the user names competitors or asks
  "who are we up against / tear down X".
version: "1.0"
inputs:
  - { name: target, type: "domain", required: false, doc: "Your/subject domain. If omitted, the first competitor is the subject." }
  - { name: competitors, type: "list[domain]", required: false, max: 5, doc: "Named competitors. If omitted, discovered in step 1." }
  - { name: market, type: "string", required: false, doc: "Product category / niche, used for market sizing and trend queries." }
tools:
  - exa_similar_search
  - spyfu_get_combined_competitors
  - spyfu_get_domain_stats
  - spyfu_get_top_pages
  - spyfu_get_most_valuable_keywords
  - spyfu_competing_seo_keywords
  - spyfu_where_they_outrank_you
  - spyfu_organic_outranking_keywords
  - spyfu_get_ppc_keywords
  - spyfu_get_paid_search
  - spyfu_get_ad_history
  - dataforseo_labs_competitors_domain
  - dataforseo_labs_domain_rank_overview
  - dataforseo_labs_domain_intersection
  - dataforseo_labs_bulk_keyword_difficulty
  - dataforseo_labs_search_intent
  - dataforseo_labs_bulk_traffic_estimation
  - dataforseo_bl_summary
  - dataforseo_bl_bulk_ranks
  - dataforseo_bl_domain_intersection
  - dataforseo_bl_timeseries_summary
  - dataforseo_domain_technologies
  - majestic_get_index_item_info
  - majestic_get_ref_domains
  - firecrawl_search
  - firecrawl_scrape_website
  - crawl_funnel_path
  - find_subdomains
  - meta_ad_library
  - meta_ad_library_ad_details
  - linkedin_ad_library
  - tiktok_ads_library
  - google_ads_advertiser_info
  - foreplay_discovery_ads
  - foreplay_discovery_brands
  - foreplay_ad_details
  - foreplay_brand_analytics
  - scrape_review_platforms
  - google_trends
  - google_jobs
  - google_news
  - youtube_search
  - google_ai_mode
  - dataforseo_ai_llm_mentions
  - dataforseo_ai_llm_mentions_top_domains
  - perplexity_responses
  - gemini_analyze_website
  - reddit_search
budget: { max_tool_calls: 90, max_usd: 3.00, max_minutes: 30 }
outputs: { report_template: competitor-depth, formats: [markdown, html] }
---

# SaaS Competitor Teardown

**Goal:** decision-ready competitive intelligence. Not a feature table — a
battlecard: where each rival wins, where they are vulnerable, what to say,
plus quantified health and trajectory signals. Depth on the named rivals beats
breadth across ten.

## Principles (read first)

- **Ad copy reveals positioning better than the homepage.** Ads are
  conversion-optimized; homepages are compromise-optimized. Never write the
  positioning section from the homepage alone.
- **Sustained ad spend is the most reliable health signal.** A creative
  running 60-90+ days is a proven winner, likely profitable (creative-level)
  — advertisers kill losers fast. Weight every ad finding by longevity. Every ad library here is active-only:
  longevity verdicts are survivorship-biased (killed ads are invisible), so
  phrase them "among currently active ads" and lean on Foreplay/SpyFu
  history for anything about the past.
- **Traffic is reach, not revenue.** Every traffic/estimate number carries its
  error band (30-50% typically; >70% under ~100k monthly visits) and a
  VERIFIED/ASSUMED tag. Never quote a bare estimate.
- **Order is the framework:** understand → quantify → risk → synthesis.
  Do not write the verdict before the evidence sections exist.

## Sequence

1. **Scope** — Transform: normalize domains (strip scheme/path/www). If
   `competitors` given, cap at 5 and skip step 2. If only `target` given, run
   `find_subdomains` on it in parallel with step 2.
2. **Discovery** (skip if competitors named) — Parallel:
   `exa_similar_search` + `spyfu_get_combined_competitors` +
   `dataforseo_labs_competitors_domain` + `firecrawl_search("{target}
   competitors")`. Transform: top 5 by relevance, deduplicated across sources.
   Prefer competitors with active paid ads and the same ICP over the biggest
   brands in the space.
3. **SEO baseline** — Fan-out per competitor AND target:
   `spyfu_get_domain_stats` + `spyfu_get_top_pages` +
   `spyfu_get_most_valuable_keywords` +
   `dataforseo_labs_domain_rank_overview` + `dataforseo_bl_summary`
   (on_error=skip).
4. **Keyword gap** — Fan-out `spyfu_competing_seo_keywords` and
   `dataforseo_labs_domain_intersection`, target vs each top-3 competitor;
   `spyfu_get_ppc_keywords` per competitor (on_error=skip).
5. **Outranking matrix** — Fan-out `spyfu_where_they_outrank_you` +
   `spyfu_organic_outranking_keywords` target vs top-3.
   Transform: attack/defend priority matrix. Enrich top-20 gap keywords with
   `dataforseo_labs_bulk_keyword_difficulty` + `dataforseo_labs_search_intent`
   (on_error=skip).
6. **Backlink comparison** — `dataforseo_bl_bulk_ranks` for all domains (one
   batched call) + `majestic_get_index_item_info` batched (TrustFlow/CitationFlow
   cross-check — a second independent index; disagreement >20 points on
   authority is a `[CONFLICT]`) + `dataforseo_bl_domain_intersection` target vs
   top-2 + `dataforseo_bl_timeseries_summary` for velocity (on_error=skip) +
   `majestic_get_ref_domains` with min_matches_required=2 for the link-gap
   shortlist (on_error=skip).
7. **Site & pricing scrape** — Fan-out `firecrawl_scrape_website` per
   competitor: homepage + /pricing. Transform: pricing tiers, packaging, trial
   vs freemium, annual-vs-monthly delta, discount patterns. Enterprise pricing
   is often offline — mark it and mine it in step 11 from reviews/forums
   ("pricing archaeology"), never invent it.
8. **Positioning & messaging** — Fan-out `gemini_analyze_website` per
   competitor. Transform: one-sentence value prop, category claim, target
   segment, claimed differentiator per competitor — from ads AND homepage,
   noting where they disagree.
9. **Ad intelligence (health signal)** — Parallel per competitor:
   `meta_ad_library` + `linkedin_ad_library` + `tiktok_ads_library` +
   `google_ads_advertiser_info` + `foreplay_discovery_ads` +
   `foreplay_discovery_brands` (on_error=skip). Then
   `meta_ad_library_ad_details` + `foreplay_ad_details` +
   `foreplay_brand_analytics` on the top advertisers, and `spyfu_get_ad_history`
   + `spyfu_get_paid_search` for search spend history. Transform: per
   competitor — active ad count, longest-running creative, platform mix,
   spend-trajectory verdict (scaling / steady / retreating). An advertiser
   sustaining spend 6+ months is almost certainly profitable
   (advertiser-level); say so explicitly when the evidence shows it.
10. **Funnel crawl** — Transform: landing URLs from ads → fan-out
    `crawl_funnel_path` (on_error=skip). Note trial gate placement and
    onboarding friction where visible.
11. **Reviews & voice of customer** — `scrape_review_platforms` per competitor
    (Trustpilot/G2/Capterra composite, filtered for churn and switching
    themes) + `reddit_search` for quoted-price testimonials and complaints
    plus churn variants `"{brand} cancelled"`, `"{brand} refund"`,
    `"{brand} vs"` (on_error=skip). Transform: recurring complaints
    (= exploitable gaps), praised workflows (= their real moat), customer
    vocabulary (= messaging input), any quoted prices; capture switch-from/
    switch-to mentions as churn-reason evidence.
12. **Market pulse & trajectory** — Parallel: `google_trends` (brand terms,
    12-month), `google_jobs` (hiring velocity and role mix — many AEs =
    scaling GTM; first-of-function hires = new bets; ghost-jobs caveat: ~40%
    of postings may never be filled), `google_news` (funding, launches,
    layoffs). `youtube_search` per brand (on_error=skip).
13. **AI search visibility** — `google_ai_mode` +
    `dataforseo_ai_llm_mentions` + `dataforseo_ai_llm_mentions_top_domains`
    for 3-5 category queries, target vs competitors (on_error=skip).
14. **Tech stack** — Fan-out `dataforseo_domain_technologies` per competitor
    (on_error=skip). Note build-vs-buy signals only when they inform a
    vulnerability or cost-structure claim.
15. **Traffic cross-check** — `dataforseo_labs_bulk_traffic_estimation` for all
    domains + ONE `perplexity_responses` query per top-2 competitor for
    engagement metrics (on_error=skip). If two sources disagree >2x, report
    the range as `[CONFLICT]` — never average silently.
16. **Synthesis** — Transform: per competitor — health scorecard (SEO
    trajectory, ad spend trajectory, hiring, review velocity, churn signals),
    win / vulnerable / what-to-say, and one battlecard row. Verdicts come last
    and must cite section evidence.

## Verification (hard rules)

- Key numbers (traffic, spend, authority, market size): ≥2 independent sources
  or tag ASSUMED. LLM output (Perplexity, Gemini, AI Mode) is never a primary
  source — cross-check against a data tool.
- Majestic vs DataForSEO authority disagreement >20 points → `[CONFLICT]`.
- No bare estimates: every traffic/revenue figure carries its error band.
- Ghost-jobs caveat on any hiring-based inference.

## Budget degradation (drop order)

A full fan-out at 5 competitors exceeds max_tool_calls. When the budget
tightens, drop in this order and name each dropped block in the partial
report: (1) tech-stack scan (step 14), (2) hiring/jobs
signals, (3) AI-visibility fan-out reduced to 2 competitors, (4) backlink
cross-check reduced to one index, (5) competitor set reduced to the 3
strongest named. Positioning, pricing archaeology, SEO baseline and the
ads-health read are never dropped.

## Output instructions

Template `competitor-depth`. Required sections:

1. **Executive summary** — the 3 strongest and the single most vulnerable
   rival, one line each, with evidence.
2. **Positioning & messaging matrix** — value prop / category claim / segment /
   differentiator per competitor; ads-vs-homepage deltas flagged.
3. **SEO & keyword footprint** — domain stats, top gaps (attack/defend
   matrix), difficulty-qualified top-20.
4. **Paid acquisition & health signals** — per competitor: platforms, creative
   longevity, spend trajectory, profitability inference with confidence tag.
5. **Pricing archaeology** — tiers table + mined quoted prices with sources;
   "offline pricing" marked, never guessed.
6. **Reviews — voice of customer** — complaints→gaps table, praised workflows,
   churn/switching reasons, 3-5 verbatim quotes with platform.
7. **Trajectory signals** — trends/jobs/news, 12-month view, ghost-jobs caveat.
8. **AI visibility** — mentions per engine per query.
9. **Battlecard** — one row per competitor: where they win / where they're
   vulnerable / churn signals / what to say / traps to set.
10. **Source log** — every figure with tool + retrieval date; confidence
    ladder; `[CONFLICT]` register; refresh recommendation (quarterly).

## Guards (failure modes to refuse)

- Homepage-and-pricing-page research: if steps 9-12 produced nothing, say the
  report is surface-level in the summary — do not present it as a teardown.
- Analyzing everyone: more than 5 rivals → force a selection, state the
  criterion.
- Static snapshot: if no historical/velocity data was obtainable for a
  competitor, tag their scorecard ASSUMED and say what a refresh should fetch.
