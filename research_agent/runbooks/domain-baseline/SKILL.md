---
name: domain-baseline
description: >-
  Full baseline picture of one domain: subdomains and funnel surfaces,
  SEO/traffic baseline, technical health, tech stack, ads presence, reviews,
  and AI visibility — the "know everything obvious about this site" pass,
  with light competitor context for calibration. Use for first-touch domain
  research, lead qualification, or onboarding a new analysis subject before
  any deeper runbook.
version: "1.0"
inputs:
  - { name: domain, type: "domain", required: true, doc: "The single domain to x-ray." }
  - { name: market, type: "string", required: false, doc: "Product category / niche, used for SERP, trend and AI-visibility queries." }
tools:
  - find_subdomains
  - discover_web_funnels
  - spyfu_get_domain_stats
  - spyfu_get_top_pages
  - spyfu_get_most_valuable_keywords
  - spyfu_get_ppc_keywords
  - spyfu_get_combined_competitors
  - spyfu_competing_seo_keywords
  - spyfu_where_they_outrank_you
  - spyfu_organic_outranking_keywords
  - spyfu_serp_analysis
  - dataforseo_labs_domain_rank_overview
  - dataforseo_labs_ranked_keywords
  - dataforseo_labs_subdomains
  - dataforseo_labs_competitors_domain
  - dataforseo_labs_domain_intersection
  - dataforseo_labs_bulk_traffic_estimation
  - dataforseo_bl_summary
  - dataforseo_bl_referring_domains
  - dataforseo_bl_anchors
  - dataforseo_bl_domain_intersection
  - dataforseo_onpage_task_post
  - dataforseo_onpage_summary
  - dataforseo_onpage_lighthouse
  - dataforseo_onpage_duplicate_tags
  - dataforseo_onpage_non_indexable
  - dataforseo_serp_google_organic
  - dataforseo_domain_technologies
  - dataforseo_biz_google_qna
  - dataforseo_ai_llm_mentions
  - dataforseo_ai_chatgpt_scraper
  - dataforseo_ai_perplexity_responses
  - dataforseo_ai_claude_responses
  - majestic_get_index_item_info
  - exa_similar_search
  - seo_growth_audit
  - firecrawl_scrape_website
  - firecrawl_map_domain
  - firecrawl_search
  - crawl_funnel_path
  - foreplay_get_brands_by_domain
  - foreplay_discovery_brands
  - foreplay_ad_details
  - foreplay_brand_analytics
  - meta_ad_library
  - meta_ad_library_ad_details
  - meta_ad_library_page_info
  - linkedin_ad_library
  - tiktok_ads_library
  - google_ads_advertiser_info
  - scrape_review_platforms
  - reddit_search
  - youtube_search
  - youtube_channel_videos
  - google_trends
  - google_jobs
  - google_news
  - google_ai_mode
  - perplexity_responses
  - gemini_keyword_report
  - gemini_reviews_report
budget: { max_tool_calls: 60, max_usd: 2.00, max_minutes: 25 }
outputs: { report_template: domain-baseline, formats: [markdown, html] }
---

# Domain Baseline

**Goal:** a complete first-pass x-ray of one domain — its subdomain and
funnel topology, SEO/traffic baseline, technical health, ads presence,
reviews, and AI visibility — with just enough competitor context to say
whether the numbers are good. Every section answers "what this means", not
just "what we found".

## Principles (read first)

- **`find_subdomains` is mandatory and early.** Funnel surfaces live on
  subdomains (`app.`, `docs.`, `blog.`, `status.`, `get.`, `demo.`); the
  homepage alone hides onboarding flows, web2app bridges and landing-page
  subdomains. One call per domain, no exceptions.
- **Depth over breadth.** This is the one-domain x-ray, not a market scan.
  Competitors appear only as calibration context — cap them at top-3 and
  never let their analysis outweigh the subject's.
- **Order is the framework:** baseline → tech audit → competitor context →
  keyword gap → backlinks → ads → funnel → reviews → AI visibility → tech
  stack. Do not write the verdict before the evidence sections exist.
- **Traffic is reach, not revenue.** Every estimate carries its error band
  (30-50% typical; >70% under ~100k monthly visits) and a VERIFIED/ASSUMED
  tag. Never infer revenue from traffic alone.
- **A baseline without interpretation is a data dump.** Every report section
  ends with a "what this means" paragraph.

## Sequence

Steps marked (optional) are the first to drop when approaching the 60-call
budget; steps 1-3 and 12 are never optional.

1. **Scope + subdomain discovery (MANDATORY)** — Transform: normalize the
   domain (strip scheme/path/www). `find_subdomains` on it, plus
   `discover_web_funnels` (on_error=skip) for a funnel-grouped topology view.
   Transform: classify subdomains by purpose (app, docs, blog, status,
   landing, tracking); extract funnel URLs for step 12; list subdomains you
   will NOT analyze as follow-ups.
