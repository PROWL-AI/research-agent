---
name: channel-economics
description: >-
  Acquisition-channel economics of a product or competitor: traffic mix
  (paid vs organic vs referral), 12-month channel decay, growth-loop
  diagnosis, niche-media and sponsorship surface, and modeled CAC/LTV
  scenarios. Use for growth strategy, channel analysis, or "where do their
  users come from" questions about a domain.
version: "1.0"
inputs:
  - { name: subject, type: "domain", required: true, doc: "Domain whose acquisition economics are analyzed." }
  - { name: acv, type: "string", required: false, doc: "Annual contract value / ARPA if known (e.g. '$1200/yr'). Drives the CAC/LTV scenario bands; if omitted, model from the pricing page." }
  - { name: market, type: "string", required: false, doc: "Product category / niche, used for niche-media discovery and trend queries." }
tools:
  - discover_niche_media
  - exa_keyword_search
  - exa_similar_search
  - exa_get_contents
  - firecrawl_search
  - firecrawl_map_domain
  - firecrawl_scrape_website
  - firecrawl_scrape_page_markdown
  - crawl_funnel_path
  - find_subdomains
  - perplexity_responses
  - spyfu_get_bulk_domain_stats
  - spyfu_get_combined_competitors
  - spyfu_get_top_pages
  - spyfu_get_most_valuable_keywords
  - spyfu_get_paid_search
  - spyfu_get_ad_history
  - spyfu_get_ppc_keywords
  - dataforseo_labs_bulk_traffic_estimation
  - dataforseo_labs_historical_bulk_traffic_estimation
  - dataforseo_labs_domain_rank_overview
  - dataforseo_bl_summary
  - dataforseo_bl_referring_domains
  - keywords_everywhere_domain_traffic_metrics
  - meta_ad_library
  - meta_ad_library_ad_details
  - linkedin_ad_library
  - tiktok_ads_library
  - google_ads_transparency_advertiser_search
  - foreplay_discovery_ads
  - foreplay_get_brands_by_domain
  - youtube_search
  - youtube_channel_videos
  - google_trends
  - google_news
budget: { max_tool_calls: 50, max_usd: 2.00, max_minutes: 25 }
outputs: { report_template: channel-economics, formats: [markdown, html] }
---

# Channel Economics

**Goal:** a decision-ready read on how a product acquires users and what that
acquisition costs. Not a traffic snapshot — the traffic MIX, its 12-month
decay curve, the growth loop the business runs on, the niche-media and
sponsorship surface it could buy, and CAC/LTV as modeled scenarios with every
assumption named. The deliverable answers: which channel is the engine, which
is decaying, and is the math viable.

## Principles (read first)

- **CAC and LTV are modeled, never measured.** A private company's unit
  economics are not public. Present pessimistic / reference / optimistic
  scenarios from the formulas and benchmark bands, name every assumption,
  and never emit a point estimate. Viability line: LTV:CAC >= 3:1.
- **Every channel decays.** A snapshot traffic share is trivia; the 12-month
  trend is the finding. Always classify the decay stage (growth / plateau /
  decline) per channel and never report a bare current-state number. Before
  calling decline in a seasonal niche (tax, travel, education, gifting),
  check the same window a year ago: a repeated annual dip is seasonality,
  not decay — say which one the curve shows.
- **Ad presence is not a paid-growth loop.** Diagnose the loop from traffic
  mix + ad longevity + referral evidence together. One-off boosts (launches,
  press hits) are named separately from compounding engines.
- **Traffic numbers are estimates with error bands.** Perplexity engagement
  data is secondhand; when two sources disagree by more than 2x, report the
  range — never pick one silently. Under ~50k monthly visits, use keyword
  count and organic value as proxy signals instead.
- **An audience claim without a verbatim evidence quote is "audience
  undisclosed".** A sponsorship signal seen once is a rumor; two independent
  sightings make it a finding.

## Sequence

1. **Scope** — Transform: normalize the domain (strip scheme/path/www). If
   `acv` omitted, note that pricing must be scraped in step 8. Run
   `find_subdomains` (on_error=skip) in parallel with step 2 to catch
   separate app/blog/docs properties whose traffic must not be conflated.
