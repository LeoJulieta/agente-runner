"""Candidate acceptance fixtures for PR D D08, D11 and D12.

Synthetic contract-design checks only. This module does not invoke the lab
engine or connect to Supabase. D12 remains blocked where preregistration is
missing; no scientific threshold is inferred here.
"""
import json
import math
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EDGE_PATH = ROOT / "tests" / "fixtures" / "pr_d_statistical_edge_fixtures_candidate.json"
MANIFEST_PATH = ROOT / "docs" / "manifest.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def bh_adjust(p_values):
    p = np.asarray(p_values, dtype=np.float64)
    if p.ndim != 1 or p.size == 0:
        raise ValueError("p_values must be a non-empty one-dimensional array")
    if not np.all(np.isfinite(p)) or np.any((p < 0.0) | (p > 1.0)):
        raise ValueError("p_values must be finite and in [0, 1]")
    m = p.size
    order = np.argsort(p, kind="mergesort")
    sorted_p = p[order]
    ranks = np.arange(1, m + 1, dtype=np.float64)
    sorted_q = np.minimum.accumulate((sorted_p * m / ranks)[::-1])[::-1]
    adjusted = np.empty_like(sorted_q)
    adjusted[order] = np.clip(sorted_q, 0.0, 1.0)
    return adjusted


def classify_fit_outcome(input_class):
    """Candidate boundary classifier; not wired to the production engine."""
    if input_class == "recognized_model_non_estimability":
        return {"classification": "SCIENTIFIC_NON_ESTIMABLE", "p_for_fdr": 1.0, "abort_batch": False}
    if input_class == "unexpected_software_or_infrastructure_exception":
        return {"classification": "STRUCTURAL_FAILURE", "p_for_fdr": None, "abort_batch": True}
    raise ValueError("unrecognized fit outcome class")


class TestPRDStatisticalEdgeFixturesCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edge = read_json(EDGE_PATH)

    def test_fixture_is_candidate_and_safe(self):
        self.assertEqual(self.edge["status"], "candidate")
        self.assertFalse(self.edge["safeguards"]["production_hypotheses"])
        self.assertFalse(self.edge["safeguards"]["supabase_production_writes"])
        self.assertEqual(self.edge["safeguards"]["manifest_execution_status_must_remain"], "fixture")
        self.assertTrue(self.edge["safeguards"]["contract_v2_unchanged"])
        self.assertFalse(self.edge["safeguards"]["e6_e11_approval"])

    def test_d08_scientific_non_estimability_does_not_become_structural_failure(self):
        cases = self.edge["D08_non_estimability"]["cases"]
        self.assertEqual(len(cases), 4)
        for case in cases:
            with self.subTest(case=case["id"]):
                actual = classify_fit_outcome(case["input_class"])
                self.assertEqual(actual["classification"], case["expected_classification"])
                self.assertEqual(actual["p_for_fdr"], case["expected_p_for_fdr"])
                self.assertEqual(actual["abort_batch"], case["abort_batch"])
        scientific = [c for c in cases if c["expected_classification"] == "SCIENTIFIC_NON_ESTIMABLE"]
        structural = [c for c in cases if c["expected_classification"] == "STRUCTURAL_FAILURE"]
        self.assertEqual(len(scientific), 3)
        self.assertEqual(len(structural), 1)
        self.assertTrue(all(c["expected_p_for_fdr"] == 1.0 for c in scientific))
        self.assertIsNone(structural[0]["expected_p_for_fdr"])
        self.assertTrue(structural[0]["abort_batch"])

    def test_d11_non_estimable_member_stays_in_frozen_bh_m(self):
        case = self.edge["D11_non_estimable_member_in_fdr_family"]
        members = case["members"]
        p_values = [member["p_for_adjustment"] for member in members]
        self.assertEqual(len(members), case["m"])
        self.assertEqual(len(set(m["hypothesis_id"] for m in members)), case["m"])
        self.assertEqual(sum(m["source"] == "non_estimable_conservative_convention" for m in members), 1)
        self.assertEqual(p_values[1], 1.0)
        q_values = bh_adjust(p_values)
        np.testing.assert_allclose(q_values, case["expected_q_in_original_order"], rtol=1e-8, atol=1e-10)
        self.assertEqual(len(q_values), case["expected_member_count_after_adjustment"])
        self.assertTrue(case["expected_non_estimable_member_retained"])
        self.assertTrue(np.all(np.isfinite(q_values)))
        self.assertTrue(np.all((q_values >= 0.0) & (q_values <= 1.0)))

    def test_d12_stays_blocked_when_preregistration_is_missing(self):
        case = self.edge["D12_preregistered_gates"]
        manifest = read_json(MANIFEST_PATH)
        self.assertEqual(case["status"], "BLOCKED")
        self.assertFalse(case["evaluation_authorized"])
        self.assertEqual(case["expected_behavior"]["result"], "BLOCKED_PREREGISTRATION_INCOMPLETE")
        self.assertTrue(case["expected_behavior"]["do_not_infer_thresholds"])
        self.assertEqual(manifest.get("execution_status"), "fixture")

        required = set(case["required_fields"])
        # This test-only manifest deliberately lacks hypothesis-level gate
        # parameters; do not synthesize defaults from the observed outcomes.
        manifest_fields = set(manifest.keys())
        for family in manifest["families"]:
            manifest_fields.update(family.keys())
        missing = required - manifest_fields
        self.assertIn("minimum_relevant_effect", missing)
        self.assertIn("expected_direction", missing)
        self.assertIn("confidence_interval_method_and_level", missing)
        self.assertIn("method_fingerprint", missing)
        self.assertTrue(math.isfinite(float(manifest["families"][0]["m"])))

    def test_fdr_helper_rejects_nonfinite_and_out_of_range_p_values(self):
        for values in ([], [float("nan")], [float("inf")], [-0.1], [1.1]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    bh_adjust(values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
