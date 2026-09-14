import { Router } from "express";
import Joi from "joi";
import { accept, index, reply } from "../controllers/notificationController.js";
import { authenticate, allowRoles } from "../middleware/auth.js";
import { validate } from "../middleware/validate.js";

export const notificationRoutes = Router();

notificationRoutes.use(authenticate, allowRoles("company", "ministry", "regional", "inspector"));
notificationRoutes.get("/", index);
notificationRoutes.post("/:id/accept", accept);
notificationRoutes.post("/:id/reply", validate(Joi.object({ replyText: Joi.string().min(2).max(3000).required() })), reply);
