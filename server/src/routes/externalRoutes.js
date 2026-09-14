import { Router } from "express";
import Joi from "joi";
import { sacc2Notification } from "../controllers/externalController.js";
import { validate } from "../middleware/validate.js";

export const externalRoutes = Router();

externalRoutes.post(
  "/sacc2/notifications",
  validate(Joi.object({
    companyId: Joi.string().guid({ version: "uuidv4" }).required(),
    objectId: Joi.string().guid({ version: "uuidv4" }).allow(null, ""),
    source: Joi.string().max(120).default("sacc2"),
    sourceRef: Joi.string().max(160).allow("", null),
    type: Joi.string().valid("request", "payment", "remark", "inspection", "status", "document").required(),
    title: Joi.string().max(240).required(),
    body: Joi.string().max(4000).required(),
    urgent: Joi.boolean().default(false),
    dueAt: Joi.date().iso().allow(null),
    formData: Joi.object().unknown(true).default({}),
  })),
  sacc2Notification,
);
