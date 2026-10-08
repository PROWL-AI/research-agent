---
name: growth-signals
description: >-
  Answers one question about a company or product: is it actually growing?
  Corroborates a trajectory verdict across the six independence classes of
  public growth signals — funding/financial, hiring, marketing/ad spend,
  product cadence, traffic/SEO trajectory, social/news momentum — inside a
  180-day corroboration window, with mixed evidence reported as mixed.
  Output is a per-class evidence table plus an overall verdict (compounding /
  steady / stalling / retreating) with confidence. Use for growth assessment,
  investment screening, partner or competitor diligence.
version: "1.0"
inputs:
  - { name: subject, type: "string", required: true, doc: "Company name or domain. Domains are used as-is; names are resolved to a domain in step 1." }
  - { name: market, type: "string", required: false, doc: "Product category / niche. Drives trend queries and the seasonal-category flag." }
  - { name: window_months, type: "string", required: false, doc: "Trend lookback in months. Default 12; never below 12 for any trend claim." }
tools:
  - find_subdomains
  - firecrawl_map_domain
  - firecrawl_scrape_page_markdown
  - dataforseo_labs_historical_bulk_traffic_estimation
  - dataforseo_labs_bulk_traffic_estimation
  - dataforseo_labs_domain_rank_overview
  - dataforseo_bl_timeseries_summary
  - dataforseo_domain_technologies
  - spyfu_get_domain_stats
  - spyfu_get_ad_history
  - spyfu_get_paid_search
  - google_trends
  - google_jobs
  - dataforseo_serp_google_jobs
  - meta_ad_library
  - meta_ad_library_page_info
  - linkedin_ad_library
  - tiktok_ads_library
  - google_ads_advertiser_info
  - foreplay_discovery_ads
  - foreplay_brand_analytics
  - youtube_channel
  - youtube_channel_videos
  - youtube_search
  - google_news
  - google_news_portal
  - bing_news
  - facebook_business_page
  - dataforseo_biz_social_facebook
  - instagram_profile
  - tiktok_profile
  - reddit_search
  - scrape_review_platforms
  - dataforseo_biz_trustpilot_search
budget: { max_tool_calls: 50, max_usd: 2.00, max_minutes: 25 }
outputs: { report_template: growth-signals, formats: [markdown, html] }
---

# Growth Signals — Trajectory Verdict

**Goal:** a defensible answer to "is this company/product actually growing?"
Not a pile of metrics — a trajectory verdict (compounding / steady / stalling
/ retreating) built from at least three independent signal classes, each
class with its own direction, strength, time window, and source. Mixed
evidence stays mixed: conflicting classes are named, never averaged away.

## Principles (read first)

- **Six independence classes, three minimum — deliberately stricter than the
  source guideline's two.** Do not "harmonize" this back down: one strong
  class plus one weak one is exactly the false-positive this gate exists to
  kill. Signals inside one class share
  a root cause and do not corroborate each other. A verdict needs agreeing
  signals from ≥3 of: (1) funding/financial, (2) hiring, (3) marketing/ad
  spend, (4) product/website change, (5) traffic/SEO trajectory, (6)
  social/news momentum. One class — traffic alone, hiring alone — is never a
  verdict.
- **The 180-day corroboration window.** Signals corroborate only when they
  overlap in time. A two-year-old funding round plus last month's hiring
  spike is not a growth story; stale signals are background, not evidence.
- **Hiring is corroborating, never primary.** ~40% of job postings may never
  be filled (ghost jobs). Weight postings by role specificity, salary
  disclosure, and repost frequency; discount evergreen reposts. A
  first-of-function hire (first PMM, first data engineer, first enterprise
  AE, first country manager) out-signals a dozen backfills — call these out.
- **Sustained ad spend is a profitability proxy.** 6+ months of continuous
  spend is almost certainly funded by working unit economics; retreating
  spend plus a hiring freeze is a compounding negative. Ad count is not ad
  dollars — say trajectory, not budget.
- **Velocity beats level.** Review-velocity trend matters more than rating
  level; changelog/release cadence is a real signal — fetch it, don't infer
  it. Every trend covers 12 months minimum, and seasonal categories are
  flagged before any up/down call.

