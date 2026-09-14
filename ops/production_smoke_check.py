#!/usr/bin/env python3
"""Production smoke-check for the Qurulush Hub company platform."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


LOCAL_REQUIRED_GATES = (
    "sqlite_integrity",
    "db_schema",
    "schema_version",
    "app_state",
    "password_storage",
    "session_maintenance",
    "backup_manifests",
    "backup_freshness",
    "uploads",
    "backups",
)


def request_json(url: str, method: str = "GET", token: str | None = None, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read().decode("utf-8")
            return res.status, json.loads(raw or "{}")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            parsed = {"ok": False, "error": raw}
        return exc.code, parsed
    except URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def readiness_checks_by_id(readiness: dict[str, Any]) -> dict[str, dict[str, Any]]:
    checks = readiness.get("checks", [])
    if not isinstance(checks, list):
        raise RuntimeError("readiness checks is not a list")
    return {str(item.get("id")): item for item in checks if isinstance(item, dict)}


def assert_local_readiness_gates(readiness: dict[str, Any]) -> list[str]:
    checks_by_id = readiness_checks_by_id(readiness)
    missing = [gate for gate in LOCAL_REQUIRED_GATES if gate not in checks_by_id]
    if missing:
        raise RuntimeError("readiness local gates missing: " + ", ".join(missing))

    failed = [
        f"{gate}={checks_by_id[gate].get('status')}: {checks_by_id[gate].get('detail')}"
        for gate in LOCAL_REQUIRED_GATES
        if checks_by_id[gate].get("status") not in {"pass", "warning"}
    ]
    if failed:
        raise RuntimeError("readiness local gates failed: " + "; ".join(failed))

    return [f"local gate {gate}={checks_by_id[gate].get('status')}" for gate in LOCAL_REQUIRED_GATES]


def production_blockers(readiness: dict[str, Any]) -> list[str]:
    return [
        f"{item.get('id')}: {item.get('detail')}"
        for item in readiness.get("checks", [])
        if isinstance(item, dict) and item.get("production_required") and item.get("status") != "pass"
    ]


def select_latest_backup(backups_payload: Any, require_existing: bool = False) -> dict[str, Any] | None:
    if not isinstance(backups_payload, list):
        raise RuntimeError("backups response is not a list")
    if not backups_payload:
        if require_existing:
            raise RuntimeError("no backups available for verification")
        return None
    latest = backups_payload[0]
    if not isinstance(latest, dict) or not latest.get("file"):
        raise RuntimeError("latest backup entry is invalid")
    return latest


def assert_backup_verification(verification: dict[str, Any], expected_file: str) -> str:
    expect(verification.get("file") == expected_file, f"backup verify file mismatch: {verification}")
    expect(verification.get("integrity") == "PRAGMA quick_check: ok", f"backup integrity failed: {verification}")
    expect(len(str(verification.get("sha256", ""))) == 64, f"backup sha256 missing: {verification}")
    counts = verification.get("counts")
    expect(isinstance(counts, dict) and "objects" in counts and "requests" in counts, f"backup counts missing: {verification}")
    return f"backup verify {expected_file}=ok"


def verify_latest_backup(base_url: str, token: str, require_existing: bool = False) -> list[str]:
    status, backups_res = request_json(urljoin(base_url, "api/backups"), token=token)
    expect(status == 200 and backups_res.get("ok"), f"backup list failed: {status} {backups_res}")
    latest = select_latest_backup(backups_res.get("data"), require_existing)
    if latest is None:
        return ["backup verify skipped=no backups"]
    backup_file = str(latest["file"])
    status, verify_res = request_json(urljoin(base_url, "api/backups/verify"), "POST", token=token, payload={"file": backup_file})
    expect(status == 200 and verify_res.get("ok"), f"backup verify failed: {status} {verify_res}")
    return [assert_backup_verification(verify_res.get("data", {}), backup_file)]


def assert_acceptance_passport(passport: dict[str, Any], require_production: bool = False) -> list[str]:
    expect(passport.get("format") == "qurulush-acceptance-passport-v1", f"acceptance passport format mismatch: {passport}")
    readiness = passport.get("readiness", {})
    expect(isinstance(readiness, dict) and readiness.get("local_ready") is True, f"acceptance passport local readiness failed: {passport}")
    backup_status = passport.get("backup_status")
    expect(backup_status in {"pass", "warning"}, f"acceptance passport backup status failed: {passport}")
    if backup_status == "pass":
        expect(passport.get("local_acceptance") is True, f"acceptance passport local acceptance failed: {passport}")
    if require_production:
        expect(passport.get("production_acceptance") is True, f"acceptance passport production acceptance failed: {passport}")
        expect(not passport.get("production_blockers"), f"acceptance passport has production blockers: {passport.get('production_blockers')}")
    return [
        f"acceptance passport local={passport.get('local_acceptance')}",
        f"acceptance passport production={passport.get('production_acceptance')}",
        f"acceptance passport backup={backup_status}",
    ]


def verify_acceptance_passport(base_url: str, token: str, require_production: bool = False) -> list[str]:
    status, passport_res = request_json(urljoin(base_url, "api/acceptance/passport"), token=token)
    expect(status == 200 and passport_res.get("ok"), f"acceptance passport failed: {status} {passport_res}")
    return assert_acceptance_passport(passport_res.get("data", {}), require_production)


def assert_session_control(payload: dict[str, Any]) -> list[str]:
    sessions = payload.get("sessions")
    expect(isinstance(sessions, list), f"session control response is invalid: {payload}")
    expect(payload.get("active_count") == len(sessions), f"session active_count mismatch: {payload}")
    expect(any(isinstance(item, dict) and item.get("current") is True for item in sessions), f"current session is not marked: {payload}")
    exported = json.dumps(payload, ensure_ascii=False).lower()
    expect("token_hash" not in exported, "session control exposes token_hash")
    return [
        f"sessions active={payload.get('active_count')}",
        f"sessions other={payload.get('other_count')}",
    ]


def verify_session_control(base_url: str, token: str) -> list[str]:
    status, sessions_res = request_json(urljoin(base_url, "api/sessions"), token=token)
    expect(status == 200 and sessions_res.get("ok"), f"session control failed: {status} {sessions_res}")
    checks = assert_session_control(sessions_res.get("data", {}))
    hostname = (urlparse(base_url).hostname or "").lower()
    if hostname in {"127.0.0.1", "localhost", "::1"} and sessions_res.get("data", {}).get("other_count"):
        status, revoke_res = request_json(urljoin(base_url, "api/sessions/revoke-others"), "POST", token=token)
        expect(status == 200 and revoke_res.get("ok"), f"local session cleanup failed: {status} {revoke_res}")
        revoked = revoke_res.get("data", {}).get("revoked_count", 0)
        checks.append(f"local session cleanup revoked={revoked}")
        status, cleaned_res = request_json(urljoin(base_url, "api/sessions"), token=token)
        expect(status == 200 and cleaned_res.get("ok"), f"session control after cleanup failed: {status} {cleaned_res}")
        cleaned = cleaned_res.get("data", {})
        expect(cleaned.get("active_count") == 1 and cleaned.get("other_count") == 0, f"local session cleanup incomplete: {cleaned}")
        checks.append("sessions cleaned active=1")
    return checks


def verify_access_matrix(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/access/matrix"), token=token)
    expect(status == 200 and result.get("ok"), f"access matrix failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-company-access-matrix-v1", f"access matrix format mismatch: {data}")
    roles = data.get("roles")
    expect(isinstance(roles, list) and len(roles) >= 6, f"access matrix roles missing: {data}")
    by_id = {str(role.get("id")): role for role in roles if isinstance(role, dict)}
    expect("ceo" in by_id and "foreman" in by_id and "brigadier" in by_id, f"access matrix core roles missing: {by_id.keys()}")
    expect(any(action.get("id") == "team" and action.get("allowed") for action in by_id["ceo"].get("actions", []) if isinstance(action, dict)), "ceo should manage team")
    expect(not any(action.get("id") == "team" and action.get("allowed") for action in by_id["brigadier"].get("actions", []) if isinstance(action, dict)), "brigadier should not manage team")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "access matrix exposes unsafe data")
    return ["access matrix=ok"]


def verify_access_matrix_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/access/matrix.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"access matrix docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"access matrix docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"access matrix docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"access matrix docx content type mismatch: {content_type}")
    expect(len(raw) > 3000, "access matrix docx is empty")
    expect(raw[:2] == b"PK", "access matrix docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "access matrix docx exposes unsafe data")
    return ["access matrix docx=ok"]


def assert_production_plan(plan: dict[str, Any], require_production: bool = False) -> list[str]:
    expect(plan.get("format") == "qurulush-production-connection-plan-v1", f"production plan format mismatch: {plan}")
    items = plan.get("items")
    expect(isinstance(items, list) and items, f"production plan items missing: {plan}")
    ids = {str(item.get("id")) for item in items if isinstance(item, dict)}
    for required in ("hook_json_contracts", "sacc2_api", "eds", "payments", "object_storage", "av_scan", "backup_remote", "reference_catalog"):
        expect(required in ids, f"production plan item missing: {required}")
    if require_production:
        expect(plan.get("production_ready") is True, f"production plan is not ready: {plan}")
        expect(int(plan.get("blocker_count") or 0) == 0, f"production plan has blockers: {plan.get('blockers')}")
    return [
        f"production plan ready={plan.get('production_ready')}",
        f"production plan blockers={plan.get('blocker_count')}",
    ]


def verify_production_plan(base_url: str, token: str, require_production: bool = False) -> list[str]:
    status, plan_res = request_json(urljoin(base_url, "api/production/plan"), token=token)
    expect(status == 200 and plan_res.get("ok"), f"production plan failed: {status} {plan_res}")
    return assert_production_plan(plan_res.get("data", {}), require_production)


def verify_production_evidence_register(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/evidence"), token=token)
    expect(status == 200 and result.get("ok"), f"production evidence register failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-evidence-register-v1", f"production evidence format mismatch: {data}")
    items = data.get("items")
    expect(isinstance(items, list) and len(items) >= 10, f"production evidence items missing: {data}")
    item_ids = {str(item.get("id")) for item in items if isinstance(item, dict)}
    expect("sacc2_api" in item_ids and "reference_catalog" in item_ids, f"production evidence core gates missing: {item_ids}")
    status, updated = request_json(
        urljoin(base_url, "api/production/evidence"),
        "POST",
        token=token,
        payload={
            "id": "sacc2_api",
            "status": "waiting_external",
            "owner": "Директор / IT",
            "deadline": "2026-09-20",
            "evidence": "Smoke-check запись: ожидается официальный доступ sacc2 / ДГАСК.",
        },
    )
    expect(status == 200 and updated.get("ok"), f"production evidence update failed: {status} {updated}")
    updated_items = {str(item.get("id")): item for item in updated.get("data", {}).get("items", []) if isinstance(item, dict)}
    expect(updated_items.get("sacc2_api", {}).get("evidence_status") == "waiting_external", f"production evidence update did not persist: {updated}")
    exported = json.dumps(updated, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production evidence exposes unsafe data")
    return ["production evidence register=ok"]


def verify_production_evidence_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/evidence.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production evidence docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production evidence docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production evidence docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production evidence docx content type mismatch: {content_type}")
    expect(len(raw) > 2500, "production evidence docx is empty")
    expect(raw[:2] == b"PK", "production evidence docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production evidence docx exposes unsafe data")
    return ["production evidence docx=ok"]


def verify_production_request_pack(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/request-pack"), token=token)
    expect(status == 200 and result.get("ok"), f"production request pack failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-request-pack-v1", f"production request pack format mismatch: {data}")
    items = data.get("items")
    expect(isinstance(items, list) and len(items) >= 10, f"production request pack items missing: {data}")
    by_id = {str(item.get("id")): item for item in items if isinstance(item, dict)}
    expect("sacc2_api" in by_id and "payments" in by_id and "reference_catalog" in by_id, f"production request pack core gates missing: {by_id.keys()}")
    expect("Министерство строительства" in str(by_id["sacc2_api"].get("stakeholder", "")), "sacc2 request should target ministry/DGASK stakeholder")
    expect("госпошлин" in str(by_id["payments"].get("request", "")), "payments request should mention state fees")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production request pack exposes unsafe data")
    return ["production request pack=ok"]


def verify_production_request_pack_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/request-pack.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production request pack docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production request pack docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production request pack docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production request pack docx content type mismatch: {content_type}")
    expect(len(raw) > 3000, "production request pack docx is empty")
    expect(raw[:2] == b"PK", "production request pack docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production request pack docx exposes unsafe data")
    return ["production request pack docx=ok"]


def verify_production_official_letters(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/official-letters"), token=token)
    expect(status == 200 and result.get("ok"), f"production official letters failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-official-letters-v1", f"production official letters format mismatch: {data}")
    letters = data.get("letters")
    expect(isinstance(letters, list) and len(letters) >= 10, f"production official letters missing: {data}")
    by_id = {str(letter.get("id")): letter for letter in letters if isinstance(letter, dict)}
    expect("sacc2_api" in by_id and "payments" in by_id, f"production official letters core letters missing: {by_id.keys()}")
    expect("Министерство строительства" in str(by_id["sacc2_api"].get("recipient", "")), "official letters should include ministry recipient")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production official letters exposes unsafe data")
    return ["production official letters=ok"]


def verify_production_official_letters_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/official-letters.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production official letters docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production official letters docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production official letters docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production official letters docx content type mismatch: {content_type}")
    expect(len(raw) > 3000, "production official letters docx is empty")
    expect(raw[:2] == b"PK", "production official letters docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production official letters docx exposes unsafe data")
    return ["production official letters docx=ok"]


def verify_production_request_tracker(base_url: str, token: str) -> list[str]:
    payload = {
        "id": "sacc2_api",
        "status": "sent",
        "outgoing_no": "SMOKE-SACC2-2026-001",
        "sent_at": "2026-09-13",
        "contact": "Минстрой / ДГАСК",
        "responsible": "Директор / IT",
        "note": "Smoke-check: запрос доступа sacc2 отправлен и ожидает ответа.",
    }
    status, result = request_json(urljoin(base_url, "api/production/request-pack/tracker"), "POST", token=token, payload=payload)
    expect(status == 200 and result.get("ok"), f"production request tracker update failed: {status} {result}")
    data = result.get("data", {})
    pack_items = {str(item.get("id")): item for item in data.get("request_pack", {}).get("items", []) if isinstance(item, dict)}
    evidence_items = {str(item.get("id")): item for item in data.get("evidence", {}).get("items", []) if isinstance(item, dict)}
    expect(pack_items.get("sacc2_api", {}).get("tracker_status") == "sent", f"production request tracker status did not persist: {data}")
    expect(pack_items.get("sacc2_api", {}).get("outgoing_no") == "SMOKE-SACC2-2026-001", f"production request outgoing number did not persist: {data}")
    expect(evidence_items.get("sacc2_api", {}).get("evidence_status") == "waiting_external", f"production request tracker did not sync evidence: {data}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production request tracker exposes unsafe data")
    return ["production request tracker=ok"]


def verify_production_action_board(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/action-board"), token=token)
    expect(status == 200 and result.get("ok"), f"production action board failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-action-board-v1", f"production action board format mismatch: {data}")
    groups = data.get("groups")
    expect(isinstance(groups, list) and len(groups) >= 5, f"production action board groups missing: {data}")
    by_id = {str(group.get("id")): group for group in groups if isinstance(group, dict)}
    expect("devops" in by_id and "ministry" in by_id and "accountant" in by_id, f"production action board core groups missing: {by_id.keys()}")
    expect(any(str(item.get("id")) == "sacc2_api" for item in by_id["ministry"].get("items", []) if isinstance(item, dict)), "production action board ministry group should include sacc2")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production action board exposes unsafe data")
    return ["production action board=ok"]


def verify_production_action_board_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/action-board.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production action board docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production action board docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production action board docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production action board docx content type mismatch: {content_type}")
    expect(len(raw) > 3000, "production action board docx is empty")
    expect(raw[:2] == b"PK", "production action board docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production action board docx exposes unsafe data")
    return ["production action board docx=ok"]


def verify_production_launch_sequence(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/launch-sequence"), token=token)
    expect(status == 200 and result.get("ok"), f"production launch sequence failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-launch-sequence-v1", f"production launch sequence format mismatch: {data}")
    phases = data.get("phases")
    expect(isinstance(phases, list) and len(phases) >= 6, f"production launch sequence phases missing: {data}")
    by_id = {str(phase.get("id")): phase for phase in phases if isinstance(phase, dict)}
    expect("governance" in by_id and "integrations" in by_id and "acceptance" in by_id, f"production launch sequence core phases missing: {by_id.keys()}")
    expect(any(str(step.get("id")) == "sacc2_api" for step in by_id["integrations"].get("steps", []) if isinstance(step, dict)), "production launch sequence should include sacc2 step")
    expect(any(str(step.get("id")) == "final_go_no_go" for step in by_id["acceptance"].get("steps", []) if isinstance(step, dict)), "production launch sequence should include final go/no-go")
    current = data.get("current_step")
    expect(current is None or isinstance(current, dict), f"production launch sequence current step invalid: {data}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production launch sequence exposes unsafe data")
    return ["production launch sequence=ok"]


def verify_production_launch_sequence_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/launch-sequence.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production launch sequence docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production launch sequence docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production launch sequence docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production launch sequence docx content type mismatch: {content_type}")
    expect(len(raw) > 3000, "production launch sequence docx is empty")
    expect(raw[:2] == b"PK", "production launch sequence docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production launch sequence docx exposes unsafe data")
    return ["production launch sequence docx=ok"]


def verify_production_remaining_work(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/remaining-work"), token=token)
    expect(status == 200 and result.get("ok"), f"production remaining work failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-remaining-work-v1", f"production remaining work format mismatch: {data}")
    steps = data.get("steps")
    expect(isinstance(steps, list), f"production remaining work steps invalid: {data}")
    if not data.get("production_ready"):
        expect(len(steps) >= 1, f"production remaining work should list open steps: {data}")
        expect(isinstance(data.get("current_step"), dict), f"production remaining work current step missing: {data}")
        expect(isinstance(data.get("top_actions"), list) and len(data.get("top_actions")) >= 1, f"production remaining work top actions missing: {data}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production remaining work exposes unsafe data")
    return [f"production remaining work steps={len(steps)}"]


def verify_production_remaining_work_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/remaining-work.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production remaining work docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production remaining work docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production remaining work docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production remaining work docx content type mismatch: {content_type}")
    expect(len(raw) > 2500, "production remaining work docx is empty")
    expect(raw[:2] == b"PK", "production remaining work docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported, "production remaining work docx exposes unsafe data")
    return ["production remaining work docx=ok"]


def verify_production_top_actions(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/top-actions"), token=token)
    expect(status == 200 and result.get("ok"), f"production top actions failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-top-actions-v1", f"production top actions format mismatch: {data}")
    actions = data.get("actions")
    expect(isinstance(actions, list), f"production top actions invalid: {data}")
    if not data.get("production_ready"):
        expect(1 <= len(actions) <= 5, f"production top actions should stay short and non-empty: {data}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "official-sacc2-key-2026" not in exported, "production top actions exposes unsafe data")
    return [f"production top actions={len(actions)}"]


def verify_production_top_actions_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/top-actions.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production top actions docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production top actions docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production top actions docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production top actions docx content type mismatch: {content_type}")
    expect(len(raw) > 2500, "production top actions docx is empty")
    expect(raw[:2] == b"PK", "production top actions docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "official-sacc2-key-2026" not in exported, "production top actions docx exposes unsafe data")
    return ["production top actions docx=ok"]


def verify_production_alerts(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/alerts"), token=token)
    expect(status == 200 and result.get("ok"), f"production alerts failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-alerts-v1", f"production alerts format mismatch: {data}")
    alerts = data.get("alerts")
    expect(isinstance(alerts, list), f"production alerts invalid: {data}")
    expect(isinstance(data.get("urgent_count"), int), f"production alerts urgent_count invalid: {data}")
    expect(isinstance(data.get("alert_count"), int) and data.get("alert_count") == len(alerts), f"production alerts count mismatch: {data}")
    if not data.get("production_ready") and int(data.get("remaining_count") or 0) > 0:
        expect(len(alerts) >= 1, f"production alerts should expose at least one open launch warning: {data}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "official-sacc2-key-2026" not in exported, "production alerts exposes unsafe data")
    return [f"production alerts={len(alerts)}"]


def verify_production_qa_evidence(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/qa-evidence"), token=token)
    expect(status == 200 and result.get("ok"), f"production qa evidence failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-qa-evidence-v1", f"production qa evidence format mismatch: {data}")
    expect(str(data.get("working_link", "")).endswith("/04_Строительная_компания.html"), f"production qa evidence working link mismatch: {data}")
    checks = {str(item.get("id")) for item in data.get("automated_checks", []) if isinstance(item, dict)}
    for required in ("backend_regression", "browser_smoke", "responsive_smoke", "accessibility_smoke", "live_smoke", "release_acceptance", "go_no_go", "acceptance_evidence"):
        expect(required in checks, f"production qa evidence missing check: {required}")
    artifacts = {str(item.get("id")) for item in data.get("artifacts", []) if isinstance(item, dict)}
    expect("current_release_zip" in artifacts and "test_report" in artifacts, f"production qa evidence missing artifacts: {artifacts}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "official-sacc2-key-2026" not in exported, "production qa evidence exposes unsafe data")

    req = Request(urljoin(base_url, "api/production/qa-evidence.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production qa evidence docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production qa evidence docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production qa evidence docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production qa evidence docx content type mismatch: {content_type}")
    expect(len(raw) > 2500, "production qa evidence docx is empty")
    expect(raw[:2] == b"PK", "production qa evidence docx is not an Office zip package")
    exported_docx = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported_docx and "token_hash" not in exported_docx and "official-sacc2-key-2026" not in exported_docx, "production qa evidence docx exposes unsafe data")
    return ["production qa evidence=ok", "production qa evidence docx=ok"]


def verify_production_status_board(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/status-board"), token=token)
    expect(status == 200 and result.get("ok"), f"production status board failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-status-board-v1", f"production status board format mismatch: {data}")
    expect(str(data.get("working_link", "")).endswith("/04_Строительная_компания.html"), f"production status board working link mismatch: {data}")
    expect(isinstance(data.get("summary_cards"), list) and len(data.get("summary_cards")) >= 4, f"production status board cards invalid: {data}")
    expect(isinstance(data.get("steps"), list), f"production status board steps invalid: {data}")
    expect(isinstance(data.get("top_actions"), list), f"production status board actions invalid: {data}")
    qa_checks = {str(item.get("id")) for item in data.get("qa_checks", []) if isinstance(item, dict)}
    expect("go_no_go" in qa_checks, f"production status board missing go/no-go check: {qa_checks}")
    expect("acceptance_evidence" in qa_checks, f"production status board missing acceptance evidence check: {qa_checks}")
    artifacts = {str(item.get("id")) for item in data.get("artifacts", []) if isinstance(item, dict)}
    expect("current_release_zip" in artifacts, f"production status board missing release artifact: {artifacts}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "official-sacc2-key-2026" not in exported, "production status board exposes unsafe data")

    req = Request(urljoin(base_url, "api/production/status-board.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production status board docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production status board docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production status board docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production status board docx content type mismatch: {content_type}")
    expect(len(raw) > 2500, "production status board docx is empty")
    expect(raw[:2] == b"PK", "production status board docx is not an Office zip package")
    exported_docx = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported_docx and "token_hash" not in exported_docx and "official-sacc2-key-2026" not in exported_docx, "production status board docx exposes unsafe data")
    return ["production status board=ok", "production status board docx=ok"]


def verify_production_account_cutover(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/account-cutover"), token=token)
    expect(status == 200 and result.get("ok"), f"production account cutover failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-account-cutover-v1", f"production account cutover format mismatch: {data}")
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    expect(isinstance(data.get("role_coverage"), list) and len(data.get("role_coverage")) >= 6, f"production account role coverage invalid: {data}")
    expect(isinstance(data.get("users"), list), f"production account users invalid: {data}")
    expect(isinstance(counts.get("active_demo"), int), f"production account active_demo invalid: {data}")
    expect(isinstance(counts.get("roles_ready"), int), f"production account roles_ready invalid: {data}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "password_hash" not in exported and "password_salt" not in exported and "token_hash" not in exported, "production account cutover exposes unsafe data")

    req = Request(urljoin(base_url, "api/production/account-cutover.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production account cutover docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production account cutover docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production account cutover docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production account cutover docx content type mismatch: {content_type}")
    expect(len(raw) > 2500, "production account cutover docx is empty")
    expect(raw[:2] == b"PK", "production account cutover docx is not an Office zip package")
    exported_docx = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported_docx and "password_hash" not in exported_docx and "password_salt" not in exported_docx and "token_hash" not in exported_docx, "production account cutover docx exposes unsafe data")
    return [f"production account cutover real={counts.get('active_real', 0)} demo={counts.get('active_demo', 0)}"]


def verify_production_env_example(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/env.example"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read().decode("utf-8")
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production env example failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production env example failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production env example request failed: {exc}") from exc
    expect("text/plain" in content_type, f"production env example content type mismatch: {content_type}")
    expect("QH_REQUIRE_PRODUCTION=1" in raw, "production env example missing production guard")
    expect("QH_SACC2_API_URL=https://sacc2.avn.kg/api" in raw, "production env example missing sacc2 URL")
    expect("QH_DEMO_PASSWORD" not in raw and "token_hash" not in raw, "production env example exposes unsafe data")
    return ["production env example=ok"]


def complete_env_validation_sample() -> str:
    return "\n".join(
        [
            "QH_BOOTSTRAP_ADMIN_EMAIL=owner@builder.kg",
            "QH_BOOTSTRAP_ADMIN_PASSWORD=RealStrongPassword2026!",
            'QH_BOOTSTRAP_ADMIN_NAME="Замирбек уулу Максатбек"',
            "QH_BOOTSTRAP_ADMIN_ROLE=ceo",
            "QH_DISABLE_DEMO_USERS=1",
            "QH_REQUIRE_PRODUCTION=1",
            "QH_REQUIRE_HOOK_JSON=1",
            "QH_SACC2_API_URL=https://sacc2.avn.kg/api",
            "QH_SACC2_API_KEY=official-sacc2-key-2026",
            'QH_SACC2_SYNC_CMD="/opt/qurulush/bin/sync-sacc2 {payload}"',
            'QH_SACC2_STATUS_MAP={"needs_company":["needs_company","need_company_response"],"informed":["informed"],"review":["review","in_review"],"done":["done","completed"]}',
            "QH_EDS_PROVIDER=OfficialEDS",
            "QH_EDS_API_URL=https://eds.builder.kg/sign",
            'QH_EDS_SIGN_CMD="/opt/qurulush/bin/sign-document {payload}"',
            "QH_PAYMENT_GATEWAY_URL=https://payments.builder.kg/api",
            'QH_PAYMENT_GATEWAY_CMD="/opt/qurulush/bin/confirm-payment {payload}"',
            "QH_STORAGE_MODE=external",
            "QH_STORAGE_URL=s3://company-documents/qurulush-hub",
            'QH_STORAGE_SYNC_CMD="aws s3 cp {file} {storage_url}/{doc_id}/"',
            'QH_AV_SCANNER="/opt/qurulush/bin/scan-upload {file}"',
            "QH_BACKUP_INTERVAL_MINUTES=60",
            "QH_BACKUP_ON_START=1",
            "QH_BACKUP_REMOTE_URL=s3://company-secure-backups/qurulush-hub",
            'QH_BACKUP_REMOTE_CMD="/opt/qurulush/bin/sync-backup {backup} {manifest}"',
            "QH_REFERENCE_VERIFIED_AT=2026-09-13",
        ]
    )


def verify_production_env_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/env/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"production env validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-env-validation-v1", f"production env validation format mismatch: {data}")
    expect(data.get("ready") is True, f"production env validation should accept complete env: {data}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("RealStrongPassword2026!" not in exported and "official-sacc2-key-2026" not in exported, "production env validation exposes submitted values")
    return ["production env validation=ok"]


def verify_auth_cutover_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/auth-cutover/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"auth cutover validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-auth-cutover-validation-v1", f"auth cutover validation format mismatch: {data}")
    expect(data.get("ready_for_cutover") is True, f"auth cutover validation should accept production bootstrap env: {data}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("RealStrongPassword2026!" not in exported, "auth cutover validation exposes submitted password")
    return ["auth cutover validation=ok"]


def verify_hook_contract_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/hooks/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"hook contract validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-hook-contract-validation-v1", f"hook contract validation format mismatch: {data}")
    expect(data.get("ready_for_hook_smoke") is True, f"hook contract validation should accept complete hook env: {data}")
    expect(data.get("ready_hook_count") == data.get("hook_count"), f"hook contract validation did not pass all hooks: {data}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("RealStrongPassword2026!" not in exported and "official-sacc2-key-2026" not in exported, "hook contract validation exposes submitted secrets")
    return ["hook contract validation=ok"]


def verify_sacc2_exchange_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/sacc2/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"sacc2 exchange validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-sacc2-exchange-validation-v1", f"sacc2 exchange validation format mismatch: {data}")
    expect(data.get("ready_for_sacc2_smoke") is True, f"sacc2 exchange validation should accept complete sacc2 env: {data}")
    expect(data.get("api_url_host") == "sacc2.avn.kg", f"sacc2 exchange validation host mismatch: {data}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("official-sacc2-key-2026" not in exported, "sacc2 exchange validation exposes API key")
    return ["sacc2 exchange validation=ok"]


def verify_sacc2_public_status(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/external/sacc2-status"), token=token)
    expect(status == 200 and result.get("ok"), f"sacc2 public status failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-sacc2-public-status-v1", f"sacc2 public status format mismatch: {data}")
    expect(data.get("credentials_used") is False, "sacc2 public status must not use credentials")
    targets = data.get("targets")
    expect(isinstance(targets, list) and targets, f"sacc2 public status targets missing: {data}")
    allowed_statuses = {"online", "external_error", "unreachable", "timeout", "reachable_with_error", "blocked"}
    invalid = [str(item.get("status")) for item in targets if not isinstance(item, dict) or item.get("status") not in allowed_statuses]
    expect(not invalid, "sacc2 public status invalid target statuses: " + ", ".join(invalid))
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("official-sacc2-key-2026" not in exported and "api_key" not in exported and "token_hash" not in exported, "sacc2 public status exposes unsafe data")
    return [f"sacc2 public status={data.get('summary_status')}"]


def verify_sacc2_public_status_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/external/sacc2-status.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=15) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"sacc2 public status docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"sacc2 public status docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"sacc2 public status docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"sacc2 public status docx content type mismatch: {content_type}")
    expect(len(raw) > 3000, "sacc2 public status docx is empty")
    expect(raw[:2] == b"PK", "sacc2 public status docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "api_key" not in exported and "token_hash" not in exported, "sacc2 public status docx exposes unsafe data")
    return ["sacc2 public status docx=ok"]


def verify_sacc2_public_status_attachment(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/external/sacc2-status/attach"), "POST", token=token, payload={})
    expect(status == 200 and result.get("ok"), f"sacc2 public status attachment failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-sacc2-public-status-attachment-v1", f"sacc2 public status attachment format mismatch: {data}")
    expect(data.get("attached_gate") == "sacc2_api", f"sacc2 public status attachment gate mismatch: {data}")
    expect(data.get("tracker_status") in {"answered", "blocked"}, f"sacc2 public status attachment unexpected tracker status: {data}")
    request_items = [
        item for item in data.get("request_pack", {}).get("items", [])
        if isinstance(item, dict) and item.get("id") == "sacc2_api"
    ]
    evidence_items = [
        item for item in data.get("evidence", {}).get("items", [])
        if isinstance(item, dict) and item.get("id") == "sacc2_api"
    ]
    expect(request_items and str(request_items[0].get("outgoing_no", "")).startswith("SACC2-STATUS-"), f"sacc2 public status request-pack not updated: {data}")
    expect(evidence_items and "Пароли использованы: нет" in str(evidence_items[0].get("evidence", "")), f"sacc2 public status evidence not updated safely: {data}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "official-sacc2-key-2026" not in exported and "token_hash" not in exported, "sacc2 public status attachment exposes unsafe data")
    return [f"sacc2 public status attachment={data.get('tracker_status')}"]


def verify_eds_integration_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/eds/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"EDS integration validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-eds-integration-validation-v1", f"EDS integration validation format mismatch: {data}")
    expect(data.get("ready_for_eds_smoke") is True, f"EDS integration validation should accept complete env: {data}")
    expect(data.get("api_url_host") == "eds.builder.kg", f"EDS integration validation host mismatch: {data}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("/opt/qurulush/bin/sign-document" not in exported, "EDS integration validation exposes sign command")
    return ["EDS integration validation=ok"]


def verify_payment_gateway_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/payments/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"payment gateway validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-payment-gateway-validation-v1", f"payment gateway validation format mismatch: {data}")
    expect(data.get("ready_for_payment_smoke") is True, f"payment gateway validation should accept complete env: {data}")
    expect(data.get("gateway_host") == "payments.builder.kg", f"payment gateway validation host mismatch: {data}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("/opt/qurulush/bin/confirm-payment" not in exported, "payment gateway validation exposes command")
    return ["payment gateway validation=ok"]


def verify_storage_integration_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/storage/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"storage integration validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-storage-integration-validation-v1", f"storage integration validation format mismatch: {data}")
    expect(data.get("ready_for_storage_smoke") is True, f"storage integration validation should accept complete env: {data}")
    expect(data.get("storage_scheme") == "s3", f"storage integration validation scheme mismatch: {data}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("/opt/qurulush/bin/storage" not in exported and "aws s3 cp" not in exported, "storage integration validation exposes command")
    return ["storage integration validation=ok"]


def verify_av_scanner_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/av/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"AV scanner validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-av-scanner-validation-v1", f"AV scanner validation format mismatch: {data}")
    expect(data.get("ready_for_av_smoke") is True, f"AV scanner validation should accept complete env: {data}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("/opt/qurulush/bin/scan-upload" not in exported, "AV scanner validation exposes command")
    return ["AV scanner validation=ok"]


def verify_backup_schedule_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/backups/schedule/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"backup schedule validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-backup-schedule-validation-v1", f"backup schedule validation format mismatch: {data}")
    expect(data.get("ready_for_backup_schedule") is True, f"backup schedule validation should accept complete env: {data}")
    expect(data.get("on_start") is True, f"backup schedule validation should require startup backup: {data}")
    return ["backup schedule validation=ok"]


def verify_backup_remote_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/backups/remote/validate"),
        "POST",
        token=token,
        payload={"env_text": complete_env_validation_sample()},
    )
    expect(status == 200 and result.get("ok"), f"remote backup validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-backup-remote-validation-v1", f"remote backup validation format mismatch: {data}")
    expect(data.get("ready_for_remote_backup_smoke") is True, f"remote backup validation should accept complete env: {data}")
    expect(data.get("remote_scheme") == "s3", f"remote backup validation scheme mismatch: {data}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("/opt/qurulush/bin/sync-backup" not in exported, "remote backup validation exposes command")
    return ["remote backup validation=ok"]


def verify_production_cutover_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/cutover/validate"),
        "POST",
        token=token,
        payload={
            "env_text": complete_env_validation_sample(),
            "domain": "cabinet.builder.kg",
            "public_url": "https://cabinet.builder.kg/",
            "port": 8781,
        },
    )
    expect(status == 200 and result.get("ok"), f"production cutover validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-production-cutover-validation-v1", f"production cutover validation format mismatch: {data}")
    expect(data.get("ready_for_production_cutover") is True, f"production cutover validation should accept complete env: {data}")
    expect(data.get("cutover_scope") == "configuration_validation", f"production cutover should label validation scope: {data}")
    expect(data.get("configuration_ready") is True, f"production cutover should mark configuration ready: {data}")
    expect(data.get("ready_for_final_acceptance") is False, f"production cutover should require final live acceptance when probe is not run: {data}")
    expect(data.get("final_acceptance_required") is True, f"production cutover should expose final acceptance requirement: {data}")
    expect(int(data.get("blocking_issue_count") or 0) == 0, f"production cutover should have no blocking issues: {data}")
    stage_ids = {str(item.get("id")) for item in data.get("stages", []) if isinstance(item, dict)}
    for required in ("sacc2", "eds", "payments", "storage", "av", "backup_schedule", "backup_remote", "legal_catalog"):
        expect(required in stage_ids, f"production cutover stage missing: {required}")
    exported = json.dumps(data, ensure_ascii=False)
    expect("RealStrongPassword2026!" not in exported and "official-sacc2-key-2026" not in exported, "production cutover exposes submitted secrets")
    expect("/opt/qurulush/bin" not in exported and "aws s3 cp" not in exported, "production cutover exposes submitted commands")
    return [f"production cutover config validation={data.get('completion_percent')}% final_acceptance={data.get('ready_for_final_acceptance')}"]


def verify_production_cutover_docx(base_url: str, token: str) -> list[str]:
    payload = json.dumps(
        {
            "env_text": complete_env_validation_sample(),
            "domain": "cabinet.builder.kg",
            "public_url": "https://cabinet.builder.kg/",
            "port": 8781,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = Request(
        urljoin(base_url, "api/production/cutover.docx"),
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production cutover docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production cutover docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production cutover docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production cutover docx content type mismatch: {content_type}")
    expect(len(raw) > 2000, "production cutover docx is empty")
    expect(raw[:2] == b"PK", "production cutover docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore")
    expect("RealStrongPassword2026!" not in exported and "official-sacc2-key-2026" not in exported, "production cutover docx exposes submitted secrets")
    expect("/opt/qurulush/bin" not in exported and "aws s3 cp" not in exported, "production cutover docx exposes submitted commands")
    return ["production cutover docx=ok"]


def assert_production_launch_checklist(checklist: dict[str, Any], require_production: bool = False) -> list[str]:
    expect(checklist.get("format") == "qurulush-production-launch-checklist-v1", f"production launch checklist format mismatch: {checklist}")
    stages = checklist.get("stages")
    commands = checklist.get("commands")
    expect(isinstance(stages, list) and stages, f"production launch checklist stages missing: {checklist}")
    expect(isinstance(commands, list) and commands, f"production launch checklist commands missing: {checklist}")
    stage_ids = {str(item.get("id")) for item in stages if isinstance(item, dict)}
    command_ids = {str(item.get("id")) for item in commands if isinstance(item, dict)}
    for required in ("server_environment", "external_integrations", "backup_recovery", "legal_catalog", "final_acceptance"):
        expect(required in stage_ids, f"production launch checklist stage missing: {required}")
    for required in ("preflight", "live_smoke", "go_no_go"):
        expect(required in command_ids, f"production launch checklist command missing: {required}")
    if require_production:
        expect(checklist.get("production_ready") is True, f"production launch checklist is not ready: {checklist}")
        expect(int(checklist.get("blocker_count") or 0) == 0, f"production launch checklist has blockers: {checklist.get('blockers')}")
    return [
        f"production launch checklist ready={checklist.get('production_ready')}",
        f"production launch checklist blockers={checklist.get('blocker_count')}",
    ]


def verify_production_launch_checklist(base_url: str, token: str, require_production: bool = False) -> list[str]:
    status, checklist_res = request_json(urljoin(base_url, "api/production/checklist"), token=token)
    expect(status == 200 and checklist_res.get("ok"), f"production launch checklist failed: {status} {checklist_res}")
    return assert_production_launch_checklist(checklist_res.get("data", {}), require_production)


def verify_production_launch_checklist_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/checklist.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production launch checklist docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production launch checklist docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production launch checklist docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"production launch checklist docx content type mismatch: {content_type}")
    expect(len(raw) > 2000, "production launch checklist docx is empty")
    expect(raw[:2] == b"PK", "production launch checklist docx is not an Office zip package")
    return ["production launch checklist docx=ok"]


def verify_legal_verification_packet(base_url: str, token: str) -> list[str]:
    status, packet_res = request_json(urljoin(base_url, "api/legal/verification-packet"), token=token)
    expect(status == 200 and packet_res.get("ok"), f"legal verification packet failed: {status} {packet_res}")
    packet = packet_res.get("data", {})
    expect(packet.get("format") == "qurulush-legal-verification-packet-v1", f"legal packet format mismatch: {packet}")
    categories = packet.get("categories")
    items = packet.get("items")
    expect(isinstance(categories, list) and "Разрешительные документы" in categories, "legal packet missing permit category")
    expect(isinstance(categories, list) and "Штрафы и нарушения" in categories, "legal packet missing fines category")
    expect(isinstance(items, list) and any(item.get("verification_status") == "needs_review" for item in items if isinstance(item, dict)), "legal packet missing review fields")
    sources = packet.get("official_sources")
    expect(isinstance(sources, list) and len(sources) >= 5, "legal packet missing official source registry")
    source_ids = {str(item.get("id")) for item in sources if isinstance(item, dict)}
    expect("minstroy_order_93_2025" in source_ids, "legal packet missing Minstroy order source")
    expect("offenses_code_2021" in source_ids, "legal packet missing offenses code source")
    expect("minstroy_license_fee_service" in source_ids, "legal packet missing license fee source")
    fine_items = [item for item in items if isinstance(item, dict) and item.get("category") == "Штрафы и нарушения"]
    expect(fine_items and any(source.get("id") == "offenses_code_2021" for source in fine_items[0].get("source_candidates", []) if isinstance(source, dict)), "legal packet fine item missing offenses code candidate")
    exported = json.dumps(packet, ensure_ascii=False).lower()
    expect("stored_file" not in exported and "token_hash" not in exported and "password" not in exported, "legal packet exposes internal data")
    return [f"legal verification packet items={len(items)}"]


def verify_legal_verification_packet_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/legal/verification-packet.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"legal verification packet docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"legal verification packet docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"legal verification packet docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"legal verification packet docx content type mismatch: {content_type}")
    expect(len(raw) > 2500, "legal verification packet docx is empty")
    expect(raw[:2] == b"PK", "legal verification packet docx is not an Office zip package")
    with zipfile.ZipFile(BytesIO(raw)) as docx:
        document_xml = docx.read("word/document.xml").decode("utf-8")
    expect("Официальные источники для сверки" in document_xml, "legal verification packet docx missing official sources")
    expect("minstroy_order_93_2025" in document_xml and "offenses_code_2021" in document_xml, "legal verification packet docx missing source identifiers")
    return ["legal verification packet docx=ok"]


def verify_interaction_map(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/interaction/map"), token=token)
    expect(status == 200 and result.get("ok"), f"interaction map failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-dgask-interaction-map-v1", f"interaction map format mismatch: {data}")
    workflows = data.get("workflows")
    expect(isinstance(workflows, list) and len(workflows) >= 7, f"interaction map workflows missing: {data}")
    ids = {str(item.get("id")) for item in workflows if isinstance(item, dict)}
    for required in ("incoming_request", "official_notification", "inspection_preparation", "state_fee_payment", "fine_or_violation", "production_exchange"):
        expect(required in ids, f"interaction map workflow missing: {required}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "stored_file" not in exported, "interaction map exposes unsafe data")
    return ["interaction map=ok"]


def verify_interaction_map_docx(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/interaction/map.docx"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"interaction map docx failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"interaction map docx failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"interaction map docx request failed: {exc}") from exc
    expect(content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"interaction map docx content type mismatch: {content_type}")
    expect(len(raw) > 3000, "interaction map docx is empty")
    expect(raw[:2] == b"PK", "interaction map docx is not an Office zip package")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "stored_file" not in exported, "interaction map docx exposes unsafe data")
    return ["interaction map docx=ok"]


def verify_production_launch_bundle(base_url: str, token: str) -> list[str]:
    req = Request(urljoin(base_url, "api/production/launch-bundle.zip"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"production launch bundle failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"production launch bundle failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"production launch bundle request failed: {exc}") from exc
    expect(content_type == "application/zip", f"production launch bundle content type mismatch: {content_type}")
    expect(raw[:2] == b"PK", "production launch bundle is not a zip package")
    expected = {
        "README_LAUNCH_PACKET.txt",
        "company-platform.env.example",
        "company-access-matrix.json",
        "qurulush-company-access-matrix.docx",
        "production-plan.json",
        "qurulush-production-plan.docx",
        "production-evidence-register.json",
        "qurulush-production-evidence-register.docx",
        "production-request-pack.json",
        "qurulush-production-request-pack.docx",
        "production-official-letters.json",
        "qurulush-production-official-letters.docx",
        "dgask-interaction-map.json",
        "qurulush-dgask-interaction-map.docx",
        "future-roadmap.json",
        "production-action-board.json",
        "qurulush-production-action-board.docx",
        "production-launch-sequence.json",
        "qurulush-production-launch-sequence.docx",
        "production-remaining-work.json",
        "qurulush-production-remaining-work.docx",
        "production-top-actions.json",
        "qurulush-production-top-actions.docx",
        "production-alerts.json",
        "production-launch-checklist.json",
        "qurulush-production-launch-checklist.docx",
        "acceptance-passport.json",
        "qurulush-acceptance-passport.docx",
        "legal-verification-packet.json",
        "qurulush-legal-verification-packet.docx",
        "qa-evidence.json",
        "qurulush-qa-evidence.docx",
        "production-status-board.json",
        "qurulush-production-status-board.docx",
        "acceptance-evidence-current.json",
        "completion-audit-current.json",
    }
    with zipfile.ZipFile(BytesIO(raw)) as package:
        names = set(package.namelist())
        expect(expected.issubset(names), f"production launch bundle missing files: {sorted(expected - names)}")
        access_matrix = json.loads(package.read("company-access-matrix.json").decode("utf-8"))
        access_matrix_docx = package.read("qurulush-company-access-matrix.docx")
        plan = json.loads(package.read("production-plan.json").decode("utf-8"))
        evidence = json.loads(package.read("production-evidence-register.json").decode("utf-8"))
        evidence_docx = package.read("qurulush-production-evidence-register.docx")
        request_pack = json.loads(package.read("production-request-pack.json").decode("utf-8"))
        request_pack_docx = package.read("qurulush-production-request-pack.docx")
        official_letters = json.loads(package.read("production-official-letters.json").decode("utf-8"))
        official_letters_docx = package.read("qurulush-production-official-letters.docx")
        interaction_map = json.loads(package.read("dgask-interaction-map.json").decode("utf-8"))
        interaction_map_docx = package.read("qurulush-dgask-interaction-map.docx")
        future_roadmap = json.loads(package.read("future-roadmap.json").decode("utf-8"))
        action_board = json.loads(package.read("production-action-board.json").decode("utf-8"))
        action_board_docx = package.read("qurulush-production-action-board.docx")
        launch_sequence = json.loads(package.read("production-launch-sequence.json").decode("utf-8"))
        launch_sequence_docx = package.read("qurulush-production-launch-sequence.docx")
        remaining_work = json.loads(package.read("production-remaining-work.json").decode("utf-8"))
        remaining_work_docx = package.read("qurulush-production-remaining-work.docx")
        top_actions = json.loads(package.read("production-top-actions.json").decode("utf-8"))
        top_actions_docx = package.read("qurulush-production-top-actions.docx")
        production_alerts = json.loads(package.read("production-alerts.json").decode("utf-8"))
        legal = json.loads(package.read("legal-verification-packet.json").decode("utf-8"))
        legal_docx = package.read("qurulush-legal-verification-packet.docx")
        account_cutover = json.loads(package.read("production-account-cutover.json").decode("utf-8"))
        account_cutover_docx = package.read("qurulush-production-account-cutover.docx")
        qa_evidence = json.loads(package.read("qa-evidence.json").decode("utf-8"))
        qa_evidence_docx = package.read("qurulush-qa-evidence.docx")
        status_board = json.loads(package.read("production-status-board.json").decode("utf-8"))
        status_board_docx = package.read("qurulush-production-status-board.docx")
        acceptance_evidence = json.loads(package.read("acceptance-evidence-current.json").decode("utf-8"))
        completion_audit = json.loads(package.read("completion-audit-current.json").decode("utf-8"))
    expect(access_matrix.get("format") == "qurulush-company-access-matrix-v1", "launch bundle access matrix format mismatch")
    expect(access_matrix_docx[:2] == b"PK", "launch bundle access matrix docx is not an Office zip package")
    expect(plan.get("format") == "qurulush-production-connection-plan-v1", "launch bundle production plan format mismatch")
    expect(evidence.get("format") == "qurulush-production-evidence-register-v1", "launch bundle production evidence format mismatch")
    expect(evidence_docx[:2] == b"PK", "launch bundle evidence docx is not an Office zip package")
    expect(request_pack.get("format") == "qurulush-production-request-pack-v1", "launch bundle production request pack format mismatch")
    expect(request_pack_docx[:2] == b"PK", "launch bundle request pack docx is not an Office zip package")
    expect(official_letters.get("format") == "qurulush-production-official-letters-v1", "launch bundle production official letters format mismatch")
    expect(official_letters_docx[:2] == b"PK", "launch bundle official letters docx is not an Office zip package")
    expect(interaction_map.get("format") == "qurulush-dgask-interaction-map-v1", "launch bundle interaction map format mismatch")
    expect(interaction_map_docx[:2] == b"PK", "launch bundle interaction map docx is not an Office zip package")
    expect(future_roadmap.get("format") == "qurulush-future-roadmap-v1", "launch bundle future roadmap format mismatch")
    future_module_ids = {str(item.get("id")) for item in future_roadmap.get("modules", []) if isinstance(item, dict)}
    expect({"field_mobile_app", "kg_payment_orchestration"}.issubset(future_module_ids), "launch bundle future roadmap missing mobile/payment modules")
    expect(action_board.get("format") == "qurulush-production-action-board-v1", "launch bundle production action board format mismatch")
    expect(action_board_docx[:2] == b"PK", "launch bundle action board docx is not an Office zip package")
    expect(launch_sequence.get("format") == "qurulush-production-launch-sequence-v1", "launch bundle production launch sequence format mismatch")
    expect(launch_sequence_docx[:2] == b"PK", "launch bundle launch sequence docx is not an Office zip package")
    expect(remaining_work.get("format") == "qurulush-production-remaining-work-v1", "launch bundle production remaining work format mismatch")
    expect(remaining_work_docx[:2] == b"PK", "launch bundle remaining work docx is not an Office zip package")
    expect(top_actions.get("format") == "qurulush-production-top-actions-v1", "launch bundle production top actions format mismatch")
    expect(top_actions_docx[:2] == b"PK", "launch bundle top actions docx is not an Office zip package")
    expect(production_alerts.get("format") == "qurulush-production-alerts-v1", "launch bundle production alerts format mismatch")
    expect(account_cutover.get("format") == "qurulush-production-account-cutover-v1", "launch bundle production account cutover format mismatch")
    expect(account_cutover_docx[:2] == b"PK", "launch bundle account cutover docx is not an Office zip package")
    expect(legal.get("format") == "qurulush-legal-verification-packet-v1", "launch bundle legal packet format mismatch")
    expect(legal_docx[:2] == b"PK", "launch bundle legal docx is not an Office zip package")
    expect(qa_evidence.get("format") == "qurulush-production-qa-evidence-v1", "launch bundle qa evidence format mismatch")
    expect(qa_evidence_docx[:2] == b"PK", "launch bundle qa evidence docx is not an Office zip package")
    expect(status_board.get("format") == "qurulush-production-status-board-v1", "launch bundle status board format mismatch")
    expect(status_board_docx[:2] == b"PK", "launch bundle status board docx is not an Office zip package")
    expect(acceptance_evidence.get("format") == "qurulush-acceptance-evidence-view-v1", "launch bundle acceptance evidence format mismatch")
    expect(completion_audit.get("format") == "qurulush-completion-audit-view-v1", "launch bundle completion audit format mismatch")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "stored_file" not in exported, "production launch bundle exposes unsafe data")
    return ["production launch bundle=ok"]


def verify_acceptance_evidence(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/acceptance/evidence"), token=token)
    expect(status == 200 and result.get("ok"), f"acceptance evidence failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-acceptance-evidence-view-v1", f"acceptance evidence format mismatch: {data}")
    expect("available" in data and "failed_stages" in data and "commands" in data, f"acceptance evidence fields missing: {data}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "official-sacc2-key-2026" not in exported and "stored_file" not in exported, "acceptance evidence exposes unsafe data")

    req = Request(urljoin(base_url, "api/acceptance/evidence.json"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"acceptance evidence JSON failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"acceptance evidence JSON failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"acceptance evidence JSON request failed: {exc}") from exc
    expect(content_type == "application/json; charset=utf-8", f"acceptance evidence JSON content type mismatch: {content_type}")
    downloaded = json.loads(raw.decode("utf-8"))
    expect(downloaded.get("format") == "qurulush-acceptance-evidence-view-v1", "acceptance evidence JSON format mismatch")
    exported_doc = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported_doc and "token_hash" not in exported_doc and "official-sacc2-key-2026" not in exported_doc and "stored_file" not in exported_doc, "acceptance evidence JSON exposes unsafe data")
    return [f"acceptance evidence available={data.get('available')} ok={data.get('ok')}"]


def verify_completion_audit(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/acceptance/completion-audit"), token=token)
    expect(status == 200 and result.get("ok"), f"completion audit failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-completion-audit-view-v1", f"completion audit format mismatch: {data}")
    expect("local_handoff_ready" in data and "production_ready" in data and "checks" in data, f"completion audit fields missing: {data}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "official-sacc2-key-2026" not in exported and "stored_file" not in exported, "completion audit exposes unsafe data")

    req = Request(urljoin(base_url, "api/acceptance/completion-audit.json"), headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"completion audit JSON failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"completion audit JSON failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"completion audit JSON request failed: {exc}") from exc
    expect(content_type == "application/json; charset=utf-8", f"completion audit JSON content type mismatch: {content_type}")
    downloaded = json.loads(raw.decode("utf-8"))
    expect(downloaded.get("format") == "qurulush-completion-audit-view-v1", "completion audit JSON format mismatch")
    exported_doc = raw.decode("utf-8", "ignore").lower()
    expect("demo2026" not in exported_doc and "token_hash" not in exported_doc and "official-sacc2-key-2026" not in exported_doc and "stored_file" not in exported_doc, "completion audit JSON exposes unsafe data")
    return [f"completion audit local_handoff={data.get('local_handoff_ready')} production_ready={data.get('production_ready')}"]


def verify_calendar(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/calendar"), token=token)
    expect(status == 200 and result.get("ok"), f"calendar failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-calendar-v1", f"calendar format mismatch: {data}")
    items = data.get("items", [])
    expect(isinstance(items, list), f"calendar items invalid: {data}")
    expect(int(data.get("open_count") or 0) >= 1, f"calendar should expose open items: {data}")
    kinds = {str(item.get("kind")) for item in items if isinstance(item, dict)}
    expect("Поручение" in kinds and "Запрос" in kinds, f"calendar missing task/request deadlines: {kinds}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "stored_file" not in exported, "calendar exposes unsafe data")
    return [f"calendar open={data.get('open_count')}"]


def verify_internal_chat(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/chat"), token=token)
    expect(status == 200 and result.get("ok"), f"chat failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-internal-chat-v1", f"chat format mismatch: {data}")
    status, posted = request_json(
        urljoin(base_url, "api/chat"),
        "POST",
        token=token,
        payload={"message": "Что сегодня срочно по срокам и ДГАСК?", "object": 1},
    )
    expect(status == 201 and posted.get("ok"), f"chat post failed: {status} {posted}")
    assistant = posted.get("assistant", {})
    expect("срок" in str(assistant.get("text", "")).lower(), f"AI chat did not answer about deadlines: {assistant}")
    exported = json.dumps(posted, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "stored_file" not in exported, "chat exposes unsafe data")
    return ["internal chat AI=ok"]


def verify_future_roadmap(base_url: str, token: str) -> list[str]:
    status, result = request_json(urljoin(base_url, "api/production/future-roadmap"), token=token)
    expect(status == 200 and result.get("ok"), f"future roadmap failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-future-roadmap-v1", f"future roadmap format mismatch: {data}")
    module_ids = {str(item.get("id")) for item in data.get("modules", []) if isinstance(item, dict)}
    expect({"field_mobile_app", "kg_payment_orchestration"}.issubset(module_ids), f"future roadmap modules missing: {module_ids}")
    exported = json.dumps(data, ensure_ascii=False).lower()
    expect("demo2026" not in exported and "token_hash" not in exported and "stored_file" not in exported, "future roadmap exposes unsafe data")
    return ["future roadmap mobile/payments=ok"]


def verify_deployment_files_bundle(base_url: str, token: str) -> list[str]:
    payload = json.dumps({"domain": "cabinet.builder.kg", "admin_email": "owner@builder.kg", "port": 8781}, ensure_ascii=False).encode("utf-8")
    req = Request(
        urljoin(base_url, "api/production/deployment-files.zip"),
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as res:
            raw = res.read()
            content_type = res.headers.get("Content-Type", "")
            expect(res.status == 200, f"deployment files bundle failed: {res.status}")
    except HTTPError as exc:
        raise RuntimeError(f"deployment files bundle failed: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"deployment files bundle request failed: {exc}") from exc
    expect(content_type == "application/zip", f"deployment files bundle content type mismatch: {content_type}")
    expect(raw[:2] == b"PK", "deployment files bundle is not a zip package")
    with zipfile.ZipFile(BytesIO(raw)) as package:
        names = set(package.namelist())
        expected = {"README_DEPLOYMENT_FILES.txt", "qurulush-hub.service", "nginx-qurulush-hub.conf", "go-no-go-command.sh", "DEPLOYMENT_SUMMARY.json"}
        expect(names == expected, f"deployment files bundle names mismatch: {sorted(names)}")
        nginx = package.read("nginx-qurulush-hub.conf").decode("utf-8")
        go_no_go = package.read("go-no-go-command.sh").decode("utf-8")
        summary = json.loads(package.read("DEPLOYMENT_SUMMARY.json").decode("utf-8"))
    expect("server_name cabinet.builder.kg" in nginx, "deployment nginx domain missing")
    expect("--hook-contract-smoke" in go_no_go, "deployment go/no-go hook smoke flag missing")
    expect(summary.get("domain") == "cabinet.builder.kg", "deployment summary domain mismatch")
    exported = raw.decode("utf-8", "ignore").lower()
    expect("company.example" not in exported and "demo2026" not in exported and "token_hash" not in exported, "deployment files bundle exposes unsafe data")
    return ["deployment files bundle=ok"]


def verify_domain_https_validation(base_url: str, token: str) -> list[str]:
    status, result = request_json(
        urljoin(base_url, "api/production/domain/validate"),
        "POST",
        token=token,
        payload={"domain": "cabinet.builder.kg", "public_url": "https://cabinet.builder.kg/", "port": 8781},
    )
    expect(status == 200 and result.get("ok"), f"domain HTTPS validation failed: {status} {result}")
    data = result.get("data", {})
    expect(data.get("format") == "qurulush-domain-https-validation-v1", f"domain HTTPS validation format mismatch: {data}")
    expect(data.get("ready_for_deployment_files") is True, f"domain HTTPS validation should accept production-looking domain: {data}")
    confirmations = data.get("required_confirmations", [])
    confirmation_ids = {str(item.get("id")) for item in confirmations if isinstance(item, dict)}
    expect("dns_a_record" in confirmation_ids and "tls_certificate" in confirmation_ids, f"domain HTTPS confirmations missing: {confirmations}")
    return ["domain HTTPS validation=ok"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check a deployed Qurulush Hub company platform")
    parser.add_argument("--base-url", required=True, help="Example: https://company.example/")
    parser.add_argument("--email", required=True, help="Director/bootstrap admin email")
    parser.add_argument("--password", required=True, help="Director/bootstrap admin password")
    parser.add_argument("--require-production", action="store_true", help="Fail unless /api/readiness reports production_ready=true")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/") + "/"
    checks: list[str] = []

    status, health = request_json(urljoin(base_url, "api/health"))
    expect(status == 200 and health.get("ok"), f"health failed: {status} {health}")
    expect(health.get("db_ready") is True, f"health db_ready failed: {health}")
    expect(health.get("storage") == "sqlite", f"health storage marker missing: {health}")
    expect("db" not in health, "health exposes internal database path")
    checks.append(f"health scheme={health.get('scheme')}")

    status, login = request_json(urljoin(base_url, "api/auth/login"), "POST", payload={"email": args.email, "password": args.password})
    expect(status == 200 and login.get("token"), f"login failed: {status} {login}")
    token = str(login["token"])
    checks.append(f"login user={login.get('user', {}).get('email')}")

    status, readiness_res = request_json(urljoin(base_url, "api/readiness"), token=token)
    expect(status == 200 and readiness_res.get("ok"), f"readiness failed: {status} {readiness_res}")
    readiness = readiness_res.get("data", {})
    expect(readiness.get("local_ready"), "readiness local_ready is false")
    checks.extend(assert_local_readiness_gates(readiness))
    checks.append(f"readiness local_ready={readiness.get('local_ready')} production_ready={readiness.get('production_ready')}")
    checks.extend(verify_session_control(base_url, token))
    checks.extend(verify_access_matrix(base_url, token))
    checks.extend(verify_access_matrix_docx(base_url, token))
    checks.extend(verify_production_plan(base_url, token, args.require_production))
    checks.extend(verify_production_evidence_register(base_url, token))
    checks.extend(verify_production_evidence_docx(base_url, token))
    checks.extend(verify_production_request_pack(base_url, token))
    checks.extend(verify_production_request_pack_docx(base_url, token))
    checks.extend(verify_production_official_letters(base_url, token))
    checks.extend(verify_production_official_letters_docx(base_url, token))
    checks.extend(verify_production_request_tracker(base_url, token))
    checks.extend(verify_production_action_board(base_url, token))
    checks.extend(verify_production_action_board_docx(base_url, token))
    checks.extend(verify_production_launch_sequence(base_url, token))
    checks.extend(verify_production_launch_sequence_docx(base_url, token))
    checks.extend(verify_production_remaining_work(base_url, token))
    checks.extend(verify_production_remaining_work_docx(base_url, token))
    checks.extend(verify_production_top_actions(base_url, token))
    checks.extend(verify_production_top_actions_docx(base_url, token))
    checks.extend(verify_production_alerts(base_url, token))
    checks.extend(verify_production_qa_evidence(base_url, token))
    checks.extend(verify_production_status_board(base_url, token))
    checks.extend(verify_acceptance_evidence(base_url, token))
    checks.extend(verify_completion_audit(base_url, token))
    checks.extend(verify_calendar(base_url, token))
    checks.extend(verify_internal_chat(base_url, token))
    checks.extend(verify_future_roadmap(base_url, token))
    checks.extend(verify_production_account_cutover(base_url, token))
    checks.extend(verify_production_env_example(base_url, token))
    checks.extend(verify_production_env_validation(base_url, token))
    checks.extend(verify_auth_cutover_validation(base_url, token))
    checks.extend(verify_hook_contract_validation(base_url, token))
    checks.extend(verify_sacc2_exchange_validation(base_url, token))
    checks.extend(verify_sacc2_public_status(base_url, token))
    checks.extend(verify_sacc2_public_status_docx(base_url, token))
    checks.extend(verify_sacc2_public_status_attachment(base_url, token))
    checks.extend(verify_eds_integration_validation(base_url, token))
    checks.extend(verify_payment_gateway_validation(base_url, token))
    checks.extend(verify_storage_integration_validation(base_url, token))
    checks.extend(verify_av_scanner_validation(base_url, token))
    checks.extend(verify_backup_schedule_validation(base_url, token))
    checks.extend(verify_backup_remote_validation(base_url, token))
    checks.extend(verify_production_cutover_validation(base_url, token))
    checks.extend(verify_production_cutover_docx(base_url, token))
    checks.extend(verify_production_launch_checklist(base_url, token, args.require_production))
    checks.extend(verify_production_launch_checklist_docx(base_url, token))
    checks.extend(verify_legal_verification_packet(base_url, token))
    checks.extend(verify_legal_verification_packet_docx(base_url, token))
    checks.extend(verify_interaction_map(base_url, token))
    checks.extend(verify_interaction_map_docx(base_url, token))
    checks.extend(verify_production_launch_bundle(base_url, token))
    checks.extend(verify_deployment_files_bundle(base_url, token))
    checks.extend(verify_domain_https_validation(base_url, token))
    checks.extend(verify_latest_backup(base_url, token, args.require_production))
    checks.extend(verify_acceptance_passport(base_url, token, args.require_production))

    if args.require_production:
        blockers = production_blockers(readiness)
        expect(readiness.get("production_ready"), "production readiness failed: " + "; ".join(blockers))
        checks.append("production_ready=true")

    request_json(urljoin(base_url, "api/auth/logout"), "POST", token=token)
    print(json.dumps({"ok": True, "checks": checks}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
