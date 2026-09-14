# Статус передачи платформы строительной компании

Дата статуса: 14.09.2026  
Рабочая локальная ссылка: http://127.0.0.1:8782/04_Строительная_компания.html  
Демо-доступ для проверки: локальный пароль задается через `QH_DEMO_PASSWORD` и выдается отдельно.

## Что готово локально

- Интерфейс строительной компании работает через HTTP-сервер.
- Роли и доступы подключены: генеральный директор, главный инженер, прораб, бригадир, бухгалтер, юрист / разрешитель.
- В платформе есть объекты, поручения, запросы ДГАСК/Минстроя, документы, проверки, платежи, штрафы, уведомления, аудит и готовность запуска.
- Добавлены внутренний чат с локальным ИИ-помощником и календарь сроков по задачам, запросам, документам, проверкам, платежам и штрафам.
- Добавлен future-roadmap для следующего этапа: мобильная field-версия с фотофиксацией замечаний и платежная оркестрация Кыргызстана через реестр провайдеров, provider callback и подтверждение бухгалтера/директора.
- Директор видит блоки `Что осталось`, `Acceptance evidence`, `Completion audit`, `Пакет запуска ZIP`, Word-выгрузки и JSON-доказательства.
- Release ZIP собран в `dist/qurulush-hub-company-platform-current.zip`.
- Acceptance evidence сохранен в `outputs/acceptance-evidence-current.json`.
- Completion audit сохранен в `outputs/completion-audit-current.json`.

## Подтвержденные проверки

- Backend/regression suite: `129 tests OK`.
- Release acceptance: `ok=true`.
- Acceptance evidence: `failed_stages=[]`.
- Completion audit: `local_handoff_ready=true`, `overall_status=local_ready_external_blockers`, `production_ready=false`.
- Live smoke по локальной ссылке: `ok=true`.
- Browser smoke проверяет `calendar endpoint`, `chat endpoint`, `chat post endpoint`, `future roadmap endpoint`, `calendar UI render` и `chat AI UI action`.
- Browser smoke проверяет future-roadmap API/UI и наличие `future-roadmap.json` в launch bundle.
- Responsive smoke проверяет календарь, чат и future-roadmap на mobile/tablet/desktop.
- Health endpoint: `ok=true`, `storage=sqlite`, `db_ready=true`.

## Что осталось до production

Локальная передача готова. Боевой запуск остается внешним этапом и требует:

1. Поднять домен/VPS/HTTPS и проверить DNS, TLS, nginx и security headers.
2. Создать реальные аккаунты компании и отключить демо-пользователей.
3. Получить официальный SACC2/API-доступ и регламент обмена статусами.
4. Подключить ЭЦП, платежи, защищенное файловое хранилище, AV-сканер и удаленные backup hooks.
5. Выбрать банк/платежного агрегатора, сверить провайдеров по действующим реестрам НБКР и подключить платежный callback/reconciliation без автоматического списания без подтверждения.
6. Подготовить следующий мобильный контур: object-scoped доступ, камера, фото до/после, offline queue, upload через storage/AV и push/чат-уведомления.
7. Сверить справочник разрешительных документов, госпошлин, штрафов, сроков и форм по действующим официальным источникам.
8. После закрытия внешних gates заново выполнить `ops/go_no_go_check.py --require-production` и `ops/completion_audit.py`; production можно принимать только при `production_ready=true`.

## Где смотреть в интерфейсе

1. Открыть рабочую ссылку.
2. Войти директором.
3. Перейти в раздел `Готовность запуска`.
4. Открыть `Чат ИИ` и спросить: `Что сегодня срочно по срокам?`.
5. Открыть `Календарь` и проверить ближайшие сроки по объектам.
6. В `Готовность запуска` открыть `Что осталось`, `Acceptance evidence` и `Completion audit`.
7. Нажать `Мобайл/платежи`, чтобы увидеть следующий этап по мобильной field-версии и платежам Кыргызстана.
8. Скачать `Пакет запуска ZIP`, если нужно передать материалы DevOps, юристу или директору.