2. **Niche media discovery (FIRST media call)** — `discover_niche_media` with
   the `market` (or the subject's category) + audience. This is mandatory
   before any other media tool: it fans out across niche newsletters,
   podcasts, YouTube channels and communities and returns channel rows with
   `audience_estimate` + `audience_evidence`. Keep every verbatim evidence
   quote next to its claim. If the tool errors or returns nothing, fall back
   to `exa_keyword_search` + `firecrawl_search` with "{market} newsletter
   sponsor", "{market} podcast advertise", "best {market} communities" and
   say so in the report. Respect the `degraded` flag / `dropped_count`:
   state "inventory partial — N sources unavailable" instead of presenting
   the list as exhaustive.
3. **Competitor frame** — Parallel: `spyfu_get_combined_competitors` +
   `exa_similar_search` on the subject. Transform: top 3-5 competitors for
   the comparative engagement profile; prefer same-ICP rivals with active
   ads over the biggest brands.
4. **Traffic engagement profile** — Fan-out ONE `perplexity_responses` query
   per domain (subject + top 3-5): "What are the estimated monthly visitors,
   average visit duration, bounce rate, and pages per visit for {domain}?
   What is the traffic channel breakdown (organic, paid, social, direct,
   referral, display, email)? Cite SimilarWeb or similar sources."
   Parallel: `spyfu_get_bulk_domain_stats` for the same domains as the
   SEO/PPC baseline. Transform: cross-reference Perplexity against SpyFu
   organic numbers; disagreement >2x → report both as a range
   (`[CONFLICT]`-style), per the 2x-disagreement rule.
5. **Channel mix & decay (12-month trend)** — `dataforseo_labs_bulk_traffic_estimation`
   for all domains + `dataforseo_labs_historical_bulk_traffic_estimation`
   (12-month window) for the subject and top-2 + `keywords_everywhere_domain_traffic_metrics`
   on the subject as an independent second source (on_error=skip) +
   `dataforseo_labs_domain_rank_overview` + `google_trends` on the brand
   term (12-month). Transform: per channel — growth / plateau / decline
   stage with the trend cited. A channel reported without its decay stage
   is a violation of the Principles.
6. **Organic & referral engine** — `spyfu_get_top_pages` +
   `spyfu_get_most_valuable_keywords` on the subject; `dataforseo_bl_summary`
   + `dataforseo_bl_referring_domains` (on_error=skip) for the referral
   surface. Transform: is content/SEO a compounding engine (rising ranks on
   commercial-intent pages) or flat? Heavy referral → partnership network;
   heavy direct → brand demand; heavy social → creator/influencer motion.
7. **Paid engine & spend trajectory** — `spyfu_get_paid_search` +
   `spyfu_get_ppc_keywords` + `spyfu_get_ad_history` for search spend and
   longevity. Parallel social: `meta_ad_library` + `linkedin_ad_library` +
   `tiktok_ads_library` + `google_ads_transparency_advertiser_search` +
   `foreplay_discovery_ads` / `foreplay_get_brands_by_domain` (on_error=skip);
   `meta_ad_library_ad_details` on the longest-running creatives.
   Transform: platform mix, creative longevity, spend verdict (scaling /
   steady / retreating). Spend sustained 6+ months is almost certainly
   profitable (advertiser-level) — say so when the evidence shows it.
8. **Growth-mechanics crawl** — `firecrawl_map_domain` on the subject;
   grep the URL map for the free-tool taxonomy (`/tools/`, `/free-`,
   `-calculator`, `-generator`, `-checker`, `-grader`) and alternatives
   pages. Fan-out `firecrawl_scrape_page_markdown` on the 3-5 most
   interesting hits (on_error=skip) + `firecrawl_scrape_website` on
   homepage + /pricing. Transform: (a) free tools — what data each captures
   and what it upsells to (each is a standing lead-gen loop); (b) PLG /
   referral markers — "refer a friend", invite flows, rewards, "Made with X"
   badges, freemium tier, public waitlist; (c) alternatives-page taxonomy —
   singular "X alternative" = switching-intent capture; plural "X
   alternatives" = early-research capture; "you vs X" = direct comparison;
   "X vs Y" (two rivals) = third-party traffic capture. Map who attacks
   whom: the direction of alternatives pages reveals who is bleeding
   customers to whom. Scrape the pricing tiers here for step 10.
9. **Funnel & loop stage** — Transform: landing URLs from step 7 ads →
   `crawl_funnel_path` (on_error=skip). Note trial-gate placement and where
   the loop leaks (ad click → signup → activation).
10. **Sponsorship signal extraction** — Transform: from $step_2.channels take
    the top 5-8 with a contact path or ad page. Fan-out
    `firecrawl_scrape_page_markdown` on Advertise / Sponsor / Media-kit /
    Work-with-us pages (rate cards, audience claims, formats);
    `youtube_channel_videos` on YouTube/podcast candidates to spot recurring
    sponsors across episodes (renewal = pricing power); `exa_get_contents`
    for newsletter archives — count distinct sponsors over the last ~10
    issues. A signal counts only with 2+ independent sightings; a channel
    with zero signals is labeled "discovery-only". Extract the contact path
    whenever present.
11. **CAC/LTV modeled scenarios** — Transform only (no tools): with `acv` or
    the scraped pricing, model per-channel UNBLENDED scenarios. State the
    formulas in the report: LTV = (ARPA / monthly churn) x gross margin;
    CAC payback (months) = CAC / (ARPA x gross margin). Benchmarks:
    LTV:CAC >= 3, payback <= 12 months (SMB) / <= 18-24 (enterprise);
    ~75% gross margin for self-serve SaaS. Emit pessimistic / reference /
    optimistic bands and name which input (churn, CPC-to-close rate, ARPA
    mix) drives the spread. If the data only supports a blended view, label
    it "blended" explicitly.
12. **Growth-loop diagnosis** — `google_news` (launches, funding, press
    spikes) + `youtube_search` on the brand (on_error=skip). Transform:
    classify the subject's PRIMARY loop — viral/referral, content/SEO, paid
    acquisition, or sales-assisted — from the traffic mix (step 5) + ad
    longevity (step 7) + PLG markers (step 8) + referral surface (step 6).
    Name the broken loop stage with evidence. Separate one-off boosts
    (launch, press hit — cite `google_news`) from compounding engines.
13. **Synthesis** — Transform: channel scorecard (mix %, decay stage, spend
    trajectory, role in the loop) + modeled economics table + niche-media
    buy list ranked by evidence strength.

## Verification (hard rules)

- Key numbers (traffic, channel share, spend, audience size): >= 2
  independent sources or tag ASSUMED. Perplexity vs SpyFu/Keywords
  Everywhere disagreement >2x → report the range, never one value.
- Every traffic-share percentage carries an error band (typically 30-50%;
  >70% under ~100k monthly visits) and a VERIFIED/ASSUMED tag.
- LLM output (Perplexity, Gemini, AI Mode) is never a primary source —
  cross-check against a data tool.
- CAC, LTV and payback are MODELED SCENARIOS ONLY: bands with named
  assumptions, never a point estimate, never the word "measured".
- Sponsorship findings need 2+ independent sightings; audience claims need a
  verbatim evidence quote or are reported as "audience undisclosed".
- Channel decay stage must be stated for every channel that appears in the
  report; no current-state-only claims.

## Output instructions

Template `channel-economics`. Required sections:

1. **Executive summary** — the primary growth loop, the single strongest and
   fastest-decaying channel, and the LTV:CAC viability verdict (reference
   scenario), one line each with evidence.
2. **Traffic mix & engagement** — channel breakdown with error bands;
   engagement metrics vs top-3 competitors; the 2x-disagreement ranges
   where sources conflicted.
3. **Channel decay** — 12-month trend per channel with decay stage; brand
   trend vs category trend.
4. **Growth-loop diagnosis** — loop type classification with evidence; the
   broken stage; one-off boosts vs compounding engines.
5. **Paid vs organic economics** — platform mix, creative longevity, spend
   trajectory verdict; organic engine health (commercial-intent pages,
   referral surface).
6. **PLG & free-tool surface** — free tools found (capture + upsell),
   referral/PLG markers, alternatives-page map (who attacks whom).
7. **Modeled CAC/LTV scenarios** — pessimistic / reference / optimistic
   table, unblended per channel where data allows; formulas and every
   assumption named; viability vs the 3:1 line and payback benchmarks.
8. **Niche media & sponsorship map** — channel table (type, audience claim
   + evidence quote, sponsorship signals, contact path); buy-list ranked by
   evidence strength; "discovery-only" and partial-inventory caveats.
9. **Recommendations** — 3-5 channel bets ranked by expected economics, each
   tied to a section's evidence.
10. **Source log** — every figure with tool + retrieval date; confidence
    ladder (VERIFIED / ASSUMED / MODELED); `[CONFLICT]` register; refresh
    recommendation (quarterly).

## Guards (failure modes to refuse)

- Presenting CAC, LTV or payback as observed/measured facts — they are
  modeled scenarios; if the user asks for "their actual CAC", say it is not
  publicly knowable and deliver the scenario bands instead.
- Traffic-share percentages as a bare snapshot: no 12-month trend or no
  error band means the number does not ship.
- Sponsorship or audience claims from a single sighting / without a verbatim
  quote — label them unverified or "audience undisclosed".
- Blend-blind economics: quoting one blended CAC when channel-level data
  exists, without labeling it blended — paid search and content are
  different businesses.
- Skipping the niche-media first call: if `discover_niche_media` was not the
  first media call (or its failure/fallback was not logged), the media
  section is labeled incomplete.
- Diagnosing a paid-growth loop from ad presence alone — no loop claim
  without traffic mix + ad longevity + referral evidence combined.
