# Запуск рабочей версии платформы

## Локальный backend

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 company_platform_server.py --port 8780
```

После запуска открыть:

```text
http://127.0.0.1:8780/
```

Основной кабинет компании будет доступен по адресу:

```text
http://127.0.0.1:8780/04_Строительная_компания.html
```

В HTTP-режиме кабинет подключается к API и сохраняет действия в SQLite.
При открытии через HTTP сначала отображается экран входа по email и паролю. После входа Bearer-токен хранится в `sessionStorage`, в шапке показывается текущий пользователь, а `Выйти` отзывает серверную сессию.

## HTTPS-режим

Если есть сертификат и ключ, backend можно запустить в TLS-режиме:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 company_platform_server.py --port 8780 --tls-cert /path/to/cert.pem --tls-key /path/to/key.pem
```

После запуска открыть:

```text
https://127.0.0.1:8780/
```

Для production нужен доменный сертификат от доверенного центра или корпоративного CA.

`GET /api/health` возвращает безопасный публичный статус: `scheme`, `storage=sqlite`, `db_ready` и `time`. Абсолютный путь к SQLite не раскрывается; подробная диагностика доступна директору через `GET /api/readiness`.

Backend отдает базовые security headers для API и HTML: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy`; в HTTPS-режиме дополнительно включается `Strict-Transport-Security`.

JSON POST-запросы ограничены по размеру до 16 МБ по умолчанию. Этого достаточно для base64-загрузки документа до 10 МБ, но защищает сервер от чрезмерных payload. При необходимости лимит можно изменить через `QH_MAX_JSON_BYTES`; превышение возвращает `413`.

## Демо-пользователи

Для локальной проверки задайте временный demo-пароль через переменную окружения `QH_DEMO_PASSWORD`. Не публикуйте этот пароль в GitHub, чатах и документах для отделов.

| Роль | Email |
| --- | --- |
| Генеральный директор | `director@company.kg` |
| Главный инженер | `engineer@company.kg` |
| Прораб | `foreman@company.kg` |
| Бригадир | `brigadier@company.kg` |
| Бухгалтер | `accountant@company.kg` |
| Юрист / разрешитель | `lawyer@company.kg` |

## Production bootstrap

Для рабочего запуска можно создать первого боевого администратора через переменные окружения:

```bash
export QH_BOOTSTRAP_ADMIN_EMAIL="owner@builder.kg"
export QH_BOOTSTRAP_ADMIN_PASSWORD="StrongBootstrap2026!"
export QH_BOOTSTRAP_ADMIN_NAME="ФИО директора"
export QH_DISABLE_DEMO_USERS="1"
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 company_platform_server.py --port 8780
```

`QH_DISABLE_DEMO_USERS=1` отключает seed-аккаунты `director@company.kg`, `engineer@company.kg` и остальные демо-логины. Для безопасности этот режим требует одновременно задать `QH_BOOTSTRAP_ADMIN_EMAIL` и `QH_BOOTSTRAP_ADMIN_PASSWORD`; пароль bootstrap-админа должен быть не короче 12 символов.

## Защита боевого запуска

Чтобы сервер не стартовал как production при неполной конфигурации, включите строгий режим:

```bash
export QH_REQUIRE_PRODUCTION="1"
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 company_platform_server.py --port 8780 --tls-cert /path/fullchain.pem --tls-key /path/privkey.pem --require-production
```

В этом режиме сервер сначала строит `GET /api/readiness`-паспорт и отказывается запускаться, если любой обязательный production-гейт не `pass`: HTTPS, corporate/bootstrap-доступ, sacc2, ЭЦП, платежи, внешнее хранилище документов, AV, расписание и удалённое хранение бэкапов, юридически сверенный справочник.

Перед запуском на сервере можно выполнить preflight без занятия HTTP-порта:

```bash
set -a
source .env.production
set +a
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 company_platform_server.py \
  --preflight \
  --require-production \
  --db /var/lib/qurulush-hub/company.sqlite3 \
  --uploads /var/lib/qurulush-hub/uploads \
  --backups /var/lib/qurulush-hub/backups \
  --tls-cert /etc/letsencrypt/live/company.example/fullchain.pem \
  --tls-key /etc/letsencrypt/live/company.example/privkey.pem
