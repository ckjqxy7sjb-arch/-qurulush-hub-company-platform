import { pathToFileURL } from "node:url";
import playwright from "/Users/maxai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;

const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = pathToFileURL(
  "/Users/maxai/Documents/Codex/2026-05-22/files-mentioned-by-the-user-03/extracted_dgask/04_Строительная_компания.html",
).toString();

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const browser = await chromium.launch({
  headless: true,
  executablePath: chromePath,
});

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto(appUrl, { waitUntil: "load" });
  await page.evaluate(() => localStorage.removeItem("qurulush_company_platform_v2"));
  await page.reload({ waitUntil: "load" });

  const initial = await page.evaluate(() => ({
    title: document.title,
    loginHidden: getComputedStyle(document.querySelector("#loginView")).display === "none",
    appVisible: !document.querySelector("#appShell").classList.contains("locked"),
    nav: document.querySelectorAll(".nav button").length,
    roles: document.querySelectorAll("#roleSelect option").length,
    objects: window.QurulushCompanyApp.getState().objects.length,
    reference: window.QurulushCompanyApp.getState().reference.length,
    requestsNeedingCompany: window.QurulushCompanyApp.getState().requests.filter((r) => r.status === "needs_company").length,
  }));
  assert(initial.title === "Кабинет строительной компании", "wrong page title");
  assert(initial.loginHidden && initial.appVisible, "file demo should open without HTTP login screen");
  assert(initial.nav === 12, "expected 12 navigation sections");
  assert(initial.roles === 6, "expected 6 company roles");
  assert(initial.objects === 3, "expected seeded objects");
  assert(initial.reference >= 8, "expected seeded reference catalog");
  assert(initial.requestsNeedingCompany === 2, "expected two open company requests");

  await page.click('button[data-tab="team"]');
  const accessMatrix = await page.evaluate(() => ({
    cells: document.querySelectorAll("#accessGrid > div").length,
    text: document.querySelector("#accessGrid").textContent,
  }));
  assert(accessMatrix.cells === 70, "access matrix should render 9 permissions for 6 roles");
  assert(accessMatrix.text.includes("Чтение документов"), "access matrix should show document read permission");
  assert(accessMatrix.text.includes("Загрузка документов"), "access matrix should show document upload permission");
  assert(accessMatrix.text.includes("ЭЦП"), "access matrix should show signing permission");
  assert(accessMatrix.text.includes("Поручения"), "access matrix should show task permission");
  await page.screenshot({ path: "company-platform-access-check.png", fullPage: true });

  await page.click("text=Права доступа");
  const rolePanelText = await page.locator("#detail").textContent();
  assert(rolePanelText.includes("Сменить пароль"), "role panel should expose password change action");
  assert(rolePanelText.includes("Экспорт пакета"), "role panel should expose exchange export action");
  assert(rolePanelText.includes("Синхронизация ДГАСК"), "role panel should expose sacc2 sync action");
  assert(rolePanelText.includes("Журнал аудита"), "role panel should expose audit action");
  assert(rolePanelText.includes("Готовность запуска"), "role panel should expose readiness action");
  await page.click("#detail .btn.secondary");

  await page.click('button[data-tab="audit"]');
  const auditText = await page.locator("#tab-audit").textContent();
  assert(auditText.includes("Журнал действий"), "audit tab should render");
  assert(auditText.includes("Изменён ответственный инспектор"), "audit tab should show seeded audit events");

  await page.click('button[data-tab="readiness"]');
  const readinessText = await page.locator("#tab-readiness").textContent();
  assert(readinessText.includes("Локальный контур"), "readiness tab should render local status");
  assert(readinessText.includes("Интеграция sacc2 / ДГАСК"), "readiness tab should list sacc2 gate");
  assert(readinessText.includes("Справочник требований"), "readiness tab should list reference catalog gate");
  assert(readinessText.includes("Активные сессии"), "readiness tab should expose session control action");
  await page.click("text=Активные сессии");
  await page.waitForTimeout(150);
  const sessionControlText = await page.locator("#sessionControl").textContent();
  assert(sessionControlText.includes("Очистить просроченные"), "session control should expose expired cleanup");
  assert(sessionControlText.includes("Завершить другие сессии"), "session control should expose other-session revoke");
  await page.click("text=План подключения");
  await page.waitForTimeout(150);
  const productionPlanText = await page.locator("#productionPlan").textContent();
  assert(productionPlanText.includes("План production-подключения"), "production plan should render");
  assert(productionPlanText.includes("QH_SACC2_API_URL"), "production plan should expose sacc2 settings");
  assert(productionPlanText.includes("Скачать Word"), "production plan should expose Word export");

  await page.click('button[data-tab="reference"]');
  const referenceText = await page.locator("#tab-reference").textContent();
  assert(referenceText.includes("Справочник требований"), "reference tab should render");
  assert(referenceText.includes("Рабочий каталог платформы"), "reference tab should show working catalog note");
  assert(referenceText.includes("Экспорт Word"), "reference tab should expose Word export");
  await page.selectOption("#referenceCategory", "Штрафы и нарушения");
  const filteredReference = await page.locator("#referenceBody").textContent();
  assert(filteredReference.includes("Протокол о нарушении / штраф"), "reference filter should show fines");
  assert(!filteredReference.includes("Разрешение на строительство"), "reference filter should hide other categories");
  await page.locator("#referenceBody tr", { hasText: "Протокол о нарушении / штраф" }).getByRole("button", { name: "Карточка" }).click();
  const referenceDetail = await page.locator("#detail").textContent();
  assert(referenceDetail.includes("Действие компании"), "reference detail should show company action");
  assert(referenceDetail.includes("Не является официальной правовой базой"), "reference detail should show source warning");
  await page.click("#detail .btn.secondary");

  await page.selectOption("#roleSelect", "brigadier");
  await page.click('button[data-tab="tasks"]');
  const brigadierTasks = await page.locator("#tasksBody").textContent();
  assert(brigadierTasks.includes("Фотофиксация устранения нарушений"), "brigadier should see assigned object task");
  assert(!brigadierTasks.includes("Подготовить акты скрытых работ"), "brigadier should not see task for another object");
  await page.locator("#tasksBody tr", { hasText: "Фотофиксация" }).getByRole("button", { name: "Карточка" }).click();
  await page.selectOption("#taskUpdateStatus", "done");
  await page.fill("#taskEvidence", "Фото и комментарий приложены.");
  await page.click("text=Сохранить статус");
  const updatedTask = await page.evaluate(() => window.QurulushCompanyApp.getState().tasks.find((t) => t.id === "TASK-2"));
  assert(updatedTask.status === "done", "brigadier should be able to close assigned task");

  await page.click('button[data-tab="requests"]');
  const brigadierCannotReply = await page.locator("#requestsBody button").first().isDisabled();
  assert(brigadierCannotReply, "brigadier must not be able to reply to DGASK requests");

  await page.selectOption("#roleSelect", "chief_engineer");
  await page.click("#requestsBody button");
  await page.fill("#replyText", "Документы приложены, просим принять ответ компании.");
  await page.click("text=Отправить ответ");
  const afterReply = await page.evaluate(() => ({
    req: window.QurulushCompanyApp.getState().requests.find((r) => r.id === "REQ-1048"),
    kpi: document.querySelector("#kpiRequests").textContent,
  }));
  assert(afterReply.req.status === "done", "reply should close the request");
  assert(afterReply.kpi === "1", "open request KPI should decrease after reply");

  await page.click('button[data-tab="documents"]');
  await page.locator("#docsBody tr", { hasText: "Проектная документация" }).getByRole("button", { name: "Карточка" }).click();
  const signPanelBefore = await page.locator("#detail").textContent();
  assert(signPanelBefore.includes("Подпись"), "document detail should show signature status");
  assert(signPanelBefore.includes("Подписать ЭЦП"), "document detail should expose signing action");
  await page.fill("#docFileName", "signed-project.pdf");
  await page.click("text=Загрузить новую версию");
  await page.locator("#docsBody tr", { hasText: "Проектная документация" }).getByRole("button", { name: "Карточка" }).click();
  await page.fill("#signatureComment", "Проверено главным инженером.");
  await page.click("text=Подписать ЭЦП");
  const signedDoc = await page.evaluate(() => window.QurulushCompanyApp.getState().docs.find((d) => d.id === "DOC-3"));
  assert(signedDoc.status === "Подписан", "chief engineer should be able to sign a document");
  assert(signedDoc.signature_status === "signed-local", "file demo signing should mark a local signature");

  await page.selectOption("#roleSelect", "accountant");
  await page.click('button[data-tab="money"]');
  await page.click("#moneyBody button:not([disabled])");
  await page.fill("#paymentNo", "UI-PAY-001");
  await page.click("text=Отметить оплачено");
  const payment = await page.evaluate(() => window.QurulushCompanyApp.getState().money.find((m) => m.id === "PAY-1"));
  assert(payment.status === "Оплачено", "accountant should be able to mark payment as paid");
  assert(payment.payment_no === "UI-PAY-001", "payment number should be saved");

  await page.selectOption("#roleSelect", "lawyer");
  await page.click('button[data-tab="money"]');
  await page.locator("#moneyBody tr", { hasText: "ЕРН" }).getByRole("button", { name: "Карточка" }).click();
  await page.fill("#appealText", "Просим пересмотреть начисление по тестовому сценарию.");
  await page.click("text=Обжаловать");
  const appealed = await page.evaluate(() => window.QurulushCompanyApp.getState().money.find((m) => m.id === "PAY-2"));
  assert(appealed.status === "Обжалуется", "lawyer should be able to appeal a fine or charge");

  await page.click('button[data-tab="requests"]');
  await page.click("text=Создать обращение");
  await page.fill("#newRequestTitle", "Тестовое обращение компании");
  await page.fill("#newRequestText", "Просим принять тестовое обращение и назначить ответственного специалиста.");
  await page.click("text=Отправить обращение");
  const created = await page.evaluate(() => window.QurulushCompanyApp.getState().requests[0]);
  assert(created.title === "Тестовое обращение компании", "new company request was not created");
  assert(created.status === "review", "new company request should be under review");

  await page.selectOption("#roleSelect", "ceo");
  await page.click('button[data-tab="requests"]');
  await page.click("text=Импорт из ДГАСК");
  await page.fill("#externalTitle", "Тестовый импорт ДГАСК");
  await page.fill("#externalText", "Импортированный запрос должен попасть в очередь компании.");
  await page.click("text=Импортировать запрос");
  const imported = await page.evaluate(() => window.QurulushCompanyApp.getState().requests[0]);
  assert(imported.title === "Тестовый импорт ДГАСК", "external request was not imported");
  assert(imported.from === "ДГАСК", "external request should keep source");

  await page.reload({ waitUntil: "load" });
  const persisted = await page.evaluate(() => ({
    requestExists: window.QurulushCompanyApp.getState().requests.some((r) => r.title === "Тестовое обращение компании"),
    importedExists: window.QurulushCompanyApp.getState().requests.some((r) => r.title === "Тестовый импорт ДГАСК"),
    paid: window.QurulushCompanyApp.getState().money.find((m) => m.id === "PAY-1").status,
    taskDone: window.QurulushCompanyApp.getState().tasks.find((t) => t.id === "TASK-2").status,
  }));
  assert(persisted.requestExists, "created request should persist after reload");
  assert(persisted.importedExists, "imported request should persist after reload");
  assert(persisted.paid === "Оплачено", "payment status should persist after reload");
  assert(persisted.taskDone === "done", "task status should persist after reload");

  await page.screenshot({ path: "company-platform-functional-check.png", fullPage: true });
  console.log(JSON.stringify({
    ok: true,
    checks: [
      "initial render",
      "access matrix render",
      "password change action render",
      "exchange import action render",
      "audit screen render",
      "readiness screen render",
      "session control render",
      "production plan render",
      "reference catalog render and filter",
      "task role scoping",
      "task close with evidence",
      "role access restriction",
      "request reply and status update",
      "payment update",
      "payment number persistence",
      "fine appeal workflow",
      "new request creation",
      "external request import",
      "task persistence",
      "localStorage persistence",
    ],
  }));
} finally {
  await browser.close();
}
