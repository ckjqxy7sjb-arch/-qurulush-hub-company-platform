import { listTasks, updateTask } from "../models/taskModel.js";
import { HttpError } from "../middleware/errors.js";

export async function index(req, res, next) {
  try {
    res.json(await listTasks(req.user));
  } catch (error) {
    next(error);
  }
}

export async function update(req, res, next) {
  try {
    const item = await updateTask(req.params.id, req.user, req.body);
    if (!item) throw new HttpError(404, "Task not found");
    res.json(item);
  } catch (error) {
    next(error);
  }
}
