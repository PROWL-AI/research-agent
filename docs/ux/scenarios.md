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
- **Expected result:** Видны актуальные счётчики; при offline сохранённый снимок явно устарел.
- **Acceptance criteria:** Видны актуальные счётчики; при offline сохранённый снимок явно устарел; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 891fbc9; see docs/evidence/fabric-dashboard/VERIFICATION.md
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 891fbc9; see docs/evidence/fabric-dashboard/VERIFICATION.md
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
- **Expected result:** Таблица не требует чтения JSON; сырой текст не выполняется как HTML.
- **Acceptance criteria:** Таблица не требует чтения JSON; сырой текст не выполняется как HTML; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 891fbc9; see docs/evidence/fabric-dashboard/VERIFICATION.md
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
- **Expected result:** Действует только непросроченный digest этого запроса; повтор не запускает работу дважды.
- **Acceptance criteria:** Действует только непросроченный digest этого запроса; повтор не запускает работу дважды; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 891fbc9; see docs/evidence/fabric-dashboard/VERIFICATION.md
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 891fbc9; see docs/evidence/fabric-dashboard/VERIFICATION.md
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
  1. Открыть дневной график и таблицу.
- **Expected result:** Учебные данные исключены; неизвестные цены не превращаются в ноль.
- **Acceptance criteria:** Учебные данные исключены; неизвестные цены не превращаются в ноль; доказательства записываются в verification.
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Ошибка сохраняет снимок; обновить панель. Платные вызовы не повторяются автоматически.
- **UI elements:** Навигация, журнал, вкладки, форма решения, настройки.
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 891fbc9; see docs/evidence/fabric-dashboard/VERIFICATION.md
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 891fbc9; see docs/evidence/fabric-dashboard/VERIFICATION.md
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — observed at 891fbc9; see docs/evidence/fabric-dashboard/VERIFICATION.md
- **Screen:** Обучение

## Core agent scenarios (CORE)

Поведение ядра исследования на всех трёх входах — CLI `prowl-research`, stdio MCP (`prowl-research mcp`) и сервис Fabric `prowl-research.default`. Сценарии написаны против **целевого** состояния из [canvas](../specs/2026-10-11-waves-canvas.md) (§2 модули, §7 волны), а не против текущего кода: на `c0dfb6e` многие из них заведомо не выполняются (KA-03…KA-12, [deep audit](../reports/2026-10-10-agent-deep-audit/README.md)).

**Статусы CORE — adopt-in-place, как в родительском prowl-app:** `UNVERIFIED` → `PASS` / `FAIL` / `GAP` со штампом коммита. Перечень статусов super-ux (`draft`/`validated`/`implemented`) относится к `SCN-*`; линтер super-ux проверяет только префикс `SCN`. Статус сценария переводит та волна, которая его поставляет, в том же изменении, что и код; `Coverage` тогда называет тест.

**Актор «вызывающий агент»** — другой агент, который вызывает этот сервис или stdio MCP; в `foundation.md` он пока не заведён персоной (там только P-01).

`terminal_code` — закрытый набор (canvas §2 N-OWN): `completed`, `budget_tools`, `budget_usd`, `budget_minutes`, `budget_llm`, `step_failed`, `evidence_incomplete`, `cancelled`, `error`, `interrupted`.

| ID | Title | Wave | Status |
|---|---|---|---|
| CORE-01 | Запуск до терминального состояния (CLI, stdio MCP) | 1 | UNVERIFIED |
| CORE-02 | Запуск через Fabric `research.run`: исход совпадает с ядром | 4 | UNVERIFIED |
| CORE-03 | Второй процесс не меняет живой прогон | 1 | UNVERIFIED |
| CORE-04 | Осиротевший прогон → `interrupted` → продолжение | 1, 2 | UNVERIFIED |
| CORE-05 | Продолжение после сбоя не платит дважды | 2 | UNVERIFIED |
| CORE-06 | Остановка по бюджету: вызовы, USD, минуты | 2 | UNVERIFIED |
| CORE-07 | Остановка по бюджету LLM | 4 | UNVERIFIED |
| CORE-08 | Оплаченный сбой входит в бюджет и после продолжения | 2 | UNVERIFIED |
| CORE-09 | `verified` только с цитатой в сохранённом raw или двумя независимыми источниками | 3 | UNVERIFIED |
| CORE-10 | Конфликт остаётся конфликтом | 3 | UNVERIFIED |
| CORE-11 | Потеря доказательств → `partial`, не `complete` | 2 | UNVERIFIED |
| CORE-12 | Переписать отчёт активного прогона нельзя | 1 | UNVERIFIED |
| CORE-13 | Судья отвергает заведомо плохой отчёт | 6 | UNVERIFIED |

