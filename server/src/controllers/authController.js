import bcrypt from "bcryptjs";
import ms from "ms";
import { env } from "../config/env.js";
import { findUserByEmail, findUserById, isRefreshTokenActive, revokeRefreshToken, storeRefreshToken } from "../models/authModel.js";
import { hashToken, issueAccessToken, issueRefreshToken, verifyRefreshToken } from "../services/tokenService.js";
import { HttpError } from "../middleware/errors.js";

function refreshCookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: env.cookieSecure,
    path: "/api/auth",
  };
}

export async function login(req, res, next) {
  try {
    const user = await findUserByEmail(req.body.email);
    if (!user || !user.is_active) throw new HttpError(401, "Invalid credentials");
    const ok = await bcrypt.compare(req.body.password, user.password_hash);
    if (!ok) throw new HttpError(401, "Invalid credentials");
    const accessToken = issueAccessToken(user);
    const refresh = issueRefreshToken(user);
    await storeRefreshToken({
      userId: user.id,
      tokenId: refresh.tokenId,
      tokenHash: hashToken(refresh.token),
      expiresAt: new Date(Date.now() + ms(env.refreshTtl)),
    });
    res.cookie("refreshToken", refresh.token, refreshCookieOptions());
    res.json({ accessToken, user: sanitizeUser(user) });
  } catch (error) {
    next(error);
  }
}

export async function refresh(req, res, next) {
  try {
    const token = req.cookies.refreshToken;
    if (!token) throw new HttpError(401, "Refresh token required");
    const decoded = verifyRefreshToken(token);
    const active = await isRefreshTokenActive(decoded.tokenId, hashToken(token));
    if (!active) throw new HttpError(401, "Refresh token revoked");
    const user = await findUserById(decoded.sub);
    if (!user) throw new HttpError(401, "User not found");
    res.json({ accessToken: issueAccessToken(user), user: sanitizeUser(user) });
  } catch (error) {
    next(error);
  }
}

export async function logout(req, res, next) {
  try {
    const token = req.cookies.refreshToken;
    if (token) {
      const decoded = verifyRefreshToken(token);
      await revokeRefreshToken(decoded.tokenId);
    }
    res.clearCookie("refreshToken", refreshCookieOptions());
    res.json({ ok: true });
  } catch (error) {
    next(error);
  }
}

export async function me(req, res, next) {
  try {
    const user = await findUserById(req.user.sub);
    if (!user) throw new HttpError(401, "User not found");
    res.json(sanitizeUser(user));
  } catch (error) {
    next(error);
  }
}

function sanitizeUser(user) {
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    role: user.role,
    companyRole: user.company_role,
    companyId: user.company_id,
    regionId: user.region_id,
    inspectorId: user.inspector_id,
  };
}
