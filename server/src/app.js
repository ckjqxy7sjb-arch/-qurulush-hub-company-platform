import cookieParser from "cookie-parser";
import cors from "cors";
import csurf from "csurf";
import express from "express";
import rateLimit from "express-rate-limit";
import helmet from "helmet";
import morgan from "morgan";
import { env } from "./config/env.js";
import { authRoutes } from "./routes/authRoutes.js";
import { calendarRoutes } from "./routes/calendarRoutes.js";
import { chatRoutes } from "./routes/chatRoutes.js";
import { dashboardRoutes } from "./routes/dashboardRoutes.js";
import { documentRoutes } from "./routes/documentRoutes.js";
import { externalRoutes } from "./routes/externalRoutes.js";
import { notificationRoutes } from "./routes/notificationRoutes.js";
import { paymentRoutes } from "./routes/paymentRoutes.js";
import { taskRoutes } from "./routes/taskRoutes.js";
import { userRoutes } from "./routes/userRoutes.js";
import { errorHandler, notFound } from "./middleware/errors.js";

export function createApp() {
  const app = express();
  const csrfProtection = csurf({
    cookie: {
      httpOnly: true,
      sameSite: "lax",
      secure: env.cookieSecure,
      path: "/",
    },
  });

  app.use(helmet({
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'self'"],
        scriptSrc: ["'self'"],
        styleSrc: ["'self'", "'unsafe-inline'"],
        imgSrc: ["'self'", "data:", "blob:"],
      },
    },
  }));
  app.use(cors({ origin: env.corsOrigin, credentials: true }));
  app.use(cookieParser());
  app.use(express.json({ limit: "2mb" }));
  app.use(express.urlencoded({ extended: true }));
  app.use("/uploads", express.static(env.uploadDir));
  if (env.nodeEnv !== "test") app.use(morgan("dev"));
  app.use(rateLimit({ windowMs: 60_000, limit: 240 }));

  app.use("/api/auth", csrfProtection, authRoutes);
  app.use("/api/external", externalRoutes);
  app.use((req, res, next) => {
    if (["GET", "HEAD", "OPTIONS"].includes(req.method)) return next();
    if (req.path.startsWith("/api/external/")) return next();
    return csrfProtection(req, res, next);
  });

  app.use("/api/dashboard", dashboardRoutes);
  app.use("/api/notifications", notificationRoutes);
  app.use("/api/payments", paymentRoutes);
  app.use("/api/documents", documentRoutes);
  app.use("/api/tasks", taskRoutes);
  app.use("/api/calendar", calendarRoutes);
  app.use("/api/chat", chatRoutes);
  app.use("/api/users", userRoutes);

  app.use(notFound);
  app.use(errorHandler);
  return app;
}
