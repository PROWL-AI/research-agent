---
name: subscription-app-audit
description: >-
  Audit of a mobile subscription app (or its competitive set, up to 4 named
  rivals): app-store intelligence, ASO keyword gaps, paywall/offer teardown,
  review mining for churn triggers, benchmarked against RevenueCat/Adapty
  quartiles with full qualifiers. Output is a funnel-leak ranking ordered by
  recoverable value. Use for app audits, paywall or ASO questions, and
  subscription-economics reviews.
version: "1.0"
inputs:
  - { name: app, type: "string", required: true, doc: "App name, App Store / Google Play URL, or bundle id (com.x.y)." }
  - { name: competitors, type: "string", required: false, doc: "Comma-separated competitor app names or store URLs (max 4). If omitted, discovered in step 3." }
  - { name: category, type: "string", required: false, doc: "App category (fitness, language learning, ...) — required for valid quartile benchmarking." }
tools:
  - resolve_app_store_ids
  - apple_app_store
  - google_play_store
  - apple_product
  - google_play_product
  - firecrawl_scrape_mobile_app
  - firecrawl_search
  - dataforseo_labs_apple_app_competitors
  - dataforseo_labs_google_app_competitors
  - dataforseo_labs_apple_keywords_for_app
  - dataforseo_labs_google_keywords_for_app
  - dataforseo_labs_apple_app_intersection
  - dataforseo_labs_google_app_intersection
  - dataforseo_labs_apple_bulk_app_metrics
  - dataforseo_labs_google_bulk_app_metrics
  - apple_product_reviews
  - google_play_product_reviews
  - gemini_reviews_report
  - reddit_search
  - meta_ad_library
  - tiktok_ads_library
  - google_ads_advertiser_info
  - google_trends
  - google_news
budget: { max_tool_calls: 50, max_usd: 2.00, max_minutes: 25 }
outputs: { report_template: subscription-app-audit, formats: [markdown, html] }
---

# Subscription App Audit

**Goal:** find where a subscription app leaks revenue and rank the leaks by
recoverable value — not a store-listing summary. Store intelligence and ASO
gaps quantify the top of funnel; the paywall teardown and review mining expose
the trial→paid and retention leaks; every number is benchmarked within its
quartile and category. Depth on the subject app beats breadth across rivals.

## Principles (read first)

- **Downloads ≠ revenue.** The economics live in trial conversion and
  retention curves that are invisible from the store page. Say explicitly
  what is NOT observable and tag it ASSUMED — never present store data as
  business health.
- **Benchmarks are meaningless without qualifiers.** Trial→paid median is
  10.7% for hard paywalls vs 2.1% freemium (RevenueCat 2025, Day-35); trials
  of 17-32d convert at 42.5% median vs 25.5% for <4d. Any benchmark quote
  without paywall type + trial length + category + quartile is a guard
  violation.
- **Compare within quartile, not against the median app.** The market is
  polarized (top quartile +80% MRR YoY, bottom −33%); median benchmarks
  mislead in both directions.
- **The first-session paywall is the highest-leverage surface** (>80% of
  trial starts happen on install day), but the cohort lens applies: up to
  50% of conversions happen after formal trial end — never judge a funnel on
  a snapshot.
- **Recoverable value ranks the leaks.** Involuntary churn (31% of Google
  Play / 14% of App Store cancels) is often the most recoverable revenue;
  ~72% of annual subs cancel within year one, 35% of annual cancels in
  month one. A visible leak with low recovery odds ranks below an invisible
  one with high odds.

## Sequence

1. **Scope** — Transform: classify `app` as store URL (extract the Apple
   numeric id / Play package name directly), bundle id, or brand name. Cap
   `competitors` at 4. Apple ids are numeric store ids; Play ids are package
   names — a platform-blind id fails with `40501 Invalid Field`.
