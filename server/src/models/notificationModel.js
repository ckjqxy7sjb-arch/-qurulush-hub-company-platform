import { query } from "../db/pool.js";

export async function listNotifications(user, filters = {}) {
  const params = [user.companyId];
  const statusSql = filters.status ? `AND n.status = $${params.push(filters.status)}` : "";
  const result = await query(
    `SELECT n.*, o.name AS object_name, u.name AS assignee_name
     FROM notifications n
     LEFT JOIN construction_objects o ON o.id = n.object_id
     LEFT JOIN users u ON u.id = n.assignee_id
     WHERE n.company_id = $1 ${statusSql}
     ORDER BY n.urgent DESC, n.due_at ASC NULLS LAST, n.created_at DESC`,
    params,
  );
  return result.rows;
}

export async function acceptNotification(id, user) {
  const result = await query(
    `UPDATE notifications
     SET status = 'in_work', assignee_id = COALESCE(assignee_id, $2), accepted_at = COALESCE(accepted_at, now()), updated_at = now()
     WHERE id = $1 AND company_id = $3
     RETURNING *`,
    [id, user.sub, user.companyId],
  );
  return result.rows[0] || null;
}

export async function saveNotificationReply(id, user, payload) {
  const result = await query(
    `UPDATE notifications
     SET status = 'sent', reply_text = $2, sent_at = now(), updated_at = now()
     WHERE id = $1 AND company_id = $3
     RETURNING *`,
    [id, payload.replyText, user.companyId],
  );
  return result.rows[0] || null;
}

export async function createIncomingNotification(payload) {
  const result = await query(
    `INSERT INTO notifications (company_id, object_id, source, source_ref, type, title, body, status, urgent, due_at, form_data)
     VALUES ($1, $2, $3, $4, $5, $6, $7, 'needs_company', $8, $9, $10::jsonb)
     RETURNING *`,
    [
      payload.companyId,
      payload.objectId || null,
      payload.source,
      payload.sourceRef || null,
      payload.type,
      payload.title,
      payload.body,
      Boolean(payload.urgent),
      payload.dueAt || null,
      JSON.stringify(payload.formData || {}),
    ],
  );
  return result.rows[0];
}
