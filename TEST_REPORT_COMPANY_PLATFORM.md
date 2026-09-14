# Тестовый отчет: кабинет строительной компании

Дата проверки: 14.09.2026  
Файл платформы: `extracted_dgask/04_Строительная_компания.html`

## Последняя сводка проверки

- Backend/regression suite: `129 tests OK`.
- Browser smoke: `ok=true`, включая `calendar endpoint`, `chat endpoint`, `chat post endpoint`, `future roadmap endpoint`, `calendar UI render`, `chat AI UI action`, `future roadmap UI action`, `acceptance evidence endpoint`, `completion audit endpoint`, `status board UI action`, Word-выгрузки, карту взаимодействия, матрицу доступов, боевые доступы и production launch bundle.
- Responsive smoke: `ok=true` на mobile/tablet/desktop, включая `calendar responsive render`, `chat AI responsive action`, `future roadmap responsive render`, `acceptance evidence responsive render`, `completion audit responsive render`, `status board responsive render` и `legal source registry responsive render`.
- Accessibility smoke: `ok=true` для labels, keyboard login, landmarks, `aria-current`, toast live-region.
- Live production smoke по `http://127.0.0.1:8782/`: `ok=true`; локальная готовность `local_ready=True`, production внешние гейты ожидаемо `production_ready=False` до реальных интеграций.
- Release acceptance: `ok=true`; актуальный пакет `dist/qurulush-hub-company-platform-current.zip`.
- Go/no-go local stage: `ok=true`, `failed_stages=[]`.
- Cutover validation уточнен: API и UI различают `configuration_ready=true` и `ready_for_final_acceptance=false`, чтобы 100% заполненной конфигурации не выглядели как уже принятый production.
- QA evidence добавлен: `/api/production/qa-evidence`, `/api/production/qa-evidence.docx`, UI-кнопка `QA пакет`, файлы `qa-evidence.json` и `qurulush-qa-evidence.docx` внутри launch bundle.
- Status board добавлен: `/api/production/status-board`, `/api/production/status-board.docx`, UI-кнопка `Статус запуска`, файлы `production-status-board.json` и `qurulush-production-status-board.docx` внутри launch bundle.
- Acceptance evidence CLI/UI добавлен: `ops/collect_acceptance_evidence.py` сохраняет `outputs/acceptance-evidence-current.json`, а `/api/acceptance/evidence` и `/api/acceptance/evidence.json` показывают/выгружают очищенный JSON с redacted-командами, результатами release/live/backup стадий и `failed_stages`.
- Acceptance evidence live run: `ok=true`, `available=true`, `failed_stages=[]`, `stage_count=3`, файл `outputs/acceptance-evidence-current.json`, пароль и token hash отсутствуют.
- Completion audit CLI/API/UI добавлен: `ops/completion_audit.py` создает `outputs/completion-audit-current.json`, `/api/acceptance/completion-audit` и `/api/acceptance/completion-audit.json` показывают очищенный итоговый аудит; текущий статус `local_handoff_ready=true`, `overall_status=local_ready_external_blockers`, `production_ready=false`.
- Handoff status добавлен: `HANDOFF_STATUS.md` включен в release ZIP и дает короткую первую страницу передачи с рабочей ссылкой, демо-входом, подтвержденными проверками и шагами, которые остались до production.
- Внутренний чат и ИИ добавлены: `/api/chat` сохраняет переписку в SQLite, локальный ИИ отвечает по срокам, запросам ДГАСК, штрафам и платежам без внешнего API-ключа; вкладка `Чат ИИ` проверена browser/responsive smoke.
- Календарь сроков добавлен: `/api/calendar` собирает задачи, запросы, документы, проверки, платежи и штрафы с учетом ролей и объектов; вкладка `Календарь` проверена browser/responsive smoke.
- Future-roadmap добавлен: `/api/production/future-roadmap` фиксирует следующий этап по мобильной field-версии с фотофиксацией замечаний и платежной оркестрации Кыргызстана; UI-кнопка `Мобайл/платежи`, responsive smoke и launch bundle `future-roadmap.json` покрывают этот контур.

## Что реализовано

- Минималистичный рабочий интерфейс строительной компании.
- Экран входа по email и паролю в HTTP-режиме, с сохранением Bearer-токена в `sessionStorage` и отображением текущего пользователя.
- Production bootstrap: первый боевой администратор из переменных окружения и отключение демо-учеток.
- Внутренние уровни доступа: генеральный директор, главный инженер, прораб, бригадир, бухгалтер, юрист / разрешитель.
- Объектные назначения для сотрудников: прораб и бригадир видят только назначенные объекты и связанные с ними действия.
- Разделы: обзор, объекты, поручения, справочник требований, запросы ДГАСК, документы, проверки, платежи и штрафы, доступы, оповещения, аудит, готовность запуска.
- Рабочий справочник требований: разрешительные документы, госпошлины и начисления, штрафы и нарушения, запросы и уведомления, проверки, роли и доступы.
- Карта взаимодействия строительной компании с Минстроем/ДГАСК: входящие запросы инспектора, официальные уведомления, проверки, разрешительные документы, госпошлины, штрафы и обмен sacc2.
- Поручения сотрудникам: назначение, ролевое отображение по объектам, статусы, подтверждение исполнения и история.
- Матрица доступов строительной компании: генеральный директор, главный инженер, прораб, бригадир, бухгалтер, юрист / разрешитель с ограничениями по действиям и объектам.
- Журнал действий с фильтром по объектам и экспортом аудита для директора.
- Раздел готовности запуска: локальные проверки, production-гейты, статус HTTPS и внешних интеграций.
- Отчет `Что осталось до боевого запуска`: открытые production-шаги, ответственные, прогресс готовности и Word-выгрузка для директора.
- Быстрое назначение production-шагов из отчета `Что осталось`: директор меняет ответственного, дедлайн, статус и заметку/доказательство без перехода в отдельный реестр.
- Короткий отчет `Ближайшие действия`: директор получает top-actions JSON и Word-файл с 3-5 приоритетами, срочностью, сроками и ответственными.
- Production alerts: директор видит срочные, просроченные, заблокированные и первые шаги без дедлайна, затем формирует их в общий журнал уведомлений без дублей.
- Главный экран директора: блок `Боевой запуск` сразу показывает production-статус, готовность, оставшиеся шаги, alerts и первые действия; первые шаги можно назначить с dashboard.
- Проверка публичной доступности sacc2 без паролей: директор видит статус `sacc2.avn.kg` и fallback `sacc.avn.kg`, private/localhost URL блокируются; статус можно выгрузить в Word и зафиксировать в request-pack/evidence.
- Выгрузка production `.env` шаблона для DevOps из кабинета директора.
- Чеклист production-запуска со стадиями, ответственными, доказательствами, командами приемки и Word-выгрузкой.
- Сохранение состояния в `localStorage`.
- Рабочие действия:
  - создание обращения компании;
  - ответ на запрос ДГАСК;
  - создание объекта строительства;
  - назначение поручения сотруднику;
  - закрытие поручения с подтверждением;
  - загрузка/обновление документа с историей версий и SHA-256;
  - подготовка материалов к проверке;
  - подтверждение оплаты с номером платежа;
  - обжалование штрафа / начисления;
  - добавление сотрудника, создание логина и назначение объектов;
  - отметка уведомлений прочитанными;
  - импорт входящего запроса от ДГАСК / министерства;
  - экспорт очищенного пакета обмена;
  - просмотр и Word-выгрузка карты взаимодействия с Минстроем/ДГАСК;
  - просмотр и Word-выгрузка матрицы доступов строительной компании;
  - просмотр и Word-выгрузка отчета `Что осталось`;
  - просмотр и генерация production-alerts в журнал уведомлений;
  - dashboard-контроль боевого запуска сразу после входа;
  - проверка публичного статуса sacc2 без использования учетных данных, Word-выгрузка статуса и фиксация в запуске;
  - выгрузка production `.env` шаблона;
  - просмотр чеклиста production-запуска;
  - создание, просмотр, restore-drill и восстановление резервных копий;
  - сброс демо-данных.

