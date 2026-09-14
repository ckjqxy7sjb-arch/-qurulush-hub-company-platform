import { listCalendarItems } from "../models/calendarModel.js";

export async function index(req, res, next) {
  try {
    res.json(await listCalendarItems(req.user));
  } catch (error) {
    next(error);
  }
}
