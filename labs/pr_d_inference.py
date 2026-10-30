"""Isolated PR D statistical primitives for acceptance cases T08 and T12.

Pure functions only: no manifest reads, database access, persistence, or calls
to the production engine. Inputs in this PR are synthetic fixtures.
"""
from __future__ import annotations

import math
import warnings
from typing import Any, Callable, Iterable

import numpy as np
from scipy.optimize import linprog
from scipy.stats import norm
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import ConvergenceWarning, PerfectSeparationError

NON_ESTIMABILITY_REASONS = frozenset({
    "logistic_separation",
    "model_non_convergence",
    "model_not_estimable",
})
INVALID_FDR_REASONS = frozenset({"hypothesis_spec_missing"})


class ScientificNonEstimability(Exception):
    """Known scientific inability to estimate the preregistered model."""

    def __init__(self, reason: str):
        if reason not in NON_ESTIMABILITY_REASONS:
            raise ValueError("non_estimability_reason_invalid")
        self.reason = reason
        super().__init__(reason)


class StructuralBatchAbort(RuntimeError):
    """Unexpected software/infrastructure failure; the family must not publish."""

    def __init__(self, failure_code: str, failure_phase: str, completed: bool = False):
        self.failure_code = failure_code
        self.failure_phase = failure_phase
        self.completed = completed
        super().__init__(f"{failure_code}:{failure_phase}")


def _has_complete_separation(y: np.ndarray, design: np.ndarray) -> bool:
    """Deterministically test strict linear separation using a feasibility LP."""
    signs = np.where(y == 1.0, 1.0, -1.0)
    # A strict separator can be scaled to satisfy signs * X @ beta >= 1.
    result = linprog(
        c=np.zeros(design.shape[1], dtype=np.float64),
        A_ub=-(signs[:, None] * design),
        b_ub=-np.ones(y.size, dtype=np.float64),
        bounds=[(None, None)] * design.shape[1],
        method="highs",
    )
    return bool(result.success)


def fit_logistic_mle(
    y: Iterable[float],
    design_matrix: Iterable[Iterable[float]],
    *,
    coefficient_index: int,
    min_n_eff: int = 30,
    maxiter: int = 100,
) -> dict[str, Any]:
    """Fit the preregistered logistic MLE; never substitute another estimator."""
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
            reason = "logistic_separation" if _has_complete_separation(outcomes, design) else "model_non_convergence"
            return _nonestimable(reason, int(outcomes.size))
    except PerfectSeparationError:
        return _nonestimable("logistic_separation", int(outcomes.size))
    except np.linalg.LinAlgError:
        return _nonestimable("model_not_estimable", int(outcomes.size))
    except ValueError as exc:
        message = str(exc).lower()
        if any(token in message for token in ("singular", "not invertible", "perfect separation")):
            reason = "logistic_separation" if "separation" in message else "model_not_estimable"
            return _nonestimable(reason, int(outcomes.size))
        raise

    if not getattr(fitted, "mle_retvals", {}).get("converged", True):
        reason = "logistic_separation" if _has_complete_separation(outcomes, design) else "model_non_convergence"
        return _nonestimable(reason, int(outcomes.size))

    beta = float(fitted.params[coefficient_index])
    se = float(fitted.bse[coefficient_index])
    p_value = float(fitted.pvalues[coefficient_index])
    if not all(math.isfinite(v) for v in (beta, se, p_value)) or se <= 0 or not 0 <= p_value <= 1:
        return _nonestimable("model_not_estimable", int(outcomes.size))

    z = float(norm.ppf(0.975))
    beta_low, beta_high = beta - z * se, beta + z * se
    try:
        odds_ratio, ci_low, ci_high = math.exp(beta), math.exp(beta_low), math.exp(beta_high)
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
            "ci_low": beta_low,
            "ci_high": beta_high,
            "odds_ratio_ci_low": ci_low,
            "odds_ratio_ci_high": ci_high,
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
            "odds_ratio_ci_low": None,
            "odds_ratio_ci_high": None,
            "non_estimability_reason": reason,
        },
        # Only an adjustment input; never an empirical p-value.
        "bh_input_p": 1.0,
    }


def adjust_bh_family(family: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply Benjamini-Hochberg to every member of one frozen family."""
    rows = [dict(row) for row in family]
    if not rows:
        raise ValueError("fdr_family_empty")
    ids = [row.get("hypothesis_id") for row in rows]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("fdr_hypothesis_identity_invalid_or_duplicate")

    p_values: list[float] = []
    metric_maps: list[dict[str, Any]] = []
    for row in rows:
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            metrics = row
        metric_maps.append(metrics)
        status = row.get("status")
        p_empirical = metrics.get("p_empirical")
        if status == "ESTIMABLE":
            if isinstance(p_empirical, bool) or not isinstance(p_empirical, (int, float)):
                raise ValueError("empirical_p_required")
            p = float(p_empirical)
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                raise ValueError("empirical_p_invalid")
            if metrics.get("non_estimability_reason") not in (None, ""):
                raise ValueError("estimable_row_has_nonestimability_reason")
        elif status == "INSUFFICIENT_POWER":
            if metrics.get("non_estimability_reason") not in NON_ESTIMABILITY_REASONS:
                raise ValueError("non_estimability_reason_required")
            if p_empirical is not None:
                raise ValueError("nonestimable_empirical_p_must_be_null")
            p = 1.0
        elif status == "INVALID":
            invalid_reason = metrics.get("invalid_reason", row.get("invalid_reason"))
            if invalid_reason not in INVALID_FDR_REASONS:
                raise ValueError("invalid_fdr_reason_required_or_unsupported")
            if p_empirical is not None:
                raise ValueError("invalid_empirical_p_must_be_null")
            p = 1.0
        else:
            raise ValueError("fdr_member_status_unsupported")
        row["bh_input_p"] = p
        metrics["bh_input_p"] = p
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
        metric_maps[index]["fdr_q"] = float(q_values[index])
        metric_maps[index]["family_m"] = m
    return rows


def evaluate_family_atomically(
    items: Iterable[Any],
    evaluator: Callable[[Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the complete synthetic family or raise without returning partial rows."""
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
            # Durable E11 abortion records are a separate implementation scope.
            raise StructuralBatchAbort("UNEXPECTED_ERROR", "analysis", completed=False) from exc
        if not isinstance(result, dict):
            raise StructuralBatchAbort("UNEXPECTED_ERROR", "analysis", completed=False)
        completed_rows.append(result)
    return completed_rows
