#!/usr/bin/env python3
"""Collect a sanitized acceptance evidence JSON for Qurulush Hub."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from company_platform_server import utc_now  # noqa: E402
from ops.backup_restore_drill import run_restore_drill  # noqa: E402
from ops.go_no_go_check import build_go_no_go_result, run_live_smoke, run_release_acceptance, run_stage  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "outputs"
UNSAFE_MARKERS = ("token_hash", "official-sacc2-key-2026", "stored_file")


def scrub_secrets(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        return {str(key): scrub_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_secrets(item, secrets) for item in value]
    if isinstance(value, str):
        cleaned = value
        for secret in secrets:
            if secret:
                cleaned = cleaned.replace(secret, "REDACTED")
        return cleaned
    return value


def redacted_command(parts: list[str], secrets: list[str]) -> str:
    return " ".join(str(scrub_secrets(part, secrets)) for part in parts)


def assert_sanitized(payload: dict[str, Any], secrets: list[str]) -> None:
    exported = json.dumps(payload, ensure_ascii=False).lower()
    unsafe = [secret for secret in secrets if secret and secret.lower() in exported]
    unsafe.extend(marker for marker in UNSAFE_MARKERS if marker in exported)
    if unsafe:
        raise RuntimeError("acceptance evidence contains unsafe data: " + ", ".join(sorted(set(unsafe))))


def collect_acceptance_evidence(
    *,
    release: Path | None = None,
    base_url: str | None = None,
    email: str | None = None,
    password: str | None = None,
    backups: Path | None = None,
    backup_file: str | None = None,
    require_production: bool = False,
) -> dict[str, Any]:
    secrets = [password or ""]
    stages: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []

    if release:
        stages.append(run_stage("release_acceptance", lambda: run_release_acceptance(release)))
        commands.append(
            {
                "id": "release_acceptance",
                "command": redacted_command(["python3", "ops/release_acceptance_check.py", str(release)], secrets),
            }
        )

    if base_url:
        if not email or not password:
            stages.append({"name": "live_smoke", "ok": False, "error": "--email and --password are required with --base-url"})
        else:
            stages.append(run_stage("live_smoke", lambda: run_live_smoke(base_url, email, password, require_production)))
        command = ["python3", "ops/production_smoke_check.py", "--base-url", base_url, "--email", email or "OWNER_EMAIL", "--password", password or "REAL_PASSWORD"]
        if require_production:
            command.append("--require-production")
        commands.append({"id": "live_smoke", "command": redacted_command(command, secrets)})

    if backups:
        stages.append(run_stage("backup_restore_drill", lambda: run_restore_drill(backups, backup_file)))
        command = ["python3", "ops/backup_restore_drill.py", str(backups)]
        if backup_file:
            command.extend(["--backup-file", backup_file])
        commands.append({"id": "backup_restore_drill", "command": redacted_command(command, secrets)})

    if not stages:
        stages.append({"name": "configuration", "ok": False, "error": "provide at least one of --release, --base-url, or --backups"})

    result = build_go_no_go_result(scrub_secrets(deepcopy(stages), secrets))
    payload = {
        "format": "qurulush-acceptance-evidence-v1",
        "generated_at": utc_now(),
        "ok": bool(result.get("ok")),
        "require_production": bool(require_production),
        "failed_stages": result.get("failed_stages", []),
        "stage_count": len(stages),
        "commands": commands,
        "go_no_go": result,
        "artifacts": [
            {"id": "release_zip", "path": str(release) if release else "", "type": "file"},
            {"id": "working_url", "path": base_url.rstrip("/") + "/04_Строительная_компания.html" if base_url else "", "type": "url"},
            {"id": "current_evidence", "path": "outputs/acceptance-evidence-current.json", "type": "file"},
        ],
        "next_step": (
            "Production evidence is complete. Store this JSON with the director acceptance record."
            if result.get("ok") and require_production
            else "Local evidence is complete. Close external production gates, then rerun with --require-production."
            if result.get("ok")
            else "Fix failed stages and rerun evidence collection."
        ),
    }
    assert_sanitized(payload, secrets)
    return payload


def write_evidence_files(payload: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(payload.get("generated_at") or utc_now()).replace(":", "").replace(" ", "_").replace("-", "")
    timestamped = output_dir / f"acceptance-evidence-{stamp}.json"
    current = output_dir / "acceptance-evidence-current.json"
    raw = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    timestamped.write_text(raw, encoding="utf-8")
    current.write_text(raw, encoding="utf-8")
    return timestamped, current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect sanitized Qurulush Hub acceptance evidence")
    parser.add_argument("--release", type=Path, help="Release zip to validate")
    parser.add_argument("--base-url", help="Live platform URL for smoke-check")
    parser.add_argument("--email", help="Director/bootstrap admin email for live smoke-check")
    parser.add_argument("--password", help="Director/bootstrap admin password for live smoke-check")
    parser.add_argument("--backups", type=Path, help="Backup directory for restore drill")
    parser.add_argument("--backup-file", help="Optional backup .sqlite3 filename")
    parser.add_argument("--require-production", action="store_true", help="Require production_ready=true during live smoke-check")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    payload = collect_acceptance_evidence(
        release=args.release,
        base_url=args.base_url,
        email=args.email,
        password=args.password,
        backups=args.backups,
        backup_file=args.backup_file,
        require_production=args.require_production,
    )
    timestamped, current = write_evidence_files(payload, args.output_dir)
    print(json.dumps({"ok": payload["ok"], "output": str(timestamped), "current": str(current), "failed_stages": payload["failed_stages"]}, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
