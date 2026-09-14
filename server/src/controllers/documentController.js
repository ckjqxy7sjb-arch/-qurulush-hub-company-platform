import { addDocumentVersion, listDocuments } from "../models/documentModel.js";
import { HttpError } from "../middleware/errors.js";

export async function index(req, res, next) {
  try {
    res.json(await listDocuments(req.user));
  } catch (error) {
    next(error);
  }
}

export async function uploadVersion(req, res, next) {
  try {
    if (!req.file) throw new HttpError(400, "File required");
    const item = await addDocumentVersion(req.params.id, req.user, req.file);
    if (!item) throw new HttpError(404, "Document not found");
    res.status(201).json(item);
  } catch (error) {
    next(error);
  }
}
