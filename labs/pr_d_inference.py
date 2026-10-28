"""Isolated PR D statistical primitives for acceptance cases T08 and T12.

This module is pure with respect to external systems: it never reads a manifest,
opens a database connection, persists rows, or invokes the production engine.
Callers must provide synthetic or otherwise explicitly authorized arrays.
"""
from __future__ import annotations

import math
import warnings
from typing import Any, Callable, Iterable

import numpy as np
from scipy.stats import norm
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import (
    ConvergenceWarning,
    PerfectSeparationError,
)

NON_ESTIMABILITY_REASONS = frozenset({
    "logistic_separation",
    "model_non_convergence",
    "model_not_estimable",
})


class ScientificNonEstimability(Exception):
    """Known scientific inability to estimate the preregistered model."""

    def __init__(self, reason: str):
        if reason not in NON_ESTIMABILITY_REASONS:
            raise ValueError("non_estimability_reason_invalid")
        self.reason = reason
        super().__init__(reason)


class StructuralBatchAbort(RuntimeError):
    """Unexpected infrastructure/software failure; the family must not publish."""

    def __init__(self, failure_code: str, failure_phase: str, completed: bool = False):
        self.failure_code = failure_code
        self.failure_phase = failure_phase
        self.completed = completed
        super().__init__(f"{failure_code}:{failure_phase}")


def fit_logistic_mle(
    y: Iterable[float],
    design_matrix: Iterable[Iterable[float]],
    *,
    coefficient_index: int,
    min_n_eff: int = 30,
    maxiter: int = 100,
) -> dict[str, Any]:
    """Fit the preregistered logistic MLE or return a closed non-estimability result.

    design_matrix must already encode the preregistered intercept and columns.
    No alternative model or fallback estimator is attempted.
    """
    outcomes = np.asarray(list(y), dtype=np.float64)
    design = np.asarray(list(design_matrix), dtype=np.float64)

    if outcomes.ndim != 1 or design.ndim != 2 or design.shape[0] != outcomes.size:
        raise ValueError("logistic_input_shape_invalid")
    if outcomes.size == 0 or not np.isfinite(outcomes).all() or not np.isfinite(design).all():
        raise ValueError("logistic_input_nonfinite_or_empty")
    if not np.isin(outcomes, [0.0, 1.0]).all():
        raise ValueError("logistic_outcome_not_binary")
    if type(min_n_eff) is not int or min_n_eff < 1 or outcomes.size < min_n_eff:
        raise ValueError("n_eff_below_minimum")
    if type(coefficient_index) is not int or not 0 <= coefficient_index < design.shape[1]:
        raise ValueError("coefficient_index_invalid")
    if design.shape[1] == 0:
        raise ValueError("logistic_design_empty")
    if np.linalg.matrix_rank(design) < design.shape[1]:
        return _nonestimable("model_not_estimable", int(outcomes.size))

    if np.unique(outcomes).size < 2:
        return _nonestimable("model_not_estimable", int(outcomes.size))

    try:
        model = sm.Logit(outcomes, design)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fitted = model.fit(disp=False, maxiter=maxiter, warn_convergence=True)
        if any(type(item.message).__name__ == "PerfectSeparationWarning" for item in caught):
            return _nonestimable("logistic_separation", int(outcomes.size))
        if any(issubclass(item.category, ConvergenceWarning) for item in caught):
            return _nonestimable("model_non_convergence", int(outcomes.size))
    except PerfectSeparationError:
        return _nonestimable("logistic_separation", int(outcomes.size))
    except (np.linalg.LinAlgError, ValueError) as exc:
        # Known singular/non-estimable numerical conditions are scientific;
        # unexpected exception classes are intentionally not swallowed.
        if isinstance(exc, np.linalg.LinAlgError):
            return _nonestimable("model_not_estimable", int(outcomes.size))
        message = str(exc).lower()
        if any(token in message for token in ("singular", "not invertible", "perfect separation")):
            reason = "logistic_separation" if "separation" in message else "model_not_estimable"
            return _nonestimable(reason, int(outcomes.size))
        raise

    converged = getattr(fitted, "mle_retvals", {}).get("converged", True)
    if not converged:
        return _nonestimable("model_non_convergence", int(outcomes.size))

    beta = float(fitted.params[coefficient_index])
    se = float(fitted.bse[coefficient_index])
    p_value = float(fitted.pvalues[coefficient_index])
    if not all(math.isfinite(v) for v in (beta, se, p_value)) or se <= 0 or not 0 <= p_value <= 1:
        return _nonestimable("model_not_estimable", int(outcomes.size))

    z = float(norm.ppf(0.975))
    beta_low = beta - z * se
    beta_high = beta + z * se
    try:
        odds_ratio = math.exp(beta)
        ci_low = math.exp(beta_low)
        ci_high = math.exp(beta_high)
    except OverflowError:
        return _nonestimable("model_not_estimable", int(outcomes.size))
    if not all(math.isfinite(v) for v in (odds_ratio, ci_low, ci_high)):
        return _nonestimable("model_not_estimable", int(outcomes.size))

    return {
        "status": "ESTIMABLE",
        "metrics": {
            "n_eff": int(outcomes.size),
            "effect_size": beta,
            "se": se,
            "p_empirical": p_value,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "coefficient_ci_low": beta_low,
            "coefficient_ci_high": beta_high,
            "odds_ratio": odds_ratio,
            "non_estimability_reason": None,
        },
        "bh_input_p": p_value,
    }


