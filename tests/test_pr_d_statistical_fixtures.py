"""Synthetic-only reproducibility checks for candidate PR D reference values.

This suite does not import or invoke the lab engine, read the run manifest, or
connect to Supabase. Values remain candidates until human review.
"""
import json
import math
import platform
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
from scipy.stats import norm, t
import statsmodels
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "pr_d_statistical_reference.json"
REQUIREMENTS_PATH = ROOT / "requirements" / "pr-d-statistical-fixtures-py312.txt"


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def bh_adjust(p_values):
    """Benjamini-Hochberg adjusted q values, returned in original order."""
    p = np.asarray(p_values, dtype=np.float64)
    if p.ndim != 1 or p.size == 0:
        raise ValueError("p_values must be a non-empty one-dimensional array")
    if not np.all(np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("p_values must be finite and within [0, 1]")
    m = p.size
    order = np.argsort(p, kind="mergesort")
    sorted_p = p[order]
    ranks = np.arange(1, m + 1, dtype=np.float64)
    sorted_q = sorted_p * m / ranks
    sorted_q = np.minimum.accumulate(sorted_q[::-1])[::-1]
    sorted_q = np.clip(sorted_q, 0.0, 1.0)
    q = np.empty_like(sorted_q)
    q[order] = sorted_q
    return q


class TestPRDStatisticalReferenceFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_fixture()
        cls.rtol = cls.fixture["tolerance"]["rtol"]
        cls.atol = cls.fixture["tolerance"]["atol"]

    def assertClose(self, actual, expected):
        self.assertTrue(
            math.isclose(float(actual), float(expected), rel_tol=self.rtol, abs_tol=self.atol),
            msg=f"actual={actual!r}, expected={expected!r}, rtol={self.rtol}, atol={self.atol}",
        )

    def test_environment_and_fixture_are_explicitly_candidate(self):
        self.assertEqual(self.fixture["schema"], "pr-d-statistical-reference-fixtures/1")
        self.assertEqual(self.fixture["status"], "candidate")
        self.assertEqual(self.fixture["python"], "3.12.x")
        self.assertEqual(sys.version_info[:2], (3, 12), platform.python_version())
        self.assertEqual(np.__version__, "2.2.6")
        self.assertEqual(scipy.__version__, "1.15.3")
        self.assertEqual(statsmodels.__version__, "0.14.5")
        self.assertEqual(pd.__version__, "2.2.3")
        pins = REQUIREMENTS_PATH.read_text(encoding="utf-8")
        for pin in (
            "numpy==2.2.6", "scipy==1.15.3", "statsmodels==0.14.5",
            "pandas==2.2.3", "patsy==1.0.1", "packaging==24.2",
            "python-dateutil==2.9.0.post0", "pytz==2025.2",
            "six==1.17.0", "tzdata==2025.2",
        ):
            self.assertIn(pin, pins)

    def test_d07_logistic_mle(self):
        case = self.fixture["D07_logistic_mle"]
        x_values, y_values = [], []
        for row in case["rows"]:
            x_values.extend([row["x"]] * (row["successes"] + row["failures"]))
            y_values.extend([1] * row["successes"] + [0] * row["failures"])

        x = sm.add_constant(np.asarray(x_values, dtype=np.float64), has_constant="add")
        y = np.asarray(y_values, dtype=np.float64)
        result = sm.Logit(y, x).fit(disp=False, method="newton", maxiter=100)
        beta0, beta1 = result.params
        se = result.bse[1]
        z_stat = beta1 / se
        p_value = 2.0 * norm.sf(abs(z_stat))
        z_critical = case["z_critical_95"]
        ci_low = beta1 - z_critical * se
        ci_high = beta1 + z_critical * se
        expected = case["expected"]

        for actual, key in (
            (beta0, "intercept"), (beta1, "beta"), (se, "se"),
            (z_stat, "z"), (p_value, "p_two_sided"),
            (ci_low, "ci_low"), (ci_high, "ci_high"),
            (math.exp(beta1), "odds_ratio"),
            (math.exp(ci_low), "or_ci_low"), (math.exp(ci_high), "or_ci_high"),
        ):
            with self.subTest(field=key):
                self.assertClose(actual, expected[key])

    def test_d09_ols_hc3_t_inference(self):
        case = self.fixture["D09_ols_hc3"]
        x = np.asarray(case["x"], dtype=np.float64)
        ln_y = np.asarray(case["ln_y"], dtype=np.float64)
        self.assertEqual(len(x), len(ln_y))
        self.assertTrue(np.all(np.isfinite(ln_y)))
        design = sm.add_constant(x, has_constant="add")
        result = sm.OLS(ln_y, design).fit(cov_type="HC3", use_t=True)
        beta0, beta1 = result.params
        se = result.bse[1]
        t_stat = beta1 / se
        df_resid = int(result.df_resid)
        p_value = 2.0 * t.sf(abs(t_stat), df_resid)
        critical = t.ppf(0.975, df_resid)
        ci_low, ci_high = beta1 - critical * se, beta1 + critical * se
        expected = case["expected"]

        for actual, key in (
            (beta0, "intercept"), (beta1, "beta"), (se, "se_hc3"),
            (t_stat, "t"), (df_resid, "df_resid"),
            (p_value, "p_two_sided_t"), (ci_low, "ci_low"), (ci_high, "ci_high"),
        ):
            with self.subTest(field=key):
                self.assertClose(actual, expected[key])

    def test_d10_bh_adjustment_and_boundary(self):
        case = self.fixture["D10_benjamini_hochberg"]
        actual = bh_adjust(case["p_values"])
        np.testing.assert_allclose(
            actual, case["expected_q_values"],
            rtol=self.rtol, atol=self.atol,
        )
        self.assertTrue(np.all(np.diff(actual) >= -self.atol))
        self.assertLessEqual(float(actual[2]), case["alpha"])
        self.assertEqual([bool(q <= case["alpha"]) for q in actual],
                         [True, True, True, False, False])

    def test_bh_rejects_invalid_values(self):
        for values in ([], [float("nan")], [-0.01], [1.01], [float("inf")]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    bh_adjust(values)


if __name__ == "__main__":
    print(
        "Candidate fixture environment:",
        platform.python_version(),
        "numpy", np.__version__,
        "scipy", scipy.__version__,
        "statsmodels", statsmodels.__version__,
        "pandas", pd.__version__,
    )
    unittest.main(verbosity=2)
