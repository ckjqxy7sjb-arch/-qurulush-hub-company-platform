import { query } from "../db/pool.js";

export async function listCalendarItems(user) {
  const result = await query(
    `SELECT id::text, 'Уведомление' AS type, title, due_at, status, NULL::text AS owner
       FROM notifications WHERE company_id = $1
     UNION ALL
     SELECT id::text, 'Поручение' AS type, title, due_at, status, assignee_id::text AS owner
       FROM tasks WHERE company_id = $1
     UNION ALL
     SELECT id::text, 'Документ' AS type, title, due_at, status, NULL::text AS owner
       FROM documents WHERE company_id = $1
     UNION ALL
     SELECT id::text, 'Платеж' AS type, title, due_at, status, NULL::text AS owner
       FROM payments WHERE company_id = $1
     ORDER BY due_at ASC NULLS LAST`,
    [user.companyId],
  );
  return result.rows;
}