```

`--preflight` выводит текстовый отчет: `local_ready`, `production_ready`, счетчики записей, список проверок и `production_blockers`. Если вместе с ним указан `--require-production`, команда возвращает код `2`, пока есть незакрытые production-гейты.

Для CI, systemd-обвязки или операторского мониторинга можно вывести тот же паспорт в JSON:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 company_platform_server.py \
  --preflight-json \
  --db /var/lib/qurulush-hub/company.sqlite3 \
  --uploads /var/lib/qurulush-hub/uploads \
  --backups /var/lib/qurulush-hub/backups
```

## Следующий этап: мобильный field-контур и платежи КР

В разделе `Готовность запуска` есть кнопка `Мобайл/платежи`. Она открывает roadmap, который заранее фиксирует будущий мобильный контур для прораба/бригадира и платежную оркестрацию Кыргызстана.

Мобильная версия должна подключаться к тем же ролям и объектам, использовать `/api/tasks/{id}/update`, `/api/documents/{id}/upload`, `/api/inspections/{index}/prepare`, `/api/chat` и `/api/calendar`, а для фотофиксации замечаний следующим этапом нужен multipart upload, AV scanner, production storage, thumbnails, offline queue и audit.

Платежи по госпошлинам, штрафам и начислениям должны идти через provider registry, выбранный банк/агрегатор, QR/deeplink или эквайринг. Полный список провайдеров перед production сверяется по актуальным реестрам НБКР и договорам платежной организации. Платформа не должна списывать деньги без явного подтверждения бухгалтера или генерального директора; статус `Оплачено` ставится только после callback/reconciliation или ручной бухгалтерской сверки.

Для всех production hook-команд (`QH_SACC2_SYNC_CMD`, `QH_EDS_SIGN_CMD`, `QH_PAYMENT_GATEWAY_CMD`, `QH_STORAGE_SYNC_CMD`, `QH_AV_SCANNER`, `QH_BACKUP_REMOTE_CMD`) preflight проверяет первый executable: абсолютный путь должен существовать и быть исполняемым, а команда без `/` должна находиться в `PATH`.

Preflight также блокирует явные заглушки в production-env: `CHANGE_ME`, `example.test`, `provider.example`, `YYYY-MM-DD`, `secret`, `test-eds` и слишком короткие API-ключи. Шаблон `.env.production.example` специально содержит такие заглушки, чтобы его нельзя было случайно принять за боевую конфигурацию.

Шаблон переменных окружения лежит в `.env.production.example`; секреты и реальные ключи нужно хранить только на сервере, вне чата и публичных репозиториев.

## Production runbook

Для переноса на VPS подготовлен отдельный операционный пакет:

- `ops/README_PRODUCTION.md` - пошаговый runbook запуска и отката.
- `ops/qurulush-hub.service.example` - systemd unit с `ExecStartPre` preflight.
- `ops/nginx-qurulush-hub.conf.example` - nginx reverse proxy для публичного HTTPS-домена.
- `ops/production_smoke_check.py` - smoke-check уже развернутой платформы по URL: health, login, readiness gates, директорский контроль сессий, публичный статус sacc2, фиксация sacc2 в request-pack/evidence и dry-run проверка последнего backup.
- `ops/backup_restore_drill.py` - изолированная тренировка восстановления последнего SQLite backup во временную базу.
- `ops/go_no_go_check.py` - единая приемка release zip, живой ссылки и backup restore drill.
- `ops/completion_audit.py` - итоговый machine-readable аудит: что доказано готовым, где `failed_stages=[]`, и какие production-гейты остаются внешними blockers.
- `ops/build_release_package.py` - чистая сборка release-архива без SQLite, uploads, backups, outputs и скриншотов.
- `ops/release_acceptance_check.py` - распаковка release zip, Python compile и preflight из распакованной копии.

После настройки сервера минимальная проверка выглядит так:

