---
name: x-trend-pulse
description: >-
  What people on X (Twitter) are saying, asking and sharing about a topic
  right now, cross-checked against search demand, news and Reddit. Output is a
  pulse of rising conversation THEMES with the posts behind each, the
  questions people ask, and whether the conversation shows up in search.
  Use for trend spotting, "what is new in <topic> this year", launch
  timing, content and positioning ideas, and early signals that search
  data has not caught yet.
version: "1.0"
inputs:
  - { name: topic, type: "string", required: true, doc: "Topic, market, product category or brand, e.g. 'AI agents for e-commerce' or 'subscription app paywalls'." }
  - { name: since, type: "string", required: false, doc: "Earliest post date, YYYY-MM-DD. Default: 90 days before today, stated in the report." }
  - { name: handles, type: "string", required: false, doc: "Optional comma-separated X handles to focus on (no @), e.g. competitors or category voices. Max 20." }
  - { name: geo, type: "string", required: false, doc: "Geography for the search-demand cross-check (ISO country). Default: worldwide, and say so." }
tools:
  - xai_x_search
  - xai_web_search
  - google_trends
  - google_trends_autocomplete
  - serpapi_google_trends
  - google_news
  - bing_news
  - reddit_search
  - youtube_search
  - perplexity_responses
budget: { max_tool_calls: 24, max_usd: 3.00, max_minutes: 20 }
outputs: { report_template: x-trend-pulse, formats: [markdown, html] }
---

# X Trend Pulse

**Goal:** a decision-ready read on what the conversation on X says about a
topic now: the themes rising in posts, the questions people ask, who drives
them, and whether each theme is also visible in search demand, news and
Reddit. X is where a trend is talked about weeks before it is searched; the
report says which themes are still talk only and which already reached
search.

## Principles (read first)

- **X is a leading signal, not proof of demand.** A theme seen only on X is
  "early" until search trends, news or Reddit confirm it. Never call a
  theme a market trend on posts alone.
- **Posts are quoted, not paraphrased into facts.** Every theme cites 2-5
  real posts (URL, author handle, date). A claim inside a post is the
  author's claim: report it as "X says", never as a verified number.
- **Engagement is context, not weight of evidence.** A viral post is one
  post. Count distinct authors per theme; a theme from one author is an
  anecdote.
- **The search window is part of the finding.** State the post window
  (`since` to today) on every theme; a 2026 theme read from 90 days of posts
  says nothing about 2025.
- **xAI answers are model syntheses over posts.** The answer text of
  `xai_x_search` and `xai_web_search` is an LLM summary; only its cited
  URLs are evidence.

## Sequence

1. **Scope** — Transform: from `topic` derive 3-6 query angles: the topic
   itself, its problems ("<topic> not working", "<topic> alternatives"),
   its questions ("how do you <topic>"), and 1-2 adjacent terms. Set
   `since` (default 90 days back, stated). `google_trends_autocomplete` on
   the topic (on_error=skip) to catch real phrasing.
2. **X conversation scan** — `xai_x_search` per angle (2-4 calls), with
   `from_date` = `since` and `allowed_x_handles` when `handles` was given.
   Ask each call for: recurring themes, the questions people ask, example
   posts with handles and dates, and engagement signals, with citations.
   Transform: cluster into themes; per theme keep the cited post URLs,
   distinct authors, and the questions asked. Drop themes with no cited
   post.
3. **Questions people ask** — one `xai_x_search` focused on questions only
   ("what are people asking about <topic>", from `since`). Transform: a
   question list, each with 1-2 cited posts; these feed content and
   positioning ideas.
4. **Search-demand cross-check** — `google_trends` on the top 3-5 theme
   phrasings (12-month view, geo set) + `serpapi_google_trends` on the top
   2 (on_error=skip). Transform: per theme, is it rising in search, flat, or
   absent. Absent = "talk only, early".
5. **News and web cross-check** — `google_news` per top theme + `bing_news`
   (on_error=skip) + one `xai_web_search` for the topic's recent coverage
   (on_error=skip). Transform: dated anchor articles per theme; a theme with
   news coverage has a named driver.
6. **Reddit and video** — `reddit_search` on the topic and its pain
   phrasing + `youtube_search` for video-first topics (on_error=skip).
   Transform: verbatim pain quotes with subreddit and date; agreement with
   X themes strengthens them.
7. **LLM context pass (secondary only)** — at most ONE
   `perplexity_responses` call: "what changed in <topic> since <since>"
   (on_error=skip). Every claim it adds must be re-confirmed by a data tool
   or a cited post before it enters the report.
8. **Synthesis** — Transform: theme board. Each theme: stage (talk only /
   reaching search / mainstream / fading), evidence stack (posts and
   authors, search direction, news, Reddit), the questions it raises, and a
   confidence tag. Order is the framework: conversation, questions, search,
   news, synthesis; the verdict comes last and cites section evidence.

## Verification (hard rules)

- Every theme cites at least 2 X post URLs from at least 2 distinct
  authors, or it goes to the watch list.
- A theme called "rising" needs X evidence plus at least one other signal
  type (search trend, news, Reddit); otherwise it is "talk only, early".
- Numbers quoted from posts (revenue, users, market size) are tagged
  `[CLAIMED BY POST]` with the post URL; they are never presented as
  verified figures.
- `google_trends` values are relative indices (0-100), never search volume;
  say so wherever a reader could mistake them. Every trend figure carries
  geo and window.
- Disagreement between X (rising) and search (declining) is a `[CONFLICT]`:
  report both, never average.

## Output instructions

Template `x-trend-pulse`. Required sections:

1. **Executive summary** — the 3 strongest rising themes with their stage
   and best evidence, the most asked question, and one line on timing
   (early, building, mainstream).
2. **Theme board** — rising / talk only / mainstream / fading / watch list;
   per theme: cited posts (handle, date, URL), distinct authors, search
   direction, news anchor, confidence tag.
3. **Questions people ask** — the question list with cited posts.
4. **Search-demand cross-check** — per theme, trend direction with geo and
   window; relative-index caveat.
5. **News, web and Reddit** — dated anchors and verbatim Reddit quotes per
   theme.
6. **Who drives the conversation** — the handles behind each theme (counts,
   not follower claims), and any concentration on a few authors.
7. **Source log** — every post and figure with tool, retrieval date and
   window; `[CONFLICT]` register; the cost of the X search calls; refresh
   recommendation (weekly for fast topics).

## Guards (failure modes to refuse)

- **One viral post as a trend:** a theme from one author or one post goes
  to the watch list, whatever its engagement.
- **Model summary as evidence:** a theme or number that appears only in
  the xAI answer text, without a cited post, is dropped.
- **Hype as demand:** a theme loud on X but absent from search, news and
  Reddit is reported as "talk only, early", never as market demand.
- **Silent window:** a report without the post window on every theme is
  incomplete; say so in the summary.
- **Missing X source:** if `xai_x_search` is unavailable (not in the live
  catalog, or every call failed), say so prominently in the summary and
  report the pulse from search, news and Reddit only; never imply X was
  read.