## Sequence

1. **Scope** — Transform: normalize `subject` (strip scheme/path/www if a
   domain; if a company name, resolve to the primary domain via
   `firecrawl_map_domain` on the best-guess domain or `google_news` brand
   coverage). Set the trend lookback from `window_months` (default 12;
   floor at 12). If `market` is given, decide now whether the category is
   seasonal (tax, travel, gifting, back-to-school, fitness-January) and
   record the flag — it gates every trend interpretation below.
2. **Surface map** — Parallel: `find_subdomains` + `firecrawl_map_domain`
   (on_error=skip). Transform: product surface inventory (app., docs.,
   blog., geo subdomains) and the brand terms to feed trend and news
   queries. New subdomains/geo sites found later count as class-4 evidence.
3. **Class 5 — traffic & SEO trajectory** — Parallel:
   `dataforseo_labs_historical_bulk_traffic_estimation` (12-month series) +
   `dataforseo_labs_domain_rank_overview` + `spyfu_get_domain_stats` +
   `dataforseo_bl_timeseries_summary` (link velocity) + `google_trends`
   (brand term + 1-2 category terms from `market`, 12-month). Then
   `dataforseo_labs_bulk_traffic_estimation` as the current-snapshot
   cross-check. Transform: direction and slope per metric; two sources
   disagreeing >2x on traffic is a `[CONFLICT]` — report the range, never
   average silently.
4. **Class 2 — hiring** — Parallel: `google_jobs` ("{subject}") +
   `dataforseo_serp_google_jobs` (cross-check, on_error=skip). Transform:
   posting velocity, role mix (Sales:CS ratio rising = acquisition push),
   geo clusters (many roles in one geo = market entry within ~2 quarters),
   and first-of-function hires called out by name. Apply the ghost-jobs
   discount: evergreen reposts and unspecific bulk roles count weak.
5. **Class 3 — ad spend trajectory** — Parallel: `meta_ad_library` +
   `meta_ad_library_page_info` + `linkedin_ad_library` +
   `tiktok_ads_library` + `google_ads_advertiser_info` +
   `foreplay_discovery_ads` (on_error=skip). Then `spyfu_get_ad_history` +
   `spyfu_get_paid_search` for search-spend history, and
   `foreplay_brand_analytics` on the brand (on_error=skip). Transform:
   active creative count, longest-running creative (long-runners = proven
   winners), creative bursts (many short-lived variants = message testing,
   positioning in flux), platform mix, and the spend-trajectory call:
   scaling / steady / retreating, with the 6-month sustained-spend rule
   stated explicitly when met.
6. **Class 4 — product & website cadence** — Fan-out
   `firecrawl_scrape_page_markdown` on the changelog/release-notes, blog,
   and pricing pages discovered in step 2 (on_error=skip; if no changelog
   exists, say so — absence is itself a cadence data point). Parallel:
   `youtube_channel` + `youtube_channel_videos` for publish cadence
   (on_error=skip) + `dataforseo_domain_technologies` for stack changes
   (on_error=skip). Transform: releases per month trend, new pricing tiers
   or packaging changes, new surface since step 2's baseline.