## Проверенные сценарии

- Первичная загрузка страницы.
- Проверка HTTP-экрана входа, успешного входа директором и отображения текущего пользователя.
- Проверка safe health payload: публичный `/api/health` не раскрывает абсолютный путь к SQLite и отдаёт только безопасную диагностику `storage/db_ready/scheme`.
- Проверка выхода через интерфейс: после `Выйти` кабинет блокируется и снова показывается экран входа.
- Проверка security headers: API и HTML получают `nosniff`, `SAMEORIGIN`, `Referrer-Policy`, `Permissions-Policy`, CSP; HTTPS-ответ получает HSTS.
- Проверка JSON body limit: чрезмерный POST payload получает `413` до чтения тела в память.
- Проверка SQLite integrity-check: readiness показывает `sqlite_integrity=pass` при исправной базе, а поврежденный SQLite-файл получает ошибку `PRAGMA quick_check`.
- Проверка версии схемы SQLite: `schema_meta` получает текущую версию, а readiness показывает `schema_version=pass`.
- Проверка обслуживания сессий: просроченные токены автоматически отзываются, а readiness показывает `session_maintenance=pass`.
- Проверка директорского контроля сессий: `GET /api/sessions` доступен только директору, показывает текущую и другие активные сессии без token hash.
- Проверка завершения сессий: директор может очистить просроченные сессии и завершить другие входы без выхода из текущей сессии.
- Проверка локальной уборки smoke-сессий: `production_smoke_check.py` на `localhost/127.0.0.1` отзывает старые локальные тестовые сессии, а для удаленного HTTPS-домена не отзывает чужие production-входы.
- Проверка manifest резервных копий: readiness/listing проверяют SHA-256, а старый валидный manifest без checksum автоматически дополняется.
- Проверка свежести резервной копии: устаревший backup старше лимита получает fail-статус, порог настраивается через `QH_BACKUP_MAX_AGE_HOURS`.
- Проверка паспорта приемки: `/api/acceptance/passport` доступен только директору, объединяет readiness, production blockers и dry-run проверку последнего backup.
- Проверка Word-паспорта приемки: `/api/acceptance/passport.docx` доступен только директору, отдаёт валидный DOCX со статусами, backup и production blockers.
- Проверка production-плана: `/api/production/plan` доступен только директору, показывает статусы гейтов, ответственных, нужные переменные и следующий шаг по sacc2, ЭЦП, платежам, storage, AV, backup и юридической сверке.
- Проверка Word production-плана: `/api/production/plan.docx` доступен только директору, отдаёт валидный DOCX с планом подключения, sacc2, ЭЦП, платежами и настройками.
- Проверка production `.env` шаблона: `/api/production/env.example` доступен только директору, отдаёт `text/plain` с нужными QH-переменными и не содержит демо-пароль или token hash.
- Проверка checklist запуска: `/api/production/checklist` доступен только директору, содержит стадии `server_environment`, `external_integrations`, `backup_recovery`, `final_acceptance` и команды `production_smoke_check.py` / `go_no_go_check.py`.
- Проверка Word checklist запуска: `/api/production/checklist.docx` доступен только директору, отдаёт валидный DOCX с этапами запуска, командами приемки и `--hook-contract-smoke`.
- Проверка пошагового блока запуска: раздел `Готовность запуска` показывает `Что осталось до боевого запуска`, ответственных, нужные настройки и следующий шаг по каждому открытому blocker.
- Проверка отчета `Что осталось`: `/api/production/remaining-work` и `/api/production/remaining-work.docx` доступны директору, показывают открытые шаги, прогресс, ответственных и sacc2-интеграцию.
- Проверка назначения из отчета `Что осталось`: директор сохраняет ответственного, дедлайн, статус и заметку по открытому production gate; данные возвращаются в `remaining-work` и evidence-регистр.
- Проверка ближайших действий: `/api/production/top-actions` и `/api/production/top-actions.docx` доступны директору, отдают короткий список приоритетов, валидный DOCX и включаются в launch bundle.
- Проверка production-alerts: `/api/production/alerts` доступен директору, показывает urgent-уведомления по срокам и первые шаги без дедлайна; `/api/production/alerts/generate` добавляет их в журнал без повторных дублей и включается в launch bundle как `production-alerts.json`.
- Проверка QA evidence: `/api/production/qa-evidence` и `/api/production/qa-evidence.docx` доступны директору, показывают рабочую ссылку, live evidence, команды тестов и актуальные артефакты без секретов.
- Проверка status board: `/api/production/status-board` и `/api/production/status-board.docx` доступны директору, показывают рабочую ссылку, readiness, сколько осталось, ближайшие действия, все открытые шаги, QA-команды и артефакты без секретов.
- Проверка acceptance evidence: `/api/acceptance/evidence` и `/api/acceptance/evidence.json` доступны директору, показывают `ok`, `available`, `failed_stages`, этапы, команды без секретов и артефакты; `ops/collect_acceptance_evidence.py` редактирует пароль в командах/результатах, пишет current и timestamp JSON, а release package включает этот скрипт как обязательный операционный файл.
- Проверка completion audit: `ops/completion_audit.py` запускает release acceptance по current ZIP, читает `outputs/acceptance-evidence-current.json` и разделяет доказанную локальную передачу от внешних production blockers; `/api/acceptance/completion-audit` и `/api/acceptance/completion-audit.json` доступны только директору и отдают очищенный JSON без паролей, token hash и внутренних файлов.
- Проверка внутреннего чата и ИИ: `/api/chat` требует вход, сохраняет пользовательское сообщение и ответ `Qurulush AI`, не раскрывает demo-пароли/token hash, добавляет audit-событие и отвечает по текущим срокам, ДГАСК, штрафам и платежам.
- Проверка календаря сроков: `/api/calendar` требует вход, собирает открытые сроки из поручений, запросов, документов, проверок, платежей и штрафов; бригадир видит только назначенные объекты и не получает платежный контур.
- Проверка future-roadmap: `/api/production/future-roadmap` доступен только директору, содержит `field_mobile_app` и `kg_payment_orchestration`, источники НБКР/Элкарт, мобильный API-contract и контроль оплаты только после подтверждения.
- Проверка боевых доступов: `/api/production/account-cutover` и `/api/production/account-cutover.docx` доступны директору, показывают active demo, active real, покрытие ролей директора, главного инженера, прораба, бригадира, бухгалтера и юриста, и не раскрывают пароли, хеши или session-token данные.
- Проверка dashboard launch status: главный экран после входа показывает `Боевой запуск`, production-статус, оставшиеся шаги, alerts, переход в раздел готовности и сохраняет быстрое назначение шага в evidence-регистр.
- Проверка ZIP-пакета запуска: `/api/production/launch-bundle.zip` доступен только директору и содержит production-план, отчет боевых доступов, future-roadmap, чеклист запуска, паспорт приемки, acceptance evidence JSON, completion audit JSON, юридический пакет и `.env` шаблон.
- Проверка deployment ZIP: `/api/production/deployment-files.zip` доступен только директору, валидирует реальный домен, отклоняет `company.example` и выгружает nginx, systemd, go/no-go и summary под выбранный домен.
- Проверка юридического пакета сверки: `/api/legal/verification-packet` доступен директору и юристу, недоступен инженеру, содержит разрешения, госпошлины, штрафы, уведомления, проверки и поля `needs_review` для НПА/статьи/сумм.
- Проверка реестра юридических источников: `/api/legal/verification-packet` содержит `official_sources`, дату `official_sources_checked_at`, источники-кандидаты по категориям и предупреждает, что утратившие силу документы нельзя использовать как действующее право.
- Проверка Word юридического пакета: `/api/legal/verification-packet.docx` отдаёт валидный DOCX для сверки правовых оснований, тарифов, штрафов, официальных источников и ответственных ролей.
- Проверка карты взаимодействия: `/api/interaction/map` и `/api/interaction/map.docx` отдают сценарии запросов инспектора, уведомлений, проверок, разрешительных документов, госпошлин, штрафов и обмена sacc2.
- Проверка матрицы доступов: `/api/access/matrix` и `/api/access/matrix.docx` показывают роли директора, главного инженера, прораба, бригадира, бухгалтера и юриста без раскрытия служебных token hash.
- Проверка публичного статуса sacc2: `/api/external/sacc2-status`, `/api/external/sacc2-status.docx` и `/api/external/sacc2-status/attach` доступны только директору, не используют учетные данные, показывают `online/external_error/unreachable`, блокируют private/localhost URL и фиксируют результат в `sacc2_api` request-pack/evidence.
- Проверка, что автономный `file://` режим открывается сразу как демо-просмотр без серверной авторизации.
- Проверка responsive-интерфейса через HTTP: телефон 390px, планшет 820px и desktop 1440px открывают вход, dashboard-блок боевого запуска, навигацию, чат ИИ, календарь сроков, future-roadmap `Мобайл/платежи`, ключевые разделы, отчет `Что осталось`, acceptance evidence, completion audit, боевые доступы, production-alerts, статус sacc2, карту взаимодействия и матрицу доступов без горизонтального overflow страницы.
- Проверка accessibility-интерфейса через HTTP: явные labels входа, keyboard login, nav landmark, `aria-current`, live-region ошибок и toast-уведомлений.
- Проверка production bootstrap: новый администратор входит, демо-директор отключён, readiness отмечает `corporate_auth` и `bootstrap_admin` как пройденные.
- Проверка cutover validation: заполненная конфигурация принимает 12 gates, но без финальных live-проверок возвращает `ready_for_final_acceptance=false` и показывает следующий шаг по предупреждениям.
- Проверка strict production-start guard: неполная конфигурация блокирует старт, полная тестовая production-конфигурация с HTTPS и всеми hook-командами запускается.
- Проверка production preflight: команда `--preflight --require-production` выводит readiness-паспорт без занятия HTTP-порта, возвращает код `2` при незакрытых гейтах и `0` при полной тестовой production-конфигурации.
- Проверка JSON preflight: `--preflight-json` отдаёт валидный машинно-читаемый readiness-паспорт с checks/counts.
- Проверка hook executable validation: preflight не считает production-hook готовым, если указанная команда не существует или не исполняется.
- Проверка placeholder validation: preflight блокирует `CHANGE_ME`, `example.test`, `secret`, `YYYY-MM-DD` и слишком короткие production API-ключи.
- Проверка production operations kit: подготовлены runbook, systemd unit с `ExecStartPre`, nginx-шаблон и smoke-check развернутого URL.
- Проверка production smoke локальных gates: smoke-check требует наличие и не-fail статус для `sqlite_integrity`, `db_schema`, `schema_version`, `app_state`, `password_storage`, `session_maintenance`, `backup_manifests`, `backup_freshness`, `uploads`, `backups`.
- Проверка production smoke backup dry-run: smoke-check берет последнюю резервную копию из `/api/backups` и проверяет её через `/api/backups/verify` без восстановления данных; в `--require-production` отсутствие backup считается ошибкой.
- Проверка backup restore drill: отдельный ops-скрипт восстанавливает последнюю SQLite-копию во временную базу, сверяет счетчики и удаляет временную базу без изменения live DB.
- Проверка go/no-go агрегатора: отдельный ops-скрипт объединяет release acceptance, deployment audit, live smoke-check и backup restore drill в один JSON `ok/failed_stages`.
- Проверка release package: сборщик формирует zip с manifest/sha256 и исключает SQLite, uploads, backups, outputs, кеши и скриншоты.
- Проверка handoff status: `HANDOFF_STATUS.md` входит в release manifest и acceptance-check как обязательный файл передачи.
- Проверка release acceptance: собранный zip сверяется с manifest SHA-256, распаковывается в чистую папку, Python-файлы компилируются, preflight подтверждает `local_ready`, deployment audit подтверждает комплект production-файлов.
- Проверка deployment audit: текущий комплект содержит env-шаблон, systemd, nginx, runbook и smoke/go-no-go/restore команды; опасный env с placeholder-значениями и открытыми правами отклоняется.
- Проверка строгих hook-контрактов: при `QH_REQUIRE_HOOK_JSON=1` внешние команды обязаны вернуть JSON со статусом `ok/synced/signed/confirmed`, пустой или неподходящий ответ отклоняется.
- Проверка hook templates: release-архив включает `ops/hook_examples/`, а deployment audit отклоняет production env, если hook-команда указывает на example-template вместо реального провайдера.
- Проверка hook contract smoke: отдельный `ops/hook_contract_smoke.py` запускает hooks по env на dry-run payload, принимает JSON-статусы и отклоняет невалидный stdout.
- Проверка deployment renderer: `ops/render_deployment_files.py` генерирует готовые systemd/nginx/go-no-go файлы под реальный домен и отклоняет placeholder-домены.
- Проверка tamper detection: acceptance-check отклоняет zip, если файл внутри архива изменён после сборки.
- Отрисовка 12 разделов навигации.
- Отрисовка 6 ролей доступа.
- Отрисовка матрицы доступа с отдельными правами чтения и загрузки документов.
- Проверка стартовых объектов и запросов.
- Проверка серверной фильтрации `/api/state` по роли: бригадир не получает запросы, документы и деньги; бухгалтер получает деньги и документы; юрист получает запросы, документы и штрафной контур.
- Проверка серверной фильтрации `/api/state` по объектам: прораб видит объекты 1 и 2, бригадир видит объект 3.
- Проверка поручений: бухгалтер не получает задачи; бригадир видит только поручения по своему объекту; прораб закрывает поручение только с подтверждением.
- Проверка создания поручения через `POST /api/tasks` и обновления через `POST /api/tasks/{id}/update`.
- Проверка раздела справочника требований: категории, фильтр, карточка требования и предупреждение о юридической сверке.
- Проверка `GET /api/reference/export`: доступ только после входа, формат `qurulush-reference-catalog-v1`, экспорт содержит категории документов/штрафов и не раскрывает служебные данные.
- Проверка `GET /api/reference/export.docx`: доступ только после входа, корректный DOCX content type, валидный Office zip-пакет, внутри есть категории и предупреждение о статусе данных.
- Проверка `GET /api/legal/verification-packet`: доступ только директору/юристу, формат `qurulush-legal-verification-packet-v1`, есть поля для НПА, статьи/пункта, подтверждения тарифов/штрафов, даты и ответственного за сверку.
- Проверка `GET /api/legal/verification-packet.docx`: корректный DOCX content type, валидный Office zip-пакет, внутри есть чек-лист правовой сверки по категориям справочника.
- Проверка защиты входа от перебора: после 5 неверных паролей вход временно блокируется с `429`.
- Проверка восстановления входа после окончания блокировки и очистки счётчика после успешного входа.
- Проверка запрета ответа на запрос ДГАСК для роли `Бригадир`.
- Проверка запрета действия по чужому объекту: прораб не отвечает по объекту 3, бригадир не готовит проверку по объекту 2.
- Проверка ответа на запрос ДГАСК от роли `Главный инженер`.
- Проверка уменьшения KPI открытых запросов после ответа.
- Проверка подтверждения оплаты от роли `Бухгалтер`.
- Проверка обязательного номера платежа при подтверждении оплаты.
- Проверка сохранения номера платежа, автора, даты и истории оплаты.
- Проверка, что юрист не может подтверждать оплату, но может подать обжалование.
- Проверка мягкой миграции старых оплаченных записей без номера платежа.
- Проверка создания нового обращения от роли `Юрист / разрешитель`.
- Проверка импорта входящего запроса ДГАСК из интерфейса директором.
- Проверка сохранения созданного обращения и статуса оплаты после перезагрузки страницы.
- Проверка создания объекта через API.
- Проверка добавления сотрудника через API.
- Проверка входа приглашённого сотрудника по созданному email и временному паролю.
- Проверка создания резервной копии SQLite директором.
- Проверка списка резервных копий через `GET /api/backups`.
- Проверка dry-run проверки backup через `POST /api/backups/verify`: checksum, `PRAGMA quick_check` и payload проверяются без изменения рабочей базы.
- Проверка restore-drill backup через `POST /api/backups/restore-drill`: копия поднимается во временную SQLite-базу, сверяются счетчики и live DB не меняется.
- Проверка восстановления состояния через `POST /api/backups/restore`: backup без manifest, повреждённый backup и backup с несовпавшим SHA-256 отклоняются; после restore временно созданная запись исчезает, а событие восстановления попадает в аудит.
- Проверка формы приглашения сотрудника с выбором назначенных объектов.
- Проверка экрана журнала действий в интерфейсе.
- Проверка `GET /api/audit/export`: доступ только директору, формат `qurulush-audit-export-v1`, экспорт содержит действия и не раскрывает пароли/сессии/внутренние файлы.
- Проверка экрана готовности запуска в интерфейсе.
- Проверка `/api/readiness`: доступ только директору, локальный контур подтверждён, production-гейты помечены как недостающие без официальных интеграций.
- Проверка прочтения одного и всех уведомлений через API.
- Проверка физического сохранения загруженного файла и защищённого скачивания через `/api/documents/{id}/file`.
- Проверка запрета неподдерживаемого типа файла при загрузке документа.
- Проверка версий документа: повторные загрузки накапливаются как `VER-1`, `VER-2`.
- Проверка SHA-256 контрольной суммы загруженного файла.
- Проверка отказа маскированного исполняемого файла с разрешённым расширением.
- Проверка подключаемого AV-сканера: чистый файл проходит, файл с тестовой сигнатурой отклоняется до сохранения.
- Проверка readiness-гейта `av_scan`: при заданном `QH_AV_SCANNER` статус становится `pass`.
- Проверка внешней синхронизации документа: `QH_STORAGE_SYNC_CMD` получает файл, копирует его во внешнее место, а версия документа получает `storage_synced_at`.
- Проверка readiness-гейта `object_storage`: при `QH_STORAGE_MODE=external` и `QH_STORAGE_SYNC_CMD` статус становится `pass`.
- Проверка ЭЦП-подписания: внешний контур получает JSON-пакет, документ сохраняет `signature_status`, отказ ЭЦП не меняет документ.
- Проверка readiness-гейта `eds`: при `QH_EDS_PROVIDER`, `QH_EDS_API_URL` и `QH_EDS_SIGN_CMD` статус становится `pass`.
- Проверка payment gateway hook: внешний шлюз получает JSON-пакет, подтверждённая оплата сохраняет `payment_gateway_synced_at`, отказ шлюза не меняет статус начисления.
- Проверка readiness-гейта `payments`: при `QH_PAYMENT_GATEWAY_CMD` статус становится `pass`.
- Проверка ролевого доступа к файлам: без токена отказ, бригадиру отказ, директору разрешено.
- Проверка хранения сессий в SQLite: в базе хранится SHA-256 хеш токена, logout помечает сессию отозванной.
- Проверка смены пароля приглашённым сотрудником: старый пароль отключается, новый работает, параллельная сессия отзывается.
- Проверка автоматических SQLite-бэкапов по расписанию: стартовая копия и следующая копия по таймеру создаются с JSON-manifest.
- Проверка remote-hook бэкапа: внешняя команда получает `.sqlite3` и `.json` manifest, копирует их во внешнее место, а manifest получает `remote_synced_at`.
- Проверка импорта внешнего запроса через `POST /api/exchange/incoming`: доступ только директору, источник валидируется, запись попадает в очередь компании.
- Проверка экспорта через `GET /api/exchange/export`: доступ только директору, пакет не содержит пользователей, паролей, внутренних имён файлов и локальных защищённых URL.
- Проверка sacc2 sync hook: директор отправляет очищенный пакет через `POST /api/sacc2/sync`, роль без полного доступа получает отказ, API-ключ не попадает в payload.
- Проверка readiness-гейта `sacc2_api`: при `QH_SACC2_API_URL`, `QH_SACC2_API_KEY` и `QH_SACC2_SYNC_CMD` статус становится `pass`.
- Проверка HTTPS health endpoint на временном self-signed сертификате.
- Проверка logout: токен становится недействительным после выхода.

