# Qurulush Hub: платформа строительной компании

Дата экспорта: 14.09.2026  
Рабочая локальная ссылка: http://127.0.0.1:8782/04_Строительная_компания.html  
Демо-доступ: локальный пароль задается через `QH_DEMO_PASSWORD` и выдается отдельно.  
Текущий статус: локальная передача готова, production требует внешних доступов и интеграций.

## 1. Назначение проекта

Qurulush Hub - рабочий кабинет строительной компании для взаимодействия с инспектором, региональным отделом, Министерством строительства КР, ДГАСК и контуром sacc2.

Платформа закрывает основные процессы строительной компании:

- объекты строительства;
- поручения сотрудникам;
- запросы и уведомления от инспектора / ДГАСК / Минстроя;
- разрешительные документы;
- проверки и предписания;
- госпошлины, начисления, штрафы и обжалования;
- внутренний чат и ИИ-помощник;
- календарь сроков;
- уровни доступа;
- журнал действий;
- readiness, production launch bundle и evidence-пакеты.

## 2. Пользовательские роли

| Роль | Назначение | Ограничения |
| --- | --- | --- |
| Генеральный директор | Полный контроль, readiness, launch bundle, сотрудники, платежи, аудит | Видит все объекты и все production-разделы |
| Главный инженер | Техническая готовность, проверки, поручения, документы | Не управляет production-запуском |
| Прораб | Работа по назначенным объектам, задачи, проверки, доказательства | Видит только свои объекты |
| Бригадир | Исполнение замечаний, подтверждения, будущая фотофиксация | Ограниченный объектный доступ |
| Бухгалтер | Госпошлины, начисления, штрафы, подтверждение оплат | Не видит технические настройки запуска |
| Юрист / разрешитель | Разрешительные документы, НПА, обжалования, юридическая сверка | Не управляет платежным шлюзом |

## 3. Основные разделы интерфейса

- `Обзор`: статус объектов, срочные действия, боевой запуск.
- `Объекты`: карточки объектов, стадии, риск, инспектор, прогресс.
- `Поручения`: назначение задач сотрудникам, сроки, доказательства исполнения.
- `Справочник`: разрешительные документы, госпошлины, штрафы, проверки, роли и взаимодействия.
- `Запросы ДГАСК`: входящие запросы, ответы компании, статусы.
- `Документы`: комплектность, загрузка, версия, checksum, ЭЦП-контур.
- `Проверки`: плановые/внеплановые проверки, предписания, подготовка материалов.
- `Платежи и штрафы`: оплата, квитанция, обжалование, платежный статус.
- `Доступы`: роли, сотрудники, объектные назначения.
- `Оповещения`: внутренние уведомления и production alerts.
- `Аудит`: история действий по объектам и пользователям.
- `Чат ИИ`: внутренний чат с локальным ИИ-помощником.
- `Календарь`: единый календарь сроков по задачам, запросам, документам, проверкам, платежам и штрафам.
- `Готовность запуска`: production gates, evidence, Word/JSON, launch bundle, future-roadmap.

## 4. Реализованные рабочие процессы

- Создание объекта строительства.
- Создание обращения компании.
- Импорт входящего запроса от ДГАСК / Минстроя.
- Ответ на запрос ДГАСК.
- Назначение поручения прорабу, бригадиру или другому сотруднику.
- Закрытие поручения с подтверждением.
- Загрузка документа и фиксация версии.
- Подписание документа через будущий ЭЦП-hook.
- Подготовка материалов к проверке.
- Подтверждение оплаты с номером платежа и квитанцией.
- Обжалование штрафа / начисления.
- Добавление сотрудника, создание логина и назначение объектов.
- Отметка уведомлений прочитанными.
- Экспорт audit и exchange-пакетов без demo-паролей и token hash.
- Скачивание Word-документов по readiness, юридической сверке и production-пакетам.

## 5. Внутренний чат и ИИ

API:

- `GET /api/chat`
- `POST /api/chat`

Функции:

- хранение сообщений в SQLite;
- объектно-ролевой доступ к сообщениям;
- локальный ИИ-помощник без внешнего API-ключа;
- ответы по срокам, ДГАСК, штрафам, платежам и production-gates;
- audit-событие при отправке сообщения.

## 6. Календарь сроков

API:

- `GET /api/calendar`

Календарь собирает:

- поручения;
- запросы ДГАСК / Минстроя;
- документы;
- проверки;
- платежи;
- штрафы.

Статусы календаря:

