---
report:
  id: prowl.chat/2026-11-12-agent-audit
  title: "Аудит Prowl Research и личного Research Agent, план раскатки на все инстанции"
  kind: audit
  project: prowl.chat
  domains: [audit, ai-agent, research, rollout, billing]
  as_of: 2026-11-12
  status: active
  valid_until: 2026-11-26
  summary: >-
    Prowl Research соответствует продукту Prowl (14 ранбуков называют живые инструменты, клиент MCP
    договаривается с prowl.chat), но отставал от шаблона research 1.7.1 базы агентов по деньгам, установке
    на общий Mac, моделям и проверке текстов. Главный разрыв (каждый платный заказ агента ждал клика
    оператора) закрыт в 0.5.0 дневным лимитом вызывающего. Ни в одном пространстве Mac Studio агенты не
    имели доступа ни к одному ресерч-агенту; план раскатки и её состояние ниже.
  sources:
    - {name: Agent source, url: "https://github.com/PROWL-AI/research-agent/tree/b6255bc", read_at: 2026-11-12}
    - {name: "Agents database, template research 1.7.1", path: "~/DATA/fabric-agents-database/templates/research", read_at: 2026-11-12}
    - {name: "Personal Research Agent", url: "https://github.com/ssheleg/research-agent/tree/11304f51", read_at: 2026-11-12}
    - {name: "Prowl product", path: "PROWL-AI/prowl-app mcp_server/_contracts.py, tool_bank.json", read_at: 2026-11-12}
  produced_by: {agent: claude-code, task: "Fabric afcbab45 (session d1ee5351)"}
---

# Аудит Prowl Research и личного Research Agent, 2026-11-12

Оператор, 2026-11-12, в чате сессии: «проведи его аудит, насколько он вообще актуальный, соответствует продукту,
соответствует нашим агентам, доработаем его ... раскидаем, добавим вместе с ресерч-агентом на все наши инстанции, на
студии, чтобы агенты имели доступ к этим ресерч-агентам и могли делать качественный ресерч».

Метод: архитектор базы агентов (`audit.py consult`, правило R29) назвал шаблон `research` 1.7.1 и его варианты
(`runbook`, `team-gateway` для этого репозитория, `corpus-desk` для личного агента); два независимых чтения кода
против шаблона, продукта и правил оператора; живые пробы без трат (ниже).

## 1. Живые пробы

| Проба | Результат |
|---|---|
| `service_status prowl-research.default` (Fabric Dashboards) | `ready`, 0.4.1, сборка `b6255bc` |
| `service_status research-agent.main` | `ready`, сборка `973348c7bd51`; `main` личного агента ушёл дальше (`11304f51`) |
| Клиент MCP этого агента (mcp 1.30.0) против `https://prowl.chat/mcp` | протокол `2025-11-25`, сервер `prowl_mcp 1.7.0`, 23 инструмента |
| `prowl_get_wallet` ключом агента (бесплатно) | ключ ограничен 5 USD в день и 10 USD всего (B-111) |
| Расход службы по журналу вызовов (`service.sqlite3`) | инструменты 1,13 USD за 83 вызова с 2026-10-10, модели 0,29 USD за 37 |
| MCP-серверы пользователей Studio (`~/.claude.json` пространств sshlg, passioncode, appvillis) | ни `prowl-research`, ни `research-agent` нет ни в одном пространстве |
| Ключи моделей (`openrouter.py list`) | `prowl-research` 50 USD, `research-agent` 70 USD в месяц; оба подняты до 100 USD (правило оператора от 2026-11-07) |

## 2. Prowl Research против шаблона, продукта и правил

| # | Разрыв | Важность | Состояние |
|---|---|---|---|
| 1 | Каждый платный заказ любого агента ждал клика оператора; у ключей облака нет дневного потолка (шаблон 1.6.0, приёмка 32; слово оператора `intake in-20261112-996c34`) | высокая | **закрыт в 0.5.0** (B-100) |
| 2 | Таблица цен не знала моделей карты оператора (Kimi K3.1 Pro, Sonnet 5.5, GLM 5.3, Gemini 3.1 Pro), DeepSeek занижен в 7 раз на входе | высокая | **закрыт в 0.5.0** |
| 3 | Ключ Prowl агента: 5 USD в день, 10 USD всего, кошелёк не читается перед прогоном | высокая | B-111, нужен вход в prowl.chat |
| 4 | Установка на второй аккаунт общего Mac: фиксированный порт, нет проверки владельца loopback, домен `gui/`, нет записи размещения (шаблон 1.3.0) | высокая | B-106; Studio пока ходит в облако |
| 5 | Сильная модель не по карте (Mimo вместо Kimi), нет запасной модели | средняя | B-107, только с замером до и после (R28) |
| 6 | R30: тексты отчёта и панели не проверяются правилами копирайтинга; в шаблоне отчёта длинное тире | средняя | B-108 |
| 7 | Панель показывает внутренние id и сырой JSON; настройка лимита есть только в API | средняя | B-109 |
| 8 | Архивную версию ранбука нельзя запустить (R28, приёмка 31) | средняя | B-110 |
| 9 | `mcp<2`: работает, пока Prowl держит старое рукопожатие | низкая | B-112 |
| 10 | Ранбуки не используют Moz (DA/PA) | низкая | B-113 |
| 11 | Нет паузы при полном диске и `metrics.json` (R31) | низкая | B-114 |

