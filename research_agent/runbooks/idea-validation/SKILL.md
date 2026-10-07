---
name: idea-validation
description: >-
  Validate a raw product or business idea that has no domain yet: behavioral
  problem-demand evidence, discovery of existing solutions and mining of their
  complaints, a dual-method market-size quick-pass, and a one-sentence
  differentiation wedge. Output is an evidence-scored validation memo with
  kill criteria and an ICE-ranked opportunity backlog. Use for "should I build
  X", idea assessment, and pre-launch research.
version: "1.0"
inputs:
  - { name: idea, type: "string", required: true, doc: "The product/business idea in one or two sentences, as the user stated it." }
  - { name: market, type: "string", required: false, doc: "Product category / niche for sizing and trend queries. Inferred from the idea if omitted." }
  - { name: target_customer, type: "string", required: false, doc: "Intended customer segment (ICP sketch), used to scope sizing and complaint mining." }
tools:
  - google_trends
  - dataforseo_serp_google_autocomplete
  - dataforseo_kw_google_ads_search_volume
  - dataforseo_kw_bing_search_volume
  - dataforseo_labs_search_intent
  - dataforseo_labs_bulk_keyword_difficulty
  - google_search
  - exa_keyword_search
  - exa_similar_search
  - exa_answer
  - firecrawl_search
  - gemini_extract_competitors
  - discover_niche_media
  - reddit_search
  - google_forums
  - scrape_review_platforms
  - spyfu_get_domain_stats
  - spyfu_get_top_pages
  - spyfu_get_paid_search
  - spyfu_get_ad_history
  - spyfu_get_ppc_keywords
  - meta_ad_library
  - linkedin_ad_library
  - tiktok_ads_library
  - google_ads_advertiser_info
  - foreplay_discovery_ads
  - foreplay_discovery_brands
  - meta_ad_library_ad_details
  - firecrawl_scrape_website
  - gemini_analyze_website
  - perplexity_responses
  - perplexity_chat
  - google_finance
  - google_news
  - google_jobs
  - youtube_search
  - dataforseo_labs_bulk_traffic_estimation
  - google_ai_mode
budget: { max_tool_calls: 45, max_usd: 1.50, max_minutes: 20 }
outputs: { report_template: idea-validation, formats: [markdown, html] }
---

# Idea Validation

**Goal:** an evidence-scored verdict on a raw idea with no domain behind it —
is there behavioral demand, who already serves it, how big is the reachable
market, and where is the wedge. Output is a validation memo with kill criteria
stated before the verdict and an ICE-ranked opportunity backlog, not a
cheerleading summary. Every claim carries a claim id so ICE scores can cite
their evidence.

## Principles (read first)

- **Behavioral over attitudinal, always.** Believe what people do — search
  volume on problem terms, competitors' sustained ad spend, community pain
  threads — never what they say they'd do. Surveys and "people say they want
  it" are tagged weak or excluded. A demand claim with no behavioral signal
  behind it does not exist.
- **Existing solutions are good news.** Zero competitors usually means zero
  market, not an open field. Incumbents validate demand; their complaints are
  where the wedge lives. Refuse competitorless-market framing.
- **Sizing is a quick-pass, not a study.** Order-of-magnitude TAM/SAM/SOM via
  the dual-method protocol (bottom-up vs top-down, 15% divergence rule). Do
  not burn budget on precision the decision doesn't need.
- **No verdict stronger than the weakest required evidence class.** The memo
  needs (a) behavioral demand, (b) competitor evidence, (c) sizing. If one is
  ASSUMED or missing, the verdict is capped at "directional" and says why.
- **Kill criteria come before the verdict.** State what evidence would
  invalidate the idea while the analysis is still honest.

## Sequence

1. **Scope** — Transform: restate the idea as (a) a problem statement, (b) 2-4
   category/problem seed terms, (c) an ICP sketch (use `target_customer` if
   given), (d) the assumed geography. If `market` is omitted, infer it and tag
   ASSUMED. Assign claim ids (C1, C2, ...) — every downstream finding
   attaches to one.
2. **Demand proxies (behavioral)** — Parallel: `google_trends` (2-4 seed
   terms in one call, 12-month trajectory — category terms, not brand names)
   + `dataforseo_serp_google_autocomplete` on the seed phrases (modifiers
   reveal use cases and price anxiety) + `dataforseo_kw_google_ads_search_volume`
   and `dataforseo_kw_bing_search_volume` for the same terms (cross-engine
   divergence is itself a signal). Enrich the top 10-15 problem keywords with
   `dataforseo_labs_search_intent` + `dataforseo_labs_bulk_keyword_difficulty`
   (on_error=skip). Transform: demand verdict per seed term — trajectory,
   volume band, intent mix. Flat-to-declining trends on all seeds is a
   first-class negative finding, not a gap to hide.
