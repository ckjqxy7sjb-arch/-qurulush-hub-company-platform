import bcrypt from "bcryptjs";
import { pool, withTransaction } from "./pool.js";

const demoPassword = process.env.DGASK_DEMO_PASSWORD || "ChangeMe2026!";

async function seed() {
  await withTransaction(async (client) => {
    const company = await client.query(
      `INSERT INTO companies (name, inn)
       VALUES ('Строительная компания', '00000000000000')
       ON CONFLICT (inn) DO UPDATE SET name = excluded.name
       RETURNING id`,
    );
    const companyId = company.rows[0]?.id || (await client.query("SELECT id FROM companies LIMIT 1")).rows[0].id;
    const passwordHash = await bcrypt.hash(demoPassword, 10);
    const users = [
      ["director@company.kg", "Генеральный директор", "director"],
      ["engineer@company.kg", "Главный инженер", "chief_engineer"],
      ["foreman@company.kg", "Прораб", "foreman"],
      ["brigadier@company.kg", "Бригадир", "brigadier"],
      ["accountant@company.kg", "Бухгалтер", "accountant"],
      ["lawyer@company.kg", "Юрист", "lawyer"],
    ];
    for (const [email, name, companyRole] of users) {
      await client.query(
        `INSERT INTO users (company_id, email, name, role, company_role, password_hash)
         VALUES ($1, $2, $3, 'company', $4, $5)
         ON CONFLICT (email) DO NOTHING`,
        [companyId, email, name, companyRole, passwordHash],
      );
    }
    const object = await client.query(
      `INSERT INTO construction_objects (company_id, name, address, current_stage, external_ref)
       VALUES ($1, 'Объект компании 1', 'Укажите адрес объекта', 'В работе', 'demo-object-1')
       ON CONFLICT (company_id, external_ref) DO UPDATE SET updated_at = now()
       RETURNING id`,
      [companyId],
    );
    const objectId = object.rows[0].id;
    const notification = await client.query(
      `INSERT INTO notifications (company_id, object_id, source, source_ref, type, title, body, status, urgent, due_at)
       VALUES ($1, $2, 'sacc2 / Минстрой', 'demo-notification-1', 'request', 'Входящее уведомление', 'Требуется ответ компании с документом или комментарием.', 'needs_company', true, current_date + 3)
       ON CONFLICT (company_id, source_ref) DO UPDATE SET updated_at = now()
       RETURNING id`,
      [companyId, objectId],
    );
    await client.query(
      `INSERT INTO payments (company_id, notification_id, object_id, title, basis, amount, status, due_at)
       VALUES ($1, $2, $3, 'Начисление по уведомлению', 'Оплата после входящего уведомления', 0, 'pending', current_date + 5)`,
      [companyId, notification.rows[0].id, objectId],
    );
    await client.query(
      `INSERT INTO documents (company_id, notification_id, object_id, title, description, status, due_at)
       VALUES ($1, $2, $3, 'Ответный документ', 'Файл для отправки в ведомственный контур', 'required', current_date + 3)`,
      [companyId, notification.rows[0].id, objectId],
    );
    await client.query(
      `INSERT INTO chat_messages (company_id, author_type, body)
       VALUES ($1, 'assistant', 'Я помогу разобрать уведомление, оплату, документ или срок.')`,
      [companyId],
    );
  });
}

seed()
  .then(() => {
    console.log("seed complete");
    return pool.end();
  })
  .catch((error) => {
    console.error(error);
    pool.end().finally(() => process.exit(1));
  });
