import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import playwright from "/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;
const python = "/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";
const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const port = 8792;
const tempRoot = mkdtempSync(join(tmpdir(), "qurulush-responsive-"));
const db = join(tempRoot, "responsive.sqlite3");
const backups = join(tempRoot, "backups");
const url = `http://127.0.0.1:${port}/04_%D0%A1%D1%82%D1%80%D0%BE%D0%B8%D1%82%D0%B5%D0%BB%D1%8C%D0%BD%D0%B0%D1%8F_%D0%BA%D0%BE%D0%BC%D0%BF%D0%B0%D0%BD%D0%B8%D1%8F.html`;
const demoPassword = `test-${Date.now()}-${Math.random().toString(36).slice(2)}!`;

const viewports = [
  { name: "mobile", width: 390, height: 844 },
  { name: "tablet", width: 820, height: 1180 },
  { name: "desktop", width: 1440, height: 1000 },
];

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

async function login(page) {
  await page.fill("#loginEmail", "director@company.kg");
  await page.fill("#loginPassword", demoPassword);
  await page.click("#loginForm button[type='submit']");
  await page.waitForSelector("#appShell:not(.locked)", { timeout: 5000 });
}

async function assertNoPageOverflow(page, name) {
  const metrics = await page.evaluate(() => {
    const app = document.querySelector("#appShell").getBoundingClientRect();
    const top = document.querySelector(".top").getBoundingClientRect();
    const activeTab = document.querySelector(".tab.active").getBoundingClientRect();
    return {
      windowWidth: window.innerWidth,
      docWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      appRight: app.right,
      topRight: top.right,
      activeTabRight: activeTab.right,
      visibleButtons: [...document.querySelectorAll("#nav button")].filter((button) => {
        const rect = button.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }).length,
      activeText: document.querySelector(".tab.active").textContent,
    };
  });
  assert(metrics.docWidth <= metrics.windowWidth + 2, `${name}: document has horizontal overflow ${metrics.docWidth}/${metrics.windowWidth}`);
  assert(metrics.bodyWidth <= metrics.windowWidth + 2, `${name}: body has horizontal overflow ${metrics.bodyWidth}/${metrics.windowWidth}`);
  assert(metrics.appRight <= metrics.windowWidth + 2, `${name}: app shell exceeds viewport`);
  assert(metrics.topRight <= metrics.windowWidth + 2, `${name}: top bar exceeds viewport`);
  assert(metrics.activeTabRight <= metrics.windowWidth + 2, `${name}: active tab exceeds viewport`);
  assert(metrics.visibleButtons >= 12, `${name}: navigation buttons are not visible`);
  assert(metrics.activeText.length > 200, `${name}: active tab did not render meaningful content`);
}

async function assertCalendarChatDetails(page, name) {
  await page.click('button[data-tab="calendar"]');
  await page.waitForSelector("#tab-calendar.active", { timeout: 3000 });
  await page.waitForSelector("#calendarList .calendar-item", { timeout: 3000 });
  const calendarText = await page.locator("#tab-calendar").textContent();
  assert(calendarText.includes("Календарь сроков"), `${name}: calendar title missing`);
  assert(calendarText.includes("Поручение") || calendarText.includes("Запрос"), `${name}: calendar work items missing`);
  assert(calendarText.includes("Ответственный"), `${name}: calendar owner missing`);
  await assertNoPageOverflow(page, `${name} calendar`);

  await page.click('button[data-tab="chat"]');
  await page.waitForSelector("#tab-chat.active", { timeout: 3000 });
  await page.fill("#chatInput", "Что сегодня срочно по срокам?");
  await page.locator("#tab-chat button", { hasText: "Отправить" }).click();
  await page.waitForFunction(() => document.querySelector("#chatFeed")?.textContent?.includes("Qurulush AI"));
  const chatText = await page.locator("#tab-chat").textContent();
  assert(chatText.includes("Внутренний чат и ИИ"), `${name}: chat title missing`);
  assert(chatText.includes("Qurulush AI"), `${name}: AI answer missing`);
  assert(chatText.includes("Сроки"), `${name}: chat quick action missing`);
  await assertNoPageOverflow(page, `${name} chat`);
}

