import { addMessage, listMessages } from "../models/chatModel.js";

function localAssistantAnswer(message) {
  const text = message.toLowerCase();
  if (text.includes("оплат")) return "Проверьте раздел Платежи: сначала основание начисления, затем номер платежа и квитанция.";
  if (text.includes("срок")) return "Откройте Календарь: там собраны сроки по уведомлениям, документам, оплатам и поручениям.";
  if (text.includes("документ")) return "По документам важны версия файла, связь с уведомлением и подтверждение отправки.";
  return "Я помогу разобрать уведомление, назначить ответственного и подготовить ответ компании.";
}

export async function index(req, res, next) {
  try {
    res.json(await listMessages(req.user));
  } catch (error) {
    next(error);
  }
}

export async function send(req, res, next) {
  try {
    await addMessage(req.user, req.body.message, "user");
    await addMessage(req.user, localAssistantAnswer(req.body.message), "assistant");
    res.status(201).json(await listMessages(req.user));
  } catch (error) {
    next(error);
  }
}
