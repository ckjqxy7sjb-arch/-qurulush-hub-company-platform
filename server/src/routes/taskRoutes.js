import { Router } from "express";
import Joi from "joi";
import { index, update } from "../controllers/taskController.js";
import { authenticate, allowRoles } from "../middleware/auth.js";
import { validate } from "../middleware/validate.js";

export const taskRoutes = Router();

taskRoutes.use(authenticate, allowRoles("company"));
taskRoutes.get("/", index);
taskRoutes.patch(
  "/:id",
  validate(Joi.object({ status: Joi.string().valid("new", "in_work", "done", "blocked").required(), evidence: Joi.string().allow("").max(3000) })),
  update,
);
