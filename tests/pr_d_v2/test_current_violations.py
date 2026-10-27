"""Characterization tests for PR D v2 blockers.

These tests PASS when the current implementation exhibits documented risks.
They inspect source only; they do not connect to Supabase or execute hypotheses.
Run: python -m unittest discover -s tests/pr_d_v2 -v
"""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[2]

class WorkflowExitCodeCharacterization(unittest.TestCase):
    def test_batch_workflow_absorbs_engine_failure(self):
        s = (ROOT / ".github/workflows/lab_batch.yml").read_text(encoding="utf-8")
        self.assertIn('python labs/lab_engine.py "${ARGS[@]}" || echo "FALLÓ $id"', s)

    def test_engine_has_no_explicit_structural_exit_code_2(self):
        s = (ROOT / "labs/lab_engine.py").read_text(encoding="utf-8")
        self.assertIn("sys.exit(1)", s)
        self.assertNotIn("sys.exit(2)", s)

class PersistenceAtomicityCharacterization(unittest.TestCase):
    def test_baseline_and_evidence_use_separate_insert_calls(self):
        s = (ROOT / "labs/lab_engine.py").read_text(encoding="utf-8")
        self.assertIn("persist_baseline(contract, supabase, baseline_value, baseline_type)", s)
        baseline_start = s.index("def persist_baseline(")
        measure_start = s.index("def measure(", baseline_start)
        self.assertIn(".insert({", s[baseline_start:measure_start])
        self.assertIn('insert_response = supabase.table("lab_results").insert({', s)
        self.assertNotIn("persist_baseline_and_evidence", s)

class AuthorizationCharacterization(unittest.TestCase):
    def test_h003_and_h005_remain_unauthorized(self):
        for h in ("H003", "H005"):
            with self.subTest(hypothesis=h):
                s = (ROOT / "labs/hypotheses" / (h + ".yaml")).read_text(encoding="utf-8")
                self.assertRegex(s, r"(?m)^authorized:\s*false\s*$")

    def test_batch_workflow_does_not_verify_a_frozen_manifest(self):
        s = (ROOT / ".github/workflows/lab_batch.yml").read_text(encoding="utf-8")
        self.assertNotIn("verify_manifest", s)

if __name__ == "__main__":
    unittest.main()
