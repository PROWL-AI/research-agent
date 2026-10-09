---
name: seo-site-audit
description: >-
  Full technical + content + authority SEO audit of one domain: DataForSEO
  site crawl and Lighthouse, the 20-section SEO Growth audit incl. AXO /
  vector semantics / AI-content hygiene / pattern detection, backlink profile
  cross-checked against Majestic, 12-month trend lines, and AI retrieval
  visibility. Output is a prioritized fix list with evidence, severity, and
  effort/impact per finding. Use for "SEO audit", "why did our traffic drop",
  "technical SEO review", or AI-visibility/GEO readiness checks.
version: "1.0"
inputs:
  - { name: domain, type: "domain", required: true, doc: "Domain to audit, e.g. example.com." }
  - { name: focus, type: "string", required: false, doc: "Optional emphasis: technical | content | ai-visibility. Shifts depth, never skips the spine." }
tools:
  - seo_growth_audit
  - seo_growth_check_technical
  - firecrawl_scrape_page_seo
  - firecrawl_scrape_page_html
  - firecrawl_map_domain
  - dataforseo_onpage_task_post
  - dataforseo_onpage_summary
  - dataforseo_onpage_pages
  - dataforseo_onpage_duplicate_tags
  - dataforseo_onpage_links
  - dataforseo_onpage_non_indexable
  - dataforseo_onpage_resources
  - dataforseo_onpage_lighthouse
  - dataforseo_bl_summary
  - dataforseo_bl_referring_domains
  - dataforseo_bl_anchors
  - dataforseo_bl_bulk_ranks
  - dataforseo_bl_bulk_spam_score
  - dataforseo_bl_history
  - dataforseo_bl_timeseries_summary
  - majestic_get_index_item_info
  - majestic_get_topics
  - spyfu_get_domain_stats
  - spyfu_get_top_pages
  - spyfu_get_most_valuable_keywords
  - spyfu_serp_analysis
  - dataforseo_labs_ranked_keywords
  - dataforseo_labs_domain_rank_overview
  - dataforseo_labs_competitors_domain
  - dataforseo_labs_bulk_traffic_estimation
  - dataforseo_labs_historical_rank_overview
  - dataforseo_labs_relevant_pages
  - dataforseo_serp_google_organic
  - dataforseo_domain_technologies
  - dataforseo_domain_whois
  - dataforseo_content_search
  - dataforseo_content_sentiment
  - dataforseo_ai_llm_mentions
  - dataforseo_ai_llm_mentions_top_domains
  - google_ai_mode
budget: { max_tool_calls: 80, max_usd: 3.00, max_minutes: 30 }
outputs: { report_template: seo-site-audit, formats: [markdown, html] }
---

# SEO Site Audit

**Goal:** a complete, evidence-backed SEO health assessment of one domain —
technical crawl, on-page and content quality across the 20-section SEO
Growth audit (incl. AXO, vector semantics, AI-content hygiene, grey/black
pattern detection), runtime performance, authority with a second-index
cross-check, and AI retrieval visibility — delivered as a prioritized fix
list, not a score dump. Every finding carries evidence, severity, and an
effort/impact estimate; quick wins come first.

## Principles (read first)

- **The SEO Growth audit is the spine; the crawl is the X-ray.**
  `seo_growth_*` reads individual pages deeply (content, entities, AXO, AI
  hygiene); `dataforseo_onpage_*` sees site-wide structure (broken links,
  duplicates, indexability). Neither substitutes for the other — a finding
  confirmed by both is the highest-confidence class.
- **No sitemap, no crawl-discovery claims.** `seo_growth_audit` and
  `seo_growth_check_technical` treat a sitemap as present only when
  `sitemap_xml` is passed. Follow the acquisition protocol exactly; if it
  fails, tag every sitemap-dependent check ASSUMED.
- **Authority needs two indexes.** DataForSEO and Majestic run independent
  crawls. Disagreement >20 points on authority = `[CONFLICT]`, stated as a
  range — never averaged silently. TrustFlow far below CitationFlow marks a
  quantity-over-quality link profile.
- **A snapshot without a trend is a diagnosis without a pulse.** Always
  request 12 months of history (SpyFu domain stats, rank overview, backlink
  timeseries). Traffic-drop questions are answered by the trend, not the
  current value.
- **One crawl, one task.** `dataforseo_onpage_task_post` is a paid,
  non-retryable task. Every onpage read depends on its `task_id`; never
  submit a second crawl for the same target in one run.

## Sequence

1. **Scope** — Transform: normalize the domain (strip scheme/path/www),
   resolve the origin (scheme + host). Note `focus` if given — it deepens
   the matching sections, it never removes a step.
