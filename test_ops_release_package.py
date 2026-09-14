from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from ops.build_release_package import RELEASE_DIR, build_release, collect_release_files
from ops.deployment_audit import audit_deployment
from ops.release_acceptance_check import accept_release_package


ROOT = Path(__file__).resolve().parent


class ReleasePackageTest(unittest.TestCase):
    def test_collect_release_files_excludes_runtime_data(self) -> None:
        files = [path.relative_to(ROOT).as_posix() for path in collect_release_files(ROOT)]
        self.assertIn("company_platform_server.py", files)
        self.assertIn("HANDOFF_STATUS.md", files)
        self.assertIn("PROJECT_EXPORT.md", files)
        self.assertIn("MOBILE_FIELD_APP_PLAN.md", files)
        self.assertIn("KG_PAYMENT_ORCHESTRATION_PLAN.md", files)
        self.assertIn("company_platform_accessibility_smoke.mjs", files)
        self.assertIn("extracted_dgask/04_Строительная_компания.html", files)
        self.assertIn("ops/backup_restore_drill.py", files)
        self.assertIn("ops/collect_acceptance_evidence.py", files)
        self.assertIn("ops/go_no_go_check.py", files)
        self.assertIn("ops/deployment_audit.py", files)
        self.assertIn("ops/hook_contract_smoke.py", files)
        self.assertIn("ops/hook_examples/sacc2_sync_contract_example.py", files)
        self.assertIn("ops/hook_examples/av_scan_contract_example.py", files)
        self.assertIn("ops/render_deployment_files.py", files)
        self.assertIn("ops/hook_examples/README.md", files)
        self.assertIn("ops/production_smoke_check.py", files)
        self.assertIn("ops/release_acceptance_check.py", files)
        self.assertNotIn("company_platform.sqlite3", files)
        self.assertFalse(any(path.startswith("uploads/") for path in files))
        self.assertFalse(any(path.startswith("backups/") for path in files))
        self.assertFalse(any(path.startswith("outputs/") for path in files))
        self.assertFalse(any("__pycache__" in path for path in files))
        self.assertFalse(any(path.endswith((".png", ".jpg", ".jpeg", ".pdf", ".pyc")) for path in files))

    def test_build_release_package_contains_manifest_and_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_path, manifest_path, manifest = build_release(Path(tmp), ROOT, "qurulush-test-release.zip")
            self.assertTrue(package_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertTrue((Path(tmp) / "qurulush-hub-company-platform-current.zip").exists())
            self.assertTrue((Path(tmp) / "qurulush-hub-company-platform-current.manifest.json").exists())
            self.assertEqual(manifest["format"], "qurulush-release-manifest-v1")
            self.assertGreaterEqual(manifest["file_count"], 8)

            with zipfile.ZipFile(package_path) as package:
                names = set(package.namelist())
                self.assertIn(f"{RELEASE_DIR}/RELEASE_MANIFEST.json", names)
                self.assertIn(f"{RELEASE_DIR}/HANDOFF_STATUS.md", names)
                self.assertIn(f"{RELEASE_DIR}/PROJECT_EXPORT.md", names)
                self.assertIn(f"{RELEASE_DIR}/MOBILE_FIELD_APP_PLAN.md", names)
                self.assertIn(f"{RELEASE_DIR}/KG_PAYMENT_ORCHESTRATION_PLAN.md", names)
                self.assertIn(f"{RELEASE_DIR}/company_platform_server.py", names)
                self.assertIn(f"{RELEASE_DIR}/company_platform_accessibility_smoke.mjs", names)
                self.assertIn(f"{RELEASE_DIR}/extracted_dgask/04_Строительная_компания.html", names)
                self.assertIn(f"{RELEASE_DIR}/ops/README_PRODUCTION.md", names)
                self.assertIn(f"{RELEASE_DIR}/ops/backup_restore_drill.py", names)
                self.assertIn(f"{RELEASE_DIR}/ops/collect_acceptance_evidence.py", names)
                self.assertIn(f"{RELEASE_DIR}/ops/go_no_go_check.py", names)
                self.assertIn(f"{RELEASE_DIR}/ops/deployment_audit.py", names)
                self.assertIn(f"{RELEASE_DIR}/ops/hook_contract_smoke.py", names)
                self.assertIn(f"{RELEASE_DIR}/ops/hook_examples/sacc2_sync_contract_example.py", names)
                self.assertIn(f"{RELEASE_DIR}/ops/hook_examples/av_scan_contract_example.py", names)
                self.assertIn(f"{RELEASE_DIR}/ops/render_deployment_files.py", names)
                self.assertIn(f"{RELEASE_DIR}/ops/release_acceptance_check.py", names)
                internal_manifest = json.loads(package.read(f"{RELEASE_DIR}/RELEASE_MANIFEST.json").decode("utf-8"))
            self.assertEqual(internal_manifest["file_count"], manifest["file_count"])

    def test_build_release_package_excludes_private_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_path, _, _ = build_release(Path(tmp), ROOT, "qurulush-test-release.zip")
            with zipfile.ZipFile(package_path) as package:
                names = package.namelist()
            joined = "\n".join(names)
            self.assertNotIn("company_platform.sqlite3", joined)
            self.assertNotIn("/uploads/", joined)
            self.assertNotIn("/backups/", joined)
            self.assertNotIn("__pycache__", joined)
            self.assertNotIn("company-platform-check.png", joined)

    def test_release_package_acceptance_check_preflights_unpacked_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_path, _, _ = build_release(root / "dist", ROOT, "qurulush-test-release.zip")
            result = accept_release_package(package_path, root / "acceptance", sys.executable)
            self.assertTrue(result["ok"])
            self.assertIn("manifest sha256", result["checks"])
            self.assertIn("local preflight", result["checks"])
            self.assertIn("deployment audit", result["checks"])

    def test_deployment_audit_accepts_current_release_layout(self) -> None:
        result = audit_deployment(ROOT)
        self.assertTrue(result["ok"], result)
        self.assertIn("layout_required_files", [item["id"] for item in result["checks"]])

    def test_deployment_audit_rejects_placeholder_env_and_open_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "company-platform.env"
            env_path.write_text(
                "\n".join(
                    [
                        "QH_BOOTSTRAP_ADMIN_EMAIL=owner@builder.kg",
                        "QH_BOOTSTRAP_ADMIN_PASSWORD=CHANGE_ME_STRONG_PASSWORD_16_PLUS_CHARS",
                        "QH_BOOTSTRAP_ADMIN_NAME=Director",
                        "QH_DISABLE_DEMO_USERS=1",
                        "QH_REQUIRE_PRODUCTION=1",
                        "QH_SACC2_API_URL=https://sacc2.avn.kg/api",
                        "QH_SACC2_API_KEY=short",
                        "QH_SACC2_SYNC_CMD=/opt/qurulush/bin/sync-sacc2 {payload}",
                        "QH_EDS_PROVIDER=CHANGE_ME_EDS_PROVIDER",
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
            result = audit_deployment(ROOT, env_path, require_production_config=True)
        self.assertFalse(result["ok"])
        self.assertIn("env_no_placeholders", result["failed_checks"])
        self.assertIn("env_secure_permissions", result["failed_checks"])

    def test_deployment_audit_rejects_example_hooks_in_production_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "company-platform.env"
            env_path.write_text(
                "\n".join(
                    [
                        "QH_BOOTSTRAP_ADMIN_EMAIL=owner@builder.kg",
                        "QH_BOOTSTRAP_ADMIN_PASSWORD=StrongBootstrap2026!",
                        "QH_BOOTSTRAP_ADMIN_NAME=Director",
                        "QH_DISABLE_DEMO_USERS=1",
                        "QH_REQUIRE_PRODUCTION=1",
                        "QH_REQUIRE_HOOK_JSON=1",
                        "QH_SACC2_API_URL=https://sacc2.avn.kg/api",
                        "QH_SACC2_API_KEY=kg-sacc2-key-2026-local-check",
                        "QH_SACC2_SYNC_CMD=/opt/qurulush-hub/ops/hook_examples/sacc2_sync_contract_example.py {payload}",
                        "QH_EDS_PROVIDER=kg-eds-provider-prod",
                        "QH_EDS_API_URL=https://eds.gov.kg/sign",
                        "QH_EDS_SIGN_CMD=/opt/qurulush/bin/sign-document {payload}",
                        "QH_PAYMENT_GATEWAY_URL=https://payments.bank.kg/api",
                        "QH_PAYMENT_GATEWAY_CMD=/opt/qurulush/bin/confirm-payment {payload}",
                        "QH_STORAGE_MODE=external",
                        "QH_STORAGE_URL=s3://company-documents/qurulush-hub",
                        "QH_STORAGE_SYNC_CMD=aws s3 cp {file} {storage_url}/{doc_id}/",
                        "QH_AV_SCANNER=clamscan --no-summary {file}",
                        "QH_BACKUP_INTERVAL_MINUTES=60",
                        "QH_BACKUP_REMOTE_URL=s3://company-secure-backups/qurulush-hub",
                        "QH_BACKUP_REMOTE_CMD=/opt/qurulush/bin/sync-backup {backup} {manifest}",
                        "QH_REFERENCE_VERIFIED_AT=2026-09-13",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(env_path, 0o600)
            result = audit_deployment(ROOT, env_path, require_production_config=True)
        self.assertFalse(result["ok"])
        self.assertIn("env_no_example_hooks", result["failed_checks"])

    def test_release_acceptance_rejects_tampered_archive_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_path, _, _ = build_release(root / "dist", ROOT, "qurulush-test-release.zip")
            tampered_path = root / "qurulush-test-release-tampered.zip"
            target = f"{RELEASE_DIR}/company_platform_server.py"
            with zipfile.ZipFile(package_path) as source, zipfile.ZipFile(tampered_path, "w", compression=zipfile.ZIP_DEFLATED) as tampered:
                for item in source.infolist():
                    raw = source.read(item.filename)
                    if item.filename == target:
                        raw += b"\n# tampered\n"
                    tampered.writestr(item, raw)
            with self.assertRaisesRegex(RuntimeError, "sha256 mismatch"):
                accept_release_package(tampered_path, root / "acceptance", sys.executable)


if __name__ == "__main__":
    unittest.main()
