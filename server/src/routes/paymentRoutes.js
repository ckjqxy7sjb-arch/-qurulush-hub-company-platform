import { Router } from "express";
import Joi from "joi";
import { index, pay } from "../controllers/paymentController.js";
import { authenticate, allowRoles, requireCompanyRole } from "../middleware/auth.js";
import { validate } from "../middleware/validate.js";

export const paymentRoutes = Router();

paymentRoutes.use(authenticate, allowRoles("company"));
paymentRoutes.get("/", index);
paymentRoutes.post(
  "/:id/pay",
  requireCompanyRole("director", "accountant"),
  validate(Joi.object({
    provider: Joi.string().max(80).required(),
    paymentNumber: Joi.string().max(120).required(),
    receiptFileName: Joi.string().max(255).allow(""),
  })),
  pay,
);
