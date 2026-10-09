---
name: ads-creative-research
description: >-
  Cross-platform ad and creative intelligence for a set of 1-5 brands or
  competitors: Meta/LinkedIn/TikTok/Google ad libraries plus Foreplay, hook
  classification against the 10 canonical hook patterns, longevity-weighted
  winner identification, and cross-platform repurposing analysis. Output is
  one-page, testable creative briefs (bets, not deliverables) with reference
  ad library IDs. Use when the user asks about competitors' ads, creative
  strategy, hook patterns, or wants ad briefs to test.
version: "1.0"
inputs:
  - { name: brands, type: "list[domain]", required: true, max: 5, doc: "Brand names or domains of the brand/competitor set (max 5). Names are resolved to advertiser IDs in step 3." }
  - { name: market, type: "string", required: false, doc: "Product category / niche, used for trend-scan and adjacent-advertiser queries." }
  - { name: geo, type: "string", required: false, doc: "Country/region code for the ad-pull window (e.g. US, DE). Defaults to the advertiser's primary market." }
tools:
  - google_trends
  - youtube_search
  - google_videos_light
  - google_shorts
  - foreplay_discovery_ads
  - foreplay_discovery_brands
  - foreplay_get_brands_by_domain
  - foreplay_get_ads_by_brand_ids
  - foreplay_get_ads_by_page_id
  - foreplay_ad_details
  - foreplay_brand_analytics
  - meta_ad_library
  - meta_ad_library_ad_details
  - meta_ad_library_page_search
  - meta_ad_library_page_info
  - linkedin_ad_library
  - tiktok_ads_library
  - tiktok_ads_library_advertiser_search
  - google_ads_advertiser_info
  - google_ads_transparency_advertiser_search
  - spyfu_get_ad_history
  - spyfu_get_term_ad_history_with_stats
  - spyfu_get_paid_search
  - spyfu_get_ppc_competitors
  - google_lens
  - crawl_funnel_path
  - llm_query_perplexity
budget: { max_tool_calls: 60, max_usd: 2.00, max_minutes: 25 }
outputs: { report_template: ads-creative-brief, formats: [markdown, html] }
---

# Ads Creative Research

**Goal:** evidence-backed creative intelligence, not a swipe file. For a set
of 1-5 brands: which ads have been running long enough to be profitable, which
hook PATTERNS the market rewards, how creative differs across platforms — and
out of that, one-page creative briefs that describe a testable bet. Depth on
2 direct competitors + 1 adjacent advertiser beats a shallow scan of ten.

## Principles (read first)

- **Longevity is the quality signal.** An ad running 60-90+ days is a proven
  winner, likely profitable (creative-level) — advertisers kill losers fast.
  Weight every finding
  by `running_days` / start date and by the advertiser's active-vs-paused
  ratio. An ACTIVE ad is not a WINNING ad; only duration earns that claim.
- **Classify hooks as patterns, never as examples.** Every extracted hook
  maps to one of the 10 canonical patterns: Contrarian, Pattern Interrupt,
  Specific Curiosity Gap, Problem-Solution 3-Second, Raw UGC, POV, ASMR,
  Creator Testimonial, Trend Remix, Before-After. An ad saved without a
  pattern label is noise.
- **Cross-platform delta changes what you can learn.** The same creative on
  Meta and TikTok means repurposing budget; TikTok-native creative means
  different production economics. Note which case you are looking at before
  drawing conclusions.
- **Only flagged-as-ad creatives count.** Scrolling a feed is not research.
  Every creative in the report comes from an ad library or a tracked-ads
  provider, with its library ID.
- **The brief is a bet, not a deliverable.** Campaign goal + KPI + funnel
  stage, one single angle, 2-3 hook variants, a named success metric. If it
  cannot be falsified by a test, it is not a brief.
- **Ad-library semantics (do not plan around these).** Meta Ad Library
  returns ACTIVE ads only — it has no date-window parameter and no paused
  counts; filter recency post-factum from each ad's start date, never by
  planning a window parameter. Spend/impression figures exist only for
  political/issue ads — never expect them for commercial pages. Paused
  counts and active-vs-paused ratios come from Foreplay only; tag them
  single-source. Longevity from any active-only library is survivorship-
  biased (killed ads are invisible) — say "among currently active ads".

