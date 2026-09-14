import jwt from "jsonwebtoken";
import { env } from "../config/env.js";
import { HttpError } from "./errors.js";

export function authenticate(req, _res, next) {
  const header = req.headers.authorization || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!token) return next(new HttpError(401, "Access token required"));
  try {
    req.user = jwt.verify(token, env.accessSecret);
    return next();
  } catch {
    return next(new HttpError(401, "Invalid access token"));
  }
}

export function allowRoles(...roles) {
  return (req, _res, next) => {
    if (!roles.includes(req.user?.role)) {
      return next(new HttpError(403, "Role access denied"));
    }
    return next();
  };
}

export function requireCompanyRole(...companyRoles) {
  return (req, _res, next) => {
    if (req.user?.role !== "company") return next(new HttpError(403, "Company role required"));
    if (companyRoles.length && !companyRoles.includes(req.user?.companyRole)) {
      return next(new HttpError(403, "Company role access denied"));
    }
    return next();
  };
}
