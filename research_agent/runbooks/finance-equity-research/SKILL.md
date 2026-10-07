---
name: finance-equity-research
description: >-
  Structured equity research on a named public company: business understanding,
  5-year financial review with earnings-quality forensics, management &
  governance, risk assessment, and only then a triangulated valuation with an
  explicit bear case and margin of safety. Use for investment research on a
  named company or ticker — not for market scans, private companies, or quick
  price checks.
version: "1.0"
inputs:
  - { name: company, type: "string", required: true, doc: "Company name, e.g. 'Novo Nordisk'." }
  - { name: ticker, type: "string", required: false, doc: "Exchange ticker if known (e.g. 'NVO', 'ASML:AMS'). Resolved in step 1 if omitted." }
  - { name: peers, type: "string", required: false, doc: "Comma-separated peer company names or tickers, max 4 — genuine business-model peers for comps. Discovered in step 8 if omitted." }
tools:
  - google_finance
  - dataforseo_serp_google_finance_ticker_search
  - dataforseo_serp_google_finance_quote
  - dataforseo_serp_google_finance_explore
  - dataforseo_serp_google_finance_markets
  - google_search
  - bing_search
  - firecrawl_search
  - firecrawl_scrape_page_markdown
  - firecrawl_scrape_website
  - firecrawl_map_domain
  - exa_keyword_search
  - exa_get_contents
  - exa_answer
  - google_scholar
  - google_news
  - google_news_light
  - bing_news
  - google_jobs
  - google_trends
  - reddit_search
  - youtube_search
  - youtube_transcripts
  - llm_query_perplexity
  - llm_query_gemini
budget: { max_tool_calls: 50, max_usd: 2.00, max_minutes: 25 }
outputs: { report_template: equity-research, formats: [markdown, html] }
---

# Finance Equity Research

**Goal:** an investment-grade research note on one public company — what the
business actually is, whether the 5-year financials are clean, whether
management allocates capital well, what breaks it, and only then what it is
worth. Order is the framework: business → financials → governance → risk →
valuation. A report that starts from a target price is reverse-engineered
advocacy; refuse to produce it.

## Principles (read first)

- **Order is the framework.** Analysts who open with valuation reverse-
  engineer from the answer. The five stages run strictly in sequence; no
  valuation number may be written before stages 1-4 exist.
- **Form your own view before reading management's.** Write the one-paragraph
  revenue model and moat assessment from data first; only then read the
  earnings-call narrative and mark where the two diverge.
- **5-year tables, not single years.** A single year proves nothing. Organic
  vs acquired growth, the gross-margin trend (cleanest pricing-power signal),
  FCF conversion and ROIC-vs-WACC only exist as trends.
- **Bear case before bull case.** The report is incomplete without a
  quantified bear case, and the margin of safety is measured against the LOW
  end of the intrinsic range, never the midpoint.
- **Data honesty.** This agent has no EDGAR/AlphaSense/Tegus access. Figures
  come from finance aggregators, SERP and scrapes of IR pages — everything
  derived from a summary is ASSUMED by default, and the report must name the
  primary filings a follow-up analyst has to read.

## Sequence

1. **Scope & ticker resolution** — Transform: normalize `company`. If `ticker`
   omitted, `dataforseo_serp_google_finance_ticker_search` +
   `google_search("{company} investor relations stock ticker")`; pick the
   primary listing and note the exchange and currency. Ambiguous names (a
   company and a product sharing a name) are resolved by market cap and IR
   domain — state the choice.
2. **Business understanding (own view first)** — Parallel: `google_finance`
   (company summary, segments if present) + `dataforseo_serp_google_finance_quote`
   (profile) + `firecrawl_map_domain` on the IR site + `firecrawl_scrape_page_markdown`
   on "our business"/segment overview pages. Transform: the revenue model in
   ONE paragraph with no marketing language — who pays, for what, how often;
   recurring vs transactional split; segment mix; geographic mix. Note
   customer concentration: any single customer >20% of revenue is a flagged
   risk.
