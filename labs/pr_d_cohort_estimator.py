"""Safe bridge from eligibility-first cohorts to the PR D Family II estimator.

Excluded rows remain represented in the cohort builder but are compacted out
before NumPy conversion. Original candidate and eligibility counts are restored
in the result so filtering cannot silently rewrite the sample provenance.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from labs.pr_d_sync_contract import ObservationExcluded, evaluate_sync_window

from labs.pr_d_family_ii import (
    fit_ols_log_positive_hc3,
)

E12_FILTER_PROVENANCE = {
    "elapsed_unit": "seconds",
    "lower_seconds": 10500.0,
    "upper_seconds": 11100.0,
    "lower_inclusive": True,
    "upper_inclusive": True,
    "missing_policy": "exclude_with_reason",
    "temporal_anchor": "publishedAt",
}
E12_METHOD_FINGERPRINT = (
    "ols-ln-positive-y-hc3-t-two-sided-v1__"
    "yt-viewcount-publishedat-10500-11100-closed-missing-excluded-v1"
)


def _validate_e12_provenance(cohort: Mapping[str, Any]) -> None:
    provenance = cohort.get("filter_provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("e12_filter_provenance_required")
    for key, expected in E12_FILTER_PROVENANCE.items():
        actual = provenance.get(key)
        if type(expected) is bool:
            valid = type(actual) is bool and actual is expected
        else:
            valid = actual == expected and type(actual) is type(expected)
        if not valid:
            raise ValueError(f"e12_filter_provenance_mismatch:{key}")
    if provenance.get("derivation") != "source_timestamp_pair":
        raise ValueError("e12_source_timestamp_derivation_required")
    for key in ("published_at_field", "sync_captured_at_field"):
        value = provenance.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"e12_source_timestamp_field_required:{key}")
    if provenance.get("elapsed_field") is not None:
        raise ValueError("e12_caller_elapsed_field_forbidden")


def fit_eligible_cohort_hc3(
    cohort: Mapping[str, Any],
    *,
    coefficient_index: int,
    min_n_eff: int = 30,
) -> dict[str, Any]:
    required = ("candidate_ids", "outcomes", "design_matrix", "eligible_mask",
                "sync_elapsed_seconds", "published_at_values", "sync_captured_at_values",
                "n_total", "n_eff", "n_events")
    if not isinstance(cohort, Mapping) or any(key not in cohort for key in required):
        raise ValueError("cohort_contract_incomplete")

    _validate_e12_provenance(cohort)

    ids = list(cohort["candidate_ids"])
    outcomes = list(cohort["outcomes"])
    design = list(cohort["design_matrix"])
    mask = list(cohort["eligible_mask"])
    elapsed_values = list(cohort["sync_elapsed_seconds"])
    published_values = list(cohort["published_at_values"])
    captured_values = list(cohort["sync_captured_at_values"])
    n = len(ids)
    if not (len(outcomes) == len(design) == len(mask) == len(elapsed_values)
            == len(published_values) == len(captured_values) == n):
        raise ValueError("cohort_alignment_invalid")
    if any(type(value) is not bool for value in mask):
        raise ValueError("cohort_eligibility_mask_invalid")
    for index, (published, captured, elapsed, eligible) in enumerate(zip(published_values, captured_values, elapsed_values, mask)):
        try:
            derived = evaluate_sync_window(published, captured)
        except ObservationExcluded:
            if elapsed is not None or eligible:
                raise ValueError(f"e12_timestamp_derivation_mismatch:{index}")
            continue
        if elapsed is None or float(elapsed) != derived.elapsed_seconds:
            raise ValueError(f"e12_elapsed_not_derived_from_source_timestamps:{index}")
        if not derived.eligible and eligible:
            raise ValueError(f"e12_out_of_window_row_marked_eligible:{index}")
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
                "method_fingerprint": E12_METHOD_FINGERPRINT,
            },
            "bh_input_p": 1.0,
        }
    else:
        result = fit_ols_log_positive_hc3(
            eligible_y, eligible_x,
            coefficient_index=coefficient_index,
            min_n_eff=min_n_eff,
        )

    result["metrics"]["method_fingerprint"] = E12_METHOD_FINGERPRINT
    result["metrics"].update({
        "n_total": n,
        "n_eff": n_eff,
        "n_events": n_events,
    })
    return result
