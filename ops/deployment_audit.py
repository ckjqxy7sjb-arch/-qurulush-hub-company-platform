#!/usr/bin/env python3
"""Audit production deployment files before a Qurulush Hub rollout."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any


RELEASE_DIR = "qurulush-hub-company-platform"
REQUIRED_LAYOUT_FILES = (
    ".env.production.example",
    "company_platform_server.py",
    "extracted_dgask/04_Строительная_компания.html",
    "ops/README_PRODUCTION.md",
    "ops/production_smoke_check.py",
    "ops/go_no_go_check.py",
    "ops/backup_restore_drill.py",
    "ops/qurulush-hub.service.example",
    "ops/nginx-qurulush-hub.conf.example",
)
REQUIRED_ENV_KEYS = (
    "QH_BOOTSTRAP_ADMIN_EMAIL",
    "QH_BOOTSTRAP_ADMIN_PASSWORD",
    "QH_BOOTSTRAP_ADMIN_NAME",
    "QH_DISABLE_DEMO_USERS",
    "QH_REQUIRE_PRODUCTION",
    "QH_REQUIRE_HOOK_JSON",
    "QH_SACC2_API_URL",
    "QH_SACC2_API_KEY",
    "QH_SACC2_SYNC_CMD",
    "QH_EDS_PROVIDER",
    "QH_EDS_API_URL",
    "QH_EDS_SIGN_CMD",
    "QH_PAYMENT_GATEWAY_URL",
    "QH_PAYMENT_GATEWAY_CMD",
    "QH_STORAGE_MODE",
    "QH_STORAGE_URL",
    "QH_STORAGE_SYNC_CMD",
    "QH_AV_SCANNER",
    "QH_BACKUP_INTERVAL_MINUTES",
    "QH_BACKUP_REMOTE_URL",
    "QH_BACKUP_REMOTE_CMD",
    "QH_REFERENCE_VERIFIED_AT",
)
PLACEHOLDER_TOKENS = (
    "change_me",
    "changeme",
    "placeholder",
    "provider.example",
    "example.com",
    "example.test",
    "company.example",
    "dummy",
    "todo",
    "yyyy-mm-dd",
)


def check_item(item_id: str, title: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"id": item_id, "title": title, "status": "pass" if ok else "fail", "detail": detail}


def resolve_root(root: Path) -> Path:
    root = root.resolve()
    if (root / "company_platform_server.py").is_file():
        return root
    release_root = root / RELEASE_DIR
    if (release_root / "company_platform_server.py").is_file():
        return release_root
    return root


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def looks_placeholder(value: str) -> bool:
    cleaned = value.strip().strip("'\"").lower()
    if cleaned in {"secret", "token", "password", "key", "provider-name", "test-eds"}:
        return True
    return any(token in cleaned for token in PLACEHOLDER_TOKENS)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def audit_layout(root: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = [name for name in REQUIRED_LAYOUT_FILES if not (root / name).is_file()]
    checks.append(
        check_item(
            "layout_required_files",
            "Required deployment files",
            not missing,
            "All deployment files are present" if not missing else "Missing: " + ", ".join(missing),
        )
    )

    env_example = root / ".env.production.example"
    if env_example.is_file():
        text = read_text(env_example)
        checks.append(
            check_item(
                "env_template_guard",
                "Production env template guard",
                "QH_REQUIRE_PRODUCTION=1" in text and "QH_DISABLE_DEMO_USERS=1" in text and "QH_DEMO_PASSWORD" not in text,
                "Template enables production guard and demo-user shutdown",
            )
        )
        values = parse_env_file(env_example)
        missing_keys = [key for key in REQUIRED_ENV_KEYS if key not in values]
        checks.append(
            check_item(
                "env_template_keys",
                "Production env template keys",
                not missing_keys,
                "All required keys are documented" if not missing_keys else "Missing keys: " + ", ".join(missing_keys),
            )
        )

    service_file = root / "ops/qurulush-hub.service.example"
    if service_file.is_file():
        text = read_text(service_file)
        checks.append(
            check_item(
                "systemd_guard",
                "Systemd production guard",
                all(
                    marker in text
                    for marker in (
                        "ExecStartPre=",
                        "--preflight",
                        "--require-production",
                        "EnvironmentFile=/etc/qurulush-hub/company-platform.env",
                        "ReadWritePaths=/var/lib/qurulush-hub",
                    )
                ),
                "Service runs preflight and restricts writes to runtime data",
            )
        )

    nginx_file = root / "ops/nginx-qurulush-hub.conf.example"
    if nginx_file.is_file():
        text = read_text(nginx_file)
        checks.append(
            check_item(
                "nginx_https_proxy",
                "Nginx HTTPS reverse proxy",
                all(
                    marker in text
                    for marker in (
                        "listen 443 ssl",
                        "ssl_certificate",
                        "proxy_set_header X-Forwarded-Proto https",
                        "client_max_body_size",
                    )
                ),
                "Nginx template terminates HTTPS and forwards secure headers",
            )
        )

    runbook = root / "ops/README_PRODUCTION.md"
    if runbook.is_file():
        text = read_text(runbook)
        checks.append(
            check_item(
                "runbook_acceptance_commands",
                "Runbook acceptance commands",
                all(marker in text for marker in ("production_smoke_check.py", "go_no_go_check.py", "backup_restore_drill.py", "--require-production")),
                "Runbook documents smoke-check, go/no-go, restore drill and production gate",
            )
        )
    return checks


def audit_env_file(env_file: Path, require_production_config: bool) -> list[dict[str, Any]]:
    values = parse_env_file(env_file)
    missing = [key for key in REQUIRED_ENV_KEYS if not values.get(key)]
    placeholders = [key for key in REQUIRED_ENV_KEYS if values.get(key) and looks_placeholder(values[key])]
    example_hooks = [
        key
        for key, value in values.items()
        if key.endswith("_CMD") and ("ops/hook_examples" in value or "contract_example.py" in value)
    ]
    sacc2_key = values.get("QH_SACC2_API_KEY", "")
    if sacc2_key and not looks_placeholder(sacc2_key) and len(sacc2_key) < 16:
        placeholders.append("QH_SACC2_API_KEY too short")

    env_mode = stat.S_IMODE(env_file.stat().st_mode)
    secure_mode = (env_mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0
    strict_flags = values.get("QH_REQUIRE_PRODUCTION") == "1" and values.get("QH_DISABLE_DEMO_USERS") == "1" and values.get("QH_REQUIRE_HOOK_JSON") == "1"
    strict_ok = not missing and not placeholders and not example_hooks and secure_mode and strict_flags
    checks = [
        check_item(
            "env_required_values",
            "Production env required values",
            not missing,
            "All required values are present" if not missing else "Missing: " + ", ".join(missing),
        ),
        check_item(
            "env_no_placeholders",
            "Production env has no placeholders",
            not placeholders,
            "No placeholder values detected" if not placeholders else "Suspicious values: " + ", ".join(sorted(set(placeholders))),
        ),
        check_item(
            "env_secure_permissions",
            "Production env file permissions",
            secure_mode,
            f"Mode {env_mode:o}; expected no group/other permissions",
        ),
        check_item(
            "env_strict_flags",
            "Production strict flags",
            strict_flags,
            "QH_REQUIRE_PRODUCTION=1, QH_DISABLE_DEMO_USERS=1 and QH_REQUIRE_HOOK_JSON=1 are set",
        ),
        check_item(
            "env_no_example_hooks",
            "Production env does not use example hooks",
            not example_hooks,
            "No example hook paths detected" if not example_hooks else "Replace example hooks: " + ", ".join(example_hooks),
        ),
    ]
    if require_production_config:
        checks.append(
            check_item(
                "env_production_config",
                "Production env acceptance",
                strict_ok,
                "Env file is acceptable for production preflight" if strict_ok else "Fix failed env checks before production",
            )
        )
    return checks


def audit_deployment(root: Path, env_file: Path | None = None, require_production_config: bool = False) -> dict[str, Any]:
    resolved_root = resolve_root(root)
    checks = audit_layout(resolved_root)
    if env_file:
        checks.extend(audit_env_file(env_file.resolve(), require_production_config))
    failed = [item for item in checks if item.get("status") != "pass"]
    return {
        "ok": not failed,
        "root": str(resolved_root),
        "env_file": str(env_file.resolve()) if env_file else None,
        "checks": checks,
        "failed_checks": [item["id"] for item in failed],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Qurulush Hub deployment files and optional production env")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project or extracted release root")
    parser.add_argument("--env", type=Path, default=None, help="Optional protected production env file")
    parser.add_argument("--require-production-config", action="store_true", help="Fail unless --env is production-ready")
    args = parser.parse_args(argv)

    if args.require_production_config and not args.env:
        result = {
            "ok": False,
            "root": str(resolve_root(args.root)),
            "env_file": None,
            "checks": [],
            "failed_checks": ["env_file_required"],
            "error": "--env is required with --require-production-config",
        }
        print(json.dumps(result, ensure_ascii=False))
        return 1

    result = audit_deployment(args.root, args.env, args.require_production_config)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
