"""Synthetic-only PR D Family II, drift and reproducibility primitives.

No repository manifest reads, database access, persistence, production-engine
calls, or real observations. All public functions are deterministic and pure.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import statsmodels.api as sm

METHOD_FINGERPRINT_OLS_HC3 = "ols-ln-positive-y-hc3-t-two-sided-v1"
DRIFT_DEGENERACY_REASONS = frozenset({
    "insufficient_positive_events",
    "scale_zero_medians_equal",
    "scale_zero_medians_differ",
})
REPRODUCIBLE_STATES = frozenset({
    "reproducible", "not_reproducible", "not_evaluable",
})


def fit_ols_log_positive_hc3(
    outcomes: Iterable[float],
    design_matrix: Iterable[Iterable[float]],
    *,
    coefficient_index: int,
    min_n_eff: int = 30,
) -> dict[str, Any]:
    """Fit OLS on ln(Y) for Y>0 with the contract-fixed HC3 covariance.

    Zero outcomes remain counted in n_total but are excluded from the
    conditional model. No alternate covariance or estimator is substituted.
    """
    y_all = np.asarray(list(outcomes), dtype=np.float64)
    design_all = np.asarray(list(design_matrix), dtype=np.float64)
    if y_all.ndim != 1 or design_all.ndim != 2 or design_all.shape[0] != y_all.size:
        raise ValueError("ols_input_shape_invalid")
    if y_all.size == 0 or not np.isfinite(y_all).all() or not np.isfinite(design_all).all():
        raise ValueError("ols_input_nonfinite_or_empty")
    if np.any(y_all < 0):
        raise ValueError("ols_outcome_negative")
    if type(min_n_eff) is not int or min_n_eff < 1:
        raise ValueError("min_n_eff_invalid")
    if type(coefficient_index) is not int or not 0 <= coefficient_index < design_all.shape[1]:
        raise ValueError("coefficient_index_invalid")
    if design_all.shape[1] == 0:
        raise ValueError("ols_design_empty")

    positive = y_all > 0
    y_positive = y_all[positive]
    design = design_all[positive]
    n_total, n_events, n_eff = int(y_all.size), int(positive.sum()), int(y_all.size)
    base = {
        "n_total": n_total,
        "n_events": n_events,
        "n_eff": n_eff,
        "method_fingerprint": METHOD_FINGERPRINT_OLS_HC3,
    }
    if n_eff < min_n_eff or n_events < 5:
        reason = "n_eff_below_minimum" if n_eff < min_n_eff else "n_events_below_minimum"
        return {
            "status": "INSUFFICIENT_POWER",
            "metrics": {
                **base, "effect_size": None, "se": None, "p_empirical": None,
                "ci_low": None, "ci_high": None, "non_estimability_reason": None,
                "insufficient_power_reason": reason,
            },
            "bh_input_p": 1.0,
        }
    if n_events <= design.shape[1] or np.linalg.matrix_rank(design) < design.shape[1]:
        return _ols_nonestimable(base, "model_not_estimable")

    try:
        fitted = sm.OLS(np.log(y_positive), design).fit(cov_type="HC3", use_t=True)
        beta = float(fitted.params[coefficient_index])
        se = float(fitted.bse[coefficient_index])
        p_value = float(fitted.pvalues[coefficient_index])
        ci = np.asarray(fitted.conf_int(alpha=0.05), dtype=np.float64)[coefficient_index]
        ci_low, ci_high = float(ci[0]), float(ci[1])
    except (np.linalg.LinAlgError, ValueError, FloatingPointError):
        return _ols_nonestimable(base, "model_not_estimable")

    values = (beta, se, p_value, ci_low, ci_high)
    if (not all(math.isfinite(value) for value in values)
            or se <= 0 or not 0 <= p_value <= 1 or ci_low > beta or ci_high < beta):
        return _ols_nonestimable(base, "model_not_estimable")
    return {
        "status": "ESTIMABLE",
        "metrics": {
            **base, "effect_size": beta, "se": se, "p_empirical": p_value,
            "ci_low": ci_low, "ci_high": ci_high, "non_estimability_reason": None,
            "insufficient_power_reason": None,
            "covariance_type": "HC3", "contrast": "two_sided_t",
        },
        "bh_input_p": p_value,
    }


def _ols_nonestimable(base: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "status": "INSUFFICIENT_POWER",
        "metrics": {
            **base, "effect_size": None, "se": None, "p_empirical": None,
            "ci_low": None, "ci_high": None, "non_estimability_reason": reason,
        },
        "bh_input_p": 1.0,
    }


def compute_d_init(
    positive_a: int | None,
    total_a: int | None,
    positive_b: int | None,
    total_b: int | None,
) -> dict[str, Any]:
    """Compute abs(p_A-p_B); missing comparable counts return null with reason."""
    values = (positive_a, total_a, positive_b, total_b)
    if any(value is None for value in values):
        return {"d_init": None, "d_init_reason": "insufficient_data"}
    if any(type(value) is not int for value in values):
        raise ValueError("d_init_counts_must_be_integers")
    if total_a <= 0 or total_b <= 0:
        raise ValueError("d_init_total_must_be_positive")
    if not 0 <= positive_a <= total_a or not 0 <= positive_b <= total_b:
        raise ValueError("d_init_positive_count_out_of_range")
    p_a = np.float64(positive_a) / np.float64(total_a)
    p_b = np.float64(positive_b) / np.float64(total_b)
    value = float(abs(p_a - p_b))
    if not math.isfinite(value):
        raise ValueError("d_init_nonfinite")
    return {"d_init": value, "d_init_reason": None}


def compute_d_cond(outcomes_a: Iterable[float], outcomes_b: Iterable[float]) -> dict[str, Any]:
    """Compute contract-defined MAD-standardized median shift using Y>0 only."""
    a = np.asarray(list(outcomes_a), dtype=np.float64)
    b = np.asarray(list(outcomes_b), dtype=np.float64)
    if a.ndim != 1 or b.ndim != 1 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("d_cond_input_nonfinite_or_shape_invalid")
    if np.any(a < 0) or np.any(b < 0):
        raise ValueError("d_cond_outcome_negative")
    a_pos, b_pos = a[a > 0], b[b > 0]
    n_a, n_b = int(a_pos.size), int(b_pos.size)
    result: dict[str, Any] = {"n_events_a": n_a, "n_events_b": n_b}
    if n_a < 5 or n_b < 5:
        return {
            **result, "D_cond": None,
            "drift_degeneracy": "insufficient_positive_events",
        }

    log_a, log_b = np.log(a_pos), np.log(b_pos)
    median_a, median_b = float(np.median(log_a)), float(np.median(log_b))
    mad_a = 1.4826 * float(np.median(np.abs(log_a - median_a)))
    mad_b = 1.4826 * float(np.median(np.abs(log_b - median_b)))
    pooled_dof = n_a + n_b - 2
    pooled = math.sqrt(((n_a - 1) * mad_a**2 + (n_b - 1) * mad_b**2) / pooled_dof)
    delta = abs(median_a - median_b)
    if not all(math.isfinite(v) for v in (median_a, median_b, mad_a, mad_b, pooled, delta)):
        raise ValueError("d_cond_nonfinite_intermediate")
    if pooled == 0.0:
        if median_a == median_b:
            return {
                **result, "D_cond": 0.0,
                "drift_degeneracy": "scale_zero_medians_equal",
            }
        return {
            **result, "D_cond": None,
            "drift_degeneracy": "scale_zero_medians_differ",
        }
    value = float(delta / pooled)
    if not math.isfinite(value):
        raise ValueError("d_cond_nonfinite")
    return {**result, "D_cond": value, "drift_degeneracy": None}


def evaluate_drift(d_init_result: dict[str, Any], d_cond_result: dict[str, Any]) -> dict[str, Any]:
    """Apply the exhaustive contractual two-dimensional drift decision table."""
    d_init = d_init_result.get("d_init")
    d_init_reason = d_init_result.get("d_init_reason")
    d_cond = d_cond_result.get("D_cond")
    degeneracy = d_cond_result.get("drift_degeneracy")
    if d_init is not None:
        if isinstance(d_init, bool) or not isinstance(d_init, (int, float)) or not math.isfinite(float(d_init)) or not 0 <= d_init <= 1:
            raise ValueError("d_init_invalid")
        if d_init_reason not in (None, ""):
            raise ValueError("d_init_reason_conflicts_with_value")
    elif d_init_reason != "insufficient_data":
        raise ValueError("d_init_null_reason_invalid")
    if d_cond is not None:
        if isinstance(d_cond, bool) or not isinstance(d_cond, (int, float)) or not math.isfinite(float(d_cond)) or d_cond < 0:
            raise ValueError("D_cond_invalid")
        if degeneracy is not None and not (
            float(d_cond) == 0.0 and degeneracy == "scale_zero_medians_equal"
        ):
            raise ValueError("D_cond_degeneracy_conflicts_with_value")
    elif degeneracy not in DRIFT_DEGENERACY_REASONS - {"scale_zero_medians_equal"}:
        raise ValueError("D_cond_null_reason_invalid")

    init_alert = d_init is not None and float(d_init) > 0.10
    cond_alert = d_cond is not None and float(d_cond) > 0.50
    regime_degeneracy = degeneracy == "scale_zero_medians_differ"
    if init_alert or cond_alert or regime_degeneracy:
        flag = "REGIME_SHIFT_SUSPECTED"
    elif d_init is None and d_cond is None:
        flag = None
    else:
        flag = "OK"

    if d_init is not None and d_cond is not None:
        state = "complete"
    elif d_init is None and d_cond is None:
        state = "not_evaluable"
    else:
        state = "partial"
    if regime_degeneracy:
        state = "partial"
    return {
        "drift_flag": flag,
        "drift_evaluation_state": state,
        "d_init": None if d_init is None else float(d_init),
        "D_cond": None if d_cond is None else float(d_cond),
        "drift_degeneracy": degeneracy,
        "d_init_reason": d_init_reason,
    }


def evaluate_reproducibility(
    *,
    b_status: str,
    b_hypothesis_id: str,
    b_contract_sha256: str,
    b_method_fingerprint: str,
    b_effect_size: float | None,
    b_ci_low: float | None,
    b_ci_high: float | None,
    antecedent_a: dict[str, Any] | None,
    windows_disjoint: bool,
    direction_consistent: bool,
    drift_flag: str | None,
    drift_evaluation_state: str,
    b_gates_pass: bool,
) -> dict[str, Any]:
    """Apply conservative A/B reproducibility rules without persistence."""
    if b_status in {"INVALID", "INSUFFICIENT_POWER"}:
        return _repro(b_status, False, "not_evaluable", "b_precedence_status")
    if b_status == "RECHAZA":
        return _repro("RECHAZA", False, "not_reproducible", "b_precedence_status")
    if b_status not in {"PROMETE", "VERIFICADO", "RECHAZA"}:
        raise ValueError("b_status_invalid")
    if not b_gates_pass:
        return _repro("RECHAZA", False, "not_reproducible", "b_gates_failed")
    if not _finite_interval(b_effect_size, b_ci_low, b_ci_high):
        return _repro("PROMETE", False, "not_evaluable", "b_inference_incomplete")
    if not isinstance(antecedent_a, dict):
        return _repro("PROMETE", False, "not_evaluable", "antecedent_not_localizable")

    required_identity = (
        antecedent_a.get("hypothesis_id") == b_hypothesis_id
        and antecedent_a.get("contract_sha256") == b_contract_sha256
        and antecedent_a.get("method_fingerprint") == b_method_fingerprint
        and antecedent_a.get("window") == "A"
        and antecedent_a.get("status") in {"PROMETE", "VERIFICADO"}
    )
    if not required_identity:
        return _repro("PROMETE", False, "not_evaluable", "antecedent_not_localizable")
    a_effect, a_low, a_high = (
        antecedent_a.get("effect_size"), antecedent_a.get("ci_low"), antecedent_a.get("ci_high")
    )
    if not _finite_interval(a_effect, a_low, a_high):
        return _repro("PROMETE", False, "not_evaluable", "antecedent_incomplete")
    if drift_evaluation_state != "complete" or drift_flag is None:
        return _repro("PROMETE", False, "not_evaluable", "drift_not_evaluable")
    if not windows_disjoint:
        return _repro("RECHAZA", False, "not_reproducible", "windows_not_disjoint")
    if not direction_consistent or float(a_effect) * float(b_effect_size) < 0:
        return _repro("RECHAZA", False, "not_reproducible", "effect_direction_inconsistent")
    if max(float(a_low), float(b_ci_low)) > min(float(a_high), float(b_ci_high)):
        return _repro("RECHAZA", False, "not_reproducible", "confidence_intervals_incompatible")
    if drift_flag != "OK":
        return _repro("RECHAZA", False, "not_reproducible", "drift_detected")
    return _repro("VERIFICADO", True, "reproducible", None)


def _finite_interval(effect: Any, low: Any, high: Any) -> bool:
    values = (effect, low, high)
    return all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
        for value in values
    ) and float(low) <= float(effect) <= float(high) and float(low) <= float(high)


def _repro(status: str, reproducible: bool, state: str, reason: str | None) -> dict[str, Any]:
    if state not in REPRODUCIBLE_STATES:
        raise ValueError("reproducible_state_invalid")
    return {
        "status": status,
        "reproducible": reproducible,
        "metrics": {"reproducible_state": state, "reproducibility_reason": reason},
    }
