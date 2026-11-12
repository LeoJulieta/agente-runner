import pytest

from labs.pr_d_family_ii import compute_d_cond, evaluate_drift, evaluate_reproducibility


def test_d_cond_insufficient_events_returns_null_with_reason():
    assert compute_d_cond([1, 2, 0], [1, 2, 3])["drift_degeneracy"] == "insufficient_positive_events"


def test_d_cond_zero_scale_equal_and_different_medians():
    equal = compute_d_cond([5] * 5, [5] * 5)
    different = compute_d_cond([1] * 5, [2] * 5)
    assert (equal["D_cond"], equal["drift_degeneracy"]) == (0.0, "scale_zero_medians_equal")
    assert different["D_cond"] is None
    assert different["drift_degeneracy"] == "scale_zero_medians_differ"


def test_drift_combines_dimensions_and_preserves_partial_state():
    partial = evaluate_drift(
        {"d_init": 0.11, "d_init_reason": None},
        {"D_cond": None, "drift_degeneracy": "insufficient_positive_events"},
    )
    complete = evaluate_drift(
        {"d_init": 0.05, "d_init_reason": None},
        {"D_cond": 0.25, "drift_degeneracy": None},
    )
    assert (partial["drift_flag"], partial["drift_evaluation_state"]) == ("REGIME_SHIFT_SUSPECTED", "partial")
    assert (complete["drift_flag"], complete["drift_evaluation_state"]) == ("OK", "complete")


def _kwargs(**overrides):
    values = {
        "b_status": "PROMETE", "b_hypothesis_id": "H001",
        "b_contract_sha256": "a" * 64,
        "b_method_fingerprint": "ols-ln-positive-y-hc3-t-two-sided-v1",
        "b_effect_size": 0.4, "b_ci_low": 0.1, "b_ci_high": 0.7,
        "antecedent_a": {
            "hypothesis_id": "H001", "contract_sha256": "a" * 64,
            "method_fingerprint": "ols-ln-positive-y-hc3-t-two-sided-v1",
            "window": "A", "status": "PROMETE",
            "effect_size": 0.3, "ci_low": 0.05, "ci_high": 0.6,
        },
        "windows_disjoint": True, "direction_consistent": True,
        "drift_flag": "OK", "drift_evaluation_state": "complete",
        "b_gates_pass": True,
    }
    values.update(overrides)
    return values


def test_reproducibility_accepts_only_compatible_disjoint_windows_without_drift():
    result = evaluate_reproducibility(**_kwargs())
    assert result["status"] == "VERIFICADO"
    assert result["reproducible"] is True
    assert result["metrics"]["reproducible_state"] == "reproducible"


@pytest.mark.parametrize(
    ("overrides", "status", "reason"),
    [
        ({"windows_disjoint": False}, "RECHAZA", "windows_not_disjoint"),
        ({"direction_consistent": False}, "RECHAZA", "effect_direction_inconsistent"),
        ({"drift_flag": "REGIME_SHIFT_SUSPECTED"}, "RECHAZA", "drift_detected"),
        ({"drift_evaluation_state": "partial"}, "PROMETE", "drift_not_evaluable"),
        ({"b_effect_size": 0.85, "b_ci_low": 0.8, "b_ci_high": 0.9},
         "RECHAZA", "confidence_intervals_incompatible"),
        ({"b_status": "INVALID"}, "INVALID", "b_precedence_status"),
    ],
)
def test_reproducibility_precedence_and_failure_paths(overrides, status, reason):
    result = evaluate_reproducibility(**_kwargs(**overrides))
    assert result["status"] == status
    assert result["metrics"]["reproducibility_reason"] == reason


def test_reproducibility_rejects_non_boolean_flags():
    with pytest.raises(ValueError, match="reproducibility_flags_must_be_booleans"):
        evaluate_reproducibility(**_kwargs(windows_disjoint=1))
