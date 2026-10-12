---
report:
  id: prowl.chat/2026-10-10-agent-deep-audit
  title: "Дополнительный аудит нового PROWL-AI/research-agent"
  kind: audit
  project: prowl.chat
  domains: [audit, ai-agent, reliability, billing, idempotency]
  as_of: 2026-10-10
  status: active
  valid_until: 2026-10-17
  summary: >-
    Найдены семь дополнительных открытых дефектов нового агента:
    чужая запись checkpoint, ложное verified, потеря evidence и расходов.
    Девять контрактных проверок падают, три контрольных проходят.
    Исправления внесены в общий план; runtime в этом срезе не изменён.
  sources:
    - {name: Agent source, url: "https://github.com/PROWL-AI/research-agent/tree/1dced8e381e63db2b61dbcd854b44d41450ed455", read_at: 2026-10-10}
    - {name: Executable probes, path: raw/probe_agent_contracts.py, read_at: 2026-10-10}
    - {name: Validated observations, path: raw/contracts-validated.log, read_at: 2026-10-10}
  produced_by: {agent: codex, task: KIMI-AGENT-AUDIT-20261010}
  supersedes: []
  consumers: [prowl.chat]
---

<sub>ssheleg skills — task-pipeline · agent-sync · agent-evals · evidence-docs · project-reports</sub>

# Дополнительный аудит нового агента

**Семь новых открытых дефектов KA-06…KA-12.** Вместе с прежними KA-03…KA-05
у нового агента десять подтверждённых проблем; общий план с двумя дефектами
Prowl содержит двенадцать. Это диагностика реализации, не доказательство
частоты ошибок на production. Исправления runtime в эту задачу не входят.

