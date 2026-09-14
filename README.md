# Qurulush Hub: платформа строительной компании

Рабочий кабинет строительной компании для взаимодействия с инспектором, региональным отделом, Министерством строительства КР, ДГАСК и sacc2-контуром.

## Быстрый старт

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 company_platform_server.py --port 8782
```

Открыть:

```text
http://127.0.0.1:8782/04_Строительная_компания.html
```

Демо-доступ:

```text
Локальный demo-пароль задается через QH_DEMO_PASSWORD и выдается отдельно.
```

## Что внутри

- Кабинет строительной компании: `extracted_dgask/04_Строительная_компания.html`.
- Backend/API/SQLite/readiness/Word/ZIP: `company_platform_server.py`.
- Полный Markdown-паспорт проекта: `PROJECT_EXPORT.md`.
- Статус передачи: `HANDOFF_STATUS.md`.
- Инструкция запуска: `RUN_COMPANY_PLATFORM.md`.
- Checklist production: `READINESS_CHECKLIST.md`.
- Тестовый отчет: `TEST_REPORT_COMPANY_PLATFORM.md`.
- План мобильной версии: `MOBILE_FIELD_APP_PLAN.md`.
- План платежей Кыргызстана: `KG_PAYMENT_ORCHESTRATION_PLAN.md`.
- Операционные скрипты production: `ops/`.

## Основные модули

- объекты строительства;
- поручения и замечания;
- запросы ДГАСК / Минстроя;
- разрешительные документы;
- проверки и предписания;
- госпошлины, начисления, штрафы и обжалования;
- внутренний чат с локальным ИИ;
- календарь сроков;
- роли и уровни доступа;
- журнал аудита;
- production readiness и launch bundle;
- future roadmap для мобильной field-версии и платежной оркестрации Кыргызстана.

## Проверки

Последняя локальная проверка:

- Backend/regression suite: `129 tests OK`.
- Browser smoke: `ok=true`.
- Responsive smoke: `ok=true` на mobile/tablet/desktop.
- Live smoke: `ok=true`.
- Release acceptance: `ok=true`.
- Acceptance evidence: `failed_stages=[]`.

## Production

Локальная передача готова. Для production нужны внешние этапы:

1. Домен/VPS/HTTPS/nginx.
2. Боевые учетные записи и отключение demo.
3. Официальный sacc2/API доступ и регламент статусов.
4. ЭЦП.
5. Платежный шлюз Кыргызстана с callback/reconciliation.
6. Production storage и AV scanner.
7. Remote backups.
8. Юридическая сверка справочника НПА, тарифов, штрафов, сроков и форм.
9. Финальный `go_no_go_check.py --require-production`.

## Документы для отделов

Для передачи другим отделам начинать с:

- `PROJECT_EXPORT.md` - полный обзор проекта.
- `HANDOFF_STATUS.md` - короткий статус.
- `READINESS_CHECKLIST.md` - что готово и что осталось.
- `MOBILE_FIELD_APP_PLAN.md` - будущая мобильная версия для поля.
- `KG_PAYMENT_ORCHESTRATION_PLAN.md` - платежи Кыргызстана.
- `dist/qurulush-hub-company-platform-current.zip` - актуальный release-пакет.

## Важное

GitHub Pages может показать только статическую HTML-демо-страницу. Полноценная рабочая платформа использует backend/API/SQLite, поэтому для работы отделов через интернет нужен VPS или другой backend-хостинг.
