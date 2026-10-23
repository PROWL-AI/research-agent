# Prowl Research — dashboard specification

surface_class: internal (a signed-in operator console of a loopback service, opened through Fabric Dashboards; no logged-out reader, no public route).

Design route: super-ux → sheleg-design / copywriting → task-pipeline. Product register, Editorial Luxury inherited from Prowl. Dials: variance 4 (recognisable brand), motion 2 (only paint transitions), density 7 (operator journal). No decorative motion, gradients or fabricated counters.

## Information architecture

| Surface | Question | Primary content/action |
|---|---|---|
| Обзор | Что требует внимания сейчас? | Waiting/working/failed counts; spend today, 7 and 30 days and per delivered report (M1-B); «Требуют внимания» holds pending decisions and failures of the last 3 days only, tutorials excluded, older failures folded into one counted line to the filtered list; latest requests, health and last refresh |
| Запросы | Что агенту поручили? | Search + state filter + real/tutorial filter; runbook/tool, requester, chain, date, price |
| Детали | Что произошло и чему доверять? | Input and config snapshot, ordered calls with duration/status/cost, readable data table, report text, sources/ledger, raw JSON, cancellation/decision |
| Цепочки | Где используется результат? | Group by caller-declared chain; project/node/parent/trace. Explicit no verified binding claim |
| Расходы | За что платим и что не посчитано? | UTC daily chart and accessible table; by model/tool, priced/unpriced calls, actual subtotal, no fixture inclusion |
| Настройки | Чем и как выполняем? | Cheap/strong model ids, max parallel jobs, max job duration; revision diff before save; all paid requests require operator decision |
| Обучение | Как безопасно проверить? | Zero-provider sample showing approval → steps → table/report, API examples, runbook inputs and tool-chain guide |

## Layout and visual decisions

Layout (wave 5; kit `fabric-dashboard-kit@1.1.3` since 2026-10-23 (B-079, B-084), DEC-0036): sticky kit chrome (title, service chip, freshness, refresh, theme and scheme pickers) with the section navigation below it; links that do not fit fold into the kit's More menu (labelled «Ещё»; pickers labelled in Russian), never a sideways-scrolling strip. Content in `.fd-page`; grids are fluid (`auto-fit` columns), tables scroll in their own labelled `.fd-scroll` box; usable from 360 CSS px. Colours come only from the kit tokens; the estate theme and scheme follow the host's appearance. Journal plus detail page with persistent breadcrumbs. Native host title remains outside service UI. Header names Prowl Research, the service state chip (from `/.well-known/fabric-service` status: «Работает», «Работает с ограничениями», «Останавливается»; reasons in its tooltip) and freshness, one primary “Новый запрос” action.

Signature: a readable research dossier: compact request rows followed by an ordered evidence trail. Surfaces, dividers and the action colour come from the active estate theme (`graphite` by default; seven kit themes × light/dark, chosen by the host or the pickers), so no colour is fixed here; hairline dividers and text state badges carry the dossier feel in every theme. Display Fraunces/Georgia, content Newsreader/Georgia, data JetBrains Mono/monospace. Font assets remain local; no CDN/network dependency. Focus ring 2px; targets ≥40px; labels always visible; colour never carries state alone. Page heading ceiling 40px desktop, 30px mobile. Motion 120/180ms, reduced-motion disables transitions.

## State contract

Loading: heading and explicit loading line; no invented metrics. Empty: explain how a request arrives and offer tutorial/new request. Failed panel: keep other sections and retry. Offline: retain last successful snapshot, timestamp and error. Unknown price: “неизвестно”, partial subtotal “≥”. A failed request leads with what happened and the next step by error code; the raw message, code and run terminal code sit under «Подробности» (M1-B). Source coverage («Охват источника») is derived from the tools a job used, in Russian, on the data and sources tabs of tool and research jobs (B-078). Approval: input, models, timeout, exact proposal digest/expiry; reject does not dispatch. Cancel: state clearly that completed upstream charges are not undone. Expired/stale: refuse, keep evidence, request a new job. Tutorial: persistent label, explicit filter, never real spend. Settings: dirty edits survive polling; diff before save; stale revision refuses save. Long/raw results bounded with artifact retrieval, never injected as HTML.

## Trust and limits

The adapter reuses the existing research core. KA-03…KA-12 are fixed in the core (waves 2–4); a ledger `verified` means a quote located in the stored source or two independent sources (ledger schema 2), not an independently audited truth, and live acceptance is wave 6. Local service discovery does not establish hub admission; the callee side of delegation is built (wave 5) and the host chain waits for the estate issuer. Budget figures are accounting; the run's limits are pre-call checks (tools by the runbook budget, models by `max_llm_usd`) and can overshoot by one call. A submitted tool job accepts arbitrary tool parameters within upstream schema/authorization; calls are bounded by timeout and operator approval. Other agents call this service directly with delegation tokens (DEC-0039); it returns job handles and machine-readable results.

## Acceptance

Tests and browser receipts live in ../evidence/fabric-dashboard/VERIFICATION.md. Source owners: service/store.py (state), runtime.py (execution), app.py (HTTP/auth), protocol.py (MCP), static/app.js + styles.css (presentation). Product outcome remains unobserved until operator use.