```bash
python3 ops/build_release_package.py --output-dir dist
python3 ops/release_acceptance_check.py dist/qurulush-hub-company-platform-YYYYMMDD_HHMMSS.zip

python3 /opt/qurulush-hub/ops/production_smoke_check.py \
  --base-url https://company.example/ \
  --email owner@builder.kg \
  --password 'REAL_PASSWORD' \
  --require-production

python3 /opt/qurulush-hub/ops/backup_restore_drill.py \
  --backups /var/lib/qurulush-hub/backups

python3 /opt/qurulush-hub/ops/go_no_go_check.py \
  --release /opt/qurulush-hub/dist/qurulush-hub-company-platform-current.zip \
  --base-url https://company.example/ \
  --email owner@builder.kg \
  --password 'REAL_PASSWORD' \
  --backups /var/lib/qurulush-hub/backups \
  --require-production
```

## Интеграция sacc2 / ДГАСК

Для production-синхронизации с официальным контуром задайте URL, ключ и команду отправки:

```bash
export QH_SACC2_API_URL="https://sacc2.avn.kg/api"
export QH_SACC2_API_KEY="полученный-официальный-ключ"
export QH_SACC2_SYNC_CMD="/opt/qurulush/bin/sync-sacc2 {payload}"
```

`POST /api/sacc2/sync` доступен только генеральному директору. Сервер формирует очищенный JSON-пакет `qurulush-company-exchange-v1` по объектам, запросам, документам, проверкам, поручениям, начислениям и аудиту. `QH_SACC2_SYNC_CMD` может использовать маркеры `{payload}` и `{api_url}`; если `{payload}` не указан, сервер добавит путь к JSON последним аргументом. API-ключ не записывается в payload, состояние, аудит или экспорт; внешняя команда должна читать его из окружения.

## Проверка загружаемых файлов

Для production можно подключить внешний антивирусный сканер:

```bash
export QH_AV_SCANNER="/usr/local/bin/clamscan --no-summary"
```

Команда получает временный файл последним аргументом. Если нужен свой порядок аргументов, используйте маркер `{file}`, например `QH_AV_SCANNER="/opt/scanner --scan {file}"`. Код возврата `0` разрешает загрузку; любой другой код отклоняет файл до сохранения в `uploads/`. При настроенной команде `GET /api/readiness` отмечает `av_scan` как пройденный.

## Внешнее хранилище документов

Для production-синхронизации загруженных документов задайте внешний режим и команду:

```bash
export QH_STORAGE_MODE="external"
export QH_STORAGE_URL="s3://company-documents/qurulush-hub"
export QH_STORAGE_SYNC_CMD="aws s3 cp {file} {storage_url}/{doc_id}/"
```

`QH_STORAGE_SYNC_CMD` запускается после локального сохранения загруженного файла. Команда может использовать маркеры `{file}`, `{doc_id}`, `{filename}`, `{storage_url}`; если `{file}` не указан, сервер добавит путь к файлу последним аргументом. При успешной синхронизации документ и его версия получают `storage_synced_at`; при ошибке внешней команды загрузка отклоняется, а локальный файл удаляется.

## Платежный шлюз

Для production-подтверждения госпошлин и штрафов задайте команду шлюза:

```bash
export QH_PAYMENT_GATEWAY_URL="https://payments.provider.example/api"
export QH_PAYMENT_GATEWAY_CMD="/opt/qurulush/bin/confirm-payment {payload}"
```

Сервер формирует временный JSON-пакет с `payment_id`, объектом, суммой, номером платежа, квитанцией и бухгалтером. `QH_PAYMENT_GATEWAY_CMD` может использовать маркеры `{payload}`, `{payment_id}`, `{payment_no}`, `{gateway_url}`; если `{payload}` не указан, сервер добавит путь к JSON последним аргументом. Код возврата `0` подтверждает оплату; ненулевой код блокирует оплату до записи в SQLite.

## ЭЦП / электронное подписание

Для production-подписания документов задайте провайдера, URL и команду подписи:

