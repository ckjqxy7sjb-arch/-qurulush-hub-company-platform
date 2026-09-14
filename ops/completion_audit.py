#!/usr/bin/env python3
"""Build a requirement-by-requirement completion audit for the company platform."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from company_platform_server import utc_now  # noqa: E402
from ops.release_acceptance_check import accept_release_package  # noqa: E402


UNSAFE_MARKERS = ("demo2026", "token_hash", "official-sacc2-key-2026", "stored_file", "password_hash", "password_salt")


def evidence_is_safe(payload: dict[str, Any]) -> bool:
    exported = json.dumps(payload, ensure_ascii=False).lower()
    return all(marker not in exported for marker in UNSAFE_MARKERS)


def stage_result(payload: dict[str, Any], name: str) -> dict[str, Any] | None:
    go_no_go = payload.get("go_no_go") if isinstance(payload.get("go_no_go"), dict) else {}
    stages = go_no_go.get("stages", []) if isinstance(go_no_go, dict) else []
    for stage in stages:
        if isinstance(stage, dict) and stage.get("name") == name:
            return stage
    return None


def live_smoke_checks(payload: dict[str, Any]) -> list[str]:
    live_stage = stage_result(payload, "live_smoke") or {}
    result = live_stage.get("result") if isinstance(live_stage.get("result"), dict) else {}
    checks = result.get("checks", []) if isinstance(result, dict) else []
    return [str(item) for item in checks if isinstance(item, str)]


def check_item(item_id: str, title: str, status: str, evidence: str, next_step: str = "") -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "status": status,
        "evidence": evidence,
        "next_step": next_step,
    }


def build_completion_audit(release: Path, evidence_path: Path, run_release_acceptance: bool = True) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    release_result: dict[str, Any] | None = None
    release_ok = False
    if not release.exists():
        checks.append(check_item("release_zip", "Release ZIP", "missing", str(release), "Собрать пакет через ops/build_release_package.py."))
    elif run_release_acceptance:
        try:
            with tempfile.TemporaryDirectory(prefix="qurulush-completion-audit-") as tmp:
                release_result = accept_release_package(release, Path(tmp))
            release_ok = True
            checks.append(check_item("release_zip", "Release ZIP", "proved", f"{release}; acceptance-check ok"))
        except Exception as exc:
            checks.append(check_item("release_zip", "Release ZIP", "failed", f"{release}; {exc}", "Исправить release package и повторить acceptance-check."))
    else:
        release_ok = True
        checks.append(check_item("release_zip", "Release ZIP", "unverified", str(release), "Запустить audit без --skip-release-acceptance."))

    evidence: dict[str, Any] = {}
    evidence_ok = False
    if not evidence_path.exists():
        checks.append(check_item("acceptance_evidence", "Acceptance evidence", "missing", str(evidence_path), "Запустить ops/collect_acceptance_evidence.py."))
    else:
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            failed_stages = evidence.get("failed_stages", [])
            evidence_ok = bool(evidence.get("ok")) and failed_stages == [] and evidence_is_safe(evidence)
            checks.append(
                check_item(
                    "acceptance_evidence",
                    "Acceptance evidence",
                    "proved" if evidence_ok else "failed",
                    f"{evidence_path}; ok={evidence.get('ok')} failed_stages={failed_stages} safe={evidence_is_safe(evidence)}",
                    "Повторить collect_acceptance_evidence после исправления failed_stages." if not evidence_ok else "",
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(check_item("acceptance_evidence", "Acceptance evidence", "failed", f"{evidence_path}; {exc}", "Пересобрать current evidence JSON."))

    release_stage = stage_result(evidence, "release_acceptance")
    live_stage = stage_result(evidence, "live_smoke")
    backup_stage = stage_result(evidence, "backup_restore_drill")
    required_stages = {
        "release_acceptance": release_stage,
        "live_smoke": live_stage,
        "backup_restore_drill": backup_stage,
    }
    for name, stage in required_stages.items():
        checks.append(
            check_item(
                name,
                name.replace("_", " ").title(),
                "proved" if isinstance(stage, dict) and stage.get("ok") is True else "missing",
                f"stage ok={stage.get('ok') if isinstance(stage, dict) else None}",
                "Пересобрать acceptance evidence с этой стадией." if not (isinstance(stage, dict) and stage.get("ok") is True) else "",
            )
        )

    smoke_checks = live_smoke_checks(evidence)
    local_ready = any("readiness local_ready=True" in item for item in smoke_checks)
    production_ready = any("production_ready=True" in item for item in smoke_checks)
    checks.append(
        check_item(
            "local_working_platform",
            "Локальная рабочая платформа",
            "proved" if local_ready and evidence_ok and release_ok else "failed",
            "live smoke confirmed local_ready=True" if local_ready else "live smoke did not confirm local_ready=True",
            "Повторить production_smoke_check по рабочей ссылке." if not local_ready else "",
        )
    )
    checks.append(
        check_item(
            "production_external_gates",
            "Боевой ведомственный контур",
            "proved" if production_ready else "incomplete_external",
            "live smoke confirmed production_ready=True" if production_ready else "live smoke confirmed production_ready=False",
            "Закрыть внешние gates: домен/HTTPS, боевые учетные записи, sacc2 API, ЭЦП, платежи, storage, AV, remote backup и юридическую сверку.",
        )
    )

    blocker_checks = [item for item in smoke_checks if "production plan blockers=" in item or "production launch checklist blockers=" in item]
    remaining_checks = [item for item in smoke_checks if "production remaining work steps=" in item]
    local_handoff_ready = all(item["status"] == "proved" for item in checks if item["id"] in {"release_zip", "acceptance_evidence", "release_acceptance", "live_smoke", "backup_restore_drill", "local_working_platform"})
    return {
        "format": "qurulush-completion-audit-v1",
        "checked_at": utc_now(),
        "release": str(release),
        "acceptance_evidence": str(evidence_path),
        "local_handoff_ready": local_handoff_ready,
        "production_ready": production_ready,
        "overall_status": "local_ready_external_blockers" if local_handoff_ready and not production_ready else ("production_ready" if local_handoff_ready and production_ready else "not_ready"),
        "blocker_evidence": blocker_checks + remaining_checks,
        "release_acceptance": release_result,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a completion audit for Qurulush Hub company platform")
    parser.add_argument("--release", type=Path, default=ROOT / "dist" / "qurulush-hub-company-platform-current.zip")
    parser.add_argument("--evidence", type=Path, default=ROOT / "outputs" / "acceptance-evidence-current.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "completion-audit-current.json")
    parser.add_argument("--skip-release-acceptance", action="store_true")
    args = parser.parse_args(argv)
    result = build_completion_audit(args.release, args.evidence, not args.skip_release_acceptance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["local_handoff_ready"], "output": str(args.output), "overall_status": result["overall_status"], "production_ready": result["production_ready"]}, ensure_ascii=False))
    return 0 if result["local_handoff_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
