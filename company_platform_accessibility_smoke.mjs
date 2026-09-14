import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import playwright from "/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;
const python = "/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";
const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const port = 8793;
const tempRoot = mkdtempSync(join(tmpdir(), "qurulush-a11y-"));
const db = join(tempRoot, "a11y.sqlite3");
const backups = join(tempRoot, "backups");
const url = `http://127.0.0.1:${port}/04_%D0%A1%D1%82%D1%80%D0%BE%D0%B8%D1%82%D0%B5%D0%BB%D1%8C%D0%BD%D0%B0%D1%8F_%D0%BA%D0%BE%D0%BC%D0%BF%D0%B0%D0%BD%D0%B8%D1%8F.html`;
const demoPassword = `test-${Date.now()}-${Math.random().toString(36).slice(2)}!`;

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

const server = spawn(python, ["company_platform_server.py", "--port", String(port), "--db", db, "--backups", backups, "--quiet"], {
  cwd: "/Users/maxai/Documents/Codex/2026-05-22/files-mentioned-by-the-user-03",
  env: { ...process.env, QH_DEMO_PASSWORD: demoPassword },
  stdio: ["ignore", "pipe", "pipe"],
});

let browser;
try {
  await waitForHealth();
  browser = await chromium.launch({ headless: true, executablePath: chromePath });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(url, { waitUntil: "load" });

  const loginSemantics = await page.evaluate(() => ({
    regionLabel: document.querySelector("#loginView")?.getAttribute("aria-labelledby"),
    titleText: document.querySelector("#loginTitle")?.textContent,
    emailLabelFor: document.querySelector('label[for="loginEmail"]')?.textContent,
    passwordLabelFor: document.querySelector('label[for="loginPassword"]')?.textContent,
    errorRole: document.querySelector("#loginError")?.getAttribute("role"),
    errorLive: document.querySelector("#loginError")?.getAttribute("aria-live"),
  }));
  assert(loginSemantics.regionLabel === "loginTitle", "login view should be labelled by title");
  assert(loginSemantics.titleText.includes("Вход"), "login title should be present");
  assert(loginSemantics.emailLabelFor === "Email", "email input should have explicit label");
  assert(loginSemantics.passwordLabelFor === "Пароль", "password input should have explicit label");
  assert(loginSemantics.errorRole === "alert", "login error should be alert");
  assert(loginSemantics.errorLive === "assertive", "login error should be assertive live region");

  await page.focus("#loginEmail");
  await page.keyboard.type("director@company.kg");
  await page.keyboard.press("Tab");
  await page.keyboard.type(demoPassword);
  await page.keyboard.press("Enter");
  await page.waitForSelector("#appShell:not(.locked)", { timeout: 5000 });

  const appSemantics = await page.evaluate(() => ({
    navLabel: document.querySelector("#nav")?.getAttribute("aria-label"),
    mainTabIndex: document.querySelector("#mainContent")?.getAttribute("tabindex"),
    roleLabel: document.querySelector('label[for="roleSelect"]')?.textContent,
    roleAria: document.querySelector("#roleSelect")?.getAttribute("aria-label"),
    userLive: document.querySelector("#currentUserBadge")?.getAttribute("aria-live"),
    activeNavCount: document.querySelectorAll("#nav button[aria-current='page']").length,
    activeNavText: document.querySelector("#nav button[aria-current='page'] span")?.textContent,
  }));
  assert(appSemantics.navLabel === "Рабочие разделы", "navigation should have aria-label");
  assert(appSemantics.mainTabIndex === "-1", "main content should be programmatically focusable");
  assert(appSemantics.roleLabel === "Роль пользователя", "role select should have hidden label");
  assert(appSemantics.roleAria === "Роль пользователя", "role select should have aria label");
  assert(appSemantics.userLive === "polite", "current user badge should be a polite live region");
  assert(appSemantics.activeNavCount === 1, "exactly one nav item should expose aria-current");
  assert(appSemantics.activeNavText === "Обзор", "dashboard should be current after login");

  await page.click('button[data-tab="readiness"]');
  const readinessSemantics = await page.evaluate(() => ({
    activeNavText: document.querySelector("#nav button[aria-current='page'] span")?.textContent,
    mainLabel: document.querySelector("#mainContent")?.getAttribute("aria-label"),
  }));
  assert(readinessSemantics.activeNavText === "Готовность", "readiness nav should become current");
  assert(readinessSemantics.mainLabel === "Готовность", "main label should follow active tab");

  await page.click("#primaryAction");
  await page.waitForSelector("#toast.show", { timeout: 3000 });
  const toastSemantics = await page.evaluate(() => ({
    role: document.querySelector("#toast")?.getAttribute("role"),
    live: document.querySelector("#toast")?.getAttribute("aria-live"),
    text: document.querySelector("#toast")?.textContent,
  }));
  assert(toastSemantics.role === "status", "toast should use status role");
  assert(toastSemantics.live === "polite", "toast should be a polite live region");
  assert(toastSemantics.text.length > 0, "toast should announce text");

  console.log(JSON.stringify({ ok: true, checks: ["login labels", "keyboard login", "landmarks", "active nav aria-current", "toast live region"] }));
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
}