```bash
export QH_EDS_PROVIDER="provider-name"
export QH_EDS_API_URL="https://eds.provider.example/sign"
export QH_EDS_SIGN_CMD="/opt/qurulush/bin/sign-document {payload}"
```

Сервер формирует временный JSON-пакет с `document_id`, объектом, именем файла, SHA-256 файла, подписантом и комментарием. `QH_EDS_SIGN_CMD` может использовать маркеры `{payload}`, `{document_id}`, `{eds_api_url}`; если `{payload}` не указан, сервер добавит путь к JSON последним аргументом. Код возврата `0` подтверждает подпись; ненулевой код блокирует изменение статуса документа.

## Автоматические бэкапы

Для регулярных SQLite-копий задайте интервал:

```bash
export QH_BACKUP_INTERVAL_MINUTES="60"
export QH_BACKUP_MAX_AGE_HOURS="24"
export QH_BACKUP_ON_START="1"
export QH_BACKUP_REMOTE_URL="s3://company-secure-backups/qurulush-hub"
export QH_BACKUP_REMOTE_CMD="aws s3 cp {backup} {remote_url}/"
```

`QH_BACKUP_INTERVAL_MINUTES` создаёт локальные копии в папке `backups/`; `QH_BACKUP_SCHEDULE` также понимает значения `hourly`, `daily`, `30m`, `6h`, `1d`. `QH_BACKUP_MAX_AGE_HOURS` задаёт максимальный возраст последнего бэкапа для readiness-проверки свежести, по умолчанию 24 часа. `QH_BACKUP_ON_START=1` создаёт первую копию сразу при запуске сервера. `QH_BACKUP_REMOTE_CMD` запускается после создания локального `.sqlite3` и `.json` manifest; если команда не использует маркеры `{backup}` или `{manifest}`, сервер добавит оба файла последними аргументами. Для адреса внешнего хранилища можно использовать `{remote_url}` из `QH_BACKUP_REMOTE_URL`.

Перед реальным восстановлением директор может выполнить `POST /api/backups/restore-drill`: сервер проверит manifest/SHA-256, поднимет резервную копию во временную SQLite-базу, сверит счетчики и удалит временную базу, не меняя рабочее состояние платформы.

## API

- `GET /api/health`
- `GET /api/readiness`
- `GET /api/external/sacc2-status`
- `GET /api/external/sacc2-status.docx`
- `POST /api/external/sacc2-status/attach`
- `GET /api/acceptance/passport`
- `GET /api/acceptance/passport.docx`
- `GET /api/production/plan`
- `GET /api/production/plan.docx`
- `GET /api/production/env.example`
- `GET /api/production/checklist`
- `GET /api/production/checklist.docx`
- `GET /api/production/top-actions`
- `GET /api/production/top-actions.docx`
- `GET /api/production/alerts`
- `POST /api/production/alerts/generate`
- `GET /api/sessions`
- `POST /api/sessions/revoke-expired`
- `POST /api/sessions/revoke-others`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/auth/change-password`
- `GET /api/state`
- `POST /api/state/reset`
- `GET /api/backups`
- `POST /api/backups`
- `POST /api/backups/verify`
- `POST /api/backups/restore-drill`
- `POST /api/backups/restore`
- `GET /api/audit/export`
- `GET /api/reference/export`
- `GET /api/reference/export.docx`
- `GET /api/exchange/export`
- `POST /api/sacc2/sync`
- `POST /api/exchange/incoming`
- `POST /api/objects`
- `POST /api/tasks`
- `POST /api/tasks/{id}/update`
- `POST /api/requests`
- `POST /api/requests/{id}/reply`
- `POST /api/documents/{id}/upload`
- `POST /api/documents/{id}/sign`
- `GET /api/documents/{id}/file`
- `POST /api/money/{id}/pay`
- `POST /api/money/{id}/appeal`
- `POST /api/inspections/{index}/prepare`
- `POST /api/team`
- `POST /api/notifications/{index}/read`
- `POST /api/notifications/read-all`

## Проверка

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest -v test_company_platform_backend.py test_ops_backup_restore_drill.py test_ops_go_no_go_check.py test_ops_release_package.py test_ops_production_smoke.py
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_smoke.mjs
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_responsive_smoke.mjs
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_accessibility_smoke.mjs
```