2. **Store ID resolution** (skip for ids extracted in step 1) —
   `resolve_app_store_ids` with brand_name + `alternate_queries` (full
   marketing name, "{brand} {category} app") — Apple often needs the longer
   name. Fallback (on_error=skip): `apple_app_store` + `google_play_store`
   search; last resort `firecrawl_search` for the canonical
   apps.apple.com / play.google.com URLs. Validate with `apple_product` /
   `google_play_product`.
3. **Competitor set** (skip if `competitors` given) — Parallel:
   `dataforseo_labs_apple_app_competitors` +
   `dataforseo_labs_google_app_competitors` for the subject app
   (on_error=skip; Labs app endpoints are US-locale only — note it).
   Transform: top 4 by keyword overlap, resolve their store ids via step 2.
4. **App metrics baseline** — Fan-out per app (subject + rivals, both
   platforms where present): `firecrawl_scrape_mobile_app` — download and
   revenue estimates, ratings, version history, publisher, IAP price points
   (on_error=skip). One batched
   `dataforseo_labs_apple_bulk_app_metrics` +
   `dataforseo_labs_google_bulk_app_metrics` across all ids for the
   portfolio benchmark (keyword counts, impressions, rank distribution).
   Every estimate carries a 30-50% error band and a VERIFIED/ASSUMED tag.
5. **ASO baseline** — Fan-out per app:
   `dataforseo_labs_apple_keywords_for_app` +
   `dataforseo_labs_google_keywords_for_app` (on_error=skip). Transform:
   per-app visibility baseline (ranked keyword count, top terms, brand vs
   generic split).
6. **ASO gap matrix** — `dataforseo_labs_apple_app_intersection` +
   `dataforseo_labs_google_app_intersection` subject vs top-3 (on_error=skip).
   NOTE: `app_ids` is a position-keyed dict
   (`{"1": "686449807", "2": "382617920"}`), not an array. Transform:
   keywords rivals rank for that the subject doesn't, weighted by impression
   share — name the top-10 actionable gaps.
7. **Paywall & offer teardown** — Transform: from step 4 scrapes and
   `apple_product` / `google_play_product` IAP metadata, extract per app the
   teardown checklist — paywall type (hard / freemium / soft), trial length,
   price points, plan mix (weekly / monthly / annual anchor), discounts and
   countdowns. Placement (onboarding / post-value / contextual) is NOT
   observable from the store page: infer from reviews in step 8 only, and
   tag the whole placement column ASSUMED. Never invent a price that is not
   in the IAP list.
8. **Review mining** — Fan-out per app: `apple_product_reviews` +
   `google_play_product_reviews` (recent-first, up to 200 per page, 1-2
   pages per store; on_error=skip when an id is missing). Consolidate ALL
   sources into one `gemini_reviews_report` call. Transform: billing/refund
   and "charged after cancel" complaints (= involuntary-churn and billing-UX
   proxies), trial-cancellation complaints (= paywall placement signal),
   praised value moments (= where the paywall should sit), feature gaps,
   review velocity as a growth proxy.
9. **Community voice** — Parallel per brand: `reddit_search`
   "{app} worth it", "{app} charged / refund / cancel" (on_error=skip).
   Transform: quoted-price sentiment and cancellation-friction stories that
   corroborate or contradict step 8.
10. **Paid UA health signal** — Parallel per brand: `meta_ad_library` +
    `tiktok_ads_library` + `google_ads_advertiser_info` (on_error=skip).
    Transform: active creative count, longest-running creative, platform mix
    per app. Creative sustained 60-90+ days is almost certainly profitable —
    UA at scale implies LTV:CAC ≥ 3:1 is being met; say so explicitly when
    the evidence shows it, and say when it does not.
11. **Demand trend** — `google_trends` brand terms, 12-month, one batched
    call across the set + `google_news` for launches, price changes, outages
    (on_error=skip).
12. **Benchmark placement** — Transform: assign the subject (and each rival,
    if data allows) a quartile position from steps 4-5 (revenue estimate,
    keyword footprint, review velocity) within `category`. Then and only
    then apply the conversion/retention doctrine — with paywall type and
    trial length from step 7 attached to every figure. No `category` input →
    downgrade all benchmark claims to directional and tag ASSUMED.