### CORE-01: Запуск до терминального состояния (CLI, stdio MCP)
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01) в терминале; вызывающий агент через stdio MCP
- **Trigger:** `prowl-research run <runbook>` или вызов stdio MCP `research.run`
- **Preconditions:** runbook проходит `prowl-research validate`; ключи заданы.
- **Steps:**
  1. Запустить прогон.
  2. Дождаться окончания; прочитать `prowl-research status <run_id>` или `research.get_status`.
- **Expected result:** checkpoint содержит терминальный `status` и `terminal_code` из закрытого набора; CLI и stdio MCP сообщают одну и ту же пару; переходы жизненного цикла записаны структурными событиями через `research_agent/events.py`, без секретов.
- **Failure outcome:** исключение внутри прогона записывается самим `Orchestrator.run` под блокировкой как `failed` + `terminal_code=error`, отмена — как `partial` + `cancelled`; обработчики MCP и CLI только сообщают и ничего не пишут.
- **Wave:** 1 (N-OWN)
- **Coverage:** —

### CORE-02: Запуск через Fabric `research.run`: исход совпадает с ядром
- **Status:** UNVERIFIED
- **Actor:** вызывающий агент; оператор (P-01) одобряет в панели
- **Trigger:** вызов `research.run` сервиса `prowl-research.default`
- **Preconditions:** сервис запущен; оператор одобрил задание (SCN-004).
- **Steps:**
  1. Создать задание; оператор одобряет.
  2. Опрашивать `fabric.job.get` до терминального состояния.
- **Expected result:** `outcome` в результате задания выводится из `status`/`terminal_code` ядра по таблице соответствия в `docs/FABRIC.md`; `research.artifact.get` возвращает тот же checkpoint, что видит CLI.
- **Failure outcome:** отмена или таймаут сервиса оставляет checkpoint прогона в терминальном состоянии (`partial` + `cancelled`), а не `running`; уже списанные расходы сохраняются (SCN-005).
- **Wave:** 4 (N-SVC, B-005); терминальная запись при отмене — 1 (N-OWN)
- **Coverage:** —

### CORE-03: Второй процесс не меняет живой прогон
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01) или вызывающий агент, случайно запустивший второй процесс
- **Trigger:** второй `prowl-research run <runbook> --run-id <id>` (или stdio MCP `research.run` с тем же `run_id`) при живом первом процессе
- **Preconditions:** первый процесс держит блокировку прогона (`RunLock`).
- **Steps:**
  1. Запустить второй процесс на тот же каталог прогона.
- **Expected result:** второй процесс получает отказ блокировки, сообщает `active` и **не пишет ничего**: checkpoint, ledger и raw первого процесса не изменены; первый завершается штатно.
- **Failure outcome:** если отказ всё же переписывает checkpoint живого владельца (например, в `failed`), это дефект KA-06; сценарий `FAIL`.
- **Wave:** 1 (N-OWN, KA-06; двухпроцессный smoke — критерий выхода волны 1)
- **Coverage:** —

### CORE-04: Осиротевший прогон → `interrupted` → продолжение
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01)
- **Trigger:** процесс прогона убит (сбой, перезагрузка); затем `prowl-research status <run_id>`, старт stdio MCP или восстановление сервиса (`Store.recover`)
- **Preconditions:** checkpoint в `running`, блокировку никто не держит.
- **Steps:**
  1. Открыть статус или запустить вход, выполняющий сверку.
  2. Продолжить прогон: `prowl-research run <runbook> --run-id <id>`.
