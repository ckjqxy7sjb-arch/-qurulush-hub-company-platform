import { query } from "../db/pool.js";

export async function findUserByEmail(email) {
  const result = await query(
    `SELECT id, company_id, region_id, inspector_id, email, name, role, company_role, password_hash, is_active
     FROM users WHERE lower(email) = lower($1)`,
    [email],
  );
  return result.rows[0] || null;
}

export async function findUserById(id) {
  const result = await query(
    `SELECT id, company_id, region_id, inspector_id, email, name, role, company_role, is_active
     FROM users WHERE id = $1 AND is_active = true`,
    [id],
  );
  return result.rows[0] || null;
}

export async function storeRefreshToken({ userId, tokenId, tokenHash, expiresAt }) {
  await query(
    `INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at)
     VALUES ($1, $2, $3, $4)`,
    [tokenId, userId, tokenHash, expiresAt],
  );
}

export async function revokeRefreshToken(tokenId) {
  await query("UPDATE refresh_tokens SET revoked_at = now() WHERE id = $1", [tokenId]);
}

export async function isRefreshTokenActive(tokenId, tokenHash) {
  const result = await query(
    `SELECT 1 FROM refresh_tokens
     WHERE id = $1 AND token_hash = $2 AND revoked_at IS NULL AND expires_at > now()`,
    [tokenId, tokenHash],
  );
  return Boolean(result.rowCount);
}
