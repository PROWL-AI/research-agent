---
name: reviews-voice
description: >-
  Mine reviews across platforms (Trustpilot/G2/Capterra/app stores/Reddit) for
  1-5 products or competitors: recurring complaints = exploitable gaps, praised
  workflows = the real moat, customer vocabulary = messaging input, quoted-price
  testimonials = pricing archaeology. Output is a voice-of-customer report with
  verbatim evidence, theme counts, and rating-velocity analysis. Use for review
  analysis, VoC, messaging research, or churn-reason research.
version: "1.0"
inputs:
  - { name: subjects, type: "string", required: true, doc: "Brand names or domains to mine reviews for, comma-separated (max 5)." }
  - { name: focus, type: "string", required: false, doc: "Optional lens, e.g. churn reasons, onboarding, pricing. Drives targeted query variants." }
tools:
  - scrape_review_platforms
  - resolve_app_store_ids
  - apple_product_reviews
  - google_play_product_reviews
  - apple_product
  - firecrawl_scrape_website
  - firecrawl_scrape_page_markdown
  - firecrawl_search
  - firecrawl_scrape_mobile_app
  - reddit_search
  - google_forums
  - dataforseo_ai_perplexity_responses
  - gemini_reviews_report
  - facebook_business_page_reviews
  - google_local
  - google_place
  - google_maps_reviews
  - dataforseo_biz_google_reviews
  - dataforseo_biz_trustpilot_search
  - serpapi_yelp
  - serpapi_yelp_reviews
budget: { max_tool_calls: 40, max_usd: 1.50, max_minutes: 20 }
outputs: { report_template: voice-of-customer, formats: [markdown, html] }
---

# Reviews — Voice of Customer

**Goal:** a decision-ready voice-of-customer report per subject: what customers
complain about (ranked by frequency, with verbatim evidence), what they praise
(the real moat — often not the marketed one), the exact words they use
(messaging input), how sentiment is moving (velocity beats average), and what
they say about price. Verbatim or it didn't happen.

## Principles (read first)

- **A complaint without a count is an anecdote.** Themes exist only when ~3+
  independent reviews say the same thing; below that, label it "weak signal".
- **The praised workflow is the moat, not the marketed differentiator.** When
  what customers love diverges from the homepage pitch, name the divergence
  explicitly — that is often the most valuable finding in the report.
- **Verbatim or drop it.** Customer vocabulary is the deliverable; a
  paraphrased quote is worthless. Every quote carries platform + date.
- **Velocity and trend beat the average score.** A 4.6 falling is worse than a
  4.2 rising. Always compute reviews-per-month and rating direction where
  dates are available.
- **Review platforms skew extreme.** People review when delighted or furious.
  State this selection bias once, up front, and weigh middle-of-the-road
  signals (Reddit threads, forums) accordingly.

## Sequence

1. **Scope & normalize** — Transform: cap `subjects` at 5; for each, derive a
   normalized domain (strip scheme/path/www) where the subject is or implies
   one, plus a brand string for review-platform lookups. Note which subjects
   are app-based products (mobile app visible on site or category implies one)
   and which are local/physical businesses (routes to step 7).
2. **Homepage capture (app-discovery fast path)** — Fan-out per subject with a
   domain: `firecrawl_scrape_page_markdown` on the homepage (or
   `firecrawl_scrape_website` when the budget allows). Transform: extract
   `app_store_url` / `google_play_url` if present. This must complete BEFORE
   step 4 — never schedule it in the same parallel block as
   `resolve_app_store_ids`.
3. **Review platform mining** — Fan-out per subject:
   `scrape_review_platforms "{brand}" domain="{domain}"` (Trustpilot/G2/
   Capterra in one call, with web-search fallback). Transform: per platform —
   rating, review count, and raw review texts preserved verbatim with dates.
   Keep the raw payload; steps 9-10 depend on it.
