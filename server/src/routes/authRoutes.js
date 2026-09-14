import { Router } from "express";
import Joi from "joi";
import { login, logout, me, refresh } from "../controllers/authController.js";
import { authenticate } from "../middleware/auth.js";
import { validate } from "../middleware/validate.js";

export const authRoutes = Router();

authRoutes.get("/csrf", (req, res) => res.json({ csrfToken: req.csrfToken() }));
authRoutes.post(
  "/login",
  validate(Joi.object({ email: Joi.string().email().required(), password: Joi.string().min(8).required() })),
  login,
);
authRoutes.post("/refresh", refresh);
authRoutes.post("/logout", logout);
authRoutes.get("/me", authenticate, me);
