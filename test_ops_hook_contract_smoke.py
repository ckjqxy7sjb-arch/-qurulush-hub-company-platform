from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from ops.hook_contract_smoke import run_hook_contract_smoke


ROOT = Path(__file__).resolve().parent


class HookContractSmokeTest(unittest.TestCase):
    def test_runs_example_hooks_and_validates_json_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage_dir = root / "storage"
            backup_dir = root / "backup"
            env_path = root / "hooks.env"
            env_path.write_text(
                "\n".join(
                    [
                        f"QH_SACC2_SYNC_CMD=python3 {ROOT}/ops/hook_examples/sacc2_sync_contract_example.py {{payload}} {root}/sacc2",
                        f"QH_EDS_SIGN_CMD=python3 {ROOT}/ops/hook_examples/eds_sign_contract_example.py {{payload}} {root}/eds",
                        f"QH_PAYMENT_GATEWAY_CMD=python3 {ROOT}/ops/hook_examples/payment_confirm_contract_example.py {{payload}} {root}/payments",
                        f"QH_STORAGE_SYNC_CMD=python3 {ROOT}/ops/hook_examples/storage_sync_contract_example.py {{file}} {storage_dir}/{{doc_id}}",
                        f"QH_AV_SCANNER=python3 {ROOT}/ops/hook_examples/av_scan_contract_example.py {{file}}",
                        f"QH_BACKUP_REMOTE_CMD=python3 {ROOT}/ops/hook_examples/backup_remote_contract_example.py {{backup}} {{manifest}} {backup_dir}",
                        "QH_SACC2_API_URL=https://sacc2.avn.kg/api",
                        "QH_EDS_PROVIDER=kg-eds-provider-prod",
                        "QH_EDS_API_URL=https://eds.gov.kg/sign",
                        "QH_PAYMENT_GATEWAY_URL=https://payments.bank.kg/api",
                        "QH_STORAGE_URL=file://storage",
                        "QH_BACKUP_REMOTE_URL=file://backup",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = run_hook_contract_smoke(env_path)
        self.assertTrue(result["ok"], result)
        self.assertEqual({item["id"] for item in result["checks"]}, {"sacc2", "eds", "payment_gateway", "storage", "av_scanner", "backup_remote"})

    def test_fails_when_hook_output_is_not_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_hook = root / "bad-hook.sh"
            bad_hook.write_text("#!/bin/sh\necho not-json\n", encoding="utf-8")
            bad_hook.chmod(0o755)
            env_path = root / "hooks.env"
            env_path.write_text(f"QH_SACC2_SYNC_CMD={bad_hook} {{payload}}\n", encoding="utf-8")
            result = run_hook_contract_smoke(env_path, {"sacc2"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_checks"], ["sacc2"])


if __name__ == "__main__":
    unittest.main()