2. **Crawl kickoff + homepage scrape** — Parallel:
   `dataforseo_onpage_task_post` with `target="{domain}"`,
   `max_crawl_pages=200` (async — retain the `task_id`; every step-7 read
   depends on it) + `firecrawl_scrape_page_seo` on the homepage (raw HTML +
   `seo_data` in one call).
3. **SpyFu baseline** — Parallel: `spyfu_get_domain_stats` with
   `past_n_months=12` (trend arrays, not just the snapshot) +
   `spyfu_get_top_pages` with `page_size=10` +
   `spyfu_get_most_valuable_keywords`.
4. **Sitemap acquisition (hard dependency for step 6)** — If the user
   supplied a sitemap URL, scrape it first. Else
   `firecrawl_scrape_page_html` on `https://{origin}/robots.txt`, parse
   every `Sitemap:` line (case-insensitive). If none, probe in order:
   `/sitemap.xml`, `/sitemap_index.xml`, `/wp-sitemap.xml`,
   `/sitemap/sitemap.xml` until one returns usable XML. Fetch the chosen
   document with `firecrawl_scrape_page_html`. Transform: retain the body
   as `sitemap_xml` and parse `<loc>` values into `sitemap_urls`.
   `firecrawl_map_domain` may run in parallel for URL discovery but does
   NOT substitute for raw `sitemap_xml`.
5. **Fan-out scrape** — For each of the top-10 pages from step 3 (fallback:
   `dataforseo_labs_relevant_pages`, then sitemap URLs):
   `firecrawl_scrape_page_seo` per page (on_error=skip; 5+ pages minimum
   for a site-level verdict, else say the audit is homepage-weighted).
6. **Fan-out SEO Growth audit (the spine)** — For each scraped page:
   `seo_growth_audit` with `html_content=$item.html`, `page_url`,
   `seo_data=$item.seo_data`, and the SAME site-wide `sitemap_xml` /
   `sitemap_urls` from step 4. Parallel: `seo_growth_check_technical` with
   `trust_pages_status` + `sitemap_xml` for the site-wide sweep (trust
   pages, redirect chains, parametric explosion, crawl traps, soft 404s)
   (on_error=skip). Transform: average the five dimension scores
   (crawl_efficiency, ai_retrieval, intent_fit, entity_trust,
   conversion_readiness) across pages; collect unique critical fixes and
   quick wins; flag site-wide patterns (e.g. all pages missing Q→A→evidence
   structure, uniform template intros = AI-hygiene risk).
7. **Crawl analysis** (all depend on the step-2 `task_id`) — Parallel:
   `dataforseo_onpage_summary` + `dataforseo_onpage_pages`
   (`filters=["resource_type","=","html"]`, sort by word count for thin
   content) + `dataforseo_onpage_duplicate_tags` +
   `dataforseo_onpage_links` (broken internal links, redirect chains) +
   `dataforseo_onpage_non_indexable` (unexpected noindex/blocked pages) +
   `dataforseo_onpage_resources` (render-blocking, oversized assets)
   (on_error=skip per call, never per step).
8. **Performance** — `dataforseo_onpage_lighthouse` for the homepage with
   `for_mobile=true` (default), plus desktop, plus the highest-traffic page
   (on_error=skip). Quote every score with device AND throttling context —
   a mobile score and a desktop score are different instruments.
9. **Authority & backlinks** — Parallel: `dataforseo_bl_summary` +
   `dataforseo_bl_referring_domains` (limit=100, order by rank desc) +
   `dataforseo_bl_anchors` (limit=50; >30% exact-match anchors = manipulative
   link building signal) + `dataforseo_bl_timeseries_summary` +
   `dataforseo_bl_history` for velocity + `majestic_get_index_item_info`
   (TrustFlow/CitationFlow second opinion) + `majestic_get_topics`
   (topical-trust mismatch = paid-link signal) (on_error=skip).
10. **Keyword footprint & trend** — `dataforseo_labs_ranked_keywords`
    (limit=200) + `dataforseo_labs_domain_rank_overview` +
    `dataforseo_labs_historical_rank_overview` for the 12-month visibility
    trend (on_error=skip). Transform: align the SpyFu trend from step 3
    with the Labs trend — a drop visible in both is VERIFIED; in one only,
    tag it and say which.
11. **SERP ownership** — Transform: top-5 keywords from step 10 → fan-out
    `dataforseo_serp_google_organic` + `spyfu_serp_analysis` per keyword
    (on_error=skip). Note unclaimed features (featured snippet, PAA) on
    SERPs the domain already ranks page-1 for.
12. **Domain intel** — Parallel: `dataforseo_domain_technologies` +
    `dataforseo_domain_whois` (age = trust signal) +
    `dataforseo_content_search` + `dataforseo_content_sentiment` for the
    brand (on_error=skip).