Backend-тесты проверяют авторизацию, production bootstrap-админа, отключение демо-учеток, строгий production-start guard, текстовый и JSON preflight, защиту от перебора пароля, HTTPS health endpoint, readiness endpoint, SQLite integrity-check через `PRAGMA quick_check`, версию схемы SQLite через `schema_meta`, SQLite-сессии, директорский просмотр активных сессий без token hash, отзыв просроченных сессий, завершение других сессий без выхода текущего директора, безопасную уборку старых smoke-сессий только на localhost, смену пароля, роли, объектные назначения, права доступа, серверную фильтрацию данных по роли и объекту, внутренний чат с локальным ИИ и календарь сроков с ролевым ограничением, SQLite-сохранение, аудит, экспорт аудита, справочник требований, Word/DOCX-экспорт справочника, Word/DOCX-экспорт production-плана, отчет боевых доступов и Word/DOCX-экспорт account cutover без секретов, безопасную публичную проверку статуса sacc2, Word-отчет без паролей и фиксацию статуса sacc2 в request-pack/evidence с блокировкой private URL, быстрые назначения ответственного/дедлайна из отчета `Что осталось`, короткий JSON/Word-отчет ближайших действий, production-alerts по срочным шагам запуска и первым шагам без дедлайна с дедупликацией уведомлений, безопасный `.env` production-шаблон, launch checklist боевого запуска и Word/DOCX-экспорт checklist, поручения сотрудникам, бизнес-действия, создание объекта, команду, уведомления, создание логина для приглашённого сотрудника, оплату с номером платежа, production-hook платёжного шлюза, обжалование штрафа, версии документов, SHA-256 файлов, ЭЦП-подписание документов, отказ маскированных исполняемых файлов, подключаемую антивирусную проверку до сохранения загрузки, внешнюю синхронизацию документов, импорт внешнего запроса, очищенный экспорт пакета обмена, production-hook синхронизации sacc2/ДГАСК, список бэкапов, restore-drill во временную базу, восстановление состояния из бэкапа, автоматическое создание SQLite-копий по расписанию и remote-hook выгрузки бэкапа. Production smoke unit-тесты проверяют поимённый контроль локальных gates, директорский контроль сессий, account cutover, public status sacc2, Word-отчет sacc2, фиксацию sacc2 в request-pack/evidence, внутренний чат ИИ, календарь сроков, короткий top-actions отчет, production-alerts, launch checklist и dry-run проверку последнего backup перед приемкой VPS. Browser smoke-test проверяет интерфейс, экран входа в HTTP-режиме, сессию пользователя, dashboard-блок `Боевой запуск`, календарь, внутренний чат с ответом ИИ, быстрое назначение production-шагов с dashboard, ограничения ролей, справочник требований, карту взаимодействия с Минстроем/ДГАСК, матрицу доступов, отчет `Что осталось`, боевые доступы, назначение production-шагов из отчета, ближайшие действия, production-alerts и генерацию уведомлений, статус sacc2, фиксацию статуса sacc2 в запуске, Word-экспорты, журнал аудита, экран готовности, панель активных сессий, production-план, кнопку Word-плана, кнопку `.env`, чеклист запуска и Word-кнопку checklist, назначение и закрытие поручений с подтверждением, ответы, загрузку и подписание документа, оплату с номером, обжалование начисления, создание обращения, импорт запроса ДГАСК, форму назначения объектов сотруднику, историю версий документа, панель бэкапов, кнопку restore-drill и сохранение в браузере. Responsive smoke-test проверяет телефон, планшет и desktop: вход, навигацию, главный блок боевого запуска, календарь, внутренний чат ИИ, ключевые разделы, отчет `Что осталось`, боевые доступы, production-alerts, статус sacc2, карту взаимодействия, матрицу доступов, отсутствие горизонтального overflow страницы и консольных ошибок. Accessibility smoke-test проверяет явные labels, keyboard login, nav landmark, `aria-current`, live-region ошибок и toast-уведомлений.

