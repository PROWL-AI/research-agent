---
name: market-sizing
description: >-
  Investor-grade TAM/SAM/SOM for a market or product offer: mandatory
  dual-method sizing (bottom-up customer-count x ARPA vs top-down industry
  reports) with the 15% divergence rule, sensitivity analysis over every
  ratio, scenario fan, and a behavioral demand-validation layer (search
  volume, community pain, incumbent share anchors). Use when asked for
  market size, opportunity assessment, or "how big is the market for X".
version: "1.0"
inputs:
  - { name: market, type: "string", required: true, doc: "Market / product category to size (e.g. 'field-service scheduling software')." }
  - { name: product, type: "string", required: false, doc: "The specific product/offer being sized; sharpens the ICP and SOM motion." }
  - { name: geo, type: "string", required: false, doc: "Geography scope (e.g. 'US', 'DACH'). Default: global with regional split." }
  - { name: acv, type: "string", required: false, doc: "Known/assumed annual contract value or customer spend; overrides mined ARPA." }
tools:
  - perplexity_responses
  - perplexity_chat
  - llm_query_perplexity
  - llm_query_gemini
  - google_trends
  - google_finance
  - google_scholar
  - google_jobs
  - google_news
  - dataforseo_serp_google_news
  - dataforseo_serp_google_dataset_search
  - dataforseo_kw_google_ads_search_volume
  - dataforseo_labs_keyword_ideas
  - dataforseo_labs_search_intent
  - dataforseo_labs_bulk_traffic_estimation
  - dataforseo_bl_bulk_ranks
  - keywords_everywhere_keyword_data
  - spyfu_get_bulk_domain_stats
  - dataforseo_biz_listings_search
  - scrape_review_platforms
  - reddit_search
  - apple_top_charts
  - google_play_store
  - firecrawl_search
budget: { max_tool_calls: 40, max_usd: 1.50, max_minutes: 20 }
outputs: { report_template: market-sizing, formats: [markdown, html] }
---

# Market Sizing — Dual-Method TAM/SAM/SOM

**Goal:** an investor-grade sizing an analyst cannot poke a hole in. Bottom-up
is the lead method (customers reachable with the actual motion x realized
ARPA); top-down industry reports only sanity-check magnitude. Both methods,
always, reconciled under the 15% divergence rule, with every ratio sourced,
dated, and stress-tested in a sensitivity table. Sizing alone is not enough —
a behavioral demand-validation layer (search demand, community pain,
incumbent share) says whether the number is backed by real pull.

## Principles (read first)

- **Build UP from SOM, sanity-check DOWN from TAM.** The number that matters
  is the customers reachable with the actual acquisition motion. A top-down
  report figure is a magnitude check, never the answer.
- **Every ratio is sourced, dated, and graded.** An unsourced multiplier is
  fiction. The source log with reliability grades is a deliverable, not an
  appendix.
