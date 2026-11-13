---
report:
  id: prowl.chat/2026-11-13-strong-model-measure
  title: "Сильная модель Prowl Research: Mimo против Kimi K3.1 Pro на одних и тех же доказательствах"
  kind: measurement
  project: prowl.chat
  domains: [ai-agent, models, quality, cost]
  as_of: 2026-11-13
  status: active
  valid_until: 2026-12-13
  summary: >-
    Три отчёта приёмки переписаны из сохранённых доказательств писателем на xiaomi/mimo-v2.6-pro и на
    moonshotai/kimi-k3.1-pro, оба оценены одним судьёй (anthropic/claude-haiku-5.5). Kimi: 0,72, 0,73, 0,83,
    все PASS, 0 дефектов; Mimo: 0,41, 0,56, 0,59, ни одного PASS, 11 дефектов. Kimi дороже на запись отчёта
    (0,38 до 1,05 USD против 0,06 до 0,15). По правилу R31 выборка из трёх мала для «выигрыша», но «не хуже»
    показано на всех трёх: модель по умолчанию переведена на карту оператора (B-107).
  sources:
    - {name: "Experiment folder (copies of three acceptance runs)", path: "~/DATA/_worktrees/b107-eval", read_at: 2026-11-13}
    - {name: "Operator's model map 2026-11-06", path: "wiki synthesis/llm-models.md", read_at: 2026-11-12}
  produced_by: {agent: claude-code, task: "Fabric 870e0081 (session d1ee5351)"}
---

# Сильная модель: Mimo против Kimi K3.1 Pro, 2026-11-13

## Метод

- Три завершённых приёмочных прогона (`runs/accept-finance-20261021`, `runs/accept-subscription-20261021b`,
  `runs/accept-teardown-20261021b`) скопированы дважды; в каждой копии `prowl-research rewrite <run> --max-llm-usd 3`
  заново пишет отчёт из сохранённого леджера, без единого вызова Prowl. Меняется только `RESEARCH_LLM_MODEL_STRONG`
  (писатель и правка): `xiaomi/mimo-v2.6-pro` или `moonshotai/kimi-k3.1-pro`. Дешёвая модель та же.
- Каждый отчёт оценён `evals/judge.py` (судья `anthropic/claude-haiku-5.5`, порог 0,7, вето по доказанным кодом
  дефектам). Цена записи: разница `stats.llm_budget.spend_usd` чекпойнта до и после.
- Длинный отчёт разбора конкурента на Kimi в первом проходе пришёл пустым: оба черновика (8000 и 24000 токенов)
  ушли в рассуждение (`finish_reason='length'`, нет текста). Это дефект писателя, исправлен в B-122 (третья попытка
  с выключенным рассуждением), после чего этот отчёт перемерен; судья в первом запуске обрезал собственный ответ и
  перезапущен один раз.

## Результат

| Отчёт | Mimo: судья, дефекты, линтер после правки, цена записи | Kimi: судья, дефекты, линтер после правки, цена записи |
|---|---|---|
| финансы (`accept-finance-20261021`) | 0,41 FAIL, 6, 13, 0,058 USD | 0,72 PASS, 0, 0, 0,382 USD |
| подписочное приложение (`accept-subscription-20261021b`) | 0,56 FAIL, 5, 0, 0,081 USD | 0,73 PASS, 0, 0, 0,408 USD |
| разбор конкурента (`accept-teardown-20261021b`) | 0,59 FAIL, 0, 4, 0,147 USD | 0,83 PASS, 0, 0, 1,054 USD |

Среднее: Mimo 0,52, Kimi 0,76. Kimi лучше на каждом из трёх отчётов (на 0,17 до 0,31). Цена записи отчёта выросла в
среднем с 0,10 до 0,61 USD; на длинном отчёте 1,05 USD, из них две попытки сгорели на рассуждении.

## Вердикт (agent-change-measure/1)

```json
{"schema": "agent-change-measure/1", "agent": "prowl-research", "change": "B-107: strong model xiaomi/mimo-v2.6-pro -> moonshotai/kimi-k3.1-pro",
 "metric": "judge weighted total per report (evals/judge.py, judge anthropic/claude-haiku-5.5)",
 "pre": {"window": "3 acceptance runs rewritten 2026-11-13", "value": 0.52, "n": 3},
 "post": {"window": "the same 3 runs, same evidence", "value": 0.76, "n": 3},
 "method": "paired rewrite of the same ledgers, one judge, defects by code",
 "verdict": "inconclusive as a win (n=3); not worse on 3 of 3, better by 0.17 to 0.31 each"}
```

Решение: модель по умолчанию `moonshotai/kimi-k3.1-pro` (карта оператора 2026-11-06: решения и планирование на Kimi;
пользовательское содержимое только на китайских моделях, Kimi из их числа). Mimo остаётся в таблице цен и в любой
установке, где её выбрали в настройках. Следующий замер: доля проверенных утверждений (`metrics.json`) на первых
14 сутках облачных экземпляров.
