import { Router } from "express";
import { dashboard } from "../controllers/dashboardController.js";
import { authenticate, allowRoles } from "../middleware/auth.js";

export const dashboardRoutes = Router();

dashboardRoutes.use(authenticate, allowRoles("company"));
dashboardRoutes.get("/", dashboard);
