---
name: ai-visibility-audit
description: >-
  Measures how visible a brand/domain is inside AI answers: mentions and
  citations across ChatGPT, Claude, Gemini, Perplexity, and Google AI Mode,
  share of voice vs competitors, and the top pages AI engines actually cite.
  Output is an AI-visibility scorecard plus retrieval-hygiene fixes grounded
  in what the winning cited pages look like. Use for AI SEO, GEO (generative
  engine optimization), and LLM-visibility questions about a domain.
version: "1.0"
inputs:
  - { name: domain, type: "domain", required: true, doc: "The brand/domain whose AI visibility is being audited." }
  - { name: market, type: "string", required: true, doc: "Product category / niche — drives the prompt fan-out (e.g. 'email marketing software')." }
  - { name: competitors, type: "list[domain]", required: false, max: 4, doc: "Named competitors for share-of-voice benchmarking. If omitted, taken from top_domains results." }
tools:
  - google_ai_mode
  - dataforseo_serp_google_ai_mode
  - serpapi_google_ai_overview
  - dataforseo_ai_chatgpt_responses
  - dataforseo_ai_chatgpt_scraper
  - dataforseo_ai_claude_responses
  - dataforseo_ai_gemini_responses
  - dataforseo_ai_perplexity_responses
  - dataforseo_ai_llm_mentions
  - dataforseo_ai_llm_mentions_aggregated
  - dataforseo_ai_llm_mentions_cross_aggregated
  - dataforseo_ai_llm_mentions_top_domains
  - dataforseo_ai_llm_mentions_top_pages
  - dataforseo_ai_keyword_volume
  - dataforseo_content_search
  - dataforseo_bl_bulk_ranks
  - majestic_get_index_item_info
  - firecrawl_scrape_page_seo
  - firecrawl_scrape_page_html
  - firecrawl_map_domain
  - seo_growth_audit
  - seo_growth_check_technical
budget: { max_tool_calls: 50, max_usd: 2.50, max_minutes: 25 }
outputs: { report_template: ai-visibility-scorecard, formats: [markdown, html] }
---

# AI Visibility Audit

**Goal:** a quantified picture of how visible a brand is inside AI answers —
which engines mention it, which cite its pages, how its share of voice
compares to competitors — plus a diagnosis (not-crawled / not-cited /
not-mentioned) and retrieval-hygiene fixes proven against the pages AI
engines actually cite today.

## Principles (read first)

- **One engine is an anecdote.** A claim about AI visibility requires at
  least two independent engines; a claim about "AI search" requires the full
  fan-out. ChatGPT, Claude, Gemini, and Perplexity are independent of each
  other; the Google AI surface (google_ai_mode, dataforseo_serp_google_ai_mode,
  serpapi_google_ai_overview) is ONE engine behind three renderers — it counts
  once toward independence. Report per-engine, never blended.
- **Mentions and citations are different problems.** Being *named* in an
  answer without a page being *cited* means the model knows the brand but
  finds nothing worth retrieving. Track both, always.
- **Share of voice, not absolute counts.** Mention counts mean nothing alone;
  benchmark target vs competitors inside the SAME prompts.
- **The LLM responses are the subject of study, not a source.** Here the AI
  answers ARE the data. Any fact they assert about the market, pricing, or
  features must come from a data tool — never quote answer content as fact.
- **AI answers drift.** Every engine result is a point-in-time sample. No
  engine finding is valid without its retrieval date attached.

## Sequence

1. **Scope** — Transform: normalize domains (strip scheme/path/www). Cap
   `competitors` at 4. If none given, defer to step 4 (derive from
   `dataforseo_ai_llm_mentions_top_domains`).
2. **Prompt set construction** — Transform: build the category prompt set
   from `market` spanning three intents: problem ("how do I {job-to-be-done}"),
   solution ("best {market} tools", "top {market} for {use case}"),
   comparison ("{market} alternatives", "{domain brand} vs {competitor}").
   The arithmetic is the budget: each prompt costs one call per engine in
   step 3 (5 engines), so CAP the set at 5 prompts (25 calls) — the
   brand-sentiment check runs in step 4 via `dataforseo_ai_llm_mentions`,
   not as extra fanned-out prompts.
3. **Engine fan-out** — Fan-out: for each of the ≤5 category prompts, run
   Parallel: `dataforseo_ai_chatgpt_responses` +
   `dataforseo_ai_claude_responses` + `dataforseo_ai_gemini_responses` +
   `dataforseo_ai_perplexity_responses` + `google_ai_mode` (on_error=skip).
   For `_responses` tools use `user_prompt` (not `prompt`) and `model_name`
   (not `model`). Record the retrieval date with every response. If
   `dataforseo_ai_chatgpt_responses` fails, fall back to
   `dataforseo_ai_chatgpt_scraper` (web-UI view, on_error=skip) — and note
   API-vs-UI provenance, never mix them silently.
4. **Mentions measurement (aggregate)** — Fan-out `dataforseo_ai_llm_mentions`
   for target + each competitor (on_error=skip); then
   `dataforseo_ai_llm_mentions_top_domains` and
   `dataforseo_ai_llm_mentions_top_pages` for the 3-5 core category keywords;
   `dataforseo_ai_llm_mentions_cross_aggregated` across all domains for share
   of voice; `dataforseo_ai_llm_mentions_aggregated` for the target's trend
   (on_error=skip). If competitors were not supplied, Transform: pick the top
   2-4 non-target domains from `top_domains` as the benchmark set.
5. **Google AI cross-validation** — Parallel for the top-3 prompts:
   `dataforseo_serp_google_ai_mode` + `serpapi_google_ai_overview`
   (on_error=skip). These are SAME-ENGINE redundancy (one upstream surface,
   three renderers) — they buy resilience against a single renderer's parse
   quirks, NOT triangulation; disagreement on who is mentioned is a
   `[CONFLICT]` about the renderers, not about the market.