async function assertReadinessDetails(page, name) {
  await page.click('button[data-tab="readiness"]');
  await page.waitForSelector("#tab-readiness.active", { timeout: 3000 });
  await page.locator("#tab-readiness button", { hasText: "Что осталось" }).click();
  await page.waitForFunction(() => document.querySelector("#productionRemainingWork")?.textContent?.includes("Что осталось до боевого запуска"));
  const text = await page.locator("#productionRemainingWork").textContent();
  assert(text.includes("Production готовность"), `${name}: remaining work progress missing`);
  assert(text.includes("Интеграция sacc2"), `${name}: remaining work sacc2 step missing`);
  assert(text.includes("Ближайшие действия"), `${name}: remaining work prioritized actions missing`);
  assert(text.includes("Назначить / обновить"), `${name}: remaining work assignment action missing`);
  assert(text.includes("Word ближайшие"), `${name}: remaining work top actions Word action missing`);
  assert(text.includes("Alerts запуска"), `${name}: remaining work production alerts action missing`);
  assert(text.includes("Скачать Word"), `${name}: remaining work Word action missing`);
  await page.locator("#productionRemainingWork button", { hasText: "Alerts запуска" }).click();
  await page.waitForFunction(() => document.querySelector("#productionAlertsReadiness")?.textContent?.includes("Production alerts"));
  const alertsText = await page.locator("#productionAlertsReadiness").textContent();
  assert(alertsText.includes("Сформировать в уведомления"), `${name}: production alerts generation action missing`);
  await assertNoPageOverflow(page, `${name} remaining work`);
  await page.locator("#productionRemainingWork button", { hasText: "Скачать Word" }).click();
  await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word отчет что осталось"));
  await page.locator("#tab-readiness button", { hasText: "QA пакет" }).first().click();
  await page.waitForFunction(() => document.querySelector("#productionQaEvidence")?.textContent?.includes("QA evidence пакет"));
  const qaText = await page.locator("#productionQaEvidence").textContent();
  assert(qaText.includes("Backend/regression suite"), `${name}: QA evidence backend check missing`);
  assert(qaText.includes("dist/qurulush-hub-company-platform-current.zip"), `${name}: QA evidence release artifact missing`);
  await assertNoPageOverflow(page, `${name} QA evidence`);
  await page.locator("#tab-readiness button", { hasText: "Статус запуска" }).first().click();
  await page.waitForFunction(() => document.querySelector("#productionStatusBoard")?.textContent?.includes("Статус запуска платформы"));
  const statusText = await page.locator("#productionStatusBoard").textContent();
  assert(statusText.includes("Рабочая ссылка"), `${name}: status board working link missing`);
  assert(statusText.includes("Все открытые шаги"), `${name}: status board open steps missing`);
  assert(statusText.includes("QA команды"), `${name}: status board QA commands missing`);
  await assertNoPageOverflow(page, `${name} status board`);
  await page.locator("#tab-readiness button", { hasText: "Мобайл/платежи" }).click();
  await page.waitForFunction(() => document.querySelector("#futureRoadmap")?.textContent?.includes("Мобильная версия и платежи КР"));
  const futureRoadmapText = await page.locator("#futureRoadmap").textContent();
  assert(futureRoadmapText.includes("Мобильная field-версия"), `${name}: future roadmap mobile app missing`);
  assert(futureRoadmapText.includes("Платежи Кыргызстана"), `${name}: future roadmap payments missing`);
  assert(futureRoadmapText.includes("НБКР"), `${name}: future roadmap payment source missing`);
  await assertNoPageOverflow(page, `${name} future roadmap`);
  await page.locator("#tab-readiness button", { hasText: "Acceptance evidence" }).click();
  await page.waitForFunction(() => document.querySelector("#acceptanceEvidence")?.textContent?.includes("Acceptance evidence"));
  const evidenceText = await page.locator("#acceptanceEvidence").textContent();
  assert(evidenceText.includes("Команды без секретов"), `${name}: acceptance evidence sanitized commands missing`);
  assert(evidenceText.includes("Скачать JSON evidence"), `${name}: acceptance evidence JSON action missing`);
  await assertNoPageOverflow(page, `${name} acceptance evidence`);
  await page.locator("#tab-readiness button", { hasText: "Completion audit" }).click();
  await page.waitForFunction(() => document.querySelector("#completionAudit")?.textContent?.includes("Completion audit"));
  const auditText = await page.locator("#completionAudit").textContent();
  assert(auditText.includes("Local handoff"), `${name}: completion audit local handoff missing`);
  assert(auditText.includes("Что осталось"), `${name}: completion audit remaining work missing`);
  assert(auditText.includes("Скачать JSON audit"), `${name}: completion audit JSON action missing`);
  await assertNoPageOverflow(page, `${name} completion audit`);
}

