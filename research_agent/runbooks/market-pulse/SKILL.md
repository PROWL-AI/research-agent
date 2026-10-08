---
name: market-pulse
description: >-
  What is happening in a market or niche right now: search-trend direction,
  news velocity, jobs-as-demand proxy, social conversation, and event-driven
  demand. Output is a pulse report of rising vs declining THEMES (not
  keywords) with the evidence stack behind each. Use for market monitoring,
  trend spotting, timing questions ("is now a good moment to enter/launch"),
  and content planning.
version: "1.0"
inputs:
  - { name: market, type: "string", required: true, doc: "Market / niche / category, e.g. 'at-home red light therapy' or 'AI SDR tools'." }
  - { name: geo, type: "string", required: false, doc: "Geography for trend/jobs/news queries (ISO country or region). Default: worldwide — and say so." }
  - { name: window_months, type: "string", required: false, doc: "Pulse window in months. Default 12; hard minimum 3 — below that there is no pulse, only noise." }
tools:
  - google_trends
  - google_trends_autocomplete
  - serpapi_google_trends
  - google_news
  - google_news_light
  - google_news_portal
  - bing_news
  - dataforseo_serp_google_news
  - google_jobs
  - dataforseo_serp_google_jobs
  - reddit_search
  - youtube_search
  - youtube_channel
  - facebook_business_page
  - instagram_profile
  - tiktok_profile
  - dataforseo_biz_social_facebook
  - firecrawl_search
  - perplexity_responses
budget: { max_tool_calls: 40, max_usd: 1.50, max_minutes: 20 }
outputs: { report_template: market-pulse, formats: [markdown, html] }
---

# Market Pulse

**Goal:** a decision-ready read on what is moving in a market right now —
rising and declining THEMES with the evidence stack behind each (trends +
news velocity + jobs + social conversation + events), not a keyword list. The
report answers: is demand growing, what is driving it, what is fading, and
what does that mean for timing.

## Principles (read first)

- **Themes, not keywords.** A theme is a narrative ("GLP-1 driving
  muscle-loss concern") backed by ≥2 signal types. A single rising query is
  an anecdote until a second signal type confirms it.
- **Seasonality is stated, never mistaken for growth.** Every trend read
  compares the 12-month view against the 5-year view; a December spike in a
  gifting niche is a calendar fact, not a pulse signal.
- **A spike without a named driver is a curiosity, not a signal.** Every
  trend anomaly must be explained by a news item, launch, regulation, or
  platform change — or tagged UNEXPLAINED and kept out of the theme list.
- **Geography is part of the number.** A trend figure without its geo is
  invalid; worldwide vs US vs DE tell different stories. State geo for every
  figure.
- **Hiring is money entering.** Jobs into a niche are a harder demand proxy
  than search interest — companies pay salaries only for expected revenue.

## Sequence

1. **Scope** — Transform: from `market` derive 5-10 query terms: 3-5 category
   terms + adjacent/problem terms + any dominant brand terms. Set `geo`
   (default worldwide, stated) and `window_months` (default 12, refuse <3).
   Use `google_trends_autocomplete` on the market term to catch the phrasing
   real searchers use (on_error=skip).
2. **Search-trend baseline** — Fan-out `google_trends` per term (batched
   where the tool allows), 12-month AND 5-year views, geo set. Transform:
   per term — direction (rising/flat/declining), seasonality verdict
   (12-month shape vs 5-year shape), breakout queries. Cross-check the 2-3
   most important terms with `serpapi_google_trends` (on_error=skip);
   direction disagreement is a `[CONFLICT]`.
3. **Right-now scan** — Parallel: `google_trends` on 3-5 niche-adjacent
   breakout-candidate terms (short recent window — breakouts live there,
   not in the 12-month baseline) + `youtube_search` for video-first
   categories (on_error=skip). Transform: any niche-relevant breakout
   already accelerating — each must get a named driver in step 6 or be
   tagged UNEXPLAINED. (The dedicated trending endpoints — google_trending_now,
   google_trending_now_news, youtube_trends — are retired; do not plan them.)
4. **News velocity** — Parallel: `google_news` for the market term and each
   rising theme candidate + `google_news_light` as cheap volume re-check +
   `google_news_portal` for the industry section (on_error=skip) +
   `bing_news` as a second index (on_error=skip). Transform: cluster
   coverage into themes; per theme compute coverage velocity (this window vs
   prior window). Rising velocity = pulse signal; cite 2-3 anchor articles
   per theme with dates.
5. **Jobs as demand proxy** — Parallel: `google_jobs` on 2-4 category terms
   (role mix and employer mix) + `dataforseo_serp_google_jobs` as
   cross-check (on_error=skip). Transform: who is hiring into the niche,
   which functions (many AEs = GTM build-out; first-of-function = new bets),
   geo spread. Ghost-jobs caveat (~40% of postings may never be filled)
   applies to every jobs-based inference.
6. **Event-driven demand** — `dataforseo_serp_google_news` with event
   queries: "<market> conference <year>", "<market> regulation", "<market>
   launch" (on_error=skip). Transform: event list (conference/meetup density
   = budget flowing into the niche; Google Events was retired 2026-09-17, so
   density is measured via news coverage) and, for each launch / regulation /
   platform change, the demand signal it should move (search interest, jobs,
   or social volume) — checked against steps 2-5.
