import { Router } from "express";
import Joi from "joi";
import { index, send } from "../controllers/chatController.js";
import { authenticate, allowRoles } from "../middleware/auth.js";
import { validate } from "../middleware/validate.js";

export const chatRoutes = Router();

chatRoutes.use(authenticate, allowRoles("company"));
chatRoutes.get("/", index);
chatRoutes.post("/", validate(Joi.object({ message: Joi.string().min(1).max(1200).required() })), send);