async function assertSacc2StatusDetails(page, name) {
  await page.click('button[data-tab="readiness"]');
  await page.waitForSelector("#tab-readiness.active", { timeout: 3000 });
  await page.locator("#tab-readiness button", { hasText: "Статус sacc2" }).click();
  await page.waitForFunction(() => document.querySelector("#sacc2PublicStatus")?.textContent?.includes("Публичная доступность sacc2"));
  const text = await page.locator("#sacc2PublicStatus").textContent();
  assert(text.includes("Пароли использованы: нет"), `${name}: sacc2 public status should not use credentials`);
  assert(text.includes("Заблокировано"), `${name}: sacc2 public status should block local URLs`);
  assert(text.includes("Зафиксировать в запуске"), `${name}: sacc2 public status attachment action missing`);
  assert(text.includes("Word статус"), `${name}: sacc2 public status Word action missing`);
  await assertNoPageOverflow(page, `${name} sacc2 public status`);
}

async function assertAccountCutoverDetails(page, name) {
  await page.click('button[data-tab="readiness"]');
  await page.waitForSelector("#tab-readiness.active", { timeout: 3000 });
  await page.locator("#tab-readiness button", { hasText: "Боевые доступы" }).click();
  await page.waitForFunction(() => document.querySelector("#productionAccountCutover")?.textContent?.includes("Боевые учетные записи"));
  const text = await page.locator("#productionAccountCutover").textContent();
  assert(text.includes("Demo активные"), `${name}: account cutover demo count missing`);
  assert(text.includes("Покрытие ролей"), `${name}: account cutover role coverage missing`);
  assert(text.includes("Пользователи без секретов"), `${name}: account cutover safe user table missing`);
  assert(text.includes("Скачать Word"), `${name}: account cutover Word action missing`);
  await assertNoPageOverflow(page, `${name} account cutover`);
}

async function assertReferenceDetails(page, name) {
  await page.click('button[data-tab="reference"]');
  await page.waitForSelector("#tab-reference.active", { timeout: 3000 });
  await page.click("text=Юр. источники");
  await page.waitForFunction(() => document.querySelector("#legalSourceRegistry")?.textContent?.includes("Юридические источники"));
  const legalText = await page.locator("#legalSourceRegistry").textContent();
  assert(legalText.includes("Кодекс Кыргызской Республики о правонарушениях"), `${name}: legal source registry offenses code missing`);
  assert(legalText.includes("needs_review"), `${name}: legal source registry review status missing`);
  await assertNoPageOverflow(page, `${name} legal source registry`);
  await page.click("text=Карта взаимодействия");
  await page.waitForFunction(() => document.querySelector("#interactionMapBox")?.textContent?.includes("Карта взаимодействия"));
  const text = await page.locator("#interactionMapBox").textContent();
  assert(text.includes("Госпошлина"), `${name}: interaction map state fee workflow missing`);
  assert(text.includes("Штраф"), `${name}: interaction map fine workflow missing`);
  assert(text.includes("sacc2"), `${name}: interaction map sacc2 exchange missing`);
  await assertNoPageOverflow(page, `${name} interaction map`);
  await page.click("text=Word карта");
  await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word карта взаимодействия"));
}

async function assertAccessDetails(page, name) {
  await page.click('button[data-tab="team"]');
  await page.waitForSelector("#tab-team.active", { timeout: 3000 });
  const text = await page.locator("#accessGrid").textContent();
  assert(text.includes("Генеральный директор"), `${name}: director access row missing`);
  assert(text.includes("Прораб"), `${name}: foreman access row missing`);
  assert(text.includes("Бригадир"), `${name}: brigadier access row missing`);
  assert(text.includes("Ограничения"), `${name}: access restrictions missing`);
  await assertNoPageOverflow(page, `${name} access matrix`);
  await page.locator("#tab-team button", { hasText: "Word" }).click();
  await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("Word матрица доступа"));
}

