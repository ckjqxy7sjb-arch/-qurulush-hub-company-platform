import { Router } from "express";
import { index } from "../controllers/userController.js";
import { authenticate, allowRoles, requireCompanyRole } from "../middleware/auth.js";

export const userRoutes = Router();

userRoutes.use(authenticate, allowRoles("company"), requireCompanyRole("director"));
userRoutes.get("/", index);
