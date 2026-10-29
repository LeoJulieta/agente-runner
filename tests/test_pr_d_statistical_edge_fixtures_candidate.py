"""Candidate acceptance fixtures for PR D D08, D11 and D12.

Synthetic contract-design checks only. This module does not invoke the lab
engine or connect to Supabase. D12 evaluates only a separate, explicitly
non-normative synthetic preregistration; the official manifest remains fixture.
"""
import json
import math
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EDGE_PATH = ROOT / "tests" / "fixtures" / "pr_d_statistical_edge_fixtures_candidate.json"
MANIFEST_PATH = ROOT / "docs" / "manifest.json"
D12_MANIFEST_PATH = ROOT / "tests" / "fixtures" / "manifest_d12_test.json"


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
    """Candidate contract mapping; not wired to the production engine."""
    scientific_reasons = {
        "logistic_separation",
        "model_non_convergence",
        "model_not_estimable",
    }
    if input_class in scientific_reasons:
        return {
            "classification": "SCIENTIFIC_NON_ESTIMABLE",
            "contract_status": "INSUFFICIENT_POWER",
            "non_estimability_reason": input_class,
            "p_for_fdr": 1.0,
            "abort_batch": False,
        }
    if input_class == "unexpected_software_or_infrastructure_exception":
        return {
            "classification": "STRUCTURAL_FAILURE",
            "contract_status": None,
            "non_estimability_reason": None,
            "p_for_fdr": None,
            "abort_batch": True,
        }
    raise ValueError("unrecognized fit outcome class")


def evaluate_d12(preregistration, observed):
    """Evaluate illustrative gates only; never called by the lab engine."""
    hypothesis = preregistration["hypothesis"]
    ci = hypothesis["confidence_interval"]
    required = {"odds_ratio", "ci_low", "ci_high", "p_value", "q_value", "n_eff", "n_events_per_window"}
    missing = required - set(observed)
    if missing:
        raise ValueError(f"observed fields missing: {sorted(missing)}")
    if hypothesis["expected_direction"] not in {"greater", "less"}:
        raise ValueError("expected_direction must be 'greater' or 'less'")
    if ci["gate_rule"] != "lower_bound > 1.0":
        raise ValueError("unsupported confidence-interval gate rule")
    numeric = {key: float(observed[key]) for key in required}
    if not all(math.isfinite(value) for value in numeric.values()):
        raise ValueError("observed numeric fields must be finite")
    if numeric["odds_ratio"] <= 0 or numeric["ci_low"] <= 0 or numeric["ci_high"] <= 0:
        raise ValueError("odds ratio and interval limits must be positive")
    if numeric["ci_low"] > numeric["ci_high"]:
        raise ValueError("confidence interval limits are reversed")
    if not 0 <= numeric["p_value"] <= 1 or not 0 <= numeric["q_value"] <= 1:
        raise ValueError("p_value and q_value must be in [0, 1]")
    if numeric["n_eff"] < 0 or numeric["n_events_per_window"] < 0:
        raise ValueError("sample and event counts must be non-negative")
    if not math.isfinite(float(hypothesis["minimum_relevant_effect"])) or hypothesis["minimum_relevant_effect"] <= 0:
        raise ValueError("minimum_relevant_effect must be finite and positive")
    if not 0 <= float(hypothesis["fdr_alpha"]) <= 1:
        raise ValueError("fdr_alpha must be in [0, 1]")

    checks = {
        "effect": numeric["odds_ratio"] >= hypothesis["minimum_relevant_effect"],
        "direction": (
            numeric["odds_ratio"] > 1.0
            if hypothesis["expected_direction"] == "greater"
            else numeric["odds_ratio"] < 1.0
        ),
        "interval": numeric["ci_low"] > 1.0,
        "fdr": numeric["q_value"] <= hypothesis["fdr_alpha"],
        "operational_minima": (
            numeric["n_eff"] >= hypothesis["operational_minima"]["n_eff"]
            and numeric["n_events_per_window"] >= hypothesis["operational_minima"]["n_events_per_window"]
        ),
    }
    return {"checks": checks, "gate": "PROMETE" if all(checks.values()) else "RECHAZA"}


class TestPRDStatisticalEdgeFixturesCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edge = read_json(EDGE_PATH)
        cls.d12 = read_json(D12_MANIFEST_PATH)

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
                self.assertEqual(actual["contract_status"], case["expected_contract_status"])
                self.assertEqual(actual["non_estimability_reason"], case["expected_reason"])
        scientific = [c for c in cases if c["expected_classification"] == "SCIENTIFIC_NON_ESTIMABLE"]
        structural = [c for c in cases if c["expected_classification"] == "STRUCTURAL_FAILURE"]
        self.assertEqual(len(scientific), 3)
        self.assertEqual(len(structural), 1)
        self.assertTrue(all(c["expected_p_for_fdr"] == 1.0 for c in scientific))
        self.assertTrue(all(c["expected_contract_status"] == "INSUFFICIENT_POWER" for c in scientific))
        self.assertEqual(
            {c["expected_reason"] for c in scientific},
            {"logistic_separation", "model_non_convergence", "model_not_estimable"},
        )
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

    def test_d12_stays_blocked_when_official_preregistration_is_missing(self):
        case = self.edge["D12_preregistered_gates"]
        official_manifest = read_json(MANIFEST_PATH)
        self.assertEqual(case["status"], "BLOCKED")
        self.assertFalse(case["evaluation_authorized"])
        self.assertEqual(case["expected_behavior"]["result"], "BLOCKED_PREREGISTRATION_INCOMPLETE")
        self.assertTrue(case["expected_behavior"]["do_not_infer_thresholds"])
        self.assertEqual(official_manifest.get("execution_status"), "fixture")

        required = set(case["required_fields"])
        manifest_fields = set(official_manifest.keys())
        for family in official_manifest["families"]:
            manifest_fields.update(family.keys())
        missing = required - manifest_fields
        self.assertIn("minimum_relevant_effect", missing)
        self.assertIn("expected_direction", missing)
        self.assertIn("confidence_interval_method_and_level", missing)
        self.assertIn("method_fingerprint", missing)
        self.assertTrue(math.isfinite(float(official_manifest["families"][0]["m"])))

    def test_d12_synthetic_preregistration_is_explicit_and_non_normative(self):
        prereg = self.d12
        self.assertEqual(prereg["status"], "candidate")
        self.assertEqual(prereg["authority"], "illustrative_not_normative")
        self.assertFalse(prereg["execution_authorized"])
        self.assertTrue(prereg["preregistered_before_synthetic_outcomes"])
        self.assertFalse(prereg["safeguards"]["official_manifest_modified"])
        self.assertEqual(prereg["safeguards"]["official_manifest_execution_status_must_remain"], "fixture")
        hypothesis = prereg["hypothesis"]
        self.assertEqual(hypothesis["effect_estimand"], "odds_ratio")
        self.assertEqual(hypothesis["minimum_relevant_effect"], 1.5)
        self.assertEqual(hypothesis["expected_direction"], "greater")
        self.assertEqual(hypothesis["confidence_interval"]["level"], 0.95)
        self.assertEqual(hypothesis["confidence_interval"]["gate_rule"], "lower_bound > 1.0")
        self.assertFalse(hypothesis["method_fingerprint_is_real_hash"])
        self.assertEqual(len(hypothesis["family_membership"]), hypothesis["m"])

    def test_d12_positive_case_passes_all_preregistered_synthetic_gates(self):
        case = next(c for c in self.d12["synthetic_cases"] if c["case_id"] == "D12-POSITIVE-OR-2")
        actual = evaluate_d12(self.d12, case["observed"])
        self.assertEqual(actual["gate"], case["expected_gate"])
        self.assertEqual(actual["gate"], "PROMETE")
        self.assertEqual(actual["checks"], case["expected_checks"])
        self.assertTrue(all(actual["checks"].values()))

    def test_d12_negative_case_rejects_without_changing_thresholds(self):
        case = next(c for c in self.d12["synthetic_cases"] if c["case_id"] == "D12-NEGATIVE-OR-1-2")
        actual = evaluate_d12(self.d12, case["observed"])
        self.assertEqual(actual["gate"], case["expected_gate"])
        self.assertEqual(actual["gate"], "RECHAZA")
        self.assertEqual(actual["checks"], case["expected_checks"])
        self.assertFalse(actual["checks"]["effect"])
        self.assertFalse(actual["checks"]["interval"])
        self.assertFalse(actual["checks"]["fdr"])
        self.assertEqual(self.d12["hypothesis"]["minimum_relevant_effect"], 1.5)
        self.assertEqual(self.d12["hypothesis"]["expected_direction"], "greater")

    def test_bh_ties_are_stable_and_return_to_original_order(self):
        first_order = bh_adjust([0.01, 0.01, 0.04, 1.0])
        shuffled_order = bh_adjust([0.04, 0.01, 1.0, 0.01])
        expected_first = np.array([0.02, 0.02, 0.05333333333333334, 1.0])
        expected_shuffled = np.array([0.05333333333333334, 0.02, 1.0, 0.02])
        np.testing.assert_allclose(first_order, expected_first, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(shuffled_order, expected_shuffled, rtol=1e-12, atol=1e-12)
        self.assertEqual(first_order[0], first_order[1])
        self.assertEqual(shuffled_order[1], shuffled_order[3])

    def test_d12_strict_interval_boundary_and_inclusive_fdr_boundary(self):
        case = next(c for c in self.d12["synthetic_cases"] if c["case_id"] == "D12-POSITIVE-OR-2")
        observed = dict(case["observed"])
        observed.update({
            "odds_ratio": 1.5,
            "ci_low": 1.0,
            "ci_high": 2.0,
            "q_value": 0.05,
            "n_eff": 30,
            "n_events_per_window": 5,
        })
        actual = evaluate_d12(self.d12, observed)
        self.assertEqual(actual["checks"], {
            "effect": True,
            "direction": True,
            "interval": False,
            "fdr": True,
            "operational_minima": True,
        })
        self.assertEqual(actual["gate"], "RECHAZA")

    def test_d12_rejects_invalid_observed_schema_and_direction(self):
        case = next(c for c in self.d12["synthetic_cases"] if c["case_id"] == "D12-POSITIVE-OR-2")
        observed = dict(case["observed"])
        missing = dict(observed)
        del missing["odds_ratio"]
        with self.assertRaises(ValueError):
            evaluate_d12(self.d12, missing)
        nonfinite = dict(observed)
        nonfinite["q_value"] = float("nan")
        with self.assertRaises(ValueError):
            evaluate_d12(self.d12, nonfinite)
        reversed_ci = dict(observed)
        reversed_ci["ci_low"], reversed_ci["ci_high"] = 2.6, 2.5
        with self.assertRaises(ValueError):
            evaluate_d12(self.d12, reversed_ci)
        invalid_p = dict(observed)
        invalid_p["p_value"] = 1.1
        with self.assertRaises(ValueError):
            evaluate_d12(self.d12, invalid_p)
        bad_direction = json.loads(json.dumps(self.d12))
        bad_direction["hypothesis"]["expected_direction"] = "sideways"
        with self.assertRaises(ValueError):
            evaluate_d12(bad_direction, observed)

    def test_fdr_helper_rejects_nonfinite_and_out_of_range_p_values(self):
        for values in ([], [float("nan")], [float("inf")], [-0.1], [1.1]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    bh_adjust(values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
