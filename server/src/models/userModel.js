import { query } from "../db/pool.js";

export async function listCompanyUsers(user) {
  const result = await query(
    `SELECT id, email, name, role, company_role, object_scope, is_active
     FROM users
     WHERE company_id = $1
     ORDER BY company_role, name`,
    [user.companyId],
  );
  return result.rows;
}
