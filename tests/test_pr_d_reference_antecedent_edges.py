"""Contract-focused synthetic reference and antecedent edge tests for PR D."""
import unittest

import numpy as np
import statsmodels.api as sm

from labs.pr_d_family_ii import (
    METHOD_FINGERPRINT_OLS_HC3,
    evaluate_reproducibility,
    fit_ols_log_positive_hc3,
)


class PRDReferenceAndAntecedentEdgeTests(unittest.TestCase):
    @staticmethod
    def fixture():
        x = np.tile(np.arange(12, dtype=np.float64), 4)
        residual = np.tile(np.array([
            -0.12, 0.04, 0.09, -0.03, 0.15, -0.08,
            0.02, -0.05, 0.11, -0.10, 0.06, -0.01,
        ], dtype=np.float64), 4)
        y = np.exp(1.1 + 0.22 * x + residual)
        design = np.column_stack((np.ones(y.size), x))
        return y, design

    def test_t27_fixed_numeric_hc3_reference_from_raw_synthetic_fixture(self):
        y, design = self.fixture()
        # Versioned expected values are calculated from raw deterministic inputs.
        # Tolerance is explicit; the independent fit below is diagnostic, not oracle.
        expected = {
            "effect_size": 0.2209090909090909,
            "se": 0.0035347143650444604,
            "ci_low": 0.21379407992025562,
            "ci_high": 0.22802410189792616,
        }
        actual = fit_ols_log_positive_hc3(y, design, coefficient_index=1)["metrics"]
        for key, value in expected.items():
            self.assertAlmostEqual(actual[key], value, delta=1e-10, msg=key)
        self.assertEqual(actual["covariance_type"], "HC3")
        self.assertEqual(actual["contrast"], "two_sided_t")
        # Cross-check against the direct statsmodels path as a second guard.
        direct = sm.OLS(np.log(y), design).fit(cov_type="HC3", use_t=True)
        self.assertAlmostEqual(actual["effect_size"], float(direct.params[1]), delta=1e-10)
        self.assertAlmostEqual(actual["se"], float(direct.bse[1]), delta=1e-10)
        ci = direct.conf_int(alpha=0.05)[1]
        self.assertAlmostEqual(actual["ci_low"], float(ci[0]), delta=1e-10)
        self.assertAlmostEqual(actual["ci_high"], float(ci[1]), delta=1e-10)

    def base_args(self, antecedent):
        return dict(
            b_status="PROMETE",
            b_hypothesis_id="H990_SYNTH",
            b_contract_sha256="synthetic-contract-sha",
            b_method_fingerprint=METHOD_FINGERPRINT_OLS_HC3,
            b_effect_size=0.25,
            b_ci_low=0.10,
            b_ci_high=0.40,
            antecedent_a=antecedent,
            windows_disjoint=True,
            direction_consistent=True,
            drift_flag="OK",
            drift_evaluation_state="complete",
            b_gates_pass=True,
        )

    def complete_antecedent(self):
        return {
            "hypothesis_id": "H990_SYNTH",
            "contract_sha256": "synthetic-contract-sha",
            "method_fingerprint": METHOD_FINGERPRINT_OLS_HC3,
            "window": "A",
            "status": "PROMETE",
            "effect_size": 0.20,
            "ci_low": 0.05,
            "ci_high": 0.35,
        }

    def test_t24_each_inferential_field_missing_or_nonfinite_is_incomplete(self):
        required = ("effect_size", "ci_low", "ci_high")
        for field in required:
            for bad_value in (None, float("nan"), float("inf")):
                with self.subTest(field=field, bad_value=bad_value):
                    antecedent = self.complete_antecedent()
                    antecedent[field] = bad_value
                    result = evaluate_reproducibility(**self.base_args(antecedent))
                    self.assertEqual(result["status"], "PROMETE")
                    self.assertFalse(result["reproducible"])
                    self.assertEqual(result["metrics"]["reproducible_state"], "not_evaluable")
                    self.assertEqual(result["metrics"]["reproducibility_reason"], "antecedent_incomplete")

    def test_t24_nonfinite_or_boolean_interval_is_not_localizable_as_complete(self):
        for bad_value in (float("nan"), float("inf"), True):
            with self.subTest(bad_value=bad_value):
                args = self.base_args(self.complete_antecedent())
                args["b_ci_high"] = bad_value
                result = evaluate_reproducibility(**args)
                self.assertEqual(result["status"], "PROMETE")
                self.assertEqual(result["metrics"]["reproducibility_reason"], "b_inference_incomplete")

    def test_t25_identity_mismatch_and_drift_gate_remain_non_verified(self):
        for field, value in (
            ("hypothesis_id", "H_OTHER"),
            ("contract_sha256", "other-contract"),
            ("method_fingerprint", "other-method"),
            ("window", "B"),
            ("status", "RECHAZA"),
        ):
            with self.subTest(field=field):
                antecedent = self.complete_antecedent()
                antecedent[field] = value
                result = evaluate_reproducibility(**self.base_args(antecedent))
                self.assertEqual(result["status"], "PROMETE")
                self.assertFalse(result["reproducible"])
                self.assertNotEqual(result["status"], "VERIFICADO")

    def test_t26_precedence_is_preserved_even_with_complete_antecedent(self):
        for status in ("INVALID", "INSUFFICIENT_POWER", "RECHAZA"):
            args = self.base_args(self.complete_antecedent())
            args["b_status"] = status
            result = evaluate_reproducibility(**args)
            self.assertEqual(result["status"], status)
            self.assertFalse(result["reproducible"])
            self.assertEqual(
                result["metrics"]["reproducible_state"],
                "not_evaluable" if status in ("INVALID", "INSUFFICIENT_POWER") else "not_reproducible",
            )


if __name__ == "__main__":
    unittest.main()
