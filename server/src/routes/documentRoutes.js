import { Router } from "express";
import { index, uploadVersion } from "../controllers/documentController.js";
import { authenticate, allowRoles } from "../middleware/auth.js";
import { upload } from "../middleware/upload.js";

export const documentRoutes = Router();

documentRoutes.use(authenticate, allowRoles("company", "ministry", "regional", "inspector"));
documentRoutes.get("/", index);
documentRoutes.post("/:id/versions", upload.single("file"), uploadVersion);
