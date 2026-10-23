# Prowl Research — scenarios

<!-- Managed with super-ux (ux-contract v4). -->


## Index
| ID | Title | Status |
|---|---|---|
| SCN-001 | Обзор и свежесть | implemented |
| SCN-002 | Найти запрос | implemented |
| SCN-003 | Прочитать результат | implemented |
| SCN-004 | Решение человека | implemented |
| SCN-005 | Отмена | implemented |
| SCN-006 | Учёт расходов | implemented |
| SCN-007 | Настройки | implemented |
| SCN-008 | Безопасное обучение | implemented |
| SCN-009 | Внешний вид, навигация и состояние сервиса | implemented |

### SCN-001: Обзор и свежесть
- **Status:** implemented
- **Product:** unobserved
- **Feature:** Fabric dashboard
- **Traces:** ST-001, FLW-01 (JTBD-01, JRN-01)
- **Entry point:** Fabric Dashboards → Prowl Research
- **Persona:** P-01
- **Preconditions:** Сервис отвечает или соединение потеряно.
- **Steps:**
  1. Открыть обзор; прочитать свежесть и состояние.
  2. Прочитать «Требуют внимания».
- **Expected result:** Видны актуальные счётчики; при offline сохранённый снимок явно устарел. «Требуют внимания» показывает только то, что ждёт сейчас (до 8 строк; свёрнутая строка оформлена ссылкой, сверх них строка «И ещё N в списке запросов»): решения и ошибки последних 3 дней, без учебных и проверочных запросов; более старые ошибки сворачиваются в одну строку со счётчиком и самым частым классом («Ещё 9 ошибок старше 3 дней · чаще всего: прервано»), строка ведёт к списку запросов с фильтром «Ошибка» (M1-B, B-066 принципы 4 и 7).
- **Acceptance criteria:** Видны актуальные счётчики; при offline сохранённый снимок явно устарел; ошибка старше 3 дней не стоит в списке «Требуют внимания», а входит в счётчик свёрнутой строки; учебный запрос в списке не появляется; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs (seeded readability checks: spend-windows, per-report, attention-now-only, older-failures-folded, failure-words-first, coverage-research, coverage-tool) and tests/test_service.py; WebKit PASS 2026-10-23 (M1-B, frames in ../evidence/fabric-dashboard/raw/m1-wave-b/, [receipt](../evidence/fabric-dashboard/raw/webkit-m1-wave-b.json)); see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Обзор

### SCN-002: Найти запрос
- **Status:** implemented
- **Product:** unobserved
- **Feature:** Fabric dashboard
- **Traces:** ST-001, FLW-01 (JTBD-01, JRN-01)
- **Entry point:** Fabric Dashboards → Prowl Research
- **Persona:** P-01
- **Preconditions:** Есть запросы разных состояний.
- **Steps:**
  1. Ввести часть имени; выбрать статус и источник.
- **Expected result:** Показаны только совпадающие запросы; пустой поиск отличается от пустой базы.
- **Acceptance criteria:** Показаны только совпадающие запросы; пустой поиск отличается от пустой базы; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 198a227; see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Запросы

### SCN-003: Прочитать результат
- **Status:** implemented
- **Product:** unobserved
- **Feature:** Fabric dashboard
- **Traces:** ST-001, FLW-01 (JTBD-01, JRN-01)
- **Entry point:** Fabric Dashboards → Prowl Research
- **Persona:** P-01
- **Preconditions:** Запрос завершён.
- **Steps:**
  1. Открыть данные, отчёт, шаги и исходный JSON.
- **Expected result:** Таблица не требует чтения JSON; сырой текст не выполняется как HTML. Запрос с ошибкой сначала говорит, что произошло и какой следующий шаг, словами по коду ошибки (у исследования, прерванного или остановленного по времени, добавлено: агент может продолжить этот прогон, готовые шаги повторно не оплачиваются; сам вызов `research.run` с `resumeJobId` назван под «Подробности»); исходное сообщение, код и код завершения прогона лежат под «Подробности» (B-066 принцип 5). Запрос, который получил ответ инструмента с известным ограничением охвата (TikTok Ads Library: только Европа; у исследования его завершённый шаг, у разового вызова завершённый вызов), показывает плашку «Охват источника» по-русски на вкладках «Данные» и «Источники», и для разового вызова, и для исследования, включая запросы, завершённые до этого изменения (B-078).
- **Acceptance criteria:** Таблица не требует чтения JSON; сырой текст не выполняется как HTML; у ошибки первым видно действие, а не исходный текст провайдера; плашка охвата есть у исследования с `tiktok_ads_library` и у разового вызова этого инструмента; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs (seeded readability checks: spend-windows, per-report, attention-now-only, older-failures-folded, failure-words-first, coverage-research, coverage-tool) and tests/test_service.py; WebKit PASS 2026-10-23 (M1-B, frames in ../evidence/fabric-dashboard/raw/m1-wave-b/, [receipt](../evidence/fabric-dashboard/raw/webkit-m1-wave-b.json)); see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Детали

### SCN-004: Решение человека
- **Status:** implemented
- **Product:** unobserved
- **Feature:** Fabric dashboard
- **Traces:** ST-001, FLW-01 (JTBD-01, JRN-01)
- **Entry point:** Fabric Dashboards → Prowl Research
- **Persona:** P-01
- **Preconditions:** Запрос ожидает решение.
- **Steps:**
  1. Сверить вход и модели; разрешить или отклонить.
- **Expected result:** Действует только непросроченный digest этого запроса; повтор не запускает работу дважды. Карточка решения называет инициатора: проверенного по токену делегирования принципала и агента, «Оператор (панель)» для запроса из панели, или заявленное имя с пометкой «заявлено».
- **Acceptance criteria:** Действует только непросроченный digest этого запроса; повтор не запускает работу дважды; инициатор назван и его источник различим; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 198a227; see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Детали

