from __future__ import annotations

import contextlib
import io
import json
import hashlib
import os
import shutil
import sqlite3
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from base64 import b64encode
from datetime import datetime, timezone
from io import BytesIO
from http.client import HTTPConnection
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

TEST_DEMO_PASSWORD = "test-" + hashlib.sha256(str(Path(__file__).resolve()).encode("utf-8")).hexdigest()[:20]
os.environ.setdefault("QH_DEMO_PASSWORD", TEST_DEMO_PASSWORD)

from company_platform_server import SCHEMA_VERSION, ApiError, backup_freshness_status, hash_token, init_db, main, make_server, parse_hook_json_output, sqlite_integrity_status


def raw_http_request(host: str, port: int, method: str, path: str, payload=None, token: str | None = None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn = HTTPConnection(host, port, timeout=5)
    conn.request(method, path, body=body, headers=headers)
    res = conn.getresponse()
    raw = res.read()
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = raw
    conn.close()
    return res.status, data


def complete_production_env_sample() -> str:
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


class BackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "test.sqlite3"
        cls.upload_root = Path(cls.tmp.name) / "uploads"
        cls.backup_root = Path(cls.tmp.name) / "backups"
        cls.server = make_server(
            "127.0.0.1",
            0,
            cls.db_path,
            upload_root=cls.upload_root,
            backup_root=cls.backup_root,
            quiet=True,
        )
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def request(self, method: str, path: str, payload=None, token: str | None = None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse()
        data = json.loads(res.read().decode("utf-8") or "{}")
        conn.close()
        return res.status, data

    def raw_request(self, method: str, path: str, token: str | None = None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request(method, path, headers=headers)
        res = conn.getresponse()
        body = res.read()
        response = {"status": res.status, "headers": dict(res.getheaders()), "body": body}
        conn.close()
        return response

    def login(self, email: str) -> str:
        status, data = self.request("POST", "/api/auth/login", {"email": email, "password": TEST_DEMO_PASSWORD})
        self.assertEqual(status, 200, data)
        return data["token"]

    def login_with_password(self, email: str, password: str) -> str:
        status, data = self.request("POST", "/api/auth/login", {"email": email, "password": password})
        self.assertEqual(status, 200, data)
        return data["token"]

    def test_health_and_login(self) -> None:
        status, data = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertTrue(data["db_ready"])
        self.assertEqual(data["storage"], "sqlite")
        self.assertNotIn("db", data)
        self.assertNotIn(str(self.db_path), json.dumps(data))
        status, data = self.request("POST", "/api/auth/login", {"email": "director@company.kg", "password": "wrong"})
        self.assertEqual(status, 401, data)
        token = self.login("director@company.kg")
        status, data = self.request("GET", "/api/state", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["role"], "ceo")
        self.assertNotIn("users", data["data"])

    def test_security_headers_are_sent_for_api_and_static_files(self) -> None:
        api = self.raw_request("GET", "/api/health")
        self.assertEqual(api["status"], 200)
        api_headers = {key.lower(): value for key, value in api["headers"].items()}
        self.assertEqual(api_headers["x-content-type-options"], "nosniff")
        self.assertEqual(api_headers["x-frame-options"], "SAMEORIGIN")
        self.assertEqual(api_headers["referrer-policy"], "strict-origin-when-cross-origin")
        self.assertIn("camera=()", api_headers["permissions-policy"])
        self.assertIn("object-src 'none'", api_headers["content-security-policy"])
        self.assertEqual(api_headers["cache-control"], "no-store")

        static = self.raw_request("GET", "/" + quote("04_Строительная_компания.html"))
        self.assertEqual(static["status"], 200)
        static_headers = {key.lower(): value for key, value in static["headers"].items()}
        self.assertEqual(static_headers["x-content-type-options"], "nosniff")
        self.assertIn("connect-src 'self'", static_headers["content-security-policy"])
        self.assertNotIn("strict-transport-security", static_headers)

    def test_json_body_size_limit_rejects_large_posts(self) -> None:
        with patch.dict(os.environ, {"QH_MAX_JSON_BYTES": "64"}, clear=False):
            status, data = self.request("POST", "/api/auth/login", {"email": "a" * 80, "password": TEST_DEMO_PASSWORD})
        self.assertEqual(status, 413, data)
        self.assertEqual(data["error"], "JSON payload is too large")

    def test_sqlite_integrity_status_rejects_corrupted_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "corrupted.sqlite3"
            db_path.write_bytes(b"this is not a sqlite database")
            ok, detail = sqlite_integrity_status(db_path)
        self.assertFalse(ok)
        self.assertIn("PRAGMA quick_check:", detail)

    def test_init_db_records_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "schema.sqlite3"
            init_db(db_path)
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], str(SCHEMA_VERSION))

    def test_backup_freshness_status_marks_stale_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backup_root = Path(tmp)
            stale = backup_root / "stale.sqlite3"
            stale.write_bytes(b"sqlite placeholder")
            old = time.time() - (3 * 24 * 60 * 60)
            os.utime(stale, (old, old))
            status, detail, counts = backup_freshness_status(backup_root)
        self.assertEqual(status, "fail")
        self.assertIn("Последний бэкап", detail)
        self.assertEqual(counts["total"], 1)

    def test_login_attempt_lockout_and_recovery(self) -> None:
        email = "engineer@company.kg"
        for _ in range(4):
            status, data = self.request("POST", "/api/auth/login", {"email": email, "password": "wrong"})
            self.assertEqual(status, 401, data)

        status, data = self.request("POST", "/api/auth/login", {"email": email, "password": "wrong"})
        self.assertEqual(status, 429, data)

        status, data = self.request("POST", "/api/auth/login", {"email": email, "password": TEST_DEMO_PASSWORD})
        self.assertEqual(status, 429, data)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE login_attempts SET locked_until = ? WHERE email = ?", (0, email))

        status, data = self.request("POST", "/api/auth/login", {"email": email, "password": TEST_DEMO_PASSWORD})
        self.assertEqual(status, 200, data)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT 1 FROM login_attempts WHERE email = ?", (email,)).fetchone()
        self.assertIsNone(row)

    def test_https_health_with_self_signed_certificate(self) -> None:
        openssl = shutil.which("openssl")
        if not openssl:
            self.skipTest("openssl is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert = root / "cert.pem"
            key = root / "key.pem"
            subprocess.run(
                [
                    openssl,
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            server = make_server(
                "127.0.0.1",
                0,
                root / "https.sqlite3",
                upload_root=root / "uploads",
                backup_root=root / "backups",
                tls_cert=cert,
                tls_key=key,
                quiet=True,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                ctx = ssl._create_unverified_context()
                with urlopen(f"https://{host}:{port}/api/health", context=ctx, timeout=5) as res:
                    headers = {key.lower(): value for key, value in res.headers.items()}
                    data = json.loads(res.read().decode("utf-8"))
                self.assertTrue(data["ok"])
                self.assertEqual(data["scheme"], "https")
                self.assertEqual(server.scheme, "https")
                self.assertIn("strict-transport-security", headers)
                self.assertEqual(headers["x-content-type-options"], "nosniff")
            finally:
                server.shutdown()
                server.server_close()

    def test_passwords_are_hashed_outside_app_state(self) -> None:
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            payload = conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()["payload"]
            user = conn.execute("SELECT password_salt, password_hash FROM users WHERE email = ?", ("director@company.kg",)).fetchone()
        finally:
            conn.close()

        self.assertNotIn(TEST_DEMO_PASSWORD, payload)
        self.assertNotIn('"users"', payload)
        self.assertEqual(len(user["password_salt"]), 32)
        self.assertEqual(len(user["password_hash"]), 64)
        self.assertNotEqual(user["password_hash"], TEST_DEMO_PASSWORD)

    def test_bootstrap_admin_can_replace_demo_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bootstrap.sqlite3"
            env = {
                "QH_BOOTSTRAP_ADMIN_EMAIL": "owner@builder.kg",
                "QH_BOOTSTRAP_ADMIN_PASSWORD": "StrongBootstrap2026!",
                "QH_BOOTSTRAP_ADMIN_NAME": "Боевой директор",
                "QH_DISABLE_DEMO_USERS": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                server = make_server("127.0.0.1", 0, db_path, upload_root=Path(tmp) / "uploads", backup_root=Path(tmp) / "backups", quiet=True)
                host, port = server.server_address
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "director@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 401, data)
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "owner@builder.kg", "password": "StrongBootstrap2026!"})
                    self.assertEqual(status, 200, data)
                    token = data["token"]
                    self.assertEqual(data["user"]["name"], "Боевой директор")
                    status, data = raw_http_request(host, port, "GET", "/api/readiness", token=token)
                    self.assertEqual(status, 200, data)
                    checks = {item["id"]: item for item in data["data"]["checks"]}
                    self.assertEqual(checks["corporate_auth"]["status"], "pass")
                    self.assertEqual(checks["bootstrap_admin"]["status"], "pass")
                    self.assertEqual(data["data"]["counts"]["bootstrap_admin"], 1)
                finally:
                    server.shutdown()
                    server.server_close()

    def test_require_production_blocks_incomplete_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"QH_REQUIRE_PRODUCTION": "1"}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "Production readiness failed"):
                    make_server(
                        "127.0.0.1",
                        0,
                        Path(tmp) / "blocked.sqlite3",
                        upload_root=Path(tmp) / "uploads",
                        backup_root=Path(tmp) / "backups",
                        quiet=True,
                    )

    def test_require_production_allows_complete_test_configuration(self) -> None:
        openssl = shutil.which("openssl")
        true_bin = shutil.which("true")
        if not openssl or not true_bin:
            self.skipTest("openssl or true is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert = root / "cert.pem"
            key = root / "key.pem"
            subprocess.run(
                [
                    openssl,
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            env = {
                "QH_BOOTSTRAP_ADMIN_EMAIL": "owner@builder.kg",
                "QH_BOOTSTRAP_ADMIN_PASSWORD": "StrongBootstrap2026!",
                "QH_BOOTSTRAP_ADMIN_NAME": "Боевой директор",
                "QH_DISABLE_DEMO_USERS": "1",
                "QH_REQUIRE_HOOK_JSON": "1",
                "QH_SACC2_API_URL": "https://sacc2.avn.kg/api",
                "QH_SACC2_API_KEY": "kg-sacc2-key-2026-local-check",
                "QH_SACC2_SYNC_CMD": f"{true_bin} {{payload}}",
                "QH_EDS_PROVIDER": "kg-eds-provider-prod",
                "QH_EDS_API_URL": "https://eds.gov.kg/sign",
                "QH_EDS_SIGN_CMD": f"{true_bin} {{payload}}",
                "QH_PAYMENT_GATEWAY_URL": "https://payments.bank.kg/api",
                "QH_PAYMENT_GATEWAY_CMD": f"{true_bin} {{payload}}",
                "QH_STORAGE_MODE": "external",
                "QH_STORAGE_URL": "s3://company-documents/qurulush-hub",
                "QH_STORAGE_SYNC_CMD": f"{true_bin} {{file}}",
                "QH_AV_SCANNER": true_bin,
                "QH_BACKUP_INTERVAL_SECONDS": "3600",
                "QH_BACKUP_REMOTE_URL": "s3://company-secure-backups/qurulush-hub",
                "QH_BACKUP_REMOTE_CMD": f"{true_bin} {{backup}} {{manifest}}",
                "QH_REFERENCE_VERIFIED_AT": "2026-09-13",
            }
            with patch.dict(os.environ, env, clear=True):
                server = make_server(
                    "127.0.0.1",
                    0,
                    root / "production.sqlite3",
                    upload_root=root / "uploads",
                    backup_root=root / "backups",
                    tls_cert=cert,
                    tls_key=key,
                    quiet=True,
                    require_production=True,
                )
                try:
                    self.assertEqual(server.scheme, "https")
                finally:
                    server.server_close()

    def test_preflight_require_production_reports_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"QH_REQUIRE_PRODUCTION": "1"}, clear=True):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(
                        [
                            "--preflight",
                            "--require-production",
                            "--db",
                            str(root / "preflight.sqlite3"),
                            "--uploads",
                            str(root / "uploads"),
                            "--backups",
                            str(root / "backups"),
                        ]
                    )
            self.assertEqual(code, 2)
            self.assertIn("production_ready: no", stdout.getvalue())
            self.assertIn("production_blockers:", stdout.getvalue())
            self.assertIn("Production readiness failed", stderr.getvalue())

    def test_preflight_json_outputs_machine_readable_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--preflight-json",
                        "--db",
                        str(root / "preflight-json.sqlite3"),
                        "--uploads",
                        str(root / "uploads"),
                        "--backups",
                        str(root / "backups"),
                    ]
                )
        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        checks = {item["id"]: item for item in report["checks"]}
        self.assertTrue(report["local_ready"], report)
        self.assertFalse(report["production_ready"], report)
        self.assertEqual(checks["sqlite_integrity"]["status"], "pass")
        self.assertEqual(checks["schema_version"]["status"], "pass")
        self.assertEqual(checks["session_maintenance"]["status"], "pass")
        self.assertEqual(report["counts"]["schema_version"], str(SCHEMA_VERSION))

    def test_preflight_rejects_missing_hook_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "QH_SACC2_API_URL": "https://sacc2.avn.kg/api",
                "QH_SACC2_API_KEY": "kg-sacc2-key-2026-local-check",
                "QH_SACC2_SYNC_CMD": "/definitely/missing/sync-sacc2 {payload}",
            }
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, env, clear=True):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(
                        [
                            "--preflight",
                            "--require-production",
                            "--db",
                            str(root / "preflight.sqlite3"),
                            "--uploads",
                            str(root / "uploads"),
                            "--backups",
                            str(root / "backups"),
                        ]
                    )
            self.assertEqual(code, 2)
            self.assertIn("Команда не найдена: /definitely/missing/sync-sacc2", stdout.getvalue())
            self.assertIn("sacc2_api", stderr.getvalue())

    def test_preflight_rejects_placeholder_production_values(self) -> None:
        true_bin = shutil.which("true")
        if not true_bin:
            self.skipTest("true is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "QH_SACC2_API_URL": "https://sacc2.example.test/api",
                "QH_SACC2_API_KEY": "secret",
                "QH_SACC2_SYNC_CMD": f"{true_bin} {{payload}}",
            }
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, env, clear=True):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(
                        [
                            "--preflight",
                            "--require-production",
                            "--db",
                            str(root / "preflight.sqlite3"),
                            "--uploads",
                            str(root / "uploads"),
                            "--backups",
                            str(root / "backups"),
                        ]
                    )
            self.assertEqual(code, 2)
            self.assertIn("production_env_values", stdout.getvalue())
            self.assertIn("QH_SACC2_API_KEY слишком короткий", stdout.getvalue())
            self.assertIn("QH_SACC2_API_URL", stdout.getvalue())

    def test_strict_hook_json_contract_accepts_status_and_rejects_empty_output(self) -> None:
        with patch.dict(os.environ, {"QH_REQUIRE_HOOK_JSON": "1"}, clear=False):
            info = parse_hook_json_output('{"status":"synced","external_id":"DGASK-42"}', "sacc2", {"ok", "synced"})
            self.assertEqual(info["sacc2_status"], "synced")
            self.assertEqual(info["sacc2_external_id"], "DGASK-42")
            with self.assertRaises(ApiError):
                parse_hook_json_output("", "sacc2", {"ok", "synced"})
            with self.assertRaises(ApiError):
                parse_hook_json_output('{"status":"rejected"}', "sacc2", {"ok", "synced"})

    def test_preflight_require_production_passes_complete_test_configuration(self) -> None:
        openssl = shutil.which("openssl")
        true_bin = shutil.which("true")
        if not openssl or not true_bin:
            self.skipTest("openssl or true is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert = root / "cert.pem"
            key = root / "key.pem"
            subprocess.run(
                [
                    openssl,
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            env = {
                "QH_BOOTSTRAP_ADMIN_EMAIL": "owner@builder.kg",
                "QH_BOOTSTRAP_ADMIN_PASSWORD": "StrongBootstrap2026!",
                "QH_BOOTSTRAP_ADMIN_NAME": "Боевой директор",
                "QH_DISABLE_DEMO_USERS": "1",
                "QH_REQUIRE_HOOK_JSON": "1",
                "QH_SACC2_API_URL": "https://sacc2.avn.kg/api",
                "QH_SACC2_API_KEY": "kg-sacc2-key-2026-local-check",
                "QH_SACC2_SYNC_CMD": f"{true_bin} {{payload}}",
                "QH_EDS_PROVIDER": "kg-eds-provider-prod",
                "QH_EDS_API_URL": "https://eds.gov.kg/sign",
                "QH_EDS_SIGN_CMD": f"{true_bin} {{payload}}",
                "QH_PAYMENT_GATEWAY_URL": "https://payments.bank.kg/api",
                "QH_PAYMENT_GATEWAY_CMD": f"{true_bin} {{payload}}",
                "QH_STORAGE_MODE": "external",
                "QH_STORAGE_URL": "s3://company-documents/qurulush-hub",
                "QH_STORAGE_SYNC_CMD": f"{true_bin} {{file}}",
                "QH_AV_SCANNER": true_bin,
                "QH_BACKUP_INTERVAL_SECONDS": "3600",
                "QH_BACKUP_REMOTE_URL": "s3://company-secure-backups/qurulush-hub",
                "QH_BACKUP_REMOTE_CMD": f"{true_bin} {{backup}} {{manifest}}",
                "QH_REFERENCE_VERIFIED_AT": "2026-09-13",
            }
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, env, clear=True):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(
                        [
                            "--preflight",
                            "--require-production",
                            "--db",
                            str(root / "preflight-production.sqlite3"),
                            "--uploads",
                            str(root / "uploads"),
                            "--backups",
                            str(root / "backups"),
                            "--tls-cert",
                            str(cert),
                            "--tls-key",
                            str(key),
                        ]
                    )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertIn("scheme: https", stdout.getvalue())
            self.assertIn("production_ready: yes", stdout.getvalue())
            self.assertIn("production_blockers: none", stdout.getvalue())

    def test_readiness_report_requires_director_and_lists_production_gates(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/readiness")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/readiness", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/readiness", token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        checks = {item["id"]: item for item in report["checks"]}
        self.assertTrue(report["local_ready"], report)
        self.assertFalse(report["production_ready"], report)
        self.assertEqual(checks["sqlite_integrity"]["status"], "pass")
        self.assertEqual(checks["sqlite_integrity"]["detail"], "PRAGMA quick_check: ok")
        self.assertEqual(checks["db_schema"]["status"], "pass")
        self.assertEqual(checks["schema_version"]["status"], "pass")
        self.assertEqual(report["counts"]["schema_version"], str(SCHEMA_VERSION))
        self.assertEqual(checks["password_storage"]["status"], "pass")
        self.assertEqual(checks["session_maintenance"]["status"], "pass")
        self.assertEqual(report["counts"]["expired_active_sessions"], 0)
        self.assertIn(checks["backup_manifests"]["status"], {"pass", "warning"})
        self.assertIn(checks["backup_freshness"]["status"], {"pass", "warning"})
        self.assertIn(checks["https"]["status"], {"pass", "warning"})
        self.assertEqual(checks["hook_json_contracts"]["status"], "missing")
        self.assertEqual(checks["sacc2_api"]["status"], "missing")
        self.assertEqual(checks["eds"]["status"], "missing")
        self.assertEqual(checks["payments"]["status"], "missing")
        self.assertEqual(checks["reference_catalog"]["status"], "warning")
        self.assertGreaterEqual(report["counts"]["tasks"], 3)
        self.assertGreaterEqual(report["counts"]["reference_items"], 8)
        self.assertEqual(report["checked_by"], "Замирбек уулу Максат")

    def test_access_matrix_requires_director_and_exports_role_docx(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/access/matrix")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/access/matrix", token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("GET", "/api/access/matrix", token=director)
        self.assertEqual(status, 200, data)
        matrix = data["data"]
        self.assertEqual(matrix["format"], "qurulush-company-access-matrix-v1")
        self.assertEqual(matrix["role_count"], 6)
        roles = {item["id"]: item for item in matrix["roles"]}
        self.assertIn("ceo", roles)
        self.assertIn("foreman", roles)
        self.assertIn("brigadier", roles)
        self.assertTrue(any(item["id"] == "team" and item["allowed"] for item in roles["ceo"]["actions"]))
        self.assertFalse(any(item["id"] == "team" and item["allowed"] for item in roles["brigadier"]["actions"]))
        self.assertIn("Исполнение поручений", roles["brigadier"]["responsibility"])

        response = self.raw_request("GET", "/api/access/matrix.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/access/matrix.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/access/matrix.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 3000)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Матрица доступа строительной компании", document_xml)
        self.assertIn("Прораб", document_xml)
        self.assertIn("Бригадир", document_xml)
        exported_text = json.dumps(matrix, ensure_ascii=False) + response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_production_plan_requires_director_and_maps_readiness_gates(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/plan")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/plan", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/production/plan", token=director)
        self.assertEqual(status, 200, data)
        plan = data["data"]
        self.assertEqual(plan["format"], "qurulush-production-connection-plan-v1")
        self.assertFalse(plan["production_ready"], plan)
        self.assertGreaterEqual(plan["blocker_count"], 1)
        self.assertIn("completion_percent", plan)
        self.assertGreaterEqual(plan["completion_percent"], 0)
        self.assertLessEqual(plan["completion_percent"], 100)
        self.assertGreaterEqual(plan["required_total"], plan["required_ready_count"])
        self.assertIsInstance(plan["next_step"], dict)
        self.assertIn("next_step", plan["next_step"])
        items = {item["id"]: item for item in plan["items"]}
        self.assertIn("hook_json_contracts", items)
        self.assertEqual(items["hook_json_contracts"]["status"], "missing")
        self.assertIn("sacc2_api", items)
        self.assertEqual(items["sacc2_api"]["status"], "missing")
        self.assertIn("QH_SACC2_API_URL", items["sacc2_api"]["variables"])
        self.assertIn("официальный API URL", items["sacc2_api"]["next_step"])
        self.assertIn("reference_catalog", items)
        self.assertIn("QH_REFERENCE_VERIFIED_AT", items["reference_catalog"]["variables"])
        exported_text = json.dumps(plan, ensure_ascii=False)
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_future_roadmap_requires_director_and_lists_mobile_and_payments(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/future-roadmap")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/future-roadmap", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/production/future-roadmap", token=director)
        self.assertEqual(status, 200, data)
        roadmap = data["data"]
        self.assertEqual(roadmap["format"], "qurulush-future-roadmap-v1")
        modules = {item["id"]: item for item in roadmap["modules"]}
        self.assertIn("field_mobile_app", modules)
        self.assertIn("kg_payment_orchestration", modules)
        self.assertTrue(any("/api/tasks/{id}/update" in item for item in modules["field_mobile_app"]["integration_contract"]))
        self.assertTrue(any("НБКР" in item["title"] for item in modules["kg_payment_orchestration"]["official_sources"]))
        self.assertTrue(any("явного подтверждения" in item for item in modules["kg_payment_orchestration"]["controls"]))
        exported_text = json.dumps(roadmap, ensure_ascii=False)
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_production_qa_evidence_requires_director_and_exports_docx(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/qa-evidence")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/qa-evidence", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/production/qa-evidence", token=director)
        self.assertEqual(status, 200, data)
        evidence = data["data"]
        self.assertEqual(evidence["format"], "qurulush-production-qa-evidence-v1")
        self.assertTrue(evidence["working_link"].endswith("/04_Строительная_компания.html"))
        self.assertTrue(evidence["local_ready"], evidence)
        self.assertFalse(evidence["production_ready"], evidence)
        self.assertGreaterEqual(evidence["remaining_count"], 1)
        check_ids = {item["id"] for item in evidence["automated_checks"]}
        self.assertIn("backend_regression", check_ids)
        self.assertIn("browser_smoke", check_ids)
        self.assertIn("go_no_go", check_ids)
        self.assertIn("acceptance_evidence", check_ids)
        live_ids = {item["id"] for item in evidence["live_evidence"]}
        self.assertIn("working_link", live_ids)
        self.assertIn("acceptance_passport", live_ids)
        artifacts = {item["id"] for item in evidence["artifacts"]}
        self.assertIn("current_release_zip", artifacts)
        self.assertIn("test_report", artifacts)

        response = self.raw_request("GET", "/api/production/qa-evidence.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/qa-evidence.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/qa-evidence.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("QA evidence пакет", document_xml)
        self.assertIn("Backend/regression suite", document_xml)
        self.assertIn("go_no_go_check.py", document_xml)
        exported_text = json.dumps(evidence, ensure_ascii=False) + response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)
        self.assertNotIn("official-sacc2-key-2026", exported_text)

    def test_production_status_board_requires_director_and_exports_docx(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/status-board")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/status-board", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/production/status-board", token=director)
        self.assertEqual(status, 200, data)
        board = data["data"]
        self.assertEqual(board["format"], "qurulush-production-status-board-v1")
        self.assertTrue(board["working_link"].endswith("/04_Строительная_компания.html"))
        self.assertTrue(board["local_ready"], board)
        self.assertFalse(board["production_ready"], board)
        self.assertGreaterEqual(board["remaining_count"], 1)
        self.assertGreaterEqual(board["blocker_count"], 1)
        card_ids = {item["id"] for item in board["summary_cards"]}
        self.assertIn("working_link", card_ids)
        self.assertIn("qa", card_ids)
        self.assertIn("current_step", board)
        self.assertTrue(board["top_actions"], board)
        self.assertTrue(board["steps"], board)
        self.assertTrue(any(item["id"] == "go_no_go" for item in board["qa_checks"]))
        self.assertTrue(any(item["id"] == "acceptance_evidence" for item in board["qa_checks"]))
        self.assertTrue(any(item["id"] == "current_release_zip" for item in board["artifacts"]))

        response = self.raw_request("GET", "/api/production/status-board.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/status-board.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/status-board.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Статус запуска платформы", document_xml)
        self.assertIn("Ближайшие действия", document_xml)
        self.assertIn("Полный список открытых шагов", document_xml)
        self.assertIn("QA команды", document_xml)
        exported_text = json.dumps(board, ensure_ascii=False) + response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)
        self.assertNotIn("official-sacc2-key-2026", exported_text)

    def test_acceptance_evidence_requires_director_and_exports_sanitized_json(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/acceptance/evidence")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/acceptance/evidence", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/acceptance/evidence", token=director)
        self.assertEqual(status, 200, data)
        evidence = data["data"]
        self.assertEqual(evidence["format"], "qurulush-acceptance-evidence-view-v1")
        self.assertIn("available", evidence)
        self.assertIn("failed_stages", evidence)
        self.assertIn("commands", evidence)
        self.assertIn("artifacts", evidence)
        self.assertEqual(evidence["source"], "outputs/acceptance-evidence-current.json")

        response = self.raw_request("GET", "/api/acceptance/evidence.json")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/acceptance/evidence.json", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/acceptance/evidence.json", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/json; charset=utf-8")
        downloaded = json.loads(response["body"].decode("utf-8"))
        self.assertEqual(downloaded["format"], "qurulush-acceptance-evidence-view-v1")

        exported_text = json.dumps(evidence, ensure_ascii=False) + response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("demo2026", exported_text.lower())
        self.assertNotIn("token_hash", exported_text)
        self.assertNotIn("official-sacc2-key-2026", exported_text)
        self.assertNotIn("stored_file", exported_text)

    def test_completion_audit_requires_director_and_exports_sanitized_json(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/acceptance/completion-audit")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/acceptance/completion-audit", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/acceptance/completion-audit", token=director)
        self.assertEqual(status, 200, data)
        audit = data["data"]
        self.assertEqual(audit["format"], "qurulush-completion-audit-view-v1")
        self.assertIn("local_handoff_ready", audit)
        self.assertIn("production_ready", audit)
        self.assertIn("overall_status", audit)
        self.assertIn("checks", audit)
        self.assertEqual(audit["source"], "outputs/completion-audit-current.json")

        response = self.raw_request("GET", "/api/acceptance/completion-audit.json")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/acceptance/completion-audit.json", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/acceptance/completion-audit.json", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/json; charset=utf-8")
        downloaded = json.loads(response["body"].decode("utf-8"))
        self.assertEqual(downloaded["format"], "qurulush-completion-audit-view-v1")

        exported_text = json.dumps(audit, ensure_ascii=False) + response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("demo2026", exported_text.lower())
        self.assertNotIn("token_hash", exported_text)
        self.assertNotIn("official-sacc2-key-2026", exported_text)
        self.assertNotIn("stored_file", exported_text)

    def test_sacc2_public_status_requires_director_and_reports_external_errors(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/external/sacc2-status")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/external/sacc2-status", token=engineer)
        self.assertEqual(status, 403, data)

        class FakeResponse:
            status = 200

            def getcode(self):
                return 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(request, timeout=0):
            url = request.full_url
            if "sacc2.avn.kg" in url:
                raise HTTPError(url, 502, "Bad Gateway", hdrs=None, fp=None)
            return FakeResponse()

        with patch.dict(os.environ, {"QH_SACC2_PUBLIC_URLS": "https://sacc2.avn.kg,https://sacc.avn.kg,http://127.0.0.1:9000"}, clear=False):
            with patch("company_platform_server.urllib.request.urlopen", side_effect=fake_urlopen):
                status, data = self.request("GET", "/api/external/sacc2-status", token=director)

        self.assertEqual(status, 200, data)
        payload = data["data"]
        self.assertEqual(payload["format"], "qurulush-sacc2-public-status-v1")
        self.assertFalse(payload["credentials_used"])
        targets = {item["url"]: item for item in payload["targets"]}
        self.assertEqual(targets["https://sacc2.avn.kg"]["status"], "external_error")
        self.assertEqual(targets["https://sacc2.avn.kg"]["status_code"], 502)
        self.assertEqual(targets["https://sacc.avn.kg"]["status"], "online")
        self.assertEqual(targets["http://127.0.0.1:9000"]["status"], "blocked")
        exported_text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

        with patch.dict(os.environ, {"QH_SACC2_PUBLIC_URLS": "https://sacc2.avn.kg,https://sacc.avn.kg"}, clear=False):
            with patch("company_platform_server.urllib.request.urlopen", side_effect=fake_urlopen):
                response = self.raw_request("GET", "/api/external/sacc2-status.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 3000)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Статус публичного контура sacc2", document_xml)
        self.assertIn("https://sacc2.avn.kg", document_xml)
        self.assertIn("external_error", document_xml)
        self.assertIn("https://sacc.avn.kg", document_xml)
        self.assertIn("online", document_xml)
        docx_text = response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, docx_text)
        self.assertNotIn("token_hash", docx_text)
        self.assertNotIn("api_key", docx_text)

        with patch.dict(os.environ, {"QH_SACC2_PUBLIC_URLS": "https://sacc2.avn.kg,https://sacc.avn.kg"}, clear=False):
            with patch("company_platform_server.urllib.request.urlopen", side_effect=fake_urlopen):
                status, data = self.request("POST", "/api/external/sacc2-status/attach", {}, token=engineer)
        self.assertEqual(status, 403, data)

        with patch.dict(os.environ, {"QH_SACC2_PUBLIC_URLS": "https://sacc2.avn.kg,https://sacc.avn.kg"}, clear=False):
            with patch("company_platform_server.urllib.request.urlopen", side_effect=fake_urlopen):
                status, data = self.request("POST", "/api/external/sacc2-status/attach", {}, token=director)
        self.assertEqual(status, 200, data)
        attachment = data["data"]
        self.assertEqual(attachment["format"], "qurulush-sacc2-public-status-attachment-v1")
        self.assertEqual(attachment["attached_gate"], "sacc2_api")
        self.assertEqual(attachment["tracker_status"], "blocked")
        pack_items = {item["id"]: item for item in attachment["request_pack"]["items"]}
        evidence_items = {item["id"]: item for item in attachment["evidence"]["items"]}
        self.assertEqual(pack_items["sacc2_api"]["tracker_status"], "blocked")
        self.assertTrue(pack_items["sacc2_api"]["outgoing_no"].startswith("SACC2-STATUS-"))
        self.assertEqual(evidence_items["sacc2_api"]["evidence_status"], "blocked")
        self.assertIn("https://sacc2.avn.kg", evidence_items["sacc2_api"]["evidence"])
        self.assertIn("Пароли использованы: нет", evidence_items["sacc2_api"]["evidence"])
        attachment_text = json.dumps(attachment, ensure_ascii=False)
        self.assertNotIn(TEST_DEMO_PASSWORD, attachment_text)
        self.assertNotIn("token_hash", attachment_text)
        status, state_data = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200, state_data)
        events = [item["event"] for item in state_data["data"]["audit"]]
        self.assertTrue(any("Статус sacc2" in event for event in events))

    def test_production_evidence_register_requires_director_and_persists_updates(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/evidence")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/evidence", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/production/evidence", token=director)
        self.assertEqual(status, 200, data)
        register = data["data"]
        self.assertEqual(register["format"], "qurulush-production-evidence-register-v1")
        self.assertGreaterEqual(register["total"], 10)
        items = {item["id"]: item for item in register["items"]}
        self.assertIn("sacc2_api", items)
        self.assertIn("QH_SACC2_API_URL", items["sacc2_api"]["variables"])
        self.assertEqual(items["sacc2_api"]["evidence_status"], "open")

        payload = {
            "id": "sacc2_api",
            "status": "done",
            "owner": "Директор / IT",
            "deadline": "2026-09-20",
            "evidence": "Письмо Минстроя SACC2-2026-001, API URL и регламент статусов получены.",
        }
        status, data = self.request("POST", "/api/production/evidence", payload)
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/evidence", payload, token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("POST", "/api/production/evidence", {**payload, "evidence": ""}, token=director)
        self.assertEqual(status, 400, data)

        status, data = self.request("POST", "/api/production/evidence", payload, token=director)
        self.assertEqual(status, 200, data)
        register = data["data"]
        items = {item["id"]: item for item in register["items"]}
        self.assertEqual(items["sacc2_api"]["evidence_status"], "done")
        self.assertEqual(items["sacc2_api"]["deadline"], "2026-09-20")
        self.assertIn("SACC2-2026-001", items["sacc2_api"]["evidence"])
        self.assertEqual(items["sacc2_api"]["updated_by"], "Замирбек уулу Максат")

        status, state_data = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200, state_data)
        events = [item["event"] for item in state_data["data"]["audit"]]
        self.assertTrue(any("Обновлен production evidence" in event for event in events))

        exported_text = json.dumps(register, ensure_ascii=False)
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_production_evidence_docx_requires_director_and_contains_register(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        response = self.raw_request("GET", "/api/production/evidence.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/evidence.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/evidence.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 2500)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            names = set(docx.namelist())
            self.assertIn("word/document.xml", names)
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Evidence-регистр production запуска", document_xml)
        self.assertIn("Интеграция sacc2 / ДГАСК", document_xml)
        exported_text = response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_production_request_pack_requires_director_and_contains_external_requests(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/request-pack")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/request-pack", token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("GET", "/api/production/request-pack", token=director)
        self.assertEqual(status, 200, data)
        pack = data["data"]
        self.assertEqual(pack["format"], "qurulush-production-request-pack-v1")
        self.assertGreaterEqual(pack["total"], 10)
        items = {item["id"]: item for item in pack["items"]}
        self.assertIn("sacc2_api", items)
        self.assertIn("Министерство строительства", items["sacc2_api"]["stakeholder"])
        self.assertIn("официальный API URL", items["sacc2_api"]["request"])
        self.assertIn("регламент статусов", items["sacc2_api"]["required_evidence"])
        self.assertIn("QH_SACC2_API_URL", items["sacc2_api"]["variables"])
        self.assertIn("Тема:", items["sacc2_api"]["draft_message"])

        response = self.raw_request("GET", "/api/production/request-pack.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/request-pack.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/request-pack.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 3000)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Пакет запросов для закрытия production blockers", document_xml)
        self.assertIn("Доступ к sacc2", document_xml)
        exported_text = json.dumps(pack, ensure_ascii=False) + response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_production_official_letters_requires_director_and_contains_letters(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/official-letters")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/official-letters", token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("GET", "/api/production/official-letters", token=director)
        self.assertEqual(status, 200, data)
        packet = data["data"]
        self.assertEqual(packet["format"], "qurulush-production-official-letters-v1")
        self.assertGreaterEqual(packet["total"], 10)
        letters = {item["id"]: item for item in packet["letters"]}
        self.assertIn("sacc2_api", letters)
        self.assertIn("payments", letters)
        self.assertIn("Министерство строительства", letters["sacc2_api"]["recipient"])
        self.assertIn("госпошлин", letters["payments"]["body"])
        self.assertIn("Генеральный директор", letters["sacc2_api"]["signature_block"])

        response = self.raw_request("GET", "/api/production/official-letters.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/official-letters.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/official-letters.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 3000)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Пакет официальных писем по production blockers", document_xml)
        self.assertIn("Министерство строительства", document_xml)
        exported_text = json.dumps(packet, ensure_ascii=False) + response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_production_request_tracker_updates_evidence_and_audit(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")
        sent_payload = {
            "id": "sacc2_api",
            "status": "sent",
            "outgoing_no": "OUT-SACC2-2026-001",
            "sent_at": "2026-09-13",
            "contact": "it@minstroy.example",
            "responsible": "Директор / IT",
            "note": "Письмо по API доступу отправлено в Минстрой.",
        }

        status, data = self.request("POST", "/api/production/request-pack/tracker", sent_payload)
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/request-pack/tracker", sent_payload, token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("POST", "/api/production/request-pack/tracker", {**sent_payload, "outgoing_no": ""}, token=director)
        self.assertEqual(status, 400, data)

        status, data = self.request("POST", "/api/production/request-pack/tracker", sent_payload, token=director)
        self.assertEqual(status, 200, data)
        pack = data["data"]["request_pack"]
        evidence = data["data"]["evidence"]
        request_items = {item["id"]: item for item in pack["items"]}
        evidence_items = {item["id"]: item for item in evidence["items"]}
        self.assertEqual(request_items["sacc2_api"]["tracker_status"], "sent")
        self.assertEqual(request_items["sacc2_api"]["outgoing_no"], "OUT-SACC2-2026-001")
        self.assertEqual(evidence_items["sacc2_api"]["evidence_status"], "waiting_external")
        self.assertIn("OUT-SACC2-2026-001", evidence_items["sacc2_api"]["evidence"])

        done_payload = {
            **sent_payload,
            "status": "evidence_attached",
            "response_at": "2026-09-20",
            "evidence": "Ответ Минстроя SACC2-2026-REPLY: API URL и регламент статусов получены.",
        }
        status, data = self.request("POST", "/api/production/request-pack/tracker", done_payload, token=director)
        self.assertEqual(status, 200, data)
        evidence = data["data"]["evidence"]
        evidence_items = {item["id"]: item for item in evidence["items"]}
        self.assertEqual(evidence_items["sacc2_api"]["evidence_status"], "done")
        self.assertIn("SACC2-2026-REPLY", evidence_items["sacc2_api"]["evidence"])

        status, state_data = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200, state_data)
        events = [item["event"] for item in state_data["data"]["audit"]]
        self.assertTrue(any("production request tracker" in event for event in events))

    def test_production_action_board_requires_director_and_groups_by_role(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/action-board")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/action-board", token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("GET", "/api/production/action-board", token=director)
        self.assertEqual(status, 200, data)
        board = data["data"]
        self.assertEqual(board["format"], "qurulush-production-action-board-v1")
        self.assertGreaterEqual(board["request_total"], 10)
        groups = {item["id"]: item for item in board["groups"]}
        self.assertIn("devops", groups)
        self.assertIn("ministry", groups)
        self.assertIn("accountant", groups)
        self.assertTrue(any(item["id"] == "sacc2_api" for item in groups["ministry"]["items"]))
        self.assertTrue(any(item["id"] == "payments" for item in groups["accountant"]["items"]))

        response = self.raw_request("GET", "/api/production/action-board.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/action-board.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/action-board.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 3000)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Карточки закрытия production blockers по ролям", document_xml)
        self.assertIn("Минстрой / ДГАСК", document_xml)
        exported_text = json.dumps(board, ensure_ascii=False) + response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_production_launch_sequence_requires_director_and_orders_steps(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/launch-sequence")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/launch-sequence", token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("GET", "/api/production/launch-sequence", token=director)
        self.assertEqual(status, 200, data)
        sequence = data["data"]
        self.assertEqual(sequence["format"], "qurulush-production-launch-sequence-v1")
        self.assertGreaterEqual(sequence["total_steps"], 10)
        self.assertGreater(sequence["open_count"], 0)
        self.assertIsInstance(sequence["current_step"], dict)
        phases = {item["id"]: item for item in sequence["phases"]}
        self.assertIn("governance", phases)
        self.assertIn("integrations", phases)
        self.assertIn("acceptance", phases)
        self.assertTrue(any(step["id"] == "sacc2_api" for step in phases["integrations"]["steps"]))
        self.assertEqual(phases["acceptance"]["steps"][-1]["id"], "final_go_no_go")

        response = self.raw_request("GET", "/api/production/launch-sequence.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/launch-sequence.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/launch-sequence.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 3000)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Пошаговый план production-запуска", document_xml)
        self.assertIn("Финальный production smoke и go/no-go", document_xml)
        exported_text = json.dumps(sequence, ensure_ascii=False) + response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_production_plan_docx_requires_director_and_contains_steps(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        response = self.raw_request("GET", "/api/production/plan.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/plan.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/plan.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 2000)
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            names = set(docx.namelist())
            self.assertIn("word/document.xml", names)
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("План подключения боевого контура", document_xml)
        self.assertIn("Интеграция sacc2 / ДГАСК", document_xml)
        self.assertIn("QH_SACC2_API_URL", document_xml)
        self.assertIn("Платежный шлюз", document_xml)
        self.assertNotIn(TEST_DEMO_PASSWORD, document_xml)
        self.assertNotIn("token_hash", document_xml)

    def test_production_env_example_requires_director_and_is_sanitized(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        response = self.raw_request("GET", "/api/production/env.example")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/env.example", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/env.example", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "text/plain; charset=utf-8")
        body = response["body"].decode("utf-8")
        self.assertIn("QH_SACC2_API_URL=https://sacc2.avn.kg/api", body)
        self.assertIn("QH_REQUIRE_PRODUCTION=1", body)
        self.assertIn("QH_REFERENCE_VERIFIED_AT=YYYY-MM-DD", body)
        self.assertNotIn(TEST_DEMO_PASSWORD, body)
        self.assertNotIn("token_hash", body)

    def test_production_env_validate_requires_director_and_redacts_values(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        valid_env = "\n".join(
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
                'QH_AV_SCANNER="clamscan --no-summary {file}"',
                "QH_BACKUP_INTERVAL_MINUTES=60",
                "QH_BACKUP_ON_START=1",
                "QH_BACKUP_REMOTE_URL=s3://company-secure-backups/qurulush-hub",
                'QH_BACKUP_REMOTE_CMD="/opt/qurulush/bin/sync-backup {backup} {manifest}"',
                "QH_REFERENCE_VERIFIED_AT=2026-09-13",
            ]
        )
        status, data = self.request("POST", "/api/production/env/validate", {"env_text": valid_env})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/env/validate", {"env_text": valid_env}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/env/validate", {"env_text": valid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-production-env-validation-v1")
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["issue_count"], 0, report)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("RealStrongPassword2026!", exported)
        self.assertNotIn("official-sacc2-key-2026", exported)

        invalid_env = "\n".join(
            [
                "BROKEN_LINE",
                "QH_BOOTSTRAP_ADMIN_EMAIL=bad-email",
                "QH_BOOTSTRAP_ADMIN_PASSWORD=CHANGE_ME",
                "QH_BOOTSTRAP_ADMIN_ROLE=unknown",
                "QH_DISABLE_DEMO_USERS=0",
                "QH_REQUIRE_PRODUCTION=0",
                "QH_REQUIRE_HOOK_JSON=0",
                "QH_SACC2_API_KEY=tinysecret7",
                "QH_REFERENCE_VERIFIED_AT=YYYY-MM-DD",
            ]
        )
        status, data = self.request("POST", "/api/production/env/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("env_line_1", issue_ids)
        self.assertIn("bootstrap_email_format", issue_ids)
        self.assertIn("placeholder_qh_bootstrap_admin_password", issue_ids)
        self.assertIn("strict_qh_require_production", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("CHANGE_ME", exported)
        self.assertNotIn("tinysecret7", exported)

    def test_auth_cutover_validation_requires_director_and_redacts_password(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        env_text = "\n".join(
            [
                "QH_BOOTSTRAP_ADMIN_EMAIL=owner@builder.kg",
                "QH_BOOTSTRAP_ADMIN_PASSWORD=RealStrongPassword2026!",
                "QH_BOOTSTRAP_ADMIN_NAME=Company Owner",
                "QH_BOOTSTRAP_ADMIN_ROLE=ceo",
                "QH_DISABLE_DEMO_USERS=1",
            ]
        )
        status, data = self.request("POST", "/api/production/auth-cutover/validate", {"env_text": env_text})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/auth-cutover/validate", {"env_text": env_text}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/auth-cutover/validate", {"env_text": env_text}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-auth-cutover-validation-v1")
        self.assertTrue(report["ready_for_cutover"], report)
        self.assertEqual(report["bootstrap_email"], "owner@builder.kg")
        self.assertEqual(report["bootstrap_role"], "ceo")
        self.assertGreaterEqual(report["active_demo_count"], 1)
        self.assertGreaterEqual(report["issue_count"], report["blocking_issue_count"])
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("RealStrongPassword2026!", exported)

        invalid_env = "\n".join(
            [
                "QH_BOOTSTRAP_ADMIN_EMAIL=director@company.kg",
                "QH_BOOTSTRAP_ADMIN_PASSWORD=CHANGE_ME",
                "QH_BOOTSTRAP_ADMIN_NAME=CHANGE_ME",
                "QH_BOOTSTRAP_ADMIN_ROLE=unknown",
                "QH_DISABLE_DEMO_USERS=0",
            ]
        )
        status, data = self.request("POST", "/api/production/auth-cutover/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_cutover"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("auth_email_demo", issue_ids)
        self.assertIn("auth_placeholder_qh_bootstrap_admin_password", issue_ids)
        self.assertIn("auth_disable_demo", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("CHANGE_ME", exported)

    def test_production_account_cutover_requires_director_and_lists_safe_role_coverage(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/account-cutover")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/account-cutover", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/production/account-cutover", token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-production-account-cutover-v1")
        self.assertFalse(report["ready_for_account_cutover"], report)
        self.assertGreaterEqual(report["counts"]["active_demo"], 1)
        before_active_real = report["counts"]["active_real"]
        role_ids = {item["id"]: item for item in report["role_coverage"]}
        self.assertIn(role_ids["ceo"]["status"], {"ready", "demo_only"})
        self.assertIn("active_demo_users", {item["id"] for item in report["blockers"]})
        exported = json.dumps(report, ensure_ascii=False)
        self.assertIn("director@company.kg", exported)
        self.assertNotIn(TEST_DEMO_PASSWORD, exported)
        self.assertNotIn("password_hash", exported)
        self.assertNotIn("password_salt", exported)
        self.assertNotIn("token_hash", exported)

        status, data = self.request(
            "POST",
            "/api/team",
            {
                "name": "Боевой бригадир cutover",
                "role": "Бригадир",
                "email": f"cutover.brigadier.{int(time.time() * 1000)}@builder.kg",
                "password": "StrongOwner2026!",
                "objectIds": [3],
            },
            token=director,
        )
        self.assertEqual(status, 201, data)
        status, data = self.request("GET", "/api/production/account-cutover", token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["counts"]["active_real"], before_active_real + 1)
        role_ids = {item["id"]: item for item in report["role_coverage"]}
        self.assertEqual(role_ids["brigadier"]["status"], "ready")
        self.assertIn("cutover.brigadier.", json.dumps(report, ensure_ascii=False))

        response = self.raw_request("GET", "/api/production/account-cutover.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        raw_docx = response["body"]
        self.assertGreater(len(raw_docx), 2000)
        self.assertEqual(raw_docx[:2], b"PK")
        with zipfile.ZipFile(BytesIO(raw_docx)) as package:
            document_xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn("Переход на боевые учетные записи", document_xml)
        self.assertIn("Боевой бригадир cutover", document_xml)
        exported_docx = raw_docx.decode("utf-8", "ignore")
        self.assertNotIn("StrongOwner2026!", exported_docx)
        self.assertNotIn("password_hash", exported_docx)
        self.assertNotIn("token_hash", exported_docx)

    def test_hook_contract_validation_requires_director_and_redacts_commands(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        env_text = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=1",
                'QH_SACC2_SYNC_CMD="/opt/secret/sync-sacc2 {payload}"',
                'QH_SACC2_STATUS_MAP={"needs_company":["needs_company"],"informed":["informed"],"review":["review"],"done":["done"]}',
                'QH_EDS_SIGN_CMD="/opt/secret/sign-document {payload}"',
                'QH_PAYMENT_GATEWAY_CMD="/opt/secret/confirm-payment {payload}"',
                'QH_STORAGE_SYNC_CMD="/opt/secret/storage-sync {file} {doc_id}"',
                'QH_AV_SCANNER="/opt/secret/scan-upload {file}"',
                'QH_BACKUP_REMOTE_CMD="/opt/secret/backup-sync {backup} {manifest}"',
            ]
        )
        status, data = self.request("POST", "/api/production/hooks/validate", {"env_text": env_text})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/hooks/validate", {"env_text": env_text}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/hooks/validate", {"env_text": env_text}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-hook-contract-validation-v1")
        self.assertTrue(report["ready_for_hook_smoke"], report)
        self.assertEqual(report["hook_count"], 6)
        self.assertEqual(report["ready_hook_count"], 6)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertIn("QH_SACC2_SYNC_CMD", exported)
        self.assertNotIn("/opt/secret", exported)

        invalid_env = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=0",
                "QH_SACC2_SYNC_CMD=CHANGE_ME",
                'QH_EDS_SIGN_CMD="/opt/secret/sign-document"',
                'QH_PAYMENT_GATEWAY_CMD="/opt/secret/confirm-payment {payload}"',
                'QH_STORAGE_SYNC_CMD="/opt/secret/storage-sync"',
                'QH_AV_SCANNER="/opt/secret/scan-upload"',
                'QH_BACKUP_REMOTE_CMD="/opt/secret/backup-sync {backup}"',
            ]
        )
        status, data = self.request("POST", "/api/production/hooks/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_hook_smoke"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("hooks_require_json", issue_ids)
        self.assertIn("hook_placeholder_sacc2", issue_ids)
        self.assertIn("hook_marker_eds_payload", issue_ids)
        self.assertIn("hook_marker_storage_file", issue_ids)
        self.assertIn("hook_marker_av_scanner_file", issue_ids)
        self.assertIn("hook_marker_backup_remote_manifest", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("CHANGE_ME", exported)
        self.assertNotIn("/opt/secret", exported)

    def test_sacc2_exchange_validation_requires_director_and_maps_statuses(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        env_text = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=1",
                "QH_SACC2_API_URL=https://sacc2.avn.kg/api",
                "QH_SACC2_API_KEY=official-sacc2-key-2026",
                'QH_SACC2_SYNC_CMD="/opt/secret/sync-sacc2 {payload}"',
                'QH_SACC2_STATUS_MAP={"needs_company":["needs_company","need_company_response"],"informed":["informed"],"review":["review","in_review"],"done":["done","completed"]}',
            ]
        )
        status, data = self.request("POST", "/api/production/sacc2/validate", {"env_text": env_text})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/sacc2/validate", {"env_text": env_text}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/sacc2/validate", {"env_text": env_text}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-sacc2-exchange-validation-v1")
        self.assertTrue(report["ready_for_sacc2_smoke"], report)
        self.assertEqual(report["api_url_host"], "sacc2.avn.kg")
        self.assertEqual(set(report["platform_statuses"]), {"needs_company", "informed", "review", "done"})
        self.assertIn("need_company_response", report["status_map"]["needs_company"])
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("official-sacc2-key-2026", exported)
        self.assertNotIn("/opt/secret", exported)

        invalid_env = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=0",
                "QH_SACC2_API_URL=http://sacc2.avn.kg/api",
                "QH_SACC2_API_KEY=short",
                'QH_SACC2_SYNC_CMD="/opt/secret/sync-sacc2"',
                'QH_SACC2_STATUS_MAP={"needs_company":[]}',
            ]
        )
        status, data = self.request("POST", "/api/production/sacc2/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_sacc2_smoke"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("sacc2_api_url_https", issue_ids)
        self.assertIn("sacc2_api_key_unsafe", issue_ids)
        self.assertIn("sacc2_command_payload_marker", issue_ids)
        self.assertIn("sacc2_require_hook_json", issue_ids)
        self.assertIn("sacc2_status_map_done", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("short", exported)
        self.assertNotIn("/opt/secret", exported)

    def test_eds_integration_validation_requires_director_and_redacts_command(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        env_text = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=1",
                "QH_EDS_PROVIDER=OfficialEDS",
                "QH_EDS_API_URL=https://eds.builder.kg/sign",
                'QH_EDS_SIGN_CMD="/opt/secret/sign-document {payload}"',
            ]
        )
        status, data = self.request("POST", "/api/production/eds/validate", {"env_text": env_text})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/eds/validate", {"env_text": env_text}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/eds/validate", {"env_text": env_text}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-eds-integration-validation-v1")
        self.assertTrue(report["ready_for_eds_smoke"], report)
        self.assertEqual(report["provider"], "OfficialEDS")
        self.assertEqual(report["api_url_host"], "eds.builder.kg")
        self.assertIn("file_sha256", report["required_payload_fields"])
        exported = json.dumps(report, ensure_ascii=False)
        self.assertIn("QH_EDS_SIGN_CMD", exported)
        self.assertNotIn("/opt/secret", exported)

        invalid_env = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=0",
                "QH_EDS_PROVIDER=CHANGE_ME",
                "QH_EDS_API_URL=http://eds.builder.kg/sign",
                'QH_EDS_SIGN_CMD="/opt/secret/sign-document"',
            ]
        )
        status, data = self.request("POST", "/api/production/eds/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_eds_smoke"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("eds_provider_placeholder", issue_ids)
        self.assertIn("eds_api_url_https", issue_ids)
        self.assertIn("eds_command_payload_marker", issue_ids)
        self.assertIn("eds_require_hook_json", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("CHANGE_ME", exported)
        self.assertNotIn("/opt/secret", exported)

    def test_payment_gateway_validation_requires_director_and_redacts_command(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        env_text = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=1",
                "QH_PAYMENT_GATEWAY_URL=https://payments.builder.kg/api",
                'QH_PAYMENT_GATEWAY_CMD="/opt/secret/confirm-payment {payload}"',
            ]
        )
        status, data = self.request("POST", "/api/production/payments/validate", {"env_text": env_text})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/payments/validate", {"env_text": env_text}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/payments/validate", {"env_text": env_text}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-payment-gateway-validation-v1")
        self.assertTrue(report["ready_for_payment_smoke"], report)
        self.assertEqual(report["gateway_host"], "payments.builder.kg")
        self.assertIn("amount", report["required_payload_fields"])
        self.assertIn("paid", report["allowed_hook_statuses"])
        exported = json.dumps(report, ensure_ascii=False)
        self.assertIn("QH_PAYMENT_GATEWAY_CMD", exported)
        self.assertNotIn("/opt/secret", exported)

        invalid_env = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=0",
                "QH_PAYMENT_GATEWAY_URL=http://payments.builder.kg/api",
                'QH_PAYMENT_GATEWAY_CMD="/opt/secret/confirm-payment"',
            ]
        )
        status, data = self.request("POST", "/api/production/payments/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_payment_smoke"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("payment_gateway_url_https", issue_ids)
        self.assertIn("payment_gateway_command_payload_marker", issue_ids)
        self.assertIn("payment_gateway_require_hook_json", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("/opt/secret", exported)

    def test_storage_integration_validation_requires_director_and_redacts_command(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        env_text = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=1",
                "QH_STORAGE_MODE=external",
                "QH_STORAGE_URL=s3://company-documents/qurulush-hub",
                'QH_STORAGE_SYNC_CMD="/opt/secret/storage-sync {file} {doc_id}"',
            ]
        )
        status, data = self.request("POST", "/api/production/storage/validate", {"env_text": env_text})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/storage/validate", {"env_text": env_text}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/storage/validate", {"env_text": env_text}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-storage-integration-validation-v1")
        self.assertTrue(report["ready_for_storage_smoke"], report)
        self.assertEqual(report["storage_mode"], "external")
        self.assertEqual(report["storage_scheme"], "s3")
        self.assertIn("{file}", report["required_markers"])
        exported = json.dumps(report, ensure_ascii=False)
        self.assertIn("QH_STORAGE_SYNC_CMD", exported)
        self.assertNotIn("/opt/secret", exported)

        invalid_env = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=0",
                "QH_STORAGE_MODE=local",
                "QH_STORAGE_URL=company-documents",
                'QH_STORAGE_SYNC_CMD="/opt/secret/storage-sync"',
            ]
        )
        status, data = self.request("POST", "/api/production/storage/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_storage_smoke"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("storage_mode_local", issue_ids)
        self.assertIn("storage_url_scheme", issue_ids)
        self.assertIn("storage_command_file_marker", issue_ids)
        self.assertIn("storage_require_hook_json", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("/opt/secret", exported)

    def test_av_scanner_validation_requires_director_and_redacts_command(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        env_text = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=1",
                'QH_AV_SCANNER="/opt/secret/scan-upload {file}"',
            ]
        )
        status, data = self.request("POST", "/api/production/av/validate", {"env_text": env_text})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/av/validate", {"env_text": env_text}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/av/validate", {"env_text": env_text}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-av-scanner-validation-v1")
        self.assertTrue(report["ready_for_av_smoke"], report)
        self.assertIn("scan_before_store", report["required_behavior"])
        self.assertIn("{file}", report["required_markers"])
        exported = json.dumps(report, ensure_ascii=False)
        self.assertIn("QH_AV_SCANNER", exported)
        self.assertNotIn("/opt/secret", exported)

        invalid_env = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=0",
                'QH_AV_SCANNER="/opt/secret/scan-upload"',
            ]
        )
        status, data = self.request("POST", "/api/production/av/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_av_smoke"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("av_command_file_marker", issue_ids)
        self.assertIn("av_require_hook_json", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("/opt/secret", exported)

    def test_backup_schedule_validation_requires_director_and_checks_startup_backup(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        env_text = "\n".join(
            [
                "QH_BACKUP_INTERVAL_MINUTES=60",
                "QH_BACKUP_ON_START=1",
                "QH_BACKUP_MAX_AGE_HOURS=24",
            ]
        )
        status, data = self.request("POST", "/api/production/backups/schedule/validate", {"env_text": env_text})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/backups/schedule/validate", {"env_text": env_text}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/backups/schedule/validate", {"env_text": env_text}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-backup-schedule-validation-v1")
        self.assertTrue(report["ready_for_backup_schedule"], report)
        self.assertEqual(report["schedule_source"], "minutes")
        self.assertTrue(report["on_start"])

        invalid_env = "\n".join(
            [
                "QH_BACKUP_INTERVAL_MINUTES=0",
                "QH_BACKUP_ON_START=0",
                "QH_BACKUP_MAX_AGE_HOURS=never",
            ]
        )
        status, data = self.request("POST", "/api/production/backups/schedule/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_backup_schedule"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("backup_schedule_minutes_invalid", issue_ids)
        self.assertIn("backup_on_start_disabled", issue_ids)
        self.assertIn("backup_max_age_invalid", issue_ids)

    def test_backup_remote_validation_requires_director_and_redacts_command(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        env_text = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=1",
                "QH_BACKUP_REMOTE_URL=s3://company-secure-backups/qurulush-hub",
                'QH_BACKUP_REMOTE_CMD="/opt/secret/backup-sync {backup} {manifest}"',
            ]
        )
        status, data = self.request("POST", "/api/production/backups/remote/validate", {"env_text": env_text})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/backups/remote/validate", {"env_text": env_text}, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/backups/remote/validate", {"env_text": env_text}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-backup-remote-validation-v1")
        self.assertTrue(report["ready_for_remote_backup_smoke"], report)
        self.assertEqual(report["remote_scheme"], "s3")
        self.assertIn("{manifest}", report["required_markers"])
        exported = json.dumps(report, ensure_ascii=False)
        self.assertIn("QH_BACKUP_REMOTE_CMD", exported)
        self.assertNotIn("/opt/secret", exported)

        invalid_env = "\n".join(
            [
                "QH_REQUIRE_HOOK_JSON=0",
                "QH_BACKUP_REMOTE_URL=company-backups",
                'QH_BACKUP_REMOTE_CMD="/opt/secret/backup-sync {backup}"',
            ]
        )
        status, data = self.request("POST", "/api/production/backups/remote/validate", {"env_text": invalid_env}, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_remote_backup_smoke"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("backup_remote_url_scheme", issue_ids)
        self.assertIn("backup_remote_command_manifest_marker", issue_ids)
        self.assertIn("backup_remote_require_hook_json", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("/opt/secret", exported)

    def test_production_cutover_validation_requires_director_and_summarizes_gates(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")
        payload = {
            "env_text": complete_production_env_sample(),
            "domain": "cabinet.builder.kg",
            "public_url": "https://cabinet.builder.kg/",
            "port": 8781,
        }

        status, data = self.request("POST", "/api/production/cutover/validate", payload)
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/cutover/validate", payload, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/cutover/validate", payload, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-production-cutover-validation-v1")
        self.assertTrue(report["ready_for_production_cutover"], report)
        self.assertEqual(report["cutover_scope"], "configuration_validation")
        self.assertTrue(report["configuration_ready"], report)
        self.assertFalse(report["ready_for_final_acceptance"], report)
        self.assertTrue(report["final_acceptance_required"], report)
        self.assertEqual(report["blocking_issue_count"], 0, report)
        self.assertEqual(report["stage_count"], 12)
        self.assertEqual(report["required_ready_count"], report["required_total"])
        self.assertGreaterEqual(report["completion_percent"], 90)
        stage_ids = {item["id"] for item in report["stages"]}
        self.assertIn("sacc2", stage_ids)
        self.assertIn("storage", stage_ids)
        self.assertIn("backup_remote", stage_ids)
        self.assertIn("legal_catalog", stage_ids)
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("live_probe_not_run", issue_ids)
        self.assertIn("перед финальной приемкой", report["next_step"])
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("RealStrongPassword2026!", exported)
        self.assertNotIn("official-sacc2-key-2026", exported)
        self.assertNotIn("/opt/qurulush/bin", exported)
        self.assertNotIn("aws s3 cp", exported)

        invalid_payload = {
            "env_text": "\n".join(
                [
                    "QH_BOOTSTRAP_ADMIN_EMAIL=director@company.kg",
                    "QH_BOOTSTRAP_ADMIN_PASSWORD=CHANGE_ME",
                    "QH_DISABLE_DEMO_USERS=0",
                    "QH_REQUIRE_HOOK_JSON=0",
                    "QH_SACC2_API_URL=http://sacc2.avn.kg/api",
                    "QH_SACC2_API_KEY=tinysecret7",
                    "QH_REFERENCE_VERIFIED_AT=YYYY-MM-DD",
                ]
            ),
            "domain": "localhost",
            "public_url": "http://localhost:8781/",
            "port": 8781,
        }
        status, data = self.request("POST", "/api/production/cutover/validate", invalid_payload, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_production_cutover"], report)
        self.assertGreater(report["blocking_issue_count"], 0)
        statuses = {item["id"]: item["status"] for item in report["stages"]}
        self.assertEqual(statuses["domain_https"], "fail")
        self.assertEqual(statuses["auth_cutover"], "fail")
        self.assertEqual(statuses["legal_catalog"], "fail")
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("domain_format", issue_ids)
        self.assertIn("auth_email_demo", issue_ids)
        self.assertIn("legal_catalog_verified_at_placeholder", issue_ids)
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("CHANGE_ME", exported)
        self.assertNotIn("tinysecret7", exported)

        status, data = self.request("POST", "/api/production/cutover.docx", payload)
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/cutover.docx", payload, token=engineer)
        self.assertEqual(status, 403, data)
        response = raw_http_request(self.host, self.port, "POST", "/api/production/cutover.docx", payload, token=director)
        self.assertEqual(response[0], 200, response)
        raw_docx = response[1] if isinstance(response[1], bytes) else b""
        self.assertGreater(len(raw_docx), 2000)
        self.assertEqual(raw_docx[:2], b"PK")
        with zipfile.ZipFile(BytesIO(raw_docx)) as package:
            document_xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn("Production cutover", document_xml)
        self.assertIn("Каталог разрешений", document_xml)
        exported_docx = raw_docx.decode("utf-8", "ignore")
        self.assertNotIn("RealStrongPassword2026!", exported_docx)
        self.assertNotIn("official-sacc2-key-2026", exported_docx)
        self.assertNotIn("/opt/qurulush/bin", exported_docx)

    def test_production_launch_bundle_requires_director_and_contains_handoff_files(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        response = self.raw_request("GET", "/api/production/launch-bundle.zip")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/launch-bundle.zip", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/launch-bundle.zip", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/zip")
        self.assertGreater(len(response["body"]), 9000)
        with zipfile.ZipFile(BytesIO(response["body"])) as package:
            names = set(package.namelist())
            expected = {
                "README_LAUNCH_PACKET.txt",
                "company-platform.env.example",
                "company-access-matrix.json",
                "qurulush-company-access-matrix.docx",
                "production-plan.json",
                "qurulush-production-plan.docx",
                "production-account-cutover.json",
                "qurulush-production-account-cutover.docx",
                "production-evidence-register.json",
                "qurulush-production-evidence-register.docx",
                "production-request-pack.json",
                "qurulush-production-request-pack.docx",
                "production-official-letters.json",
                "qurulush-production-official-letters.docx",
                "dgask-interaction-map.json",
                "qurulush-dgask-interaction-map.docx",
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
            }
            self.assertTrue(expected.issubset(names), names)
            readme = package.read("README_LAUNCH_PACKET.txt").decode("utf-8")
            access_matrix = json.loads(package.read("company-access-matrix.json").decode("utf-8"))
            access_matrix_docx = package.read("qurulush-company-access-matrix.docx")
            legal = json.loads(package.read("legal-verification-packet.json").decode("utf-8"))
            plan = json.loads(package.read("production-plan.json").decode("utf-8"))
            account_cutover = json.loads(package.read("production-account-cutover.json").decode("utf-8"))
            account_cutover_docx = package.read("qurulush-production-account-cutover.docx")
            evidence = json.loads(package.read("production-evidence-register.json").decode("utf-8"))
            evidence_docx = package.read("qurulush-production-evidence-register.docx")
            request_pack = json.loads(package.read("production-request-pack.json").decode("utf-8"))
            request_pack_docx = package.read("qurulush-production-request-pack.docx")
            official_letters = json.loads(package.read("production-official-letters.json").decode("utf-8"))
            official_letters_docx = package.read("qurulush-production-official-letters.docx")
            interaction_map = json.loads(package.read("dgask-interaction-map.json").decode("utf-8"))
            interaction_map_docx = package.read("qurulush-dgask-interaction-map.docx")
            action_board = json.loads(package.read("production-action-board.json").decode("utf-8"))
            action_board_docx = package.read("qurulush-production-action-board.docx")
            launch_sequence = json.loads(package.read("production-launch-sequence.json").decode("utf-8"))
            launch_sequence_docx = package.read("qurulush-production-launch-sequence.docx")
            remaining_work = json.loads(package.read("production-remaining-work.json").decode("utf-8"))
            remaining_work_docx = package.read("qurulush-production-remaining-work.docx")
            top_actions = json.loads(package.read("production-top-actions.json").decode("utf-8"))
            top_actions_docx = package.read("qurulush-production-top-actions.docx")
            production_alerts = json.loads(package.read("production-alerts.json").decode("utf-8"))
            legal_docx = package.read("qurulush-legal-verification-packet.docx")
            qa_evidence = json.loads(package.read("qa-evidence.json").decode("utf-8"))
            qa_evidence_docx = package.read("qurulush-qa-evidence.docx")
            status_board = json.loads(package.read("production-status-board.json").decode("utf-8"))
            status_board_docx = package.read("qurulush-production-status-board.docx")
        self.assertIn("пакет запуска строительной компании", readme)
        self.assertIn("роли, права, объекты", readme)
        self.assertIn("evidence-регистр", readme)
        self.assertIn("кому направить запросы", readme)
        self.assertIn("проекты официальных писем", readme)
        self.assertIn("карта взаимодействия", readme)
        self.assertIn("переход с demo-доступов", readme)
        self.assertIn("карточки закрытия blockers", readme)
        self.assertIn("пошаговая карта запуска", readme)
        self.assertIn("что осталось до боевого запуска", readme)
        self.assertIn("короткий список ближайших действий", readme)
        self.assertIn("предупреждения для журнала уведомлений", readme)
        self.assertIn("пакет доказательств тестовой проверки", readme)
        self.assertIn("единый директорский статус запуска", readme)
        self.assertIn("go/no-go", readme)
        self.assertEqual(access_matrix["format"], "qurulush-company-access-matrix-v1")
        self.assertEqual(access_matrix_docx[:2], b"PK")
        self.assertEqual(legal["format"], "qurulush-legal-verification-packet-v1")
        self.assertEqual(plan["format"], "qurulush-production-connection-plan-v1")
        self.assertEqual(account_cutover["format"], "qurulush-production-account-cutover-v1")
        self.assertEqual(account_cutover_docx[:2], b"PK")
        self.assertGreaterEqual(account_cutover["counts"]["active_demo"], 1)
        self.assertEqual(evidence["format"], "qurulush-production-evidence-register-v1")
        self.assertEqual(evidence_docx[:2], b"PK")
        self.assertEqual(request_pack["format"], "qurulush-production-request-pack-v1")
        self.assertEqual(request_pack_docx[:2], b"PK")
        self.assertEqual(official_letters["format"], "qurulush-production-official-letters-v1")
        self.assertEqual(official_letters_docx[:2], b"PK")
        self.assertEqual(interaction_map["format"], "qurulush-dgask-interaction-map-v1")
        self.assertEqual(interaction_map_docx[:2], b"PK")
        self.assertEqual(action_board["format"], "qurulush-production-action-board-v1")
        self.assertEqual(action_board_docx[:2], b"PK")
        self.assertEqual(launch_sequence["format"], "qurulush-production-launch-sequence-v1")
        self.assertEqual(launch_sequence_docx[:2], b"PK")
        self.assertEqual(remaining_work["format"], "qurulush-production-remaining-work-v1")
        self.assertEqual(remaining_work_docx[:2], b"PK")
        self.assertEqual(top_actions["format"], "qurulush-production-top-actions-v1")
        self.assertEqual(top_actions_docx[:2], b"PK")
        self.assertEqual(production_alerts["format"], "qurulush-production-alerts-v1")
        self.assertEqual(legal_docx[:2], b"PK")
        self.assertEqual(qa_evidence["format"], "qurulush-production-qa-evidence-v1")
        self.assertEqual(qa_evidence_docx[:2], b"PK")
        self.assertEqual(status_board["format"], "qurulush-production-status-board-v1")
        self.assertEqual(status_board_docx[:2], b"PK")
        exported_text = response["body"].decode("utf-8", "ignore")
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)
        self.assertNotIn("stored_file", exported_text)

    def test_deployment_files_bundle_requires_director_and_validates_domain(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        payload = {"domain": "cabinet.builder.kg", "admin_email": "owner@builder.kg", "port": 8781}
        status, data = self.request("POST", "/api/production/deployment-files.zip", payload)
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/deployment-files.zip", payload, token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("POST", "/api/production/deployment-files.zip", {"domain": "company.example", "admin_email": "owner@builder.kg"}, token=director)
        self.assertEqual(status, 400, data)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request(
            "POST",
            "/api/production/deployment-files.zip",
            body=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {director}"},
        )
        res = conn.getresponse()
        raw = res.read()
        headers = dict(res.getheaders())
        conn.close()
        self.assertEqual(res.status, 200, raw[:200])
        self.assertEqual(headers["Content-Type"], "application/zip")
        with zipfile.ZipFile(BytesIO(raw)) as package:
            names = set(package.namelist())
            self.assertEqual(
                names,
                {
                    "README_DEPLOYMENT_FILES.txt",
                    "qurulush-hub.service",
                    "nginx-qurulush-hub.conf",
                    "go-no-go-command.sh",
                    "DEPLOYMENT_SUMMARY.json",
                },
            )
            nginx = package.read("nginx-qurulush-hub.conf").decode("utf-8")
            service = package.read("qurulush-hub.service").decode("utf-8")
            go_no_go = package.read("go-no-go-command.sh").decode("utf-8")
            summary = json.loads(package.read("DEPLOYMENT_SUMMARY.json").decode("utf-8"))
        self.assertIn("server_name cabinet.builder.kg", nginx)
        self.assertIn("--require-production", service)
        self.assertIn("--hook-contract-smoke", go_no_go)
        self.assertEqual(summary["domain"], "cabinet.builder.kg")
        exported_text = raw.decode("utf-8", "ignore")
        self.assertNotIn("company.example", exported_text)
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_domain_https_validation_requires_director_and_lists_confirmations(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        payload = {"domain": "cabinet.builder.kg", "public_url": "https://cabinet.builder.kg/", "port": 8781}
        status, data = self.request("POST", "/api/production/domain/validate", payload)
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/production/domain/validate", payload, token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/production/domain/validate", payload, token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-domain-https-validation-v1")
        self.assertTrue(report["ready_for_deployment_files"], report)
        self.assertEqual(report["domain"], "cabinet.builder.kg")
        self.assertEqual(report["backend_port"], 8781)
        confirmation_ids = {item["id"] for item in report["required_confirmations"]}
        self.assertIn("dns_a_record", confirmation_ids)
        self.assertIn("tls_certificate", confirmation_ids)
        self.assertIn("nginx_proxy", confirmation_ids)
        self.assertFalse(report["live_probe_requested"])

        live_probe = {
            "status": "pass",
            "checks": [
                {"id": "https_reachable", "title": "Публичная доступность", "status": "pass", "detail": "HTTP status 200"},
                {"id": "header_strict_transport_security", "title": "HSTS", "status": "pass", "detail": "Header найден"},
            ],
        }
        with patch("company_platform_server.probe_public_https_url", return_value=live_probe) as probe:
            status, data = self.request("POST", "/api/production/domain/validate", {**payload, "probe_live": True}, token=director)
        self.assertEqual(status, 200, data)
        probe.assert_called_once_with("https://cabinet.builder.kg/")
        report = data["data"]
        self.assertTrue(report["live_probe_requested"])
        self.assertTrue(report["ready_for_live_https"])
        self.assertEqual(report["live_probe"]["checks"][0]["id"], "https_reachable")

        status, data = self.request(
            "POST",
            "/api/production/domain/validate",
            {"domain": "company.example", "public_url": "http://other.example/", "port": 80},
            token=director,
        )
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertFalse(report["ready_for_deployment_files"])
        issue_ids = {item["id"] for item in report["issues"]}
        self.assertIn("domain_format", issue_ids)
        self.assertIn("backend_port", issue_ids)
        self.assertIn("public_url_https", issue_ids)

    def test_production_launch_checklist_requires_director_and_contains_commands(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/checklist")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/checklist", token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("GET", "/api/production/checklist", token=director)
        self.assertEqual(status, 200, data)
        checklist = data["data"]
        self.assertEqual(checklist["format"], "qurulush-production-launch-checklist-v1")
        self.assertFalse(checklist["production_ready"], checklist)
        self.assertGreaterEqual(checklist["blocker_count"], 1)
        stages = {item["id"]: item for item in checklist["stages"]}
        self.assertIn("server_environment", stages)
        self.assertIn("external_integrations", stages)
        self.assertIn("backup_recovery", stages)
        self.assertIn("final_acceptance", stages)
        command_text = json.dumps(checklist["commands"], ensure_ascii=False)
        self.assertIn("production_smoke_check.py", command_text)
        self.assertIn("go_no_go_check.py", command_text)
        self.assertIn("--hook-contract-smoke", command_text)
        exported_text = json.dumps(checklist, ensure_ascii=False)
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

    def test_production_launch_checklist_docx_requires_director_and_contains_commands(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        response = self.raw_request("GET", "/api/production/checklist.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/checklist.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/checklist.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 2000)
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            names = set(docx.namelist())
            self.assertIn("word/document.xml", names)
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Чеклист production запуска", document_xml)
        self.assertIn("Финальная приемка", document_xml)
        self.assertIn("production_smoke_check.py", document_xml)
        self.assertIn("go_no_go_check.py", document_xml)
        self.assertIn("--hook-contract-smoke", document_xml)
        self.assertNotIn(TEST_DEMO_PASSWORD, document_xml)
        self.assertNotIn("token_hash", document_xml)

    def test_production_remaining_work_requires_director_and_exports_docx(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/production/remaining-work")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/production/remaining-work", token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("GET", "/api/production/remaining-work", token=director)
        self.assertEqual(status, 200, data)
        report = data["data"]
        self.assertEqual(report["format"], "qurulush-production-remaining-work-v1")
        self.assertFalse(report["production_ready"], report)
        self.assertGreaterEqual(report["remaining_count"], 1)
        self.assertGreaterEqual(report["blocker_count"], 1)
        self.assertIsInstance(report["current_step"], dict)
        step_ids = {str(item["id"]) for item in report["steps"]}
        self.assertIn("sacc2_api", step_ids)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        status, data = self.request(
            "POST",
            "/api/production/evidence",
            {
                "id": "sacc2_api",
                "status": "waiting_external",
                "owner": "IT-интегратор",
                "deadline": today,
                "evidence": "Назначен ответственный за официальный доступ sacc2.",
            },
            token=director,
        )
        self.assertEqual(status, 200, data)
        status, data = self.request("GET", "/api/production/remaining-work", token=director)
        self.assertEqual(status, 200, data)
        assigned_steps = {str(item["id"]): item for item in data["data"]["steps"]}
        self.assertEqual(assigned_steps["sacc2_api"]["owner"], "IT-интегратор")
        self.assertEqual(assigned_steps["sacc2_api"]["deadline"], today)
        self.assertEqual(assigned_steps["sacc2_api"]["evidence_status"], "waiting_external")
        self.assertEqual(assigned_steps["sacc2_api"]["urgency"], "today")
        self.assertEqual(assigned_steps["sacc2_api"]["days_left"], 0)
        self.assertIn("официальный доступ sacc2", assigned_steps["sacc2_api"]["evidence_note"])
        self.assertEqual(data["data"]["by_urgency"]["today"], 1)
        self.assertEqual(data["data"]["top_actions"][0]["id"], "sacc2_api")

        exported_text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)

        status, top_data = self.request("GET", "/api/production/top-actions")
        self.assertEqual(status, 401, top_data)
        status, top_data = self.request("GET", "/api/production/top-actions", token=engineer)
        self.assertEqual(status, 403, top_data)
        status, top_data = self.request("GET", "/api/production/top-actions", token=director)
        self.assertEqual(status, 200, top_data)
        top_actions = top_data["data"]
        self.assertEqual(top_actions["format"], "qurulush-production-top-actions-v1")
        self.assertGreaterEqual(top_actions["action_count"], 1)
        self.assertLessEqual(top_actions["action_count"], 5)
        self.assertEqual(top_actions["actions"][0]["id"], "sacc2_api")
        self.assertEqual(top_actions["actions"][0]["urgency"], "today")
        top_exported = json.dumps(top_actions, ensure_ascii=False)
        self.assertNotIn(TEST_DEMO_PASSWORD, top_exported)
        self.assertNotIn("token_hash", top_exported)

        status, alerts_data = self.request("GET", "/api/production/alerts")
        self.assertEqual(status, 401, alerts_data)
        status, alerts_data = self.request("GET", "/api/production/alerts", token=engineer)
        self.assertEqual(status, 403, alerts_data)
        status, alerts_data = self.request("GET", "/api/production/alerts", token=director)
        self.assertEqual(status, 200, alerts_data)
        alerts = alerts_data["data"]
        self.assertEqual(alerts["format"], "qurulush-production-alerts-v1")
        self.assertGreaterEqual(alerts["alert_count"], 1)
        self.assertGreaterEqual(alerts["urgent_count"], 1)
        sacc2_alert = next(item for item in alerts["alerts"] if item["production_step_id"] == "sacc2_api")
        self.assertTrue(sacc2_alert["urgent"])
        self.assertEqual(sacc2_alert["urgency"], "today")
        self.assertIn("IT-интегратор", sacc2_alert["text"])
        no_deadline_alert = next(item for item in alerts["alerts"] if item["urgency"] == "no_deadline")
        self.assertFalse(no_deadline_alert["urgent"])
        self.assertIn("Назначить дедлайн", no_deadline_alert["text"])

        status, generated = self.request("POST", "/api/production/alerts/generate", {}, engineer)
        self.assertEqual(status, 403, generated)
        status, generated = self.request("POST", "/api/production/alerts/generate", {}, director)
        self.assertEqual(status, 200, generated)
        self.assertGreaterEqual(generated["data"]["created_count"], 1)
        notifications = generated["notifications"]
        self.assertTrue(any(item.get("production_alert_key") == "production:sacc2_api" for item in notifications))
        self.assertTrue(any(item.get("urgent") and "Production:" in item.get("title", "") for item in notifications))
        status, generated_again = self.request("POST", "/api/production/alerts/generate", {}, director)
        self.assertEqual(status, 200, generated_again)
        self.assertEqual(generated_again["data"]["created_count"], 0)

        response = self.raw_request("GET", "/api/production/top-actions.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/top-actions.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/top-actions.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 2500)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            top_document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Ближайшие действия запуска", top_document_xml)
        self.assertIn("IT-интегратор", top_document_xml)
        self.assertNotIn(TEST_DEMO_PASSWORD, top_document_xml)
        self.assertNotIn("token_hash", top_document_xml)

        response = self.raw_request("GET", "/api/production/remaining-work.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/production/remaining-work.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/production/remaining-work.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 2500)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Что осталось до боевого запуска платформы", document_xml)
        self.assertIn("Пошаговый остаток", document_xml)
        self.assertIn("Интеграция sacc2", document_xml)
        self.assertNotIn(TEST_DEMO_PASSWORD, document_xml)
        self.assertNotIn("token_hash", document_xml)

    def test_acceptance_passport_requires_director_and_verifies_latest_backup(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/acceptance/passport")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/acceptance/passport", token=engineer)
        self.assertEqual(status, 403, data)

        status, backup = self.request("POST", "/api/backups", {}, director)
        self.assertEqual(status, 201, backup)
        status, data = self.request("GET", "/api/acceptance/passport", token=director)
        self.assertEqual(status, 200, data)
        passport = data["data"]
        self.assertEqual(passport["format"], "qurulush-acceptance-passport-v1")
        self.assertTrue(passport["local_acceptance"], passport)
        self.assertFalse(passport["production_acceptance"], passport)
        self.assertEqual(passport["backup_status"], "pass")
        self.assertEqual(passport["latest_backup"]["file"], backup["data"]["file"])
        self.assertEqual(passport["backup_verification"]["integrity"], "PRAGMA quick_check: ok")
        self.assertIn("sacc2_api", passport["production_blockers"])

    def test_acceptance_passport_docx_requires_director_and_contains_status(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")
        self.request("POST", "/api/backups", {}, director)

        response = self.raw_request("GET", "/api/acceptance/passport.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/acceptance/passport.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/acceptance/passport.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 2000)
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            names = set(docx.namelist())
            self.assertIn("word/document.xml", names)
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Паспорт приемки платформы строительной компании", document_xml)
        self.assertIn("Проверка backup", document_xml)
        self.assertIn("Production blockers", document_xml)

    def test_audit_export_requires_director_and_is_sanitized(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)
        engineer = self.login("engineer@company.kg")
        status, data = self.request("POST", "/api/requests/REQ-1048/reply", {"text": "Ответ для аудита."}, engineer)
        self.assertEqual(status, 200, data)

        status, data = self.request("GET", "/api/audit/export")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/audit/export", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/audit/export", token=director)
        self.assertEqual(status, 200, data)
        export = data["data"]
        self.assertEqual(export["format"], "qurulush-audit-export-v1")
        self.assertEqual(export["exported_by"], "Замирбек уулу Максат")
        self.assertTrue(any("REQ-1048" in item["event"] for item in export["audit"]))
        exported_text = json.dumps(export, ensure_ascii=False)
        self.assertNotIn("password", exported_text.lower())
        self.assertNotIn("sessions", exported_text.lower())
        self.assertNotIn("stored_file", exported_text)

    def test_reference_export_requires_login_and_marks_working_catalog(self) -> None:
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/reference/export")
        self.assertEqual(status, 401, data)

        status, data = self.request("GET", "/api/reference/export", token=engineer)
        self.assertEqual(status, 200, data)
        export = data["data"]
        self.assertEqual(export["format"], "qurulush-reference-catalog-v1")
        self.assertEqual(export["exported_by"], "Асанов Тимур")
        self.assertIn("Разрешительные документы", export["categories"])
        self.assertIn("Штрафы и нарушения", export["categories"])
        self.assertGreaterEqual(len(export["reference"]), 8)
        self.assertIn("Не является официальной правовой базой", export["source_note"])
        exported_text = json.dumps(export, ensure_ascii=False)
        self.assertNotIn("password", exported_text.lower())
        self.assertNotIn("sessions", exported_text.lower())
        self.assertNotIn("stored_file", exported_text)

    def test_reference_docx_export_requires_login_and_contains_catalog(self) -> None:
        director = self.login("director@company.kg")

        response = self.raw_request("GET", "/api/reference/export.docx")
        self.assertEqual(response["status"], 401, response)

        response = self.raw_request("GET", "/api/reference/export.docx", token=director)
        self.assertEqual(response["status"], 200, response["body"][:200])
        self.assertEqual(
            response["headers"].get("Content-Type"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertGreater(len(response["body"]), 2000)
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            names = set(docx.namelist())
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("word/document.xml", names)
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Справочник требований строительной компании", document_xml)
        self.assertIn("Разрешительные документы", document_xml)
        self.assertIn("Штрафы и нарушения", document_xml)
        self.assertIn("Не является официальной правовой базой", document_xml)
        self.assertNotIn("password", document_xml.lower())
        self.assertNotIn("sessions", document_xml.lower())
        self.assertNotIn("stored_file", document_xml)

    def test_interaction_map_requires_director_and_exports_docx(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/interaction/map")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/interaction/map", token=engineer)
        self.assertEqual(status, 403, data)
        status, data = self.request("GET", "/api/interaction/map", token=director)
        self.assertEqual(status, 200, data)
        interaction = data["data"]
        self.assertEqual(interaction["format"], "qurulush-dgask-interaction-map-v1")
        self.assertGreaterEqual(interaction["counts"]["open_requests"], 1)
        workflows = {item["id"]: item for item in interaction["workflows"]}
        self.assertIn("incoming_request", workflows)
        self.assertIn("state_fee_payment", workflows)
        self.assertIn("fine_or_violation", workflows)
        self.assertIn("production_exchange", workflows)
        exported_text = json.dumps(interaction, ensure_ascii=False)
        self.assertIn("Инспектор", exported_text)
        self.assertIn("Госпошлина", exported_text)
        self.assertIn("штраф", exported_text.lower())
        self.assertNotIn(TEST_DEMO_PASSWORD, exported_text)
        self.assertNotIn("token_hash", exported_text)
        self.assertNotIn("stored_file", exported_text)

        response = self.raw_request("GET", "/api/interaction/map.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/interaction/map.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/interaction/map.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertGreater(len(response["body"]), 3000)
        self.assertEqual(response["body"][:2], b"PK")
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Карта взаимодействия строительной компании", document_xml)
        self.assertIn("Входящий запрос инспектора", document_xml)
        self.assertIn("Госпошлина", document_xml)
        self.assertIn("Штраф", document_xml)
        self.assertNotIn(TEST_DEMO_PASSWORD, document_xml)
        self.assertNotIn("token_hash", document_xml)
        self.assertNotIn("stored_file", document_xml)

    def test_legal_verification_packet_requires_legal_access_and_contains_review_fields(self) -> None:
        director = self.login("director@company.kg")
        lawyer = self.login("lawyer@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/legal/verification-packet")
        self.assertEqual(status, 401, data)

        status, data = self.request("GET", "/api/legal/verification-packet", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/legal/verification-packet", token=lawyer)
        self.assertEqual(status, 200, data)
        packet = data["data"]
        self.assertEqual(packet["format"], "qurulush-legal-verification-packet-v1")
        self.assertEqual(packet["exported_by"], "Сыдыкова Элина")
        self.assertIn("Разрешительные документы", packet["categories"])
        self.assertIn("Штрафы и нарушения", packet["categories"])
        self.assertGreaterEqual(packet["counts"]["Разрешительные документы"], 1)
        self.assertGreaterEqual(len(packet["items"]), 8)
        first = packet["items"][0]
        self.assertEqual(first["verification_status"], "needs_review")
        self.assertIn("legal_source", first)
        self.assertIn("legal_basis_article", first)
        self.assertGreaterEqual(first["source_candidate_count"], 1)
        self.assertIn("source_candidates", first)
        self.assertFalse(first["tariff_or_penalty_confirmed"])
        self.assertIn("Действующие НПА Кыргызской Республики", packet["verification_scope"])
        self.assertEqual(packet["official_sources_checked_at"], "2026-09-14")
        source_ids = {item["id"]: item for item in packet["official_sources"]}
        self.assertIn("minstroy_order_93_2025", source_ids)
        self.assertIn("offenses_code_2021", source_ids)
        self.assertIn("minstroy_license_fee_service", source_ids)
        self.assertEqual(source_ids["expired_urban_fine_instruction_2005"]["status"], "expired_do_not_use_as_current_law")
        fine_item = next(item for item in packet["items"] if item["category"] == "Штрафы и нарушения")
        fine_source_ids = {item["id"] for item in fine_item["source_candidates"]}
        self.assertIn("offenses_code_2021", fine_source_ids)
        exported_text = json.dumps(packet, ensure_ascii=False)
        self.assertIn("госпошлин", exported_text)
        self.assertNotIn("password", exported_text.lower())
        self.assertNotIn("sessions", exported_text.lower())
        self.assertNotIn("stored_file", exported_text)

        response = self.raw_request("GET", "/api/legal/verification-packet.docx")
        self.assertEqual(response["status"], 401, response)
        response = self.raw_request("GET", "/api/legal/verification-packet.docx", token=engineer)
        self.assertEqual(response["status"], 403, response)
        response = self.raw_request("GET", "/api/legal/verification-packet.docx", token=director)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(
            response["headers"].get("Content-Type"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertGreater(len(response["body"]), 2500)
        with zipfile.ZipFile(BytesIO(response["body"])) as docx:
            names = set(docx.namelist())
            self.assertIn("word/document.xml", names)
            document_xml = docx.read("word/document.xml").decode("utf-8")
        self.assertIn("Пакет юридической сверки Qurulush Hub", document_xml)
        self.assertIn("Разрешения, госпошлины, штрафы", document_xml)
        self.assertIn("НПА/регламент", document_xml)
        self.assertIn("Статья/пункт", document_xml)
        self.assertIn("Официальные источники для сверки", document_xml)
        self.assertIn("minstroy_order_93_2025", document_xml)
        self.assertIn("offenses_code_2021", document_xml)
        self.assertIn("needs_review", document_xml)
        self.assertNotIn("password", document_xml.lower())
        self.assertNotIn("sessions", document_xml.lower())
        self.assertNotIn("stored_file", document_xml)

    def test_logout_invalidates_token(self) -> None:
        token = self.login("director@company.kg")
        status, data = self.request("GET", "/api/state", token=token)
        self.assertEqual(status, 200, data)
        status, data = self.request("POST", "/api/auth/logout", {}, token=token)
        self.assertEqual(status, 200, data)
        status, data = self.request("GET", "/api/state", token=token)
        self.assertEqual(status, 401, data)

    def test_sessions_are_stored_as_hashes_in_sqlite(self) -> None:
        import sqlite3

        token = self.login("director@company.kg")
        token_digest = hash_token(token)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT token_hash, email, expires_at, revoked_at FROM sessions WHERE token_hash = ?", (token_digest,)).fetchone()
            all_rows = conn.execute("SELECT token_hash FROM sessions").fetchall()

        self.assertIsNotNone(row)
        self.assertEqual(row["email"], "director@company.kg")
        self.assertEqual(len(row["token_hash"]), 64)
        self.assertIsNone(row["revoked_at"])
        self.assertNotIn(token, json.dumps([dict(item) for item in all_rows]))

        status, data = self.request("POST", "/api/auth/logout", {}, token=token)
        self.assertEqual(status, 200, data)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT revoked_at FROM sessions WHERE token_hash = ?", (token_digest,)).fetchone()
        self.assertIsNotNone(row["revoked_at"])

    def test_login_revokes_expired_sessions(self) -> None:
        expired_digest = hash_token("expired-session-token")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (token_hash, email, expires_at, created_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (expired_digest, "director@company.kg", 1, "expired-test"),
            )

        self.login("director@company.kg")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT revoked_at FROM sessions WHERE token_hash = ?", (expired_digest,)).fetchone()
        self.assertIsNotNone(row["revoked_at"])

    def test_director_can_view_active_sessions_without_token_hashes(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("GET", "/api/sessions")
        self.assertEqual(status, 401, data)
        status, data = self.request("GET", "/api/sessions", token=engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/sessions", token=director)
        self.assertEqual(status, 200, data)
        payload = data["data"]
        self.assertGreaterEqual(payload["active_count"], 2)
        self.assertGreaterEqual(payload["other_count"], 1)
        self.assertTrue(any(item["current"] for item in payload["sessions"]))
        self.assertTrue(any(item["email"] == "director@company.kg" for item in payload["sessions"]))
        exported_text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("token_hash", exported_text)
        self.assertNotIn(hash_token(director), exported_text)

    def test_director_can_revoke_expired_and_other_sessions(self) -> None:
        active = self.login("director@company.kg")
        other = self.login("director@company.kg")
        expired_digest = hash_token("expired-session-for-admin-control")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (token_hash, email, expires_at, created_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (expired_digest, "director@company.kg", 1, "expired-admin-control-test"),
            )

        status, data = self.request("POST", "/api/sessions/revoke-expired", {}, active)
        self.assertEqual(status, 200, data)
        self.assertGreaterEqual(data["data"]["revoked_count"], 1)
        self.assertTrue(any(item["current"] for item in data["data"]["sessions"]))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT revoked_at FROM sessions WHERE token_hash = ?", (expired_digest,)).fetchone()
        self.assertIsNotNone(row["revoked_at"])

        status, data = self.request("POST", "/api/sessions/revoke-others", {}, active)
        self.assertEqual(status, 200, data)
        self.assertGreaterEqual(data["data"]["revoked_count"], 1)
        self.assertEqual(data["data"]["active_count"], 1)
        self.assertEqual(data["data"]["other_count"], 0)
        status, data = self.request("GET", "/api/state", token=active)
        self.assertEqual(status, 200, data)
        status, data = self.request("GET", "/api/state", token=other)
        self.assertEqual(status, 401, data)

    def test_user_can_change_password_and_revoke_other_sessions(self) -> None:
        director = self.login("director@company.kg")
        status, data = self.request(
            "POST",
            "/api/team",
            {"name": "Смена Пароля", "role": "Прораб", "email": "password.user@company.kg", "password": "Temp2026!"},
            director,
        )
        self.assertEqual(status, 201, data)

        active_token = self.login_with_password("password.user@company.kg", "Temp2026!")
        stale_token = self.login_with_password("password.user@company.kg", "Temp2026!")
        status, data = self.request(
            "POST",
            "/api/auth/change-password",
            {"currentPassword": "wrong", "newPassword": "Changed2026!"},
            active_token,
        )
        self.assertEqual(status, 401, data)

        status, data = self.request(
            "POST",
            "/api/auth/change-password",
            {"currentPassword": "Temp2026!", "newPassword": "Changed2026!"},
            active_token,
        )
        self.assertEqual(status, 200, data)
        self.assertEqual(data["data"]["email"], "password.user@company.kg")

        status, data = self.request("GET", "/api/state", token=active_token)
        self.assertEqual(status, 200, data)
        status, data = self.request("GET", "/api/state", token=stale_token)
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/auth/login", {"email": "password.user@company.kg", "password": "Temp2026!"})
        self.assertEqual(status, 401, data)
        new_token = self.login_with_password("password.user@company.kg", "Changed2026!")
        status, data = self.request("GET", "/api/state", token=new_token)
        self.assertEqual(status, 200, data)

    def test_state_is_scoped_by_role(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        status, director_state = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200, director_state)
        self.assertGreater(len(director_state["data"]["requests"]), 0)
        self.assertGreater(len(director_state["data"]["documents"]), 0)
        self.assertGreater(len(director_state["data"]["money"]), 0)
        self.assertGreater(len(director_state["data"]["team"]), 1)

        brigadier = self.login("brigadier@company.kg")
        status, brigadier_state = self.request("GET", "/api/state", token=brigadier)
        self.assertEqual(status, 200, brigadier_state)
        self.assertEqual(brigadier_state["data"]["requests"], [])
        self.assertEqual(brigadier_state["data"]["documents"], [])
        self.assertEqual(brigadier_state["data"]["money"], [])
        self.assertGreater(len(brigadier_state["data"]["objects"]), 0)
        self.assertGreater(len(brigadier_state["data"]["inspections"]), 0)
        self.assertEqual(brigadier_state["data"]["team"][0]["email"], "brigadier@company.kg")

        accountant = self.login("accountant@company.kg")
        status, accountant_state = self.request("GET", "/api/state", token=accountant)
        self.assertEqual(status, 200, accountant_state)
        self.assertEqual(accountant_state["data"]["requests"], [])
        self.assertEqual(accountant_state["data"]["inspections"], [])
        self.assertGreater(len(accountant_state["data"]["documents"]), 0)
        self.assertGreater(len(accountant_state["data"]["money"]), 0)

        lawyer = self.login("lawyer@company.kg")
        status, lawyer_state = self.request("GET", "/api/state", token=lawyer)
        self.assertEqual(status, 200, lawyer_state)
        self.assertGreater(len(lawyer_state["data"]["requests"]), 0)
        self.assertGreater(len(lawyer_state["data"]["documents"]), 0)
        self.assertGreater(len(lawyer_state["data"]["money"]), 0)
        self.assertEqual(lawyer_state["data"]["inspections"], [])

    def test_internal_chat_and_calendar_are_scoped_and_persisted(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        status, data = self.request("GET", "/api/calendar")
        self.assertEqual(status, 401, data)

        status, calendar = self.request("GET", "/api/calendar", token=director)
        self.assertEqual(status, 200, calendar)
        self.assertEqual(calendar["data"]["format"], "qurulush-calendar-v1")
        self.assertGreater(calendar["data"]["open_count"], 0)
        kinds = {item["kind"] for item in calendar["data"]["items"]}
        self.assertIn("Поручение", kinds)
        self.assertIn("Запрос", kinds)
        self.assertIn("Документ", kinds)
        self.assertIn("Платеж / штраф", kinds)

        brigadier = self.login("brigadier@company.kg")
        status, brigadier_calendar = self.request("GET", "/api/calendar", token=brigadier)
        self.assertEqual(status, 200, brigadier_calendar)
        self.assertTrue(
            all(item.get("object") in {3, None, ""} for item in brigadier_calendar["data"]["items"]),
            brigadier_calendar,
        )
        self.assertNotIn("Платеж / штраф", {item["kind"] for item in brigadier_calendar["data"]["items"]})

        status, data = self.request("POST", "/api/chat", {"message": "Что сегодня срочно по срокам и ДГАСК?"})
        self.assertEqual(status, 401, data)

        status, chat = self.request(
            "POST",
            "/api/chat",
            {"message": "Что сегодня срочно по срокам и ДГАСК?", "object": 1},
            director,
        )
        self.assertEqual(status, 201, chat)
        self.assertEqual(chat["data"]["format"], "qurulush-internal-chat-v1")
        self.assertIn("assistant", chat)
        self.assertIn("срок", chat["assistant"]["text"].lower())
        self.assertEqual(chat["assistant"]["object"], 1)

        status, stored_chat = self.request("GET", "/api/chat", token=director)
        self.assertEqual(status, 200, stored_chat)
        self.assertGreaterEqual(len(stored_chat["data"]["messages"]), 2)
        self.assertNotIn("token_hash", json.dumps(stored_chat, ensure_ascii=False))

        status, state = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200, state)
        self.assertTrue(any(item["event"] == "Сообщение во внутреннем чате с ИИ" for item in state["data"]["audit"]))

    def test_object_assignments_scope_visibility_and_actions(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        foreman = self.login("foreman@company.kg")
        status, foreman_state = self.request("GET", "/api/state", token=foreman)
        self.assertEqual(status, 200, foreman_state)
        self.assertEqual({obj["id"] for obj in foreman_state["data"]["objects"]}, {1, 2})
        self.assertFalse(any(item.get("object") == 3 for item in foreman_state["data"]["requests"]))
        self.assertFalse(any(item.get("object") == 3 for item in foreman_state["data"]["documents"]))

        status, data = self.request("POST", "/api/requests/REQ-1029/reply", {"text": "чужой объект"}, foreman)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/requests/REQ-1048/reply", {"text": "мой объект"}, foreman)
        self.assertEqual(status, 200, data)

        brigadier = self.login("brigadier@company.kg")
        status, brigadier_state = self.request("GET", "/api/state", token=brigadier)
        self.assertEqual(status, 200, brigadier_state)
        self.assertEqual({obj["id"] for obj in brigadier_state["data"]["objects"]}, {3})
        self.assertEqual(brigadier_state["data"]["requests"], [])

        status, data = self.request("POST", "/api/inspections/1/prepare", {}, brigadier)
        self.assertEqual(status, 403, data)
        status, data = self.request("POST", "/api/inspections/0/prepare", {}, brigadier)
        self.assertEqual(status, 200, data)

        status, data = self.request(
            "POST",
            "/api/team",
            {"name": "Назначенный бригадир", "role": "Бригадир", "email": "assigned.brigadier@company.kg", "password": "Temp2026!", "objectIds": [2]},
            director,
        )
        self.assertEqual(status, 201, data)
        self.assertEqual(data["data"]["object_ids"], [2])

        assigned = self.login_with_password("assigned.brigadier@company.kg", "Temp2026!")
        status, assigned_state = self.request("GET", "/api/state", token=assigned)
        self.assertEqual(status, 200, assigned_state)
        self.assertEqual({obj["id"] for obj in assigned_state["data"]["objects"]}, {2})
        status, data = self.request("POST", "/api/inspections/1/prepare", {}, assigned)
        self.assertEqual(status, 200, data)

    def test_tasks_are_scoped_and_require_evidence_to_close(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        accountant = self.login("accountant@company.kg")
        status, accountant_state = self.request("GET", "/api/state", token=accountant)
        self.assertEqual(status, 200, accountant_state)
        self.assertEqual(accountant_state["data"]["tasks"], [])

        engineer = self.login("engineer@company.kg")
        status, data = self.request(
            "POST",
            "/api/tasks",
            {
                "title": "Проверить акты по объекту 1",
                "text": "Сверить комплект перед ответом инспектору.",
                "object": 1,
                "owner": "Прораб",
                "priority": "high",
                "due": "18.09.2026",
                "source": "REQ-1048",
            },
            engineer,
        )
        self.assertEqual(status, 201, data)
        task_id = data["data"]["id"]

        brigadier = self.login("brigadier@company.kg")
        status, data = self.request("POST", f"/api/tasks/{task_id}/update", {"status": "done", "evidence": "чужой объект"}, brigadier)
        self.assertEqual(status, 403, data)

        foreman = self.login("foreman@company.kg")
        status, data = self.request("POST", f"/api/tasks/{task_id}/update", {"status": "done"}, foreman)
        self.assertEqual(status, 400, data)
        status, data = self.request("POST", f"/api/tasks/{task_id}/update", {"status": "done", "evidence": "Акты проверены и приложены."}, foreman)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["data"]["status"], "done")
        self.assertEqual(data["data"]["evidence"], "Акты проверены и приложены.")

        status, brigadier_state = self.request("GET", "/api/state", token=brigadier)
        self.assertEqual(status, 200, brigadier_state)
        self.assertTrue(all(item["object"] == 3 for item in brigadier_state["data"]["tasks"]))
        status, data = self.request("POST", "/api/tasks/TASK-2/update", {"status": "blocked", "evidence": "Не хватает сертификатов."}, brigadier)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["data"]["status"], "blocked")

    def test_backup_endpoint_requires_director_and_writes_manifest(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")

        status, data = self.request("POST", "/api/backups", {}, engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/backups", {}, director)
        self.assertEqual(status, 201, data)
        backup = data["data"]
        backup_file = self.backup_root / backup["file"]
        manifest_file = self.backup_root / backup["manifest"]
        self.assertTrue(backup_file.exists())
        self.assertGreater(backup_file.stat().st_size, 0)
        self.assertTrue(manifest_file.exists())
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(manifest["created_by"], "Замирбек уулу Максат")
        self.assertEqual(Path(manifest["backup"]).resolve(), backup_file.resolve())
        self.assertEqual(manifest["sha256"], hashlib.sha256(backup_file.read_bytes()).hexdigest())
        self.assertEqual(backup["sha256"], manifest["sha256"])

    def test_remote_backup_command_syncs_backup_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote"
            sync_script = root / "sync-backup.sh"
            sync_script.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "mkdir -p \"$REMOTE_DIR\"\n"
                "cp \"$1\" \"$REMOTE_DIR/$(basename \"$1\")\"\n"
                "cp \"$2\" \"$REMOTE_DIR/$(basename \"$2\")\"\n",
                encoding="utf-8",
            )
            sync_script.chmod(0o755)
            env = {
                "QH_BACKUP_REMOTE_CMD": str(sync_script),
                "QH_BACKUP_REMOTE_URL": "file://remote-test",
                "REMOTE_DIR": str(remote),
            }
            with patch.dict(os.environ, env, clear=False):
                server = make_server(
                    "127.0.0.1",
                    0,
                    root / "remote.sqlite3",
                    upload_root=root / "uploads",
                    backup_root=root / "backups",
                    quiet=True,
                )
                host, port = server.server_address
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "director@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    director = data["token"]

                    status, backup = raw_http_request(host, port, "POST", "/api/backups", {}, director)
                    self.assertEqual(status, 201, backup)
                    self.assertTrue(backup["data"]["remote_synced"])
                    backup_file = backup["data"]["file"]
                    manifest_file = backup["data"]["manifest"]
                    self.assertTrue((remote / backup_file).exists())
                    self.assertTrue((remote / manifest_file).exists())
                    manifest = json.loads((root / "backups" / manifest_file).read_text(encoding="utf-8"))
                    self.assertIn("remote_synced_at", manifest)

                    status, readiness = raw_http_request(host, port, "GET", "/api/readiness", token=director)
                    self.assertEqual(status, 200, readiness)
                    checks = {item["id"]: item for item in readiness["data"]["checks"]}
                    self.assertEqual(checks["backup_remote"]["status"], "pass")
                finally:
                    server.shutdown()
                    server.server_close()

    def test_backup_list_and_restore_roundtrip(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        status, backup_data = self.request("POST", "/api/backups", {}, director)
        self.assertEqual(status, 201, backup_data)
        backup_file = backup_data["data"]["file"]
        manifest_path = (self.backup_root / backup_file).with_suffix(".json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("sha256")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        lawyer = self.login("lawyer@company.kg")
        status, data = self.request(
            "POST",
            "/api/requests",
            {"title": "Временный запрос перед восстановлением", "text": "Эта запись должна исчезнуть после restore.", "object": 1},
            lawyer,
        )
        self.assertEqual(status, 201, data)

        status, list_data = self.request("GET", "/api/backups", token=director)
        self.assertEqual(status, 200, list_data)
        self.assertTrue(any(item["file"] == backup_file for item in list_data["data"]))
        listed_backup = next(item for item in list_data["data"] if item["file"] == backup_file)
        self.assertEqual(len(listed_backup["sha256"]), 64)
        repaired_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(repaired_manifest["sha256"]), 64)
        self.assertIn("checksum_added_at", repaired_manifest)

        status, verified = self.request("POST", "/api/backups/verify", {"file": backup_file}, director)
        self.assertEqual(status, 200, verified)
        self.assertEqual(verified["data"]["file"], backup_file)
        self.assertEqual(verified["data"]["integrity"], "PRAGMA quick_check: ok")
        self.assertEqual(verified["data"]["sha256"], repaired_manifest["sha256"])
        self.assertGreaterEqual(verified["data"]["counts"]["requests"], 3)

        status, readiness = self.request("GET", "/api/readiness", token=director)
        self.assertEqual(status, 200, readiness)
        checks = {item["id"]: item for item in readiness["data"]["checks"]}
        self.assertEqual(checks["backup_freshness"]["status"], "pass")
        self.assertEqual(readiness["data"]["counts"]["backup_manifests_invalid"], 0)

        status, data = self.request("POST", "/api/backups/restore", {"file": "../bad.sqlite3"}, director)
        self.assertEqual(status, 400, data)

        corrupted_backup = self.backup_root / "corrupted.sqlite3"
        corrupted_backup.write_bytes(b"not a sqlite backup")
        status, data = self.request("POST", "/api/backups/restore", {"file": corrupted_backup.name}, director)
        self.assertEqual(status, 400, data)
        self.assertEqual(data["error"], "backup manifest is missing")

        corrupted_backup.with_suffix(".json").write_text(
            json.dumps({"sha256": hashlib.sha256(corrupted_backup.read_bytes()).hexdigest()}, ensure_ascii=False),
            encoding="utf-8",
        )
        status, data = self.request("POST", "/api/backups/restore", {"file": corrupted_backup.name}, director)
        self.assertEqual(status, 400, data)
        self.assertIn("backup integrity failed", data["error"])

        tampered_backup = self.backup_root / "tampered.sqlite3"
        tampered_manifest = tampered_backup.with_suffix(".json")
        shutil.copy(self.backup_root / backup_file, tampered_backup)
        shutil.copy((self.backup_root / backup_file).with_suffix(".json"), tampered_manifest)
        with sqlite3.connect(tampered_backup) as conn:
            row = conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
            tampered_payload = json.loads(row[0])
            tampered_payload["requests"].append({"id": "TAMPERED", "title": "Подмена", "object": 1})
            conn.execute("UPDATE app_state SET payload = ?, updated_at = ? WHERE id = 1", (json.dumps(tampered_payload, ensure_ascii=False), "tampered"))
        status, data = self.request("POST", "/api/backups/restore", {"file": tampered_backup.name}, director)
        self.assertEqual(status, 400, data)
        self.assertEqual(data["error"], "backup sha256 mismatch")

        for path in (corrupted_backup, corrupted_backup.with_suffix(".json"), tampered_backup, tampered_manifest):
            path.unlink(missing_ok=True)

        status, restore_data = self.request("POST", "/api/backups/restore", {"file": backup_file}, director)
        self.assertEqual(status, 200, restore_data)
        self.assertEqual(restore_data["data"]["restored_from"], backup_file)
        self.assertTrue(restore_data["data"]["safety_backup"].endswith(".sqlite3"))

        status, state = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200, state)
        self.assertFalse(any(r["title"] == "Временный запрос перед восстановлением" for r in state["data"]["requests"]))
        self.assertTrue(any("Восстановлено состояние" in item["event"] for item in state["data"]["audit"]))

    def test_backup_restore_drill_requires_director_and_does_not_change_live_state(self) -> None:
        director = self.login("director@company.kg")
        engineer = self.login("engineer@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        status, backup_data = self.request("POST", "/api/backups", {}, director)
        self.assertEqual(status, 201, backup_data)
        backup_file = backup_data["data"]["file"]
        status, created = self.request(
            "POST",
            "/api/requests",
            {"title": "Запрос после backup для drill", "text": "Должен остаться после dry-run.", "object": 1},
            director,
        )
        self.assertEqual(status, 201, created)

        status, data = self.request("POST", "/api/backups/restore-drill", {"file": backup_file})
        self.assertEqual(status, 401, data)
        status, data = self.request("POST", "/api/backups/restore-drill", {"file": backup_file}, engineer)
        self.assertEqual(status, 403, data)

        status, drill = self.request("POST", "/api/backups/restore-drill", {"file": backup_file}, director)
        self.assertEqual(status, 200, drill)
        result = drill["data"]
        self.assertTrue(result["ok"])
        self.assertEqual(result["file"], backup_file)
        self.assertEqual(result["source_integrity"], "PRAGMA quick_check: ok")
        self.assertEqual(result["restored_integrity"], "PRAGMA quick_check: ok")
        self.assertTrue(result["temp_database_removed"])
        self.assertIn("objects", result["backup_counts"])
        self.assertIn("objects", result["restored_counts"])

        status, state = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200, state)
        self.assertTrue(any(r["title"] == "Запрос после backup для drill" for r in state["data"]["requests"]))

    def test_scheduled_backups_create_sqlite_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "QH_BACKUP_INTERVAL_SECONDS": "1",
                "QH_BACKUP_ON_START": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                server = make_server(
                    "127.0.0.1",
                    0,
                    root / "scheduled.sqlite3",
                    upload_root=root / "uploads",
                    backup_root=root / "backups",
                    quiet=True,
                )
                host, port = server.server_address
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    deadline = time.monotonic() + 4
                    backup_files = []
                    while time.monotonic() < deadline:
                        backup_files = list((root / "backups").glob("*.sqlite3"))
                        if len(backup_files) >= 2:
                            break
                        time.sleep(0.1)
                    self.assertGreaterEqual(len(backup_files), 2)
                    self.assertTrue(all(path.with_suffix(".json").exists() for path in backup_files))

                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "director@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    status, readiness = raw_http_request(host, port, "GET", "/api/readiness", token=data["token"])
                    self.assertEqual(status, 200, readiness)
                    checks = {item["id"]: item for item in readiness["data"]["checks"]}
                    self.assertEqual(checks["backup_schedule"]["status"], "pass")
                    self.assertEqual(checks["backup_remote"]["status"], "missing")
                finally:
                    server.shutdown()
                    server.server_close()

    def test_exchange_import_and_export_are_permissioned_and_sanitized(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        engineer = self.login("engineer@company.kg")
        payload = {
            "source": "ДГАСК",
            "title": "Входящий запрос по исполнительной документации",
            "text": "Предоставить журнал работ и акты скрытых работ.",
            "object": 1,
            "due": "21.09.2026",
            "owner": "Главный инженер",
        }
        status, data = self.request("POST", "/api/exchange/incoming", payload, engineer)
        self.assertEqual(status, 403, data)

        status, data = self.request("POST", "/api/exchange/incoming", payload, director)
        self.assertEqual(status, 201, data)
        self.assertTrue(data["data"]["id"].startswith("EXT-"))
        self.assertEqual(data["data"]["from"], "ДГАСК")
        self.assertEqual(data["data"]["status"], "needs_company")

        status, data = self.request("POST", "/api/exchange/incoming", {**payload, "source": "Unknown"}, director)
        self.assertEqual(status, 400, data)

        file_payload = b64encode(b"exchange document").decode("ascii")
        status, data = self.request(
            "POST",
            "/api/documents/DOC-4/upload",
            {"fileName": "exchange-doc.pdf", "contentBase64": file_payload},
            director,
        )
        self.assertEqual(status, 200, data)
        self.assertIn("stored_file", data["data"])
        self.assertIn("file_sha256", data["data"])
        self.assertEqual(data["data"]["versions"][0]["file_sha256"], hashlib.sha256(b"exchange document").hexdigest())

        brigadier = self.login("brigadier@company.kg")
        status, data = self.request("GET", "/api/exchange/export", token=brigadier)
        self.assertEqual(status, 403, data)

        status, data = self.request("GET", "/api/exchange/export", token=director)
        self.assertEqual(status, 200, data)
        export = data["data"]
        self.assertEqual(export["format"], "qurulush-company-exchange-v1")
        self.assertTrue(any(r["title"] == payload["title"] for r in export["requests"]))
        self.assertTrue(any(task["id"] == "TASK-1" for task in export["tasks"]))
        exported_text = json.dumps(export, ensure_ascii=False)
        self.assertNotIn("users", exported_text)
        self.assertNotIn("password", exported_text.lower())
        self.assertNotIn("stored_file", exported_text)
        self.assertNotIn("/api/documents/", exported_text)

    def test_sacc2_sync_command_receives_sanitized_exchange_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync_dir = root / "sacc2"
            sync_script = root / "sacc2-sync.sh"
            sync_script.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "mkdir -p \"$2\"\n"
                "cp \"$1\" \"$2/payload.json\"\n",
                encoding="utf-8",
            )
            sync_script.chmod(0o755)
            env = {
                "QH_SACC2_API_URL": "https://sacc2.example.test/api",
                "QH_SACC2_API_KEY": "secret-sacc2-key",
                "QH_SACC2_SYNC_CMD": f"{sync_script} {{payload}} {sync_dir}",
            }
            with patch.dict(os.environ, env, clear=False):
                server = make_server(
                    "127.0.0.1",
                    0,
                    root / "sacc2.sqlite3",
                    upload_root=root / "uploads",
                    backup_root=root / "backups",
                    quiet=True,
                )
                host, port = server.server_address
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "engineer@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    engineer = data["token"]
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "director@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    director = data["token"]

                    status, denied = raw_http_request(host, port, "POST", "/api/sacc2/sync", {}, engineer)
                    self.assertEqual(status, 403, denied)

                    status, synced = raw_http_request(host, port, "POST", "/api/sacc2/sync", {}, director)
                    self.assertEqual(status, 200, synced)
                    self.assertEqual(synced["data"]["status"], "synced")
                    self.assertEqual(synced["data"]["synced_by"], "Замирбек уулу Максат")
                    payload_text = (sync_dir / "payload.json").read_text(encoding="utf-8")
                    payload = json.loads(payload_text)
                    self.assertEqual(payload["format"], "qurulush-company-exchange-v1")
                    self.assertEqual(payload["target"], "sacc2")
                    self.assertEqual(payload["api_url"], "https://sacc2.example.test/api")
                    self.assertIn("requests", payload)
                    self.assertIn("documents", payload)
                    self.assertNotIn("secret-sacc2-key", payload_text)
                    self.assertNotIn("stored_file", payload_text)
                    self.assertNotIn("/api/documents/", payload_text)

                    status, state = raw_http_request(host, port, "GET", "/api/state", token=director)
                    self.assertEqual(status, 200, state)
                    self.assertEqual(state["data"]["integrations"]["sacc2"]["status"], "synced")
                    self.assertTrue(any("sacc2" in item["event"] for item in state["data"]["audit"]))

                    status, readiness = raw_http_request(host, port, "GET", "/api/readiness", token=director)
                    self.assertEqual(status, 200, readiness)
                    checks = {item["id"]: item for item in readiness["data"]["checks"]}
                    self.assertEqual(checks["sacc2_api"]["status"], "pass")
                finally:
                    server.shutdown()
                    server.server_close()

    def test_document_versions_checksum_and_unsafe_content_rejection(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)
        engineer = self.login("engineer@company.kg")

        first = b64encode(b"first document body").decode("ascii")
        status, data = self.request(
            "POST",
            "/api/documents/DOC-3/upload",
            {"fileName": "project-v1.txt", "contentBase64": first},
            engineer,
        )
        self.assertEqual(status, 200, data)
        self.assertEqual(data["data"]["file_sha256"], hashlib.sha256(b"first document body").hexdigest())
        self.assertEqual(len(data["data"]["versions"]), 1)
        self.assertEqual(data["data"]["versions"][0]["uploaded_by"], "Асанов Тимур")

        second = b64encode(b"second document body").decode("ascii")
        status, data = self.request(
            "POST",
            "/api/documents/DOC-3/upload",
            {"fileName": "project-v2.txt", "contentBase64": second},
            engineer,
        )
        self.assertEqual(status, 200, data)
        self.assertEqual(len(data["data"]["versions"]), 2)
        self.assertEqual(data["data"]["versions"][1]["id"], "VER-2")
        self.assertEqual(data["data"]["versions"][1]["file_sha256"], hashlib.sha256(b"second document body").hexdigest())

        unsafe = b64encode(b"MZnot really a text file").decode("ascii")
        status, data = self.request(
            "POST",
            "/api/documents/DOC-3/upload",
            {"fileName": "masked.txt", "contentBase64": unsafe},
            engineer,
        )
        self.assertEqual(status, 400, data)

        status, export_data = self.request("GET", "/api/exchange/export", token=director)
        self.assertEqual(status, 200, export_data)
        exported_text = json.dumps(export_data["data"], ensure_ascii=False)
        self.assertIn("file_sha256", exported_text)
        self.assertNotIn("stored_file", exported_text)
        self.assertNotIn("/api/documents/", exported_text)

    def test_configured_storage_sync_command_marks_uploaded_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external_storage = root / "external-storage"
            sync_script = root / "sync-upload.sh"
            sync_script.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "mkdir -p \"$2\"\n"
                "cp \"$1\" \"$2/$(basename \"$1\")\"\n",
                encoding="utf-8",
            )
            sync_script.chmod(0o755)
            env = {
                "QH_STORAGE_MODE": "external",
                "QH_STORAGE_URL": "file://external-storage",
                "QH_STORAGE_SYNC_CMD": f"{sync_script} {{file}} {external_storage}/{{doc_id}}",
            }
            with patch.dict(os.environ, env, clear=False):
                server = make_server(
                    "127.0.0.1",
                    0,
                    root / "storage.sqlite3",
                    upload_root=root / "uploads",
                    backup_root=root / "backups",
                    quiet=True,
                )
                host, port = server.server_address
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "director@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    director = data["token"]
                    payload = b64encode(b"storage sync body").decode("ascii")

                    status, upload = raw_http_request(
                        host,
                        port,
                        "POST",
                        "/api/documents/DOC-3/upload",
                        {"fileName": "storage.txt", "contentBase64": payload},
                        director,
                    )
                    self.assertEqual(status, 200, upload)
                    stored_file = upload["data"]["stored_file"]
                    self.assertEqual(upload["data"]["storage_mode"], "external")
                    self.assertIn("storage_synced_at", upload["data"])
                    self.assertTrue((external_storage / "DOC-3" / stored_file).exists())

                    status, state = raw_http_request(host, port, "GET", "/api/state", token=director)
                    self.assertEqual(status, 200, state)
                    doc = next(item for item in state["data"]["documents"] if item["id"] == "DOC-3")
                    self.assertEqual(doc["versions"][-1]["storage_mode"], "external")
                    self.assertIn("storage_synced_at", doc["versions"][-1])

                    status, readiness = raw_http_request(host, port, "GET", "/api/readiness", token=director)
                    self.assertEqual(status, 200, readiness)
                    checks = {item["id"]: item for item in readiness["data"]["checks"]}
                    self.assertEqual(checks["object_storage"]["status"], "pass")
                finally:
                    server.shutdown()
                    server.server_close()

    def test_eds_signing_command_signs_documents_before_persisting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sign_dir = root / "signed"
            sign_script = root / "eds-sign.sh"
            sign_script.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "mkdir -p \"$2\"\n"
                "cp \"$1\" \"$2/signature.json\"\n"
                "if grep -q REJECT \"$1\"; then\n"
                "  exit 1\n"
                "fi\n",
                encoding="utf-8",
            )
            sign_script.chmod(0o755)
            env = {
                "QH_EDS_PROVIDER": "test-eds",
                "QH_EDS_API_URL": "https://eds.example.test/sign",
                "QH_EDS_SIGN_CMD": f"{sign_script} {{payload}} {sign_dir}",
            }
            with patch.dict(os.environ, env, clear=False):
                server = make_server(
                    "127.0.0.1",
                    0,
                    root / "eds.sqlite3",
                    upload_root=root / "uploads",
                    backup_root=root / "backups",
                    quiet=True,
                )
                host, port = server.server_address
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "engineer@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    engineer = data["token"]
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "accountant@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    accountant = data["token"]
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "director@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    director = data["token"]

                    payload = b64encode(b"document for signing").decode("ascii")
                    status, upload = raw_http_request(
                        host,
                        port,
                        "POST",
                        "/api/documents/DOC-3/upload",
                        {"fileName": "sign-me.txt", "contentBase64": payload},
                        engineer,
                    )
                    self.assertEqual(status, 200, upload)

                    status, denied = raw_http_request(host, port, "POST", "/api/documents/DOC-3/sign", {"comment": "accountant sign"}, accountant)
                    self.assertEqual(status, 403, denied)

                    status, signed = raw_http_request(host, port, "POST", "/api/documents/DOC-3/sign", {"comment": "Готово к отправке"}, engineer)
                    self.assertEqual(status, 200, signed)
                    self.assertEqual(signed["data"]["status"], "Подписан")
                    self.assertEqual(signed["data"]["signature_status"], "signed")
                    self.assertEqual(signed["data"]["signed_by"], "Асанов Тимур")
                    signature_payload = json.loads((sign_dir / "signature.json").read_text(encoding="utf-8"))
                    self.assertEqual(signature_payload["document_id"], "DOC-3")
                    self.assertEqual(signature_payload["comment"], "Готово к отправке")
                    self.assertEqual(signature_payload["file_sha256"], upload["data"]["file_sha256"])

                    status, upload_doc4 = raw_http_request(
                        host,
                        port,
                        "POST",
                        "/api/documents/DOC-4/upload",
                        {"fileName": "reject-sign.txt", "contentBase64": payload},
                        engineer,
                    )
                    self.assertEqual(status, 200, upload_doc4)
                    status, rejected = raw_http_request(host, port, "POST", "/api/documents/DOC-4/sign", {"comment": "REJECT"}, engineer)
                    self.assertEqual(status, 503, rejected)
                    status, state = raw_http_request(host, port, "GET", "/api/state", token=director)
                    self.assertEqual(status, 200, state)
                    doc4 = next(item for item in state["data"]["documents"] if item["id"] == "DOC-4")
                    self.assertNotIn("signature_status", doc4)

                    status, readiness = raw_http_request(host, port, "GET", "/api/readiness", token=director)
                    self.assertEqual(status, 200, readiness)
                    checks = {item["id"]: item for item in readiness["data"]["checks"]}
                    self.assertEqual(checks["eds"]["status"], "pass")
                finally:
                    server.shutdown()
                    server.server_close()

    def test_configured_antivirus_scanner_checks_uploads_before_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scanner = root / "fake-av.sh"
            scanner.write_text(
                "#!/bin/sh\n"
                "if grep -q EICAR \"$1\"; then\n"
                "  exit 1\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            scanner.chmod(0o755)

            with patch.dict(os.environ, {"QH_AV_SCANNER": str(scanner)}, clear=False):
                server = make_server(
                    "127.0.0.1",
                    0,
                    root / "av.sqlite3",
                    upload_root=root / "uploads",
                    backup_root=root / "backups",
                    quiet=True,
                )
                host, port = server.server_address
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "director@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    director = data["token"]

                    clean = b64encode(b"clean document body").decode("ascii")
                    status, data = raw_http_request(
                        host,
                        port,
                        "POST",
                        "/api/documents/DOC-3/upload",
                        {"fileName": "clean.txt", "contentBase64": clean},
                        director,
                    )
                    self.assertEqual(status, 200, data)
                    self.assertTrue((root / "uploads" / data["data"]["stored_file"]).exists())

                    infected = b64encode(b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE").decode("ascii")
                    status, data = raw_http_request(
                        host,
                        port,
                        "POST",
                        "/api/documents/DOC-4/upload",
                        {"fileName": "infected.txt", "contentBase64": infected},
                        director,
                    )
                    self.assertEqual(status, 400, data)

                    status, state = raw_http_request(host, port, "GET", "/api/state", token=director)
                    self.assertEqual(status, 200, state)
                    doc = next(item for item in state["data"]["documents"] if item["id"] == "DOC-4")
                    self.assertNotEqual(doc.get("file"), "infected.txt")
                    self.assertEqual(doc.get("versions", []), [])

                    status, readiness = raw_http_request(host, port, "GET", "/api/readiness", token=director)
                    self.assertEqual(status, 200, readiness)
                    checks = {item["id"]: item for item in readiness["data"]["checks"]}
                    self.assertEqual(checks["av_scan"]["status"], "pass")
                finally:
                    server.shutdown()
                    server.server_close()

    def test_strict_antivirus_scanner_requires_json_before_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scanner = root / "json-av.sh"
            scanner.write_text(
                "#!/bin/sh\n"
                "if grep -q BADJSON \"$1\"; then\n"
                "  echo not-json\n"
                "  exit 0\n"
                "fi\n"
                "echo '{\"status\":\"clean\",\"provider\":\"test-av\"}'\n",
                encoding="utf-8",
            )
            scanner.chmod(0o755)

            with patch.dict(os.environ, {"QH_REQUIRE_HOOK_JSON": "1", "QH_AV_SCANNER": f"{scanner} {{file}}"}, clear=False):
                server = make_server(
                    "127.0.0.1",
                    0,
                    root / "av-json.sqlite3",
                    upload_root=root / "uploads",
                    backup_root=root / "backups",
                    quiet=True,
                )
                host, port = server.server_address
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "director@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    director = data["token"]

                    clean = b64encode(b"clean json scanned document").decode("ascii")
                    status, upload = raw_http_request(
                        host,
                        port,
                        "POST",
                        "/api/documents/DOC-3/upload",
                        {"fileName": "clean-json.txt", "contentBase64": clean},
                        director,
                    )
                    self.assertEqual(status, 200, upload)
                    self.assertTrue((root / "uploads" / upload["data"]["stored_file"]).exists())

                    bad_json = b64encode(b"BADJSON document body").decode("ascii")
                    status, rejected = raw_http_request(
                        host,
                        port,
                        "POST",
                        "/api/documents/DOC-4/upload",
                        {"fileName": "bad-json.txt", "contentBase64": bad_json},
                        director,
                    )
                    self.assertEqual(status, 503, rejected)
                    self.assertIn("invalid JSON", rejected["error"])

                    status, state = raw_http_request(host, port, "GET", "/api/state", token=director)
                    self.assertEqual(status, 200, state)
                    doc = next(item for item in state["data"]["documents"] if item["id"] == "DOC-4")
                    self.assertEqual(doc.get("versions", []), [])
                finally:
                    server.shutdown()
                    server.server_close()

    def test_role_permissions_and_business_actions(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        brigadier = self.login("brigadier@company.kg")
        status, data = self.request("POST", "/api/requests/REQ-1048/reply", {"text": "нет прав"}, brigadier)
        self.assertEqual(status, 403, data)

        engineer = self.login("engineer@company.kg")
        status, data = self.request("POST", "/api/requests/REQ-1048/reply", {"text": "Документы приложены."}, engineer)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["data"]["status"], "done")

        accountant = self.login("accountant@company.kg")
        status, data = self.request("POST", "/api/money/PAY-1/pay", {}, accountant)
        self.assertEqual(status, 400, data)
        status, data = self.request("POST", "/api/money/PAY-1/pay", {"paymentNo": "P-001"}, accountant)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["data"]["status"], "Оплачено")
        self.assertEqual(data["data"]["payment_no"], "P-001")
        self.assertEqual(data["data"]["paid_by"], "Кадырова Айжан")
        self.assertTrue(data["data"]["history"])

        lawyer = self.login("lawyer@company.kg")
        status, data = self.request("POST", "/api/money/PAY-2/pay", {"paymentNo": "P-002"}, lawyer)
        self.assertEqual(status, 403, data)
        status, data = self.request("POST", "/api/money/PAY-2/appeal", {"text": "Не согласны с основанием начисления."}, lawyer)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["data"]["status"], "Обжалуется")
        self.assertEqual(data["data"]["appealed_by"], "Сыдыкова Элина")

        status, data = self.request(
            "POST",
            "/api/requests",
            {"title": "Новое обращение", "text": "Просим назначить инспектора.", "object": 1},
            lawyer,
        )
        self.assertEqual(status, 201, data)
        self.assertEqual(data["data"]["status"], "review")

        status, state = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200)
        self.assertTrue(any(r["title"] == "Новое обращение" for r in state["data"]["requests"]))
        self.assertEqual(next(m for m in state["data"]["money"] if m["id"] == "PAY-1")["status"], "Оплачено")
        self.assertEqual(next(m for m in state["data"]["money"] if m["id"] == "PAY-2")["status"], "Обжалуется")
        self.assertGreaterEqual(len(state["data"]["audit"]), 5)

    def test_payment_gateway_command_confirms_or_rejects_payment_before_persisting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payment_dir = root / "gateway"
            gateway_script = root / "gateway.sh"
            gateway_script.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "mkdir -p \"$2\"\n"
                "cp \"$1\" \"$2/payment.json\"\n"
                "if grep -q REJECT \"$1\"; then\n"
                "  exit 1\n"
                "fi\n",
                encoding="utf-8",
            )
            gateway_script.chmod(0o755)
            env = {
                "QH_PAYMENT_GATEWAY_CMD": f"{gateway_script} {{payload}} {payment_dir}",
                "QH_PAYMENT_GATEWAY_URL": "https://payments.example.test",
            }
            with patch.dict(os.environ, env, clear=False):
                server = make_server(
                    "127.0.0.1",
                    0,
                    root / "payments.sqlite3",
                    upload_root=root / "uploads",
                    backup_root=root / "backups",
                    quiet=True,
                )
                host, port = server.server_address
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "accountant@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    accountant = data["token"]
                    status, data = raw_http_request(host, port, "POST", "/api/auth/login", {"email": "director@company.kg", "password": TEST_DEMO_PASSWORD})
                    self.assertEqual(status, 200, data)
                    director = data["token"]

                    status, paid = raw_http_request(
                        host,
                        port,
                        "POST",
                        "/api/money/PAY-1/pay",
                        {"paymentNo": "GATE-001", "receipt": "gateway-receipt.pdf"},
                        accountant,
                    )
                    self.assertEqual(status, 200, paid)
                    self.assertEqual(paid["data"]["status"], "Оплачено")
                    self.assertEqual(paid["data"]["payment_gateway_status"], "confirmed")
                    self.assertIn("payment_gateway_synced_at", paid["data"])
                    gateway_payload = json.loads((payment_dir / "payment.json").read_text(encoding="utf-8"))
                    self.assertEqual(gateway_payload["payment_no"], "GATE-001")
                    self.assertEqual(gateway_payload["amount"], 45000)

                    status, rejected = raw_http_request(
                        host,
                        port,
                        "POST",
                        "/api/money/PAY-2/pay",
                        {"paymentNo": "REJECT-002", "receipt": "gateway-reject.pdf"},
                        accountant,
                    )
                    self.assertEqual(status, 503, rejected)
                    status, state = raw_http_request(host, port, "GET", "/api/state", token=director)
                    self.assertEqual(status, 200, state)
                    pay2 = next(item for item in state["data"]["money"] if item["id"] == "PAY-2")
                    self.assertNotEqual(pay2["status"], "Оплачено")
                    self.assertNotIn("payment_gateway_synced_at", pay2)

                    status, readiness = raw_http_request(host, port, "GET", "/api/readiness", token=director)
                    self.assertEqual(status, 200, readiness)
                    checks = {item["id"]: item for item in readiness["data"]["checks"]}
                    self.assertEqual(checks["payments"]["status"], "pass")
                finally:
                    server.shutdown()
                    server.server_close()

    def test_legacy_paid_records_get_payment_metadata(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
            payload = json.loads(row[0])
            for item in payload["money"]:
                if item["id"] == "PAY-3":
                    item.pop("payment_no", None)
                    item.pop("paid_at", None)
                    item.pop("paid_by", None)
            conn.execute("UPDATE app_state SET payload = ?, updated_at = ? WHERE id = 1", (json.dumps(payload, ensure_ascii=False), "legacy"))

        status, state = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200, state)
        paid = next(m for m in state["data"]["money"] if m["id"] == "PAY-3")
        self.assertEqual(paid["payment_no"], "SEED-2026-003")
        self.assertEqual(paid["paid_by"], "Кадырова Айжан")

    def test_document_upload_and_inspection_prepare(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        engineer = self.login("engineer@company.kg")
        status, data = self.request("POST", "/api/documents/DOC-3/upload", {"file": "project-v2.pdf"}, engineer)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["data"]["status"], "На проверке")
        self.assertEqual(data["data"]["file"], "project-v2.pdf")

        status, data = self.request("POST", "/api/documents/DOC-3/upload", {"file": "payload.exe"}, engineer)
        self.assertEqual(status, 400, data)

        payload = b64encode(b"document body").decode("ascii")
        status, data = self.request(
            "POST",
            "/api/documents/DOC-4/upload",
            {"fileName": "payload.exe", "contentBase64": payload},
            engineer,
        )
        self.assertEqual(status, 400, data)

        status, data = self.request(
            "POST",
            "/api/documents/DOC-4/upload",
            {"fileName": "../unsafe акт.pdf", "contentBase64": payload},
            engineer,
        )
        self.assertEqual(status, 200, data)
        uploaded = data["data"]
        self.assertEqual(uploaded["file"], "unsafe акт.pdf")
        self.assertEqual(uploaded["file_url"], "/api/documents/DOC-4/file")
        self.assertEqual(uploaded["file_size"], len(b"document body"))
        self.assertTrue((self.upload_root / uploaded["stored_file"]).exists())
        self.assertEqual((self.upload_root / uploaded["stored_file"]).read_bytes(), b"document body")

        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request("GET", uploaded["file_url"])
        res = conn.getresponse()
        self.assertEqual(res.status, 401)
        res.read()
        conn.close()

        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request("GET", uploaded["file_url"], headers={"Authorization": f"Bearer {engineer}"})
        res = conn.getresponse()
        self.assertEqual(res.status, 200)
        self.assertEqual(res.read(), b"document body")
        conn.close()

        brigadier = self.login("brigadier@company.kg")
        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request("GET", uploaded["file_url"], headers={"Authorization": f"Bearer {brigadier}"})
        res = conn.getresponse()
        self.assertEqual(res.status, 403)
        res.read()
        conn.close()

        foreman = self.login("foreman@company.kg")
        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request("GET", uploaded["file_url"], headers={"Authorization": f"Bearer {foreman}"})
        res = conn.getresponse()
        self.assertEqual(res.status, 200)
        self.assertEqual(res.read(), b"document body")
        conn.close()

        status, data = self.request("POST", "/api/documents/DOC-4/upload", {"file": "foreman-upload.pdf"}, foreman)
        self.assertEqual(status, 403, data)

        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request("GET", f"/uploads/{quote(uploaded['stored_file'])}")
        res = conn.getresponse()
        self.assertNotEqual(res.status, 200)
        res.read()
        conn.close()

        status, data = self.request("POST", "/api/inspections/1/prepare", {}, foreman)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["data"]["status"], "Материалы отправлены")

    def test_objects_team_and_notifications(self) -> None:
        director = self.login("director@company.kg")
        self.request("POST", "/api/state/reset", {}, director)

        brigadier = self.login("brigadier@company.kg")
        status, data = self.request(
            "POST",
            "/api/objects",
            {"name": "Запрещённый объект", "address": "Бишкек", "stage": "Котлован"},
            brigadier,
        )
        self.assertEqual(status, 403, data)

        engineer = self.login("engineer@company.kg")
        status, data = self.request(
            "POST",
            "/api/objects",
            {"name": "Новый объект API", "address": "Бишкек", "stage": "Котлован"},
            engineer,
        )
        self.assertEqual(status, 201, data)
        self.assertEqual(data["data"]["name"], "Новый объект API")

        status, data = self.request(
            "POST",
            "/api/team",
            {"name": "Тестовый сотрудник", "role": "Бригадир"},
            engineer,
        )
        self.assertEqual(status, 403, data)

        status, data = self.request(
            "POST",
            "/api/team",
            {"name": "Тестовый сотрудник", "role": "Бригадир"},
            director,
        )
        self.assertEqual(status, 201, data)
        self.assertEqual(data["data"]["name"], "Тестовый сотрудник")

        status, data = self.request(
            "POST",
            "/api/team",
            {"name": "Логин сотрудник", "role": "Прораб", "email": "new.foreman@company.kg", "password": "Temp2026!"},
            director,
        )
        self.assertEqual(status, 201, data)
        self.assertEqual(data["data"]["email"], "new.foreman@company.kg")

        status, data = self.request("POST", "/api/auth/login", {"email": "new.foreman@company.kg", "password": "Temp2026!"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["user"]["role"], "foreman")

        status, data = self.request(
            "POST",
            "/api/team",
            {"name": "Дубликат", "role": "Прораб", "email": "new.foreman@company.kg", "password": "Temp2026!"},
            director,
        )
        self.assertEqual(status, 409, data)

        status, data = self.request("POST", "/api/notifications/0/read", {}, brigadier)
        self.assertEqual(status, 200, data)
        self.assertTrue(data["data"]["read"])

        status, data = self.request("POST", "/api/notifications/read-all", {}, brigadier)
        self.assertEqual(status, 200, data)
        self.assertTrue(all(item["read"] for item in data["data"]))

        status, state = self.request("GET", "/api/state", token=director)
        self.assertEqual(status, 200)
        self.assertTrue(any(obj["name"] == "Новый объект API" for obj in state["data"]["objects"]))
        self.assertTrue(any(user["name"] == "Тестовый сотрудник" for user in state["data"]["team"]))
        self.assertTrue(any(user.get("email") == "new.foreman@company.kg" for user in state["data"]["team"]))
        self.assertNotIn("Temp2026!", json.dumps(state["data"], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
