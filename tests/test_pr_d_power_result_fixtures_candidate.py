"""Candidate-only shape tests for PR D T28 power-result consistency.

These tests validate the output contract only. They do not compute power,
choose a power method, import the lab engine, read production data, or connect
to Supabase.
"""
import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "pr_d_power_result_fixtures_candidate.json"
ALLOWED_UNITS = {"eligible_observations", "positive_events"}
ALLOWED_NULL_REASONS = {
    "method_not_preregistered",
    "missing_parameters",
    "assumptions_not_met",
    "unsupported_family_or_model",
    "invalid_effect_specification",
}


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def validate_power_result(result):
    """Validate T28 value/reason/unit shape; deliberately does not calculate power."""
    if not isinstance(result, dict) or set(result) != {"value", "reason", "unit"}:
        raise ValueError("result must contain exactly value, reason, and unit")

    value = result["value"]
    reason = result["reason"]
    unit = result["unit"]

    if value is None:
        if reason not in ALLOWED_NULL_REASONS:
            raise ValueError("null value requires one closed null reason")
        if unit is not None:
            raise ValueError("null value requires unit=null")
        return "VALID_NULL_SHAPE"

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("non-null value must be numeric and not boolean")
    if not math.isfinite(float(value)) or float(value) <= 0.0:
        raise ValueError("non-null value must be finite and positive")
    if reason is not None:
        raise ValueError("valid numeric value requires reason=null")
    if unit not in ALLOWED_UNITS:
        raise ValueError("valid numeric value requires a supported unit")
    return "VALID_SHAPE"


class TestPRDPowerResultFixturesCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_fixture()

    def test_fixture_is_candidate_only_and_does_not_authorize_power_calculation(self):
        self.assertEqual(self.fixture["schema"], "pr-d-power-result-fixtures-candidate/1")
        self.assertEqual(self.fixture["status"], "candidate")
        self.assertEqual(self.fixture["authority"], "illustrative_not_normative")
        self.assertFalse(self.fixture["safeguards"]["calculation_performed"])
        self.assertFalse(self.fixture["safeguards"]["power_method_preregistered"])
        self.assertFalse(self.fixture["safeguards"]["production_hypotheses"])
        self.assertFalse(self.fixture["safeguards"]["supabase_production_writes"])
        self.assertEqual(
            self.fixture["safeguards"]["manifest_execution_status_must_remain"], "fixture"
        )
        self.assertFalse(self.fixture["safeguards"]["e6_e11_approval"])

    def test_each_supported_unit_has_a_valid_illustrative_shape(self):
        cases = self.fixture["illustrative_valid_outputs"]
        self.assertEqual({case["result"]["unit"] for case in cases}, ALLOWED_UNITS)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(validate_power_result(case["result"]), case["expected"])

    def test_all_five_closed_null_reasons_have_consistent_shape(self):
        cases = self.fixture["illustrative_null_outputs"]
        self.assertEqual(
            {case["result"]["reason"] for case in cases}, ALLOWED_NULL_REASONS
        )
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(validate_power_result(case["result"]), case["expected"])
                self.assertIsNone(case["result"]["value"])
                self.assertIsNone(case["result"]["unit"])

    def test_rejects_inconsistent_value_reason_unit_combinations(self):
        invalid = [
            {"value": None, "reason": None, "unit": None},
            {"value": None, "reason": "missing_parameters", "unit": "eligible_observations"},
            {"value": 42.0, "reason": "missing_parameters", "unit": "eligible_observations"},
            {"value": 42.0, "reason": None, "unit": None},
            {"value": 42.0, "reason": None, "unit": "observations"},
            {"value": 0.0, "reason": None, "unit": "eligible_observations"},
            {"value": -1.0, "reason": None, "unit": "eligible_observations"},
            {"value": float("nan"), "reason": None, "unit": "eligible_observations"},
            {"value": float("inf"), "reason": None, "unit": "eligible_observations"},
            {"value": True, "reason": None, "unit": "eligible_observations"},
            {"value": 42.0, "reason": None, "unit": "eligible_observations", "extra": 1},
        ]
        for result in invalid:
            with self.subTest(result=result):
                with self.assertRaises(ValueError):
                    validate_power_result(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
