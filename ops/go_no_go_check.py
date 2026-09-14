#!/usr/bin/env python3
"""Aggregate release, live smoke, and backup restore checks into one go/no-go result."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from company_platform_server import utc_now  # noqa: E402
from ops.backup_restore_drill import run_restore_drill  # noqa: E402
from ops.deployment_audit import audit_deployment  # noqa: E402
from ops.hook_contract_smoke import run_hook_contract_smoke  # noqa: E402
from ops.production_smoke_check import (  # noqa: E402
    assert_local_readiness_gates,
    expect,
    production_blockers,
    request_json,
    verify_auth_cutover_validation,
    verify_backup_remote_validation,
    verify_backup_schedule_validation,
    verify_deployment_files_bundle,
    verify_domain_https_validation,
    verify_eds_integration_validation,
    verify_acceptance_evidence,
    verify_acceptance_passport,
    verify_completion_audit,
    verify_access_matrix,
    verify_access_matrix_docx,
    verify_hook_contract_validation,
    verify_legal_verification_packet,
    verify_legal_verification_packet_docx,
    verify_interaction_map,
    verify_interaction_map_docx,
    verify_payment_gateway_validation,
    verify_production_official_letters,
    verify_production_official_letters_docx,
    verify_production_evidence_docx,
    verify_production_evidence_register,
    verify_production_env_example,
    verify_production_env_validation,
    verify_production_action_board,
    verify_production_action_board_docx,
    verify_production_cutover_validation,
    verify_production_cutover_docx,
    verify_production_launch_bundle,
    verify_production_launch_checklist,
    verify_production_launch_checklist_docx,
    verify_production_launch_sequence,
    verify_production_launch_sequence_docx,
    verify_production_remaining_work,
    verify_production_remaining_work_docx,
    verify_production_top_actions,
    verify_production_top_actions_docx,
    verify_production_alerts,
    verify_production_qa_evidence,
    verify_production_status_board,
    verify_production_account_cutover,
    verify_production_request_pack,
    verify_production_request_pack_docx,
    verify_production_request_tracker,
    verify_sacc2_exchange_validation,
    verify_sacc2_public_status,
    verify_sacc2_public_status_docx,
    verify_sacc2_public_status_attachment,
    verify_latest_backup,
    verify_production_plan,
    verify_session_control,
    verify_storage_integration_validation,
    verify_av_scanner_validation,
)
from ops.release_acceptance_check import accept_release_package  # noqa: E402


StageRunner = Callable[[], dict[str, Any]]


def run_stage(name: str, runner: StageRunner) -> dict[str, Any]:
    try:
        result = runner()
        return {"name": name, "ok": True, "result": result}
    except Exception as exc:
        return {"name": name, "ok": False, "error": str(exc)}


def run_release_acceptance(package: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="qurulush-release-acceptance-") as tmp:
        return accept_release_package(package, Path(tmp))


def run_deployment_audit(root: Path, env_file: Path | None = None, require_production_config: bool = False) -> dict[str, Any]:
    result = audit_deployment(root, env_file, require_production_config)
    if not result.get("ok"):
        failed = ", ".join(str(item) for item in result.get("failed_checks", [])) or "unknown"
        raise RuntimeError("deployment audit failed: " + failed)
    return result


def run_hook_smoke(env_file: Path) -> dict[str, Any]:
    result = run_hook_contract_smoke(env_file)
    if not result.get("ok"):
        failed = ", ".join(str(item) for item in result.get("failed_checks", [])) or "unknown"
        raise RuntimeError("hook contract smoke failed: " + failed)
    return result


def run_live_smoke(base_url: str, email: str, password: str, require_production: bool = False) -> dict[str, Any]:
    normalized_url = base_url.rstrip("/") + "/"
    checks: list[str] = []

    status, health = request_json(urljoin(normalized_url, "api/health"))
    expect(status == 200 and health.get("ok"), f"health failed: {status} {health}")
    expect(health.get("db_ready") is True, f"health db_ready failed: {health}")
    expect(health.get("storage") == "sqlite", f"health storage marker missing: {health}")
    expect("db" not in health, "health exposes internal database path")
    checks.append(f"health scheme={health.get('scheme')}")

    status, login = request_json(urljoin(normalized_url, "api/auth/login"), "POST", payload={"email": email, "password": password})
    expect(status == 200 and login.get("token"), f"login failed: {status} {login}")
    token = str(login["token"])
    try:
        checks.append(f"login user={login.get('user', {}).get('email')}")
        status, readiness_res = request_json(urljoin(normalized_url, "api/readiness"), token=token)
        expect(status == 200 and readiness_res.get("ok"), f"readiness failed: {status} {readiness_res}")
        readiness = readiness_res.get("data", {})
        expect(readiness.get("local_ready"), "readiness local_ready is false")
        checks.extend(assert_local_readiness_gates(readiness))
        checks.append(f"readiness local_ready={readiness.get('local_ready')} production_ready={readiness.get('production_ready')}")
        checks.extend(verify_session_control(normalized_url, token))
        checks.extend(verify_access_matrix(normalized_url, token))
        checks.extend(verify_access_matrix_docx(normalized_url, token))
        checks.extend(verify_production_plan(normalized_url, token, require_production))
        checks.extend(verify_production_evidence_register(normalized_url, token))
        checks.extend(verify_production_evidence_docx(normalized_url, token))
        checks.extend(verify_production_request_pack(normalized_url, token))
        checks.extend(verify_production_request_pack_docx(normalized_url, token))
        checks.extend(verify_production_official_letters(normalized_url, token))
        checks.extend(verify_production_official_letters_docx(normalized_url, token))
        checks.extend(verify_production_request_tracker(normalized_url, token))
        checks.extend(verify_production_action_board(normalized_url, token))
        checks.extend(verify_production_action_board_docx(normalized_url, token))
        checks.extend(verify_production_launch_sequence(normalized_url, token))
        checks.extend(verify_production_launch_sequence_docx(normalized_url, token))
        checks.extend(verify_production_remaining_work(normalized_url, token))
        checks.extend(verify_production_remaining_work_docx(normalized_url, token))
        checks.extend(verify_production_top_actions(normalized_url, token))
        checks.extend(verify_production_top_actions_docx(normalized_url, token))
        checks.extend(verify_production_alerts(normalized_url, token))
        checks.extend(verify_production_qa_evidence(normalized_url, token))
        checks.extend(verify_production_status_board(normalized_url, token))
        checks.extend(verify_acceptance_evidence(normalized_url, token))
        checks.extend(verify_completion_audit(normalized_url, token))
        checks.extend(verify_production_account_cutover(normalized_url, token))
        checks.extend(verify_production_env_example(normalized_url, token))
        checks.extend(verify_production_env_validation(normalized_url, token))
        checks.extend(verify_auth_cutover_validation(normalized_url, token))
        checks.extend(verify_hook_contract_validation(normalized_url, token))
        checks.extend(verify_sacc2_exchange_validation(normalized_url, token))
        checks.extend(verify_sacc2_public_status(normalized_url, token))
        checks.extend(verify_sacc2_public_status_docx(normalized_url, token))
        checks.extend(verify_sacc2_public_status_attachment(normalized_url, token))
        checks.extend(verify_eds_integration_validation(normalized_url, token))
        checks.extend(verify_payment_gateway_validation(normalized_url, token))
        checks.extend(verify_storage_integration_validation(normalized_url, token))
        checks.extend(verify_av_scanner_validation(normalized_url, token))
        checks.extend(verify_backup_schedule_validation(normalized_url, token))
        checks.extend(verify_backup_remote_validation(normalized_url, token))
        checks.extend(verify_production_cutover_validation(normalized_url, token))
        checks.extend(verify_production_cutover_docx(normalized_url, token))
        checks.extend(verify_production_launch_checklist(normalized_url, token, require_production))
        checks.extend(verify_production_launch_checklist_docx(normalized_url, token))
        checks.extend(verify_legal_verification_packet(normalized_url, token))
        checks.extend(verify_legal_verification_packet_docx(normalized_url, token))
        checks.extend(verify_interaction_map(normalized_url, token))
        checks.extend(verify_interaction_map_docx(normalized_url, token))
        checks.extend(verify_production_launch_bundle(normalized_url, token))
        checks.extend(verify_deployment_files_bundle(normalized_url, token))
        checks.extend(verify_domain_https_validation(normalized_url, token))
        checks.extend(verify_latest_backup(normalized_url, token, require_production))
        checks.extend(verify_acceptance_passport(normalized_url, token, require_production))

        if require_production:
            blockers = production_blockers(readiness)
            expect(readiness.get("production_ready"), "production readiness failed: " + "; ".join(blockers))
            checks.append("production_ready=true")

        return {"ok": True, "base_url": normalized_url, "checks": checks}
    finally:
        request_json(urljoin(normalized_url, "api/auth/logout"), "POST", token=token)


def build_go_no_go_result(stages: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [stage for stage in stages if not stage.get("ok")]
    return {
        "ok": not failed,
        "checked_at": utc_now(),
        "stages": stages,
        "failed_stages": [stage["name"] for stage in failed],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a go/no-go acceptance check for Qurulush Hub")
    parser.add_argument("--release", type=Path, help="Release zip to validate")
    parser.add_argument("--base-url", help="Live platform URL for smoke-check")
    parser.add_argument("--email", help="Director/bootstrap admin email for live smoke-check")
    parser.add_argument("--password", help="Director/bootstrap admin password for live smoke-check")
    parser.add_argument("--backups", type=Path, help="Backup directory for restore drill")
    parser.add_argument("--backup-file", help="Optional backup .sqlite3 filename")
    parser.add_argument("--deployment-root", type=Path, help="Project or extracted release root for deployment audit")
    parser.add_argument("--env", type=Path, help="Protected production env file for deployment audit")
    parser.add_argument("--hook-contract-smoke", action="store_true", help="Run dry-run JSON contract smoke for external hooks from --env")
    parser.add_argument("--require-production", action="store_true", help="Require production_ready=true during live smoke-check")
    parser.add_argument("--require-production-config", action="store_true", help="Require --env to pass strict production deployment audit")
    args = parser.parse_args(argv)

    stages: list[dict[str, Any]] = []
    if args.release:
        stages.append(run_stage("release_acceptance", lambda: run_release_acceptance(args.release)))
    if args.deployment_root or args.env or args.require_production_config:
        if args.require_production_config and not args.env:
            stages.append({"name": "deployment_audit", "ok": False, "error": "--env is required with --require-production-config"})
        else:
            audit_root = args.deployment_root or Path.cwd()
            stages.append(run_stage("deployment_audit", lambda: run_deployment_audit(audit_root, args.env, args.require_production_config)))
    if args.hook_contract_smoke:
        if not args.env:
            stages.append({"name": "hook_contract_smoke", "ok": False, "error": "--env is required with --hook-contract-smoke"})
        else:
            stages.append(run_stage("hook_contract_smoke", lambda: run_hook_smoke(args.env)))
    if args.base_url:
        if not args.email or not args.password:
            stages.append({"name": "live_smoke", "ok": False, "error": "--email and --password are required with --base-url"})
        else:
            stages.append(run_stage("live_smoke", lambda: run_live_smoke(args.base_url, args.email, args.password, args.require_production)))
    if args.backups:
        stages.append(run_stage("backup_restore_drill", lambda: run_restore_drill(args.backups, args.backup_file)))

    if not stages:
        stages.append({"name": "configuration", "ok": False, "error": "provide at least one of --release, --deployment-root, --env, --base-url, or --backups"})

    result = build_go_no_go_result(stages)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
