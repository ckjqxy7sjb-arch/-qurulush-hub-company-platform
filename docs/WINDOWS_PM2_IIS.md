# Windows Server + PM2 + IIS

Production-схема:

1. Node.js 20 LTS запускает REST API.
2. PM2 держит процесс `dgask-kr-api`.
3. IIS работает как reverse proxy на `http://127.0.0.1:8080`.
4. React/Vite build отдается как статический frontend.
5. PostgreSQL хранит рабочие данные.

Команды:

```powershell
npm ci
npm run build
npm run migrate
npm run seed
pm2 start ecosystem.config.cjs
pm2 save
```

IIS должен проксировать:

- `/api/*` -> `http://127.0.0.1:8080/api/*`
- `/uploads/*` -> `http://127.0.0.1:8080/uploads/*`

Frontend build:

- `dist/`

Перед production нужно заменить все значения `.env.example`, включить HTTPS и задать реальные JWT secrets.
