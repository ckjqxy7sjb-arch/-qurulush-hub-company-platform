import { query } from "../db/pool.js";

export async function listPayments(user) {
  const result = await query(
    `SELECT p.*, n.title AS notification_title, o.name AS object_name
     FROM payments p
     LEFT JOIN notifications n ON n.id = p.notification_id
     LEFT JOIN construction_objects o ON o.id = p.object_id
     WHERE p.company_id = $1
     ORDER BY p.status <> 'paid' DESC, p.due_at ASC NULLS LAST`,
    [user.companyId],
  );
  return result.rows;
}

export async function markPaid(id, user, payload) {
  const result = await query(
    `UPDATE payments
     SET status = 'paid', provider = $2, payment_number = $3, receipt_file_name = $4, paid_at = now(), paid_by = $5, updated_at = now()
     WHERE id = $1 AND company_id = $6
     RETURNING *`,
    [id, payload.provider, payload.paymentNumber, payload.receiptFileName, user.sub, user.companyId],
  );
  return result.rows[0] || null;
}
