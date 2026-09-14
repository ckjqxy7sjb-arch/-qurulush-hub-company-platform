import crypto from "node:crypto";
import jwt from "jsonwebtoken";
import { env } from "../config/env.js";

export function issueAccessToken(user) {
  return jwt.sign(
    {
      sub: user.id,
      role: user.role,
      companyRole: user.company_role,
      companyId: user.company_id,
      regionId: user.region_id,
      inspectorId: user.inspector_id,
    },
    env.accessSecret,
    { expiresIn: env.accessTtl },
  );
}

export function issueRefreshToken(user) {
  const tokenId = crypto.randomUUID();
  const token = jwt.sign({ sub: user.id, tokenId }, env.refreshSecret, { expiresIn: env.refreshTtl });
  return { token, tokenId };
}

export function verifyRefreshToken(token) {
  return jwt.verify(token, env.refreshSecret);
}

export function hashToken(token) {
  return crypto.createHash("sha256").update(token).digest("hex");
}