- `overdue`;
- `today`;
- `soon`;
- `planned`;
- `unscheduled`;
- `done`.

## 7. Будущая мобильная field-версия

Документ: `MOBILE_FIELD_APP_PLAN.md`  
Roadmap API: `GET /api/production/future-roadmap`  
Интерфейс: `Готовность запуска` -> `Мобайл/платежи`

Цель мобильного контура:

- прораб, бригадир и исполнитель работают с телефона;
- видят только назначенные объекты и замечания;
- устраняют замечания;
- делают фото до/после;
- отправляют доказательство в платформу;
- работают при слабой связи через offline queue;
- получают push/чат-уведомления;
- используют календарь и ИИ-подсказки.

Планируемый API-contract:

- `/api/tasks/{id}/update` - статус устранения;
- `/api/documents/{id}/upload` - фото и документы после подключения storage/AV;
- `/api/inspections/{index}/prepare` - подготовка проверки;
- `/api/chat` - внутренний чат и ИИ;
- `/api/calendar` - сроки;
- новый multipart upload endpoint - фото, thumbnail, checksum, AV verdict, storage reference.

## 8. Платежи Кыргызстана

Документ: `KG_PAYMENT_ORCHESTRATION_PLAN.md`  
Roadmap API: `GET /api/production/future-roadmap`

Цель платежного контура:

- при уведомлении о госпошлине, начислении или штрафе создать payment intent;
- дать бухгалтеру или директору кнопку `Оплатить`;
- выбрать канал оплаты;
- получить provider callback / квитанцию;
- сверить сумму, назначение, валюту и payment id;
- закрыть платеж только после подтверждения.

Планируемые каналы:

- банковский счет и интернет-банкинг;
- Элкарт / банк-эквайринг;
- QR/deeplink в мобильный банк или электронный кошелек;
- платежная организация / агрегатор из актуального реестра НБКР;
- ручная бухгалтерская сверка с квитанцией, если callback недоступен.

Контроли:

- нет списания без явного подтверждения бухгалтера или директора;
- секреты провайдера только на backend;
- платежи идемпотентны, чтобы callback не задвоил оплату;
- спорный штраф можно отправить в обжалование вместо оплаты;
- audit хранит actor, role, object id, amount, provider, payment id, status и timestamp.

Источники для сверки:

- НБКР: реестр операторов платежных систем и платежных организаций - https://www.nbkr.kg/index1.jsp?item=97&lang=RUS
- НБКР: реестр операторов взаимодействия - https://www.nbkr.kg/index1.jsp?item=3488&lang=RUS
- НБКР: нормативные документы по платежным системам - https://www.nbkr.kg/contout.jsp?item=106&lang=RUS
- Элкарт / Межбанковский процессинговый центр - https://elcart.kg/
- MegaPay - https://megapay.kg/

## 9. Production readiness

Production пока не считается готовым, потому что нужны реальные внешние контуры:

1. Домен, VPS, HTTPS, nginx и security headers.
2. Боевые учетные записи и отключение demo-пользователей.
3. Официальный sacc2 / ДГАСК API URL, ключ и регламент статусов.
4. ЭЦП-провайдер и hook подписания документов.
5. Платежный шлюз и provider callback/reconciliation.
6. Внешнее файловое хранилище.
7. AV scanner для загружаемых файлов.
8. Регулярные и удаленные backup hooks.
9. Юридическая сверка справочника разрешений, НПА, тарифов, штрафов, сроков и форм.
10. Финальный `go_no_go_check.py --require-production`.

## 10. Основные API

| API | Назначение |
| --- | --- |
| `GET /api/health` | Безопасный публичный health |
| `POST /api/auth/login` | Вход |
| `POST /api/auth/logout` | Выход |
| `GET /api/state` | Состояние платформы с учетом роли |
| `GET /api/readiness` | Локальная и production готовность |
| `GET /api/calendar` | Календарь сроков |
| `GET /api/chat` | Чат |
| `POST /api/chat` | Сообщение в чат и ответ ИИ |
| `GET /api/production/plan` | План подключения production |
| `GET /api/production/future-roadmap` | Мобильный и платежный roadmap |
| `GET /api/production/launch-bundle.zip` | Единый пакет запуска |
| `GET /api/acceptance/evidence` | Acceptance evidence |
| `GET /api/acceptance/completion-audit` | Completion audit |
| `GET /api/legal/verification-packet` | Юридическая сверка |
| `GET /api/interaction/map` | Карта взаимодействия с ДГАСК / Минстроем |
| `GET /api/access/matrix` | Матрица ролей и доступов |