`GET /api/readiness` доступен генеральному директору и возвращает паспорт готовности запуска: локальное состояние SQLite, `PRAGMA quick_check`, версию схемы `schema_meta`, таблицы, хранение паролей, обслуживание сессий, качество manifest резервных копий, свежесть последней резервной копии, каталоги `uploads/` и `backups/`, наличие резервных копий, режим HTTP/HTTPS, демо-аккаунты и недостающие production-интеграции. В текущей локальной версии `local_ready=true`, а `production_ready=false`, пока не подключены официальный sacc2/API URL, ключ и sync-команда, production ЭЦП-команда, платёжный gateway-hook, внешний storage-hook документов, AV-сканер и команда выгрузки бэкапов во внешнее хранилище.

`GET /api/sessions` доступен генеральному директору и показывает активные входы: пользователь, роль, время создания, оставшееся время и признак текущей сессии. Ответ не раскрывает token hash. `POST /api/sessions/revoke-expired` очищает просроченные активные записи, а `POST /api/sessions/revoke-others` завершает все остальные открытые входы, сохраняя текущую сессию директора.

`GET /api/production/plan` доступен генеральному директору и возвращает план подключения боевого контура: домен/HTTPS, боевые учетные записи, sacc2/ДГАСК, ЭЦП, платежи, внешнее хранилище документов, AV-сканер, расписание и удаленное хранение бэкапов, юридическая сверка справочника. Для каждого пункта указаны статус readiness-гейта, ответственный, нужные переменные/команды и следующий шаг.

`GET /api/production/plan.docx` доступен генеральному директору и выгружает Word-файл `qurulush-production-plan.docx` с тем же планом подключения. Контрольный файл из живого API сохранён как `outputs/qurulush-production-plan.docx` и визуально проверен через `render_docx.py`; рендеры лежат в `outputs/qurulush-production-plan-render/`.

`POST /api/production/cutover/validate` проверяет полноту cutover-конфигурации без возврата секретов и shell-команд. Ответ отдельно показывает `configuration_ready` и `ready_for_final_acceptance`: даже при 100% заполненных gates финальная приемка остается неготовой, пока не закрыты предупреждения вроде live DNS/TLS/headers probe и проверки текущей базы после production restart.

`GET /api/production/qa-evidence` доступен генеральному директору и возвращает QA-пакет текущей проверки: рабочую ссылку, live evidence, команды regression/browser/responsive/accessibility/live-smoke/release/go-no-go и список артефактов. `GET /api/production/qa-evidence.docx` выгружает тот же пакет в Word без паролей, API-ключей и token hash.

`GET /api/production/status-board` доступен генеральному директору и возвращает единый статус запуска: рабочую ссылку, процент готовности, количество оставшихся шагов, текущий следующий шаг, ближайшие действия, полный список открытых blockers, QA-команды и артефакты. `GET /api/production/status-board.docx` выгружает этот статус в Word для отправки директору, DevOps и ответственным исполнителям.

`GET /api/acceptance/evidence` доступен генеральному директору и возвращает последний очищенный acceptance evidence из `outputs/acceptance-evidence-current.json`: `ok`, `failed_stages`, этапы go/no-go, команды без секретов и артефакты. `GET /api/acceptance/evidence.json` скачивает тот же безопасный JSON для архива приемки.

Для сохранения машинно-читаемого доказательства приемки используйте:

```bash
python3 ops/collect_acceptance_evidence.py \
  --release dist/qurulush-hub-company-platform-current.zip \
  --base-url https://YOUR-DOMAIN/ \
  --email OWNER_EMAIL \
  --password 'REAL_PASSWORD' \
  --backups /var/lib/qurulush-hub/backups \
  --require-production
```

Скрипт пишет `outputs/acceptance-evidence-current.json` и timestamp-копию. Пароль в JSON заменяется на `REDACTED`.

После сборки evidence можно получить единый completion audit:

