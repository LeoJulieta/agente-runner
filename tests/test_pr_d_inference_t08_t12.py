"""Synthetic, deterministic acceptance tests for PR D T08/T12 only."""
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from labs.pr_d_inference import (
    NON_ESTIMABILITY_REASONS,
    StructuralBatchAbort,
    adjust_bh_family,
    evaluate_family_atomically,
    fit_logistic_mle,
)


class PRDInferenceT08T12Tests(unittest.TestCase):
    def test_logistic_perfect_separation_is_scientific_non_estimability(self):
        # 40 deterministic observations, full-rank design, perfectly separated.
        x = np.arange(40, dtype=float)
        y = (x >= 20).astype(int)
        design = np.column_stack([np.ones(40), x])
        result = fit_logistic_mle(y, design, coefficient_index=1, min_n_eff=30)
        self.assertEqual(result["status"], "INSUFFICIENT_POWER")
        self.assertEqual(result["metrics"]["non_estimability_reason"], "logistic_separation")
        self.assertIsNone(result["metrics"]["p_empirical"])
        self.assertEqual(result["bh_input_p"], 1.0)
        self.assertIn(result["metrics"]["non_estimability_reason"], NON_ESTIMABILITY_REASONS)

    def test_rank_deficient_design_is_not_estimable(self):
        x = np.arange(40, dtype=float)
        design = np.column_stack([np.ones(40), x, x])
        y = ((x % 3) == 0).astype(int)
        result = fit_logistic_mle(y, design, coefficient_index=1, min_n_eff=30)
        self.assertEqual(result["status"], "INSUFFICIENT_POWER")
        self.assertEqual(result["metrics"]["non_estimability_reason"], "model_not_estimable")
        self.assertIsNone(result["metrics"]["p_empirical"])
        self.assertEqual(result["bh_input_p"], 1.0)

    def test_nonconvergence_is_distinguished_from_separation(self):
        x = np.tile(np.arange(10, dtype=float), 4)
        y = np.array(([0, 0, 0, 1, 0, 1, 1, 0, 1, 1] * 4), dtype=int)
        design = np.column_stack([np.ones(len(x)), x])

        def synthetic_nonconvergence(*args, **kwargs):
            warnings.warn("synthetic nonconvergence", ConvergenceWarning)
            return SimpleNamespace(mle_retvals={"converged": False})

        with patch("labs.pr_d_inference.sm.Logit.fit", side_effect=synthetic_nonconvergence):
            result = fit_logistic_mle(y, design, coefficient_index=1, min_n_eff=30)
        self.assertEqual(result["status"], "INSUFFICIENT_POWER")
        self.assertEqual(result["metrics"]["non_estimability_reason"], "model_non_convergence")
        self.assertIsNone(result["metrics"]["p_empirical"])
        self.assertEqual(result["bh_input_p"], 1.0)

    def test_insufficient_n_is_not_mislabeled_as_nonestimability(self):
        x = np.arange(20, dtype=float)
        y = (x % 2).astype(int)
        design = np.column_stack([np.ones(20), x])
        with self.assertRaisesRegex(ValueError, "n_eff_below_minimum"):
            fit_logistic_mle(y, design, coefficient_index=1, min_n_eff=30)

    def test_estimable_logistic_returns_wald_metrics(self):
        # Fixed synthetic pattern avoids separation; no random generator or real observations.
        x = np.tile(np.arange(10, dtype=float), 4)
        y = np.array(([0, 0, 0, 1, 0, 1, 1, 0, 1, 1] * 4), dtype=int)
        design = np.column_stack([np.ones(len(x)), x])
        result = fit_logistic_mle(y, design, coefficient_index=1, min_n_eff=30)
        self.assertEqual(result["status"], "ESTIMABLE")
        metrics = result["metrics"]
        for key in ("effect_size", "se", "p_empirical", "ci_low", "ci_high", "odds_ratio"):
            self.assertTrue(np.isfinite(metrics[key]), key)
        self.assertGreaterEqual(metrics["p_empirical"], 0.0)
        self.assertLessEqual(metrics["p_empirical"], 1.0)
        self.assertLess(metrics["ci_low"], metrics["ci_high"])
        self.assertLess(metrics["coefficient_ci_low"], metrics["coefficient_ci_high"])
        self.assertAlmostEqual(metrics["ci_low"], metrics["coefficient_ci_low"], places=15)
        self.assertAlmostEqual(metrics["ci_high"], metrics["coefficient_ci_high"], places=15)
        self.assertLess(metrics["odds_ratio_ci_low"], metrics["odds_ratio_ci_high"])
        self.assertAlmostEqual(metrics["odds_ratio"], np.exp(metrics["effect_size"]), places=12)
        self.assertAlmostEqual(result["bh_input_p"], metrics["p_empirical"], places=15)

    def test_bh_preserves_family_m_and_uses_one_only_as_adjustment_input(self):
        family = [
            {"hypothesis_id": "H990_A", "status": "ESTIMABLE", "p_empirical": 0.01},
            {
                "hypothesis_id": "H991_B",
                "status": "INSUFFICIENT_POWER",
                "p_empirical": None,
                "non_estimability_reason": "logistic_separation",
            },
            {"hypothesis_id": "H992_C", "status": "ESTIMABLE", "p_empirical": 0.04},
        ]
        adjusted = adjust_bh_family(family)
        self.assertEqual(len(adjusted), 3)
        self.assertEqual({row["hypothesis_id"] for row in adjusted}, {"H990_A", "H991_B", "H992_C"})
        nonestimable = next(row for row in adjusted if row["hypothesis_id"] == "H991_B")
        self.assertIsNone(nonestimable["p_empirical"])
        self.assertEqual(nonestimable["bh_input_p"], 1.0)
        self.assertTrue(all(0.0 <= row["fdr_q"] <= 1.0 for row in adjusted))

    def test_bh_accepts_nested_contract_metrics_without_fabricating_empirical_p(self):
        row = fit_logistic_mle(
            (np.arange(40) >= 20).astype(int),
            np.column_stack([np.ones(40), np.arange(40, dtype=float)]),
            coefficient_index=1,
        )
        row["hypothesis_id"] = "H990_SEPARATED"
        adjusted = adjust_bh_family([row])
        self.assertIsNone(adjusted[0]["metrics"]["p_empirical"])
        self.assertEqual(adjusted[0]["metrics"]["bh_input_p"], 1.0)
        self.assertEqual(adjusted[0]["metrics"]["family_m"], 1)
        self.assertEqual(adjusted[0]["family_m"], 1)

    def test_unknown_or_missing_p_does_not_silently_leave_fdr_family(self):
        family = [
            {"hypothesis_id": "H990_A", "status": "ESTIMABLE", "p_empirical": 0.01},
            {"hypothesis_id": "H991_B", "status": "INSUFFICIENT_POWER", "p_empirical": None},
        ]
        with self.assertRaisesRegex(ValueError, "non_estimability_reason_required"):
            adjust_bh_family(family)


    def test_invalid_hypothesis_keeps_its_fdr_slot_with_adjustment_only_p_one(self):
        family = [
            {"hypothesis_id": "H990_A", "status": "ESTIMABLE", "p_empirical": 0.01},
            {
                "hypothesis_id": "H991_MISSING",
                "status": "INVALID",
                "p_empirical": None,
                "invalid_reason": "hypothesis_spec_missing",
            },
            {"hypothesis_id": "H992_C", "status": "ESTIMABLE", "p_empirical": 0.04},
        ]
        adjusted = adjust_bh_family(family)
        invalid = next(row for row in adjusted if row["hypothesis_id"] == "H991_MISSING")
        self.assertEqual(len(adjusted), 3)
        self.assertEqual(invalid["bh_input_p"], 1.0)
        self.assertIsNone(invalid["p_empirical"])
        self.assertEqual(invalid["family_m"], 3)
        self.assertEqual(invalid["fdr_q"], 1.0)

    def test_invalid_hypothesis_requires_closed_reason_and_null_empirical_p(self):
        invalid_reason = {
            "hypothesis_id": "H991_BAD",
            "status": "INVALID",
            "p_empirical": None,
            "invalid_reason": "unknown_reason",
        }
        with self.assertRaisesRegex(ValueError, "invalid_fdr_reason_required_or_unsupported"):
            adjust_bh_family([invalid_reason])
        fabricated_p = {
            "hypothesis_id": "H992_BAD",
            "status": "INVALID",
            "p_empirical": 0.5,
            "invalid_reason": "hypothesis_spec_missing",
        }
        with self.assertRaisesRegex(ValueError, "invalid_empirical_p_must_be_null"):
            adjust_bh_family([fabricated_p])

    def test_structural_exception_aborts_without_returning_partial_family(self):
        def evaluate(item):
            if item == "broken":
                raise RuntimeError("synthetic unexpected backend failure")
            return {"hypothesis_id": item, "status": "ESTIMABLE", "p_empirical": 0.2}

        with self.assertRaises(StructuralBatchAbort) as caught:
            evaluate_family_atomically(["first", "broken", "third"], evaluate)
        self.assertEqual(caught.exception.failure_code, "UNEXPECTED_ERROR")
        self.assertEqual(caught.exception.failure_phase, "analysis")
        self.assertEqual(caught.exception.completed, False)

    def test_only_closed_scientific_nonestimability_causes_are_allowed(self):
        self.assertEqual(
            NON_ESTIMABILITY_REASONS,
            frozenset({"logistic_separation", "model_non_convergence", "model_not_estimable"}),
        )


if __name__ == "__main__":
    unittest.main()