## 11. Word / JSON выгрузки

Директор может выгружать:

- production plan DOCX;
- evidence register DOCX;
- request pack DOCX;
- official letters DOCX;
- access matrix DOCX;
- interaction map DOCX;
- legal verification packet DOCX;
- QA evidence DOCX;
- status board DOCX;
- launch checklist DOCX;
- launch bundle ZIP;
- acceptance evidence JSON;
- completion audit JSON.

## 12. Тесты и доказательства

Последняя проверка:

- Backend/regression suite: `129 tests OK`.
- Browser smoke: `ok=true`.
- Responsive smoke: `ok=true` на mobile/tablet/desktop.
- Live smoke по `http://127.0.0.1:8782/`: `ok=true`.
- Release acceptance: `ok=true`.
- Acceptance evidence: `failed_stages=[]`.
- Completion audit: `local_handoff_ready=true`, `production_ready=false`.

Ключевые smoke-пункты:

- `calendar endpoint`;
- `chat endpoint`;
- `chat post endpoint`;
- `future roadmap endpoint`;
- `future roadmap UI action`;
- `production launch bundle endpoint`;
- `future-roadmap.json` внутри launch bundle;
- `mobile/tablet/desktop future roadmap responsive render`.

## 13. Основные файлы проекта

| Файл | Назначение |
| --- | --- |
| `company_platform_server.py` | Backend, SQLite, API, readiness, Word/ZIP генерация |
| `extracted_dgask/04_Строительная_компания.html` | Основной интерфейс строительной компании |
| `READINESS_CHECKLIST.md` | Полный checklist готовности |
| `RUN_COMPANY_PLATFORM.md` | Инструкция запуска |
| `HANDOFF_STATUS.md` | Короткий статус передачи |
| `TEST_REPORT_COMPANY_PLATFORM.md` | Отчет тестирования |
| `MOBILE_FIELD_APP_PLAN.md` | План мобильной field-версии |
| `KG_PAYMENT_ORCHESTRATION_PLAN.md` | План платежной оркестрации Кыргызстана |
| `.env.production.example` | Безопасный шаблон production env |
| `ops/production_smoke_check.py` | Live smoke deployed URL |
| `ops/build_release_package.py` | Сборка release ZIP |
| `ops/release_acceptance_check.py` | Проверка release ZIP |
| `ops/go_no_go_check.py` | Финальная go/no-go проверка |
| `ops/completion_audit.py` | Итоговый аудит готовности |
| `dist/qurulush-hub-company-platform-current.zip` | Актуальный release-пакет |

## 14. Команды запуска

Локальный запуск:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 company_platform_server.py --port 8782
```

Открыть:

```text
http://127.0.0.1:8782/04_Строительная_компания.html
```

Полная регрессия:

```bash
PYTHONPYCACHEPREFIX=/tmp/qh-pyc /Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest -v test_company_platform_backend.py test_ops_backup_restore_drill.py test_ops_go_no_go_check.py test_ops_release_package.py test_ops_production_smoke.py
```

Browser smoke:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_server_smoke.mjs
```

Responsive smoke:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_responsive_smoke.mjs
```

Сборка release:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 ops/build_release_package.py
```

Acceptance release:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 ops/release_acceptance_check.py dist/qurulush-hub-company-platform-current.zip
```

## 15. Что осталось сделать дальше

1. Поднять production-домен и HTTPS.
2. Подключить реальные аккаунты компании и отключить demo.
3. Получить официальный sacc2/API доступ.
4. Выбрать ЭЦП-провайдера и подключить подпись.
5. Выбрать банк/платежного агрегатора, сверить провайдеров по НБКР и реализовать payment provider registry.
6. Реализовать платежные intents, redirect/deeplink, callback и reconciliation.
7. Подключить external storage и AV scanner.
8. Реализовать мобильный upload для фотофиксации замечаний.
9. Собрать PWA/mobile shell и проверить на реальном телефоне.
10. Провести юридическую сверку справочника разрешений, тарифов, штрафов, форм и сроков.
11. Выполнить финальный production go/no-go.

## 16. Важное ограничение

Справочник разрешительных документов, госпошлин, штрафов и НПА сейчас является рабочим каталогом платформы. Перед production его нужно юридически сверить по действующим официальным источникам Кыргызской Республики. Demo-значения и тарифы нельзя считать официальными до такой сверки.
