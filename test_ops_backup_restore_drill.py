from __future__ import annotations

import tempfile
import unittest
import json
import sqlite3
from pathlib import Path

from company_platform_server import create_sqlite_backup, init_db, load_state, save_state, sha256_file
from ops.backup_restore_drill import choose_backup, run_restore_drill


class BackupRestoreDrillTest(unittest.TestCase):
    def test_restore_drill_restores_backup_into_isolated_temp_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "company.sqlite3"
            backup_root = root / "backups"
            init_db(db_path)
            state = load_state(db_path)
            state["requests"].append(
                {
                    "id": "REQ-DRILL",
                    "title": "Контрольный запрос для restore drill",
                    "status": "needs_company",
                    "object": 1,
                }
            )
            save_state(state, db_path)
            backup = create_sqlite_backup(db_path, backup_root, "Unit test")

            result = run_restore_drill(backup_root, backup["file"])

            self.assertTrue(result["ok"])
            self.assertEqual(result["file"], backup["file"])
            self.assertEqual(result["source_integrity"], "PRAGMA quick_check: ok")
            self.assertEqual(result["restored_integrity"], "PRAGMA quick_check: ok")
            self.assertEqual(len(result["sha256"]), 64)
            self.assertEqual(result["backup_counts"]["requests"], len(state["requests"]))
            self.assertEqual(result["restored_counts"]["requests"], len(state["requests"]))
            self.assertTrue(result["temp_database_removed"])

    def test_choose_backup_rejects_empty_backup_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "no backups available"):
                choose_backup(Path(tmp))

    def test_restore_drill_marks_schema_defaults_filled_for_legacy_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "company.sqlite3"
            backup_root = root / "backups"
            init_db(db_path)
            backup = create_sqlite_backup(db_path, backup_root, "Legacy unit test")
            backup_path = backup_root / backup["file"]
            manifest_path = backup_path.with_suffix(".json")

            with sqlite3.connect(backup_path) as conn:
                row = conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
                payload = json.loads(row[0])
                payload.pop("tasks", None)
                conn.execute("UPDATE app_state SET payload = ? WHERE id = 1", (json.dumps(payload, ensure_ascii=False),))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["sha256"] = sha256_file(backup_path)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            result = run_restore_drill(backup_root, backup["file"])

            self.assertEqual(result["backup_counts"]["tasks"], 0)
            self.assertGreater(result["restored_counts"]["tasks"], 0)
            self.assertEqual(result["migration_filled"]["tasks"], result["restored_counts"]["tasks"])


if __name__ == "__main__":
    unittest.main()