### SCN-005: Отмена
- **Status:** implemented
- **Product:** unobserved
- **Feature:** Fabric dashboard
- **Traces:** ST-001, FLW-01 (JTBD-01, JRN-01)
- **Entry point:** Fabric Dashboards → Prowl Research
- **Persona:** P-01
- **Preconditions:** Запрос работает.
- **Steps:**
  1. Нажать отмену; прочитать последствия; подтвердить.
- **Expected result:** Задача становится cancelled; уже списанные расходы сохраняются.
- **Acceptance criteria:** Задача становится cancelled; уже списанные расходы сохраняются; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 198a227; see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Детали

### SCN-006: Учёт расходов
- **Status:** implemented
- **Product:** unobserved
- **Feature:** Fabric dashboard
- **Traces:** ST-001, FLW-01 (JTBD-01, JRN-01)
- **Entry point:** Fabric Dashboards → Prowl Research
- **Persona:** P-01
- **Preconditions:** Есть priced и unpriced receipts.
- **Steps:**
  1. Прочитать расходы на обзоре.
  2. Открыть дневной график и таблицу.
- **Expected result:** Учебные данные исключены; неизвестные цены не превращаются в ноль. Обзор показывает расходы за сегодня, 7 и 30 дней рядом и стоимость одного готового отчёта (расходы за 30 дней на число исследований, завершённых за 30 дней); если у части вызовов нет цены, сумма помечена «≥» (известная часть), а при отсутствии цен вовсе стоит «неизвестно»; окна считаются по дням UTC (B-066 принцип 2).
- **Acceptance criteria:** Учебные данные исключены; неизвестные цены не превращаются в ноль; три окна и стоимость отчёта видны без перехода на другую вкладку; без готовых отчётов стоимость отчёта названа словами, а не делением на ноль; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs (seeded readability checks: spend-windows, per-report, attention-now-only, older-failures-folded, failure-words-first, coverage-research, coverage-tool) and tests/test_service.py; WebKit PASS 2026-10-23 (M1-B, frames in ../evidence/fabric-dashboard/raw/m1-wave-b/, [receipt](../evidence/fabric-dashboard/raw/webkit-m1-wave-b.json)); see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Расходы

### SCN-007: Настройки
- **Status:** implemented
- **Product:** unobserved
- **Feature:** Fabric dashboard
- **Traces:** ST-001, FLW-01 (JTBD-01, JRN-01)
- **Entry point:** Fabric Dashboards → Prowl Research
- **Persona:** P-01
- **Preconditions:** Есть текущая revision.
- **Steps:**
  1. Изменить модель/очередь; проверить diff; применить.
- **Expected result:** Новая revision влияет на новые запросы; старый snapshot сохранён.
- **Acceptance criteria:** Новая revision влияет на новые запросы; старый snapshot сохранён; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 198a227; see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Настройки

### SCN-008: Безопасное обучение
- **Status:** implemented
- **Product:** unobserved
- **Feature:** Fabric dashboard
- **Traces:** ST-001, FLW-01 (JTBD-01, JRN-01)
- **Entry point:** Fabric Dashboards → Prowl Research
- **Persona:** P-01
- **Preconditions:** Ключи отсутствуют.
- **Steps:**
  1. Создать учебный запрос; разрешить его; посмотреть данные.
- **Expected result:** Ни одного внешнего вызова; всё помечено учебным.
- **Acceptance criteria:** Ни одного внешнего вызова; всё помечено учебным; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 198a227; see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Обучение

### SCN-009: Внешний вид, навигация и состояние сервиса
- **Status:** implemented
- **Product:** unobserved
- **Feature:** Fabric dashboard
- **Traces:** ST-001, FLW-01 (JTBD-01, JRN-01)
- **Entry point:** Fabric Dashboards → Prowl Research
- **Persona:** P-01
- **Preconditions:** Панель открыта; ширина окна от 360 px.
- **Steps:**
  1. Прочитать состояние сервиса в шапке; сменить тему и цветовую схему; открыть разделы, в том числе через «Ещё» на узком экране; пролистать широкую таблицу.
- **Expected result:** Чип в шапке называет состояние сервиса («Работает», «Работает с ограничениями», «Останавливается»), подсказка — причины ограничений. Тема и схема выбираются по-русски и запоминаются набором Fabric Dashboards; внутри хоста Fabric Dashboards их задаёт хост. На 360 px страница не прокручивается вбок; не поместившиеся разделы уходят в «Ещё»; широкая таблица прокручивается внутри своей рамки и помечена, когда не помещается.
- **Acceptance criteria:** Состояние, подписи и прокрутка как выше; без ошибок страницы; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Нет связи — чип и снимок остаются, свежесть говорит «Нет свежих данных».
- **UI elements:** Чип состояния, выбор темы и схемы, навигация с «Ещё», рамка прокрутки таблицы.
- **Coverage:** scripts/test-dashboard.mjs (checks status-chip, russian-kit-labels, scroll-box-prepared, requests-360-no-overflow) — observed at 198a227; see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Все

## Core agent scenarios (CORE)

Поведение ядра исследования на всех трёх входах — CLI `prowl-research`, stdio MCP (`prowl-research mcp`) и сервис Fabric `prowl-research.default`. Сценарии написаны против **целевого** состояния из [canvas](../specs/2026-10-11-waves-canvas.md) (§2 модули, §7 волны), а не против текущего кода: на `c0dfb6e` многие из них заведомо не выполняются (KA-03…KA-12, [deep audit](../reports/2026-10-10-agent-deep-audit/README.md)).

**Статусы CORE — adopt-in-place, как в родительском prowl-app:** `UNVERIFIED` → `PASS` / `FAIL` / `GAP` со штампом коммита. Перечень статусов super-ux (`draft`/`validated`/`implemented`) относится к `SCN-*`; линтер super-ux проверяет только префикс `SCN`. Статус сценария переводит та волна, которая его поставляет, в том же изменении, что и код; `Coverage` тогда называет тест.

**Актор «вызывающий агент»** — другой агент, который вызывает этот сервис или stdio MCP; в `foundation.md` он пока не заведён персоной (там только P-01).