```bash
python3 ops/completion_audit.py \
  --release dist/qurulush-hub-company-platform-current.zip \
  --evidence outputs/acceptance-evidence-current.json \
  --output outputs/completion-audit-current.json
```

Файл `outputs/completion-audit-current.json` показывает `local_handoff_ready`, `production_ready`, `overall_status`, доказанные стадии и внешние blockers.

`GET /api/acceptance/completion-audit` показывает тот же итоговый аудит в интерфейсе директора. `GET /api/acceptance/completion-audit.json` скачивает очищенный JSON для передачи директору, DevOps или команде запуска.

`GET /api/audit/export` доступен генеральному директору и выгружает очищенный JSON-пакет `qurulush-audit-export-v1`: дата выгрузки, автор выгрузки, данные компании и журнал действий. Экспорт не включает пользователей, пароли, сессии и внутренние имена сохранённых файлов.

`GET /api/reference/export` доступен авторизованному пользователю и выгружает рабочий JSON-справочник `qurulush-reference-catalog-v1`: разрешительные документы, госпошлины и начисления, штрафы и нарушения, запросы и уведомления, проверки, роли и доступы. Справочник помечен как рабочая модель платформы и не является официальной правовой базой до сверки действующих НПА, тарифов, форм и регламентов ДГАСК / Минстроя КР.

`GET /api/reference/export.docx` доступен авторизованному пользователю и выгружает Word-файл `qurulush-reference-catalog.docx` со справочником требований. Контрольный файл из живого API сохранён как `outputs/qurulush-reference-catalog.docx` и визуально проверен через `render_docx.py`; рендеры лежат в `outputs/qurulush-reference-render/`.

`GET /api/legal/verification-packet` доступен генеральному директору и юристу / разрешителю. Пакет содержит категории справочника, поля `needs_review`, реестр официальных источников-кандидатов, привязку источников к разрешительным документам, госпошлинам, штрафам, запросам, уведомлениям и проверкам, а также пометку для утративших силу документов `expired_do_not_use_as_current_law`.

`GET /api/legal/verification-packet.docx` выгружает Word-файл юридической сверки с отдельной таблицей официальных источников и колонкой источников-кандидатов по каждому пункту справочника. Этот файл предназначен для юриста: до подтверждения НПА, статей, тарифов, штрафов, форм и сроков production gate справочника остается не закрытым.

Также проверяется, что демо-пароль не хранится в общем состоянии приложения: пользователи вынесены в SQLite-таблицу `users`, а пароль хранится как PBKDF2-хеш с солью. Сессии сохраняются в SQLite-таблице `sessions`; сам Bearer-токен в базе не хранится, только SHA-256 хеш.

Повторные неверные попытки входа записываются в SQLite-таблицу `login_attempts`. После 5 ошибок в пределах 15 минут вход временно блокируется на 10 минут и возвращает `429`; успешный вход очищает счётчик.

Загруженные через HTTP-режим документы сохраняются в папку `uploads/`, а скачивание идёт через защищённый маршрут `GET /api/documents/{id}/file` с Bearer-токеном и правом `documents:read`. Максимальный размер одного файла: 10 МБ. Разрешённые расширения: `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.jpg`, `.jpeg`, `.png`, `.zip`, `.txt`.

Каждая загрузка документа получает запись версии с автором, датой, размером и SHA-256 контрольной суммой. Сервер отклоняет исполняемое содержимое с типовыми сигнатурами Windows, Linux и macOS, даже если файл переименован в разрешённое расширение. Если задан `QH_AV_SCANNER` или `QH_AV_SCANNER_CMD`, файл дополнительно проходит внешний сканер до записи на диск. Если задан `QH_STORAGE_SYNC_CMD`, файл синхронизируется во внешнее хранилище перед сохранением состояния документа.

Документ подписывается через `POST /api/documents/{id}/sign`. Доступ есть у директора, главного инженера и юриста / разрешителя. Если задан `QH_EDS_SIGN_CMD`, сервер сначала подтверждает подпись через внешний ЭЦП-контур; при ошибке статус документа не меняется. В локальном demo-режиме без команды подпись отмечается как `signed-local`.

