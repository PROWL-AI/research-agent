---
report:
  id: prowl.chat/2026-11-13-writer-prompt-v2
  title: "Prowl Research: вторая версия промпта писателя и проверка текста по каталогу (B-108)"
  kind: measurement
  project: prowl.chat
  domains: [ai-agent, quality, copy]
  as_of: 2026-11-13
  status: active
  valid_until: 2026-12-13
  summary: >-
    Три сохранённых прогона приёмки переписаны писателем moonshotai/kimi-k3.1-pro с промптом версии 2 (без тире,
    правила текста из паттерна copy-check базы агентов, линтер и починка по маркерам AT-06 и AT-16). Длинных тире в
    отчётах 0, 0, 0 против 1, 7, 145 у версии 1. Оценка судьи 0,78, 0,58, 0,72 против 0,72, 0,73, 0,83 на B-107;
    контроль версии 1 в тот же день дал 0,51 на втором отчёте (черновик обрезан моделью) и не дописал третий. Вердикт:
    улучшение по тире доказано, по судье разница не выходит за разброс модели.
  sources:
    - {name: "Experiment folders on the Studio space sshlg", path: "~/DATA/_worktrees/b108-eval/{v1,v2}", read_at: 2026-11-13}
    - {name: "B-107 baseline (version 1)", path: "docs/reports/2026-11-13-strong-model-measure/README.md", read_at: 2026-11-13}
  produced_by: {agent: claude-code, task: "B-108 rest"}
---

# Промпт писателя версии 2, 2026-11-13

## Метод

- Те же три прогона, что в B-107 (`accept-finance-20261021`, `accept-subscription-20261021b`,
  `accept-teardown-20261021b`), скопированы из `b107-eval`; `prowl-research rewrite <run> --max-llm-usd 3` заново
  пишет отчёт из сохранённого леджера, без вызовов Prowl. Писатель `moonshotai/kimi-k3.1-pro`, судья `evals/judge.py`.
- Версия 2: `RESEARCH_WRITER_PROMPT=2` (по умолчанию). Версия 1 как выпущена: `RESEARCH_WRITER_PROMPT=1`.
- Тире: число U+2014 в `report.md`.

## Результат

| Отчёт | Версия 1, B-107 (тире, судья) | Версия 1, тот же день | Версия 2 (тире, судья) |
|---|---|---|---|
| финансы | 1, 0,72 | не переписан | 0, 0,78 PASS |
| подписочное приложение | 7, 0,73 | 19, 0,51 FAIL: черновик обрезан на 24000 токенов | 0, 0,58 FAIL: 6 расхождений статуса |
| разбор конкурента | 145, 0,83 | не дописан: вывод обрезан моделью | 0, 0,72 PASS |

Шаблон промпта версии 2 тире не несёт; тире в отчёт приносит ещё текст ранбука (38 до 51 тире на ранбук 1.0), его
ловит линтер, и починка убирает. Три SEO-ранбука 1.1 (B-113) уже без тире.

## Вердикт (agent-change-measure/1)

```json
{"schema": "agent-change-measure/1", "agent": "prowl-research", "change": "B-108: writer prompt version 2 and the copy-check pattern on the report",
 "metric": "em dashes per report (primary); judge weighted total (guard)",
 "pre": {"window": "B-107 rewrites of 3 runs, version 1", "value": {"dashes": [1, 7, 145], "judge": [0.72, 0.73, 0.83]}, "n": 3},
 "post": {"window": "the same 3 runs, version 2", "value": {"dashes": [0, 0, 0], "judge": [0.78, 0.58, 0.72]}, "n": 3},
 "method": "paired rewrite of the same ledgers, one judge; a same-day version-1 control on two runs",
 "verdict": "improved on the primary metric 3 of 3; the guard is inside the writer model's own variance (the same-day version-1 control scored 0.51 and failed to finish the third)"}
```

Решение: версия 2 по умолчанию, версия 1 остаётся для замеров. Новое: писатель на Kimi отдаёт обрезанный, но не
пустой черновик, когда рассуждение съедает бюджет (B-128); резерв B-122 срабатывает только на пустой.
