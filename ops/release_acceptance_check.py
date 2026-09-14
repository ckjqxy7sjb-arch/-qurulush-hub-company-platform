#!/usr/bin/env python3
"""Validate that a release zip can be unpacked and preflighted."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


RELEASE_DIR = "qurulush-hub-company-platform"
REQUIRED_FILES = {
    f"{RELEASE_DIR}/.env.production.example",
    f"{RELEASE_DIR}/HANDOFF_STATUS.md",
    f"{RELEASE_DIR}/PROJECT_EXPORT.md",
    f"{RELEASE_DIR}/MOBILE_FIELD_APP_PLAN.md",
    f"{RELEASE_DIR}/KG_PAYMENT_ORCHESTRATION_PLAN.md",
    f"{RELEASE_DIR}/company_platform_server.py",
    f"{RELEASE_DIR}/company_platform_server_smoke.mjs",
    f"{RELEASE_DIR}/company_platform_responsive_smoke.mjs",
    f"{RELEASE_DIR}/company_platform_accessibility_smoke.mjs",
    f"{RELEASE_DIR}/extracted_dgask/04_Строительная_компания.html",
    f"{RELEASE_DIR}/ops/README_PRODUCTION.md",
    f"{RELEASE_DIR}/ops/backup_restore_drill.py",
    f"{RELEASE_DIR}/ops/completion_audit.py",
    f"{RELEASE_DIR}/ops/collect_acceptance_evidence.py",
    f"{RELEASE_DIR}/ops/go_no_go_check.py",
    f"{RELEASE_DIR}/ops/deployment_audit.py",
    f"{RELEASE_DIR}/ops/hook_contract_smoke.py",
    f"{RELEASE_DIR}/ops/hook_examples/sacc2_sync_contract_example.py",
    f"{RELEASE_DIR}/ops/hook_examples/av_scan_contract_example.py",
    f"{RELEASE_DIR}/ops/render_deployment_files.py",
    f"{RELEASE_DIR}/ops/production_smoke_check.py",
    f"{RELEASE_DIR}/ops/build_release_package.py",
    f"{RELEASE_DIR}/ops/release_acceptance_check.py",
    f"{RELEASE_DIR}/RELEASE_MANIFEST.json",
}
BANNED_PARTS = {"/uploads/", "/backups/", "/outputs/", "/__pycache__/", "/dist/"}
BANNED_SUFFIXES = (".sqlite3", ".db", ".pyc", ".png", ".jpg", ".jpeg", ".pdf")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inspect_package(package_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(package_path) as package:
        names = set(package.namelist())
        missing = sorted(REQUIRED_FILES - names)
        banned = sorted(
            name
            for name in names
            if any(part in f"/{name}" for part in BANNED_PARTS) or name.lower().endswith(BANNED_SUFFIXES)
        )
        manifest = json.loads(package.read(f"{RELEASE_DIR}/RELEASE_MANIFEST.json").decode("utf-8"))
        manifest_entries = manifest.get("files", [])
        manifest_names = {f"{RELEASE_DIR}/{item.get('path')}" for item in manifest_entries}
        expected_names = manifest_names | {f"{RELEASE_DIR}/RELEASE_MANIFEST.json"}
        extra = sorted(name for name in names - expected_names if not name.endswith("/"))
        checksum_errors: list[str] = []
        for item in manifest_entries:
            archive_name = f"{RELEASE_DIR}/{item.get('path')}"
            if archive_name not in names:
                checksum_errors.append(f"{archive_name}: missing from zip")
                continue
            raw = package.read(archive_name)
            if len(raw) != item.get("size"):
                checksum_errors.append(f"{archive_name}: size mismatch")
            if sha256_bytes(raw) != item.get("sha256"):
                checksum_errors.append(f"{archive_name}: sha256 mismatch")
    return {
        "file_count": len(names),
        "manifest_file_count": manifest.get("file_count"),
        "missing": missing,
        "banned": banned,
        "extra": extra,
        "checksum_errors": checksum_errors,
    }


def accept_release_package(package_path: Path, work_dir: Path, python_executable: str = sys.executable) -> dict[str, Any]:
    package_path = package_path.resolve()
    inspection = inspect_package(package_path)
    if inspection["missing"]:
        raise RuntimeError("release package is missing required files: " + ", ".join(inspection["missing"]))
    if inspection["banned"]:
        raise RuntimeError("release package contains runtime files: " + ", ".join(inspection["banned"]))
    if inspection["extra"]:
        raise RuntimeError("release package contains files outside manifest: " + ", ".join(inspection["extra"]))
    if inspection["checksum_errors"]:
        raise RuntimeError("release package manifest verification failed: " + "; ".join(inspection["checksum_errors"]))

    extract_root = work_dir / "extract"
    runtime_root = work_dir / "runtime"
    extract_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path) as package:
        package.extractall(extract_root)

    release_root = extract_root / RELEASE_DIR
    env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }

    compile_result = subprocess.run(
        [
            python_executable,
            "-m",
            "py_compile",
            "company_platform_server.py",
            "ops/backup_restore_drill.py",
            "ops/completion_audit.py",
            "ops/collect_acceptance_evidence.py",
            "ops/go_no_go_check.py",
            "ops/deployment_audit.py",
            "ops/hook_contract_smoke.py",
            "ops/render_deployment_files.py",
            "ops/hook_examples/sacc2_sync_contract_example.py",
            "ops/hook_examples/eds_sign_contract_example.py",
            "ops/hook_examples/payment_confirm_contract_example.py",
            "ops/hook_examples/storage_sync_contract_example.py",
            "ops/hook_examples/av_scan_contract_example.py",
            "ops/hook_examples/backup_remote_contract_example.py",
            "ops/production_smoke_check.py",
            "ops/build_release_package.py",
            "ops/release_acceptance_check.py",
        ],
        cwd=release_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if compile_result.returncode != 0:
        raise RuntimeError("release python compile failed: " + (compile_result.stderr or compile_result.stdout).strip())

    preflight_result = subprocess.run(
        [
            python_executable,
            "company_platform_server.py",
            "--preflight",
            "--db",
            str(runtime_root / "company.sqlite3"),
            "--uploads",
            str(runtime_root / "uploads"),
            "--backups",
            str(runtime_root / "backups"),
        ],
        cwd=release_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if preflight_result.returncode != 0:
        raise RuntimeError("release preflight failed: " + (preflight_result.stderr or preflight_result.stdout).strip())
    if "local_ready: yes" not in preflight_result.stdout:
        raise RuntimeError("release preflight did not confirm local_ready")

    audit_result = subprocess.run(
        [
            python_executable,
            "ops/deployment_audit.py",
            "--root",
            str(release_root),
        ],
        cwd=release_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if audit_result.returncode != 0:
        raise RuntimeError("release deployment audit failed: " + (audit_result.stderr or audit_result.stdout).strip())

    return {
        "ok": True,
        "package": str(package_path),
        "file_count": inspection["file_count"],
        "manifest_file_count": inspection["manifest_file_count"],
        "checks": ["required files", "runtime exclusions", "manifest sha256", "python compile", "local preflight", "deployment audit"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Qurulush Hub release zip")
    parser.add_argument("package", type=Path)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        result = accept_release_package(args.package, Path(tmp))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
