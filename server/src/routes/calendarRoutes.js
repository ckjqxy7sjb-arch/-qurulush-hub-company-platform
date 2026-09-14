import { Router } from "express";
import { index } from "../controllers/calendarController.js";
import { authenticate, allowRoles } from "../middleware/auth.js";

export const calendarRoutes = Router();

calendarRoutes.use(authenticate, allowRoles("company"));
calendarRoutes.get("/", index);