2. **Domain baseline** — Parallel: `spyfu_get_domain_stats` +
   `spyfu_get_top_pages` + `spyfu_get_most_valuable_keywords` +
   `spyfu_get_ppc_keywords` + `dataforseo_labs_domain_rank_overview` +
   `dataforseo_labs_ranked_keywords` (limit=100) + `dataforseo_bl_summary` +
   `majestic_get_index_item_info` (second independent index — TrustFlow/
   CitationFlow cross-check) + `dataforseo_labs_subdomains`
   (which subdomains carry organic traffic vs SEO-invisible).
3. **Site scrape** — `firecrawl_scrape_website` homepage + /pricing (try
   /plans, /packages on 404). Transform: product, offer, pricing model,
   positioning claims. If a page fails (JS-heavy, blocked), state the failure
   in the report — never skip silently.
4. **Technical SEO audit** — `seo_growth_audit` on the homepage +
   `dataforseo_onpage_task_post` (max_crawl_pages=100) +
   `dataforseo_onpage_lighthouse` (on_error=skip).
5. **On-page results** — `dataforseo_onpage_summary` (from $step4.task_id) +
   `dataforseo_onpage_duplicate_tags` + `dataforseo_onpage_non_indexable`
   (on_error=skip). Transform: the 3-5 highest-impact technical issues.
6. **Competitor discovery (context only)** — Parallel:
   `spyfu_get_combined_competitors` + `dataforseo_labs_competitors_domain` +
   `exa_similar_search`. Transform: top-3 by relevance, deduplicated. If
   `market` was given, use it to reject out-of-category matches.
7. **Competitor calibration** — Fan-out `spyfu_get_domain_stats` per top-3 +
   `dataforseo_bl_summary` per top-2. Transform: is the subject's SEO
   baseline ahead of, at, or behind its closest peers — one line per rival.
8. **Keyword gap** — `spyfu_competing_seo_keywords` +
   `dataforseo_labs_domain_intersection`, target vs top-2.
9. **Outranking & SERP** (optional) — `spyfu_where_they_outrank_you` +
   `spyfu_organic_outranking_keywords` vs top-1; `spyfu_serp_analysis` +
   `dataforseo_serp_google_organic` for 3 core `market` keywords
   (on_error=skip). Transform: attack/defend priorities.
10. **Backlink deep-dive** — `dataforseo_bl_referring_domains` +
    `dataforseo_bl_anchors` + `dataforseo_bl_domain_intersection` vs top-2
    (on_error=skip). Anchor-text profile: branded vs commercial vs spam.
11. **Content footprint** (optional) — `firecrawl_map_domain` → Transform: filter
    /blog, /resources, /learn paths → scrape 3 recent posts. `youtube_search`
    + `youtube_channel_videos` for the brand name (on_error=skip).
12. **Ads presence** — Parallel: `foreplay_get_brands_by_domain` +
    `meta_ad_library` + `google_ads_advertiser_info` +
    `foreplay_discovery_brands` + `linkedin_ad_library` +
    `tiktok_ads_library` (on_error=skip). Then `meta_ad_library_ad_details` +
    `meta_ad_library_page_info` + `foreplay_ad_details` +
    `foreplay_brand_analytics` on the top creatives (on_error=skip).
    Transform: platforms, active ad count, longest-running creative (60-90+
    days = proven winner, likely profitable (creative-level)), landing
    URLs for step 13. "Not advertising" is a
    finding — record it, don't omit the section.
13. **Funnel crawl** — Transform: ad landing URLs + funnel subdomain URLs
    from $step1.funnel_urls → fan-out `crawl_funnel_path` (on_error=skip).
    Overlap between ads and subdomain funnels confirms active marketing
    funnels; subdomain funnels with no matching ads are dormant or
    organic-only paths — say which.
14. **Reviews & community** — `scrape_review_platforms` for the brand +
    `firecrawl_search("{domain} reviews")` + `dataforseo_biz_google_qna` +
    `reddit_search` (on_error=skip) → `gemini_reviews_report`. Transform:
    recurring praise, recurring complaints, customer vocabulary, review
    velocity.
15. **Market pulse** — Parallel: `google_trends` (brand term, 12-month) +
    `google_jobs` (hiring velocity and role mix; ghost-jobs caveat: ~40% of
    postings may never be filled) + `google_news` (funding, launches,
    layoffs).
16. **Keyword synthesis** (optional) — `gemini_keyword_report` over the combined
    keyword data from steps 2, 8-9 (on_error=skip). LLM synthesis, never a
    primary source — every keyword it elevates must trace to a data tool.
