"""Contract-focused deterministic HC3 reference and precedence tests for PR D."""
import numpy as np
import pytest
import statsmodels.api as sm

from labs.pr_d_family_ii import (
    METHOD_FINGERPRINT_OLS_HC3,
    evaluate_reproducibility,
    fit_ols_log_positive_hc3,
)


# Exact synthetic X and Y values; no generated outcomes or rounded intermediates.
X_VALUES = np.tile(np.arange(12, dtype=np.float64), 4)
Y_VALUES = np.tile(np.array([
    2.6644562419294173, 3.896193301795215, 5.103874718536726,
    5.640653908428322, 8.41486681144013, 8.331137487687693,
    11.473040742794833, 13.329771603195779, 19.49191959603112,
    19.6878166447624, 28.789190879242685, 33.44826778394492,
], dtype=np.float64), 4)
DESIGN = np.column_stack((np.ones(X_VALUES.size, dtype=np.float64), X_VALUES))


def _complete_antecedent():
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


def _base_args(antecedent=None, **overrides):
    args = dict(
        b_status="PROMETE",
        b_hypothesis_id="H990_SYNTH",
        b_contract_sha256="synthetic-contract-sha",
        b_method_fingerprint=METHOD_FINGERPRINT_OLS_HC3,
        b_effect_size=0.25,
        b_ci_low=0.10,
        b_ci_high=0.40,
        antecedent_a=_complete_antecedent() if antecedent is None else antecedent,
        windows_disjoint=True,
        direction_consistent=True,
        drift_flag="OK",
        drift_evaluation_state="complete",
        b_gates_pass=True,
    )
    args.update(overrides)
    return args


def test_t27_hc3_reference_includes_intermediates_and_bitwise_determinism():
    design = DESIGN.copy()
    y = Y_VALUES.copy()

    def run_once():
        actual = fit_ols_log_positive_hc3(y, design, coefficient_index=1)["metrics"]
        direct = sm.OLS(np.log(y), design).fit(cov_type="HC3", use_t=True)
        return actual, direct

    actual_1, direct_1 = run_once()
    actual_2, direct_2 = run_once()

    expected = {
        "effect_size": 0.2209090909090909,
        "se": 0.0035347143650444604,
        "ci_low": 0.21379407992025562,
        "ci_high": 0.22802410189792616,
    }
    for key, value in expected.items():
        assert actual_1[key] == pytest.approx(value, abs=1e-10)
        assert actual_2[key] == actual_1[key]
    assert actual_1["covariance_type"] == "HC3"
    assert actual_1["contrast"] == "two_sided_t"

    # Intermediate covariance and residuals are checked against a versioned oracle.
    expected_covariance = np.array([
        [6.5538384388115424e-04, -7.9884417822394246e-05],
        [-7.9884417822394246e-05, 1.2494205642451663e-05],
    ], dtype=np.float64)
    expected_residual_prefix = np.array([
        -0.12166666666666781,
        0.03742424242424125,
        0.08651515151515032,
        -0.03439393939394031,
    ], dtype=np.float64)
    np.testing.assert_allclose(direct_1.cov_params(), expected_covariance, rtol=0, atol=1e-10)
    np.testing.assert_allclose(direct_1.resid[:4], expected_residual_prefix, rtol=0, atol=1e-10)
    np.testing.assert_allclose(direct_2.cov_params(), direct_1.cov_params(), rtol=0, atol=0)
    np.testing.assert_allclose(direct_2.resid, direct_1.resid, rtol=0, atol=0)
    assert actual_2 == actual_1
    assert direct_2.params.tobytes() == direct_1.params.tobytes()
    assert direct_2.cov_params().tobytes() == direct_1.cov_params().tobytes()
    assert direct_2.resid.tobytes() == direct_1.resid.tobytes()


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        (field, bad_value)
        for field in ("effect_size", "ci_low", "ci_high")
        for bad_value in (None, float("nan"), float("inf"))
    ],
)
def test_t24_missing_or_nonfinite_antecedent_inference_is_not_evaluable(field, bad_value):
    antecedent = _complete_antecedent()
    antecedent[field] = bad_value
    result = evaluate_reproducibility(**_base_args(antecedent))
    assert result["status"] == "PROMETE"
    assert result["reproducible"] is False
    assert result["metrics"]["reproducible_state"] == "not_evaluable"
    assert result["metrics"]["reproducibility_reason"] == "antecedent_incomplete"


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), True, None])
def test_t24_nonfinite_or_missing_b_inference_cannot_be_promoted(bad_value):
    result = evaluate_reproducibility(**_base_args(b_ci_high=bad_value))
    assert result["status"] == "PROMETE"
    assert result["reproducible"] is False
    assert result["metrics"]["reproducibility_reason"] == "b_inference_incomplete"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hypothesis_id", "H_OTHER"),
        ("contract_sha256", "other-contract"),
        ("method_fingerprint", "other-method"),
        ("window", "B"),
        ("status", "RECHAZA"),
    ],
)
def test_t25_identity_mismatch_never_verifies(field, value):
    antecedent = _complete_antecedent()
    antecedent[field] = value
    result = evaluate_reproducibility(**_base_args(antecedent))
    assert result["status"] == "PROMETE"
    assert result["reproducible"] is False
    assert result["metrics"]["reproducible_state"] == "not_evaluable"


@pytest.mark.parametrize(
    ("b_status", "expected_state"),
    [
        ("INVALID", "not_evaluable"),
        ("INSUFFICIENT_POWER", "not_evaluable"),
        ("RECHAZA", "not_reproducible"),
    ],
)
def test_t26_b_status_precedence_cannot_be_overridden(b_status, expected_state):
    result = evaluate_reproducibility(**_base_args(b_status=b_status))
    assert result["status"] == b_status
    assert result["reproducible"] is False
    assert result["metrics"]["reproducible_state"] == expected_state


@pytest.mark.parametrize("drift_flag", ["REGIME_SHIFT_SUSPECTED", "UNKNOWN_NON_OK"])
def test_t26_drift_flag_cannot_be_washed_into_promete_or_verificado(drift_flag):
    result = evaluate_reproducibility(**_base_args(drift_flag=drift_flag))
    assert result["status"] == "RECHAZA"
    assert result["status"] not in {"PROMETE", "VERIFICADO"}
    assert result["reproducible"] is False
    assert result["metrics"]["reproducibility_reason"] == "drift_detected"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