## Результат автоматического smoke-test

Команда:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_smoke.mjs
```

Результат:

```json
{"ok":true,"checks":["initial render","access matrix render","password change action render","exchange import action render","audit screen render","readiness screen render","reference catalog render and filter","task role scoping","task close with evidence","role access restriction","request reply and status update","payment update","payment number persistence","fine appeal workflow","new request creation","external request import","task persistence","localStorage persistence"]}
```

## Результат backend unit-тестов

Команда:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest -v test_company_platform_backend.py
```

Результат:

```text
test_audit_export_requires_director_and_is_sanitized ... ok
test_backup_endpoint_requires_director_and_writes_manifest ... ok
test_backup_list_and_restore_roundtrip ... ok
test_bootstrap_admin_can_replace_demo_users ... ok
test_configured_antivirus_scanner_checks_uploads_before_storage ... ok
test_configured_storage_sync_command_marks_uploaded_documents ... ok
test_document_upload_and_inspection_prepare ... ok
test_document_versions_checksum_and_unsafe_content_rejection ... ok
test_eds_signing_command_signs_documents_before_persisting ... ok
test_exchange_import_and_export_are_permissioned_and_sanitized ... ok
test_health_and_login ... ok
test_https_health_with_self_signed_certificate ... ok
test_json_body_size_limit_rejects_large_posts ... ok
test_legacy_paid_records_get_payment_metadata ... ok
test_login_attempt_lockout_and_recovery ... ok
test_logout_invalidates_token ... ok
test_object_assignments_scope_visibility_and_actions ... ok
test_objects_team_and_notifications ... ok
test_passwords_are_hashed_outside_app_state ... ok
test_payment_gateway_command_confirms_or_rejects_payment_before_persisting ... ok
test_preflight_require_production_passes_complete_test_configuration ... ok
test_preflight_require_production_reports_blockers ... ok
test_preflight_rejects_missing_hook_executable ... ok
test_preflight_rejects_placeholder_production_values ... ok
test_readiness_report_requires_director_and_lists_production_gates ... ok
test_reference_docx_export_requires_login_and_contains_catalog ... ok
test_reference_export_requires_login_and_marks_working_catalog ... ok
test_require_production_allows_complete_test_configuration ... ok
test_require_production_blocks_incomplete_configuration ... ok
test_remote_backup_command_syncs_backup_and_manifest ... ok
test_role_permissions_and_business_actions ... ok
test_sacc2_sync_command_receives_sanitized_exchange_payload ... ok
test_scheduled_backups_create_sqlite_copies ... ok
test_security_headers_are_sent_for_api_and_static_files ... ok
test_sessions_are_stored_as_hashes_in_sqlite ... ok
test_state_is_scoped_by_role ... ok
test_tasks_are_scoped_and_require_evidence_to_close ... ok
test_user_can_change_password_and_revoke_other_sessions ... ok

Ran 43 tests

OK
```

