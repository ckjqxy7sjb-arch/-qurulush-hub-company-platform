import { listPayments, markPaid } from "../models/paymentModel.js";
import { HttpError } from "../middleware/errors.js";

export async function index(req, res, next) {
  try {
    res.json(await listPayments(req.user));
  } catch (error) {
    next(error);
  }
}

export async function pay(req, res, next) {
  try {
    const item = await markPaid(req.params.id, req.user, req.body);
    if (!item) throw new HttpError(404, "Payment not found");
    res.json(item);
  } catch (error) {
    next(error);
  }
}