Приглашение сотрудника через роль `Генеральный директор` создаёт запись в команде и отдельный login в SQLite-таблице `users`; временный пароль хранится только как PBKDF2-хеш.

Для прораба и бригадира применяется объектный доступ: сервер фильтрует объекты, запросы, документы, проверки и начисления по назначенным объектам, а также блокирует действия по чужому объекту. Приглашая сотрудника, директор может выбрать назначенные объекты в форме.

Контур поручений:

- `POST /api/tasks` создаёт внутреннее поручение по объекту, источнику, сроку и приоритету. Доступно директору, главному инженеру и прорабу с учетом объектного доступа.
- `POST /api/tasks/{id}/update` меняет статус поручения на `new`, `in_progress`, `done` или `blocked`. Для закрытия `done` требуется подтверждение/основание; действие пишется в историю, аудит и уведомления.
- `/api/state` фильтрует поручения по роли и назначенным объектам: бригадир видит только свои объектные задачи, бухгалтер и юрист не получают рабочие поручения.

Сотрудник может сменить пароль через `POST /api/auth/change-password`; после смены старый пароль перестаёт работать, а остальные активные сессии пользователя отзываются.

Финансовый контур: бухгалтер подтверждает оплату только с номером платежа и квитанцией; сервер сохраняет `payment_no`, `receipt`, `paid_at`, `paid_by` и историю. Если задан `QH_PAYMENT_GATEWAY_CMD`, сервер сначала отправляет JSON-пакет во внешний шлюз; при ошибке шлюза оплата не сохраняется. Юрист / разрешитель может подать обжалование по неоплаченному штрафу или начислению через `POST /api/money/{id}/appeal`; оплаченные начисления к обжалованию не принимаются.

Старые оплаченные записи без номера платежа мягко нормализуются при чтении состояния: система подставляет seed-метаданные или `LEGACY-{id}`, не требуя ручного сброса базы.

Резервная копия создаётся директором через `POST /api/backups`: сервер сохраняет `.sqlite3` и `.json` manifest с SHA-256 контрольной суммой в папку `backups/`. Если задан `QH_BACKUP_REMOTE_CMD`, сервер после локального сохранения запускает команду внешней выгрузки; при успехе manifest получает `remote_synced_at`. Список доступен через `GET /api/backups` и показывает checksum. `POST /api/backups/verify` выполняет dry-run проверку выбранной копии без изменения рабочей базы: сверяет SHA-256, запускает `PRAGMA quick_check` и проверяет наличие читаемого `app_state`. Восстановление состояния платформы выполняется через `POST /api/backups/restore` с именем файла; выбранная копия сначала проходит ту же проверку, повреждённый или подменённый `.sqlite3` отклоняется, затем сервер автоматически создаёт safety-бэкап текущего состояния и пишет событие в аудит. При заданном `QH_BACKUP_INTERVAL_MINUTES`, `QH_BACKUP_INTERVAL_SECONDS` или `QH_BACKUP_SCHEDULE` сервер запускает фоновый scheduler и создаёт SQLite-копии по интервалу. При остановке сервера поток scheduler завершается через `server_close()`.

Контур обмена для директора:

- `POST /api/sacc2/sync` отправляет очищенный пакет обмена в production-hook sacc2 / ДГАСК. Успешная синхронизация записывает `integrations.sacc2`, аудит и уведомление.
- `POST /api/exchange/incoming` принимает входящий запрос от `ДГАСК`, `Министерство`, `Региональный отдел` или `Инспектор`, валидирует объект, создаёт запись в очереди запросов, добавляет аудит и уведомление.
- `GET /api/exchange/export` отдаёт JSON-пакет `qurulush-company-exchange-v1` по объектам, запросам, документам, проверкам, поручениям, начислениям и аудиту. Экспорт не включает пользователей, пароли, сессии, внутренние имена сохранённых файлов и локальные защищённые URL документов.

Полная HTTP-проверка связки UI/API/SQLite:

```bash
/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node company_platform_server_smoke.mjs
```