## Результат backup restore drill и release-package тестов

Команда:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest -v test_ops_backup_restore_drill.py test_ops_release_package.py
```

Результат:

```text
test_choose_backup_rejects_empty_backup_directory ... ok
test_restore_drill_marks_schema_defaults_filled_for_legacy_backup ... ok
test_restore_drill_restores_backup_into_isolated_temp_database ... ok
test_build_release_package_contains_manifest_and_required_files ... ok
test_build_release_package_excludes_private_runtime_files ... ok
test_collect_release_files_excludes_runtime_data ... ok
test_release_package_acceptance_check_preflights_unpacked_archive ... ok
test_release_acceptance_rejects_tampered_archive_file ... ok

Ran 8 tests

OK
```

## Результат production smoke unit-тестов

Команда:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest -v test_ops_production_smoke.py
```

Результат:

```text
test_assert_backup_verification_requires_integrity_sha_and_counts ... ok
test_assert_acceptance_passport_checks_local_and_backup_status ... ok
test_assert_acceptance_passport_requires_production_when_requested ... ok
test_assert_local_readiness_gates_accepts_pass_and_warning ... ok
test_assert_local_readiness_gates_rejects_failed_or_missing_status ... ok
test_assert_local_readiness_gates_rejects_missing_gate ... ok
test_production_blockers_returns_only_required_non_pass_checks ... ok
test_select_latest_backup_accepts_first_entry_and_allows_empty_non_production ... ok
test_select_latest_backup_requires_existing_backup_for_production ... ok

Ran 9 tests

OK
```

