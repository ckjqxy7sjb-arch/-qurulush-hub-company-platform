import cron from "node-cron";
import { env } from "../config/env.js";
import { query } from "../db/pool.js";

async function createReminderAudit(action) {
  await query(
    `INSERT INTO audit_log (action, entity_type, form_data)
     VALUES ($1, 'system_reminder', $2::jsonb)`,
    [action, JSON.stringify({ tz: env.cronTz })],
  );
}

export function startReminderJobs() {
  cron.schedule(
    "0 16 * * 5",
    () => createReminderAudit("weekly_inspector_deadline_reminder").catch(console.error),
    { timezone: env.cronTz },
  );

  cron.schedule(
    "0 17 28-31 * *",
    () => createReminderAudit("month_end_open_notification_reminder").catch(console.error),
    { timezone: env.cronTz },
  );
}
