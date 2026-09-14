# Production runbook

## Цель

Этот пакет нужен, чтобы перенести платформу строительной компании из локальной проверки в управляемый серверный запуск.

## Файлы

- `.env.production.example` - шаблон production-переменных без реальных секретов.
- `ops/qurulush-hub.service.example` - пример systemd unit с обязательным preflight перед стартом.
- `ops/nginx-qurulush-hub.conf.example` - пример nginx reverse proxy для публичного HTTPS-домена.
- `ops/backup_restore_drill.py` - изолированная проверка восстановления последней SQLite-копии во временную базу.
- `ops/production_smoke_check.py` - проверка уже поднятой платформы по URL, включая readiness, активные сессии, production-план, account cutover, env-шаблон, launch checklist, Word-чеклист, backup dry-run и паспорт приемки.
- `ops/go_no_go_check.py` - единый go/no-go агрегатор release acceptance, deployment audit, live smoke-check и restore drill.
- `ops/completion_audit.py` - итоговый аудит готовности: подтверждает локальную передачу, проверяет current release/evidence и отдельно показывает внешние production blockers.
- `ops/deployment_audit.py` - проверка deployment-комплекта и закрытого production env-файла перед запуском.
- `ops/hook_contract_smoke.py` - dry-run проверка реальных hook-команд из env: каждая должна вернуть JSON-статус.
- `ops/hook_examples/` - шаблоны JSON-контрактов для sacc2, ЭЦП, платежей, storage, AV scanner и remote backup; использовать как основу для реальных приватных hooks.
- `ops/render_deployment_files.py` - генератор готовых `systemd`, `nginx` и `go-no-go` файлов под реальный домен.
- `ops/build_release_package.py` - сборка чистого zip-архива без runtime-данных.
- `ops/release_acceptance_check.py` - проверка zip-архива через распаковку, Python compile и локальный preflight.

## Сборка release-архива

Перед переносом на VPS собрать архив:

```bash
python3 ops/build_release_package.py --output-dir dist
python3 ops/release_acceptance_check.py dist/qurulush-hub-company-platform-YYYYMMDD_HHMMSS.zip
```

Скрипт включает backend, статический кабинет, `.env.production.example`, runbook, systemd/nginx шаблоны, smoke-check и документацию. Он исключает `company_platform.sqlite3`, `uploads/`, `backups/`, `outputs/`, скриншоты, кеши и `.pyc`. Внутрь архива добавляется `RELEASE_MANIFEST.json` с SHA-256 по каждому файлу.
Acceptance-check сверяет каждый файл с `RELEASE_MANIFEST.json`, отклоняет лишние файлы вне manifest, распаковывает архив во временную папку, компилирует серверные Python-файлы, запускает `--preflight` из распакованной копии и выполняет deployment audit комплекта.

## Подготовка сервера

1. Создать пользователя сервиса:

```bash
sudo useradd --system --home /opt/qurulush-hub --shell /usr/sbin/nologin qurulush
```

2. Скопировать release-архив:

```bash
sudo mkdir -p /opt/qurulush-hub /var/lib/qurulush-hub/uploads /var/lib/qurulush-hub/backups
sudo unzip qurulush-hub-company-platform-YYYYMMDD_HHMMSS.zip -d /opt/
sudo rsync -a /opt/qurulush-hub-company-platform/ /opt/qurulush-hub/
sudo chown -R qurulush:qurulush /opt/qurulush-hub /var/lib/qurulush-hub
```

3. Создать закрытый env-файл:

```bash
sudo install -m 600 -o root -g root .env.production.example /etc/qurulush-hub/company-platform.env
sudo nano /etc/qurulush-hub/company-platform.env
```

4. Заменить все заглушки на реальные значения:

- bootstrap admin email, name, strong password;
- официальный sacc2 / ДГАСК API URL, ключ и executable sync-команду;
- ЭЦП provider, URL и executable sign-команду;
- платежный gateway executable;
- внешнее хранилище документов;
- AV scanner executable;
- remote backup executable;
- `QH_REQUIRE_HOOK_JSON=1`, чтобы sacc2/ЭЦП/платежи/storage/AV scanner/remote backup возвращали машинно-проверяемый JSON со статусом;
- дату юридической сверки справочника требований.