## Результат go/no-go unit-тестов

Команда:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest -v test_ops_go_no_go_check.py
```

Результат:

```text
test_build_go_no_go_result_reports_failed_stages ... ok
test_main_requires_at_least_one_check_source ... ok
test_run_stage_captures_success_and_failure ... ok

Ran 3 tests

OK
```

Полный Python-набор `test_company_platform_backend.py test_ops_backup_restore_drill.py test_ops_go_no_go_check.py test_ops_hook_contract_smoke.py test_ops_release_package.py test_ops_render_deployment_files.py test_ops_production_smoke.py`: 123 tests OK.

Живой go/no-go результат по release zip, локальной ссылке и backup-каталогу:

```json
{"ok": true, "checked_at": "2026-09-13 17:42:05", "release": "dist/qurulush-hub-company-platform-current.zip", "stages": [{"name": "release_acceptance", "ok": true}, {"name": "deployment_audit", "ok": true}, {"name": "live_smoke", "ok": true}, {"name": "backup_restore_drill", "ok": true}], "failed_stages": []}
```

Живой статус публичных sacc2-адресов без ввода учетных данных:

```json
{"summary_status":"online","targets":[{"url":"https://sacc2.avn.kg","status":"external_error","status_code":502},{"url":"https://sacc.avn.kg","status":"online","status_code":200}],"credentials_used":false}
```

Фиксация этого статуса в запуске проверена через live smoke/go-no-go: `sacc2 public status attachment=blocked`, gate `sacc2_api` получает служебный номер `SACC2-STATUS-*`, request-pack/evidence обновляются без паролей и token hash.

В отчете `Что осталось` добавлена управленческая срочность: `top_actions`, `by_urgency`, метки `Просрочено/Сегодня/Скоро/Запланировано/Без срока` и расчет `days_left` по назначенным дедлайнам.

Word-отчет `qurulush-production-top-actions.docx` выгружен из live API и отрендерен через `render_docx.py`; проверена 1 страница, таблица ближайших действий читается без обрезки текста.

Добавлен директорский слой `Production alerts`: API `/api/production/alerts` выделяет просроченные, сегодняшние, ближайшие, заблокированные и первые no-deadline шаги запуска; `/api/production/alerts/generate` переносит их в общий журнал уведомлений с ключом дедупликации.

Word-отчет `qurulush-sacc2-public-status.docx` выгружен из live API и отрендерен через `render_docx.py`; проверена 1 страница без обрезки текста и таблиц.

## Результат responsive smoke-test

Команда:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_responsive_smoke.mjs
```