`terminal_code` — закрытый набор (canvas §2 N-OWN): `completed`, `budget_tools`, `budget_usd`, `budget_minutes`, `budget_llm`, `step_failed`, `evidence_incomplete`, `cancelled`, `error`, `interrupted`.

| ID | Title | Wave | Status |
|---|---|---|---|
| CORE-01 | Запуск до терминального состояния (CLI, stdio MCP) | 1 | PASS@583f1d1 |
| CORE-02 | Запуск через Fabric `research.run`: исход совпадает с ядром | 4 | UNVERIFIED |
| CORE-03 | Второй процесс не меняет живой прогон | 1 | PASS@583f1d1 |
| CORE-04 | Осиротевший прогон → `interrupted` → продолжение | 1, 2 | PASS@0b0347b |
| CORE-05 | Продолжение после сбоя не платит дважды | 2 | PASS@2bbf566 |
| CORE-06 | Остановка по бюджету: вызовы, USD, минуты | 2 | PASS@2bbf566 |
| CORE-07 | Остановка по бюджету LLM | 4 | UNVERIFIED |
| CORE-08 | Оплаченный сбой входит в бюджет и после продолжения | 2 | PASS@0b0347b |
| CORE-09 | `verified` только с цитатой в сохранённом raw или двумя независимыми источниками | 3 | PASS@5fcf2f4 |
| CORE-10 | Конфликт остаётся конфликтом | 3 | PASS@5fcf2f4 |
| CORE-11 | Потеря доказательств → `partial`, не `complete` | 2 | PASS@2bbf566 |
| CORE-12 | Переписать отчёт активного прогона нельзя | 1 | PASS@583f1d1 |
| CORE-13 | Судья отвергает заведомо плохой отчёт | 6 | UNVERIFIED |
| CORE-14 | Повторная отправка тем же ключом не оплачивается дважды на сервере | 6 | PASS@6dfc47f |
| CORE-15 | Вызов с токеном делегирования: проверка, отказ, запись цепочки | 5 | PASS@198a227 |
| CORE-16 | Продолжение завершившегося задания сервиса без повторной оплаты | 5 | PASS@d77deeb |
| CORE-17 | Отказ инструмента по одному шагу не останавливает прогон | 6 | UNVERIFIED |
| CORE-18 | Значение из более раннего шага подставляется, неразрешённое не отправляется | 6 | UNVERIFIED |
| CORE-19 | Шаблонный текст и значение, которое провайдер заведомо отклоняет, не отправляются | 6 | UNVERIFIED |

### CORE-01: Запуск до терминального состояния (CLI, stdio MCP)
- **Status:** PASS@583f1d1
- **Actor:** оператор (P-01) в терминале; вызывающий агент через stdio MCP
- **Trigger:** `prowl-research run <runbook>` или вызов stdio MCP `research.run`
- **Preconditions:** runbook проходит `prowl-research validate`; ключи заданы.
- **Steps:**
  1. Запустить прогон.
  2. Дождаться окончания; прочитать `prowl-research status <run_id>` или `research.get_status`.
- **Expected result:** checkpoint содержит терминальный `status` и `terminal_code` из закрытого набора; CLI и stdio MCP сообщают одну и ту же пару; переходы жизненного цикла записаны структурными событиями через `research_agent/events.py`, без секретов.
- **Failure outcome:** исключение внутри прогона записывается самим `Orchestrator.run` под блокировкой как `failed` + `terminal_code=error`, отмена — как `partial` + `cancelled`; обработчики MCP и CLI только сообщают и ничего не пишут.
- **Wave:** 1 (N-OWN)
- **Coverage:** `tests/test_ka_contracts.py`: `test_clean_finish_is_completed_everywhere`, `test_owner_writes_failed_on_exception`, `test_cancel_mid_run_is_written_by_the_owner_and_non_owners_write_nothing`, `test_budget_stop_maps_to_budget_code`, `test_usd_budget_stop_maps_to_budget_usd_end_to_end`, `test_minutes_budget_stop_maps_to_budget_minutes_end_to_end`, `test_emit_*`

### CORE-02: Запуск через Fabric `research.run`: исход совпадает с ядром
- **Status:** UNVERIFIED
- **Actor:** вызывающий агент; оператор (P-01) одобряет в панели
- **Trigger:** вызов `research.run` сервиса `prowl-research.default`
- **Preconditions:** сервис запущен; оператор одобрил задание (SCN-004).
- **Steps:**
  1. Создать задание; оператор одобряет.
  2. Опрашивать `fabric.job.get` до терминального состояния.
- **Expected result:** `outcome` в результате задания выводится из `status`/`terminal_code` ядра по таблице соответствия в `docs/FABRIC.md`; `research.artifact.get` возвращает тот же checkpoint, что видит CLI.
- **Failure outcome:** отмена, таймаут (ошибка задания `timeout`) или остановка сервиса оставляют checkpoint прогона в терминальном состоянии (`partial` + `cancelled`), а не `running`, и ошибка задания несёт тот же код в `error.data.terminalCode` (форма ошибки закреплённой схемы interop: только `code`, `message`, `data`; задание, сохранённое сборкой до B-075, отдаётся в той же форме); уже списанные расходы сохраняются (SCN-005).
- **Wave:** 4 (N-SVC, B-005); терминальная запись при отмене — 1 (N-OWN)
- **Coverage:** волна 1 (терминальная запись при отмене, таймауте и остановке сервиса): `test_service_cancel_reaches_the_orchestrator`, `test_service_timeout_has_its_own_code_and_carries_terminal_code`, `test_service_shutdown_marks_job_interrupted_and_checkpoint_cancelled`; волна 4 (соответствие `outcome`, один транспорт LLM, переподключение служебных вызовов, журнал вызовов = журнал попыток прогона): `test_envelope_outcome_follows_the_run`, `test_a_service_research_job_journals_exactly_the_attempts_its_run_ledger_counts`, `test_service_llm_retries_a_429_like_the_core_and_journals_each_attempt`, `test_service_metadata_calls_reconnect_but_a_paid_call_is_sent_once`, `test_journal_and_ledger_agree_across_a_429`, `test_the_service_call_limit_refuses_before_anything_is_recorded`, `test_a_service_job_stopped_by_the_llm_cap_reports_partial`; B-075 (форма ошибки): `test_job_view_serves_a_legacy_terminal_code_inside_data`, `test_job_view_keeps_an_error_without_terminal_code_as_is`, `scripts/verify-fabric-contract.py` (проверка `failed-job` по контракту на `7a14a48`)

