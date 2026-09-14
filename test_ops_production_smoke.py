from __future__ import annotations

import unittest
from unittest.mock import patch

import ops.production_smoke_check as smoke
from ops.production_smoke_check import (
    LOCAL_REQUIRED_GATES,
    assert_acceptance_passport,
    assert_backup_verification,
    assert_local_readiness_gates,
    assert_production_launch_checklist,
    assert_production_plan,
    assert_session_control,
    production_blockers,
    select_latest_backup,
    verify_session_control,
    verify_production_top_actions,
    verify_production_top_actions_docx,
    verify_production_alerts,
    verify_sacc2_public_status,
    verify_sacc2_public_status_docx,
    verify_sacc2_public_status_attachment,
)


def readiness_with_local_gates(status: str = "pass") -> dict:
    return {
        "checks": [
            {"id": gate, "status": status, "detail": "ok"}
            for gate in LOCAL_REQUIRED_GATES
        ]
    }


class ProductionSmokeCheckTest(unittest.TestCase):
    def test_assert_local_readiness_gates_accepts_pass_and_warning(self) -> None:
        readiness = readiness_with_local_gates()
        readiness["checks"][-1]["status"] = "warning"
        checks = assert_local_readiness_gates(readiness)
        self.assertEqual(len(checks), len(LOCAL_REQUIRED_GATES))
        self.assertIn("local gate sqlite_integrity=pass", checks)
        self.assertIn("local gate backups=warning", checks)

    def test_assert_local_readiness_gates_rejects_missing_gate(self) -> None:
        readiness = readiness_with_local_gates()
        readiness["checks"] = readiness["checks"][:-1]
        with self.assertRaisesRegex(RuntimeError, "readiness local gates missing: backups"):
            assert_local_readiness_gates(readiness)

    def test_assert_local_readiness_gates_rejects_failed_or_missing_status(self) -> None:
        readiness = readiness_with_local_gates()
        readiness["checks"][0]["status"] = "missing"
        readiness["checks"][1]["status"] = "fail"
        with self.assertRaisesRegex(RuntimeError, "sqlite_integrity=missing"):
            assert_local_readiness_gates(readiness)

    def test_production_blockers_returns_only_required_non_pass_checks(self) -> None:
        readiness = {
            "checks": [
                {"id": "https", "status": "fail", "detail": "HTTP", "production_required": True},
                {"id": "manual_backup", "status": "warning", "detail": "local", "production_required": False},
                {"id": "eds", "status": "pass", "detail": "ok", "production_required": True},
            ]
        }
        self.assertEqual(production_blockers(readiness), ["https: HTTP"])

    def test_select_latest_backup_accepts_first_entry_and_allows_empty_non_production(self) -> None:
        latest = {"file": "company_platform_20260913.sqlite3"}
        self.assertEqual(select_latest_backup([latest, {"file": "old.sqlite3"}]), latest)
        self.assertIsNone(select_latest_backup([], require_existing=False))

    def test_select_latest_backup_requires_existing_backup_for_production(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no backups available"):
            select_latest_backup([], require_existing=True)

    def test_assert_backup_verification_requires_integrity_sha_and_counts(self) -> None:
        backup_file = "company_platform_20260913.sqlite3"
        result = assert_backup_verification(
            {
                "file": backup_file,
                "integrity": "PRAGMA quick_check: ok",
                "sha256": "a" * 64,
                "counts": {"objects": 3, "requests": 2},
            },
            backup_file,
        )
        self.assertEqual(result, f"backup verify {backup_file}=ok")
        with self.assertRaisesRegex(RuntimeError, "backup integrity failed"):
            assert_backup_verification(
                {
                    "file": backup_file,
                    "integrity": "PRAGMA quick_check: failed",
                    "sha256": "a" * 64,
                    "counts": {"objects": 3, "requests": 2},
                },
                backup_file,
            )

    def test_assert_acceptance_passport_checks_local_and_backup_status(self) -> None:
        checks = assert_acceptance_passport(
            {
                "format": "qurulush-acceptance-passport-v1",
                "local_acceptance": True,
                "production_acceptance": False,
                "backup_status": "pass",
                "readiness": {"local_ready": True},
                "production_blockers": ["sacc2_api"],
            }
        )
        self.assertIn("acceptance passport local=True", checks)
        self.assertIn("acceptance passport backup=pass", checks)
        with self.assertRaisesRegex(RuntimeError, "backup status failed"):
            assert_acceptance_passport(
                {
                    "format": "qurulush-acceptance-passport-v1",
                    "local_acceptance": False,
                    "production_acceptance": False,
                    "backup_status": "fail",
                    "readiness": {"local_ready": True},
                }
            )

    def test_assert_acceptance_passport_requires_production_when_requested(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "production acceptance failed"):
            assert_acceptance_passport(
                {
                    "format": "qurulush-acceptance-passport-v1",
                    "local_acceptance": True,
                    "production_acceptance": False,
                    "backup_status": "pass",
                    "readiness": {"local_ready": True},
                    "production_blockers": ["https"],
                },
                require_production=True,
            )

    def test_assert_session_control_requires_current_session_and_sanitized_payload(self) -> None:
        checks = assert_session_control(
            {
                "active_count": 2,
                "other_count": 1,
                "sessions": [
                    {"email": "director@company.kg", "role": "ceo", "current": True},
                    {"email": "engineer@company.kg", "role": "chief_engineer", "current": False},
                ],
            }
        )
        self.assertEqual(checks, ["sessions active=2", "sessions other=1"])
        with self.assertRaisesRegex(RuntimeError, "current session is not marked"):
            assert_session_control({"active_count": 1, "other_count": 0, "sessions": [{"current": False}]})
        with self.assertRaisesRegex(RuntimeError, "token_hash"):
            assert_session_control({"active_count": 1, "other_count": 0, "sessions": [{"current": True, "token_hash": "secret"}]})

    def test_verify_session_control_cleans_only_localhost_extra_sessions(self) -> None:
        calls = []

        def fake_request_json(url, method="GET", token=None, payload=None):
            calls.append((url, method, token, payload))
            if url.endswith("/api/sessions/revoke-others"):
                return 200, {"ok": True, "data": {"revoked_count": 1}}
            if url.endswith("/api/sessions") and len([call for call in calls if call[0].endswith("/api/sessions")]) == 1:
                return 200, {
                    "ok": True,
                    "data": {
                        "active_count": 2,
                        "other_count": 1,
                        "sessions": [{"current": True}, {"current": False}],
                    },
                }
            return 200, {
                "ok": True,
                "data": {
                    "active_count": 1,
                    "other_count": 0,
                    "sessions": [{"current": True}],
                },
            }

        with patch.object(smoke, "request_json", side_effect=fake_request_json):
            checks = verify_session_control("http://127.0.0.1:8782/", "TOKEN")

        self.assertIn("local session cleanup revoked=1", checks)
        self.assertIn("sessions cleaned active=1", checks)
        self.assertTrue(any(call[0].endswith("/api/sessions/revoke-others") for call in calls))

        remote_calls = []

        def fake_remote_request_json(url, method="GET", token=None, payload=None):
            remote_calls.append((url, method, token, payload))
            return 200, {
                "ok": True,
                "data": {
                    "active_count": 2,
                    "other_count": 1,
                    "sessions": [{"current": True}, {"current": False}],
                },
            }

        with patch.object(smoke, "request_json", side_effect=fake_remote_request_json):
            remote_checks = verify_session_control("https://company.example/", "TOKEN")

        self.assertEqual(remote_checks, ["sessions active=2", "sessions other=1"])
        self.assertFalse(any(call[0].endswith("/api/sessions/revoke-others") for call in remote_calls))

    def test_verify_sacc2_public_status_requires_safe_payload(self) -> None:
        def fake_request_json(url, method="GET", token=None, payload=None):
            return 200, {
                "ok": True,
                "data": {
                    "format": "qurulush-sacc2-public-status-v1",
                    "summary_status": "online",
                    "credentials_used": False,
                    "targets": [
                        {"url": "https://sacc2.avn.kg", "status": "external_error", "status_code": 502},
                        {"url": "https://sacc.avn.kg", "status": "online", "status_code": 200},
                    ],
                },
            }

        with patch.object(smoke, "request_json", side_effect=fake_request_json):
            self.assertEqual(verify_sacc2_public_status("http://127.0.0.1:8782/", "TOKEN"), ["sacc2 public status=online"])

        def unsafe_request_json(url, method="GET", token=None, payload=None):
            return 200, {
                "ok": True,
                "data": {
                    "format": "qurulush-sacc2-public-status-v1",
                    "summary_status": "online",
                    "credentials_used": False,
                    "api_key": "official-sacc2-key-2026",
                    "targets": [{"url": "https://sacc2.avn.kg", "status": "online", "status_code": 200}],
                },
            }

        with patch.object(smoke, "request_json", side_effect=unsafe_request_json):
            with self.assertRaisesRegex(RuntimeError, "unsafe data"):
                verify_sacc2_public_status("http://127.0.0.1:8782/", "TOKEN")

    def test_verify_sacc2_public_status_docx_requires_office_package(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"PK" + (b"x" * 3200)

        with patch.object(smoke, "urlopen", return_value=FakeResponse()):
            self.assertEqual(verify_sacc2_public_status_docx("http://127.0.0.1:8782/", "TOKEN"), ["sacc2 public status docx=ok"])

        class UnsafeResponse(FakeResponse):
            def read(self):
                return b"PK" + (b"x" * 3100) + b"api_key"

        with patch.object(smoke, "urlopen", return_value=UnsafeResponse()):
            with self.assertRaisesRegex(RuntimeError, "unsafe data"):
                verify_sacc2_public_status_docx("http://127.0.0.1:8782/", "TOKEN")

    def test_verify_production_top_actions_requires_short_safe_payload(self) -> None:
        payload = {
            "ok": True,
            "data": {
                "format": "qurulush-production-top-actions-v1",
                "production_ready": False,
                "actions": [{"id": "sacc2_api", "title": "Интеграция sacc2"}],
            },
        }
        with patch.object(smoke, "request_json", return_value=(200, payload)):
            self.assertEqual(verify_production_top_actions("http://127.0.0.1:8782/", "TOKEN"), ["production top actions=1"])

        unsafe_payload = {
            **payload,
            "data": {
                **payload["data"],
                "token_hash": "abc",
            },
        }
        with patch.object(smoke, "request_json", return_value=(200, unsafe_payload)):
            with self.assertRaisesRegex(RuntimeError, "unsafe data"):
                verify_production_top_actions("http://127.0.0.1:8782/", "TOKEN")

    def test_verify_production_top_actions_docx_requires_office_package(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"PK" + (b"x" * 3200)

        with patch.object(smoke, "urlopen", return_value=FakeResponse()):
            self.assertEqual(verify_production_top_actions_docx("http://127.0.0.1:8782/", "TOKEN"), ["production top actions docx=ok"])

        class UnsafeResponse(FakeResponse):
            def read(self):
                return b"PK" + (b"x" * 3100) + b"token_hash"

        with patch.object(smoke, "urlopen", return_value=UnsafeResponse()):
            with self.assertRaisesRegex(RuntimeError, "unsafe data"):
                verify_production_top_actions_docx("http://127.0.0.1:8782/", "TOKEN")

    def test_verify_production_alerts_requires_safe_payload(self) -> None:
        payload = {
            "ok": True,
            "data": {
                "format": "qurulush-production-alerts-v1",
                "alert_count": 1,
                "urgent_count": 1,
                "alerts": [{"id": "production:sacc2_api", "title": "Production: Интеграция sacc2", "urgent": True}],
            },
        }
        with patch.object(smoke, "request_json", return_value=(200, payload)):
            self.assertEqual(verify_production_alerts("http://127.0.0.1:8782/", "TOKEN"), ["production alerts=1"])

        unsafe_payload = {
            **payload,
            "data": {
                **payload["data"],
                "alerts": [{"id": "production:sacc2_api", "text": "official-sacc2-key-2026"}],
            },
        }
        with patch.object(smoke, "request_json", return_value=(200, unsafe_payload)):
            with self.assertRaisesRegex(RuntimeError, "unsafe data"):
                verify_production_alerts("http://127.0.0.1:8782/", "TOKEN")

        empty_alerts_payload = {
            "ok": True,
            "data": {
                "format": "qurulush-production-alerts-v1",
                "production_ready": False,
                "remaining_count": 3,
                "alert_count": 0,
                "urgent_count": 0,
                "alerts": [],
            },
        }
        with patch.object(smoke, "request_json", return_value=(200, empty_alerts_payload)):
            with self.assertRaisesRegex(RuntimeError, "at least one open launch warning"):
                verify_production_alerts("http://127.0.0.1:8782/", "TOKEN")

    def test_verify_sacc2_public_status_attachment_updates_tracker_safely(self) -> None:
        safe_payload = {
            "ok": True,
            "data": {
                "format": "qurulush-sacc2-public-status-attachment-v1",
                "attached_gate": "sacc2_api",
                "tracker_status": "blocked",
                "request_pack": {
                    "items": [
                        {"id": "sacc2_api", "outgoing_no": "SACC2-STATUS-20260913-101010"},
                    ]
                },
                "evidence": {
                    "items": [
                        {"id": "sacc2_api", "evidence": "Проверка sacc2. Пароли использованы: нет."},
                    ]
                },
            },
        }

        with patch.object(smoke, "request_json", return_value=(200, safe_payload)):
            self.assertEqual(
                verify_sacc2_public_status_attachment("http://127.0.0.1:8782/", "TOKEN"),
                ["sacc2 public status attachment=blocked"],
            )

        unsafe_payload = {
            **safe_payload,
            "data": {
                **safe_payload["data"],
                "api_key": "official-sacc2-key-2026",
            },
        }
        with patch.object(smoke, "request_json", return_value=(200, unsafe_payload)):
            with self.assertRaisesRegex(RuntimeError, "unsafe data"):
                verify_sacc2_public_status_attachment("http://127.0.0.1:8782/", "TOKEN")

    def test_assert_production_plan_requires_core_items(self) -> None:
        plan = {
            "format": "qurulush-production-connection-plan-v1",
            "production_ready": False,
            "blocker_count": 2,
            "items": [
                {"id": "hook_json_contracts"},
                {"id": "sacc2_api"},
                {"id": "eds"},
                {"id": "payments"},
                {"id": "object_storage"},
                {"id": "av_scan"},
                {"id": "backup_remote"},
                {"id": "reference_catalog"},
            ],
        }
        checks = assert_production_plan(plan)
        self.assertEqual(checks, ["production plan ready=False", "production plan blockers=2"])
        with self.assertRaisesRegex(RuntimeError, "production plan item missing: payments"):
            assert_production_plan({**plan, "items": [{"id": "hook_json_contracts"}, {"id": "sacc2_api"}, {"id": "eds"}]})
        with self.assertRaisesRegex(RuntimeError, "production plan is not ready"):
            assert_production_plan(plan, require_production=True)

    def test_assert_production_launch_checklist_requires_stages_and_commands(self) -> None:
        checklist = {
            "format": "qurulush-production-launch-checklist-v1",
            "production_ready": False,
            "blocker_count": 2,
            "stages": [
                {"id": "server_environment"},
                {"id": "external_integrations"},
                {"id": "backup_recovery"},
                {"id": "legal_catalog"},
                {"id": "final_acceptance"},
            ],
            "commands": [
                {"id": "preflight"},
                {"id": "live_smoke"},
                {"id": "go_no_go"},
            ],
        }
        checks = assert_production_launch_checklist(checklist)
        self.assertEqual(checks, ["production launch checklist ready=False", "production launch checklist blockers=2"])
        with self.assertRaisesRegex(RuntimeError, "production launch checklist stage missing: backup_recovery"):
            assert_production_launch_checklist({**checklist, "stages": [{"id": "server_environment"}, {"id": "external_integrations"}]})
        with self.assertRaisesRegex(RuntimeError, "production launch checklist command missing: go_no_go"):
            assert_production_launch_checklist({**checklist, "commands": [{"id": "preflight"}, {"id": "live_smoke"}]})
        with self.assertRaisesRegex(RuntimeError, "production launch checklist is not ready"):
            assert_production_launch_checklist(checklist, require_production=True)


if __name__ == "__main__":
    unittest.main()
