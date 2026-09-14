import { query } from "../db/pool.js";

export async function listMessages(user) {
  const result = await query(
    `SELECT c.*, u.name AS author_name
     FROM chat_messages c
     LEFT JOIN users u ON u.id = c.author_id
     WHERE c.company_id = $1
     ORDER BY c.created_at ASC
     LIMIT 200`,
    [user.companyId],
  );
  return result.rows;
}

export async function addMessage(user, body, authorType = "user") {
  const result = await query(
    `INSERT INTO chat_messages (company_id, author_id, author_type, body)
     VALUES ($1, $2, $3, $4)
     RETURNING *`,
    [user.companyId, authorType === "user" ? user.sub : null, authorType, body],
  );
  return result.rows[0];
}
