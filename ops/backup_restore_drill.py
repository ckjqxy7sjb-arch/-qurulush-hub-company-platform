#!/usr/bin/env python3
"""Run an isolated restore drill for Qurulush Hub SQLite backups."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from company_platform_server import (  # noqa: E402
    init_db,
    list_sqlite_backups,
    load_state,
    normalize_money_records,
    normalize_team_assignments,
    public_state_payload,
    save_state,
    sqlite_integrity_status,
    utc_now,
    verify_backup_for_restore,
)


def state_counts(state: dict[str, Any]) -> dict[str, int]:
    return {
        "objects": len(state.get("objects", [])),
        "requests": len(state.get("requests", [])),
        "tasks": len(state.get("tasks", [])),
        "documents": len(state.get("documents", state.get("docs", []))),
        "audit": len(state.get("audit", [])),
    }


def payload_count_keys(payload: dict[str, Any]) -> set[str]:
    keys = {"objects", "requests", "tasks", "audit"} & set(payload)
    if "documents" in payload or "docs" in payload:
        keys.add("documents")
    return keys


def read_backup_payload(backup_file: Path) -> dict[str, Any]:
    with sqlite3.connect(backup_file) as backup_conn:
        row = backup_conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if not row:
        raise RuntimeError("backup has no app_state payload")
    payload = json.loads(row[0])
    if not isinstance(payload, dict):
        raise RuntimeError("backup app_state payload is not an object")
    return payload


def choose_backup(backup_root: Path, file_name: str | None = None) -> str:
    if file_name:
        return file_name
    backups = list_sqlite_backups(backup_root)
    if not backups:
        raise RuntimeError("no backups available for restore drill")
    return str(backups[0]["file"])


def run_restore_drill(backup_root: Path, file_name: str | None = None) -> dict[str, Any]:
    selected_file = choose_backup(backup_root, file_name)
    verified = verify_backup_for_restore(backup_root, selected_file)
    backup_file = (backup_root / selected_file).resolve()
    payload = read_backup_payload(backup_file)

    with tempfile.TemporaryDirectory(prefix="qurulush-restore-drill-") as tmp:
        runtime_root = Path(tmp)
        temp_db = runtime_root / "restore-drill.sqlite3"
        init_db(temp_db)
        restored_state = public_state_payload()
        restored_state.update(payload)
        restored_state.pop("users", None)
        normalize_team_assignments(restored_state)
        normalize_money_records(restored_state)
        save_state(restored_state, temp_db)

        integrity_ok, integrity_detail = sqlite_integrity_status(temp_db)
        if not integrity_ok:
            raise RuntimeError("restored temp database integrity failed: " + integrity_detail)
        loaded_state = load_state(temp_db)
        backup_counts = dict(verified["counts"])
        restored_counts = state_counts(loaded_state)
        comparable_keys = payload_count_keys(payload)
        mismatches = {
            key: {"backup": backup_counts[key], "restored": restored_counts[key]}
            for key in comparable_keys
            if backup_counts.get(key) != restored_counts.get(key)
        }
        if mismatches:
            raise RuntimeError(f"restored counts mismatch: {mismatches}")
        migration_filled = {
            key: restored_counts[key]
            for key in restored_counts
            if key not in comparable_keys and restored_counts[key] != backup_counts.get(key)
        }

    return {
        "ok": True,
        "checked_at": utc_now(),
        "file": selected_file,
        "sha256": verified["sha256"],
        "source_integrity": verified["integrity"],
        "restored_integrity": integrity_detail,
        "backup_counts": backup_counts,
        "restored_counts": restored_counts,
        "migration_filled": migration_filled,
        "temp_database_removed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify that the latest Qurulush Hub SQLite backup can be restored into an isolated temp database")
    parser.add_argument("--backups", type=Path, default=ROOT / "backups", help="Backup directory")
    parser.add_argument("--file", default=None, help="Optional backup .sqlite3 filename; defaults to the latest backup")
    args = parser.parse_args(argv)
    result = run_restore_drill(args.backups, args.file)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