6. **Citation extraction** — Transform: from all engine responses, extract
   every cited domain and page. Compute: mention share per domain per engine,
   citation share per domain per engine, and the mentioned-not-cited list
   (named in answer text, absent from citations). Cited third-party domains
   (review sites, listicles, docs) are partnership/backlink targets — list
   them separately.
7. **Winning-page scrape** — Fan-out `firecrawl_scrape_page_seo` on the top
   2-3 cited pages of the target AND of the top-2 competitors (on_error=skip).
   Transform: what do pages AI cites actually look like — structure, headings,
   schema, freshness, Q→A→evidence shape, word count. This comparison is the
   mandatory ground for every fix recommendation.
8. **Technical crawlability** — `firecrawl_scrape_page_html` on robots.txt
   (AI-bot blocks: GPTBot, ClaudeBot, PerplexityBot, Google-Extended) and on
   the homepage; follow sitemap acquisition (§1.15: robots.txt `Sitemap:`
   lines → canonical probes) and pass `sitemap_xml`/`sitemap_urls` to
   `seo_growth_audit` on the target's key cited-page HTML, or
   `seo_growth_check_technical` when HTML is thin (on_error=skip). Report
   `ai_retrieval_score` explicitly — a strong overall score with a weak AI
   retrieval score is the classic "crawled but not citable" pattern.
   `firecrawl_map_domain` (on_error=skip) to check the brand's content
   footprint exists at all.
9. **Authority context** — `dataforseo_bl_bulk_ranks` for all domains (one
   batched call) + `majestic_get_index_item_info` batched (on_error=skip) +
   `dataforseo_content_search` for the target brand (on_error=skip).
   Transform: does citation share track link authority, or is a
   lower-authority competitor out-citing the target (structure beats
   authority → the fix is content, not links)? `dataforseo_ai_keyword_volume`
   for the category (on_error=skip) as a directional note on how much demand
   is shifting to AI search.
10. **Diagnosis** — Transform: classify every visibility gap into exactly one
    bucket, with evidence: **not-crawled** (AI-bot blocks, non-indexable,
    JS-only rendering — technical fix), **not-cited** (crawled, mentioned,
    but pages not retrieved — structure/authority fix), **not-mentioned**
    (absent from answer text entirely — awareness/PR fix).
11. **Synthesis** — Transform: AI-visibility scorecard (brand × engine ×
    mentioned/cited), share-of-voice table, and fixes ranked by expected
    impact — each fix citing the winning-page comparison from step 7.

## Budget degradation (drop order)

The engine fan-out dominates the budget (5 prompts x 5 engines = 25
calls of 50). When it tightens, drop in this order: (1) engine fan-out
reduced to the top-3 prompts, (2) Google AI cross-validation to the top-2
prompts, (3) winning-page scrapes to 2 pages total. The mentions /
share-of-voice aggregation (step 4) is never dropped — without it there is
no scorecard.

## Verification (hard rules)

- Every engine finding carries its retrieval date; results without one are
  dropped from evidence.
- A "brand X is mentioned / not mentioned" claim needs ≥2 engines or it is
  tagged ASSUMED. Google AI claims need ≥2 of `google_ai_mode`,
  `dataforseo_serp_google_ai_mode`, `serpapi_google_ai_overview` agreeing;
  disagreement → `[CONFLICT]`.
- Share-of-voice numbers state their denominator (prompts × engines × date).
- LLM answer CONTENT is never evidence about the market — only about what the
  engine said. Market facts come from data tools.
- Scraper-vs-API provenance is labelled per row; the two are different
  samples, not confirmations of each other.

## Output instructions

Template `ai-visibility-scorecard`. Required sections:

1. **Executive summary** — overall visibility verdict (strong / fragmented /
   invisible) and the top 3 fixes, one line each, with evidence.
2. **Methodology & retrieval dates** — engines queried, prompt list, dates,
   and the LLM-as-subject caveat stated once, prominently.
3. **AI visibility scorecard** — matrix: brand × engine, cell =
   mentioned / cited / absent (with sentiment note where an engine
   characterizes the brand negatively).
4. **Share of voice** — cross-aggregated mentions and citation share vs
   competitors, with denominators.
5. **Citation analysis** — top cited pages per brand; third-party citation
   sources worth targeting; the mentioned-not-cited list.
6. **Diagnosis** — not-crawled / not-cited / not-mentioned buckets with the
   evidence for each classification.
7. **Retrieval-hygiene fixes** — ranked by expected impact; each grounded in
   the winning-page comparison (structure, schema, freshness, AI-bot access).
8. **Source log** — every finding with tool + retrieval date; confidence
   ladder (VERIFIED = 2+ engines/data sources, ASSUMED = single);
   `[CONFLICT]` register; refresh recommendation (monthly — answers drift).

## Guards (failure modes to refuse)

- **Single-prompt conclusions.** If the prompt fan-out collapsed to 1-2
  working prompts, say the audit is inconclusive — do not extrapolate.
- **Single-engine verdicts.** One engine's answer is an anecdote; never write
  a visibility claim from it alone.
- **Undated engine results.** AI answers drift; a result without a retrieval
  date is not evidence.
- **Fix without comparison.** No retrieval-hygiene recommendation that is not
  grounded in what the currently-cited pages actually look like.
- **LLM as market source.** Never quote answer content (market shares,
  pricing, feature claims) as fact — it is the subject of study only.
- **False invisibility.** A failed scraper call is not "the brand is
  invisible" — distinguish tool failure from genuine absence before
  diagnosing.