3. **Moat evidence, not moat adjectives** — Parallel: `google_trends` (brand
   term, 5-year, demand proxy) + `exa_keyword_search` ("{company} competitive
   advantage pricing power churn") + `reddit_search` for unvarnished customer
   voice (on_error=skip). Transform: moat verdict anchored to the 5-year
   gross-margin trend from step 4 — expanding/stable margin = pricing power;
   compressing = the moat claim needs evidence, not adjectives.
4. **5-year financial statement review** — Parallel: `google_finance` +
   `dataforseo_serp_google_finance_quote` + `dataforseo_serp_google_finance_explore`
   for headline statements; `firecrawl_scrape_website` on the IR financials/
   annual-report pages for the multi-year tables (on_error=skip). Transform:
   5-year table — revenue (organic vs acquired: check acquisition history via
   `google_news` M&A hits), gross margin, operating margin, net income, FCF,
   capex (maintenance vs growth split if disclosed), net debt, share count.
   Compute: FCF conversion (<70% of net income sustained 3+ years =
   earnings-quality flag), accruals ratio (>5-8% of assets predicts misses),
   net debt/EBITDA (>4x in a cyclical = flag), ROIC vs WACC estimate.
5. **Earnings-quality forensics** — `google_scholar` ("accruals anomaly
   earnings management {sector}") for the sector's known manipulation
   surfaces + `exa_answer` ("{company} revenue recognition policy change
   restatement SEC comment letter", on_error=skip). Transform: receivables
   growth vs revenue growth, goodwill as % of assets, capitalized-vs-expensed
   cost choices, one-time items pattern. Every forensic flag cites its line
   item; no flag, no section — do not manufacture suspicion.
6. **Management & governance** — `google_search` ("{company} DEF 14A proxy
   statement {latest year}") + `firecrawl_scrape_page_markdown` on the proxy
   or its best summary (on_error=skip) + `google_news_light` on insider
   open-market buys/sells (on_error=skip). Transform: capital-allocation
   track record 5y (buyback price vs today's price, acquisition write-downs,
   dividend coverage), insider open-market BUYS (grants don't count),
   comp-metric manipulation surface (adjusted EBITDA targets management
   controls), related-party transactions.
7. **Risk assessment** — Transform first: the 50% customer-deterioration case
   (revenue -X%, margin compression, covenant headroom from step 4's net
   debt/EBITDA). Then Parallel: `firecrawl_scrape_page_markdown` on the
   contractual-obligations/commitments page if found in step 4's crawl
   (purchase obligations, contingent liabilities — the highest-density page
   in a 10-K, on_error=skip) + `google_jobs` (key-person and function-level
   signals; ghost-jobs caveat) + `google_scholar` + `google_news` for the
   3-year tech-disruption test (who kills this business model and is it
   already funded).
8. **Peer selection** — If `peers` given, validate; else Parallel:
   `dataforseo_serp_google_finance_explore` (sector peers) +
   `exa_keyword_search` ("{company} competitors similar business model") +
   `dataforseo_serp_google_finance_markets` (on_error=skip). Transform: cap
   at 4 GENUINE business-model peers (same revenue model and margin
   structure), not same-sector names with different economics — state the
   inclusion criterion.
9. **Valuation (LAST)** — Fan-out `dataforseo_serp_google_finance_quote` +
   `google_finance` per peer for multiples. Transform three methods: (a) DCF
   from step 4's FCF — WACC × terminal-growth sensitivity table mandatory
   (terminal value is 60-80% of the answer; a single-point DCF is refused);
   (b) comps vs the peer set AND the company's own 5-year multiple range;
   (c) precedent transactions from step 4's M&A scan, +20-30% control
   premium. Bear case BEFORE bull case; margin of safety = entry 20-30%
   below the LOW end of the intrinsic range. `llm_query_perplexity` +
   `llm_query_gemini` as consensus tie-breakers on contested assumptions
   only — never as data.
10. **Data-honesty audit & synthesis** — Transform: count ASSUMED share per
    section (>50% ASSUMED downgrades the section and says so inline), list
    the primary filings a follow-up must read (latest 10-K, two 10-Qs, DEF
    14A, relevant 8-Ks), then write the verdict — stages 1-7 cited, verdict
    last.

## Verification (hard rules)

- Key numbers (revenue, margins, FCF, net debt, multiples): ≥2 independent
  sources (e.g. `google_finance` vs `dataforseo_serp_google_finance_quote` vs
  an IR scrape) or tag ASSUMED. Quote disagreement >2%, ratio disagreement
  >5% → `[CONFLICT]`; one targeted extra lookup to resolve, else surface it.
- Everything derived from aggregator summaries (not a filing or IR page) is
  ASSUMED by default — say so, and route it to the follow-up filings list.
- Estimates (WACC, terminal growth, FCF conversion) carry their inputs and
  an error band; a modeled range with named assumptions, never a confident
  point value.
- LLM output (`llm_query_*`, `exa_answer`) is never a primary source — it
  cannot mint a VERIFIED tag; use it to decide which check to run next.

## Output instructions

Template `equity-research`. Required sections:

1. **Executive summary** — business in one sentence, the single strongest and
   single weakest finding, the verdict in one line.
2. **Business model** — the one-paragraph revenue model, recurring vs
   transactional, segment/geographic mix, customer-concentration flag,
   moat verdict tied to the gross-margin trend.
3. **5-year financial review** — the table, organic vs acquired growth,
   margin trends, FCF conversion, accruals ratio, net debt/EBITDA,
   ROIC vs WACC, capex split.
4. **Earnings-quality forensics** — flags with line items, or an explicit
   "no flags found" with the checks performed.
5. **Management & governance** — capital-allocation scorecard, insider
   buys, comp-metric surface, related parties.
6. **Risk assessment** — 50% deterioration model, off-balance-sheet items,
   key-person, 3-year disruption test; each risk quantified where possible.
7. **Valuation** — DCF sensitivity table, comps vs peers and own 5-year
   range, precedent transactions; bear case first, then base, then bull;
   margin-of-safety entry band.
8. **Contradictions & open questions** — every `[CONFLICT]` and what would
   resolve it.
9. **Source log** — every figure with tool + retrieval date; confidence
   ladder (High/Medium/Low); `[CONFLICT]` register; the follow-up primary-
   filings list (10-K, 10-Qs, DEF 14A, 8-Ks) with what each must confirm.

## Guards (failure modes to refuse)

- **Valuation-first**: any request to "just give me a price target" — refuse;
  the number is only defensible as the output of stages 1-4.
- **Summary-as-filing**: if every financial figure came from aggregators with
  zero IR/filing scrape, label the note "screening-grade, not filing-grade"
  in the summary — do not present it as filing-based research.
- **Bull-only report**: no quantified bear case = the report does not ship.
- **Moat by adjective**: "strong brand / network effects / switching costs"
  without a margin-trend or retention evidence anchor — delete the sentence.
- **Precision theater**: a single-point DCF or intrinsic value without the
  WACC × terminal-growth sensitivity table and the margin-of-safety band.
- **Peers by name only**: comps against same-sector names with different
  business models (e.g. hardware vs subscription) — re-select or state why
  no genuine peer exists.
