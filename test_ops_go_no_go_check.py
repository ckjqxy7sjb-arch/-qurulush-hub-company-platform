from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from ops.collect_acceptance_evidence import collect_acceptance_evidence, scrub_secrets, write_evidence_files
from ops.completion_audit import build_completion_audit
from ops.build_release_package import build_release
from ops.go_no_go_check import build_go_no_go_result, main, run_deployment_audit, run_hook_smoke, run_stage


ROOT = Path(__file__).resolve().parent
TEST_ACCEPTANCE_PASSWORD = "test-" + hashlib.sha256(str(ROOT).encode("utf-8")).hexdigest()[:20]


class GoNoGoCheckTest(unittest.TestCase):
    def test_run_stage_captures_success_and_failure(self) -> None:
        passed = run_stage("release", lambda: {"checks": ["ok"]})
        self.assertTrue(passed["ok"])
        self.assertEqual(passed["name"], "release")
        self.assertEqual(passed["result"]["checks"], ["ok"])

        failed = run_stage("smoke", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["name"], "smoke")
        self.assertIn("boom", failed["error"])

    def test_build_go_no_go_result_reports_failed_stages(self) -> None:
        result = build_go_no_go_result(
            [
                {"name": "release_acceptance", "ok": True, "result": {}},
                {"name": "live_smoke", "ok": False, "error": "health failed"},
            ]
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stages"], ["live_smoke"])
        self.assertIn("checked_at", result)

    def test_main_requires_at_least_one_check_source(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([]), 1)

    def test_run_deployment_audit_accepts_layout_stage(self) -> None:
        result = run_deployment_audit(ROOT)
        self.assertTrue(result["ok"])
        self.assertFalse(result["failed_checks"])

    def test_run_deployment_audit_rejects_bad_env_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "company-platform.env"
            env_path.write_text(
                "\n".join(
                    [
                        "QH_BOOTSTRAP_ADMIN_EMAIL=owner@builder.kg",
                        "QH_BOOTSTRAP_ADMIN_PASSWORD=CHANGE_ME",
                        "QH_BOOTSTRAP_ADMIN_NAME=Director",
                        "QH_DISABLE_DEMO_USERS=1",
                        "QH_REQUIRE_PRODUCTION=1",
                        "QH_SACC2_API_URL=https://sacc2.avn.kg/api",
                        "QH_SACC2_API_KEY=short",
                        "QH_SACC2_SYNC_CMD=/opt/qurulush/bin/sync-sacc2 {payload}",
                        "QH_EDS_PROVIDER=provider.example",
                        "QH_EDS_API_URL=https://eds.provider.example/sign",
                        "QH_EDS_SIGN_CMD=/opt/qurulush/bin/sign-document {payload}",
                        "QH_PAYMENT_GATEWAY_URL=https://payments.provider.example/api",
                        "QH_PAYMENT_GATEWAY_CMD=/opt/qurulush/bin/confirm-payment {payload}",
                        "QH_STORAGE_MODE=external",
                        "QH_STORAGE_URL=s3://company-documents/qurulush-hub",
                        "QH_STORAGE_SYNC_CMD=aws s3 cp {file} {storage_url}/{doc_id}/",
                        "QH_AV_SCANNER=clamscan --no-summary {file}",
                        "QH_BACKUP_INTERVAL_MINUTES=60",
                        "QH_BACKUP_REMOTE_URL=s3://company-secure-backups/qurulush-hub",
                        "QH_BACKUP_REMOTE_CMD=/opt/qurulush/bin/sync-backup {backup} {manifest}",
                        "QH_REFERENCE_VERIFIED_AT=YYYY-MM-DD",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(env_path, 0o644)
            with self.assertRaisesRegex(RuntimeError, "deployment audit failed"):
                run_deployment_audit(ROOT, env_path, require_production_config=True)

    def test_main_requires_env_for_strict_deployment_audit(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--deployment-root", str(ROOT), "--require-production-config"]), 1)
        self.assertIn("deployment_audit", output.getvalue())

    def test_main_requires_env_for_hook_contract_smoke(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--hook-contract-smoke"]), 1)
        self.assertIn("hook_contract_smoke", output.getvalue())

    def test_run_hook_smoke_accepts_example_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / "hooks.env"
            env_path.write_text(
                "\n".join(
                    [
                        f"QH_SACC2_SYNC_CMD=python3 {ROOT}/ops/hook_examples/sacc2_sync_contract_example.py {{payload}} {root}/sacc2",
                        f"QH_EDS_SIGN_CMD=python3 {ROOT}/ops/hook_examples/eds_sign_contract_example.py {{payload}} {root}/eds",
                        f"QH_PAYMENT_GATEWAY_CMD=python3 {ROOT}/ops/hook_examples/payment_confirm_contract_example.py {{payload}} {root}/payments",
                        f"QH_STORAGE_SYNC_CMD=python3 {ROOT}/ops/hook_examples/storage_sync_contract_example.py {{file}} {root}/storage/{{doc_id}}",
                        f"QH_AV_SCANNER=python3 {ROOT}/ops/hook_examples/av_scan_contract_example.py {{file}}",
                        f"QH_BACKUP_REMOTE_CMD=python3 {ROOT}/ops/hook_examples/backup_remote_contract_example.py {{backup}} {{manifest}} {root}/backup",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = run_hook_smoke(env_path)
        self.assertTrue(result["ok"])

    def test_collect_acceptance_evidence_redacts_password_and_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = collect_acceptance_evidence(
                base_url="http://127.0.0.1:9/",
                email="director@company.kg",
                password=TEST_ACCEPTANCE_PASSWORD,
            )
            self.assertEqual(payload["format"], "qurulush-acceptance-evidence-v1")
            self.assertFalse(payload["ok"])
            exported = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn(TEST_ACCEPTANCE_PASSWORD, exported)
            self.assertIn("REDACTED", exported)
            self.assertIn("live_smoke", payload["failed_stages"])
            timestamped, current = write_evidence_files(payload, output_dir)
            self.assertTrue(timestamped.exists())
            self.assertTrue(current.exists())
            saved = json.loads(current.read_text(encoding="utf-8"))
            self.assertEqual(saved["format"], "qurulush-acceptance-evidence-v1")

    def test_scrub_secrets_recurses_nested_payloads(self) -> None:
        scrubbed = scrub_secrets({"a": ["secret-value", {"b": "keep secret-value"}]}, ["secret-value"])
        self.assertEqual(scrubbed["a"][0], "REDACTED")
        self.assertEqual(scrubbed["a"][1]["b"], "keep REDACTED")

    def test_completion_audit_separates_local_handoff_from_external_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, _manifest, _release_manifest = build_release(root / "dist", ROOT, "completion-audit-test.zip")
            evidence = root / "acceptance-evidence-current.json"
            evidence.write_text(
                json.dumps(
                    {
                        "format": "qurulush-acceptance-evidence-v1",
                        "ok": True,
                        "failed_stages": [],
                        "go_no_go": {
                            "stages": [
                                {"name": "release_acceptance", "ok": True, "result": {"checks": ["required files"]}},
                                {
                                    "name": "live_smoke",
                                    "ok": True,
                                    "result": {
                                        "checks": [
                                            "readiness local_ready=True production_ready=False",
                                            "production plan blockers=12",
                                            "production remaining work steps=13",
                                        ]
                                    },
                                },
                                {"name": "backup_restore_drill", "ok": True, "result": {"ok": True}},
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = build_completion_audit(release, evidence, run_release_acceptance=True)
        self.assertTrue(result["local_handoff_ready"])
        self.assertFalse(result["production_ready"])
        self.assertEqual(result["overall_status"], "local_ready_external_blockers")
        checks = {item["id"]: item for item in result["checks"]}
        self.assertEqual(checks["production_external_gates"]["status"], "incomplete_external")
        exported = json.dumps(result, ensure_ascii=False).lower()
        self.assertNotIn("demo2026", exported)
        self.assertNotIn("token_hash", exported)


if __name__ == "__main__":
    unittest.main()