async function assertViewport(page, viewport) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  await page.goto(url, { waitUntil: "load" });
  await login(page);

  const dashboardLaunchText = await page.locator("#dashboardLaunchStatus").textContent();
  assert(dashboardLaunchText.includes("Боевой запуск"), `${viewport.name}: dashboard launch status missing`);
  assert(dashboardLaunchText.includes("Осталось"), `${viewport.name}: dashboard remaining count missing`);
  assert(dashboardLaunchText.includes("Alerts"), `${viewport.name}: dashboard alerts count missing`);
  assert(dashboardLaunchText.includes("Назначить"), `${viewport.name}: dashboard quick assignment missing`);
  await assertNoPageOverflow(page, `${viewport.name} dashboard`);

  const topActions = await page.locator(".top-actions").boundingBox();
  assert(topActions && topActions.width <= viewport.width, `${viewport.name}: top actions exceed viewport`);

  for (const tab of ["objects", "requests", "documents", "money", "reference", "readiness"]) {
    await page.click(`button[data-tab="${tab}"]`);
    await page.waitForSelector(`#tab-${tab}.active`, { timeout: 3000 });
    await assertNoPageOverflow(page, `${viewport.name} ${tab}`);
  }

  const text = await page.locator("body").textContent();
  assert(text.includes("Справочник требований"), `${viewport.name}: reference text missing`);
  assert(text.includes("Готовность запуска"), `${viewport.name}: readiness text missing`);
  assert(text.includes("Платежи и штрафы"), `${viewport.name}: money text missing`);

  await assertCalendarChatDetails(page, viewport.name);
  await assertReadinessDetails(page, viewport.name);
  await assertAccountCutoverDetails(page, viewport.name);
  await assertSacc2StatusDetails(page, viewport.name);
  await assertReferenceDetails(page, viewport.name);
  await assertAccessDetails(page, viewport.name);
}

const server = spawn(python, ["company_platform_server.py", "--port", String(port), "--db", db, "--backups", backups, "--quiet"], {
  cwd: "/Users/maxai/Documents/Codex/2026-05-22/files-mentioned-by-the-user-03",
  env: { ...process.env, QH_DEMO_PASSWORD: demoPassword, QH_SACC2_PUBLIC_URLS: "http://127.0.0.1:9000" },
  stdio: ["ignore", "pipe", "pipe"],
});

let browser;
try {
  await waitForHealth();
  browser = await chromium.launch({ headless: true, executablePath: chromePath });
  const checks = [];
  for (const viewport of viewports) {
    const page = await browser.newPage();
    const consoleErrors = [];
    const badResponses = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !msg.text().includes("Failed to load resource")) consoleErrors.push(msg.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(error.message));
    page.on("response", (response) => {
      const status = response.status();
      const responseUrl = response.url();
      if (status >= 400 && !responseUrl.endsWith("/favicon.ico")) {
        badResponses.push(`${status} ${responseUrl}`);
      }
    });
    await assertViewport(page, viewport);
    assert(consoleErrors.length === 0, `${viewport.name}: console errors: ${consoleErrors.join("; ")}`);
    assert(badResponses.length === 0, `${viewport.name}: bad responses: ${badResponses.join("; ")}`);
    checks.push(`${viewport.name} responsive render`);
    checks.push(`${viewport.name} dashboard launch status responsive render`);
    checks.push(`${viewport.name} calendar responsive render`);
    checks.push(`${viewport.name} chat AI responsive action`);
    checks.push(`${viewport.name} remaining work responsive render`);
    checks.push(`${viewport.name} QA evidence responsive render`);
    checks.push(`${viewport.name} status board responsive render`);
    checks.push(`${viewport.name} future roadmap responsive render`);
    checks.push(`${viewport.name} acceptance evidence responsive render`);
    checks.push(`${viewport.name} completion audit responsive render`);
    checks.push(`${viewport.name} account cutover responsive render`);
    checks.push(`${viewport.name} sacc2 public status responsive render`);
    checks.push(`${viewport.name} legal source registry responsive render`);
    checks.push(`${viewport.name} interaction map responsive render`);
    checks.push(`${viewport.name} access matrix responsive render`);
    await page.close();
  }
  console.log(JSON.stringify({ ok: true, checks }));
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
}