### CORE-03: Второй процесс не меняет живой прогон
- **Status:** PASS@583f1d1
- **Actor:** оператор (P-01) или вызывающий агент, случайно запустивший второй процесс
- **Trigger:** второй `prowl-research run <runbook> --run-id <id>` (или stdio MCP `research.run` с тем же `run_id`) при живом первом процессе
- **Preconditions:** первый процесс держит блокировку прогона (`RunLock`).
- **Steps:**
  1. Запустить второй процесс на тот же каталог прогона.
- **Expected result:** второй процесс получает отказ `run … is locked by another process` (в stdio MCP — сразу, и при `wait=false`), `research.get_status` показывает `active=true`, `orphaned=false`, и **никто не пишет ничего**: checkpoint, ledger и raw первого процесса не изменены; первый завершается штатно.
- **Failure outcome:** если отказ всё же переписывает checkpoint живого владельца (например, в `failed`), это дефект KA-06; сценарий `FAIL`.
- **Wave:** 1 (N-OWN, KA-06; двухпроцессный smoke — критерий выхода волны 1)
- **Coverage:** `test_ka06_non_owner_cannot_mutate_locked_checkpoint[run|startup]`, `test_research_run_wait_false_refuses_a_run_locked_elsewhere`, `tests/test_two_process_lock.py::test_second_process_cannot_write_a_locked_run`

### CORE-04: Осиротевший прогон → `interrupted` → продолжение
- **Status:** PASS@0b0347b
- **Actor:** оператор (P-01)
- **Trigger:** процесс прогона убит (сбой, перезагрузка); затем `prowl-research status <run_id>`, старт stdio MCP или восстановление сервиса (`Store.recover`)
- **Preconditions:** checkpoint в `running`, блокировку никто не держит. Каталог прогонов один для всех команд CLI и stdio MCP: `RESEARCH_RUNS_DIR`, иначе `./runs`; у сервиса — свой `runs/` в корне сервиса.
- **Steps:**
  1. Открыть статус или запустить вход, выполняющий сверку.
  2. Продолжить прогон: `prowl-research run <runbook> --run-id <id>`.
- **Expected result:** сверка берёт `RunLock` без ожидания, помечает прогон `interrupted` под блокировкой; продолжение выполняет шаги в состояниях `pending`, `skipped_budget` (если бюджет позволяет), `outcome_unknown` (тем же ключом), `raw_saved` (только извлечение) и `failed` (обязательный шаг, а также необязательный после отказа, остановившего прогон); `completed`, `skipped_on_error` и `excluded` не выполняются.
- **Failure outcome:** если блокировка занята — сверка ничего не пишет (событие `run.reconcile.skipped_active`), а статус показывает `active=true`; недоступный для записи каталог не мешает сверке остальных (`run.reconcile.failed`). Чтение статуса само по себе никогда не пишет, кроме этой сверки под блокировкой.
- **Wave:** 1 (сверка в `interrupted`, N-OWN); 2 (продолжение по сохранённым состояниям шагов, N-STATE)
- **Coverage:** волна 1 (сверка): `test_control_unlocked_orphan_is_reconciled`, `test_reconcile_orphans_reports_what_it_marked_and_skips_active`, `test_reconcile_survives_an_unwritable_run_dir`, `test_cli_status_reconciles_an_orphan_and_prints_terminal`, `test_service_recover_reconciles_its_run_dirs`; волна 2 (продолжение по состояниям шагов): `test_ka03_*`, `test_outcome_unknown_attempt_is_resent_with_the_same_key`, `tests/test_durability.py`

### CORE-05: Продолжение после сбоя не платит дважды
- **Status:** PASS@2bbf566
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** продолжение прогона, упавшего на любой границе сохранения шага
- **Preconditions:** для шага уже сохранён raw (`raw_saved`) или попытка отправлена без известного исхода (`dispatching`).
- **Steps:**
  1. Продолжить прогон.
- **Expected result:** (клиентская половина) шаг с сохранённым raw только извлекается заново — **без повторной отправки**, даже если бюджет исчерпан; шаг в `dispatching` или с таймаутом чтения становится `outcome_unknown` и отправляется с **тем же** ключом идемпотентности `run:step_id:attempt_no` — остановка по бюджету его не переименовывает; идентификаторы шагов не сдвигаются, даже если план или каталог инструментов изменились. Что повторная отправка **бесплатна**, решает сервер Prowl в своём окне дедупликации (15 минут по умолчанию) — это CORE-14.
- **Failure outcome:** если инструмент выпал из каталога — помечается `excluded` именно этот шаг, остальные не перенумеровываются; v1 checkpoint, который нельзя перенести без догадок, показывается как `status: needs_attention` с причиной: отчёт читается и экспортируется, `research.run` отказывает по имени, продолжения нет.
- **Wave:** 2 (N-STATE, N-COST; KA-03, KA-04, KA-05; тест `CrashAt` на каждой границе)
- **Coverage:** `tests/test_durability.py::test_every_durable_boundary_is_resumable_without_paying_twice`, `test_ka10_resume_finishes_extraction_from_saved_raw_without_paying`, `test_outcome_unknown_attempt_is_resent_with_the_same_key`, `test_read_timeout_is_outcome_unknown_and_resent_with_the_same_key`, `test_budget_stop_keeps_an_outcome_unknown_step_and_its_key`, `test_raw_saved_step_is_extracted_even_after_the_tool_budget_is_spent`, `test_v1_crash_between_save_and_completion_is_finished_without_paying`, `test_a_run_that_needs_attention_stays_readable_and_is_never_resumed`, `test_migration_refuses_*`