3. **Competitor discovery without a domain** — Parallel: `google_search` +
   `exa_keyword_search` on the problem statement + `firecrawl_search("{idea}
   tools / alternatives / software")`. Transform: feed results to
   `gemini_extract_competitors`; take the top 5, cap deep-dive at 3 — prefer
   players with active paid ads and the same ICP over the biggest brands. If
   two search rounds return zero credible players, record "no solutions
   found" as a red-flag finding (probable no-market), not a blue ocean.
4. **Community pain & niche media** — Parallel: `reddit_search` +
   `google_forums` on the problem terms (pain threads, DIY workarounds,
   quoted prices) + `discover_niche_media` (where the audience congregates —
   feeds channel assumptions) (on_error=skip). Transform: recurring pain
   themes with verbatim quotes. DIY workarounds (spreadsheets, Zapier chains)
   count as demand evidence AND wedge input.
5. **Incumbent baseline** — Fan-out per top-3 incumbent:
   `spyfu_get_domain_stats` (past_n_months=12 — trajectory, not snapshot) +
   `spyfu_get_top_pages` + `dataforseo_labs_bulk_traffic_estimation` (one
   batched call for all domains) (on_error=skip). A SpyFu/DataForSEO miss
   means very new or very small — note it, don't treat as zero.
6. **Ad spend as demand proof** — Parallel per top-3 incumbent:
   `meta_ad_library` + `linkedin_ad_library` + `tiktok_ads_library` +
   `google_ads_advertiser_info` + `foreplay_discovery_ads` +
   `foreplay_discovery_brands` (on_error=skip). Then `spyfu_get_ad_history` +
   `spyfu_get_paid_search` + `spyfu_get_ppc_keywords` for search-spend
   history, and `meta_ad_library_ad_details` on the longest-running creatives
   (on_error=skip). Transform: per incumbent — platforms, longest-running
   creative, spend trajectory (scaling / steady / retreating). Sustained
   spend 60-90+ days = someone is profitably paying to acquire this customer;
   the strongest behavioral demand signal in this runbook. An empty ad
   library is a finding (channel skipped or weak economics), never an error.
7. **Offer & pricing scrape** — Fan-out `firecrawl_scrape_website` per top-3
   incumbent (homepage + /pricing) + `gemini_analyze_website` per incumbent.
   Transform: pricing tiers, packaging, trial vs freemium, claimed value prop
   — needed for the ARPA anchor in step 9 and the gap map in step 8.
   Offline/enterprise pricing is marked, never guessed.
8. **Complaint mining (the wedge quarry)** — `scrape_review_platforms` per
   top-3 incumbent (Trustpilot/G2/Capterra composite, on_error=skip) +
   targeted `reddit_search` on "{brand} alternative / sucks / vs"
   (on_error=skip). Transform: complaints → gap table (frequency × severity),
   praised workflows (= the incumbent's real moat — the wedge must route
   around it, not through it), customer vocabulary, quoted prices.
9. **Sizing quick-pass (dual-method, mandatory)** — Bottom-up first:
   addressable customer count from a named proxy (state the proxy-table row
   and multiplier) × ARPA anchored on the tier the ICP actually buys (from
   step 7) with the segment haircut band applied. Top-down cross-check: ONE
   `perplexity_responses` query — "TAM/SAM/SOM for {market} in {geography}:
   market size USD, CAGR, customer count; cite analyst reports, NAICS,
   Census" — plus `google_finance` for any public incumbent as a revenue
   anchor (on_error=skip). Transform: divergence >15% → present both,
   downgrade to "directional", name the driving assumption — never average
   silently. SOM only as channel reach × conversion capacity, or omitted.
10. **Trajectory & saturation context** — Parallel: `google_news` (funding,
    launches, layoffs) + `google_jobs` (incumbent hiring velocity; ~40%
    ghost-jobs caveat) + `youtube_search` per top incumbent brand +
    `google_ai_mode` for 2-3 category queries (who AI assistants already
    recommend) + `exa_answer` for any factual hole (on_error=skip).