Результат:

```json
{"ok":true,"checks":["mobile responsive render","mobile remaining work responsive render","mobile sacc2 public status responsive render","mobile interaction map responsive render","mobile access matrix responsive render","mobile completion audit responsive render","tablet responsive render","tablet remaining work responsive render","tablet sacc2 public status responsive render","tablet interaction map responsive render","tablet access matrix responsive render","tablet completion audit responsive render","desktop responsive render","desktop remaining work responsive render","desktop sacc2 public status responsive render","desktop interaction map responsive render","desktop access matrix responsive render","desktop completion audit responsive render"]}
```

## Результат accessibility smoke-test

Команда:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_accessibility_smoke.mjs
```

Результат:

```json
{"ok":true,"checks":["login labels","keyboard login","landmarks","active nav aria-current","toast live region"]}
```

Живой restore drill локального backup-каталога:

```json
{"ok": true, "file": "company_platform_20260913_094410_017783_325de2.sqlite3", "source_integrity": "PRAGMA quick_check: ok", "restored_integrity": "PRAGMA quick_check: ok", "backup_counts": {"objects": 3, "requests": 3, "tasks": 0, "documents": 5, "audit": 3}, "restored_counts": {"objects": 3, "requests": 3, "tasks": 3, "documents": 5, "audit": 3}, "migration_filled": {"tasks": 3}, "temp_database_removed": true}
```

## Результат HTTP integration smoke-test

Команда:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_server_smoke.mjs
```

Результат:

```json
{"ok":true,"checks":["python server health","security headers on API and HTML","readiness endpoint flags production gates","acceptance passport endpoint","acceptance passport docx endpoint","acceptance evidence endpoint","acceptance evidence JSON endpoint","completion audit endpoint","completion audit JSON endpoint","backup restore drill endpoint","session control endpoint","session revoke others endpoint","production plan endpoint","production plan docx endpoint","production env example endpoint","production launch checklist endpoint","production launch checklist docx endpoint","reference export endpoint","reference docx export endpoint","legal verification packet endpoint","legal verification packet docx endpoint","production launch bundle endpoint","deployment files bundle endpoint","http frontend load","http login screen and session","readiness UI render","session control UI render","remaining launch steps UI render","production launch bundle UI action","deployment files bundle UI action","production plan UI render","production env example UI action","production launch checklist UI render","production launch checklist docx UI action","acceptance passport UI render","acceptance evidence UI action","acceptance evidence JSON UI action","completion audit UI action","completion audit JSON UI action","audit UI render","reference UI render and filter","legal verification packet UI action","api role login","ui task creation persisted to SQLite","ui task completion with evidence persisted to SQLite","ui request reply persisted to SQLite","ui payment persisted to SQLite","ui payment number persisted to SQLite","ui fine appeal persisted to SQLite","ui new request persisted to SQLite","ui external request import persisted to SQLite","ui object creation persisted to SQLite","ui file upload persisted to SQLite","api document signing persisted to SQLite","ui document version and checksum rendered","exchange export is permissioned and sanitized","protected document download requires API token","document download follows role permissions","ui team invite persisted to SQLite","ui object assignment control rendered","invited employee can log in","invited employee can change password","director can create SQLite backup","director can dry-run restore SQLite backup","director can list and restore SQLite backup","director can export sanitized audit log","ui notifications read state persisted to SQLite","ui logout returns to login screen","server audit updated"]}
```

Эта проверка поднимает локальный Python-сервер, открывает кабинет компании через HTTP, выполняет действия в интерфейсе и затем подтверждает через API, что изменения сохранились в SQLite: production checklist, поручение, закрытие поручения с подтверждением, ответ, оплата с номером платежа, обжалование начисления, обращение, импорт запроса ДГАСК, объект, файл документа, версия и SHA-256 документа, сотрудник, назначение объектов, login приглашённого сотрудника, смена временного пароля, резервная копия, restore-drill, список и восстановление бэкапа, уведомления и аудит.

## Результат production smoke-check живой локальной ссылки

Команда:

```bash
QH_DEMO_PASSWORD='REDACTED' python3 ops/production_smoke_check.py --base-url http://127.0.0.1:8782/ --email director@company.kg --password 'REDACTED'
```

Результат:

```json
{"ok": true, "checks": ["health scheme=http", "login user=director@company.kg", "local gate sqlite_integrity=pass", "local gate db_schema=pass", "local gate schema_version=pass", "local gate app_state=pass", "local gate password_storage=pass", "local gate session_maintenance=pass", "local gate backup_manifests=pass", "local gate backup_freshness=pass", "local gate uploads=pass", "local gate backups=pass", "readiness local_ready=True production_ready=False", "sessions active=10", "sessions other=9", "production plan ready=False", "production plan blockers=12", "production env example=ok", "production launch checklist ready=False", "production launch checklist blockers=12", "production launch checklist docx=ok", "legal verification packet items=8", "legal verification packet docx=ok", "production launch bundle=ok", "deployment files bundle=ok", "backup verify company_platform_20260913_094410_017783_325de2.sqlite3=ok", "acceptance passport local=True", "acceptance passport production=False", "acceptance passport backup=pass"]}
```

## Результат DOCX render-проверки production-плана

Контрольный Word-файл выгружен из живого API:

```text
outputs/qurulush-production-plan.docx
```

Команда визуальной проверки:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /Users/maxai/.codex/plugins/cache/openai-primary-runtime/documents/26.909.11809/skills/documents/render_docx.py outputs/qurulush-production-plan.docx --output_dir outputs/qurulush-production-plan-render --emit_pdf
```

Результат: отрендерены 2 страницы PNG и PDF в `outputs/qurulush-production-plan-render/`. Визуальная проверка страниц показала читаемый план, корректные переносы длинных переменных и отсутствие обрезания.

## Результат DOCX render-проверки чеклиста запуска

Контрольный Word-файл выгружен из живого API:

```text
outputs/qurulush-production-launch-checklist.docx
```

Команда визуальной проверки:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /Users/maxai/.codex/plugins/cache/openai-primary-runtime/documents/26.909.11809/skills/documents/render_docx.py outputs/qurulush-production-launch-checklist.docx --output_dir outputs/qurulush-production-launch-checklist-render --emit_pdf
```

Результат: отрендерены 2 страницы PNG и PDF в `outputs/qurulush-production-launch-checklist-render/`. Визуальная проверка страниц показала читаемый checklist, корректные переносы команд и отсутствие обрезания.