### CORE-06: Остановка по бюджету: вызовы, USD, минуты
- **Status:** PASS@2bbf566
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** прогон достигает лимита runbook `Budget` по вызовам инструментов, USD или минутам
- **Preconditions:** лимит меньше, чем требует план.
- **Steps:**
  1. Запустить прогон; дождаться остановки.
- **Expected result:** следующая отправка не происходит; прогон `partial` с `terminal_code` `budget_tools` / `budget_usd` / `budget_minutes`; невыполненные шаги — `skipped_budget`, их список передаётся writer'у с указанием пометить отчёт как partial; расход считается по журналу попыток (`actual`, иначе `estimate`, неизвестная цена — по оценке, не ноль).
- **Failure outcome:** продолжение с поднятым бюджетом выполняет `skipped_budget` шаги; без поднятия — не выполняет.
- **Wave:** 2 (N-COST)
- **Coverage:** `test_budget_stop_maps_to_budget_code`, `test_usd_budget_stop_maps_to_budget_usd_end_to_end`, `test_minutes_budget_stop_maps_to_budget_minutes_end_to_end`, `test_ka11_known_cost_does_not_discard_previous_estimates`, `test_writer_is_told_which_steps_are_missing`, `test_skipped_budget_steps_run_only_once_the_budget_allows`

### CORE-07: Остановка по бюджету LLM
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** расход LLM приближается к `max_llm_usd` (runbook, `RESEARCH_MAX_LLM_USD`, `--max-llm-usd`, вход stdio MCP `max_llm_usd`; поле входа Fabric `research.run` — волна 5, вместе с пересборкой манифеста; до неё сервис берёт лимит из окружения, runbook или значения по умолчанию)
- **Preconditions:** лимит задан или действует `config.DEFAULT_MAX_LLM_USD`.
- **Steps:**
  1. Запустить прогон; дождаться остановки.
- **Expected result:** проверка до вызова останавливает исследовательские стадии с `terminal_code=budget_llm`, когда следующий вызов вышел бы за лимит минус резерв писателя, и после такого отказа ни один платный инструмент больше не отправляется; писатель тратит резерв и выпускает отчёт из собранного, а если и резерва нет, отчёт состоит из ledger как собран (раздел «Source coverage» в нём перечисляет `statement` каждого ограничения источника, текст для человека, B-077) (продолжение без новых доказательств и без денег сохраняет уже написанный отчёт); отказ на этапе отчёта (repair, проверка цитат) делает прогон `partial` + `budget_llm`, а не `completed`; ограничение действует на каждую попытку, повторы тоже, и после продолжения или повторного планирования (расход и лимит читаются из журнала попыток); `rewrite` тратит из того же лимита. Лимит означает проверку перед вызовом по оценке: последний разрешённый вызов может превысить его на разницу между фактом и оценкой. Ответ с ошибкой HTTP (429, 5xx) учитывается как бесплатный.
- **Failure outcome:** модель без цены учитывается по консервативной оценке как `unknown`, никогда как 0.
- **Wave:** 4 (N-LLMB, KA-G01)
- **Coverage:** `tests/test_llm_budget.py`: `test_research_calls_stop_before_the_cap_and_the_writer_spends_the_reserve`, `test_every_retry_is_an_attempt_and_counts`, `test_a_missing_price_is_never_zero`, `test_the_run_stops_research_at_the_llm_cap_and_resumes_without_paying_twice`, `test_when_even_the_reserve_is_gone_the_evidence_still_ships`, `test_the_cap_resolves_caller_then_env_then_recorded_then_runbook_then_default`, `test_a_retry_is_refused_before_it_is_sent`, `test_once_research_is_refused_no_further_tool_is_paid_for`, `test_a_refused_repair_or_citation_pass_ends_the_run_partial`, `test_a_replanned_run_keeps_its_cap_and_spend`, `test_a_billed_planner_failure_is_still_counted_after_a_replan`, `test_a_resume_that_gathers_nothing_keeps_the_paid_report`, `test_rewrite_spends_from_the_run_ledger_and_refuses_without_budget`, `test_a_refused_longer_draft_ships_the_paid_truncated_one`, `test_the_cap_reaches_the_run_from_the_cli`, `test_the_cap_reaches_the_run_from_mcp`, `test_infinite_caps_are_refused_everywhere`; `tests/test_not_sent_arguments.py`: `test_the_evidence_only_fallback_prints_the_statement_not_the_writer_instruction`

### CORE-08: Оплаченный сбой входит в бюджет и после продолжения
- **Status:** PASS@0b0347b
- **Actor:** оператор (P-01)
- **Trigger:** инструмент вернул ошибку, но провайдер списал стоимость; прогон затем продолжен
- **Preconditions:** ошибка несёт списанную стоимость (`ProwlError.cost_usd`).
- **Steps:**
  1. Прогнать до сбоя; продолжить прогон.
- **Expected result:** попытка записана в журнал с исходом и стоимостью в `finally`; после продолжения расход восстанавливается из сохранённых попыток **до** первой отправки, и сбой учитывается в бюджете.
- **Failure outcome:** если стоимость сбоя теряется или продолжение начинает расход с нуля — дефект (KA-10/KA-12); сценарий `FAIL`.
- **Wave:** 2 (N-COST; KA-10, KA-12)
- **Coverage:** `test_ka12_billed_failure_cost_survives_resume`

### CORE-09: `verified` только с цитатой в сохранённом raw или двумя независимыми источниками
- **Status:** PASS@5fcf2f4
- **Actor:** оператор (P-01), читающий отчёт; вызывающий агент, потребляющий ledger
- **Trigger:** извлечение утверждений из шага
- **Preconditions:** raw шага сохранён с `raw_sha256`.
- **Steps:**
  1. Прогнать; открыть ledger и отчёт.
