import { listCalendarItems } from "../models/calendarModel.js";
import { listDocuments } from "../models/documentModel.js";
import { listNotifications } from "../models/notificationModel.js";
import { listPayments } from "../models/paymentModel.js";

export async function dashboard(req, res, next) {
  try {
    const [notifications, payments, documents, calendar] = await Promise.all([
      listNotifications(req.user),
      listPayments(req.user),
      listDocuments(req.user),
      listCalendarItems(req.user),
    ]);
    const today = new Date().toISOString().slice(0, 10);
    res.json({
      metrics: {
        newNotifications: notifications.filter((item) => ["new", "needs_company"].includes(item.status)).length,
        unpaidAmount: payments.filter((item) => item.status !== "paid").reduce((sum, item) => sum + Number(item.amount || 0), 0),
        pendingDocuments: documents.filter((item) => !["sent", "accepted", "uploaded"].includes(item.status)).length,
        dueToday: calendar.filter((item) => String(item.due_at || "").slice(0, 10) === today).length,
      },
      urgentNotifications: notifications.filter((item) => item.urgent || item.status === "needs_company").slice(0, 6),
    });
  } catch (error) {
    next(error);
  }
}