4. **App store ID resolution** (app-based subjects only) — Per subject:
   `resolve_app_store_ids` with `brand_name` + `domain` + `company_name` +
   `alternate_queries` (full marketing name, category phrase like "esim
   travel app" — Apple often needs the longer name, not the domain slug).
   If both IDs null, fallback (on_error=skip): `firecrawl_search`
   `"{brand}" "{domain}" official app App Store OR Play Store`, then
   `dataforseo_ai_perplexity_responses` asking only for the two canonical
   `apps.apple.com` / `play.google.com` URLs (no prose); validate with
   `apple_product`. Last resort: user-supplied store links.
5. **App store reviews** — Parallel per subject with resolved IDs:
   `apple_product_reviews` + `google_play_product_reviews` (Play: up to 200
   reviews per page, paginate for velocity) (on_error=skip when IDs missing)
   + `firecrawl_scrape_mobile_app` per store URL for ratings history, version
   cadence, download/revenue estimates (on_error=skip). App reviews reveal
   churn triggers (update breakage, paywall shocks) invisible on B2B
   platforms.
6. **Community voice** — Fan-out per subject: `reddit_search "{brand}"` plus
   variants `"{brand} alternative"`, `"{brand} pricing"`, `"{brand} vs"`, and
   `google_forums "{brand}"` (on_error=skip). If `focus` given, add targeted
   variants (churn: `"{brand} cancelled"`, `"{brand} refund"`; onboarding:
   `"{brand} setup"`, `"{brand} getting started"`; pricing: `"{brand} price
   increase"`, `"{brand} worth it"`). Transform: capture quoted-price
   testimonials with URL + date — pricing archaeology; capture switch-from/
   switch-to mentions as churn-reason evidence.
7. **Local & social proof** (local/physical subjects only; skip otherwise) —
   Chain: `google_local "{brand}"` → `google_place` with the `kgmid` from
   results (kgmid is required; there is no `cid` param) → `google_maps_reviews`
   with `place_id` or `data_id` (NOT `kgmid` — it raises TypeError here),
   using `sort_by` + `next_page_token` to page. Parallel (on_error=skip):
   `dataforseo_biz_google_reviews`, `dataforseo_biz_trustpilot_search`,
   `facebook_business_page_reviews`, `serpapi_yelp` + `serpapi_yelp_reviews`.
8. **Consolidated sentiment** — One `gemini_reviews_report` call per subject
   over the raw output of steps 3+5+6(+7) — never one call per source.
   Transform: the LLM clusters; you verify. Every theme it emits must map back
   to specific raw reviews with counts; anything not traceable is dropped.
9. **Velocity & trend** — Transform: per subject per platform —
   reviews-per-month over the available window, rating trend direction
   (rising/falling/flat), and any rating discontinuities tied to dated events
   (a pricing change, a broken release). Version cadence from step 5 supports
   update-breakage claims.
10. **Synthesis** — Transform per subject: complaint themes ranked by count
    with verbatim evidence; praised workflows with the marketed-vs-actual
    divergence named; vocabulary bank (exact phrases, platform, date);
    pricing quotes; segment cuts where reviewer type is visible (company
    size, role, plan); verdict — the top 2 exploitable gaps and the top 2
    moat elements, citing theme counts.

## Verification (hard rules)

- A theme needs ~3+ independent reviews (distinct reviewers, ideally distinct
  platforms) or it is tagged "weak signal" — never presented as a pattern.
- Quotes are verbatim with platform + date, or they are dropped. No
  paraphrase, no ellipsis-editing that changes meaning.
- Key claims (dominant complaint, moat workflow) triangulate across ≥2
  platforms where 2+ platforms had data; single-platform findings are tagged
  ASSUMED.
- Material cross-platform rating divergence (e.g. G2 4.5 vs Trustpilot 2.1)
  is a `[CONFLICT]` — investigate the cause (segment mix, recency) and report
  both, never average silently.
- LLM output (`gemini_reviews_report`, Perplexity) is never a primary source —
  it organizes evidence, it does not create it.
- Review-volume and velocity numbers carry their window ("~40 reviews/month
  over the last 6 months visible") — platforms expose partial histories, say so.

## Output instructions

Template `voice-of-customer`. Required sections:

1. **Executive summary** — per subject: the single biggest complaint theme,
   the single biggest moat element, sentiment direction. One line each, with
   counts.
2. **Platform coverage & review health** — per subject × platform: rating,
   review count, velocity, trend direction, selection-bias caveat. Platforms
   unreachable marked, not omitted silently.
3. **Complaint themes** — ranked table: theme / count / platforms / severity /
   1-2 verbatim quotes. Weak signals in a separate sub-list.
4. **Praised workflows — the real moat** — what customers actually value;
   marketed-vs-actual divergence named explicitly where it exists.
5. **Customer vocabulary bank** — 10-20 verbatim phrases with platform + date,
   grouped by theme. This is the messaging input; do not summarize it away.
6. **Pricing archaeology** — quoted-price testimonials with source URL + date;
   "offline pricing" inferred only when a review says so, tagged ASSUMED.
7. **Segment cuts** — themes by reviewer type (company size, role, plan)
   where visible; say when segmentation was not possible.
8. **Focus findings** (only when `focus` was given) — evidence for the
   requested lens, e.g. churn reasons ranked by count.
9. **Source log** — every platform with tool + retrieval date; confidence
   ladder (VERIFIED = 2+ platforms / ASSUMED = single platform / weak
   signal); `[CONFLICT]` register; refresh recommendation (monthly for
   fast-moving categories).

## Guards (failure modes to refuse)

- **Anecdote-as-theme:** a finding built on 1-2 reviews. Label it weak signal
  or cut it — never let a vivid single quote drive the verdict.
- **Paraphrased voice:** a vocabulary or quotes section written in the agent's
  words. If verbatim text wasn't captured, the section says so — it is not
  reconstructed.
- **Average-score report:** if no dates were obtainable anywhere, the report
  must say velocity analysis was impossible and downgrade confidence — a bare
  4.3 with no trend is not a VoC finding.
- **Silent selection bias:** any conclusion ("customers love X") without the
  up-front caveat that review platforms skew extreme and Reddit/forums skew
  technical.
- **Single-platform VoC presented as cross-platform:** if only one platform
  yielded data for a subject, the report header for that subject says
  "partial coverage: {platform} only".
- **LLM hallucination laundering:** a theme or quote present in the
  `gemini_reviews_report` output but not traceable to a raw review in steps
  3/5/6/7. Drop it and note the drop in the source log.
