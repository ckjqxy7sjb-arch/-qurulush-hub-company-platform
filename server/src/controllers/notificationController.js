import { acceptNotification, listNotifications, saveNotificationReply } from "../models/notificationModel.js";
import { HttpError } from "../middleware/errors.js";

export async function index(req, res, next) {
  try {
    res.json(await listNotifications(req.user, req.query));
  } catch (error) {
    next(error);
  }
}

export async function accept(req, res, next) {
  try {
    const item = await acceptNotification(req.params.id, req.user);
    if (!item) throw new HttpError(404, "Notification not found");
    res.json(item);
  } catch (error) {
    next(error);
  }
}

export async function reply(req, res, next) {
  try {
    const item = await saveNotificationReply(req.params.id, req.user, req.body);
    if (!item) throw new HttpError(404, "Notification not found");
    res.json(item);
  } catch (error) {
    next(error);
  }
}
