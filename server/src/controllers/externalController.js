import { createIncomingNotification } from "../models/notificationModel.js";
import { sanitizePlainText } from "../services/sanitizeService.js";

export async function sacc2Notification(req, res, next) {
  try {
    const item = await createIncomingNotification({
      ...req.body,
      source: sanitizePlainText(req.body.source),
      title: sanitizePlainText(req.body.title),
      body: sanitizePlainText(req.body.body),
    });
    res.status(201).json({ ok: true, notificationId: item.id });
  } catch (error) {
    next(error);
  }
}