7. **Class 1 — funding & financial** — Parallel: `google_news` ("{subject}
   funding OR raises OR revenue OR pricing") + `bing_news` (cross-check) +
   `google_news_portal` (on_error=skip). Transform: rounds with dates,
   pricing increases, public revenue statements, layoffs. Every item gets a
   date — anything older than 180 days is background, not corroboration.
   Silence here is not decline: private companies often raise quietly.
8. **Class 6 — social & news momentum** — Parallel:
   `facebook_business_page` + `dataforseo_biz_social_facebook`
   (cross-validation pair) + `instagram_profile` + `tiktok_profile` +
   `youtube_search` (brand, recent) + `reddit_search` (brand mentions,
   on_error=skip). Transform: follower/engagement direction per platform
   (high followers + dead engagement = stale audience, discount it),
   community-activity trend. Pinterest data is unavailable (upstream
   deprecated) — note the gap rather than planning around it.
9. **Review velocity** — Parallel: `scrape_review_platforms`
   (Trustpilot/G2/Capterra composite) + `dataforseo_biz_trustpilot_search`
   (on_error=skip). Transform: reviews per month over the window — rising
   velocity = growing user base even if the rating is flat; the rating
   level itself is context, not a growth signal. Theme split (praise /
   feature-requests / bugs) feeds the report's quality-debt note.
10. **Synthesis** — Transform: build the per-class table (class, signal,
    direction, strength, window, source). Check the verdict gates: ≥3
    independent classes with signals inside the same 180-day window, all
    trends ≥12 months, seasonal flag applied. Then the verdict:
    **compounding** (3+ classes rising, none retreating), **steady**
    (rising classes balanced by flat ones), **stalling** (mostly flat with
    one retreating), **retreating** (2+ classes retreating — e.g., ad spend
    pulled plus hiring frozen). If classes conflict, the verdict is MIXED
    and the conflicting classes are named with what each implies — never
    blended into a fake average. Assign confidence (high = 4+ agreeing
    classes; medium = 3; low = verdict withheld, evidence stated).

## Verification (hard rules)

- No verdict from fewer than 3 independent classes inside the 180-day
  window. Fewer → report per-class findings and withhold the verdict.
- Key numbers (traffic, review counts, follower counts): ≥2 independent
  sources or tag ASSUMED, with the error band (traffic estimates: 30-50%,
  >70% under ~100k monthly visits).
- Traffic sources disagreeing >2x, or Facebook metrics disagreeing between
  SearchAPI and DataForSEO → `[CONFLICT]` register; report the range.
- Hiring-based inferences always carry the ghost-jobs caveat; hiring alone
  never carries a verdict.
- Ad findings state creative count and longevity — never inferred dollar
  spend unless a source provides it, and then with the source named.
- LLM output is never a primary source for any number in this report.
- Every trend claim covers ≥12 months; seasonal categories are compared
  year-over-year, not quarter-over-quarter.

## Output instructions

Template `growth-signals`. Required sections:

1. **Verdict** — compounding / steady / stalling / retreating / MIXED, with
   confidence, the corroborating classes named, and the 180-day window
   stated. If withheld, say why and what would resolve it.
2. **Per-class evidence table** — one row per class: signal, direction,
   strength (strong/moderate/weak), time window, source tools.
3. **Traffic & SEO trajectory** — 12-month series with error bands,
   cross-source agreement, brand-trend direction.
4. **Hiring** — velocity, role mix, first-of-function hires called out,
   geo-entry signals, ghost-jobs discount applied.
5. **Ad spend trajectory** — platforms, creative longevity vs bursts,
   scaling/steady/retreating call, sustained-spend profitability inference
   with confidence tag.
6. **Product cadence** — release/changelog rhythm, pricing/packaging
   changes, new surface, YouTube publish cadence.
7. **Funding & news** — dated events inside vs outside the 180-day window;
   silence explicitly noted as non-evidence.
8. **Social & reviews** — platform momentum table, review-velocity trend,
   quality-debt themes.
9. **Mixed-evidence register** — every class disagreement, what each side
   implies (pivot, channel shift, layoff-then-refocus), unresolved.
10. **Source log** — every figure with tool + retrieval date; confidence
    ladder (VERIFIED / ASSUMED / [CONFLICT]); full `[CONFLICT]` register;
    refresh recommendation (quarterly, or post-funding-event).

## Guards (failure modes to refuse)

- **One-class verdict.** Traffic-only or hiring-only growth claims are
  refused on sight — corroborate across ≥3 classes or withhold the verdict.
- **Short-window trends.** Any up/down call on <12 months of data is
  rejected; for seasonal categories, require year-over-year comparison.
- **Blended averages.** Never average conflicting classes into "moderate
  growth" — conflicting signals are a finding, report both sides.
- **Hiring-primary verdict.** Raw posting counts without the ghost-jobs
  discount (~40% may never be filled) and role-quality weighting are not
  evidence of growth.
- **Ad-count-as-dollars.** Creative counts describe activity and
  trajectory, not budget; never convert them to spend figures.
- **Silence-as-decline.** No funding news, no changelog, or no social
  presence is an absence of signal — tag the class "no data", do not score
  it as negative.