11. **Synthesis** — Transform, in order: (a) kill criteria — the specific
    evidence that would invalidate the idea (e.g. "no problem-term with
    growing volume", "zero incumbents with sustained spend", "TAM below $XM
    at any reasonable ARPA"); (b) the wedge — ONE sentence from complaint
    frequency × severity + unserved segment + pricing gap, citing claim ids;
    (c) ICE backlog — 3-6 opportunities scored Impact / Confidence / Ease
    (1-10): Impact and Confidence must cite the claim ids they derive from,
    Ease from effort heuristics (build complexity, channel access from step
    4, incumbent moat from step 8); (d) verdict — build / pivot / kill /
    needs-more-evidence, capped by the weakest evidence class. Note the Sean
    Ellis 40% "very disappointed" test as the post-launch PMF companion —
    recommend it, never simulate it.

## Verification (hard rules)

- Demand claims: behavioral signal required (search volume, trend trajectory,
  sustained ad spend, pain threads with engagement); anything else is tagged
  weak. LLM output (Perplexity, Gemini, AI Mode, Exa answer) is never a
  primary source — cross-check against a data tool.
- Key numbers (volumes, traffic, TAM): ≥2 independent sources or tag ASSUMED;
  traffic figures carry the 30-50% error band (>70% under ~100k monthly
  visits — order of magnitude only).
- Cross-engine volume divergence (Google vs Bing) >2x → `[CONFLICT]`, report
  both. Dual-method sizing divergence >15% → `[CONFLICT]` + "directional".
- Sustained-spend inferences state the observation window; "profitable" is
  inferred, never asserted — tag ASSUMED unless a second signal agrees.
- Every ICE Impact/Confidence score cites its claim ids; a score without
  citations is deleted, not averaged.

## Output instructions

Template `idea-validation`. Required sections:

1. **Idea restated** — problem statement, seed terms, ICP sketch, geography;
   inferred inputs tagged ASSUMED.
2. **Demand evidence (behavioral)** — per seed term: trend trajectory, volume
   band, intent mix, cross-engine agreement; autocomplete use-case map.
3. **Existing solutions** — discovered incumbents, offers and pricing,
   traffic trajectory, ad-spend longevity with the profitability inference
   (confidence-tagged). "Zero competitors found" appears here as a red flag
   with the search rounds attempted.
4. **Complaints & voice of customer** — gap table (complaint × frequency ×
   severity), incumbent moats, 3-5 verbatim quotes with platform, quoted
   prices.
5. **Market size quick-pass** — bottom-up and top-down TAM/SAM/SOM side by
   side, proxy row + multiplier + ARPA haircut stated, divergence handling,
   confidence tag.
6. **Trajectory & saturation** — news, hiring (ghost-jobs caveat), YouTube
   presence, AI-assistant recommendations: heating up or consolidating.
7. **Kill criteria** — the evidence that would invalidate the idea, stated
   before the verdict, each criterion tied to a checkable signal.
8. **The wedge** — one sentence, evidence-cited.
9. **ICE opportunity backlog** — ranked table: opportunity, I/C/E scores,
   claim-id citations per score, first test for each.
10. **Verdict** — build / pivot / kill / needs-more-evidence, capped by the
    weakest evidence class, plus the recommended post-launch PMF test (Sean
    Ellis 40%) and what to measure first.
11. **Source log** — every figure with tool + retrieval date; confidence
    ladder (VERIFIED / ASSUMED / weak); `[CONFLICT]` register; refresh
    recommendation (re-run demand + ad-spend steps before committing build
    budget).

## Guards (failure modes to refuse)

- **Attitudinal demand presented as validation.** Survey results, waitlist
  signups the user mentions, "people say they want it" — never evidence. If
  behavioral signals are absent, the verdict is "needs-more-evidence", full
  stop.
- **Competitorless-market framing.** "No competitors = open opportunity" is
  refused; zero credible incumbents after two search rounds is a probable
  no-market signal and must be reported as such.
- **Verdict stronger than the evidence.** If any of demand / competitors /
  sizing is ASSUMED or missing, the memo says "directional" and names the
  missing class — no confident verdict on a broken leg.
- **Single-method sizing or silent averaging.** One TAM number, or two
  methods averaged without disclosure, fails the memo; both numbers ship or
  the section is tagged ASSUMED.
- **Simulated PMF tests.** Do not fabricate Sean Ellis survey results,
  willingness-to-pay percentages, or fake user quotes — recommend the test,
  list what to measure, stop there.
- **Wedge by assertion.** A wedge sentence without complaint/gap citations is
  marketing copy; delete it and mark the wedge "not yet evidenced".