7. **Social conversation** — Parallel: `reddit_search` on the market term +
   top pain phrasings ("<market> worth it", "<market> vs", "best <market>")
   + `youtube_search` per dominant theme (on_error=skip). Transform: pain
   threads are unmet-need evidence — quote verbatim with subreddit and date;
   recurring recommendation patterns = demand the market already routes
   somewhere.
8. **Social presence stack (recipe 5.24)** — For the 2-3 brands/creators
   that dominate the niche conversation (skip for unbranded niches):
   `facebook_business_page` + `dataforseo_biz_social_facebook`
   (cross-validation) + `instagram_profile` + `tiktok_profile` +
   `youtube_channel` (all on_error=skip). Transform: platform presence
   matrix and where the audience actually engages; high followers with low
   engagement = stale audience. Pinterest/Reddit metrics via DataForSEO are
   deprecated (T365) — state that Pinterest has no current data source
   rather than planning around it.
9. **LLM context pass (secondary only)** — ONE `perplexity_responses`
   query: "what changed in <market> in the last <window> months"
   (on_error=skip). Use it to find drivers or themes the data steps missed —
   every claim it contributes must be re-confirmed against a data tool
   before entering the report. `firecrawl_search` may fill a specific gap
   the same way (on_error=skip).
10. **Synthesis** — Transform: theme board — each theme scored rising /
    plateau / declining with its evidence stack (trends direction, news
    velocity, jobs signal, social evidence, event driver). A theme needs ≥2
    signal types to be called rising or declining; single-signal themes go
    to a watch list. Order is the framework: baseline → velocity → drivers →
    synthesis — the verdict comes last and cites section evidence.

## Verification (hard rules)

- Key claims (is the market growing, is theme X rising): ≥2 independent
  signal types or tag ASSUMED. LLM output (Perplexity) is never a primary
  source — cross-check against a data tool.
- Trend direction disagreement between `google_trends` and
  `serpapi_google_trends`, or news-volume disagreement between `google_news`
  and `bing_news` >2x → `[CONFLICT]`, report both, never average silently.
- Every trend figure carries geo + window; every spike carries a named
  driver or the tag UNEXPLAINED.
- Error bands: trend indices are relative (0-100), never absolute volume —
  say so wherever a reader could mistake them for search volume.
- Ghost-jobs caveat on every hiring-based inference; engagement-rate caveats
  on every follower-count inference.

## Output instructions

Template `market-pulse`. Required sections:

1. **Executive summary** — market direction in one line, the top 2 rising
   themes and top 1 declining theme with their strongest evidence each, and
   the timing verdict (enter / wait / avoid) with confidence tag.
2. **Search-trend baseline** — per term: direction, 12-month vs 5-year
   shape, seasonality verdict, geo + window stated on every figure; relative
   index caveat.
3. **News velocity** — theme clusters with coverage counts per window,
   velocity direction, and 2-3 dated anchor articles per rising theme.
4. **Jobs signal** — who is hiring into the niche, role mix, geo spread,
   ghost-jobs caveat; verdict on money entering vs leaving.
5. **Event-driven demand** — launches / regulations / platform changes /
   conference density, each tied to the demand signal it should move and
   whether that signal actually moved.
6. **Social conversation** — pain threads with 3-5 verbatim quotes
   (subreddit + date), recurring unmet needs, recommendation patterns.
7. **Social presence matrix** — platform investment per dominant
   brand/creator, engagement quality flags, Pinterest-data deprecation note.
8. **Theme board** — rising / plateau / declining / watch-list, each theme
   with its evidence stack and confidence tag (VERIFIED/ASSUMED).
9. **Source log** — every figure with tool + retrieval date + geo; confidence
   ladder; `[CONFLICT]` register; refresh recommendation (monthly for fast
   niches, quarterly otherwise).

## Guards (failure modes to refuse)

- **Spike-chasing:** a breakout query with no named driver found in steps
  4-6 goes to the watch list tagged UNEXPLAINED — never presented as a
  rising theme.
- **Short-window reads:** `window_months` < 3 → refuse the pulse framing;
  say a <3-month window can only produce a news recap, and offer that
  instead.
- **Seasonality-as-growth:** if the 5-year view shows the same peak every
  year, the theme is seasonal — do not call it rising; say when the next
  seasonal window opens instead.
- **Keyword-list reporting:** a report that lists rising queries without
  clustering them into evidenced themes is surface-level — say so in the
  summary if social/news/jobs steps produced nothing.
- **Silent worldwide default:** if `geo` was not given, every figure is
  worldwide and the report says so once, prominently — never imply a local
  read from worldwide data.
- **Stale-audience social proof:** follower counts without engagement or
  posting-recency context are not evidence of demand — exclude them from the
  theme evidence stack.