def _nonestimable(reason: str, n_eff: int) -> dict[str, Any]:
    if reason not in NON_ESTIMABILITY_REASONS:
        raise ValueError("non_estimability_reason_invalid")
    return {
        "status": "INSUFFICIENT_POWER",
        "metrics": {
            "n_eff": n_eff,
            "effect_size": None,
            "se": None,
            "p_empirical": None,
            "ci_low": None,
            "ci_high": None,
            "odds_ratio": None,
            "non_estimability_reason": reason,
        },
        # This value is only an input to the frozen-family BH adjustment.
        # It is deliberately not written into p_empirical.
        "bh_input_p": 1.0,
    }


def adjust_bh_family(family: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply Benjamini-Hochberg to a frozen family without dropping members."""
    rows = [dict(row) for row in family]
    if not rows:
        raise ValueError("fdr_family_empty")
    ids = [row.get("hypothesis_id") for row in rows]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("fdr_hypothesis_identity_invalid_or_duplicate")

    p_values: list[float] = []
    for row in rows:
        status = row.get("status")
        p_empirical = row.get("p_empirical")
        if status == "ESTIMABLE":
            if isinstance(p_empirical, bool) or not isinstance(p_empirical, (int, float)):
                raise ValueError("empirical_p_required")
            p = float(p_empirical)
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                raise ValueError("empirical_p_invalid")
            if row.get("non_estimability_reason") not in (None, ""):
                raise ValueError("estimable_row_has_nonestimability_reason")
        elif status == "INSUFFICIENT_POWER":
            reason = row.get("non_estimability_reason")
            if reason not in NON_ESTIMABILITY_REASONS:
                raise ValueError("non_estimability_reason_required")
            if p_empirical is not None:
                raise ValueError("nonestimable_empirical_p_must_be_null")
            p = 1.0
        else:
            raise ValueError("fdr_member_status_unsupported")
        row["bh_input_p"] = p
        p_values.append(p)

    m = len(rows)
    order = sorted(range(m), key=lambda index: (p_values[index], index))
    q_values = [1.0] * m
    running_min = 1.0
    for reverse_rank in range(m - 1, -1, -1):
        index = order[reverse_rank]
        rank = reverse_rank + 1
        running_min = min(running_min, p_values[index] * m / rank)
        q_values[index] = min(1.0, running_min)

    for index, row in enumerate(rows):
        row["fdr_q"] = float(q_values[index])
        row["family_m"] = m
    return rows


def evaluate_family_atomically(
    items: Iterable[Any],
    evaluator: Callable[[Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluate a synthetic frozen family; return nothing if a structural error occurs."""
    completed_rows: list[dict[str, Any]] = []
    for item in items:
        try:
            result = evaluator(item)
        except ScientificNonEstimability as exc:
            completed_rows.append({
                "hypothesis_id": str(item),
                "status": "INSUFFICIENT_POWER",
                "p_empirical": None,
                "non_estimability_reason": exc.reason,
            })
            continue
        except Exception as exc:
            # Durable operational abortion records are handled by the runner/CI
            # layer in the separate E11 implementation.
            raise StructuralBatchAbort("UNEXPECTED_ERROR", "analysis", completed=False) from exc
        if not isinstance(result, dict):
            raise StructuralBatchAbort("UNEXPECTED_ERROR", "analysis", completed=False)
        completed_rows.append(result)
    return completed_rows
