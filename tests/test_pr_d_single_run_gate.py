import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from labs.pr_d_single_run_gate import validate_single_run


def manifest(status="fixture"):
    return {
        "execution_status": status,
        "families": [{"hypothesis_ids": ["H990_PRD_TEST_INIT"]}],
    }


class SingleRunGateTests(unittest.TestCase):
    def test_fixture_manifest_is_blocked(self):
        with self.assertRaisesRegex(PermissionError, "manifest_not_approved"):
            validate_single_run(manifest("fixture"), "H990_PRD_TEST_INIT")

    def test_approved_manifest_allows_only_frozen_hypothesis(self):
        validate_single_run(manifest("approved"), "H990_PRD_TEST_INIT")
        with self.assertRaisesRegex(PermissionError, "hypothesis_not_in_frozen_manifest"):
            validate_single_run(manifest("approved"), "H001")

    def test_invalid_hypothesis_id_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "hypothesis_id_invalid"):
            validate_single_run(manifest("approved"), "H001; echo unsafe")

    def test_engine_direct_invocation_blocks_fixture_before_credentials_or_supabase(self):
        import os
        env = {key: value for key, value in os.environ.items() if key not in {"SUPABASE_URL", "SUPABASE_KEY"}}
        result = subprocess.run(
            [sys.executable, "labs/lab_engine.py", "--hypothesis", "H990_PRD_TEST_INIT"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertIn("execution_manifest_blocked", result.stdout)
        self.assertNotIn("SUPABASE_URL", result.stderr + result.stdout)
        self.assertNotIn("SUPABASE_KEY", result.stderr + result.stdout)

    def test_cli_blocks_checked_in_fixture_before_engine_can_run(self):
        result = subprocess.run(
            [
                sys.executable,
                "labs/pr_d_single_run_gate.py",
                "--manifest",
                "docs/manifest.json",
                "--hypothesis-id",
                "H990_PRD_TEST_INIT",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        # The CLI must fail closed for either the fixture status or a stale contract hash.
        # On a candidate contract branch, hash validation can correctly fail before
        # the approval-status check; neither reason may permit execution.
        self.assertTrue(
            "manifest_not_approved" in result.stderr
            or "manifest_contract_hash_mismatch" in result.stderr,
            result.stderr,
        )
        self.assertNotIn("VALID", result.stdout)


if __name__ == "__main__":
    unittest.main()
