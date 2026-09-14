from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ops.render_deployment_files import render_deployment_files, validate_domain


class RenderDeploymentFilesTest(unittest.TestCase):
    def test_render_deployment_files_replaces_domain_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = render_deployment_files(
                domain="cabinet.builder.kg",
                output_dir=root / "out",
                app_root=Path("/opt/qurulush-hub"),
                runtime_root=Path("/var/lib/qurulush-hub"),
                env_file=Path("/etc/qurulush-hub/company-platform.env"),
                admin_email="owner@builder.kg",
            )
            service = Path(result["files"]["systemd"]).read_text(encoding="utf-8")
            nginx = Path(result["files"]["nginx"]).read_text(encoding="utf-8")
            go_no_go = Path(result["files"]["go_no_go"]).read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn("cabinet.builder.kg", nginx)
        self.assertIn("/etc/letsencrypt/live/cabinet.builder.kg/fullchain.pem", service)
        self.assertIn("--hook-contract-smoke", go_no_go)
        self.assertNotIn("company.example", service + nginx + go_no_go)

    def test_validate_domain_rejects_placeholder(self) -> None:
        with self.assertRaisesRegex(ValueError, "real DNS"):
            validate_domain("company.example")


if __name__ == "__main__":
    unittest.main()
