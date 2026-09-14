import { spawn } from "node:child_process";
import { mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import playwright from "/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;
const python = "/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";
const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const port = 8791;
const tempRoot = mkdtempSync(join(tmpdir(), "qurulush-platform-"));
const db = join(tempRoot, "server.sqlite3");
const backups = join(tempRoot, "backups");
const url = `http://127.0.0.1:${port}/04_%D0%A1%D1%82%D1%80%D0%BE%D0%B8%D1%82%D0%B5%D0%BB%D1%8C%D0%BD%D0%B0%D1%8F_%D0%BA%D0%BE%D0%BC%D0%BF%D0%B0%D0%BD%D0%B8%D1%8F.html`;
const demoPassword = `test-${Date.now()}-${Math.random().toString(36).slice(2)}!`;
const validProductionEnv = [
  "QH_BOOTSTRAP_ADMIN_EMAIL=owner@builder.kg",
  "QH_BOOTSTRAP_ADMIN_PASSWORD=RealStrongPassword2026!",
  'QH_BOOTSTRAP_ADMIN_NAME="Замирбек уулу Максатбек"',
  "QH_BOOTSTRAP_ADMIN_ROLE=ceo",
  "QH_DISABLE_DEMO_USERS=1",
  "QH_REQUIRE_PRODUCTION=1",
  "QH_REQUIRE_HOOK_JSON=1",
  "QH_SACC2_API_URL=https://sacc2.avn.kg/api",
  "QH_SACC2_API_KEY=official-sacc2-key-2026",
  'QH_SACC2_SYNC_CMD="/opt/qurulush/bin/sync-sacc2 {payload}"',
  'QH_SACC2_STATUS_MAP={"needs_company":["needs_company","need_company_response"],"informed":["informed"],"review":["review","in_review"],"done":["done","completed"]}',
  "QH_EDS_PROVIDER=OfficialEDS",
  "QH_EDS_API_URL=https://eds.builder.kg/sign",
  'QH_EDS_SIGN_CMD="/opt/qurulush/bin/sign-document {payload}"',
  "QH_PAYMENT_GATEWAY_URL=https://payments.builder.kg/api",
  'QH_PAYMENT_GATEWAY_CMD="/opt/qurulush/bin/confirm-payment {payload}"',
  "QH_STORAGE_MODE=external",
  "QH_STORAGE_URL=s3://company-documents/qurulush-hub",
  'QH_STORAGE_SYNC_CMD="aws s3 cp {file} {storage_url}/{doc_id}/"',
  'QH_AV_SCANNER="/opt/qurulush/bin/scan-upload {file}"',
  "QH_BACKUP_INTERVAL_MINUTES=60",
  "QH_BACKUP_ON_START=1",
  "QH_BACKUP_REMOTE_URL=s3://company-secure-backups/qurulush-hub",
  'QH_BACKUP_REMOTE_CMD="/opt/qurulush/bin/sync-backup {backup} {manifest}"',
  "QH_REFERENCE_VERIFIED_AT=2026-09-13",
].join("\n");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForHealth() {
  for (let i = 0; i < 50; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (res.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("server did not become healthy");
}

async function apiLogin(email, password = demoPassword) {
  const res = await fetch(`http://127.0.0.1:${port}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  assert(res.ok, `login failed for ${email}`);
  return (await res.json()).token;
}

async function apiState(token) {
  const res = await fetch(`http://127.0.0.1:${port}/api/state`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  assert(res.ok, "state fetch failed");
  return (await res.json()).data;
}

async function openTab(page, tab) {
  const button = page.locator(`button[data-tab="${tab}"]`);
  await button.scrollIntoViewIfNeeded();
  await button.click();
}

const server = spawn(python, ["company_platform_server.py", "--port", String(port), "--db", db, "--backups", backups, "--quiet"], {
  cwd: "/Users/maxai/Documents/Codex/2026-05-22/files-mentioned-by-the-user-03",
  env: { ...process.env, QH_DEMO_PASSWORD: demoPassword, QH_SACC2_PUBLIC_URLS: "http://127.0.0.1:9000" },
  stdio: ["ignore", "pipe", "pipe"],
});

try {
  await waitForHealth();
  const healthRes = await fetch(`http://127.0.0.1:${port}/api/health`);
  const healthPayload = await healthRes.clone().json();
  assert(healthPayload.ok && healthPayload.db_ready && healthPayload.storage === "sqlite", "health should expose safe DB readiness");
  assert(!Object.prototype.hasOwnProperty.call(healthPayload, "db"), "health should not expose internal DB path");
  assert(healthRes.headers.get("x-content-type-options") === "nosniff", "API should send nosniff header");
  assert(healthRes.headers.get("x-frame-options") === "SAMEORIGIN", "API should send frame header");
  assert((healthRes.headers.get("content-security-policy") || "").includes("object-src 'none'"), "API should send CSP header");
  const htmlRes = await fetch(url);
  assert(htmlRes.headers.get("x-content-type-options") === "nosniff", "HTML should send nosniff header");
  assert((htmlRes.headers.get("content-security-policy") || "").includes("connect-src 'self'"), "HTML should send CSP header");
  const preRestoreDirector = await apiLogin("director@company.kg");
  const preBackupRes = await fetch(`http://127.0.0.1:${port}/api/backups`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(preBackupRes.ok, "pre-action backup failed");
  const preActionBackup = (await preBackupRes.json()).data.file;
  const restoreDrillRes = await fetch(`http://127.0.0.1:${port}/api/backups/restore-drill`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${preRestoreDirector}` },
    body: JSON.stringify({ file: preActionBackup }),
  });
  assert(restoreDrillRes.ok, "backup restore drill endpoint failed");
  const restoreDrill = (await restoreDrillRes.json()).data;
  assert(restoreDrill.ok && restoreDrill.file === preActionBackup, "backup restore drill payload mismatch");
  assert(restoreDrill.source_integrity === "PRAGMA quick_check: ok", "backup restore drill source integrity failed");
  assert(restoreDrill.restored_integrity === "PRAGMA quick_check: ok", "backup restore drill temp integrity failed");
  assert(restoreDrill.temp_database_removed, "backup restore drill should remove temp database");
  const readinessRes = await fetch(`http://127.0.0.1:${port}/api/readiness`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(readinessRes.ok, "readiness endpoint failed");
  const readiness = (await readinessRes.json()).data;
  assert(readiness.local_ready, "readiness should confirm local platform checks");
  assert(!readiness.production_ready, "readiness should flag missing production integrations");
  assert(readiness.checks.some((item) => item.id === "sacc2_api" && item.status === "missing"), "readiness should include sacc2 gate");
  assert(readiness.checks.some((item) => item.id === "reference_catalog" && item.status === "warning"), "readiness should include reference verification gate");
  assert(readiness.counts.reference_items >= 8, "readiness should count reference catalog items");
  const futureRoadmapRes = await fetch(`http://127.0.0.1:${port}/api/production/future-roadmap`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(futureRoadmapRes.ok, "future roadmap endpoint failed");
  const futureRoadmap = (await futureRoadmapRes.json()).data;
  assert(futureRoadmap.format === "qurulush-future-roadmap-v1", "future roadmap format mismatch");
  assert(futureRoadmap.modules.some((item) => item.id === "field_mobile_app"), "future roadmap should include mobile field app");
  assert(futureRoadmap.modules.some((item) => item.id === "kg_payment_orchestration"), "future roadmap should include Kyrgyzstan payment orchestration");
  const acceptanceRes = await fetch(`http://127.0.0.1:${port}/api/acceptance/passport`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(acceptanceRes.ok, "acceptance passport endpoint failed");
  const acceptancePassport = (await acceptanceRes.json()).data;
  assert(acceptancePassport.format === "qurulush-acceptance-passport-v1", "acceptance passport format mismatch");
  assert(acceptancePassport.local_acceptance, "acceptance passport should confirm local acceptance");
  assert(!acceptancePassport.production_acceptance, "acceptance passport should flag production blockers");
  assert(acceptancePassport.backup_status === "pass", "acceptance passport should verify latest backup");
  const acceptanceDocxRes = await fetch(`http://127.0.0.1:${port}/api/acceptance/passport.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(acceptanceDocxRes.ok, "acceptance passport docx endpoint failed");
  assert(acceptanceDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "acceptance passport docx content type mismatch");
  const acceptanceDocx = Buffer.from(await acceptanceDocxRes.arrayBuffer());
  assert(acceptanceDocx.length > 2000, "acceptance passport docx should not be empty");
  assert(acceptanceDocx.subarray(0, 2).toString() === "PK", "acceptance passport docx should be a zip package");
  const acceptanceEvidenceRes = await fetch(`http://127.0.0.1:${port}/api/acceptance/evidence`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(acceptanceEvidenceRes.ok, "acceptance evidence endpoint failed");
  const acceptanceEvidence = (await acceptanceEvidenceRes.json()).data;
  assert(acceptanceEvidence.format === "qurulush-acceptance-evidence-view-v1", "acceptance evidence format mismatch");
  assert(Array.isArray(acceptanceEvidence.failed_stages), "acceptance evidence should expose failed stages");
  assert(Array.isArray(acceptanceEvidence.commands), "acceptance evidence should expose commands");
  const acceptanceEvidenceJsonRes = await fetch(`http://127.0.0.1:${port}/api/acceptance/evidence.json`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(acceptanceEvidenceJsonRes.ok, "acceptance evidence json endpoint failed");
  assert(acceptanceEvidenceJsonRes.headers.get("content-type") === "application/json; charset=utf-8", "acceptance evidence json content type mismatch");
  const acceptanceEvidenceJson = await acceptanceEvidenceJsonRes.text();
  assert(acceptanceEvidenceJson.includes("qurulush-acceptance-evidence-view-v1"), "acceptance evidence json should include view format");
  assert(!acceptanceEvidenceJson.toLowerCase().includes(demoPassword.toLowerCase()), "acceptance evidence json should not expose demo password");
  assert(!acceptanceEvidenceJson.includes("token_hash"), "acceptance evidence json should not expose token hash fields");
  const completionAuditRes = await fetch(`http://127.0.0.1:${port}/api/acceptance/completion-audit`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(completionAuditRes.ok, "completion audit endpoint failed");
  const completionAudit = (await completionAuditRes.json()).data;
  assert(completionAudit.format === "qurulush-completion-audit-view-v1", "completion audit format mismatch");
  assert(Object.prototype.hasOwnProperty.call(completionAudit, "local_handoff_ready"), "completion audit should expose local handoff state");
  assert(Object.prototype.hasOwnProperty.call(completionAudit, "production_ready"), "completion audit should expose production state");
  const completionAuditJsonRes = await fetch(`http://127.0.0.1:${port}/api/acceptance/completion-audit.json`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(completionAuditJsonRes.ok, "completion audit json endpoint failed");
  assert(completionAuditJsonRes.headers.get("content-type") === "application/json; charset=utf-8", "completion audit json content type mismatch");
  const completionAuditJson = await completionAuditJsonRes.text();
  assert(completionAuditJson.includes("qurulush-completion-audit-view-v1"), "completion audit json should include view format");
  assert(!completionAuditJson.toLowerCase().includes(demoPassword.toLowerCase()), "completion audit json should not expose demo password");
  assert(!completionAuditJson.includes("token_hash"), "completion audit json should not expose token hash fields");
  const calendarRes = await fetch(`http://127.0.0.1:${port}/api/calendar`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(calendarRes.ok, "calendar endpoint failed");
  const calendar = (await calendarRes.json()).data;
  assert(calendar.format === "qurulush-calendar-v1", "calendar format mismatch");
  assert(calendar.open_count > 0, "calendar should expose open deadlines");
  assert(calendar.items.some((item) => item.kind === "Запрос"), "calendar should include request deadlines");
  assert(calendar.items.some((item) => item.kind === "Платеж / штраф"), "calendar should include payment and fine deadlines");
  const chatRes = await fetch(`http://127.0.0.1:${port}/api/chat`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(chatRes.ok, "chat endpoint failed");
  const chat = (await chatRes.json()).data;
  assert(chat.format === "qurulush-internal-chat-v1", "chat format mismatch");
  const chatPostRes = await fetch(`http://127.0.0.1:${port}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${preRestoreDirector}` },
    body: JSON.stringify({ message: "Что сегодня срочно по срокам и ДГАСК?", object: 1 }),
  });
  assert(chatPostRes.ok, "chat post endpoint failed");
  const chatPost = await chatPostRes.json();
  assert(chatPost.assistant?.text?.toLowerCase().includes("срок"), "AI chat should answer about deadlines");
  assert(!JSON.stringify(chatPost).toLowerCase().includes(demoPassword.toLowerCase()), "AI chat should not expose demo password");
  const secondaryDirector = await apiLogin("director@company.kg");
  const sessionsRes = await fetch(`http://127.0.0.1:${port}/api/sessions`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(sessionsRes.ok, "session control endpoint failed");
  const sessionsPayload = (await sessionsRes.json()).data;
  assert(sessionsPayload.active_count >= 2, "session control should list active sessions");
  assert(sessionsPayload.other_count >= 1, "session control should count other sessions");
  assert(sessionsPayload.sessions.some((item) => item.current), "session control should mark current session");
  assert(!JSON.stringify(sessionsPayload).includes("token_hash"), "session control should not expose token hashes");
  const accessMatrixRes = await fetch(`http://127.0.0.1:${port}/api/access/matrix`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(accessMatrixRes.ok, "access matrix endpoint failed");
  const accessMatrix = (await accessMatrixRes.json()).data;
  assert(accessMatrix.format === "qurulush-company-access-matrix-v1", "access matrix format mismatch");
  assert(accessMatrix.roles.some((role) => role.id === "ceo" && role.actions.some((action) => action.id === "team" && action.allowed)), "access matrix should allow director team control");
  assert(accessMatrix.roles.some((role) => role.id === "brigadier" && role.actions.some((action) => action.id === "team" && !action.allowed)), "access matrix should restrict brigadier team control");
  assert(!JSON.stringify(accessMatrix).includes("token_hash"), "access matrix should not expose token hashes");
  const accessMatrixDocxRes = await fetch(`http://127.0.0.1:${port}/api/access/matrix.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(accessMatrixDocxRes.ok, "access matrix docx endpoint failed");
  assert(accessMatrixDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "access matrix docx content type mismatch");
  const accessMatrixDocx = Buffer.from(await accessMatrixDocxRes.arrayBuffer());
  assert(accessMatrixDocx.length > 3000, "access matrix docx should not be empty");
  assert(accessMatrixDocx.subarray(0, 2).toString() === "PK", "access matrix docx should be a zip package");
  const revokeOthersRes = await fetch(`http://127.0.0.1:${port}/api/sessions/revoke-others`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${preRestoreDirector}` },
    body: "{}",
  });
  assert(revokeOthersRes.ok, "session revoke-others endpoint failed");
  const revokeOthersPayload = (await revokeOthersRes.json()).data;
  assert(revokeOthersPayload.revoked_count >= 1, "session revoke-others should revoke at least one session");
  const revokedStateRes = await fetch(`http://127.0.0.1:${port}/api/state`, {
    headers: { Authorization: `Bearer ${secondaryDirector}` },
  });
  assert(revokedStateRes.status === 401, "revoked session should not access state");
  const productionPlanRes = await fetch(`http://127.0.0.1:${port}/api/production/plan`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionPlanRes.ok, "production plan endpoint failed");
  const productionPlan = (await productionPlanRes.json()).data;
  assert(productionPlan.format === "qurulush-production-connection-plan-v1", "production plan format mismatch");
  assert(!productionPlan.production_ready, "production plan should flag production blockers");
  assert(Number.isInteger(productionPlan.completion_percent), "production plan should include completion percent");
  assert(productionPlan.next_step && productionPlan.next_step.next_step, "production plan should expose next launch step");
  assert(productionPlan.items.some((item) => item.id === "sacc2_api" && item.variables.includes("QH_SACC2_API_URL")), "production plan should include sacc2 variables");
  assert(productionPlan.items.some((item) => item.id === "payments"), "production plan should include payments");
  const productionEvidenceRes = await fetch(`http://127.0.0.1:${port}/api/production/evidence`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionEvidenceRes.ok, "production evidence endpoint failed");
  const productionEvidence = (await productionEvidenceRes.json()).data;
  assert(productionEvidence.format === "qurulush-production-evidence-register-v1", "production evidence format mismatch");
  assert(productionEvidence.items.some((item) => item.id === "sacc2_api"), "production evidence should include sacc2 gate");
  const productionEvidenceUpdateRes = await fetch(`http://127.0.0.1:${port}/api/production/evidence`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ id: "sacc2_api", status: "waiting_external", owner: "Директор / IT", deadline: "2026-09-20", evidence: "Browser smoke: ожидается официальный доступ sacc2 / ДГАСК." }),
  });
  assert(productionEvidenceUpdateRes.ok, "production evidence update endpoint failed");
  const productionEvidenceUpdate = (await productionEvidenceUpdateRes.json()).data;
  assert(productionEvidenceUpdate.items.find((item) => item.id === "sacc2_api").evidence_status === "waiting_external", "production evidence update should persist");
  const productionEvidenceDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/evidence.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionEvidenceDocxRes.ok, "production evidence docx endpoint failed");
  assert(productionEvidenceDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production evidence docx content type mismatch");
  const productionEvidenceDocx = Buffer.from(await productionEvidenceDocxRes.arrayBuffer());
  assert(productionEvidenceDocx.length > 2500, "production evidence docx should not be empty");
  assert(productionEvidenceDocx.subarray(0, 2).toString() === "PK", "production evidence docx should be a zip package");
  const productionRequestPackRes = await fetch(`http://127.0.0.1:${port}/api/production/request-pack`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionRequestPackRes.ok, "production request pack endpoint failed");
  const productionRequestPack = (await productionRequestPackRes.json()).data;
  assert(productionRequestPack.format === "qurulush-production-request-pack-v1", "production request pack format mismatch");
  assert(productionRequestPack.items.some((item) => item.id === "sacc2_api" && item.stakeholder.includes("Министерство строительства")), "production request pack should include sacc2 ministry request");
  const productionRequestPackDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/request-pack.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionRequestPackDocxRes.ok, "production request pack docx endpoint failed");
  assert(productionRequestPackDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production request pack docx content type mismatch");
  const productionRequestPackDocx = Buffer.from(await productionRequestPackDocxRes.arrayBuffer());
  assert(productionRequestPackDocx.length > 3000, "production request pack docx should not be empty");
  assert(productionRequestPackDocx.subarray(0, 2).toString() === "PK", "production request pack docx should be a zip package");
  const productionOfficialLettersRes = await fetch(`http://127.0.0.1:${port}/api/production/official-letters`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionOfficialLettersRes.ok, "production official letters endpoint failed");
  const productionOfficialLetters = (await productionOfficialLettersRes.json()).data;
  assert(productionOfficialLetters.format === "qurulush-production-official-letters-v1", "production official letters format mismatch");
  assert(productionOfficialLetters.letters.some((letter) => letter.id === "sacc2_api" && letter.recipient.includes("Министерство строительства")), "production official letters should include ministry letter");
  const productionOfficialLettersDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/official-letters.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionOfficialLettersDocxRes.ok, "production official letters docx endpoint failed");
  assert(productionOfficialLettersDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production official letters docx content type mismatch");
  const productionOfficialLettersDocx = Buffer.from(await productionOfficialLettersDocxRes.arrayBuffer());
  assert(productionOfficialLettersDocx.length > 3000, "production official letters docx should not be empty");
  assert(productionOfficialLettersDocx.subarray(0, 2).toString() === "PK", "production official letters docx should be a zip package");
  const productionRequestTrackerRes = await fetch(`http://127.0.0.1:${port}/api/production/request-pack/tracker`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ id: "sacc2_api", status: "sent", outgoing_no: "BROWSER-SACC2-2026-001", sent_at: "2026-09-13", contact: "Минстрой / ДГАСК", responsible: "Директор / IT", note: "Browser smoke: запрос доступа sacc2 отправлен." }),
  });
  assert(productionRequestTrackerRes.ok, "production request tracker endpoint failed");
  const productionRequestTracker = (await productionRequestTrackerRes.json()).data;
  assert(productionRequestTracker.request_pack.items.find((item) => item.id === "sacc2_api").tracker_status === "sent", "production request tracker should persist sent status");
  assert(productionRequestTracker.evidence.items.find((item) => item.id === "sacc2_api").evidence_status === "waiting_external", "production request tracker should sync evidence");
  const productionActionBoardRes = await fetch(`http://127.0.0.1:${port}/api/production/action-board`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionActionBoardRes.ok, "production action board endpoint failed");
  const productionActionBoard = (await productionActionBoardRes.json()).data;
  assert(productionActionBoard.format === "qurulush-production-action-board-v1", "production action board format mismatch");
  assert(productionActionBoard.groups.some((group) => group.id === "ministry" && group.items.some((item) => item.id === "sacc2_api")), "production action board should group sacc2 under ministry");
  assert(productionActionBoard.groups.some((group) => group.id === "accountant" && group.items.some((item) => item.id === "payments")), "production action board should group payments under accountant");
  const productionActionBoardDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/action-board.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionActionBoardDocxRes.ok, "production action board docx endpoint failed");
  assert(productionActionBoardDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production action board docx content type mismatch");
  const productionActionBoardDocx = Buffer.from(await productionActionBoardDocxRes.arrayBuffer());
  assert(productionActionBoardDocx.length > 3000, "production action board docx should not be empty");
  assert(productionActionBoardDocx.subarray(0, 2).toString() === "PK", "production action board docx should be a zip package");
  const productionLaunchSequenceRes = await fetch(`http://127.0.0.1:${port}/api/production/launch-sequence`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionLaunchSequenceRes.ok, "production launch sequence endpoint failed");
  const productionLaunchSequence = (await productionLaunchSequenceRes.json()).data;
  assert(productionLaunchSequence.format === "qurulush-production-launch-sequence-v1", "production launch sequence format mismatch");
  assert(productionLaunchSequence.phases.some((phase) => phase.id === "integrations" && phase.steps.some((step) => step.id === "sacc2_api")), "production launch sequence should include sacc2 step");
  assert(productionLaunchSequence.phases.some((phase) => phase.id === "acceptance" && phase.steps.some((step) => step.id === "final_go_no_go")), "production launch sequence should include final go/no-go");
  const productionLaunchSequenceDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/launch-sequence.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionLaunchSequenceDocxRes.ok, "production launch sequence docx endpoint failed");
  assert(productionLaunchSequenceDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production launch sequence docx content type mismatch");
  const productionLaunchSequenceDocx = Buffer.from(await productionLaunchSequenceDocxRes.arrayBuffer());
  assert(productionLaunchSequenceDocx.length > 3000, "production launch sequence docx should not be empty");
  assert(productionLaunchSequenceDocx.subarray(0, 2).toString() === "PK", "production launch sequence docx should be a zip package");
  const productionRemainingWorkRes = await fetch(`http://127.0.0.1:${port}/api/production/remaining-work`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionRemainingWorkRes.ok, "production remaining work endpoint failed");
  const productionRemainingWork = (await productionRemainingWorkRes.json()).data;
  assert(productionRemainingWork.format === "qurulush-production-remaining-work-v1", "production remaining work format mismatch");
  assert(productionRemainingWork.remaining_count >= 1, "production remaining work should list open steps");
  assert(productionRemainingWork.steps.some((step) => step.id === "sacc2_api"), "production remaining work should include sacc2 step");
  const productionRemainingWorkDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/remaining-work.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionRemainingWorkDocxRes.ok, "production remaining work docx endpoint failed");
  assert(productionRemainingWorkDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production remaining work docx content type mismatch");
  const productionRemainingWorkDocx = Buffer.from(await productionRemainingWorkDocxRes.arrayBuffer());
  assert(productionRemainingWorkDocx.length > 2500, "production remaining work docx should not be empty");
  assert(productionRemainingWorkDocx.subarray(0, 2).toString() === "PK", "production remaining work docx should be a zip package");
  const productionTopActionsRes = await fetch(`http://127.0.0.1:${port}/api/production/top-actions`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionTopActionsRes.ok, "production top actions endpoint failed");
  const productionTopActions = (await productionTopActionsRes.json()).data;
  assert(productionTopActions.format === "qurulush-production-top-actions-v1", "production top actions format mismatch");
  assert(productionTopActions.action_count >= 1, "production top actions should list priorities");
  assert(productionTopActions.actions.length <= 5, "production top actions should stay short");
  const productionTopActionsDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/top-actions.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionTopActionsDocxRes.ok, "production top actions docx endpoint failed");
  assert(productionTopActionsDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production top actions docx content type mismatch");
  const productionTopActionsDocx = Buffer.from(await productionTopActionsDocxRes.arrayBuffer());
  assert(productionTopActionsDocx.length > 2500, "production top actions docx should not be empty");
  assert(productionTopActionsDocx.subarray(0, 2).toString() === "PK", "production top actions docx should be a zip package");
  const productionAlertsRes = await fetch(`http://127.0.0.1:${port}/api/production/alerts`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionAlertsRes.ok, "production alerts endpoint failed");
  const productionAlerts = (await productionAlertsRes.json()).data;
  assert(productionAlerts.format === "qurulush-production-alerts-v1", "production alerts format mismatch");
  assert(Array.isArray(productionAlerts.alerts), "production alerts should return a list");
  const productionQaEvidenceRes = await fetch(`http://127.0.0.1:${port}/api/production/qa-evidence`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionQaEvidenceRes.ok, "production qa evidence endpoint failed");
  const productionQaEvidence = (await productionQaEvidenceRes.json()).data;
  assert(productionQaEvidence.format === "qurulush-production-qa-evidence-v1", "production qa evidence format mismatch");
  assert(productionQaEvidence.automated_checks.some((item) => item.id === "go_no_go"), "production qa evidence should include go/no-go check");
  assert(productionQaEvidence.automated_checks.some((item) => item.id === "acceptance_evidence"), "production qa evidence should include acceptance evidence check");
  assert(productionQaEvidence.artifacts.some((item) => item.id === "current_release_zip"), "production qa evidence should include current release zip");
  const productionQaEvidenceDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/qa-evidence.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionQaEvidenceDocxRes.ok, "production qa evidence docx endpoint failed");
  assert(productionQaEvidenceDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production qa evidence docx content type mismatch");
  const productionQaEvidenceDocx = Buffer.from(await productionQaEvidenceDocxRes.arrayBuffer());
  assert(productionQaEvidenceDocx.length > 2500, "production qa evidence docx should not be empty");
  assert(productionQaEvidenceDocx.subarray(0, 2).toString() === "PK", "production qa evidence docx should be a zip package");
  const productionStatusBoardRes = await fetch(`http://127.0.0.1:${port}/api/production/status-board`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionStatusBoardRes.ok, "production status board endpoint failed");
  const productionStatusBoard = (await productionStatusBoardRes.json()).data;
  assert(productionStatusBoard.format === "qurulush-production-status-board-v1", "production status board format mismatch");
  assert(productionStatusBoard.working_link.endsWith("/04_Строительная_компания.html"), "production status board should include working link");
  assert(productionStatusBoard.summary_cards.some((item) => item.id === "working_link"), "production status board should include working link card");
  assert(productionStatusBoard.summary_cards.some((item) => item.id === "acceptance_evidence"), "production status board should include acceptance evidence card");
  assert(productionStatusBoard.qa_checks.some((item) => item.id === "go_no_go"), "production status board should include go/no-go QA check");
  assert(productionStatusBoard.qa_checks.some((item) => item.id === "acceptance_evidence"), "production status board should include acceptance evidence QA check");
  const productionStatusBoardDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/status-board.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionStatusBoardDocxRes.ok, "production status board docx endpoint failed");
  assert(productionStatusBoardDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production status board docx content type mismatch");
  const productionStatusBoardDocx = Buffer.from(await productionStatusBoardDocxRes.arrayBuffer());
  assert(productionStatusBoardDocx.length > 2500, "production status board docx should not be empty");
  assert(productionStatusBoardDocx.subarray(0, 2).toString() === "PK", "production status board docx should be a zip package");
  const productionPlanDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/plan.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionPlanDocxRes.ok, "production plan docx endpoint failed");
  assert(productionPlanDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production plan docx content type mismatch");
  const productionPlanDocx = Buffer.from(await productionPlanDocxRes.arrayBuffer());
  assert(productionPlanDocx.length > 2000, "production plan docx should not be empty");
  assert(productionPlanDocx.subarray(0, 2).toString() === "PK", "production plan docx should be a zip package");
  const productionEnvRes = await fetch(`http://127.0.0.1:${port}/api/production/env.example`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionEnvRes.ok, "production env example endpoint failed");
  assert((productionEnvRes.headers.get("content-type") || "").includes("text/plain"), "production env example content type mismatch");
  const productionEnv = await productionEnvRes.text();
  assert(productionEnv.includes("QH_REQUIRE_PRODUCTION=1"), "production env example should include production guard");
  assert(productionEnv.includes("QH_SACC2_API_URL=https://sacc2.avn.kg/api"), "production env example should include sacc2 URL");
  assert(!productionEnv.includes(demoPassword), "production env example should not expose demo password");
  const productionEnvValidationRes = await fetch(`http://127.0.0.1:${port}/api/production/env/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(productionEnvValidationRes.ok, "production env validation endpoint failed");
  const productionEnvValidation = (await productionEnvValidationRes.json()).data;
  assert(productionEnvValidation.format === "qurulush-production-env-validation-v1", "production env validation format mismatch");
  assert(productionEnvValidation.ready, "production env validation should accept complete env");
  assert(!JSON.stringify(productionEnvValidation).includes("RealStrongPassword2026!"), "production env validation should not echo password");
  assert(!JSON.stringify(productionEnvValidation).includes("official-sacc2-key-2026"), "production env validation should not echo API key");
  const authCutoverRes = await fetch(`http://127.0.0.1:${port}/api/production/auth-cutover/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(authCutoverRes.ok, "auth cutover validation endpoint failed");
  const authCutover = (await authCutoverRes.json()).data;
  assert(authCutover.format === "qurulush-auth-cutover-validation-v1", "auth cutover validation format mismatch");
  assert(authCutover.ready_for_cutover, "auth cutover validation should accept production bootstrap env");
  assert(!JSON.stringify(authCutover).includes("RealStrongPassword2026!"), "auth cutover validation should not echo password");
  const accountCutoverRes = await fetch(`http://127.0.0.1:${port}/api/production/account-cutover`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(accountCutoverRes.ok, "production account cutover endpoint failed");
  const accountCutover = (await accountCutoverRes.json()).data;
  assert(accountCutover.format === "qurulush-production-account-cutover-v1", "production account cutover format mismatch");
  assert(Array.isArray(accountCutover.role_coverage) && accountCutover.role_coverage.length >= 6, "production account cutover should list roles");
  assert(accountCutover.counts.active_demo >= 1, "production account cutover should show active demo users in default demo state");
  assert(!JSON.stringify(accountCutover).includes(demoPassword), "production account cutover should not echo demo password");
  assert(!JSON.stringify(accountCutover).includes("password_hash"), "production account cutover should not expose password hash fields");
  const hookContractRes = await fetch(`http://127.0.0.1:${port}/api/production/hooks/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(hookContractRes.ok, "hook contract validation endpoint failed");
  const hookContract = (await hookContractRes.json()).data;
  assert(hookContract.format === "qurulush-hook-contract-validation-v1", "hook contract validation format mismatch");
  assert(hookContract.ready_for_hook_smoke, "hook contract validation should accept complete hook env");
  assert(!JSON.stringify(hookContract).includes("official-sacc2-key-2026"), "hook contract validation should not echo API key");
  const sacc2ValidationRes = await fetch(`http://127.0.0.1:${port}/api/production/sacc2/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(sacc2ValidationRes.ok, "sacc2 exchange validation endpoint failed");
  const sacc2Validation = (await sacc2ValidationRes.json()).data;
  assert(sacc2Validation.format === "qurulush-sacc2-exchange-validation-v1", "sacc2 exchange validation format mismatch");
  assert(sacc2Validation.ready_for_sacc2_smoke, "sacc2 exchange validation should accept complete env");
  assert(!JSON.stringify(sacc2Validation).includes("official-sacc2-key-2026"), "sacc2 exchange validation should not echo API key");
  const sacc2PublicStatusRes = await fetch(`http://127.0.0.1:${port}/api/external/sacc2-status`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(sacc2PublicStatusRes.ok, "sacc2 public status endpoint failed");
  const sacc2PublicStatus = (await sacc2PublicStatusRes.json()).data;
  assert(sacc2PublicStatus.format === "qurulush-sacc2-public-status-v1", "sacc2 public status format mismatch");
  assert(sacc2PublicStatus.credentials_used === false, "sacc2 public status should not use credentials");
  assert(sacc2PublicStatus.targets.some((item) => item.url === "http://127.0.0.1:9000" && item.status === "blocked"), "sacc2 public status should block private URLs");
  assert(!JSON.stringify(sacc2PublicStatus).includes("official-sacc2-key-2026"), "sacc2 public status should not echo API key");
  const sacc2PublicStatusDocxRes = await fetch(`http://127.0.0.1:${port}/api/external/sacc2-status.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(sacc2PublicStatusDocxRes.ok, "sacc2 public status docx endpoint failed");
  assert(sacc2PublicStatusDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "sacc2 public status docx content type mismatch");
  const sacc2PublicStatusDocx = Buffer.from(await sacc2PublicStatusDocxRes.arrayBuffer());
  assert(sacc2PublicStatusDocx.length > 3000, "sacc2 public status docx should not be empty");
  assert(sacc2PublicStatusDocx.subarray(0, 2).toString() === "PK", "sacc2 public status docx should be a zip package");
  const sacc2PublicStatusAttachRes = await fetch(`http://127.0.0.1:${port}/api/external/sacc2-status/attach`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  assert(sacc2PublicStatusAttachRes.ok, "sacc2 public status attachment endpoint failed");
  const sacc2PublicStatusAttach = (await sacc2PublicStatusAttachRes.json()).data;
  assert(sacc2PublicStatusAttach.format === "qurulush-sacc2-public-status-attachment-v1", "sacc2 public status attachment format mismatch");
  assert(sacc2PublicStatusAttach.attached_gate === "sacc2_api", "sacc2 public status attachment gate mismatch");
  assert(sacc2PublicStatusAttach.tracker_status === "blocked", "sacc2 public status attachment should block unsafe public URL checks");
  assert(sacc2PublicStatusAttach.request_pack.items.some((item) => item.id === "sacc2_api" && item.outgoing_no.startsWith("SACC2-STATUS-")), "sacc2 public status attachment should update request pack");
  assert(!JSON.stringify(sacc2PublicStatusAttach).includes("official-sacc2-key-2026"), "sacc2 public status attachment should not echo API key");
  const edsValidationRes = await fetch(`http://127.0.0.1:${port}/api/production/eds/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(edsValidationRes.ok, "EDS integration validation endpoint failed");
  const edsValidation = (await edsValidationRes.json()).data;
  assert(edsValidation.format === "qurulush-eds-integration-validation-v1", "EDS integration validation format mismatch");
  assert(edsValidation.ready_for_eds_smoke, "EDS integration validation should accept complete env");
  assert(!JSON.stringify(edsValidation).includes("/opt/qurulush/bin/sign-document"), "EDS integration validation should not echo sign command");
  const paymentValidationRes = await fetch(`http://127.0.0.1:${port}/api/production/payments/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(paymentValidationRes.ok, "payment gateway validation endpoint failed");
  const paymentValidation = (await paymentValidationRes.json()).data;
  assert(paymentValidation.format === "qurulush-payment-gateway-validation-v1", "payment gateway validation format mismatch");
  assert(paymentValidation.ready_for_payment_smoke, "payment gateway validation should accept complete env");
  assert(!JSON.stringify(paymentValidation).includes("/opt/qurulush/bin/confirm-payment"), "payment gateway validation should not echo command");
  const storageValidationRes = await fetch(`http://127.0.0.1:${port}/api/production/storage/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(storageValidationRes.ok, "storage integration validation endpoint failed");
  const storageValidation = (await storageValidationRes.json()).data;
  assert(storageValidation.format === "qurulush-storage-integration-validation-v1", "storage integration validation format mismatch");
  assert(storageValidation.ready_for_storage_smoke, "storage integration validation should accept complete env");
  assert(!JSON.stringify(storageValidation).includes("aws s3 cp"), "storage integration validation should not echo command");
  const avValidationRes = await fetch(`http://127.0.0.1:${port}/api/production/av/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(avValidationRes.ok, "AV scanner validation endpoint failed");
  const avValidation = (await avValidationRes.json()).data;
  assert(avValidation.format === "qurulush-av-scanner-validation-v1", "AV scanner validation format mismatch");
  assert(avValidation.ready_for_av_smoke, "AV scanner validation should accept complete env");
  assert(!JSON.stringify(avValidation).includes("/opt/qurulush/bin/scan-upload"), "AV scanner validation should not echo command");
  const backupScheduleValidationRes = await fetch(`http://127.0.0.1:${port}/api/production/backups/schedule/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(backupScheduleValidationRes.ok, "backup schedule validation endpoint failed");
  const backupScheduleValidation = (await backupScheduleValidationRes.json()).data;
  assert(backupScheduleValidation.format === "qurulush-backup-schedule-validation-v1", "backup schedule validation format mismatch");
  assert(backupScheduleValidation.ready_for_backup_schedule, "backup schedule validation should accept complete env");
  const backupRemoteValidationRes = await fetch(`http://127.0.0.1:${port}/api/production/backups/remote/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv }),
  });
  assert(backupRemoteValidationRes.ok, "remote backup validation endpoint failed");
  const backupRemoteValidation = (await backupRemoteValidationRes.json()).data;
  assert(backupRemoteValidation.format === "qurulush-backup-remote-validation-v1", "remote backup validation format mismatch");
  assert(backupRemoteValidation.ready_for_remote_backup_smoke, "remote backup validation should accept complete env");
  assert(!JSON.stringify(backupRemoteValidation).includes("/opt/qurulush/bin/sync-backup"), "remote backup validation should not echo command");
  const productionCutoverValidationRes = await fetch(`http://127.0.0.1:${port}/api/production/cutover/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv, domain: "cabinet.builder.kg", public_url: "https://cabinet.builder.kg/", port: 8781 }),
  });
  assert(productionCutoverValidationRes.ok, "production cutover validation endpoint failed");
  const productionCutoverValidation = (await productionCutoverValidationRes.json()).data;
  assert(productionCutoverValidation.format === "qurulush-production-cutover-validation-v1", "production cutover validation format mismatch");
  assert(productionCutoverValidation.ready_for_production_cutover, "production cutover validation should accept complete env");
  assert(productionCutoverValidation.cutover_scope === "configuration_validation", "production cutover should label configuration validation scope");
  assert(productionCutoverValidation.configuration_ready, "production cutover should mark configuration ready");
  assert(productionCutoverValidation.ready_for_final_acceptance === false, "production cutover should require final acceptance when live probe is not run");
  assert(productionCutoverValidation.stages.some((item) => item.id === "legal_catalog"), "production cutover should include legal catalog gate");
  assert(!JSON.stringify(productionCutoverValidation).includes("official-sacc2-key-2026"), "production cutover validation should not echo API key");
  assert(!JSON.stringify(productionCutoverValidation).includes("/opt/qurulush/bin"), "production cutover validation should not echo commands");
  const productionCutoverDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/cutover.docx`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ env_text: validProductionEnv, domain: "cabinet.builder.kg", public_url: "https://cabinet.builder.kg/", port: 8781 }),
  });
  assert(productionCutoverDocxRes.ok, "production cutover docx endpoint failed");
  assert(productionCutoverDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production cutover docx content type mismatch");
  const productionCutoverDocx = Buffer.from(await productionCutoverDocxRes.arrayBuffer());
  assert(productionCutoverDocx.length > 2000, "production cutover docx should not be empty");
  assert(productionCutoverDocx.subarray(0, 2).toString() === "PK", "production cutover docx should be a zip package");
  assert(!productionCutoverDocx.toString("utf8").includes("official-sacc2-key-2026"), "production cutover docx should not echo API key");
  const productionChecklistRes = await fetch(`http://127.0.0.1:${port}/api/production/checklist`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionChecklistRes.ok, "production launch checklist endpoint failed");
  const productionChecklist = (await productionChecklistRes.json()).data;
  assert(productionChecklist.format === "qurulush-production-launch-checklist-v1", "production launch checklist format mismatch");
  assert(productionChecklist.stages.some((item) => item.id === "final_acceptance"), "production launch checklist should include final acceptance");
  assert(productionChecklist.commands.some((item) => item.id === "go_no_go"), "production launch checklist should include go/no-go command");
  const productionChecklistDocxRes = await fetch(`http://127.0.0.1:${port}/api/production/checklist.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(productionChecklistDocxRes.ok, "production launch checklist docx endpoint failed");
  assert(productionChecklistDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "production launch checklist docx content type mismatch");
  const productionChecklistDocx = Buffer.from(await productionChecklistDocxRes.arrayBuffer());
  assert(productionChecklistDocx.length > 2000, "production launch checklist docx should not be empty");
  assert(productionChecklistDocx.subarray(0, 2).toString() === "PK", "production launch checklist docx should be a zip package");
  const referenceExportRes = await fetch(`http://127.0.0.1:${port}/api/reference/export`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(referenceExportRes.ok, "reference export endpoint failed");
  const referenceExport = (await referenceExportRes.json()).data;
  assert(referenceExport.format === "qurulush-reference-catalog-v1", "reference export format mismatch");
  assert(referenceExport.categories.includes("Разрешительные документы"), "reference export should include permit category");
  assert(referenceExport.categories.includes("Штрафы и нарушения"), "reference export should include fines category");
  assert(referenceExport.source_note.includes("Не является официальной правовой базой"), "reference export should warn about legal verification");
  assert(!JSON.stringify(referenceExport).includes("stored_file"), "reference export should not expose stored files");
  const referenceDocxRes = await fetch(`http://127.0.0.1:${port}/api/reference/export.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(referenceDocxRes.ok, "reference docx export endpoint failed");
  assert(referenceDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "reference docx content type mismatch");
  const referenceDocx = Buffer.from(await referenceDocxRes.arrayBuffer());
  assert(referenceDocx.length > 2000, "reference docx should not be empty");
  assert(referenceDocx.subarray(0, 2).toString() === "PK", "reference docx should be a zip package");
  const legalPacketRes = await fetch(`http://127.0.0.1:${port}/api/legal/verification-packet`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(legalPacketRes.ok, "legal verification packet endpoint failed");
  const legalPacket = (await legalPacketRes.json()).data;
  assert(legalPacket.format === "qurulush-legal-verification-packet-v1", "legal verification packet format mismatch");
  assert(legalPacket.categories.includes("Разрешительные документы"), "legal packet should include permit category");
  assert(legalPacket.categories.includes("Штрафы и нарушения"), "legal packet should include fines category");
  assert(legalPacket.items.some((item) => item.verification_status === "needs_review"), "legal packet should expose review fields");
  assert(legalPacket.official_sources.some((item) => item.id === "minstroy_order_93_2025"), "legal packet should include Minstroy order source");
  assert(legalPacket.official_sources.some((item) => item.id === "offenses_code_2021"), "legal packet should include offenses code source");
  assert(legalPacket.items.some((item) => item.category === "Штрафы и нарушения" && item.source_candidates.some((source) => source.id === "offenses_code_2021")), "legal packet fines should include offenses code candidate");
  assert(!JSON.stringify(legalPacket).includes("stored_file"), "legal packet should not expose stored files");
  const legalPacketDocxRes = await fetch(`http://127.0.0.1:${port}/api/legal/verification-packet.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(legalPacketDocxRes.ok, "legal verification packet docx endpoint failed");
  assert(legalPacketDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "legal verification packet docx content type mismatch");
  const legalPacketDocx = Buffer.from(await legalPacketDocxRes.arrayBuffer());
  assert(legalPacketDocx.length > 2500, "legal verification packet docx should not be empty");
  assert(legalPacketDocx.subarray(0, 2).toString() === "PK", "legal verification packet docx should be a zip package");
  const interactionMapRes = await fetch(`http://127.0.0.1:${port}/api/interaction/map`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(interactionMapRes.ok, "interaction map endpoint failed");
  const interactionMapPayload = (await interactionMapRes.json()).data;
  assert(interactionMapPayload.format === "qurulush-dgask-interaction-map-v1", "interaction map format mismatch");
  assert(interactionMapPayload.workflows.some((item) => item.id === "fine_or_violation"), "interaction map should include fines workflow");
  assert(interactionMapPayload.workflows.some((item) => item.id === "state_fee_payment"), "interaction map should include state fee workflow");
  const interactionMapDocxRes = await fetch(`http://127.0.0.1:${port}/api/interaction/map.docx`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(interactionMapDocxRes.ok, "interaction map docx endpoint failed");
  assert(interactionMapDocxRes.headers.get("content-type") === "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "interaction map docx content type mismatch");
  const interactionMapDocx = Buffer.from(await interactionMapDocxRes.arrayBuffer());
  assert(interactionMapDocx.length > 3000, "interaction map docx should not be empty");
  assert(interactionMapDocx.subarray(0, 2).toString() === "PK", "interaction map docx should be a zip package");
  const launchBundleRes = await fetch(`http://127.0.0.1:${port}/api/production/launch-bundle.zip`, {
    headers: { Authorization: `Bearer ${preRestoreDirector}` },
  });
  assert(launchBundleRes.ok, "production launch bundle endpoint failed");
  assert(launchBundleRes.headers.get("content-type") === "application/zip", "production launch bundle content type mismatch");
  const launchBundle = Buffer.from(await launchBundleRes.arrayBuffer());
  assert(launchBundle.length > 9000, "production launch bundle should not be empty");
  assert(launchBundle.subarray(0, 2).toString() === "PK", "production launch bundle should be a zip package");
  assert(launchBundle.includes(Buffer.from("qurulush-production-evidence-register.docx")), "production launch bundle should include evidence docx");
  assert(launchBundle.includes(Buffer.from("qurulush-production-request-pack.docx")), "production launch bundle should include request pack docx");
  assert(launchBundle.includes(Buffer.from("qurulush-production-official-letters.docx")), "production launch bundle should include official letters docx");
  assert(launchBundle.includes(Buffer.from("qurulush-dgask-interaction-map.docx")), "production launch bundle should include interaction map docx");
  assert(launchBundle.includes(Buffer.from("future-roadmap.json")), "production launch bundle should include future roadmap json");
  assert(launchBundle.includes(Buffer.from("qurulush-production-action-board.docx")), "production launch bundle should include action board docx");
  assert(launchBundle.includes(Buffer.from("qurulush-production-launch-sequence.docx")), "production launch bundle should include launch sequence docx");
  assert(launchBundle.includes(Buffer.from("qurulush-production-remaining-work.docx")), "production launch bundle should include remaining work docx");
  assert(launchBundle.includes(Buffer.from("production-top-actions.json")), "production launch bundle should include top actions json");
  assert(launchBundle.includes(Buffer.from("qurulush-production-top-actions.docx")), "production launch bundle should include top actions docx");
  assert(launchBundle.includes(Buffer.from("production-alerts.json")), "production launch bundle should include production alerts json");
  assert(launchBundle.includes(Buffer.from("qa-evidence.json")), "production launch bundle should include qa evidence json");
  assert(launchBundle.includes(Buffer.from("qurulush-qa-evidence.docx")), "production launch bundle should include qa evidence docx");
  assert(launchBundle.includes(Buffer.from("acceptance-evidence-current.json")), "production launch bundle should include acceptance evidence json");
  assert(launchBundle.includes(Buffer.from("completion-audit-current.json")), "production launch bundle should include completion audit json");
  assert(launchBundle.includes(Buffer.from("production-status-board.json")), "production launch bundle should include status board json");
  assert(launchBundle.includes(Buffer.from("qurulush-production-status-board.docx")), "production launch bundle should include status board docx");
  assert(launchBundle.includes(Buffer.from("qurulush-company-access-matrix.docx")), "production launch bundle should include access matrix docx");
  const deploymentBundleRes = await fetch(`http://127.0.0.1:${port}/api/production/deployment-files.zip`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ domain: "cabinet.builder.kg", admin_email: "owner@builder.kg", port: 8781 }),
  });
  assert(deploymentBundleRes.ok, "deployment files bundle endpoint failed");
  assert(deploymentBundleRes.headers.get("content-type") === "application/zip", "deployment files bundle content type mismatch");
  const deploymentBundle = Buffer.from(await deploymentBundleRes.arrayBuffer());
  assert(deploymentBundle.length > 1500, "deployment files bundle should not be empty");
  assert(deploymentBundle.subarray(0, 2).toString() === "PK", "deployment files bundle should be a zip package");
  const domainHttpsRes = await fetch(`http://127.0.0.1:${port}/api/production/domain/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${preRestoreDirector}`, "Content-Type": "application/json" },
    body: JSON.stringify({ domain: "cabinet.builder.kg", public_url: "https://cabinet.builder.kg/", port: 8781 }),
  });
  assert(domainHttpsRes.ok, "domain HTTPS validation endpoint failed");
  const domainHttps = (await domainHttpsRes.json()).data;
  assert(domainHttps.format === "qurulush-domain-https-validation-v1", "domain HTTPS validation format mismatch");
  assert(domainHttps.ready_for_deployment_files, "domain HTTPS validation should accept production-looking domain");
  assert(domainHttps.required_confirmations.some((item) => item.id === "tls_certificate"), "domain HTTPS validation should list TLS confirmation");
  const browser = await chromium.launch({ headless: true, executablePath: chromePath });
  try {
    const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 1000 } });
    await context.addInitScript((password) => {
      localStorage.setItem("qurulush_company_passwords_v2", JSON.stringify({
        ceo: password,
        chief_engineer: password,
        foreman: password,
        brigadier: password,
        accountant: password,
        lawyer: password,
      }));
    }, demoPassword);
    const page = await context.newPage();
    await page.goto(url, { waitUntil: "networkidle" });
    const loginText = await page.locator("#loginView").textContent();
    const loginVisible = await page.locator("#loginEmail").isVisible();
    if (loginVisible) {
      assert(loginText.includes("Вход в кабинет строительной компании"), "HTTP UI should start with login screen");
      await page.fill("#loginEmail", "director@company.kg");
      await page.fill("#loginPassword", demoPassword);
      await page.click("#loginForm button[type=submit]");
    }
    await page.waitForSelector("#appShell:not(.locked)");
    const currentUserBadge = await page.locator("#currentUserBadge").textContent();
    assert(currentUserBadge.includes("Замирбек уулу Максат"), "login should show current user");
    await page.waitForFunction(() => document.querySelector("#dashboardLaunchStatus")?.textContent?.includes("Боевой запуск"));
    const dashboardLaunchText = await page.locator("#dashboardLaunchStatus").textContent();
    assert(dashboardLaunchText.includes("Production"), "dashboard launch status should show production state");
    assert(dashboardLaunchText.includes("Осталось"), "dashboard launch status should show remaining work");
    assert(dashboardLaunchText.includes("Alerts"), "dashboard launch status should show alerts count");
    assert(dashboardLaunchText.includes("Назначить"), "dashboard launch status should expose quick assignment");
    assert(dashboardLaunchText.includes("Открыть готовность"), "dashboard launch status should link to readiness");
    const tomorrowIso = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    await page.fill("#dash-owner-corporate_auth", "Директор smoke");
    await page.fill("#dash-deadline-corporate_auth", tomorrowIso);
    await page.fill("#dash-evidence-corporate_auth", "Dashboard smoke: назначить реальные учетные записи.");
    await page.locator("#dashboardLaunchStatus .remaining-step", { hasText: "Боевые учетные записи" }).locator("button", { hasText: "Назначить" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Шаг запуска назначен"));
    await page.waitForFunction(() => document.querySelector("#dash-owner-corporate_auth")?.value === "Директор smoke");

    await openTab(page, "calendar");
    await page.waitForSelector("#calendarList .calendar-item");
    const calendarText = await page.locator("#tab-calendar").textContent();
    assert(calendarText.includes("Календарь сроков"), "calendar UI should render");
    assert(calendarText.includes("Поручение") || calendarText.includes("Запрос"), "calendar UI should show work items");
    assert(calendarText.includes("Сегодня") || calendarText.includes("Скоро") || calendarText.includes("Запланировано"), "calendar UI should show urgency");

    await openTab(page, "chat");
    await page.waitForSelector("#chatFeed");
    await page.fill("#chatInput", "Что сегодня срочно по срокам и ДГАСК?");
    await page.locator("#tab-chat button", { hasText: "Отправить" }).click();
    await page.waitForFunction(() => document.querySelector("#chatFeed")?.textContent?.includes("Qurulush AI"));
    const chatText = await page.locator("#tab-chat").textContent();
    assert(chatText.includes("Внутренний чат и ИИ"), "chat UI should render");
    assert(chatText.includes("Qurulush AI"), "chat UI should show AI answer");
    assert(!chatText.toLowerCase().includes(demoPassword.toLowerCase()), "chat UI should not expose demo password");

    await openTab(page, "readiness");
    await page.waitForTimeout(250);
    const readinessText = await page.locator("#tab-readiness").textContent();
    assert(readinessText.includes("Готовность запуска"), "readiness UI should render");
    assert(readinessText.includes("Интеграция sacc2 / ДГАСК"), "readiness UI should show sacc2 dependency");
    await page.click("text=Активные сессии");
    await page.waitForTimeout(250);
    const sessionText = await page.locator("#sessionControl").textContent();
    assert(sessionText.includes("Активные сессии"), "session control UI should render");
    assert(sessionText.includes("Очистить просроченные"), "session control UI should expose expired-session cleanup");
    assert(sessionText.includes("Завершить другие сессии"), "session control UI should expose other-session revoke");
    const remainingText = await page.locator("#remainingSteps").textContent();
    assert(remainingText.includes("Что осталось до боевого запуска"), "readiness UI should show remaining launch steps");
    assert(remainingText.includes("Production готовность"), "remaining steps should show launch progress");
    assert(remainingText.includes("Следующий шаг"), "remaining steps should show next launch action");
    assert(remainingText.includes("Домен и HTTPS"), "remaining steps should include HTTPS");
    assert(remainingText.includes("Интеграция sacc2"), "remaining steps should include sacc2");
    assert(remainingText.includes("Юридическая сверка справочника"), "remaining steps should include legal catalog verification");
    const readinessBundleText = await page.locator("#tab-readiness").textContent();
    assert(readinessBundleText.includes("Пакет запуска ZIP"), "readiness UI should expose launch bundle download");
    assert(readinessBundleText.includes("Deployment-файлы под домен"), "readiness UI should expose deployment composer");
    assert(readinessBundleText.includes("Проверить HTTPS"), "readiness UI should expose domain HTTPS check");
    assert(readinessBundleText.includes("Deployment ZIP"), "readiness UI should expose deployment bundle download");
    assert(readinessBundleText.includes("Проверка production .env"), "readiness UI should expose env validator");
    assert(readinessBundleText.includes("Проверить запуск"), "readiness UI should expose production cutover check");
    assert(readinessBundleText.includes("Мастер запуска платформы"), "readiness UI should expose launch wizard");
    assert(readinessBundleText.includes("Ближайший блокер"), "launch wizard should show nearest blocker");
    assert(readinessBundleText.includes("Финальный чеклист"), "launch wizard should expose checklist action");
    await page.locator("#tab-readiness button", { hasText: "Мобайл/платежи" }).click();
    await page.waitForSelector("#futureRoadmap", { state: "visible", timeout: 3000 });
    const futureRoadmapText = await page.locator("#futureRoadmap").textContent();
    assert(futureRoadmapText.includes("Мобильная версия и платежи КР"), "future roadmap UI should render");
    assert(futureRoadmapText.includes("Мобильная field-версия"), "future roadmap UI should show mobile field app");
    assert(futureRoadmapText.includes("Фото") || futureRoadmapText.includes("фото"), "future roadmap UI should mention photo capture");
    assert(futureRoadmapText.includes("Платежи Кыргызстана"), "future roadmap UI should show Kyrgyzstan payments");
    await page.locator("#deploymentComposer button", { hasText: "Проверить HTTPS" }).click();
    await page.waitForTimeout(250);
    const domainHttpsText = await page.locator("#domainHttpsResult").textContent();
    assert(domainHttpsText.includes("Домен и HTTPS"), "domain HTTPS UI should render result");
    assert(domainHttpsText.includes("TLS-сертификат"), "domain HTTPS UI should show TLS confirmation");
    await page.fill("#productionEnvText", "QH_REQUIRE_PRODUCTION=0\nQH_BOOTSTRAP_ADMIN_PASSWORD=CHANGE_ME");
    await page.locator("#envValidator button", { hasText: "Проверить .env" }).click();
    await page.waitForTimeout(250);
    const envValidationText = await page.locator("#envValidationResult").textContent();
    assert(envValidationText.includes("Результат проверки"), "env validator UI should render result");
    assert(envValidationText.includes("QH_REQUIRE_PRODUCTION"), "env validator UI should list unsafe key");
    assert(!envValidationText.includes("CHANGE_ME"), "env validator UI should not echo submitted values");
    await page.fill("#productionEnvText", validProductionEnv);
    await page.locator("#envValidator button", { hasText: "Проверить запуск" }).click();
    await page.waitForTimeout(250);
    const productionCutoverText = await page.locator("#productionCutoverResult").textContent();
    assert(productionCutoverText.includes("Production cutover"), "production cutover UI should render result");
    assert(productionCutoverText.includes("Каталог разрешений"), "production cutover UI should show legal catalog gate");
    assert(productionCutoverText.includes("Готовность конфигурации:"), "production cutover UI should show configuration completion percent");
    assert(productionCutoverText.includes("Финальная приемка:"), "production cutover UI should show final acceptance state");
    assert(productionCutoverText.includes("Скачать Word"), "production cutover UI should expose Word export");
    assert(!productionCutoverText.includes("official-sacc2-key-2026"), "production cutover UI should not echo API key");
    assert(!productionCutoverText.includes("/opt/qurulush/bin"), "production cutover UI should not echo commands");
    await page.locator("#productionCutoverResult button", { hasText: "Скачать Word" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word cutover"));
    const cutoverToast = await page.locator("#toast").textContent();
    assert(cutoverToast.includes("Word cutover"), "production cutover UI should confirm Word export");
    await page.locator("#envValidator button", { hasText: "Проверить учетные записи" }).click();
    await page.waitForTimeout(250);
    const authCutoverText = await page.locator("#authCutoverResult").textContent();
    assert(authCutoverText.includes("Переход на боевые учетные записи"), "auth cutover UI should render result");
    assert(authCutoverText.includes("owner@builder.kg"), "auth cutover UI should show bootstrap email");
    assert(!authCutoverText.includes("RealStrongPassword2026!"), "auth cutover UI should not echo password");
    await page.locator("#tab-readiness button", { hasText: "Боевые доступы" }).click();
    await page.waitForTimeout(250);
    const accountCutoverText = await page.locator("#productionAccountCutover").textContent();
    assert(accountCutoverText.includes("Боевые учетные записи"), "production account cutover UI should render");
    assert(accountCutoverText.includes("Demo активные"), "production account cutover UI should show active demo count");
    assert(accountCutoverText.includes("Покрытие ролей"), "production account cutover UI should show role coverage");
    assert(accountCutoverText.includes("Пользователи без секретов"), "production account cutover UI should show safe user table");
    assert(accountCutoverText.includes("Пригласить сотрудника"), "production account cutover UI should expose invite action");
    assert(!accountCutoverText.includes(demoPassword), "production account cutover UI should not echo demo password");
    await page.locator("#productionAccountCutover button", { hasText: "Скачать Word" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word по доступам"));
    const accountCutoverToast = await page.locator("#toast").textContent();
    assert(accountCutoverToast.includes("Word по доступам"), "production account cutover UI should confirm Word export");
    await page.locator("#envValidator button", { hasText: "Проверить hooks" }).click();
    await page.waitForTimeout(250);
    const hookContractText = await page.locator("#hookContractsResult").textContent();
    assert(hookContractText.includes("JSON-контракты внешних hooks"), "hook contract UI should render result");
    assert(hookContractText.includes("QH_SACC2_SYNC_CMD"), "hook contract UI should list sacc2 command key");
    assert(!hookContractText.includes("official-sacc2-key-2026"), "hook contract UI should not echo API key");
    await page.locator("#envValidator button", { hasText: "Проверить sacc2" }).click();
    await page.waitForTimeout(250);
    const sacc2Text = await page.locator("#sacc2ExchangeResult").textContent();
    assert(sacc2Text.includes("Интеграция sacc2 / ДГАСК"), "sacc2 validation UI should render result");
    assert(sacc2Text.includes("needs_company"), "sacc2 validation UI should show status map");
    assert(!sacc2Text.includes("official-sacc2-key-2026"), "sacc2 validation UI should not echo API key");
    await page.locator("#tab-readiness button", { hasText: "Статус sacc2" }).click();
    await page.waitForFunction(() => document.querySelector("#sacc2PublicStatus")?.textContent?.includes("Публичная доступность sacc2"));
    const sacc2PublicStatusText = await page.locator("#sacc2PublicStatus").textContent();
    assert(sacc2PublicStatusText.includes("Публичная доступность sacc2"), "sacc2 public status UI should render result");
    assert(sacc2PublicStatusText.includes("Пароли использованы: нет"), "sacc2 public status UI should not use credentials");
    assert(sacc2PublicStatusText.includes("Заблокировано"), "sacc2 public status UI should block private URL");
    assert(sacc2PublicStatusText.includes("Word статус"), "sacc2 public status UI should expose Word export");
    assert(sacc2PublicStatusText.includes("Зафиксировать в запуске"), "sacc2 public status UI should expose tracker attachment");
    await page.locator("#sacc2PublicStatus button", { hasText: "Зафиксировать в запуске" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Статус sacc2 зафиксирован"));
    await page.waitForFunction(() => document.querySelector("#rp-outgoing-sacc2_api")?.value?.startsWith("SACC2-STATUS-"));
    const sacc2AttachmentOutgoingNo = await page.locator("#rp-outgoing-sacc2_api").inputValue();
    assert(sacc2AttachmentOutgoingNo.startsWith("SACC2-STATUS-"), "sacc2 public status attachment should update request pack");
    await page.locator("#sacc2PublicStatus button", { hasText: "Word статус" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word статус sacc2"));
    const sacc2PublicStatusToast = await page.locator("#toast").textContent();
    assert(sacc2PublicStatusToast.includes("Word статус sacc2"), "sacc2 public status UI should confirm Word export");
    await page.locator("#envValidator button", { hasText: "Проверить ЭЦП" }).click();
    await page.waitForTimeout(250);
    const edsText = await page.locator("#edsIntegrationResult").textContent();
    assert(edsText.includes("ЭЦП / электронное подписание"), "EDS validation UI should render result");
    assert(edsText.includes("file_sha256"), "EDS validation UI should show payload fields");
    assert(!edsText.includes("/opt/qurulush/bin/sign-document"), "EDS validation UI should not echo sign command");
    await page.locator("#envValidator button", { hasText: "Проверить платежи" }).click();
    await page.waitForTimeout(250);
    const paymentText = await page.locator("#paymentGatewayResult").textContent();
    assert(paymentText.includes("Платежи, госпошлины и штрафы"), "payment validation UI should render result");
    assert(paymentText.includes("payment_no"), "payment validation UI should show payload fields");
    assert(!paymentText.includes("/opt/qurulush/bin/confirm-payment"), "payment validation UI should not echo command");
    await page.locator("#envValidator button", { hasText: "Проверить хранилище" }).click();
    await page.waitForTimeout(250);
    const storageText = await page.locator("#storageIntegrationResult").textContent();
    assert(storageText.includes("Production-файловое хранилище"), "storage validation UI should render result");
    assert(storageText.includes("{file}"), "storage validation UI should show markers");
    assert(!storageText.includes("aws s3 cp"), "storage validation UI should not echo command");
    await page.locator("#envValidator button", { hasText: "Проверить AV" }).click();
    await page.waitForTimeout(250);
    const avText = await page.locator("#avScannerResult").textContent();
    assert(avText.includes("Антивирусная проверка файлов"), "AV validation UI should render result");
    assert(avText.includes("scan_before_store"), "AV validation UI should show required behavior");
    assert(!avText.includes("/opt/qurulush/bin/scan-upload"), "AV validation UI should not echo command");
    await page.locator("#envValidator button", { hasText: "Проверить бэкапы" }).click();
    await page.waitForTimeout(250);
    const backupScheduleText = await page.locator("#backupScheduleResult").textContent();
    assert(backupScheduleText.includes("Расписание бэкапов"), "backup schedule UI should render result");
    assert(backupScheduleText.includes("при старте"), "backup schedule UI should show startup backup status");
    await page.locator("#envValidator button", { hasText: "Проверить remote backup" }).click();
    await page.waitForTimeout(250);
    const backupRemoteText = await page.locator("#backupRemoteResult").textContent();
    assert(backupRemoteText.includes("Удаленное хранение бэкапов"), "remote backup UI should render result");
    assert(backupRemoteText.includes("{manifest}"), "remote backup UI should show manifest marker");
    assert(!backupRemoteText.includes("/opt/qurulush/bin/sync-backup"), "remote backup UI should not echo command");
    await page.click("text=План подключения");
    await page.waitForTimeout(250);
    const productionPlanText = await page.locator("#productionPlan").textContent();
    assert(productionPlanText.includes("План production-подключения"), "production plan UI should render");
    assert(productionPlanText.includes("QH_SACC2_API_URL"), "production plan UI should show sacc2 variables");
    assert(productionPlanText.includes("Платежный шлюз"), "production plan UI should show payments step");
    assert(productionPlanText.includes("Скачать Word"), "production plan UI should expose Word export");
    assert(productionPlanText.includes("Скачать .env"), "production plan UI should expose env export");
    assert(productionPlanText.includes("QA пакет"), "production plan UI should expose QA evidence action");
    const productionEvidenceText = await page.locator("#productionEvidence").textContent();
    assert(productionEvidenceText.includes("Evidence-регистр запуска"), "production evidence UI should render");
    assert(productionEvidenceText.includes("Интеграция sacc2"), "production evidence UI should include sacc2 gate");
    await page.selectOption("#ev-status-sacc2_api", "in_progress");
    await page.fill("#ev-owner-sacc2_api", "Директор / IT");
    await page.fill("#ev-deadline-sacc2_api", "2026-09-21");
    await page.fill("#ev-note-sacc2_api", "UI smoke: письмо по доступу sacc2 отправлено.");
    await page.locator("#productionEvidence tr", { hasText: "Интеграция sacc2" }).locator("button", { hasText: "Сохранить" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Evidence сохранен"));
    const productionEvidenceUpdatedNote = await page.locator("#ev-note-sacc2_api").inputValue();
    assert(productionEvidenceUpdatedNote.includes("UI smoke: письмо по доступу sacc2 отправлено."), "production evidence UI should persist saved note");
    const productionEvidenceTextAfterSave = await page.locator("#productionEvidence").textContent();
    assert(productionEvidenceTextAfterSave.includes("Скачать Word"), "production evidence UI should expose Word export");
    await page.locator("#productionEvidence button", { hasText: "Скачать Word" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word evidence"));
    const evidenceToast = await page.locator("#toast").textContent();
    assert(evidenceToast.includes("Word evidence"), "production evidence UI should confirm Word export");
    await page.click("text=Пакет запросов");
    await page.waitForTimeout(250);
    const productionRequestPackText = await page.locator("#productionRequestPack").textContent();
    assert(productionRequestPackText.includes("Пакет запросов к внешним сторонам"), "production request pack UI should render");
    assert(productionRequestPackText.includes("Министерство строительства"), "production request pack UI should include ministry stakeholder");
    assert(productionRequestPackText.includes("Доступ к sacc2"), "production request pack UI should include sacc2 request subject");
    assert(productionRequestPackText.includes("Скачать Word"), "production request pack UI should expose Word export");
    await page.click("text=Письма");
    await page.waitForTimeout(250);
    const productionOfficialLettersText = await page.locator("#productionOfficialLetters").textContent();
    assert(productionOfficialLettersText.includes("Официальные письма и заявки"), "production official letters UI should render");
    assert(productionOfficialLettersText.includes("Министерство строительства"), "production official letters UI should include ministry recipient");
    assert(productionOfficialLettersText.includes("госпошлин"), "production official letters UI should include payment/fine text");
    assert(productionOfficialLettersText.includes("Скачать Word"), "production official letters UI should expose Word export");
    await page.locator("#productionOfficialLetters button", { hasText: "Скачать Word" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word письма"));
    const officialLettersToast = await page.locator("#toast").textContent();
    assert(officialLettersToast.includes("Word письма"), "production official letters UI should confirm Word export");
    await page.selectOption("#rp-status-sacc2_api", "sent");
    await page.fill("#rp-outgoing-sacc2_api", "UI-SACC2-2026-002");
    await page.fill("#rp-sent-sacc2_api", "2026-09-13");
    await page.fill("#rp-contact-sacc2_api", "Минстрой / ДГАСК");
    await page.fill("#rp-responsible-sacc2_api", "Директор / IT");
    await page.fill("#rp-note-sacc2_api", "UI tracker: запрос sacc2 отправлен, ожидаем регламент статусов.");
    await page.locator("#productionRequestPack .readiness-card", { hasText: "Интеграция sacc2" }).locator("button", { hasText: "Сохранить трекер" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Трекер запроса сохранен"));
    const requestTrackerToast = await page.locator("#toast").textContent();
    assert(requestTrackerToast.includes("Трекер запроса сохранен"), "production request tracker UI should confirm save");
    const requestTrackerStatus = await page.locator("#rp-status-sacc2_api").inputValue();
    assert(requestTrackerStatus === "sent", "production request tracker UI should persist sent status");
    const syncedEvidenceStatus = await page.locator("#ev-status-sacc2_api").inputValue();
    assert(syncedEvidenceStatus === "waiting_external", "production request tracker UI should sync evidence status");
    await page.click("text=По ролям");
    await page.waitForTimeout(250);
    const productionActionBoardText = await page.locator("#productionActionBoard").textContent();
    assert(productionActionBoardText.includes("Карточки закрытия blockers по ролям"), "production action board UI should render");
    assert(productionActionBoardText.includes("Минстрой / ДГАСК"), "production action board UI should include ministry group");
    assert(productionActionBoardText.includes("Бухгалтер"), "production action board UI should include accountant group");
    assert(productionActionBoardText.includes("Скачать Word"), "production action board UI should expose Word export");
    await page.locator("#productionActionBoard button", { hasText: "Скачать Word" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word карточки по ролям"));
    const actionBoardToast = await page.locator("#toast").textContent();
    assert(actionBoardToast.includes("Word карточки по ролям"), "production action board UI should confirm Word export");
    await page.click("text=Пошагово");
    await page.waitForTimeout(250);
    const productionLaunchSequenceText = await page.locator("#productionLaunchSequence").textContent();
    assert(productionLaunchSequenceText.includes("Пошаговый план запуска"), "production launch sequence UI should render");
    assert(productionLaunchSequenceText.includes("Текущий следующий шаг"), "production launch sequence UI should show current step");
    assert(productionLaunchSequenceText.includes("Интеграции Минстроя"), "production launch sequence UI should include integrations phase");
    assert(productionLaunchSequenceText.includes("Финальный production smoke"), "production launch sequence UI should include final go/no-go");
    assert(productionLaunchSequenceText.includes("Скачать Word"), "production launch sequence UI should expose Word export");
    await page.locator("#productionLaunchSequence button", { hasText: "Скачать Word" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word пошаговый план"));
    const launchSequenceToast = await page.locator("#toast").textContent();
    assert(launchSequenceToast.includes("Word пошаговый план"), "production launch sequence UI should confirm Word export");
    await page.locator("#tab-readiness button", { hasText: "Что осталось" }).click();
    await page.waitForTimeout(250);
    const productionRemainingWorkText = await page.locator("#productionRemainingWork").textContent();
    assert(productionRemainingWorkText.includes("Что осталось до боевого запуска"), "production remaining work UI should render");
    assert(productionRemainingWorkText.includes("Production готовность"), "production remaining work UI should show progress");
    assert(productionRemainingWorkText.includes("Интеграция sacc2"), "production remaining work UI should include sacc2 step");
    assert(productionRemainingWorkText.includes("Ближайшие действия"), "production remaining work UI should show prioritized actions");
    assert(productionRemainingWorkText.includes("Все открытые шаги"), "production remaining work UI should show full open step list");
    assert(productionRemainingWorkText.includes("Скачать Word"), "production remaining work UI should expose Word export");
    assert(productionRemainingWorkText.includes("Word ближайшие"), "production remaining work UI should expose top actions Word export");
    assert(productionRemainingWorkText.includes("Назначить / обновить"), "production remaining work UI should expose assignment action");
    await page.fill("#rw-owner-sacc2_api", "IT-интегратор smoke");
    const todayIso = new Date().toISOString().slice(0, 10);
    await page.fill("#rw-deadline-sacc2_api", todayIso);
    await page.fill("#rw-evidence-sacc2_api", "Smoke assignment: запросить официальный доступ sacc2.");
    await page.evaluate(() => {
      document.querySelector("#rw-owner-sacc2_api").closest(".remaining-step").querySelector("button").click();
    });
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Шаг запуска обновлен"));
    await page.waitForFunction(() => document.querySelector("#rw-owner-sacc2_api")?.value === "IT-интегратор smoke");
    await page.locator("#productionRemainingWork button", { hasText: "Alerts запуска" }).click();
    await page.waitForFunction(() => document.querySelector("#productionAlertsReadiness")?.textContent?.includes("Production alerts"));
    const productionAlertsText = await page.locator("#productionAlertsReadiness").textContent();
    assert(productionAlertsText.includes("Production: Интеграция sacc2"), "production alerts UI should include sacc2 alert");
    assert(productionAlertsText.includes("Сформировать в уведомления"), "production alerts UI should expose notification generation");
    await page.locator("#productionAlertsReadiness button", { hasText: "Сформировать в уведомления" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Production alerts создано"));
    const alertsToast = await page.locator("#toast").textContent();
    assert(alertsToast.includes("Production alerts создано"), "production alerts UI should confirm generation");
    await page.locator("#productionRemainingWork button", { hasText: "Word ближайшие" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word ближайшие действия"));
    await page.locator("#productionRemainingWork button", { hasText: "Скачать Word" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word отчет что осталось"));
    const remainingWorkToast = await page.locator("#toast").textContent();
    assert(remainingWorkToast.includes("Word отчет что осталось"), "production remaining work UI should confirm Word export");
    await page.click("text=QA пакет");
    await page.waitForTimeout(250);
    const qaEvidenceText = await page.locator("#productionQaEvidence").textContent();
    assert(qaEvidenceText.includes("QA evidence пакет"), "production QA evidence UI should render");
    assert(qaEvidenceText.includes("Backend/regression suite"), "production QA evidence UI should show backend checks");
    assert(qaEvidenceText.includes("go_no_go_check.py"), "production QA evidence UI should show go/no-go command");
    assert(qaEvidenceText.includes("dist/qurulush-hub-company-platform-current.zip"), "production QA evidence UI should show current release artifact");
    assert(qaEvidenceText.includes("Скачать Word QA"), "production QA evidence UI should expose Word export");
    await page.locator("#productionQaEvidence button", { hasText: "Скачать Word QA" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word QA"));
    const qaToast = await page.locator("#toast").textContent();
    assert(qaToast.includes("Word QA"), "production QA evidence UI should confirm Word export");
    await page.locator("#tab-readiness button", { hasText: "Статус запуска" }).first().click();
    await page.waitForFunction(() => document.querySelector("#productionStatusBoard")?.textContent?.includes("Статус запуска платформы"));
    const statusBoardText = await page.locator("#productionStatusBoard").textContent();
    assert(statusBoardText.includes("Рабочая ссылка"), "production status board UI should show working link");
    assert(statusBoardText.includes("Ближайшие действия"), "production status board UI should show top actions");
    assert(statusBoardText.includes("Все открытые шаги"), "production status board UI should show all open steps");
    assert(statusBoardText.includes("QA команды"), "production status board UI should show QA commands");
    assert(statusBoardText.includes("Скачать Word статус"), "production status board UI should expose Word export");
    await page.locator("#productionStatusBoard button", { hasText: "Скачать Word статус" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word статус запуска"));
    const statusBoardToast = await page.locator("#toast").textContent();
    assert(statusBoardToast.includes("Word статус запуска"), "production status board UI should confirm Word export");
    await page.locator("#tab-readiness button", { hasText: "Acceptance evidence" }).first().click();
    await page.waitForFunction(() => document.querySelector("#acceptanceEvidence")?.textContent?.includes("Acceptance evidence"));
    const acceptanceEvidenceText = await page.locator("#acceptanceEvidence").textContent();
    assert(acceptanceEvidenceText.includes("Команды без секретов"), "acceptance evidence UI should show sanitized commands");
    assert(acceptanceEvidenceText.includes("Скачать JSON evidence"), "acceptance evidence UI should expose JSON download");
    assert(!acceptanceEvidenceText.toLowerCase().includes(demoPassword.toLowerCase()), "acceptance evidence UI should not expose demo password");
    await page.locator("#acceptanceEvidence button", { hasText: "Скачать JSON evidence" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("JSON evidence"));
    await page.locator("#tab-readiness button", { hasText: "Completion audit" }).first().click();
    await page.waitForFunction(() => document.querySelector("#completionAudit")?.textContent?.includes("Completion audit"));
    const completionAuditText = await page.locator("#completionAudit").textContent();
    assert(completionAuditText.includes("Local handoff"), "completion audit UI should show local handoff status");
    assert(completionAuditText.includes("Production"), "completion audit UI should show production status");
    assert(completionAuditText.includes("Скачать JSON audit"), "completion audit UI should expose JSON download");
    assert(!completionAuditText.toLowerCase().includes(demoPassword.toLowerCase()), "completion audit UI should not expose demo password");
    await page.locator("#completionAudit button", { hasText: "Скачать JSON audit" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("JSON audit"));
    await page.locator("#productionRequestPack button", { hasText: "Скачать Word" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word пакет запросов"));
    const requestPackToast = await page.locator("#toast").textContent();
    assert(requestPackToast.includes("Word пакет запросов"), "production request pack UI should confirm Word export");
    await page.click("text=Чеклист запуска");
    await page.waitForTimeout(250);
    const launchChecklistText = await page.locator("#productionLaunchChecklist").textContent();
    assert(launchChecklistText.includes("Чеклист production-запуска"), "production launch checklist UI should render");
    assert(launchChecklistText.includes("Финальная приемка"), "production launch checklist UI should show final acceptance");
    assert(launchChecklistText.includes("go_no_go_check.py"), "production launch checklist UI should show go/no-go command");
    assert(launchChecklistText.includes("Скачать Word"), "production launch checklist UI should expose Word export");
    await page.click("text=Паспорт приемки");
    await page.waitForTimeout(250);
    const acceptanceText = await page.locator("#acceptancePassport").textContent();
    assert(acceptanceText.includes("Локальная приемка"), "acceptance passport UI should render local status");
    assert(acceptanceText.includes("Backup:"), "acceptance passport UI should render backup status");
    assert(acceptanceText.includes("Скачать Word"), "acceptance passport UI should expose Word export");

    await openTab(page, "audit");
    await page.waitForTimeout(250);
    const seedAuditText = await page.locator("#tab-audit").textContent();
    assert(seedAuditText.includes("Журнал действий"), "audit UI should render");
    assert(seedAuditText.includes("Изменён ответственный инспектор"), "audit UI should show existing events");

    await openTab(page, "reference");
    await page.waitForTimeout(250);
    const referenceText = await page.locator("#tab-reference").textContent();
    assert(referenceText.includes("Справочник требований"), "reference UI should render");
    assert(referenceText.includes("Рабочий каталог платформы"), "reference UI should show working catalog note");
    assert(referenceText.includes("Экспорт Word"), "reference UI should expose Word export");
    assert(referenceText.includes("Юр. сверка Word"), "reference UI should expose legal verification Word export");
    assert(referenceText.includes("Юр. источники"), "reference UI should expose legal source registry");
    await page.click("text=Юр. источники");
    await page.waitForFunction(() => document.querySelector("#legalSourceRegistry")?.textContent?.includes("Юридические источники"));
    const legalSourceText = await page.locator("#legalSourceRegistry").textContent();
    assert(legalSourceText.includes("Минстро"), "legal source registry UI should include Minstroy sources");
    assert(legalSourceText.includes("Кодекс Кыргызской Республики о правонарушениях"), "legal source registry UI should include offenses code source");
    assert(legalSourceText.includes("needs_review"), "legal source registry UI should keep review status");
    assert(legalSourceText.includes("Юр. сверка Word"), "legal source registry UI should expose Word export");
    await page.click("text=Карта взаимодействия");
    await page.waitForTimeout(250);
    const interactionMapText = await page.locator("#interactionMapBox").textContent();
    assert(interactionMapText.includes("Карта взаимодействия с Минстроем"), "interaction map UI should render");
    assert(interactionMapText.includes("Штраф"), "interaction map UI should include fine workflow");
    assert(interactionMapText.includes("Госпошлина"), "interaction map UI should include state fee workflow");
    assert(interactionMapText.includes("sacc2"), "interaction map UI should include sacc2 exchange");
    await page.click("text=Word карта");
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word карта взаимодействия"));
    const interactionMapToast = await page.locator("#toast").textContent();
    assert(interactionMapToast.includes("Word карта взаимодействия"), "interaction map UI should confirm Word export");
    await page.selectOption("#referenceCategory", "Госпошлины и начисления");
    const filteredReferenceText = await page.locator("#referenceBody").textContent();
    assert(filteredReferenceText.includes("Подтверждение оплаты госпошлины"), "reference UI filter should show charges");
    assert(!filteredReferenceText.includes("Протокол о нарушении / штраф"), "reference UI filter should hide fines");

    await page.selectOption("#roleSelect", "chief_engineer");
    await openTab(page, "requests");
    await page.click("#requestsBody button");
    await page.fill("#replyText", "Ответ через HTTP-интерфейс сохранён на сервере.");
    await page.click("text=Отправить ответ");
    await page.waitForTimeout(250);

    await openTab(page, "tasks");
    await page.click("text=Назначить поручение");
    await page.fill("#newTaskTitle", "HTTP поручение прорабу");
    await page.fill("#newTaskText", "Подготовить подтверждение выполнения для инспектора.");
    await page.selectOption("#newTaskObject", "1");
    await page.selectOption("#newTaskOwner", { label: "Прораб" });
    await page.selectOption("#newTaskPriority", "high");
    await page.locator("#detail").getByRole("button", { name: "Назначить поручение" }).click();
    await page.waitForTimeout(250);

    await page.selectOption("#roleSelect", "foreman");
    await page.waitForTimeout(250);
    await openTab(page, "tasks");
    await page.locator("#tasksBody tr", { hasText: "HTTP поручение прорабу" }).getByRole("button", { name: "Карточка" }).click();
    await page.selectOption("#taskUpdateStatus", "done");
    await page.fill("#taskEvidence", "Поручение исполнено, подтверждение приложено.");
    await page.click("text=Сохранить статус");
    await page.waitForTimeout(250);

    await page.selectOption("#roleSelect", "accountant");
    await openTab(page, "money");
    await page.click("#moneyBody button:not([disabled])");
    await page.fill("#paymentNo", "HTTP-PAY-001");
    await page.click("text=Отметить оплачено");
    await page.waitForTimeout(250);

    await page.selectOption("#roleSelect", "lawyer");
    await openTab(page, "money");
    await page.locator("#moneyBody tr", { hasText: "ЕРН" }).getByRole("button", { name: "Карточка" }).click();
    await page.fill("#appealText", "Просим пересмотреть начисление по HTTP-сценарию.");
    await page.click("text=Обжаловать");
    await page.waitForTimeout(250);

    await openTab(page, "requests");
    await page.click("text=Создать обращение");
    await page.fill("#newRequestTitle", "HTTP обращение компании");
    await page.fill("#newRequestText", "Просим назначить ответственного инспектора через серверный контур.");
    await page.click("text=Отправить обращение");
    await page.waitForTimeout(250);

    await page.selectOption("#roleSelect", "chief_engineer");
    await page.waitForTimeout(250);
    await openTab(page, "objects");
    await page.click("text=Добавить объект");
    await page.fill("#newObjectName", "HTTP объект строительства");
    await page.fill("#newObjectAddress", "Бишкек, тестовый адрес");
    await page.click("text=Сохранить объект");
    await page.waitForTimeout(250);

    await openTab(page, "documents");
    await page.locator("#docsBody tr", { hasText: "Проектная документация" }).getByRole("button", { name: "Карточка" }).click();
    await page.setInputFiles("#docFileInput", {
      name: "project-http.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("project file through UI"),
    });
    await page.click("text=Загрузить новую версию");
    await page.waitForTimeout(250);
    await page.locator("#docsBody tr", { hasText: "Проектная документация" }).getByRole("button", { name: "Карточка" }).click();
    const docDetailText = await page.locator("#detail").textContent();
    assert(docDetailText.includes("SHA-256"), "document detail should show checksum");
    assert(docDetailText.includes("VER-1"), "document detail should show version history");
    await page.click("#detail .btn.secondary");

    await page.selectOption("#roleSelect", "ceo");
    await page.waitForTimeout(250);
    await openTab(page, "team");
    const accessGridText = await page.locator("#accessGrid").textContent();
    assert(accessGridText.includes("Генеральный директор"), "access matrix UI should show director role");
    assert(accessGridText.includes("Прораб"), "access matrix UI should show foreman role");
    assert(accessGridText.includes("Бригадир"), "access matrix UI should show brigadier role");
    assert(accessGridText.includes("Ограничения"), "access matrix UI should show role restrictions");
    await page.locator("#tab-team button", { hasText: "Word" }).click();
    await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word матрица доступа"));
    const accessMatrixToast = await page.locator("#toast").textContent();
    assert(accessMatrixToast.includes("Word матрица доступа"), "access matrix UI should confirm Word export");
    await page.click("text=Пригласить сотрудника");
    assert(await page.locator("#inviteObjects option").count() >= 3, "team invite should expose object assignment");
    await page.fill("#inviteName", "HTTP сотрудник");
    await page.fill("#inviteEmail", "http.brigadier@company.kg");
    await page.fill("#invitePassword", "Temp2026!");
    await page.selectOption("#inviteRole", { label: "Бригадир" });
    await page.click("text=Добавить пользователя");
    await page.waitForTimeout(250);

    await page.click("text=Права доступа");
    await page.click("text=Резервные копии");
    await page.waitForTimeout(250);
    const backupListBefore = await page.locator("#backupList").textContent();
    assert(backupListBefore.includes(preActionBackup), "backup list should show existing backup");
    assert(backupListBefore.includes("SHA"), "backup list should show checksum");
    assert(await page.locator("#backupList button", { hasText: "Проверить" }).count() >= 1, "backup list should expose verify action");
    assert(await page.locator("#backupList button", { hasText: "Restore drill" }).count() >= 1, "backup list should expose restore drill action");
    await page.click("text=Создать резервную копию");
    await page.waitForTimeout(250);
    const backupFiles = readdirSync(backups);
    assert(backupFiles.some((name) => name.endsWith(".sqlite3")), "SQLite backup file was not created");
    assert(backupFiles.some((name) => name.endsWith(".json")), "SQLite backup manifest was not created");
    await page.click("#detail .btn.secondary");

    await openTab(page, "notifications");
    await page.click("text=Отметить прочитанными");
    await page.waitForTimeout(250);

    await openTab(page, "requests");
    await page.click("text=Импорт из ДГАСК");
    await page.fill("#externalTitle", "HTTP импорт ДГАСК");
    await page.fill("#externalText", "Серверный импорт должен попасть в очередь компании.");
    await page.click("text=Импортировать запрос");
    await page.waitForTimeout(250);
    await openTab(page, "notifications");
    await page.click("text=Отметить прочитанными");
    await page.waitForTimeout(250);

    const director = await apiLogin("director@company.kg");
    const exportRes = await fetch(`http://127.0.0.1:${port}/api/exchange/export`, {
      headers: { Authorization: `Bearer ${director}` },
    });
    assert(exportRes.ok, "exchange export failed");
    const exportPayload = (await exportRes.json()).data;
    assert(exportPayload.format === "qurulush-company-exchange-v1", "exchange export format mismatch");
    const exportText = JSON.stringify(exportPayload);
    assert(!exportText.includes("stored_file"), "exchange export should not expose stored files");
    assert(!exportText.includes("/api/documents/"), "exchange export should not expose protected local URLs");

    const state = await apiState(director);
    assert(state.requests.find((r) => r.id === "REQ-1048").status === "done", "reply was not persisted to backend");
    assert(state.tasks.some((t) => t.title === "HTTP поручение прорабу" && t.status === "done"), "task completion was not persisted to backend");
    assert(state.money.find((m) => m.id === "PAY-1").status === "Оплачено", "payment was not persisted to backend");
    assert(state.money.find((m) => m.id === "PAY-1").payment_no === "HTTP-PAY-001", "payment number was not persisted to backend");
    assert(state.money.find((m) => m.id === "PAY-2").status === "Обжалуется", "fine appeal was not persisted to backend");
    assert(state.requests.some((r) => r.title === "HTTP обращение компании"), "new request was not persisted to backend");
    assert(state.requests.some((r) => r.title === "HTTP импорт ДГАСК"), "external request import was not persisted to backend");
    assert(state.objects.some((o) => o.name === "HTTP объект строительства"), "new object was not persisted to backend");
    const uploadedDoc = state.docs.find((d) => d.id === "DOC-3");
    assert(uploadedDoc.file === "project-http.txt", "uploaded file name was not persisted to backend");
    assert(uploadedDoc.file_url === "/api/documents/DOC-3/file" && uploadedDoc.file_size > 0, "uploaded file metadata was not persisted to backend");
    const signRes = await fetch(`http://127.0.0.1:${port}/api/documents/DOC-3/sign`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${director}` },
      body: JSON.stringify({ comment: "HTTP smoke signature" }),
    });
    assert(signRes.ok, "document signing endpoint failed");
    const signedDoc = (await signRes.json()).data;
    assert(signedDoc.status === "Подписан", "document signing was not persisted to backend");
    assert(signedDoc.signature_status, "document signing should store signature status");
    const blockedDownload = await fetch(`http://127.0.0.1:${port}${uploadedDoc.file_url}`);
    assert(blockedDownload.status === 401, "document download should require a token");
    const brigadierToken = await apiLogin("brigadier@company.kg");
    const roleBlockedDownload = await fetch(`http://127.0.0.1:${port}${uploadedDoc.file_url}`, {
      headers: { Authorization: `Bearer ${brigadierToken}` },
    });
    assert(roleBlockedDownload.status === 403, "document download should be blocked for brigadier role");
    const download = await fetch(`http://127.0.0.1:${port}${uploadedDoc.file_url}`, {
      headers: { Authorization: `Bearer ${director}` },
    });
    assert(download.ok, "authorized document download failed");
    assert((await download.text()) === "project file through UI", "authorized document download returned wrong file body");
    assert(state.team.some((u) => u.name === "HTTP сотрудник"), "team invite was not persisted to backend");
    const invitedToken = await apiLogin("http.brigadier@company.kg", "Temp2026!");
    const invitedState = await apiState(invitedToken);
    assert(invitedState, "invited employee login failed");
    const changePassword = await fetch(`http://127.0.0.1:${port}/api/auth/change-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${invitedToken}` },
      body: JSON.stringify({ currentPassword: "Temp2026!", newPassword: "Changed2026!" }),
    });
    assert(changePassword.ok, "invited employee password change failed");
    const oldPasswordLogin = await fetch(`http://127.0.0.1:${port}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "http.brigadier@company.kg", password: "Temp2026!" }),
    });
    assert(oldPasswordLogin.status === 401, "old invited employee password should stop working");
    await apiLogin("http.brigadier@company.kg", "Changed2026!");
    assert(state.notifications.every((n) => n.read), "notifications read state was not persisted to backend");
    assert(state.audit.length >= 5, "audit should include UI/API actions");
    const auditExportRes = await fetch(`http://127.0.0.1:${port}/api/audit/export`, {
      headers: { Authorization: `Bearer ${director}` },
    });
    assert(auditExportRes.ok, "audit export failed");
    const auditExport = (await auditExportRes.json()).data;
    assert(auditExport.format === "qurulush-audit-export-v1", "audit export format mismatch");
    assert(auditExport.audit.some((item) => item.event.includes("HTTP-PAY-001")), "audit export should include payment action");
    assert(auditExport.audit.some((item) => item.event.includes("HTTP поручение прорабу")), "audit export should include task action");
    assert(!JSON.stringify(auditExport).includes("stored_file"), "audit export should not expose stored files");

    const restoreRes = await fetch(`http://127.0.0.1:${port}/api/backups/restore`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${director}` },
      body: JSON.stringify({ file: preActionBackup }),
    });
    assert(restoreRes.ok, "backup restore failed");
    const restoredState = await apiState(director);
    assert(!restoredState.requests.some((r) => r.title === "HTTP обращение компании"), "restore should remove post-backup request");
    assert(restoredState.audit.some((item) => item.event.includes("Восстановлено состояние")), "restore should be audited");

    await page.screenshot({ path: "company-platform-server-check.png", fullPage: true });
    await page.getByRole("button", { name: "Выйти" }).click();
    await page.waitForFunction(() => document.querySelector("#appShell")?.classList.contains("locked"));
    const loginVisibleAgain = await page.locator("#loginView").isVisible();
    assert(loginVisibleAgain, "logout should return to login screen");
    console.log(JSON.stringify({
      ok: true,
      checks: [
        "python server health",
        "security headers on API and HTML",
        "readiness endpoint flags production gates",
        "acceptance passport endpoint",
        "acceptance passport docx endpoint",
        "acceptance evidence endpoint",
        "acceptance evidence JSON endpoint",
        "completion audit endpoint",
        "completion audit JSON endpoint",
        "calendar endpoint",
        "chat endpoint",
        "chat post endpoint",
        "future roadmap endpoint",
        "backup restore drill endpoint",
        "session control endpoint",
        "access matrix endpoint",
        "access matrix docx endpoint",
        "session revoke others endpoint",
        "production plan endpoint",
        "production evidence endpoint",
        "production evidence update endpoint",
        "production evidence docx endpoint",
        "production request pack endpoint",
        "production request pack docx endpoint",
        "production official letters endpoint",
        "production official letters docx endpoint",
        "production request tracker endpoint",
        "production action board endpoint",
        "production action board docx endpoint",
        "production launch sequence endpoint",
        "production launch sequence docx endpoint",
        "production remaining work endpoint",
        "production remaining work docx endpoint",
        "production top actions endpoint",
        "production top actions docx endpoint",
        "production alerts endpoint",
        "production qa evidence endpoint",
        "production qa evidence docx endpoint",
        "production status board endpoint",
        "production status board docx endpoint",
        "production plan docx endpoint",
        "production env example endpoint",
        "production env validation endpoint",
        "auth cutover validation endpoint",
        "production account cutover endpoint",
        "hook contract validation endpoint",
        "sacc2 exchange validation endpoint",
        "sacc2 public status endpoint",
        "sacc2 public status docx endpoint",
        "sacc2 public status attachment endpoint",
        "EDS integration validation endpoint",
        "payment gateway validation endpoint",
        "storage integration validation endpoint",
        "AV scanner validation endpoint",
        "backup schedule validation endpoint",
        "remote backup validation endpoint",
        "production cutover validation endpoint",
        "production cutover docx endpoint",
        "production launch checklist endpoint",
        "production launch checklist docx endpoint",
        "reference export endpoint",
        "reference docx export endpoint",
        "legal verification packet endpoint",
        "legal verification packet docx endpoint",
        "interaction map endpoint",
        "interaction map docx endpoint",
        "production launch bundle endpoint",
        "deployment files bundle endpoint",
        "http frontend load",
        "http login screen and session",
        "dashboard launch status UI render",
        "dashboard launch quick assignment UI action",
        "calendar UI render",
        "chat AI UI action",
        "readiness UI render",
        "session control UI render",
        "remaining launch steps UI render",
        "production launch bundle UI action",
        "deployment files bundle UI action",
        "domain HTTPS validation UI action",
        "production launch wizard UI render",
        "future roadmap UI action",
        "production env validator UI action",
        "auth cutover UI action",
        "production account cutover UI action",
        "production account cutover docx UI action",
        "hook contract validation UI action",
        "sacc2 exchange validation UI action",
        "sacc2 public status UI action",
        "sacc2 public status attachment UI action",
        "sacc2 public status docx UI action",
        "EDS integration validation UI action",
        "payment gateway validation UI action",
        "storage integration validation UI action",
        "AV scanner validation UI action",
        "backup schedule validation UI action",
        "remote backup validation UI action",
        "production cutover validation UI action",
        "production cutover docx UI action",
        "production plan UI render",
        "production evidence UI render",
        "production evidence UI update",
        "production evidence docx UI action",
        "production request pack UI render",
        "production official letters UI render",
        "production official letters docx UI action",
        "production request tracker UI update",
        "production action board UI render",
        "production action board docx UI action",
        "production launch sequence UI render",
        "production launch sequence docx UI action",
        "production remaining work UI render",
        "production remaining work assignment UI action",
        "production alerts UI action",
        "production qa evidence UI action",
        "production qa evidence docx UI action",
        "production status board UI action",
        "production status board docx UI action",
        "acceptance evidence UI action",
        "acceptance evidence JSON UI action",
        "completion audit UI action",
        "completion audit JSON UI action",
        "production top actions docx UI action",
        "production remaining work docx UI action",
        "production request pack docx UI action",
        "production env example UI action",
        "production launch checklist UI render",
        "production launch checklist docx UI action",
        "acceptance passport UI render",
        "audit UI render",
        "reference UI render and filter",
        "legal source registry UI action",
        "interaction map UI render",
        "interaction map docx UI action",
        "legal verification packet UI action",
        "api role login",
        "ui task creation persisted to SQLite",
        "ui task completion with evidence persisted to SQLite",
        "ui request reply persisted to SQLite",
        "ui payment persisted to SQLite",
        "ui payment number persisted to SQLite",
        "ui fine appeal persisted to SQLite",
        "ui new request persisted to SQLite",
        "ui external request import persisted to SQLite",
        "ui object creation persisted to SQLite",
        "ui file upload persisted to SQLite",
        "api document signing persisted to SQLite",
        "ui document version and checksum rendered",
        "exchange export is permissioned and sanitized",
        "protected document download requires API token",
        "document download follows role permissions",
        "access matrix UI render",
        "access matrix docx UI action",
        "ui team invite persisted to SQLite",
        "ui object assignment control rendered",
        "invited employee can log in",
        "invited employee can change password",
        "director can create SQLite backup",
        "director can dry-run restore SQLite backup",
        "director can list and restore SQLite backup",
        "director can export sanitized audit log",
        "ui notifications read state persisted to SQLite",
        "ui logout returns to login screen",
        "server audit updated",
      ],
    }));
  } finally {
    await browser.close();
  }
} finally {
  server.kill("SIGTERM");
}