## Результат DOCX render-проверки паспорта приемки

Контрольный Word-файл выгружен из живого API:

```text
outputs/qurulush-acceptance-passport.docx
```

Результат: отрендерены 2 страницы PNG и PDF в `outputs/qurulush-acceptance-passport-render/`. Визуальная проверка страниц показала читаемые таблицы, корректный перенос длинных значений и отсутствие обрезания.

## Результат DOCX render-проверки

Контрольный Word-файл выгружен из живого API:

```text
outputs/qurulush-reference-catalog.docx
```

Команда визуальной проверки:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /Users/maxai/.codex/plugins/cache/openai-primary-runtime/documents/26.909.11809/skills/documents/render_docx.py outputs/qurulush-reference-catalog.docx --output_dir outputs/qurulush-reference-render --emit_pdf
```

Результат: отрендерены 2 страницы PNG и PDF в `outputs/qurulush-reference-render/`. Визуальная проверка страниц показала читаемые таблицы, корректные переносы текста и отсутствие обрезания.

## Результат DOCX render-проверки юридического пакета

Контрольный Word-файл выгружен из живого API:

```text
outputs/qurulush-legal-verification-packet.docx
```

Команда визуальной проверки:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /Users/maxai/.codex/plugins/cache/openai-primary-runtime/documents/26.909.11809/skills/documents/render_docx.py outputs/qurulush-legal-verification-packet.docx --output_dir outputs/qurulush-legal-verification-render-final --emit_pdf
```

Результат: отрендерены 3 страницы PNG и PDF в `outputs/qurulush-legal-verification-render-final/`. Визуальная проверка страниц показала читаемые таблицы, корректные переносы текста и отсутствие обрезания.

## Ограничения текущей версии

- Фронтенд-кабинет может работать как локальная демо-страница через `localStorage`.
- Backend-слой уже добавлен: Python HTTP API, SQLite-состояние, демо-авторизация, роли, права, аудит.
- HTTP-интерфейс начинается с экрана входа; после успешного входа отображается имя пользователя и открывается кабинет по его роли.
- Backend поддерживает HTTPS-режим через `--tls-cert` и `--tls-key`; `/api/health` и `/api/readiness` отдают текущую схему.
- Публичный `/api/health` не раскрывает абсолютный путь к SQLite; подробные пути и readiness-гейты доступны директору через `/api/readiness`.
- При открытии через backend фронтенд подтягивает состояние из API и отправляет ключевые действия на сервер.
- `/api/state` фильтрует данные по роли, поэтому запрет доступа работает не только на уровне кнопок интерфейса.
- `/api/state` фильтрует данные по назначенным объектам; сервер также блокирует действия по чужому объекту.
- Поручения сотрудникам сохраняются в SQLite, фильтруются по объектам и требуют подтверждение при закрытии.
- Демо-пользователи хранятся в отдельной SQLite-таблице, пароли проверяются через PBKDF2-хеши и не находятся в общем payload состояния.
- Сессии хранятся в SQLite-таблице `sessions`; Bearer-токен не хранится в открытом виде, используется SHA-256 хеш, logout отзывает сессию.
- Повторные неверные попытки входа хранятся в SQLite-таблице `login_attempts`; после 5 ошибок вход временно блокируется с `429`, а успешный вход очищает счётчик.
- Добавлено серверное файловое хранилище: документы принимаются как base64, сохраняются в `uploads/`, получают безопасное имя, размер и защищённую API-ссылку на скачивание с ролевой проверкой `documents:read`.
- Загрузка документов ограничена разрешёнными расширениями: `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.jpg`, `.jpeg`, `.png`, `.zip`, `.txt`.
- Каждая загрузка документа получает запись версии с автором, датой, размером и SHA-256.
- Сервер отклоняет исполняемое содержимое с типовыми сигнатурами Windows, Linux и macOS, даже если расширение файла разрешено.
- Директор, главный инженер и юрист / разрешитель могут подписывать документы; при заданном `QH_EDS_SIGN_CMD` подпись подтверждается внешней командой до изменения статуса.
- Если задан `QH_AV_SCANNER` или `QH_AV_SCANNER_CMD`, сервер запускает внешний сканер перед записью файла; ненулевой код возврата блокирует загрузку.
- Если задан `QH_STORAGE_MODE=external` и `QH_STORAGE_SYNC_CMD`, сервер синхронизирует файл во внешнее хранилище до сохранения состояния документа и отмечает версию `storage_synced_at`.
- Приглашение сотрудника создаёт не только запись в команде, но и отдельную учётную запись в SQLite с PBKDF2-хешем временного пароля.
- Сотрудник может сменить пароль; старый пароль перестаёт работать, остальные активные сессии этого пользователя отзываются.
- Директор может создавать резервную копию SQLite; рядом сохраняется JSON-manifest с датой, автором, источником, размером файла и SHA-256.
- Директор может смотреть список резервных копий, видеть checksum, запускать dry-run проверку выбранного backup и восстанавливать состояние платформы из выбранного бэкапа; список/ready-паспорт проверяют checksum manifest, старые валидные manifest дополняются SHA-256, а перед restore выбранная копия сверяется с SHA-256, проверяется через `PRAGMA quick_check`, затем создаётся safety-бэкап текущего состояния.
- Readiness контролирует свежесть последней резервной копии через `backup_freshness`; порог задаётся `QH_BACKUP_MAX_AGE_HOURS`, по умолчанию 24 часа.
- При заданном `QH_BACKUP_INTERVAL_MINUTES`, `QH_BACKUP_INTERVAL_SECONDS` или `QH_BACKUP_SCHEDULE` сервер автоматически создаёт SQLite-копии по расписанию и останавливает scheduler через `server_close()`.
- При заданном `QH_BACKUP_REMOTE_CMD` сервер запускает внешнюю команду выгрузки после создания бэкапа; успешная передача отмечается в manifest полем `remote_synced_at`.
- Директор может открыть паспорт готовности запуска: локальные проверки проходят, а недостающие production-интеграции явно подсвечены.
- Директор может открыть журнал действий и выгрузить очищенный пакет аудита.
- Авторизованный пользователь может выгрузить справочник требований в JSON и Word/DOCX.
- Бухгалтер подтверждает оплату с номером платежа, квитанцией, датой, автором и записью в истории.
- Если задан `QH_PAYMENT_GATEWAY_CMD`, сервер подтверждает оплату через внешний шлюз до сохранения статуса; отказ шлюза возвращает ошибку и не меняет начисление.
- Юрист / разрешитель может подать обжалование по неоплаченному штрафу или начислению; оплаченные начисления не принимаются к обжалованию.
- Старые оплаченные записи без номера платежа мягко получают legacy-метаданные при чтении состояния.
- Добавлена сессионная логика: токен имеет срок действия, хранится на сервере как хеш, `/api/auth/logout` инвалидирует текущую сессию.
- Добавлено обслуживание сессий: просроченные токены автоматически отзываются при инициализации, входе и проверке текущего пользователя; readiness показывает отдельный gate `session_maintenance`.
- Добавлен директорский контроль сессий: активные входы видны в разделе готовности, просроченные записи очищаются вручную, другие входы можно завершить без выхода текущего директора.
- Добавлен production-план: директор видит статус каждого боевого подключения, ответственного, нужные переменные/команды и следующий шаг до закрытия production-гейтов.
- Добавлены HTTP security headers для API и статических файлов; HSTS включается в HTTPS-режиме.
- Добавлен лимит размера JSON POST-запросов: по умолчанию 16 МБ, превышение возвращает `413`, настройка через `QH_MAX_JSON_BYTES`.
- Добавлен SQLite integrity-check: `GET /api/readiness` и preflight проверяют базу через `PRAGMA quick_check`, а повреждённый файл не проходит локальную готовность.
- Добавлен контроль версии схемы: SQLite хранит `schema_version` в `schema_meta`, а readiness/preflight проверяют соответствие ожидаемой версии.
- Добавлен контур обмена: директор импортирует входящий запрос от ДГАСК / министерства / регионального отдела / инспектора, а экспорт `qurulush-company-exchange-v1` отдаёт очищенный JSON-пакет без внутренних секретов и служебных путей.
- Добавлен production-hook sacc2 / ДГАСК: директор отправляет очищенный пакет через `QH_SACC2_SYNC_CMD`, API-ключ остаётся в окружении и не записывается в payload.
- Добавлен публичный контроль sacc2: директор проверяет `sacc2.avn.kg`/fallback без паролей, выгружает Word-статус и одним кликом фиксирует результат в request-pack/evidence по gate `sacc2_api`.
- Добавлено назначение шагов запуска прямо из отчета `Что осталось`: ответственный, дедлайн, статус и доказательство сохраняются через evidence-регистр и сразу отражаются в UI.
- Добавлен короткий отчет ближайших действий: `/api/production/top-actions`, Word-выгрузка и файлы `production-top-actions.json` / `qurulush-production-top-actions.docx` внутри launch bundle.
- Добавлены production-alerts: `/api/production/alerts`, `/api/production/alerts/generate`, UI-кнопки `Alerts запуска` и `Сформировать в уведомления`, файл `production-alerts.json` внутри launch bundle.
- Добавлен dashboard-блок `Боевой запуск`: директор видит готовность, alerts, остаток шагов и назначает первые production-действия сразу после входа.
- Добавлен strict production-start guard: при `QH_REQUIRE_PRODUCTION=1` или `--require-production` сервер не стартует с незакрытыми production-гейтами.
- Добавлен production preflight: `--preflight` печатает readiness-паспорт до старта сервера, а `--preflight --require-production` завершает проверку кодом `2`, если production-гейты ещё не закрыты.
- Добавлен JSON preflight: `--preflight-json` печатает тот же readiness-паспорт в JSON для CI, systemd-обвязки и мониторинга.
- Production preflight теперь проверяет доступность executable для всех внешних hook-команд и не пропускает несуществующие пути как готовую интеграцию.
- Production preflight теперь блокирует явные placeholder-значения и короткие API-ключи в production-переменных.
- Подготовлен production operations kit: `ops/README_PRODUCTION.md`, `ops/qurulush-hub.service.example`, `ops/nginx-qurulush-hub.conf.example`, `ops/production_smoke_check.py`.
- Подготовлен release package builder: `ops/build_release_package.py` собирает чистый zip с `RELEASE_MANIFEST.json` и не включает runtime-данные.
- Подготовлен release acceptance-check: `ops/release_acceptance_check.py` сверяет manifest SHA-256, отклоняет подмененные файлы и проверяет распакованный zip через compile, локальный preflight и deployment audit.
- Подготовлен deployment audit: `ops/deployment_audit.py` проверяет production-файлы, а при переданном env-файле ловит placeholder-значения, отсутствие строгих production-флагов и права доступа группы/остальных.
- Добавлен production-гейт `hook_json_contracts`: без `QH_REQUIRE_HOOK_JSON=1` платформа не считается production-ready, а внешние hook-команды в строгом режиме должны вернуть машинно-проверяемый JSON.
- Добавлены hook contract templates для sacc2, ЭЦП, платежей, storage и remote backup; они включаются в release как образцы, но `deployment_audit.py` запрещает использовать их напрямую в production env.
- Добавлен renderer deployment-файлов: `ops/render_deployment_files.py` выпускает готовые `qurulush-hub.service`, `nginx-qurulush-hub.conf`, `go-no-go-command.sh` и summary под реальный домен.
- Реальная интеграция с ДГАСК / sacc2, production-доменом, доверенным сертификатом и фактическими командами провайдеров для ЭЦП, платежей, AV, storage и удалённых бэкапов требует настройки на сервере.
- Добавлен отчет боевых доступов: `/api/production/account-cutover`, `/api/production/account-cutover.docx`, UI-кнопка `Боевые доступы`, проверка покрытия ролей и файл `production-account-cutover.json` / `qurulush-production-account-cutover.docx` внутри launch bundle.