5. Проверить закрытый env-файл до запуска:

```bash
python3 /opt/qurulush-hub/ops/deployment_audit.py \
  --root /opt/qurulush-hub \
  --env /etc/qurulush-hub/company-platform.env \
  --require-production-config
```

Команда должна вернуть `ok=true`. Если env-файл доступен группе/остальным пользователям, содержит `CHANGE_ME`, `company.example`, `provider.example`, `YYYY-MM-DD` или не включает `QH_REQUIRE_PRODUCTION=1` и `QH_REQUIRE_HOOK_JSON=1`, запуск нельзя принимать.

6. Сгенерировать готовые deployment-файлы под реальный домен:

```bash
python3 /opt/qurulush-hub/ops/render_deployment_files.py \
  --domain cabinet.builder.kg \
  --output-dir /opt/qurulush-hub/dist/deployment-files \
  --admin-email owner@builder.kg
```

Генератор создаст `qurulush-hub.service`, `nginx-qurulush-hub.conf`, `go-no-go-command.sh` и `DEPLOYMENT_SUMMARY.json` без `company.example`.

## Hook templates

Шаблоны в `ops/hook_examples/` показывают только формат обмена:

```bash
python3 ops/hook_examples/sacc2_sync_contract_example.py payload.json /tmp/qh-hook-test
python3 ops/hook_examples/eds_sign_contract_example.py payload.json /tmp/qh-hook-test
python3 ops/hook_examples/payment_confirm_contract_example.py payload.json /tmp/qh-hook-test
python3 ops/hook_examples/storage_sync_contract_example.py document.pdf /tmp/qh-storage-test
python3 ops/hook_examples/av_scan_contract_example.py document.pdf
python3 ops/hook_examples/backup_remote_contract_example.py backup.sqlite3 backup.json /tmp/qh-backup-test
```

В production нельзя указывать `ops/hook_examples/*` прямо в `.env`: `deployment_audit.py --require-production-config` отклонит такой env. Реальные hooks должны находиться, например, в `/opt/qurulush/bin/`, выполнять фактический вызов провайдера и печатать JSON только после подтверждения внешней операции.

После настройки реальных hooks выполнить контрактный smoke:

```bash
python3 /opt/qurulush-hub/ops/hook_contract_smoke.py \
  --env /etc/qurulush-hub/company-platform.env
```

Каждый реальный hook должен поддерживать safe dry-run payload и вернуть JSON-статус. Если хотя бы один hook возвращает пустой stdout, невалидный JSON или неподходящий статус, production-приемку не проходить.

## Preflight

Перед включением systemd выполнить:

```bash
set -a
source /etc/qurulush-hub/company-platform.env
set +a
sudo -u qurulush python3 /opt/qurulush-hub/company_platform_server.py \
  --preflight \
  --require-production \
  --db /var/lib/qurulush-hub/company.sqlite3 \
  --uploads /var/lib/qurulush-hub/uploads \
  --backups /var/lib/qurulush-hub/backups \
  --tls-cert /etc/letsencrypt/live/company.example/fullchain.pem \
  --tls-key /etc/letsencrypt/live/company.example/privkey.pem
```

Ожидаемый результат для боевого запуска:

```text
local_ready: yes
production_ready: yes
production_blockers: none
```

Если есть `production_blockers`, сервис не должен запускаться как production.

## Restore drill

Перед первым боевым вводом и после настройки расписания резервного копирования выполнить изолированную проверку восстановления:

```bash
python3 /opt/qurulush-hub/ops/backup_restore_drill.py \
  --backups /var/lib/qurulush-hub/backups
```

Скрипт берет последнюю `.sqlite3` копию, проверяет manifest/SHA-256, читает `app_state`, переносит состояние во временную SQLite, запускает `PRAGMA quick_check` и удаляет временную базу. Живая база сервиса не меняется.

## Go/no-go перед вводом

После запуска сервиса выполнить единую приемку:

```bash
python3 /opt/qurulush-hub/ops/go_no_go_check.py \
  --release /opt/qurulush-hub/dist/qurulush-hub-company-platform-current.zip \
  --deployment-root /opt/qurulush-hub \
  --env /etc/qurulush-hub/company-platform.env \
  --base-url https://company.example/ \
  --email owner@builder.kg \
  --password 'REAL_PASSWORD' \
  --backups /var/lib/qurulush-hub/backups \
  --require-production-config \
  --hook-contract-smoke \
  --require-production
```

Команда возвращает один JSON с `ok`, списком стадий и `failed_stages`. При `ok=false` запуск в промышленную эксплуатацию не принимать.

## Systemd

```bash
sudo cp /opt/qurulush-hub/dist/deployment-files/qurulush-hub.service /etc/systemd/system/qurulush-hub.service
sudo systemctl daemon-reload
sudo systemctl enable --now qurulush-hub
sudo systemctl status qurulush-hub
```

## Nginx

```bash
sudo cp /opt/qurulush-hub/dist/deployment-files/nginx-qurulush-hub.conf /etc/nginx/sites-available/qurulush-hub.conf
sudo ln -s /etc/nginx/sites-available/qurulush-hub.conf /etc/nginx/sites-enabled/qurulush-hub.conf
sudo nginx -t
sudo systemctl reload nginx
```

## Smoke-check после запуска

```bash
python3 /opt/qurulush-hub/ops/production_smoke_check.py \
  --base-url https://company.example/ \
  --email owner@builder.kg \
  --password 'REAL_PASSWORD' \
  --require-production
```

Успешный результат:

```json
{"ok": true, "checks": ["health ...", "login ...", "local gate sqlite_integrity=pass", "readiness ...", "sessions active=1", "production plan ready=True", "production env example=ok", "production launch checklist ready=True", "production launch checklist docx=ok", "backup verify ...=ok", "acceptance passport local=True", "acceptance passport production=True", "production_ready=true"]}
```

## Откат

1. Остановить сервис:

```bash
sudo systemctl stop qurulush-hub
```

2. Восстановить последний проверенный SQLite backup из `/var/lib/qurulush-hub/backups`.
3. Запустить preflight.
4. Запустить сервис снова:

```bash
sudo systemctl start qurulush-hub
```

## Важные правила

- Не хранить реальные API-ключи в репозитории, чате или публичных файлах.
- Не отключать `--require-production` на сервере.
- Не принимать `.env.production.example` как боевой env: он специально содержит заглушки.
- Не считать `configuration_ready=true` финальным запуском: перед приемкой нужен `ready_for_final_acceptance=true`, live DNS/TLS/headers probe и `go_no_go_check.py --require-production`.
- Перед передачей директору выгружать `QA пакет` / `qurulush-qa-evidence.docx`, чтобы отдельно зафиксировать рабочую ссылку, live evidence, команды проверок и актуальный release ZIP.
- Перед финальной встречей выгружать `Статус запуска` / `qurulush-production-status-board.docx`, чтобы в одном документе были рабочая ссылка, итог тестов, количество оставшихся blockers, ближайшие действия и полный список открытых шагов.
- После финального go/no-go запускать `ops/collect_acceptance_evidence.py`, чтобы сохранить `outputs/acceptance-evidence-current.json` с результатами release/live/backup стадий и redacted-командами для архива приемки.
- В интерфейсе директора открывать `Acceptance evidence` или API `GET /api/acceptance/evidence`, затем скачивать `/api/acceptance/evidence.json` как машинно-читаемое доказательство без паролей, API-ключей и token hash.
- Последним шагом запускать `ops/completion_audit.py`; принимать локальную передачу при `local_handoff_ready=true`, а production-запуск только при дополнительном `production_ready=true`.
- Не ставить `QH_REFERENCE_VERIFIED_AT`, пока справочник документов, госпошлин, штрафов, форм и сроков не проверен ответственным специалистом.
- Использовать `Юр. источники` и `qurulush-legal-verification-packet.docx` как рабочий пакет сверки; документы со статусом `expired_do_not_use_as_current_law` оставлять только как предупреждение, не как действующее основание для штрафов или требований.