13. **Funnel-leak ranking** — Transform: for each leak (ASO visibility gap,
    first-session paywall miss, trial-length mismatch, plan-mix/anchor
    weakness, involuntary churn / billing retry, month-one annual churn,
    review-driven store rating drag) estimate recoverable value = leak size
    × recovery probability × price point, with an explicit error band and
    VERIFIED/ASSUMED tag. Rank by recoverable value, never by visibility.

## Verification (hard rules)

- Key numbers (downloads, revenue, ratings velocity): ≥2 independent sources
  (e.g. `firecrawl_scrape_mobile_app` vs Labs bulk metrics) or tag ASSUMED.
  Two sources disagreeing >2x → report the range as `[CONFLICT]`, never
  average silently.
- LLM output (`gemini_reviews_report`, Gemini in general) is synthesis, never
  a primary source — every quantitative claim in it must trace to a data tool.
- Every benchmark quote carries paywall type + trial length + category +
  quartile + cohort window (e.g. "Day-35"). Missing any qualifier → drop the
  number or tag it illustrative-only.
- Store-page observability limit: trial→paid rate, retention curves, and
  cohort revenue are NOT in any tool here — mark every such figure ASSUMED
  and name what instrumentation (e.g. RevenueCat/Adapty dashboard) would
  verify it.
- US-locale caveat on all Labs app data; flag when the subject's market is
  elsewhere.

## Output instructions

Template `subscription-app-audit`. Required sections:

1. **Executive summary** — top-3 leaks by recoverable value, one line each,
   with the estimate and its error band.
2. **Store intelligence & quartile placement** — per app: downloads/revenue
   estimates with error bands, ratings, version cadence, review velocity;
   quartile verdict within category.
3. **Paywall & offer teardown** — checklist table per app (type, trial
   length, price points, plan mix, discounts); placement column tagged
   ASSUMED with the review evidence behind each inference.
4. **ASO gap matrix** — visibility baseline per app + top-10 actionable
   keyword gaps weighted by impression share.
5. **Review mining — churn triggers** — billing/refund complaint rates,
   trial-cancellation complaints, praised value moments, 3-5 verbatim quotes
   with store and date.
6. **Paid UA & health signals** — per app: creative longevity, platform mix,
   LTV:CAC ≥ 3:1 inference with confidence tag.
7. **Benchmarked economics** — doctrine-qualified comparison (hard-paywall
   vs freemium trial→paid, trial-length conversion curve, involuntary-churn
   share, annual month-one churn) with the subject's assumed position and
   what data would verify it.
8. **Funnel-leak ranking** — the deliverable: each leak with recoverable
   value range, recovery probability, evidence, and the fix direction.
9. **Source log** — every figure with tool + retrieval date; confidence
   ladder (VERIFIED / ASSUMED / illustrative); `[CONFLICT]` register;
   refresh recommendation (monthly for ASO, quarterly for economics).

## Guards (failure modes to refuse)

- **Downloads-as-success:** if the only obtainable numbers are store
  download/rating counts, say the audit is surface-level in the summary —
  do not present it as subscription economics.
- **Unqualified conversion quotes:** any trial→paid or churn figure without
  paywall type, trial length, category, and cohort window is deleted, not
  footnoted.
- **Median-app benchmarking:** refuse to compare a top- or bottom-quartile
  app against market medians; restate within its quartile or tag directional.
- **Snapshot verdicts:** if no velocity data (trends, review velocity,
  version history, ad longevity) was obtainable, tag every trajectory claim
  ASSUMED and say what a refresh should fetch.
- **Invented paywall facts:** trial length, prices, or placement not present
  in IAP metadata or reviews are never guessed — mark "not observable from
  store data" and move on.
- **Leaks ranked by visibility:** a loud complaint (e.g. price) must not
  outrank a quiet, higher-recovery leak (e.g. billing retry) — the ranking
  must show the recoverable-value math for each row.