Соответствие продукту: все 14 ранбуков называют инструменты, которые есть в `tool_bank.json` Prowl (444), ни один не
назван в списке выведенных `tools/manifest.yaml`. Что уже соответствует шаблону: R28 (B-105, ворота в наборе тестов и
в ночной проверке), проверка цитат 1.2.4 (B-101), один процесс держит замок прогона.

## 3. Личный Research Agent (вариант `corpus-desk`)

Агент живой и развивается своим проектом (доска Fabric `368ab91b`); код этой сессией не меняется (правило Fabric:
чужой репозиторий меняет его проект). Найдено:

- переезд на Studio (BL-367) дважды откатан, ждёт `peer_owner` 1.3.x (BL-375, обещано к 2026-11-13);
- экземпляра PassionCode нет (BL-387, сборщик копии к 2026-11-18; репозиторий не создан, вентиль эффектов отказал без
  оператора);
- облачная копия Appvillis работает с 2026-11-05, но дверь выдачи ключей RA-12.5 просрочена (обещана к 2026-11-11),
  девять ключей на чтение ждут;
- модели не по карте (Mimo с запасной Haiku на пути с пользовательским содержимым), Telegram шлёт напрямую в Bot API
  вопреки правилу о собственном шлюзе, нет R30, R31, ворот R28, паузы `disk_low`, проверки цитат 1.2.4.

Всё это ушло его проекту запросом на доске со словами оператора (раздел 5).

## 4. Раскатка: кто куда ходит

Решение: агенты пространств Mac Studio ходят в **облачные** экземпляры, а не в локальные установки. Причины: у
пространств нет входа в GUI (`launchctl bootstrap gui/` падает), loopback общий для всех аккаунтов, а проверки
владельца у Prowl Research ещё нет (B-106); облачный режим уже построен (B-099) и даёт каждому вызывающему свой ключ,
свои задания и свой дневной лимит. Деньги одни (кошелёк prowl.chat оператора), стороны разделены ключами и
отдельной копией Appvillis.

| Сторона | Пространство или машина | Prowl Research | Research Agent |
|---|---|---|---|
| личная | MacBook | `prowl-research.default`, локально | `research-agent.main`, локально |
| личная | Studio `sshlg`, `assessment`, `aiteam1` | облако `prowl-research` (Heroku, личный аккаунт), ключ клиента на пространство | личный экземпляр после переезда (BL-367) |
| PassionCode | Studio `passioncode` | облако `prowl-research`, свой ключ клиента; своя копия, когда PassionCode понадобятся свои ключи провайдеров (B-115) | экземпляр PassionCode (BL-387) |
| Appvillis | Studio `appvillis`, `esim` | облако `appvillis-prowl-research` (Heroku, команда `telegramcrew`), копия `appvillis-com/appvillis-prowl-research` | облачная копия `https://104-248-136-152.sslip.io/mcp` |

### Состояние на 2026-11-13

| Где | Prowl Research | Проверка |
|---|---|---|
| MacBook | `prowl-research.default` 0.5.0, `ready`; Claude Code: `prowl-research` и `research-agent` Connected | `service_status`, `claude mcp list`, дымовой тест PASS (`pr-bbba08e73fd29941b607`) |
| облако `prowl-research` | 0.5.0 с B-116 до B-119, `ready`, `degraded: []`, в Fabric Dashboards `prowl-research.cloud` | well-known `status: ready` |
| Studio `sshlg` | ключ `studio-sshlg`, MCP `prowl-research` Connected | `initialize`, 7 инструментов, 14 ранбуков; учебное задание `pr-21fec45ebc627a9e8158` стартовало по лимиту и `completed` |
| Studio `passioncode` | ключ `studio-passioncode`, MCP Connected | 7 инструментов, 14 ранбуков |
| Studio `assessment` | ключ `studio-assessment`, MCP Connected | `claude mcp get` |
| облако `appvillis-prowl-research` | копия `62c8ce9` (оригинал `5722585`), `degraded`: нет ключа Prowl | well-known: ключ модели подключён после выпуска |
| Studio `appvillis` | ключ `studio-appvillis`, MCP `appvillis-prowl-research` Connected | `claude mcp get` |
| Studio `esim` | не подключено: SSH с MacBook не пускает | сообщение studio-agent, тред `9695cc44` |

Личное облако пока ходит в Prowl ключом этого же агента (лимит ключа 5 USD в день, 10 USD всего, B-111). Отдельные
ключи Prowl для обоих облаков: человеческий шаг (вход в prowl.chat). Research Agent: запрос его проекту, тред
`96893d02`.

## 5. Что передано другим

- Проекту Research Agent (`368ab91b`): запрос на доске со словами оператора и списком разрывов раздела 3.
- Владельцу ключа Prowl (оператор): два ключа Prowl для облачных экземпляров и лимит ключа агента (B-111).
