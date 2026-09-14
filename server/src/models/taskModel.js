import { query } from "../db/pool.js";

export async function listTasks(user) {
  const result = await query(
    `SELECT t.*, n.title AS notification_title, o.name AS object_name, u.name AS assignee_name
     FROM tasks t
     LEFT JOIN notifications n ON n.id = t.notification_id
     LEFT JOIN construction_objects o ON o.id = t.object_id
     LEFT JOIN users u ON u.id = t.assignee_id
     WHERE t.company_id = $1
     ORDER BY t.due_at ASC NULLS LAST, t.created_at DESC`,
    [user.companyId],
  );
  return result.rows;
}

export async function updateTask(id, user, payload) {
  const result = await query(
    `UPDATE tasks
     SET status = COALESCE($2, status), evidence = COALESCE($3, evidence), completed_at = CASE WHEN $2 = 'done' THEN now() ELSE completed_at END, updated_at = now()
     WHERE id = $1 AND company_id = $4
     RETURNING *`,
    [id, payload.status, payload.evidence, user.companyId],
  );
  return result.rows[0] || null;
}
