import { listCompanyUsers } from "../models/userModel.js";

export async function index(req, res, next) {
  try {
    res.json(await listCompanyUsers(req.user));
  } catch (error) {
    next(error);
  }
}