- **Expected result:** сверка берёт `RunLock` без ожидания, помечает прогон `interrupted` под блокировкой; продолжение выполняет только шаги в состояниях `pending`, `outcome_unknown`, `raw_saved` (только извлечение) и `failed` без `on_error_skip`.
- **Failure outcome:** если блокировка занята — сверка ничего не пишет и сообщает `active`. Чтение статуса само по себе никогда не пишет, кроме этой сверки под блокировкой.
- **Wave:** 1 (сверка в `interrupted`, N-OWN); 2 (продолжение по сохранённым состояниям шагов, N-STATE)
- **Coverage:** —

### CORE-05: Продолжение после сбоя не платит дважды
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** продолжение прогона, упавшего на любой границе сохранения шага
- **Preconditions:** для шага уже сохранён raw (`raw_saved`) или попытка отправлена без известного исхода (`dispatching`).
- **Steps:**
  1. Продолжить прогон.
- **Expected result:** шаг с сохранённым raw только извлекается заново — **без повторной отправки**; шаг в `dispatching` становится `outcome_unknown` и отправляется с **тем же** ключом идемпотентности `run:step_id:attempt_no`; идентификаторы шагов не сдвигаются, даже если план или каталог инструментов изменились.
- **Failure outcome:** если инструмент выпал из каталога — помечается `excluded` именно этот шаг, остальные не перенумеровываются; несовместимый v1 checkpoint получает `CheckpointMigrationError` и отчёт `needs_attention`, а не продолжение.
- **Wave:** 2 (N-STATE, N-COST; KA-03, KA-04, KA-05; тест `CrashAt` на каждой границе)
- **Coverage:** —

### CORE-06: Остановка по бюджету: вызовы, USD, минуты
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** прогон достигает лимита runbook `Budget` по вызовам инструментов, USD или минутам
- **Preconditions:** лимит меньше, чем требует план.
- **Steps:**
  1. Запустить прогон; дождаться остановки.
- **Expected result:** следующая отправка не происходит; прогон `partial` с `terminal_code` `budget_tools` / `budget_usd` / `budget_minutes`; невыполненные шаги — `skipped_budget` и раскрыты в отчёте; расход считается по журналу попыток (`actual`, иначе `estimate`, неизвестная цена — по оценке, не ноль).
- **Failure outcome:** продолжение с поднятым бюджетом выполняет `skipped_budget` шаги; без поднятия — не выполняет.
- **Wave:** 2 (N-COST)
- **Coverage:** —

### CORE-07: Остановка по бюджету LLM
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** расход LLM приближается к `max_llm_usd` (runbook, `RESEARCH_MAX_LLM_USD`, `--max-llm-usd` или вход MCP/Fabric)
- **Preconditions:** лимит задан или действует `config.DEFAULT_MAX_LLM_USD`.
- **Steps:**
  1. Запустить прогон; дождаться остановки.
- **Expected result:** проверка до вызова останавливает исследовательские стадии с `terminal_code=budget_llm`, когда следующий вызов вышел бы за лимит минус резерв писателя; писатель тратит резерв и выпускает отчёт из собранного; ограничение действует и на повторы, и после продолжения.
- **Failure outcome:** модель без цены учитывается по консервативной оценке как `unknown`, никогда как 0.
- **Wave:** 4 (N-LLMB, KA-G01)
- **Coverage:** —

### CORE-08: Оплаченный сбой входит в бюджет и после продолжения
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01)
- **Trigger:** инструмент вернул ошибку, но провайдер списал стоимость; прогон затем продолжен
- **Preconditions:** ошибка несёт списанную стоимость (`ProwlError.cost_usd`).
- **Steps:**
  1. Прогнать до сбоя; продолжить прогон.