- **Behavioral over attitudinal, always.** Search volume, review counts, and
  competitor revenue are demand evidence. Stated-intent surveys ("would you
  pay for X?") are near-worthless — never headline them.
- **SOM realism anchors:** 0.5-2% adoption year one for new products; tech
  IPOs typically hold 0.1-2% of their stated TAM. A 10% year-one claim is a
  red flag to refuse, not to format.
- **Unit discipline is non-negotiable:** never mix revenue with customer
  spend, users with companies with households, seats with usage. Adjust
  pricing by region when `geo` is set.

## Sequence

1. **Scope & unit lock** — Transform: write the sizing contract before any
   tool call: unit of count (companies / users / households / seats),
   unit of value (revenue vs customer spend), geo scope, price basis
   (list vs realized). Every later number must state these units; a figure
   that can't is a unit-mixing bug. If `acv` given, pin it as the ARPA anchor.
2. **Category & problem-term definition** — Transform: 3-5 category terms
   plus 5-10 problem terms (the pain the product solves, in customer
   vocabulary). Expand with `dataforseo_labs_keyword_ideas` on the seed
   terms (on_error=skip). These feed both demand validation and top-down
   report queries.
3. **Bottom-up: customer count via proxy table** — pick the ONE proxy row
   matching the segment and state it explicitly:
   B2B companies -> `perplexity_responses` for NAICS establishment counts
   ("US Census County Business Patterns, NAICS {code}: establishment count,
   {geo}") + `dataforseo_serp_google_dataset_search` for the Census/BLS
   dataset itself (x0.8-1.0 of establishments in code); B2B roles/seats ->
   BLS occupational counts via `perplexity_responses` (x0.5-0.7 title
   inflation); SMB/local -> `dataforseo_biz_listings_search` for business
   listings in the vertical + geo (x0.7-0.9 stale listings); B2C app-led ->
   `apple_top_charts` + `google_play_store` category presence (x0.2-0.4
   downloads-to-active, x0.02-0.1 to paying; on_error=skip); category
   buyers -> review-platform listing + review counts via
   `scrape_review_platforms` as a floor, never an estimate.
4. **Bottom-up: realized ARPA** — Parallel: `firecrawl_search` for incumbent
   pricing pages + `perplexity_chat` quick lookups of list prices for 3-5
   category incumbents. Transform: anchor on the tier the ICP actually buys
   (not the cheapest advertised), then apply the haircut band: self-serve/
   SMB 80-90% of list, mid-market 65-80%, enterprise 50-70%. If `geo` set,
   adjust for regional pricing. If `acv` input given, use it and mark the
   mined range as cross-check only.
5. **Bottom-up TAM** — Transform: customer count x realized ARPA, with the
   full formula printed (proxy row, multiplier, haircut). Keep SAM filters
   for step 11 — each filter compounds error, so minimize them.
6. **Top-down cross-check** — Parallel: `perplexity_responses` for analyst
   market reports ("market size and CAGR for {market} in {geo}; cite the
   report name and year — Gartner, Forrester, Statista, Grand View, etc.")
   + `google_scholar` for academic/industry sizing + `llm_query_perplexity`
   for a web-grounded second opinion. Require TWO independent reports;
   "industry sources say" without a named report + year is a citation
   failure. LLM output is never a primary source — it steers tool checks.
7. **Dual-method reconciliation** — Transform: if bottom-up vs top-down
   differ by <=15%, report both with bottom-up as lead. If >15%, do NOT
   average and do NOT pick one silently: present both, flag the divergence,
   downgrade sizing confidence to "directional", and name the single input
   assumption that drives the gap (usually the customer-count multiplier or
   the ARPA haircut).
8. **Demand validation: search demand** — Parallel:
   `dataforseo_kw_google_ads_search_volume` +
   `keywords_everywhere_keyword_data` on the 5-10 problem terms (two
   independent volume sources; disagreement >2x is a `[CONFLICT]`) +
   `google_trends` on 2-3 broad category terms (5-year view for trajectory
   and seasonality) + `dataforseo_labs_search_intent` to split
   informational vs transactional demand (on_error=skip). Keyword volume
   on problem terms = existing demand proxy; category-term trajectory
   (rising / flat / declining) is a sizing input, not decoration.
9. **Demand validation: community pain** — `reddit_search` on the problem
   terms (volume and recency of complaint threads) +
   `scrape_review_platforms` on 2-3 category incumbents for recurring
   complaints (on_error=skip). Transform: pain-intensity note — active
   recent complaint volume corroborates the problem terms from step 2.
10. **Incumbent reality check** — Parallel: `spyfu_get_bulk_domain_stats` +
    `dataforseo_labs_bulk_traffic_estimation` +
    `dataforseo_bl_bulk_ranks` for the top 5-10 category players +
    `google_finance` for any public comps (revenue / stated TAM = actual
    realized share — the strongest anchor against TAM inflation).
    Transform: realized-share table; expect category leaders at 0.1-2% of
    stated TAM. If claimed TAM implies leaders hold >10%, the TAM is
    almost certainly overstated — say so.
11. **SAM/SOM & segmentation** — Transform: MECE segmentation (no
    overlapping segments; a customer in two segments is double-counted)
    with minimal filters from TAM to SAM, and a roll-up check that
    segments sum back to TAM. SOM is tied to concrete acquisition
    capacity — channel reach x conversion from the actual motion (e.g.
    "paid search on {n} problem terms at {cpc} -> {trials} -> {customers}")
    — never a bare "% of TAM". Year-one adoption anchor: 0.5-2% of SAM.
12. **Market pulse** — Parallel: `google_jobs` on 2-3 category leaders
    (hiring velocity = market-entry signal; ghost-jobs caveat ~40%) +
    `google_news` (funding rounds, launches = capital validating the
    market) + `dataforseo_serp_google_news` on "{market} conference
    {year}" (event density as budget-flow proxy) (on_error=skip).
13. **Sensitivity & scenarios** — Transform: vary every ratio in the
    bottom-up build +-25% (customer multiplier, ARPA haircut, SAM filters,
    adoption rate). Any ratio swinging the output >10% is a SWING RATIO
    and must carry a primary-validation note (what evidence would pin it).
    Build the scenario fan: pessimistic (low multiplier, deep haircut,
    0.5% adoption) / reference (midpoints) / optimistic (high multiplier,
    shallow haircut, 2% adoption). Never ship a single-point estimate.
14. **Synthesis** — Transform: one verdict paragraph — reference SOM with
    the scenario fan, sizing confidence (high / directional / low), the
    swing ratios that most need primary research, and the demand-validation
    verdict (confirmed / mixed / absent behavioral demand).

## Verification (hard rules)

- Sizing numbers (customer counts, ARPA, market size, keyword volumes):
  >=2 independent sources, >=3 for numbers that drive the conclusion.
  Two tools reading the same upstream index do not count twice.
- Dual-method divergence >15% -> both numbers presented, confidence
  downgraded to "directional", driver assumption named. Never average.
- `[CONFLICT]` protocol: tag disagreeing sources, spend at most ONE targeted
  extra lookup (prefer `llm_query_gemini` as tie-breaker on qualitative
  disputes), and if unresolved surface both — never silently pick a side.
- VERIFIED tag requires a tool-level check against a second source;
  everything single-sourced or modeled is ASSUMED. LLM answers (Perplexity,
  llm_query_*) are never primary sources — cite as "model cross-check".
- Traffic-derived revenue math carries the traffic error band through the
  calculation (30-50% typical; >70% under ~100k monthly visits — report
  order of magnitude only).
- Hallucinated-precision guard: an undisclosed number is a modeled RANGE
  with named assumptions or "no authoritative public evidence" — never a
  confident point value. Precise quotes with named attribution are allowed.

## Output instructions

Template `market-sizing`. Required sections:

1. **Executive summary** — pessimistic / reference / optimistic SOM, sizing
   confidence, demand-validation verdict, one line each.
2. **Market definition & unit lock** — the sizing contract: units, geo,
   price basis, MECE segment map.
3. **Bottom-up build** — proxy row used, multiplier band applied, ARPA tier
   + haircut, the full printed formula with sources.
4. **Top-down build** — named reports with year and figures; academic
   sources; what each actually measures (revenue vs spend).
5. **Reconciliation** — both numbers, divergence %, verdict, and the named
   driver assumption if >15%.
6. **Demand validation** — problem-term volumes (both sources), category
   trend trajectory, intent split, community-pain evidence with 2-3
   verbatim quotes.
7. **Incumbent reality check** — realized-share table, leader share vs
   stated TAM, TAM-inflation verdict.
8. **SAM/SOM & segmentation** — segment table with roll-up check, SOM
   capacity math (channel reach x conversion), year-one adoption anchor.
9. **Sensitivity & scenarios** — swing-ratio table (ratio / +-25% effect /
   primary-validation note), scenario fan with assumptions per leg.
10. **Source log** — every ratio with tool + retrieval date + reliability
    grade; confidence ladder; `[CONFLICT]` register; what a refresh should
    re-fetch first (the swing ratios).

## Guards (failure modes to refuse)

- **The 1% fallacy:** SOM stated as "we take 1% of TAM" with no acquisition
  capacity math — refuse; tie SOM to channel reach x conversion or omit it.
- **SOM presented as TAM:** reachable-market numbers headlined as the
  addressable market — label every figure with which layer it is.
- **Double-counting overlapping segments:** a customer countable in two
  segments; the roll-up check fails — fix the segmentation before writing.
- **Single-point estimate:** any headline number without the pessimistic /
  reference / optimistic fan — refuse to publish it.
- **Top-down-only sizing:** a report figure with no bottom-up build — the
  run is incomplete, say so; never let an analyst report be the lead method.
- **Stated-intent as demand evidence:** survey "willingness to pay" numbers
  presented as validation — behavioral signals only in section 6.
