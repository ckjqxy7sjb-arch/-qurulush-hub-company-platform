import { readdir, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { pool, withTransaction } from "./pool.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const migrationsDir = join(__dirname, "../../migrations");

async function ensureMigrationsTable(client) {
  await client.query(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      id TEXT PRIMARY KEY,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `);
}

async function migrate() {
  const files = (await readdir(migrationsDir)).filter((file) => file.endsWith(".sql")).sort();
  await withTransaction(async (client) => {
    await ensureMigrationsTable(client);
    const applied = await client.query("SELECT id FROM schema_migrations");
    const done = new Set(applied.rows.map((row) => row.id));
    for (const file of files) {
      if (done.has(file)) continue;
      const sql = await readFile(join(migrationsDir, file), "utf8");
      await client.query(sql);
      await client.query("INSERT INTO schema_migrations (id) VALUES ($1)", [file]);
      console.log(`applied ${file}`);
    }
  });
}

migrate()
  .then(() => pool.end())
  .catch((error) => {
    console.error(error);
    pool.end().finally(() => process.exit(1));
  });