- **Expected result:** попытка записана в журнал с исходом и стоимостью в `finally`; после продолжения расход восстанавливается из сохранённых попыток **до** первой отправки, и сбой учитывается в бюджете.
- **Failure outcome:** если стоимость сбоя теряется или продолжение начинает расход с нуля — дефект (KA-10/KA-12); сценарий `FAIL`.
- **Wave:** 2 (N-COST; KA-10, KA-12)
- **Coverage:** —

### CORE-09: `verified` только с цитатой в сохранённом raw или двумя независимыми источниками
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01), читающий отчёт; вызывающий агент, потребляющий ledger
- **Trigger:** извлечение утверждений из шага
- **Preconditions:** raw шага сохранён с `raw_sha256`.
- **Steps:**
  1. Прогнать; открыть ledger и отчёт.
- **Expected result:** утверждение `verified` только если (а) его цитата найдена в сохранённом raw (после нормализации пробелов, sha256 совпадает) и значение стоит внутри цитаты, или (б) ≥2 согласных утверждения с разными известными `independence_key`; два инструмента над одним URL — один источник; transform не независим от своих входов.
- **Failure outcome:** цитата не найдена или источник `unknown` — утверждение не `verified`; v1 `verbatim` без цитаты понижается до `assumed` с раскрытием.
- **Wave:** 3 (N-EVID; KA-07, KA-08, KA-09)
- **Coverage:** —

### CORE-10: Конфликт остаётся конфликтом
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01), читающий отчёт
- **Trigger:** в одной группе утверждений появляются ≥2 разных значения
- **Preconditions:** —
- **Steps:**
  1. Прогнать; открыть ledger и отчёт.
- **Expected result:** все утверждения группы `conflict`, независимо от порядка поступления и от того, что пришло позже; утверждение без значения не подтверждает и не разрешает конфликт; отчёт показывает конфликт.
- **Failure outcome:** если итоговый статус группы зависит от порядка — тест независимости от порядка падает; сценарий `FAIL`.
- **Wave:** 3 (N-EVID)
- **Coverage:** —

### CORE-11: Потеря доказательств → `partial`, не `complete`
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01); вызывающий агент
- **Trigger:** запись raw или извлечение шага не удались
- **Preconditions:** —
- **Steps:**
  1. Прогнать до конца.
- **Expected result:** шаг не становится `completed`; прогон `partial` с `terminal_code=evidence_incomplete`, если не хватает только доказательств; отчёт раскрывает, каких шагов нет.
- **Failure outcome:** продолжение повторяет только извлечение, если raw сохранён, без новой оплаты (CORE-05).
- **Wave:** 2 (N-STATE; B-006, B-008)
- **Coverage:** —

### CORE-12: Переписать отчёт активного прогона нельзя
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01)
- **Trigger:** `prowl-research rewrite <run_id>` при живом прогоне
- **Preconditions:** прогон держит `RunLock`.
- **Steps:**
  1. Запустить переписывание.
- **Expected result:** команда отказывает, сообщает `active` и ничего не пишет — ни `report.md`, ни checkpoint.
- **Failure outcome:** после завершения прогона переписывание берёт блокировку и работает (только писатель, без расходов Prowl).
- **Wave:** 1 (N-OWN)
- **Coverage:** —

### CORE-13: Судья отвергает заведомо плохой отчёт
- **Status:** UNVERIFIED
- **Actor:** оператор (P-01) при приёмке
- **Trigger:** запуск судьи (`evals/judge.py`) на заранее испорченных фикстурах
- **Preconditions:** набор planted-bad фикстур: выдуманная цитата, неподтверждённая цифра, скрытый конфликт, отсутствующее раскрытие.
- **Steps:**
  1. Прогнать судью на каждой фикстуре; затем на размеченном наборе.
- **Expected result:** судья проваливает каждую planted-bad фикстуру; на размеченном наборе записано число согласия с человеком; код выхода прогона и код выхода судьи разделены.
- **Failure outcome:** фикстура, которую судья пропустил, блокирует приёмку; судья без калибровки не используется как доказательство качества.
- **Wave:** 6 (N-ACC, B-017)
- **Coverage:** —
