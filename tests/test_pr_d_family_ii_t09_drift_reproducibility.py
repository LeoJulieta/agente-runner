"""Deterministic synthetic acceptance tests for PR D T09/T10, T15-T26."""
import unittest

import numpy as np

from labs.pr_d_family_ii import (
    METHOD_FINGERPRINT_OLS_HC3,
    compute_d_cond,
    compute_d_init,
    evaluate_drift,
    evaluate_reproducibility,
    fit_ols_log_positive_hc3,
)


class PRDFamilyIITest(unittest.TestCase):
    def test_t09_ols_ln_positive_y_uses_hc3_and_t_interval(self):
        x = np.tile(np.arange(12, dtype=float), 4)
        residual = np.tile(np.array([-0.12, 0.04, 0.09, -0.03, 0.15, -0.08,
                                     0.02, -0.05, 0.11, -0.10, 0.06, -0.01]), 4)
        y_positive = np.exp(1.1 + 0.22 * x + residual)
        y = np.concatenate(([0.0, 0.0], y_positive))
        design = np.column_stack([np.ones(y.size), np.concatenate(([0.0, 1.0], x))])
        result = fit_ols_log_positive_hc3(y, design, coefficient_index=1)
        self.assertEqual(result["status"], "ESTIMABLE")
        m = result["metrics"]
        self.assertEqual(m["method_fingerprint"], METHOD_FINGERPRINT_OLS_HC3)
        self.assertEqual(m["covariance_type"], "HC3")
        self.assertEqual(m["contrast"], "two_sided_t")
        self.assertEqual(m["n_total"], 50)
        self.assertEqual(m["n_events"], 48)
        self.assertEqual(m["n_eff"], 50)
        for key in ("effect_size", "se", "p_empirical", "ci_low", "ci_high"):
            self.assertTrue(np.isfinite(m[key]), key)
        self.assertGreater(m["se"], 0)
        self.assertGreaterEqual(m["p_empirical"], 0)
        self.assertLessEqual(m["p_empirical"], 1)
        self.assertLess(m["ci_low"], m["ci_high"])
        self.assertAlmostEqual(result["bh_input_p"], m["p_empirical"], places=15)

    def test_t09_zeros_count_in_total_but_are_excluded_from_ln_model(self):
        y = np.array([0, 0, *np.exp(np.linspace(0.1, 1.5, 40))], dtype=float)
        x = np.arange(y.size, dtype=float)
        design = np.column_stack([np.ones(y.size), x])
        result = fit_ols_log_positive_hc3(y, design, coefficient_index=1)
        self.assertEqual(result["metrics"]["n_total"], 42)
        self.assertEqual(result["metrics"]["n_events"], 40)
        self.assertEqual(result["metrics"]["n_eff"], 42)

    def test_t09_below_minimum_is_insufficient_not_a_fake_estimate(self):
        y = np.exp(np.linspace(0.1, 1.0, 10))
        design = np.column_stack([np.ones(10), np.arange(10, dtype=float)])
        result = fit_ols_log_positive_hc3(y, design, coefficient_index=1, min_n_eff=30)
        self.assertEqual(result["status"], "INSUFFICIENT_POWER")
        self.assertIsNone(result["metrics"]["p_empirical"])
        self.assertIsNone(result["metrics"]["effect_size"])
        self.assertEqual(result["bh_input_p"], 1.0)


    def test_t09_n_eff_and_n_events_have_independent_minimums(self):
        y = np.array([1, 2, 3, 4] + [0] * 26, dtype=float)
        design = np.column_stack([np.ones(y.size), np.arange(y.size, dtype=float)])
        result = fit_ols_log_positive_hc3(y, design, coefficient_index=1)
        self.assertEqual(result["status"], "INSUFFICIENT_POWER")
        self.assertEqual(result["metrics"]["n_eff"], 30)
        self.assertEqual(result["metrics"]["n_events"], 4)
        self.assertEqual(result["metrics"]["insufficient_power_reason"], "n_events_below_minimum")
        self.assertIsNone(result["metrics"]["p_empirical"])
        self.assertEqual(result["bh_input_p"], 1.0)

    def test_t09_negative_or_nonfinite_outcomes_are_rejected(self):
        design = np.column_stack([np.ones(3), np.arange(3, dtype=float)])
        with self.assertRaisesRegex(ValueError, "ols_outcome_negative"):
            fit_ols_log_positive_hc3([-1, 1, 2], design, coefficient_index=1)
        with self.assertRaisesRegex(ValueError, "ols_input_nonfinite_or_empty"):
            fit_ols_log_positive_hc3([1, np.nan, 2], design, coefficient_index=1)

    def test_t10_diagnostic_presence_cannot_switch_hc3_method(self):
        x = np.tile(np.arange(12, dtype=float), 4)
        residual = np.tile(np.array([-0.12, 0.04, 0.09, -0.03, 0.15, -0.08,
                                     0.02, -0.05, 0.11, -0.10, 0.06, -0.01]), 4)
        y = np.exp(1.1 + 0.22 * x + residual)
        design = np.column_stack([np.ones(y.size), x])
        first = fit_ols_log_positive_hc3(y, design, coefficient_index=1)
        # A descriptive diagnostic is deliberately kept outside the inferential API.
        _diagnostic_placeholder = {"breusch_pagan": {"statistic": 0.0, "p_value": 1.0}}
        second = fit_ols_log_positive_hc3(y, design, coefficient_index=1)
        self.assertEqual(first, second)
        self.assertEqual(second["metrics"]["covariance_type"], "HC3")

    def test_t15_t16_d_init_is_absolute_difference_and_exact_threshold_does_not_alert(self):
        init = compute_d_init(10, 100, 20, 100)
        self.assertAlmostEqual(init["d_init"], 0.10, places=14)
        result = evaluate_drift(init, {"D_cond": 0.5, "drift_degeneracy": None})
        self.assertEqual(result["drift_flag"], "OK")
        self.assertEqual(result["drift_evaluation_state"], "complete")
        self.assertTrue(np.isfinite(result["d_init"]))

    def test_t15_neighbor_above_threshold_alerts(self):
        init = compute_d_init(10, 100, 21, 100)
        result = evaluate_drift(init, {"D_cond": 0.2, "drift_degeneracy": None})
        self.assertEqual(result["drift_flag"], "REGIME_SHIFT_SUSPECTED")

    def test_t16_missing_counts_return_null_not_zero(self):
        result = compute_d_init(None, 100, 20, 100)
        self.assertIsNone(result["d_init"])
        self.assertEqual(result["d_init_reason"], "insufficient_data")

    def test_t16_invalid_counts_are_not_absorbed_as_partial(self):
        with self.assertRaisesRegex(ValueError, "d_init_positive_count_out_of_range"):
            compute_d_init(101, 100, 20, 100)

    def test_t17_d_cond_uses_only_positive_outcomes(self):
        a = np.array([0, 0, 1, 2, 3, 4, 5, 6], dtype=float)
        b = np.array([0, 1, 2, 3, 4, 5, 6, 7], dtype=float)
        result = compute_d_cond(a, b)
        self.assertEqual(result["n_events_a"], 6)
        self.assertEqual(result["n_events_b"], 7)
        self.assertTrue(np.isfinite(result["D_cond"]))
        self.assertIsNone(result["drift_degeneracy"])

    def test_t18_d_cond_threshold_is_strict_at_point_five(self):
        result = evaluate_drift(
            {"d_init": 0.1, "d_init_reason": None},
            {"D_cond": 0.5, "drift_degeneracy": None},
        )
        self.assertEqual(result["drift_flag"], "OK")
        above = evaluate_drift(
            {"d_init": 0.1, "d_init_reason": None},
            {"D_cond": 0.5000001, "drift_degeneracy": None},
        )
        self.assertEqual(above["drift_flag"], "REGIME_SHIFT_SUSPECTED")

    def test_t19_fewer_than_five_positive_events_yields_null(self):
        result = compute_d_cond([0, 1, 2, 3, 4], [1, 2, 3, 4, 5, 6])
        self.assertIsNone(result["D_cond"])
        self.assertEqual(result["drift_degeneracy"], "insufficient_positive_events")

    def test_t20_zero_scale_equal_medians_is_zero_without_epsilon(self):
        result = compute_d_cond([1] * 5, [1] * 6)
        self.assertEqual(result["D_cond"], 0.0)
        self.assertEqual(result["drift_degeneracy"], "scale_zero_medians_equal")
        drift = evaluate_drift(
            {"d_init": 0.0, "d_init_reason": None}, result
        )
        self.assertEqual(drift["drift_flag"], "OK")

    def test_t21_zero_scale_different_medians_is_null_and_alert(self):
        result = compute_d_cond([1] * 5, [2] * 6)
        self.assertIsNone(result["D_cond"])
        self.assertEqual(result["drift_degeneracy"], "scale_zero_medians_differ")
        drift = evaluate_drift({"d_init": 0.0, "d_init_reason": None}, result)
        self.assertEqual(drift["drift_flag"], "REGIME_SHIFT_SUSPECTED")
        self.assertEqual(drift["drift_evaluation_state"], "partial")

    def test_t22_drift_table_partial_when_one_indicator_missing(self):
        result = evaluate_drift(
            {"d_init": 0.0, "d_init_reason": None},
            {"D_cond": None, "drift_degeneracy": "insufficient_positive_events"},
        )
        self.assertEqual(result["drift_flag"], "OK")
        self.assertEqual(result["drift_evaluation_state"], "partial")
        no_data = evaluate_drift(
            {"d_init": None, "d_init_reason": "insufficient_data"},
            {"D_cond": None, "drift_degeneracy": "insufficient_positive_events"},
        )
        self.assertIsNone(no_data["drift_flag"])
        self.assertEqual(no_data["drift_evaluation_state"], "not_evaluable")

    def test_t22_invalid_null_reason_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "D_cond_null_reason_invalid"):
            evaluate_drift(
                {"d_init": 0.0, "d_init_reason": None},
                {"D_cond": None, "drift_degeneracy": "unknown"},
            )

    def test_t24_absent_or_incomplete_antecedent_means_promete_not_reject(self):
        base = dict(
            b_status="PROMETE", b_hypothesis_id="H990_SYNTH", b_contract_sha256="abc",
            b_method_fingerprint="method-v1", b_effect_size=0.2, b_ci_low=0.05,
            b_ci_high=0.35, antecedent_a=None, windows_disjoint=True,
            direction_consistent=True, drift_flag="OK", drift_evaluation_state="complete",
            b_gates_pass=True,
        )
        missing = evaluate_reproducibility(**base)
        self.assertEqual(missing["status"], "PROMETE")
        self.assertFalse(missing["reproducible"])
        self.assertEqual(missing["metrics"]["reproducible_state"], "not_evaluable")

        incomplete = dict(base)
        incomplete["antecedent_a"] = {
            "hypothesis_id": "H990_SYNTH", "contract_sha256": "abc",
            "method_fingerprint": "method-v1", "window": "A", "status": "PROMETE",
            "effect_size": 0.2, "ci_low": None, "ci_high": 0.4,
        }
        result = evaluate_reproducibility(**incomplete)
        self.assertEqual(result["status"], "PROMETE")
        self.assertEqual(result["metrics"]["reproducibility_reason"], "antecedent_incomplete")

    def test_t25_t26_only_complete_compatible_case_is_verified(self):
        antecedent = {
            "hypothesis_id": "H990_SYNTH", "contract_sha256": "abc",
            "method_fingerprint": "method-v1", "window": "A", "status": "PROMETE",
            "effect_size": 0.2, "ci_low": 0.05, "ci_high": 0.35,
        }
        args = dict(
            b_status="PROMETE", b_hypothesis_id="H990_SYNTH", b_contract_sha256="abc",
            b_method_fingerprint="method-v1", b_effect_size=0.25, b_ci_low=0.1,
            b_ci_high=0.4, antecedent_a=antecedent, windows_disjoint=True,
            direction_consistent=True, drift_flag="OK", drift_evaluation_state="complete",
            b_gates_pass=True,
        )
        result = evaluate_reproducibility(**args)
        self.assertEqual(result["status"], "VERIFICADO")
        self.assertTrue(result["reproducible"])
        self.assertEqual(result["metrics"]["reproducible_state"], "reproducible")

    def test_t25_incompatible_comparison_is_rechaza_not_reproducible(self):
        antecedent = {
            "hypothesis_id": "H990_SYNTH", "contract_sha256": "abc",
            "method_fingerprint": "method-v1", "window": "A", "status": "PROMETE",
            "effect_size": 0.2, "ci_low": 0.05, "ci_high": 0.35,
        }
        result = evaluate_reproducibility(
            b_status="PROMETE", b_hypothesis_id="H990_SYNTH", b_contract_sha256="abc",
            b_method_fingerprint="method-v1", b_effect_size=0.8, b_ci_low=0.7,
            b_ci_high=0.9, antecedent_a=antecedent, windows_disjoint=True,
            direction_consistent=True, drift_flag="OK", drift_evaluation_state="complete",
            b_gates_pass=True,
        )
        self.assertEqual(result["status"], "RECHAZA")
        self.assertEqual(result["metrics"]["reproducible_state"], "not_reproducible")

    def test_t25_partial_drift_cannot_verify_reproducibility(self):
        antecedent = {
            "hypothesis_id": "H990_SYNTH", "contract_sha256": "abc",
            "method_fingerprint": "method-v1", "window": "A", "status": "PROMETE",
            "effect_size": 0.2, "ci_low": 0.05, "ci_high": 0.35,
        }
        result = evaluate_reproducibility(
            b_status="PROMETE", b_hypothesis_id="H990_SYNTH", b_contract_sha256="abc",
            b_method_fingerprint="method-v1", b_effect_size=0.25, b_ci_low=0.1,
            b_ci_high=0.4, antecedent_a=antecedent, windows_disjoint=True,
            direction_consistent=True, drift_flag="OK", drift_evaluation_state="partial",
            b_gates_pass=True,
        )
        self.assertEqual(result["status"], "PROMETE")
        self.assertFalse(result["reproducible"])
        self.assertEqual(result["metrics"]["reproducible_state"], "not_evaluable")

    def test_t26_rejected_b_state_cannot_be_upgraded_to_verified(self):
        result = evaluate_reproducibility(
            b_status="RECHAZA", b_hypothesis_id="H990_SYNTH", b_contract_sha256="abc",
            b_method_fingerprint="method-v1", b_effect_size=0.2, b_ci_low=0.05,
            b_ci_high=0.35, antecedent_a=None, windows_disjoint=True,
            direction_consistent=True, drift_flag="OK", drift_evaluation_state="complete",
            b_gates_pass=True,
        )
        self.assertEqual(result["status"], "RECHAZA")
        self.assertFalse(result["reproducible"])

    def test_t26_precedence_invalid_and_insufficient_power_is_preserved(self):
        for status in ("INVALID", "INSUFFICIENT_POWER"):
            result = evaluate_reproducibility(
                b_status=status, b_hypothesis_id="H990_SYNTH", b_contract_sha256="abc",
                b_method_fingerprint="method-v1", b_effect_size=None, b_ci_low=None,
                b_ci_high=None, antecedent_a=None, windows_disjoint=False,
                direction_consistent=False, drift_flag=None, drift_evaluation_state="not_evaluable",
                b_gates_pass=False,
            )
            self.assertEqual(result["status"], status)
            self.assertFalse(result["reproducible"])
            self.assertEqual(result["metrics"]["reproducible_state"], "not_evaluable")


    def test_t09_candidate_count_is_separate_from_eligible_rows_and_events(self):
        # 36 candidate rows: 4 are excluded by the preregistered filter.
        x = np.arange(36, dtype=float)
        y = np.exp(0.1 + 0.03 * x)
        y[[2, 7, 19, 31]] = 0.0  # eligible zeros remain in n_eff, not n_events
        eligible = np.ones(36, dtype=bool)
        eligible[[0, 1, 2, 3]] = False
        design = np.column_stack([np.ones(36), x])
        result = fit_ols_log_positive_hc3(
            y, design, coefficient_index=1, eligible_mask=eligible
        )
        metrics = result["metrics"]
        self.assertEqual(result["status"], "ESTIMABLE")
        self.assertEqual(metrics["n_total"], 36)
        self.assertEqual(metrics["n_eff"], 32)
        self.assertEqual(metrics["n_events"], 28)

    def test_t09_eligible_zeros_count_toward_minimum_but_excluded_rows_do_not(self):
        x = np.arange(34, dtype=float)
        y = np.exp(0.2 + 0.02 * x)
        y[:3] = 0.0
        eligible = np.ones(34, dtype=bool)
        eligible[-4:] = False
        design = np.column_stack([np.ones(34), x])
        result = fit_ols_log_positive_hc3(
            y, design, coefficient_index=1, eligible_mask=eligible
        )
        self.assertEqual(result["status"], "ESTIMABLE")
        self.assertEqual(result["metrics"]["n_total"], 34)
        self.assertEqual(result["metrics"]["n_eff"], 30)
        self.assertEqual(result["metrics"]["n_events"], 27)

    def test_t09_mask_shape_and_type_are_validated(self):
        y = np.exp(np.linspace(0.1, 1.0, 32))
        design = np.column_stack([np.ones(32), np.arange(32, dtype=float)])
        with self.assertRaisesRegex(ValueError, "ols_eligibility_mask_invalid"):
            fit_ols_log_positive_hc3(
                y, design, coefficient_index=1, eligible_mask=[True] * 31
            )
        with self.assertRaisesRegex(ValueError, "ols_eligibility_mask_invalid"):
            fit_ols_log_positive_hc3(
                y, design, coefficient_index=1, eligible_mask=[1] * 32
            )

    def test_t09_numeric_hc3_matches_independent_statsmodels_reference(self):
        x = np.tile(np.arange(12, dtype=float), 4)
        residual = np.tile(np.array([-0.12, 0.04, 0.09, -0.03, 0.15, -0.08,
                                     0.02, -0.05, 0.11, -0.10, 0.06, -0.01]), 4)
        y_positive = np.exp(1.1 + 0.22 * x + residual)
        y = np.concatenate(([0.0, 0.0], y_positive))
        design_all = np.column_stack([np.ones(y.size), np.concatenate(([0.0, 1.0], x))])
        keep = y > 0
        # Independent reference path: call statsmodels directly, without the wrapper.
        reference = __import__("statsmodels.api", fromlist=["OLS"]).OLS(
            np.log(y[keep]), design_all[keep]
        ).fit(cov_type="HC3", use_t=True)
        actual = fit_ols_log_positive_hc3(y, design_all, coefficient_index=1)["metrics"]
        self.assertAlmostEqual(actual["effect_size"], float(reference.params[1]), delta=1e-10)
        self.assertAlmostEqual(actual["se"], float(reference.bse[1]), delta=1e-10)
        self.assertAlmostEqual(actual["p_empirical"], float(reference.pvalues[1]), delta=1e-10)
        ci = reference.conf_int(alpha=0.05)[1]
        self.assertAlmostEqual(actual["ci_low"], float(ci[0]), delta=1e-10)
        self.assertAlmostEqual(actual["ci_high"], float(ci[1]), delta=1e-10)

    def test_t09_zero_is_excluded_but_negative_is_invalid_in_family_ii(self):
        design = np.column_stack([np.ones(42), np.arange(42, dtype=float)])
        y = np.array([0.0, 0.0, *np.exp(np.linspace(0.1, 1.5, 40))])
        result = fit_ols_log_positive_hc3(y, design, coefficient_index=1)
        self.assertEqual(result["status"], "ESTIMABLE")
        self.assertEqual(result["metrics"]["n_total"], 42)
        self.assertEqual(result["metrics"]["n_events"], 40)
        self.assertEqual(result["metrics"]["n_eff"], 42)
        y_with_negative = y.copy()
        y_with_negative[0] = -0.01
        with self.assertRaisesRegex(ValueError, "ols_outcome_negative"):
            fit_ols_log_positive_hc3(y_with_negative, design, coefficient_index=1)
        with self.assertRaisesRegex(ValueError, "d_cond_outcome_negative"):
            compute_d_cond([-1, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 6])

    def test_t24_antecedent_identity_mismatch_is_not_localizable(self):
        base_a = {
            "hypothesis_id": "H990_SYNTH", "contract_sha256": "abc",
            "method_fingerprint": "method-v1", "window": "A", "status": "PROMETE",
            "effect_size": 0.2, "ci_low": 0.05, "ci_high": 0.35,
        }
        base_b = dict(
            b_status="PROMETE", b_hypothesis_id="H990_SYNTH", b_contract_sha256="abc",
            b_method_fingerprint="method-v1", b_effect_size=0.25, b_ci_low=0.1,
            b_ci_high=0.4, windows_disjoint=True, direction_consistent=True,
            drift_flag="OK", drift_evaluation_state="complete", b_gates_pass=True,
        )
        mismatches = (
            ("hypothesis_id", "OTHER"),
            ("contract_sha256", "different-contract"),
            ("method_fingerprint", "different-method"),
            ("window", "B"),
            ("status", "RECHAZA"),
        )
        for field, wrong_value in mismatches:
            with self.subTest(field=field):
                antecedent = dict(base_a)
                antecedent[field] = wrong_value
                result = evaluate_reproducibility(**base_b, antecedent_a=antecedent)
                self.assertEqual(result["status"], "PROMETE")
                self.assertFalse(result["reproducible"])
                self.assertEqual(result["metrics"]["reproducibility_reason"], "antecedent_not_localizable")

    def test_t25_drift_alert_rejects_reproducibility_with_compatible_antecedent(self):
        antecedent = {
            "hypothesis_id": "H990_SYNTH", "contract_sha256": "abc",
            "method_fingerprint": "method-v1", "window": "A", "status": "PROMETE",
            "effect_size": 0.2, "ci_low": 0.05, "ci_high": 0.35,
        }
        result = evaluate_reproducibility(
            b_status="PROMETE", b_hypothesis_id="H990_SYNTH", b_contract_sha256="abc",
            b_method_fingerprint="method-v1", b_effect_size=0.25, b_ci_low=0.1,
            b_ci_high=0.4, antecedent_a=antecedent, windows_disjoint=True,
            direction_consistent=True, drift_flag="REGIME_SHIFT_SUSPECTED",
            drift_evaluation_state="complete", b_gates_pass=True,
        )
        self.assertEqual(result["status"], "RECHAZA")
        self.assertFalse(result["reproducible"])
        self.assertEqual(result["metrics"]["reproducibility_reason"], "drift_detected")
        self.assertEqual(result["metrics"]["reproducible_state"], "not_reproducible")

    def test_t26_drift_rejection_is_not_replaced_by_promete_when_antecedent_missing(self):
        result = evaluate_reproducibility(
            b_status="RECHAZA", b_hypothesis_id="H990_SYNTH", b_contract_sha256="abc",
            b_method_fingerprint="method-v1", b_effect_size=0.25, b_ci_low=0.1,
            b_ci_high=0.4, antecedent_a=None, windows_disjoint=True,
            direction_consistent=True, drift_flag="REGIME_SHIFT_SUSPECTED",
            drift_evaluation_state="complete", b_gates_pass=True,
        )
        self.assertEqual(result["status"], "RECHAZA")
        self.assertFalse(result["reproducible"])
        self.assertEqual(result["metrics"]["reproducibility_reason"], "b_precedence_status")


if __name__ == "__main__":
    unittest.main()
