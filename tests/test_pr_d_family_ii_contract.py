"""Deterministic synthetic acceptance tests for candidate PR D E6, E7 and E10."""
import pytest

from labs.pr_d_family_ii import (
    compute_d_cond,
    evaluate_drift,
    evaluate_reproducibility,
)


def _b(**overrides):
    values = {
        "b_status": "PROMETE",
        "b_hypothesis_id": "H-SYNTH-01",
        "b_contract_sha256": "a" * 64,
        "b_method_fingerprint": "method-v1",
        "b_effect_size": 0.20,
        "b_ci_low": 0.05,
        "b_ci_high": 0.35,
        "antecedent_a": {
            "hypothesis_id": "H-SYNTH-01",
            "contract_sha256": "a" * 64,
            "method_fingerprint": "method-v1",
            "window": "A",
            "status": "PROMETE",
            "effect_size": 0.18,
            "ci_low": 0.02,
            "ci_high": 0.34,
        },
        "windows_disjoint": True,
        "direction_consistent": True,
        "drift_flag": "OK",
        "drift_evaluation_state": "complete",
        "b_gates_pass": True,
    }
    values.update(overrides)
    return values


def test_e6_absent_antecedent_is_promete_but_not_evaluable():
    result = evaluate_reproducibility(**_b(antecedent_a=None))
    assert result["status"] == "PROMETE"
    assert result["reproducible"] is False
    assert result["metrics"] == {
        "reproducible_state": "not_evaluable",
        "reproducibility_reason": "antecedent_not_localizable",
    }


@pytest.mark.parametrize("missing_field", ["effect_size", "ci_low", "ci_high"])
def test_e6_incomplete_antecedent_is_not_misclassified_as_rejection(missing_field):
    antecedent = dict(_b()["antecedent_a"])
    antecedent[missing_field] = None
    result = evaluate_reproducibility(**_b(antecedent_a=antecedent))
    assert result["status"] == "PROMETE"
    assert result["reproducible"] is False
    assert result["metrics"]["reproducible_state"] == "not_evaluable"
    assert result["metrics"]["reproducibility_reason"] == "antecedent_incomplete"


def test_e6_complete_compatible_antecedent_can_verify():
    result = evaluate_reproducibility(**_b())
    assert result["status"] == "VERIFICADO"
    assert result["reproducible"] is True
    assert result["metrics"]["reproducible_state"] == "reproducible"
    assert result["metrics"]["reproducibility_reason"] is None


def test_e7_incompatible_direction_is_rechaza_not_not_evaluable():
    result = evaluate_reproducibility(**_b(
        direction_consistent=False,
        b_effect_size=-0.20,
        b_ci_low=-0.30,
        b_ci_high=0.10,
    ))
    assert result["status"] == "RECHAZA"
    assert result["reproducible"] is False
    assert result["metrics"]["reproducible_state"] == "not_reproducible"
    assert result["metrics"]["reproducibility_reason"] == "effect_direction_inconsistent"


@pytest.mark.parametrize("status", ["INVALID", "INSUFFICIENT_POWER"])
def test_e7_invalid_and_insufficient_power_keep_precedence(status):
    result = evaluate_reproducibility(**_b(b_status=status))
    assert result["status"] == status
    assert result["metrics"]["reproducible_state"] == "not_evaluable"
    assert result["metrics"]["reproducibility_reason"] == "b_precedence_status"


def test_e7_failed_gates_are_rechaza():
    result = evaluate_reproducibility(**_b(b_gates_pass=False))
    assert result["status"] == "RECHAZA"
    assert result["metrics"]["reproducibility_reason"] == "b_gates_failed"


def _drift(d_init, d_cond, reason=None):
    return evaluate_drift(
        {"d_init": d_init, "d_init_reason": "insufficient_data" if d_init is None else None},
        {"D_cond": d_cond, "drift_degeneracy": reason},
    )


@pytest.mark.parametrize(
    ("d_init", "d_cond", "expected_flag", "expected_state"),
    [
        (0.11, None, "REGIME_SHIFT_SUSPECTED", "partial"),
        (0.10, 0.51, "REGIME_SHIFT_SUSPECTED", "complete"),
        (0.10, 0.50, "OK", "complete"),
        (None, 0.51, "REGIME_SHIFT_SUSPECTED", "partial"),
        (None, 0.50, "OK", "partial"),
        (None, None, None, "not_evaluable"),
        (0.10, None, "OK", "partial"),
    ],
)
def test_e10_drift_decision_table_and_strict_thresholds(d_init, d_cond, expected_flag, expected_state):
    result = _drift(d_init, d_cond, "insufficient_positive_events" if d_cond is None else None)
    assert result["drift_flag"] == expected_flag
    assert result["drift_evaluation_state"] == expected_state


def test_e10_scale_zero_medians_differ_always_raises_drift_alert():
    result = _drift(None, None, "scale_zero_medians_differ")
    assert result["drift_flag"] == "REGIME_SHIFT_SUSPECTED"
    assert result["drift_evaluation_state"] == "partial"


def test_e10_scale_zero_equal_medians_is_zero_not_alert():
    result = _drift(0.10, 0.0, "scale_zero_medians_equal")
    assert result["drift_flag"] == "OK"
    assert result["drift_evaluation_state"] == "complete"


def test_e10_compute_d_cond_exercises_both_mad_degeneracies():
    equal = compute_d_cond([5] * 6, [5] * 6)
    different = compute_d_cond([5] * 6, [7] * 6)
    assert equal["D_cond"] == 0.0
    assert equal["drift_degeneracy"] == "scale_zero_medians_equal"
    assert different["D_cond"] is None
    assert different["drift_degeneracy"] == "scale_zero_medians_differ"


def test_e10_insufficient_positive_events_is_partial_not_structural_error():
    result = compute_d_cond([0, 0, 1, 2], [0, 3, 4, 5])
    assert result["D_cond"] is None
    assert result["drift_degeneracy"] == "insufficient_positive_events"
