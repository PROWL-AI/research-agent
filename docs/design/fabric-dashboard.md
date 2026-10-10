# Prowl Research — dashboard specification

Design route: super-ux → sheleg-design / copywriting → task-pipeline. Product register, Editorial Luxury inherited from Prowl. Dials: variance 4 (recognisable brand), motion 2 (only paint transitions), density 7 (operator journal). No decorative motion, gradients or fabricated counters.

## Information architecture

| Surface | Question | Primary content/action |
|---|---|---|
| Обзор | Что требует внимания сейчас? | Waiting/working/failed, latest requests, health and last refresh |
| Запросы | Что агенту поручили? | Search + state filter + real/tutorial filter; runbook/tool, requester, chain, date, price |
| Детали | Что произошло и чему доверять? | Input and config snapshot, ordered calls with duration/status/cost, readable data table, report text, sources/ledger, raw JSON, cancellation/decision |
| Цепочки | Где используется результат? | Group by caller-declared chain; project/node/parent/trace. Explicit no verified binding claim |
| Расходы | За что платим и что не посчитано? | UTC daily chart and accessible table; by model/tool, priced/unpriced calls, actual subtotal, no fixture inclusion |
| Настройки | Чем и как выполняем? | Cheap/strong model ids, max parallel jobs, max job duration; revision diff before save; all paid requests require operator decision |
| Обучение | Как безопасно проверить? | Zero-provider sample showing approval → steps → table/report, API examples, runbook inputs and tool-chain guide |

## Layout and visual decisions

Desktop ≥1100: 208px left navigation, content max 1480px, journal plus detail page with persistent breadcrumbs. Medium: 160px navigation; mobile ≤760: horizontal scrollable navigation above content, single column; tables scroll inside their container. Native host title remains outside service UI. Header names Prowl Research, health and freshness, one primary “Новый запрос” action.

Signature: a readable research dossier: compact request rows followed by an ordered evidence trail. Cream surfaces, hairline dividers, sage for action, text state badges. Display Fraunces/Georgia, content Newsreader/Georgia, data JetBrains Mono/monospace. Font assets remain local; no CDN/network dependency. Focus ring 2px; targets ≥40px; labels always visible; colour never carries state alone. Page heading ceiling 40px desktop, 30px mobile. Motion 120/180ms, reduced-motion disables transitions.

## State contract

Loading: heading and explicit loading line; no invented metrics. Empty: explain how a request arrives and offer tutorial/new request. Failed panel: keep other sections and retry. Offline: retain last successful snapshot, timestamp and error. Unknown price: “неизвестно”, partial subtotal “≥”. Approval: input, models, timeout, exact proposal digest/expiry; reject does not dispatch. Cancel: state clearly that completed upstream charges are not undone. Expired/stale: refuse, keep evidence, request a new job. Tutorial: persistent label, explicit filter, never real spend. Settings: dirty edits survive polling; diff before save; stale revision refuses save. Long/raw results bounded with artifact retrieval, never injected as HTML.

## Trust and limits

The adapter reuses the existing research core. Prior KA-03…KA-12 findings remain tracked until individually fixed; evidence labels are reported as model/ledger claims, not independently verified truth. Local service discovery does not establish hub admission. Budget charts are accounting, not hard caps. A submitted tool job accepts arbitrary tool parameters within upstream schema/authorization; calls are bounded by timeout and operator approval. Cross-agent chaining belongs to Fabric `agent.call`, with this service returning job handles and machine-readable results.

## Acceptance

Tests and browser receipts live in ../evidence/fabric-dashboard/VERIFICATION.md. Source owners: service/store.py (state), runtime.py (execution), app.py (HTTP/auth), protocol.py (MCP), static/app.js + styles.css (presentation). Product outcome remains unobserved until operator use.
