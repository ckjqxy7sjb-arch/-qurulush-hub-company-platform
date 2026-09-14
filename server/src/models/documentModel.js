import { query, withTransaction } from "../db/pool.js";

export async function listDocuments(user) {
  const result = await query(
    `SELECT d.*, n.title AS notification_title, t.title AS task_title, o.name AS object_name
     FROM documents d
     LEFT JOIN notifications n ON n.id = d.notification_id
     LEFT JOIN tasks t ON t.id = d.task_id
     LEFT JOIN construction_objects o ON o.id = d.object_id
     WHERE d.company_id = $1
     ORDER BY d.due_at ASC NULLS LAST, d.created_at DESC`,
    [user.companyId],
  );
  return result.rows;
}

export async function addDocumentVersion(id, user, file) {
  return withTransaction(async (client) => {
    const doc = await client.query("SELECT * FROM documents WHERE id = $1 AND company_id = $2", [id, user.companyId]);
    if (!doc.rows[0]) return null;
    const version = await client.query(
      `INSERT INTO document_versions (document_id, file_name, file_path, file_size, uploaded_by)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING *`,
      [id, file.originalname, file.path, file.size, user.sub],
    );
    await client.query("UPDATE documents SET status = 'uploaded', updated_at = now() WHERE id = $1", [id]);
    return version.rows[0];
  });
}