Этот срез дополняет, а не заменяет [RPT prowl.chat/2026-10-10-kimi-session-audit](https://github.com/PROWL-AI/prowl-app/blob/214112520a96552ecd58c60381ce2e50fe63b139/docs/reports/2026-10-10-kimi-session-audit/README.md).
Владелец — отдельный `PROWL-AI/research-agent`; одноимённый соседний проект к этому аудиту не относится.
[Handoff](../../HANDOFF.md) ведёт к общему плану исправлений и предыдущим resume-находкам.
Машинные данные: [findings.json](findings.json).

## Метод и границы

Проверены MCP lifecycle, оркестратор, workers, evidence ledger и учёт расходов.
Тесты используют реальные файловые checkpoint, flock, ledger и разбор billing в ProwlClient;
LLM и сетевые ответы синтетические. Ошибки записи и extraction внесены намеренно.
Никаких запросов к платным провайдерам и production-изменений не было.
Пробы проверяют ожидаемый контракт, поэтому красный результат здесь означает воспроизведение дефекта.
Контроли проверяют успешное сохранение evidence, обычный budget stop и восстановление настоящего orphan.

## Подтверждённые дефекты

### KA-06 · high · Чужой процесс меняет checkpoint активного владельца

**Наблюдение:** run → failed; startup → interrupted при занятом flock. [Источник](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/mcp_server.py#L102).

**Критерий исправления:** Все записи lifecycle и startup reconciliation требуют владения lock; отказ или чтение статуса не меняют checkpoint активного владельца.

Проверка: `test_ka06_non_owner_cannot_mutate_locked_checkpoint` в [исполняемом наборе](raw/probe_agent_contracts.py); [результат](raw/contracts-validated.log).

### KA-07 · high · Пустое значение снимает числовой конфликт

**Наблюдение:** 100 и 200: conflict → verified после третьего claim с value=None. [Источник](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/evidence/ledger.py#L184).

**Критерий исправления:** Статус пересчитывается по всей группе доказательств; отсутствие значения не является подтверждением и не снимает противоречие.

Проверка: `test_ka07_valueless_claim_cannot_erase_numeric_conflict` в [исполняемом наборе](raw/probe_agent_contracts.py); [результат](raw/contracts-validated.log).

### KA-08 · high · Выдуманная цитата получает verified

**Наблюдение:** Пустой raw; fabricated revenue 999 billion USD → verified. [Источник](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/orchestrator.py#L684).

**Критерий исправления:** verbatim требует привязки цитаты к сохранённому raw, а значение — к фрагменту источника; bool от LLM не является проверкой.

Проверка: `test_ka08_fabricated_verbatim_is_not_verified` в [исполняемом наборе](raw/probe_agent_contracts.py); [результат](raw/contracts-validated.log).

### KA-09 · medium · Два инструмента считаются независимыми источниками одного документа

**Наблюдение:** web_search + page_scraper одного URL → оба verified. [Источник](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/evidence/ledger.py#L205).

**Критерий исправления:** Разделить инструмент доставки и происхождение данных; один документ не даёт двух независимых подтверждений. Неизвестная независимость остаётся unknown/assumed.

Проверка: `test_ka09_same_document_is_not_two_independent_sources` в [исполняемом наборе](raw/probe_agent_contracts.py); [результат](raw/contracts-validated.log).

### KA-10 · high · Потеря raw или ошибка extraction заканчивается complete

**Наблюдение:** raw_write: complete, claim с отсутствующим raw_ref; extraction: complete, 0 claims. [Источник](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/subagent.py#L249).

**Критерий исправления:** Ошибки evidence сохраняются в typed outcome; complete запрещён при несохранённом raw или незавершённой extraction. Resume использует уже оплаченный raw и не делает повторный paid dispatch.

Проверка: `test_ka10_evidence_failure_cannot_report_complete` в [исполняемом наборе](raw/probe_agent_contracts.py); [результат](raw/contracts-validated.log).

### KA-11 · high · Первый известный расход исключает прошлые оценки из budget check

**Наблюдение:** При max_usd=.5: оценка .4 + известные .3; третий вызов всё равно исполняется. [Источник](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/orchestrator.py#L640).

**Критерий исправления:** По каждой попытке хранить actual/estimate/unknown, заменять оценку фактом только для той же попытки, считать общий расход без потерь и двойного счёта.

Проверка: `test_ka11_known_cost_does_not_discard_previous_estimates` в [исполняемом наборе](raw/probe_agent_contracts.py); [результат](raw/contracts-validated.log).

### KA-12 · high · Стоимость оплаченной ошибки теряется при resume

**Наблюдение:** Клиент знает .6, stats.cost_usd=None; resume снова вызывает tool при max_usd=.5. [Источник](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/agent/subagent.py#L190).

**Критерий исправления:** В finally каждой отправленной попытки сохранять известный расход независимо от успеха; новый клиент восстанавливает расходы до проверки следующего dispatch.

Проверка: `test_ka12_billed_failure_cost_survives_resume` в [исполняемом наборе](raw/probe_agent_contracts.py); [результат](raw/contracts-validated.log).

## Что эти результаты означают

- `verified` сейчас не является доказательством факта: проверяющий цитаты сопоставляет
  отчёт с ledger, а ошибки могут возникнуть раньше — при наполнении самого ledger.
  KA-07…KA-09 требуют проверки происхождения, а не только дополнительного LLM judge.
- KA-10 воспроизведён при локальном сбое записи одного raw-файла; тотальный отказ диска
  в этом тесте не имитировался. Сохранять остальные результаты можно, но успешный terminal status
  не должен скрывать потерянное evidence.
- KA-11 воспроизведён с одним worker. Это отдельный дефект смешанного учёта,
  а не уже документированный допуск на одновременные вызовы.
- KA-12 использует billed error envelope через реальный `ProwlClient._invoke`.
  Локальный known-cost stop работает; теряется именно сохранение стоимости неуспешной попытки.
- KA-06 использует второй file descriptor и реальную конкуренцию flock, без timing sleeps.
  Второй MCP-процесс способен воспроизвести тот же путь; провайдер не вызывается.

## Недоработки и непроверенные ворота

| ID плана | Статус | Что требуется |
|---|---|---|
| KA-G01 | implementation gap | Общий LLM budget, учёт по попыткам и восстановление usage. Сейчас [Budget](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/runbook.py#L36) не содержит лимита LLM; [usage](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/research_agent/llm.py#L60) живёт в памяти клиента. |
| KA-G02 | NOT_RUN | Finance/subscription: реальные run + judge, расходы, проверка человеком; сначала показать, что judge отвергает намеренно плохой отчёт. Наличие [judge.py](https://github.com/PROWL-AI/research-agent/blob/1dced8e381e63db2b61dbcd854b44d41450ed455/evals/judge.py#L206) не доказывает калибровку. Историческая ошибка запуска описана в первом аудите. |
| KA-G03 | NOT_RUN | Fabric host admission и выполнение опубликованного bundle: SHA, host/run receipt, status/report. Проверка деклараций не является host-приёмкой. |

## Проверки и воспроизведение

Из корня этого репозитория, Python 3.11 с установленными test dependencies:

```sh
PYTHONPATH=tests:. .venv/bin/python -m pytest -q -s docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m research_agent validate
```

- Контрактные проверки: **9 failed, 3 passed**, exit 1 — [receipt](raw/contracts-validated.log).
- Штатные тесты: результат в [baseline-suite.log](raw/baseline-suite.log). Они не включают `probe_*.py`.
- Проверки документации, исходных хешей и runbooks: [checks.json](raw/checks.json).
- Первый эксперимент [contracts.log](raw/contracts.log) — **TEST_ERROR для двух budget-сценариев**:
  одинаковые аргументы были дедуплицированы валидатором плана. В итоговом наборе у шагов
  разные домены, положительный budget-контроль проходит. Начальный результат не используется
  как доказательство KA-11 или как результат исправленного набора.
- Live providers, PostgreSQL parent-race, hosted CI, deploy и Fabric: **NOT_RUN**.

## Следующая работа

Общий план сохраняет KA-01…KA-05 и добавляет KA-06…KA-12 с зависимостями и acceptance.
Для агента сначала KA-06 (единое владение lifecycle), затем связанный пакет
KA-03/04/05/10 (устойчивая идентичность и восстановление evidence).
Учёт расходов KA-11/12 и ledger KA-07/08/09 можно разрабатывать независимо;
платную приёмку запускать после закрытия контрактных проверок.

---

**Made with [ssheleg skills](https://github.com/ssheleg/sshlg-skills)**

- [`task-pipeline`](https://github.com/ssheleg/task-pipeline) — план исправлений и передача
- [`agent-sync`](https://github.com/ssheleg/agent-sync) — локальное владение backlog
- [`agent-evals`](https://github.com/ssheleg/agent-stack) — проверки состояний и доказательств
- [`evidence-docs`](https://github.com/ssheleg/task-pipeline) — проверяемые ссылки и результаты
- `project-reports` — отчёт и индекс — not a skill this family ships