- **Expected result:** утверждение `verified` только если (а) его цитата найдена в сохранённом raw (после нормализации пробелов, sha256 совпадает) и значение стоит внутри цитаты, или (б) ≥2 согласных утверждения с разными известными `independence_key`; два инструмента над одним URL — один источник; два поставщика одного исходного датасета (`google_trends` и `serpapi_google_trends`) — один источник; URL засчитывается, только если его называет raw или запрос; утверждения одного шага не подтверждают друг друга; transform и LLM-инструменты (Perplexity, Gemini, Google AI) — не источник.
- **Failure outcome:** цитата не найдена или источник `unknown` — утверждение не `verified`; v1 `verbatim` без цитаты понижается до `assumed` с раскрытием.
- **Wave:** 3 (N-EVID; KA-07, KA-08, KA-09)
- **Coverage:** `test_ka08_fabricated_verbatim_is_not_verified`, `test_ka09_same_document_is_not_two_independent_sources`, `test_span_verification_reads_the_whole_stored_raw`, `test_two_independent_publishers_corroborate`, `test_two_data_providers_without_urls_corroborate_but_one_provider_does_not`, `test_transform_claim_never_corroborates_its_source`, `test_transform_quote_never_span_verifies`, `test_v1_verbatim_claim_without_a_quote_is_downgraded_on_load`, `test_tampered_raw_is_a_typed_extraction_failure_and_the_resume_finishes`, `test_a_bare_number_quote_is_not_a_quote`, `test_a_quote_copied_from_the_json_the_extractor_saw_is_found`, `test_value_in_quote_matches_numbers_on_number_boundaries`, `test_an_invented_source_url_does_not_make_a_second_source`, `test_urls_named_by_the_raw_count_but_one_step_is_one_delivery`, `test_a_web_tool_claim_without_a_url_is_no_source`, `test_a_quote_not_found_neither_verifies_nor_counts`, `test_an_llm_answer_tool_never_span_verifies`, `test_independence_is_the_upstream_source_not_the_delivery_tool`

### CORE-10: Конфликт остаётся конфликтом
- **Status:** PASS@5fcf2f4
- **Actor:** оператор (P-01), читающий отчёт
- **Trigger:** в одной группе утверждений появляются ≥2 разных значения
- **Preconditions:** —
- **Steps:**
  1. Прогнать; открыть ledger и отчёт.
- **Expected result:** все утверждения группы со значением — `conflict`, независимо от порядка поступления и от того, что пришло позже (единица не указана — совместима с любой; `$` и `USD` — одна единица); утверждение без значения не подтверждает и не разрешает конфликт; writer получает обе стороны со статусом `conflict` и правило `[CONFLICT]`, график по конфликтному утверждению отклоняется. Что живой отчёт действительно показывает конфликт, проверяет живая приёмка (волна 6).
- **Failure outcome:** если итоговый статус группы зависит от порядка — тест независимости от порядка падает; сценарий `FAIL`.
- **Wave:** 3 (N-EVID)
- **Coverage:** `test_ka07_valueless_claim_cannot_erase_numeric_conflict`, `test_statuses_do_not_depend_on_insertion_order`, `test_recompute_survives_save_and_load`, `test_removing_a_claim_recomputes_its_group`, `test_status_events_are_emitted_once_per_transition`, `test_currency_symbol_and_code_are_one_unit_and_missing_unit_is_compatible`, `test_blank_values_are_no_values`, `test_conflict_reaches_the_writer_with_both_sides_and_the_rule`, `test_a_chart_over_a_conflict_claim_is_rejected`

### CORE-11: Потеря доказательств → `partial`, не `complete`
- **Status:** PASS@2bbf566
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** запись raw или извлечение шага не удались
- **Preconditions:** —
- **Steps:**
  1. Прогнать до конца.
- **Expected result:** шаг не становится `completed`; прогон `partial` с `terminal_code=evidence_incomplete`, если не хватает только доказательств; список шагов без доказательств передаётся writer'у.
- **Failure outcome:** продолжение повторяет только извлечение, если raw сохранён, без новой оплаты (CORE-05); если не записался raw обязательного шага — продолжение запрашивает его снова (новый оплачиваемый вызов), необязательный шаг становится `skipped_on_error` и не оплачивается повторно.
- **Wave:** 2 (N-STATE; B-006, B-008)
- **Coverage:** `test_ka10_evidence_failure_cannot_report_complete[raw_write|extraction]`, `test_raw_write_failure_is_skipped_when_optional_and_refetched_when_required[True|False]`, `test_writer_is_told_which_steps_are_missing`

### CORE-12: Переписать отчёт активного прогона нельзя
- **Status:** PASS@583f1d1
- **Actor:** оператор (P-01)
- **Trigger:** `prowl-research rewrite <run_id>` при живом прогоне
- **Preconditions:** прогон держит `RunLock`.
- **Steps:**
  1. Запустить переписывание.
- **Expected result:** команда отказывает (`run … is active; rewrite refused`) и ничего не пишет — ни `report.md`, ни checkpoint.
- **Failure outcome:** после завершения прогона переписывание берёт блокировку и работает (только писатель, без расходов Prowl).
- **Wave:** 1 (N-OWN)
- **Coverage:** `test_rewrite_report_refused_while_locked`

### CORE-13: Судья отвергает заведомо плохой отчёт
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01) при приёмке
- **Trigger:** запуск судьи (`evals/judge.py`) на заранее испорченных фикстурах
- **Preconditions:** набор planted-bad фикстур: выдуманная ссылка, выдуманная цитата, цифра, которой нет в процитированном утверждении, скрытый конфликт, нераскрытый неполный прогон, пометка VERIFIED у непроверенного утверждения. Цифра без ссылки снижает оценку цитирования и не является вето.
- **Steps:**
  1. Прогнать судью на каждой фикстуре; затем на размеченном наборе.