17. **AI search visibility** — Parallel for 3 product-category queries:
    `google_ai_mode` + `dataforseo_ai_llm_mentions` +
    `dataforseo_ai_chatgpt_scraper` + `dataforseo_ai_perplexity_responses` +
    `dataforseo_ai_claude_responses` (on_error=skip). Transform: is the
    domain cited, mentioned, or absent per engine per query.
18. **Traffic engagement cross-check** — `dataforseo_labs_bulk_traffic_estimation`
    + ONE `perplexity_responses` query: "Monthly visitors, visit duration,
    bounce rate, pages/visit, traffic channel breakdown for {domain}. Cite
    SimilarWeb." (on_error=skip). Sources disagreeing >2x → report the range
    as `[CONFLICT]`, never average silently.
19. **Tech stack** — `dataforseo_domain_technologies` for the target (+ top-2
    competitors, optional). Note build-vs-buy signals only when they inform a
    cost-structure or maturity claim.
20. **Synthesis** — Transform: baseline scorecard (SEO, content, ads, reviews,
    AI visibility, tech — strong / average / weak each, with evidence), the
    per-section "what this means" paragraphs, and the follow-up register
    (unexplored subdomains, skipped optional steps, refresh candidates).

## Budget degradation (drop order)

A full fan-out is ~75 calls against the 60-call budget. When the budget
tightens, drop in this order and name each dropped block in the partial
report: (1) steps marked (optional), (2) tech-stack competitor fan-out
(step 19 reduced to the target only), (3) competitor calibration reduced
to top-1 (step 7), (4) backlink deep-dive reduced to
`dataforseo_bl_summary` alone (step 10), (5) AI visibility reduced to
`google_ai_mode` alone (step 17). Subdomain discovery, domain baseline,
site scrape and ads presence (steps 1-3, 12) are never dropped.

## Verification (hard rules)

- Key numbers (traffic, keywords, authority, ad counts): ≥2 independent
  sources or tag ASSUMED. LLM output (Perplexity, Gemini, AI Mode) is never
  a primary source — cross-check against a data tool.
- Majestic vs DataForSEO backlink counts: within ~2x is expected (independent
  crawls); a larger gap is a `[CONFLICT]`, not a number to average away.
  Their authority scores (Trust Flow vs Authority/Rank) disagreeing by >20
  points is likewise a `[CONFLICT]` — report both with sources.
- No bare estimates: every traffic figure carries its error band; no revenue
  inference from traffic alone — if asked, give a banded range tagged ASSUMED
  with the stated assumptions.
- Every scrape failure, skipped optional step, and unanalyzed subdomain is
  named in the report — silence is not neutrality.

## Output instructions

Template `domain-baseline`. Required sections:

1. **Executive summary** — what this domain is, one-line health verdict per
   pillar (SEO / content / ads / reviews / AI visibility), the single most
   notable finding.
2. **Subdomain & funnel map** — classified subdomain table (purpose, SEO
   traffic if known, funnel role); funnel paths confirmed by ads vs dormant.
3. **SEO & traffic baseline** — domain stats, top pages/keywords, ranked-
   keyword profile, traffic estimate with error band, competitor calibration.
4. **Technical health** — audit + on-page findings, 3-5 highest-impact issues.
5. **Keyword gap & backlinks** — gap priorities, authority cross-check
   (DataForSEO vs Majestic), anchor profile, link-gap shortlist.
6. **Ads presence** — platforms, creative longevity, spend-trajectory verdict,
   or an explicit "no paid presence found" with what that implies.
7. **Content & reviews** — content program cadence/depth; review composite
   with 3-5 verbatim quotes and platform; community signal.
8. **AI visibility** — cited / mentioned / absent per engine per query.
9. **Tech stack** — what the site is built on and what it implies.
10. **What this means** — the interpretation: strengths to build on, gaps
    worth a deeper runbook, follow-up register (unanalyzed subdomains,
    skipped steps, refresh recommendation).
11. **Source log** — every figure with tool + retrieval date; confidence
    ladder (VERIFIED ≥2 sources / SINGLE-SOURCE / ASSUMED); `[CONFLICT]`
    register.

## Guards (failure modes to refuse)

- **Skipping `find_subdomains`.** It is mandatory and early — a baseline
  without the subdomain map is not this runbook; if the call fails, retry
  once, then state the failure prominently.
- **Revenue-from-traffic inference.** Refuse bare revenue claims; error
  bands and ASSUMED tags are mandatory on any monetization estimate.
- **Silent scrape failures.** JS-heavy or blocked pages are stated as
  failures with the tool's error, never dropped from the narrative.
- **Discovered-but-ignored subdomains.** Any funnel subdomain found but not
  crawled goes in the follow-up register — never vanish it.
- **Competitor drift.** If competitor work is outweighing the subject's
  sections, cut it back to calibration lines — deep teardown is a different
  runbook.
- **Data-dump delivery.** A section with numbers but no "what this means"
  interpretation is unfinished; refuse to ship it.
