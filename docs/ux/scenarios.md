# Prowl Research — scenarios

<!-- Managed with super-ux (ux-contract v4). -->


## Index
| ID | Title | Status |
|---|---|---|
| SCN-001 | Обзор и свежесть | draft |
| SCN-002 | Найти запрос | draft |
| SCN-003 | Прочитать результат | draft |
| SCN-004 | Решение человека | draft |
| SCN-005 | Отмена | draft |
| SCN-006 | Учёт расходов | draft |
| SCN-007 | Настройки | draft |
| SCN-008 | Безопасное обучение | draft |

### SCN-001: Обзор и свежесть
- **Status:** draft
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — verification pending
- **Screen:** Обзор

### SCN-002: Найти запрос
- **Status:** draft
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — verification pending
- **Screen:** Запросы

### SCN-003: Прочитать результат
- **Status:** draft
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — verification pending
- **Screen:** Детали

### SCN-004: Решение человека
- **Status:** draft
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — verification pending
- **Screen:** Детали

### SCN-005: Отмена
- **Status:** draft
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — verification pending
- **Screen:** Детали

### SCN-006: Учёт расходов
- **Status:** draft
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — verification pending
- **Screen:** Расходы

### SCN-007: Настройки
- **Status:** draft
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — verification pending
- **Screen:** Настройки

### SCN-008: Безопасное обучение
- **Status:** draft
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
- **Coverage:** scripts/test-dashboard.mjs and tests/test_service.py — verification pending
- **Screen:** Обучение