## Обновление 2026-09-14

- Backend suite: 128 tests OK.
- Browser smoke: OK, включая `calendar endpoint`, `chat endpoint`, `chat post endpoint`, `calendar UI render`, `chat AI UI action`, `acceptance evidence endpoint`, `completion audit endpoint`, `completion audit UI action`, `production account cutover endpoint`, `production account cutover UI action` и `production account cutover docx UI action`.
- Responsive smoke: OK, включая `calendar responsive render`, `chat AI responsive action`, `acceptance evidence responsive render`, `completion audit responsive render` и `account cutover responsive render` на mobile/tablet/desktop.
- Accessibility smoke: OK.
- Production smoke по `http://127.0.0.1:8782/`: OK, новый статус `calendar open=12`, `internal chat AI=ok`, `acceptance evidence available=True ok=True`; `production account cutover real=0 demo=6`.
- Release: `dist/qurulush-hub-company-platform-current.zip` обновлен, acceptance-check OK, manifest `file_count=35`.
- Go/no-go локального этапа: OK, `failed_stages=[]`. Production остается не готовым, потому что реальные доступы, sacc2, домен/HTTPS, внешние hooks, storage/AV/backup и юридическая сверка еще не закрыты.
- Completion audit: OK для локальной передачи, `local_handoff_ready=true`, `overall_status=local_ready_external_blockers`, `production_ready=false`.

## Вывод

Кабинет строительной компании готов как функциональная локальная платформа для проверки бизнес-процессов, интерфейса, ролей доступа и пользовательских сценариев. Для промышленной эксплуатации нужно заменить демо-авторизацию на корпоративную, выпустить доверенный сертификат для домена, получить официальный доступ ДГАСК / sacc2 и настроить реальные provider-команды для sacc2, ЭЦП, платежей, AV, storage и бэкапов.
