import process from "node:process";

export const env = {
  nodeEnv: process.env.NODE_ENV || "development",
  port: Number(process.env.PORT || 8080),
  databaseUrl: process.env.DATABASE_URL || "postgres://postgres:postgres@127.0.0.1:5432/dgask_kr",
  accessSecret: process.env.JWT_ACCESS_SECRET || "dev-access-secret-change-me",
  refreshSecret: process.env.JWT_REFRESH_SECRET || "dev-refresh-secret-change-me",
  accessTtl: process.env.JWT_ACCESS_TTL || "15m",
  refreshTtl: process.env.JWT_REFRESH_TTL || "30d",
  corsOrigin: (process.env.CORS_ORIGIN || "http://127.0.0.1:5173,http://localhost:5173").split(","),
  cookieSecure: process.env.COOKIE_SECURE === "true",
  uploadDir: process.env.UPLOAD_DIR || "uploads",
  cronTz: process.env.CRON_TZ || "Asia/Bishkek",
};
