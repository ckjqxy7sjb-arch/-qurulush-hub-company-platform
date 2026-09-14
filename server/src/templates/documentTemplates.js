export function paymentReceiptHtml(payment) {
  return `
    <html>
      <body style="font-family:Arial,sans-serif;padding:32px;color:#111827">
        <h1 style="font-size:20px;margin:0 0 16px">Подтверждение оплаты</h1>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="border:1px solid #ddd;padding:8px">Начисление</td><td style="border:1px solid #ddd;padding:8px">${payment.title}</td></tr>
          <tr><td style="border:1px solid #ddd;padding:8px">Сумма</td><td style="border:1px solid #ddd;padding:8px">${payment.amount} ${payment.currency}</td></tr>
          <tr><td style="border:1px solid #ddd;padding:8px">Номер платежа</td><td style="border:1px solid #ddd;padding:8px">${payment.payment_number || "-"}</td></tr>
          <tr><td style="border:1px solid #ddd;padding:8px">Статус</td><td style="border:1px solid #ddd;padding:8px">${payment.status}</td></tr>
        </table>
      </body>
    </html>
  `;
}

export function notificationReplyHtml(notification) {
  return `
    <html>
      <body style="font-family:Arial,sans-serif;padding:32px;color:#111827">
        <h1 style="font-size:20px;margin:0 0 16px">Ответ строительной компании</h1>
        <p><b>Уведомление:</b> ${notification.title}</p>
        <p><b>Источник:</b> ${notification.source}</p>
        <p><b>Ответ:</b></p>
        <p>${notification.reply_text || ""}</p>
      </body>
    </html>
  `;
}