- **Expected result:** судья проваливает каждую planted-bad фикстуру; на размеченном наборе записано число согласия с человеком; код выхода прогона и код выхода судьи разделены.
- **Failure outcome:** фикстура, которую судья пропустил, блокирует приёмку; судья без калибровки не используется как доказательство качества.
- **Wave:** 6 (N-ACC, B-017)
- **Coverage:** офлайн-половина — `tests/test_judge_calibration.py`, `evals/calibrate.py`, `scripts/mutation_check.py` ([доказательства](../evidence/judge-calibration/README.md)): модель, ставящая 0.95 всем, всё равно проваливает каждую заложенную фикстуру (фикстуры написаны вместе с проверками), честные проходят; расход судьи проверяется оценкой до вызова; код выхода 0/1/2, сбой модели — 2. Живая половина (согласие настроенной модели судьи, размеченные реальные прогоны) не выполнена: ключ модели есть, флаг `--live` — ручной шлюз оператора; статус остаётся UNVERIFIED.

### CORE-14: Повторная отправка тем же ключом не оплачивается дважды на сервере
- **Status:** PASS@6dfc47f (живая проверка 2026-10-21, B-032)
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** продолжение прогона с шагом `outcome_unknown` (CORE-05)
- **Preconditions:** живой ключ Prowl; прогон прерван во время оплачиваемого вызова.
- **Steps:**
  1. Продолжить прогон в пределах окна дедупликации сервера (по умолчанию 15 минут).
  2. Продолжить другой такой прогон после окна.
- **Expected result:** в окне сервер воспроизводит прежний исход и не списывает второй раз; квитанция кошелька показывает одно списание.
- **Failure outcome:** после окна тот же ключ списывается заново — это задокументировано в README; журнал попыток считает повторную отправку одной попыткой, поэтому бюджет недосчитывает на этот вызов.
- **Wave:** 6 (живая приёмка; зависит от KA-01 в prowl-app)
- **Coverage:** живая проба 2026-10-21: первый вызов `google_news_light` USD 0.009, повтор тем же ключом USD 0.0 с теми же данными. Оговорка: сервер кэширует одинаковые запросы, новый ключ с теми же аргументами тоже USD 0.0, так что повтор и кэш здесь не разделены; баланс кошелька общий с другими агентами и не служит квитанцией. Шаг 2 (после окна) не измерялся.

### CORE-15: Вызов с токеном делегирования: проверка, отказ, запись цепочки
- **Status:** PASS@198a227
- **Actor:** вызывающий агент (с токеном, выпущенным hub по DEC-0039)
- **Trigger:** `tools/call` на `/mcp` сервиса `prowl-research.default` с `Authorization: Bearer <токен делегирования>` или `Fabric-Delegation`
- **Preconditions:** заданы `RESEARCH_DELEGATION_ISSUER` и `RESEARCH_DELEGATION_JWKS` (иначе любой предъявленный токен отклоняется).
- **Steps:**
  1. Вызвать `research.tutorial` с действующим токеном; затем с токеном другой аудитории, просроченным, с чужой подписью, без нужной способности.
- **Expected result:** действующий токен принят; задание хранит `principal`, `caller`, цепочку и `kid`, но не сам токен, а панель показывает инициатора как проверенного. Вызывающий видит, отменяет и читает артефакты только своих заданий; его ключ идемпотентности не пересекается с чужим. Методы без способности (`initialize`, `tools/list`) тоже требуют подлинного действующего токена. Свой токен агента с loopback (T0) работает без токена делегирования; предъявленный рядом токен всё равно проверяется.
- **Failure outcome:** неверный токен — отказ кодом контракта (`wrong-audience`, `token-expired`, `unauthenticated`, `scope-not-granted`, `effect-above-ceiling`, `issuer-unavailable`) как результат вызова, задание не создаётся; чужое задание — `scope-not-granted`; метод без способности с неверным токеном — HTTP 401 с `WWW-Authenticate` (без доверенного издателя — 503 `issuer-unavailable`); нет ни своего токена, ни токена делегирования — 401 `unauthenticated`. Сервис слушает только loopback.
- **Wave:** 5 (N-FAB, FD-12); цепочка через живой hub — волна 6 (KA-G03)
- **Coverage:** `tests/test_delegation.py` (все тесты файла)

### CORE-16: Продолжение завершившегося задания сервиса без повторной оплаты
- **Status:** PASS@d77deeb
- **Actor:** вызывающий агент (только MCP: в панели продолжения нет; оператор одобряет его там)
- **Trigger:** `research.run` с `resumeJobId` упавшего, отменённого или прерванного исследовательского задания того же runbook и с теми же входными данными
- **Preconditions:** исходное задание не ждёт решения, не работает и не закончило прогон.
- **Steps:**
  1. Создать задание-продолжение; оператор одобряет его в панели.
- **Expected result:** повтор того же вызова (тот же ключ идемпотентности, тот же запрос, тот же вызывающий) возвращает уже созданное задание. Продолжение, созданное оператором для цепочки агента, остаётся действием оператора и видно агенту — владельцу цепочки. Новое задание продолжает прогон исходного: сохранённые ответы только извлекаются, уже оплаченный шаг не отправляется снова, журнал попыток и лимит LLM переходят. Продолжение продолжения пишет в прогон корня цепочки, а не заводит новый; отчёт и артефакты читаются через любое задание цепочки.
- **Failure outcome:** отказ при создании, с причиной: неизвестный id; чужой runbook или другие входные данные; задание, которое ждёт решения или работает; прогон, который уже закончен; задание, отклонённое оператором; прогон, который уже продолжает другое задание; задание другого принципала — `scope-not-granted`.
- **Wave:** 5 (N-FAB, B-039)
- **Coverage:** `tests/test_service_parity.py::test_a_failed_service_job_is_resumed_without_paying_again`, `::test_a_resume_respects_the_principal_and_the_operators_rejection`, `::test_a_resume_replayed_with_the_same_key_returns_the_same_job`

