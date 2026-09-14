import { createApp } from "./app.js";
import { env } from "./config/env.js";
import { startReminderJobs } from "./jobs/reminders.js";

const app = createApp();

app.listen(env.port, () => {
  console.log(`DGASK KR API listening on :${env.port}`);
  startReminderJobs();
});
