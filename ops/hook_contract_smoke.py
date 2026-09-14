#!/usr/bin/env python3
"""Smoke-test external hook JSON contracts with safe dry-run payloads."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.deployment_audit import parse_env_file  # noqa: E402


HOOKS: tuple[dict[str, Any], ...] = (
    {
        "id": "sacc2",
        "command": "QH_SACC2_SYNC_CMD",
        "timeout": "QH_SACC2_SYNC_TIMEOUT_SECONDS",
        "allowed_statuses": {"ok", "synced"},
        "payload_name": "sacc2-payload.json",
        "payload": lambda env: {
            "format": "qurulush-hook-contract-smoke-v1",
            "target": "sacc2",
            "dry_run": True,
            "api_url": env.get("QH_SACC2_API_URL", ""),
            "submitted_by": "hook-contract-smoke",
        },
        "replacements": lambda env, paths: {"{payload}": str(paths["payload"]), "{api_url}": env.get("QH_SACC2_API_URL", "")},
        "append_if_missing": "{payload}",
    },
    {
        "id": "eds",
        "command": "QH_EDS_SIGN_CMD",
        "timeout": "QH_EDS_SIGN_TIMEOUT_SECONDS",
        "allowed_statuses": {"ok", "signed"},
        "payload_name": "eds-payload.json",
        "payload": lambda env: {
            "format": "qurulush-hook-contract-smoke-v1",
            "document_id": "DOC-SMOKE",
            "file_sha256": "0" * 64,
            "dry_run": True,
            "eds_provider": env.get("QH_EDS_PROVIDER", ""),
            "eds_api_url": env.get("QH_EDS_API_URL", ""),
            "submitted_by": "hook-contract-smoke",
        },
        "replacements": lambda env, paths: {"{payload}": str(paths["payload"]), "{document_id}": "DOC-SMOKE", "{eds_api_url}": env.get("QH_EDS_API_URL", "")},
        "append_if_missing": "{payload}",
    },
    {
        "id": "payment_gateway",
        "command": "QH_PAYMENT_GATEWAY_CMD",
        "timeout": "QH_PAYMENT_GATEWAY_TIMEOUT_SECONDS",
        "allowed_statuses": {"ok", "confirmed", "paid"},
        "payload_name": "payment-payload.json",
        "payload": lambda env: {
            "format": "qurulush-hook-contract-smoke-v1",
            "payment_id": "PAY-SMOKE",
            "payment_no": "DRY-RUN-PAYMENT",
            "amount": 1,
            "dry_run": True,
            "gateway_url": env.get("QH_PAYMENT_GATEWAY_URL", ""),
            "submitted_by": "hook-contract-smoke",
        },
        "replacements": lambda env, paths: {"{payload}": str(paths["payload"]), "{payment_id}": "PAY-SMOKE", "{payment_no}": "DRY-RUN-PAYMENT", "{gateway_url}": env.get("QH_PAYMENT_GATEWAY_URL", "")},
        "append_if_missing": "{payload}",
    },
    {
        "id": "storage",
        "command": "QH_STORAGE_SYNC_CMD",
        "timeout": "QH_STORAGE_SYNC_TIMEOUT_SECONDS",
        "allowed_statuses": {"ok", "stored", "uploaded", "synced"},
        "file_name": "storage-smoke.txt",
        "file_body": "qurulush storage smoke\n",
        "replacements": lambda env, paths: {
            "{file}": str(paths["file"]),
            "{doc_id}": "DOC-SMOKE",
            "{filename}": "storage-smoke.txt",
            "{storage_url}": env.get("QH_STORAGE_URL", ""),
        },
        "append_if_missing": "{file}",
    },
    {
        "id": "av_scanner",
        "command": "QH_AV_SCANNER",
        "timeout": "QH_AV_SCAN_TIMEOUT_SECONDS",
        "allowed_statuses": {"ok", "clean"},
        "file_name": "av-smoke.txt",
        "file_body": "qurulush av smoke\n",
        "replacements": lambda env, paths: {"{file}": str(paths["file"])},
        "append_if_missing": "{file}",
    },
    {
        "id": "backup_remote",
        "command": "QH_BACKUP_REMOTE_CMD",
        "timeout": "QH_BACKUP_REMOTE_TIMEOUT_SECONDS",
        "allowed_statuses": {"ok", "stored", "uploaded", "synced"},
        "backup_name": "backup-smoke.sqlite3",
        "manifest_name": "backup-smoke.json",
        "replacements": lambda env, paths: {"{backup}": str(paths["backup"]), "{manifest}": str(paths["manifest"]), "{remote_url}": env.get("QH_BACKUP_REMOTE_URL", "")},
        "append_if_missing": "{backup}",
    },
)


def timeout_from_env(env: dict[str, str], name: str, default: int = 30) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


def command_from_env(env: dict[str, str], name: str) -> list[str]:
    raw = env.get(name, "").strip()
    if not raw:
        raise RuntimeError(f"{name} is required")
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} is not valid shell-like command syntax") from exc
    if not command:
        raise RuntimeError(f"{name} is empty")
    executable = command[0]
    candidate = Path(executable).expanduser() if Path(executable).name != executable else None
    if candidate and not candidate.is_file():
        raise RuntimeError(f"{name} executable not found: {executable}")
    if candidate and not os.access(candidate, os.X_OK):
        raise RuntimeError(f"{name} executable is not executable: {executable}")
    if not candidate and not shutil.which(executable):
        raise RuntimeError(f"{name} executable not found in PATH: {executable}")
    return command


def prepare_paths(hook: dict[str, Any], work_dir: Path, env: dict[str, str]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    if "payload" in hook:
        payload = work_dir / str(hook["payload_name"])
        payload.write_text(json.dumps(hook["payload"](env), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths["payload"] = payload
    if "file_name" in hook:
        source = work_dir / str(hook["file_name"])
        source.write_text(str(hook["file_body"]), encoding="utf-8")
        paths["file"] = source
    if "backup_name" in hook:
        backup = work_dir / str(hook["backup_name"])
        manifest = work_dir / str(hook["manifest_name"])
        backup.write_bytes(b"qurulush backup smoke\n")
        manifest.write_text(json.dumps({"format": "qurulush-backup-smoke-v1", "dry_run": True}, indent=2) + "\n", encoding="utf-8")
        paths["backup"] = backup
        paths["manifest"] = manifest
    return paths


def replace_command_markers(command: list[str], replacements: dict[str, str]) -> list[str]:
    prepared: list[str] = []
    for part in command:
        value = part
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        prepared.append(value)
    return prepared


def parse_hook_response(stdout: str, allowed_statuses: set[str], hook_id: str) -> dict[str, Any]:
    raw = stdout.strip()
    if not raw:
        raise RuntimeError(f"{hook_id} returned empty stdout; JSON response required")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{hook_id} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{hook_id} returned non-object JSON")
    status = str(payload.get("status", "")).strip().lower()
    if payload.get("ok") is True and not status:
        status = "ok"
    if status not in allowed_statuses:
        raise RuntimeError(f"{hook_id} returned unacceptable status: {status or 'empty'}")
    return {
        "status": status,
        "external_id": payload.get("external_id"),
        "provider": payload.get("provider"),
    }


def smoke_hook(hook: dict[str, Any], env: dict[str, str], work_dir: Path) -> dict[str, Any]:
    hook_id = str(hook["id"])
    try:
        command = command_from_env(env, str(hook["command"]))
        hook_dir = work_dir / hook_id
        hook_dir.mkdir(parents=True, exist_ok=True)
        paths = prepare_paths(hook, hook_dir, env)
        replacements = hook["replacements"](env, paths)
        prepared = replace_command_markers(command, replacements)
        marker = str(hook.get("append_if_missing", ""))
        if marker and marker not in command:
            prepared.append(replacements[marker])
        result = subprocess.run(
            prepared,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_from_env(env, str(hook["timeout"])),
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"{hook_id} exited {result.returncode}: {detail[:300]}")
        response = parse_hook_response(result.stdout, set(hook["allowed_statuses"]), hook_id)
        return {"id": hook_id, "status": "pass", "detail": f"JSON status={response['status']}", "response": response}
    except Exception as exc:
        return {"id": hook_id, "status": "fail", "detail": str(exc)}


def run_hook_contract_smoke(env_file: Path | None = None, hooks: set[str] | None = None) -> dict[str, Any]:
    env = dict(os.environ)
    if env_file:
        env.update(parse_env_file(env_file))
    selected = [hook for hook in HOOKS if not hooks or str(hook["id"]) in hooks]
    if not selected:
        raise RuntimeError("no hooks selected")
    with tempfile.TemporaryDirectory(prefix="qurulush-hook-smoke-") as tmp:
        work_dir = Path(tmp)
        checks = [smoke_hook(hook, env, work_dir) for hook in selected]
    failed = [item for item in checks if item["status"] != "pass"]
    return {
        "ok": not failed,
        "env_file": str(env_file.resolve()) if env_file else None,
        "checks": checks,
        "failed_checks": [item["id"] for item in failed],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Qurulush Hub external hook JSON contracts")
    parser.add_argument("--env", type=Path, default=None, help="Optional env file with QH_* hook commands")
    parser.add_argument("--hook", action="append", choices=[str(hook["id"]) for hook in HOOKS], help="Hook id to test; can be repeated")
    args = parser.parse_args(argv)
    result = run_hook_contract_smoke(args.env, set(args.hook or []))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