## Sequence

1. **Scope** — Transform: normalize brands (strip scheme/www/path from
   domains, keep brand names as-is), cap at 5, deduplicate. Select the
   deep-dive set: 2 direct competitors + 1 adjacent advertiser (adjacent =
   same audience, different product — from `market` if given). Default
   `geo` to each advertiser's primary market if omitted.
2. **Trend scan** — Parallel: `google_trends` (brand + category terms,
   12-month, geo-scoped, batch up to 5 terms per call) + `youtube_search`
   and `google_shorts` for the category's current creative formats +
   `google_videos_light` for brand video presence (on_error=skip).
   Transform: 3-5 rising themes worth testing hooks against.
3. **Advertiser discovery** — Parallel per brand: `foreplay_get_brands_by_domain`
   (fallback on failure: `foreplay_discovery_brands` fuzzy name search, then
   `foreplay_discovery_ads` with the brand/domain as query) +
   `meta_ad_library_page_search` + `tiktok_ads_library_advertiser_search` +
   `google_ads_transparency_advertiser_search` + `google_ads_advertiser_info`
   (on_error=skip). Transform: one advertiser-ID table — brand × platform ×
   IDs (Foreplay brand_id, Meta page_id, TikTok advertiser_id).
4. **Top-ads pull** — Fan-out per brand (recency is filtered POST-FACTUM
   from each ad's start date — no library takes a date-window parameter),
   geo filter where the library supports one:
   `meta_ad_library` + `linkedin_ad_library` (B2B especially) +
   `tiktok_ads_library` + `foreplay_get_ads_by_brand_ids` (one bulk call when
   ≥3 Foreplay brand IDs exist; otherwise `foreplay_discovery_ads` per brand;
   `foreplay_get_ads_by_page_id` when only the Meta page is known)
   (on_error=skip). An empty library is a valid finding, not an error —
   record which channels each brand skips.
5. **Advertiser deep-dive** (2 direct + 1 adjacent only) — Fan-out per
   deep-dive brand: `foreplay_brand_analytics` (creative cadence, spend
   trajectory, format distribution) + `meta_ad_library_page_info` (likes,
   verification — spend/impressions exist for political ads only, never
   expect them here) + `spyfu_get_ad_history` per domain,
   past_n_months=12 + `spyfu_get_paid_search` + `spyfu_get_ppc_competitors`
   for the target brand (on_error=skip). Transform: per advertiser — active
   ad count, paused count and active-vs-paused ratio FROM FOREPLAY ONLY
   (Meta/LinkedIn/TikTok libraries are active-only; tag the ratio
   single-source), cadence, platform mix.
6. **Hook extraction** — Fan-out `foreplay_ad_details` on the top 3-5 ads
   per deep-dive brand (hooks, transcription, emotional drivers — never skip
   for top ads) + `meta_ad_library_ad_details` on the top Meta creatives
   (variations, regions, targeting) (on_error=skip). Transform: classify
   every hook into one of the 10 canonical patterns; note the first-3-second
   device per video ad; tag format (1:1 / 4:5 / 9:16, static vs video).
7. **Longevity weighting** — Transform: sort all creatives by
   `running_days` / library start date. Flag 60-90+ day runners explicitly
   as proven signals. Cross-check Foreplay `running_days` against Meta
   library start dates for the top 5 — disagreement is a `[CONFLICT]`.
   Restate: an ACTIVE ad is not a WINNING ad; only longevity + the
   advertiser's keep/kill ratio support a winner claim.
8. **Cross-platform verification** — Transform: per deep-dive brand, mark
   each creative as repurposed (same asset on Meta + TikTok) or
   platform-native, using asset fingerprints from steps 4 and 6; use
   `google_lens` on 1-2 hero creatives to confirm reuse (on_error=skip).
   `spyfu_get_term_ad_history_with_stats` for 3-5 core keywords to build the
   12-month messaging-evolution timeline (on_error=skip). Optional
   tie-breaker on a contested claim: ONE `llm_query_perplexity` query — a
   model cross-check, never a data source.
9. **Funnel & offer extraction** — Transform: landing URLs from top ads →
   fan-out `crawl_funnel_path` on the top 2-3 (on_error=skip). Extract the
   offer structure, proof points, and the exact claims each ad makes — this
   feeds the can-claim / can't-claim line in the briefs.
10. **Brief synthesis** — Transform: one one-page brief per deep-dive brand
    (or per distinct angle). Every brief names: campaign goal + KPI + funnel
    stage; audience (what they already believe, what stops their scroll);
    SINGLE angle in one sentence; 2-3 hook variants tied to canonical
    patterns; offer & proof (claims you can and can't make); reference ads
    with library IDs; format spec (1:1 / 4:5 / 9:16); success metric. A
    brief without a falsifiable success metric is rejected and rewritten.

## Verification (hard rules)

- Winner claims need ≥2 independent sources (e.g. Foreplay `running_days` +
  Meta library start date) or are tagged ASSUMED. LLM output
  (`llm_query_perplexity`) is never a primary source — it decides which tool
  check to run next, nothing more.
- Spend figures: ranges with named assumptions and error bands only —
  "no authoritative public evidence" beats a confident point value. A
  verbatim quoted number with attribution is allowed.
- `[CONFLICT]` protocol: disagreeing durations/start dates get at most ONE
  targeted recheck; if unresolved, surface the pair — never average, never
  silently pick a side.
- VERIFIED = confirmed against a second source; everything single-sourced or
  inferred is ASSUMED. A section that is majority-ASSUMED says so in its
  heading.
- Platform absence is a finding: record it, do not treat it as a tool error
  or backfill it with guesses.

## Output instructions

Template `ads-creative-brief`. Required sections:

1. **Executive summary** — the market's creative climate in 3 lines: the
   dominant hook patterns, the single clearest proven winner (with library
   ID), the biggest untested gap.
2. **Advertiser landscape** — per brand: platforms present/absent, active ad
   count, active-vs-paused ratio, creative cadence, spend-trajectory verdict
   (scaling / steady / retreating) with confidence tag.
3. **Hook pattern map** — the 10 canonical patterns × brands matrix; each
   cell cites reference ad library IDs, not descriptions from memory.
4. **Proven winners** — creatives with 60-90+ days runtime, longevity-weighted,
   each with library ID, pattern label, format, and funnel stage.
5. **Cross-platform delta** — repurposed vs platform-native per brand, and
   what each implies about production economics and what can be learned.
6. **Messaging evolution** — 12-month ad-copy timeline per deep-dive brand;
   dramatic pivots flagged as strategic signals.
7. **Creative briefs** — one page each, bet-shaped: goal + KPI + funnel
   stage, audience beliefs & scroll-stoppers, single angle, 2-3 hook
   variants, offer & proof (can/can't claims), reference ads with library
   IDs, format spec, success metric.
8. **Source log** — every claim with tool + retrieval date; confidence
   ladder (High/Medium/Low); `[CONFLICT]` register; refresh recommendation.

## Guards (failure modes to refuse)

- **Feed-scrolling as research.** If a creative did not come from an ad
  library or tracked-ads provider with an ID, it does not enter the report.
- **Swipe file without variable structure.** A dump of saved ads with no
  pattern label, longevity, and platform per item produces copies, not
  hypotheses — restructure before writing anything.
- **ACTIVE sold as WINNING.** Recency or presence in the library is not
  evidence of performance; refuse winner language without duration data.
- **Session with no artifact.** Every run ends with the written report,
  even if the honest output is "evidence insufficient — here is what a
  follow-up must fetch."
- **Breadth over depth.** More than 5 brands, or deep-dives on more than
  2 direct + 1 adjacent — force a selection and state the criterion.
- **Copying the winner.** A brief that replicates a reference ad instead of
  stating a differentiated bet is a failure — rewrite it with a distinct
  angle.
