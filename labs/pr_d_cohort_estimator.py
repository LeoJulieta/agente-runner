"""Safe bridge from eligibility-first cohorts to the PR D Family II estimator.

Excluded rows remain represented in the cohort builder but are compacted out
before NumPy conversion. Original candidate and eligibility counts are restored
in the result so filtering cannot silently rewrite the sample provenance.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from labs.pr_d_family_ii import fit_ols_log_positive_hc3


def fit_eligible_cohort_hc3(
    cohort: Mapping[str, Any],
    *,
    coefficient_index: int,
    min_n_eff: int = 30,
) -> dict[str, Any]:
    required = ("candidate_ids", "outcomes", "design_matrix", "eligible_mask",
                "n_total", "n_eff", "n_events")
    if not isinstance(cohort, Mapping) or any(key not in cohort for key in required):
        raise ValueError("cohort_contract_incomplete")

    ids = list(cohort["candidate_ids"])
    outcomes = list(cohort["outcomes"])
    design = list(cohort["design_matrix"])
    mask = list(cohort["eligible_mask"])
    n = len(ids)
    if not (len(outcomes) == len(design) == len(mask) == n):
        raise ValueError("cohort_alignment_invalid")
    if any(type(value) is not bool for value in mask):
        raise ValueError("cohort_eligibility_mask_invalid")
    n_eff = sum(mask)
    n_events = sum(1 for y, keep in zip(outcomes, mask) if keep and y is not None and y > 0)
    if (cohort["n_total"], cohort["n_eff"], cohort["n_events"]) != (n, n_eff, n_events):
        raise ValueError("cohort_count_invariant_failed")

    eligible_y = []
    eligible_x = []
    for y, x, keep in zip(outcomes, design, mask):
        if not keep:
            if y is not None or x is not None:
                raise ValueError("excluded_analytic_placeholder_must_be_null")
            continue
        if y is None or x is None:
            raise ValueError("eligible_analytic_value_missing")
        eligible_y.append(y)
        eligible_x.append(x)

    if n_eff == 0:
        if type(min_n_eff) is not int or min_n_eff < 1:
            raise ValueError("min_n_eff_invalid")
        result = {
            "status": "INSUFFICIENT_POWER",
            "metrics": {
                "effect_size": None, "se": None, "p_empirical": None,
                "ci_low": None, "ci_high": None,
                "non_estimability_reason": None,
                "insufficient_power_reason": "n_eff_below_minimum",
                "method_fingerprint": "ols-ln-positive-y-hc3-t-two-sided-v1",
            },
            "bh_input_p": 1.0,
        }
    else:
        result = fit_ols_log_positive_hc3(
            eligible_y, eligible_x,
            coefficient_index=coefficient_index,
            min_n_eff=min_n_eff,
        )

    result["metrics"].update({
        "n_total": n,
        "n_eff": n_eff,
        "n_events": n_events,
    })
    return result
