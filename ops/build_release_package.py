#!/usr/bin/env python3
"""Build a deployable Qurulush Hub company platform release package."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = "qurulush-hub-company-platform"
DEFAULT_INCLUDE_PATHS = (
    ".env.production.example",
    "README.md",
    "HANDOFF_STATUS.md",
    "PROJECT_EXPORT.md",
    "MOBILE_FIELD_APP_PLAN.md",
    "KG_PAYMENT_ORCHESTRATION_PLAN.md",
    "company_platform_server.py",
    "company_platform_server_smoke.mjs",
    "company_platform_responsive_smoke.mjs",
    "company_platform_accessibility_smoke.mjs",
    "RUN_COMPANY_PLATFORM.md",
    "READINESS_CHECKLIST.md",
    "TEST_REPORT_COMPANY_PLATFORM.md",
    "extracted_dgask",
    "ops/README_PRODUCTION.md",
    "ops/backup_restore_drill.py",
    "ops/build_release_package.py",
    "ops/completion_audit.py",
    "ops/go_no_go_check.py",
    "ops/collect_acceptance_evidence.py",
    "ops/deployment_audit.py",
    "ops/hook_contract_smoke.py",
    "ops/hook_examples",
    "ops/render_deployment_files.py",
    "ops/release_acceptance_check.py",
    "ops/production_smoke_check.py",
    "ops/qurulush-hub.service.example",
    "ops/nginx-qurulush-hub.conf.example",
)
EXCLUDED_PARTS = {"__pycache__", "uploads", "backups", "outputs", "dist", ".git", ".agents", ".codex"}
EXCLUDED_SUFFIXES = {".pyc", ".sqlite3", ".db", ".log", ".png", ".jpg", ".jpeg", ".pdf"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_release_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def collect_release_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for item in DEFAULT_INCLUDE_PATHS:
        path = root / item
        if path.is_file() and is_release_file(path, root):
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(child for child in path.rglob("*") if is_release_file(child, root)))
    return sorted(set(files), key=lambda p: p.relative_to(root).as_posix())


def build_manifest(files: list[Path], root: Path = ROOT) -> dict[str, Any]:
    return {
        "format": "qurulush-release-manifest-v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "file_count": len(files),
        "excludes": sorted(EXCLUDED_PARTS | {f"*{suffix}" for suffix in EXCLUDED_SUFFIXES}),
        "files": [
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
        ],
    }


def build_release(output_dir: Path, root: Path = ROOT, name: str | None = None) -> tuple[Path, Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    package_name = name or f"qurulush-hub-company-platform-{timestamp}.zip"
    if not package_name.endswith(".zip"):
        package_name += ".zip"
    package_path = output_dir / package_name
    manifest_path = output_dir / package_name.replace(".zip", ".manifest.json")
    files = collect_release_files(root)
    manifest = build_manifest(files, root)

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in files:
            package.write(path, f"{RELEASE_DIR}/{path.relative_to(root).as_posix()}")
        package.writestr(
            f"{RELEASE_DIR}/RELEASE_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    current_package = output_dir / "qurulush-hub-company-platform-current.zip"
    current_manifest = output_dir / "qurulush-hub-company-platform-current.manifest.json"
    shutil.copy2(package_path, current_package)
    shutil.copy2(manifest_path, current_manifest)
    return package_path, manifest_path, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a deployable Qurulush Hub release zip")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--name", default=None, help="Optional package filename")
    args = parser.parse_args(argv)
    package_path, manifest_path, manifest = build_release(args.output_dir, ROOT, args.name)
    print(
        json.dumps(
            {
                "ok": True,
                "package": str(package_path),
                "manifest": str(manifest_path),
                "current_package": str(args.output_dir / "qurulush-hub-company-platform-current.zip"),
                "current_manifest": str(args.output_dir / "qurulush-hub-company-platform-current.manifest.json"),
                "file_count": manifest["file_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