13. **AI visibility** — Parallel: `google_ai_mode` for 3 product-category
    queries + `dataforseo_ai_llm_mentions` with `target="{domain}"` +
    `dataforseo_ai_llm_mentions_top_domains` for the same queries
    (on_error=skip). Cross-read against the step-6 `ai_retrieval_score` and
    AXO section: low retrieval score AND absent from AI answers = the same
    root cause; say so.
14. **Competitive context** — `dataforseo_labs_competitors_domain` →
    Transform: top 3 → `dataforseo_bl_bulk_ranks` +
    `dataforseo_labs_bulk_traffic_estimation` +
    `dataforseo_bl_bulk_spam_score` in one batched pass each. Context only:
    severity is calibrated against peers, not set by them.
15. **Synthesis** — Transform: merge crawl issues + SEO Growth findings +
    Lighthouse + authority into ONE deduplicated issue list. Each item:
    evidence (tool + page/URL), severity (critical/high/medium/low),
    effort (S/M/L), impact (high/medium/low), and the exact fix. Sort by
    impact ÷ effort; quick wins (impact ≥ medium, effort S) lead the report.

## Verification (hard rules)

- Key numbers (traffic, authority, backlinks, scores): ≥2 independent
  sources or tag ASSUMED. Majestic vs DataForSEO authority disagreement
  >20 points → `[CONFLICT]`, report the range, never average.
- LLM output (`google_ai_mode`, mention sentiment) is never a primary
  source for a traffic or ranking claim — cross-check against a data tool.
- No bare estimates: every traffic/visibility figure carries its error band
  and a VERIFIED/ASSUMED tag; trends verified in two providers are VERIFIED.
- Lighthouse scores are quoted only with device and throttling context.
- A finding without evidence in the crawl, audit, or backlink data does not
  enter the fix list. Scores are quoted as ranges across audited pages,
  never as a single-site scalar from the homepage alone.

## Output instructions

Template `seo-site-audit`. Required sections:

1. **Quick wins** — table first: fix / evidence / effort / expected impact.
   Max 10 rows, all effort-S.
2. **Executive summary** — overall score (range across pages), five
   dimension scores, the 3 most urgent problems, one line each.
3. **Technical SEO** — crawl health: indexability, duplicates, broken
   links, redirect chains, crawl waste/traps, soft 404s; each with affected
   URLs and the exact fix.
4. **On-page & content quality** — findings grouped by the audit's 20
   sections (Technical SEO → Pattern Detection), severity-tagged, with
   per-page breakdown where issues are page-specific.
5. **Performance** — Lighthouse per page per device with context; CWV
   failures mapped to the resource evidence from step 7.
6. **Authority & backlinks** — profile summary, anchor distribution
   verdict, velocity trend (12 months), Majestic cross-check with any
   `[CONFLICT]`s, topical-trust mismatch, spam signals.
7. **Keywords & SERP ownership** — ranked footprint, 12-month visibility
   trend (the traffic-drop answer lives here), top-5 SERP feature map.
8. **AI visibility & AXO** — AI retrieval score, mention matrix per engine,
   AXO/vector-semantics/AI-hygiene findings and their exact fixes.
9. **Competitive context** — peer authority/traffic table, used only to
   calibrate severity.
10. **Prioritized fix list** — the full deduplicated list: evidence /
    severity / effort / impact / exact fix, sorted impact ÷ effort.
11. **Source log** — every figure with tool + retrieval date; confidence
    ladder; `[CONFLICT]` register; refresh recommendation (quarterly, or
    monthly during active fix work).

## Guards (failure modes to refuse)

- **Recommendation without evidence:** no fix enters the list unless the
  crawl, SEO Growth audit, Lighthouse, or backlink data shows it. "Best
  practice" suggestions with no observed defect are refused.
- **Homepage-only "site audit":** if fewer than 5 pages were scraped and
  audited, say the report is homepage-weighted in the summary — do not
  present it as a site-wide verdict.
- **Sitemap-free crawl claims:** if sitemap acquisition failed, tag every
  sitemap/hreflang/RSS-sync finding ASSUMED and state what a refresh must
  fetch — never infer a sitemap from homepage HTML.
- **Snapshot diagnosis:** a traffic-drop question answered from current
  values alone is refused. If no 12-month trend was obtainable, say the
  drop question is UNANSWERED and list the missing data.
- **Lighthouse without context:** a bare "Performance: 62" is refused —
  device and throttling always travel with the number.
- **Content strategy from technical data:** do not prescribe editorial
  calendars or topic strategies from crawl/Lighthouse data; content
  direction requires the keyword and SERP evidence of steps 10-11, and is
  stated as such.
