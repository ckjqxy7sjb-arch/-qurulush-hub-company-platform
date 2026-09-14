# ДГАСК КР: кабинет строительной компании

Новая основная версия проекта переводит платформу на full-stack:

- Frontend: React 18.3, Vite 5, React Router v6, TanStack Query v5, Zustand, Axios.
- Backend: Node.js 20 LTS, Express 4.19, PostgreSQL через `pg`, JWT auth, Joi validation.
- Production: Windows Server, PM2, IIS reverse proxy.

Цель платформы: дать строительной компании простой рабочий кабинет для входящих уведомлений от sacc2 / Минстроя / ДГАСК, оплат, отправки документов, внутренних поручений, календаря сроков и чата с ИИ.

## Что изменилось

Старый HTML/Python-прототип остается в репозитории как `legacy/reference`. Новый основной код находится в:

- `src/` - React SPA.
- `server/src/` - Express REST API.
- `server/migrations/` - PostgreSQL SQL migrations.
- `docs/ARCHITECTURE.md` - описание архитектуры.
- `docs/WINDOWS_PM2_IIS.md` - схема production на Windows Server + PM2 + IIS.

Из пользовательской логики убраны лишние министерские разделы: юридические источники, НПА-справочник как основной экран, production readiness, acceptance evidence, launch bundle и демо-данные ведомственного кабинета.

## Быстрый старт

```bash
npm install
cp .env.example .env
npm run migrate
npm run seed
npm run dev:api
npm run dev
```

Frontend:

```text
http://127.0.0.1:5173
```

API:

```text
http://127.0.0.1:8080/api
```

## Основные разделы

- `Центр` - главные метрики и срочные действия.
- `Уведомления` - входящие запросы, начисления, замечания, статусы.
- `Платежи` - штрафы, госпошлины, начисления, квитанции.
- `Документы` - ответы, акты, фото, подтверждения оплаты.
- `Поручения` - задачи для прораба, бригадира, бухгалтера, юриста.
- `Календарь` - сроки по уведомлениям, оплатам, документам и задачам.
- `Чат ИИ` - внутренний чат и локальные подсказки.
- `Доступы` - сотрудники, роли и объектные ограничения.

## Роли

В backend есть основные роли ведомственного контура:

- `ministry`
- `regional`
- `inspector`
- `company`

Внутри компании используется `company_role`:

- `director`
- `chief_engineer`
- `foreman`
- `brigadier`
- `accountant`
- `lawyer`

## Внешние интеграции

Подготовлен внешний endpoint для будущего sacc2:

```text
POST /api/external/sacc2/notifications
```

Он принимает входящее уведомление и кладет его в очередь компании.

Платежные системы Кыргызстана будут подключаться через слой `payments`: после callback/reconciliation платформа должна обновлять статус оплаты, сохранять номер платежа и квитанцию.