### CORE-17: Отказ инструмента по одному шагу не останавливает прогон
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** сервер Prowl отвечает определённым отказом на один шаг: «нет результатов», `not_found`, `provider_error`, `validation`, `forbidden` (ключ провайдера, инструмент вне области ключа)
- **Preconditions:** нет
- **Steps:**
  1. Запустить прогон, в плане которого один обязательный шаг получит такой отказ.
- **Expected result:** шаг становится `failed` с причиной сервера (необязательный: `skipped_on_error`); воркер берёт следующий шаг, следующие сегменты выполняются, трансформация узнаёт, какие шаги перед ней получили отказ. Прогон с отказом обязательного шага заканчивается `partial` с `terminal_code=step_failed`; `stop_reason` перечисляет такие шаги с причиной сервера, а writer получает их список с причинами до того, как начинает писать, поэтому отчёт говорит, чего нет. Если прогон затем остановил бюджет, код остаётся бюджетным, а `stop_reason` дополнительно называет отказавшие шаги. Продолжение запрашивает упавшие шаги снова (новая попытка) и не платит за выполненные.
- **Failure outcome:** прогон останавливается, как раньше: пустой кошелёк Prowl (`insufficient_funds`), локальный отказ сервиса (лимит вызовов, журнал недоступен), неизвестный исход отправки (`outcome_unknown`), пять отказов обязательных шагов подряд на весь прогон (необязательные не считаются), любой бюджет. Неначатые шаги остаются `pending`.
- **Wave:** 6 (N-ACC, B-049)
- **Coverage:** `tests/test_step_failure_policy.py` (18 тестов), `tests/test_orchestrator.py::test_a_refused_step_does_not_stop_the_run_and_reaches_the_writer`

### CORE-18: Значение из более раннего шага подставляется, неразрешённое не отправляется
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** шаг плана требует значение, которое знает только более ранний шаг (числовой id приложения в App Store, имя пакета Google Play); планировщик пишет его как `{{имя}}`
- **Preconditions:** перед таким шагом в плане есть трансформация, названная в инструкции
- **Steps:**
  1. Запустить прогон, в плане которого шаг-разрешитель, трансформация и шаг с плейсхолдером.
- **Expected result:** трансформация получает список нужных имён и отдаёт блок `bindings`; значение принимается, только если сырой ответ прогона содержит его дословно (`checkpoint.bindings`); шаг отправляет заполненные аргументы (`bound_arguments`), а `arguments` хранит план как написан; заметка трансформации для writer идёт без блока.
- **Failure outcome:** плейсхолдер, который никто не разрешил, или выдуманное значение не отправляются вовсе: шаг `skipped_on_error` (обязательный: `failed`, прогон `partial`/`step_failed`) с причиной `not sent: no earlier step resolved {{имя}}`, без попытки и без оплаты; в счётчик отказов подряд это не входит.
- **Wave:** 6 (N-ACC, B-065)
- **Coverage:** `tests/test_plan_bindings.py` (10 тестов); как writer называет неотправленный шаг: CORE-19

### CORE-19: Шаблонный текст и значение, которое провайдер заведомо отклоняет, не отправляются
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** планировщик пишет в аргумент не значение, а шаблон другой формы (`[substitute ...]`, `<id from ...>`, `{шаг.поле}`, `PLACEHOLDER_...`), или значение, которое провайдер отклоняет, хотя схема инструмента об этом молчит (`tiktok_ads_library`, `country: "US"`)
- **Preconditions:** план прошёл проверку; ограничение записано в `research_agent/agent/tool_limits.py` с источником
- **Steps:**
  1. Запустить прогон, в плане которого такой шаг.
- **Expected result:** планировщик получает раздел «Argument limits the schemas do not state» с ограничениями инструментов своего runbook; шаг с шаблонным текстом или запрещённым значением не отправляется: `skipped_on_error` (обязательный: `failed`, прогон `partial`/`step_failed`) с причиной `not sent: an argument holds template text, not a value: ...` или `not sent: <tool> does not take country='US' (a known provider limit)`, без попытки и без оплаты; остальные шаги идут дальше. Writer получает такие шаги отдельным списком «not sent» (в частичном прогоне в разделе PARTIAL RUN, в полном прогоне с неотправленным опциональным шагом в разделе STEPS NOT SENT) и называет их пробелом этого прогона, а не ответом источника и не находкой вроде «не рекламируется в TikTok» (так же для неразрешённых `{{имя}}` из CORE-18); принятое значение уходит в написании провайдера (`fr` как `FR`); для отправленного инструмента с ограничением writer получает раздел «Source coverage» (TikTok: только Европа), и пустой европейский результат не читается как «не рекламируется в TikTok».
- **Failure outcome:** в счётчик отказов подряд такой шаг не входит; настоящее значение (`"Novo Nordisk" going concern`, URL, JSON, `{company.name}` внутри промпта) отправляется как раньше. Прямой `research.tools.call` с заведомо отклоняемым значением получает до создания задания результат инструмента с `isError: true` и кодом `request-rejected` (форма «Новый запрос» на дашборде: HTTP 400 под формой); задание, созданное до появления ограничения, проверяется ещё раз при отправке и завершается с `error.code` `request-rejected` и той же причиной, без вызова; прямой результат ограниченного инструмента несёт поле `coverage` (оно же в `notVerified`); дашборд показывает тот же факт по-русски в плашке «Охват источника» на вкладках «Данные» и «Источники», выводя его из инструментов, которые запрос использовал, и для исследований тоже (B-078); повторная отправка шага с неизвестным исходом уходит с теми же параметрами, что первая попытка, под тем же ключом, и не оценивается заново правилом, появившимся позже (отправленный шаг не называется «not sent»); шаблонный текст на этом пути не проверяется (значения пишет сам вызывающий); повтор ключа уже созданного задания отвечает этим заданием.
- **Wave:** 6 (N-ACC, B-070, B-071)
- **Coverage:** `tests/test_not_sent_arguments.py` (52 теста; аргументы взяты из сохранённых прогонов)

