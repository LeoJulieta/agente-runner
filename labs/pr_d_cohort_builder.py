"""Fail-closed, deterministic cohort eligibility for isolated PR D fixtures.

Eligibility is decided before analytic values are validated. Excluded rows keep
their identity and reasons but carry None placeholders in aligned analytic
arrays; consumers MUST apply eligible_mask before numerical estimation.
No database, environment, API, or production access occurs in this module.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Any

MISSING_EXCLUDE = "exclude_with_reason"
MISSING_RAISE = "raise"
MISSING_POLICIES = frozenset({MISSING_EXCLUDE, MISSING_RAISE})


class CohortInputError(ValueError):
    """Candidate data or preregistered cohort configuration is invalid."""


@dataclass(frozen=True)
class SyncWindow:
    lower_seconds: float
    upper_seconds: float
    lower_inclusive: bool
    upper_inclusive: bool
    missing_policy: str

    def __post_init__(self) -> None:
        for value in (self.lower_seconds, self.upper_seconds):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise CohortInputError("sync_window_bound_not_numeric")
            if not math.isfinite(float(value)):
                raise CohortInputError("sync_window_bound_nonfinite")
        if float(self.lower_seconds) < 0 or float(self.lower_seconds) >= float(self.upper_seconds):
            raise CohortInputError("sync_window_bounds_invalid")
        if type(self.lower_inclusive) is not bool or type(self.upper_inclusive) is not bool:
            raise CohortInputError("sync_window_inclusivity_must_be_explicit_boolean")
        if not isinstance(self.missing_policy, str) or self.missing_policy not in MISSING_POLICIES:
            raise CohortInputError("sync_window_missing_policy_unsupported")


def _numeric(value: Any, reason: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise CohortInputError(reason)
    result = float(value)
    if not math.isfinite(result):
        raise CohortInputError(reason)
    return result


def _inside_window(value: float, window: SyncWindow) -> bool:
    lower_ok = value >= float(window.lower_seconds) if window.lower_inclusive else value > float(window.lower_seconds)
    upper_ok = value <= float(window.upper_seconds) if window.upper_inclusive else value < float(window.upper_seconds)
    return lower_ok and upper_ok


def _normalize_masks(masks: Mapping[str, Iterable[bool]], n_total: int) -> dict[str, list[bool]]:
    if not isinstance(masks, Mapping):
        raise CohortInputError("preregistered_masks_required")
    names = list(masks)
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise CohortInputError("preregistered_filter_name_invalid")
    result: dict[str, list[bool]] = {}
    for name in sorted(names):
        try:
            values = list(masks[name])
        except TypeError as exc:
            raise CohortInputError("preregistered_filter_mask_invalid") from exc
        if len(values) != n_total or any(type(value) is not bool for value in values):
            raise CohortInputError("preregistered_filter_mask_alignment_invalid")
        result[name] = values
    return result


def build_preregistered_cohort(
    candidate_rows: Iterable[Mapping[str, Any]],
    *,
    candidate_id_field: str,
    outcome_field: str,
    predictor_fields: Sequence[str],
    sync_elapsed_seconds_field: str,
    sync_window: SyncWindow,
    preregistered_masks: Mapping[str, Iterable[bool]],
    temporal_anchor: str = "externally_preregistered_not_inferred",
) -> dict[str, Any]:
    """Build aligned arrays and provenance without validating excluded analytics.

    Pass 1 validates identity, temporal eligibility, and preregistered masks.
    Pass 2 validates outcome/predictors only for eligible rows. Excluded rows
    retain their position and identity, with None analytic placeholders.

    A downstream estimator must first select rows where eligible_mask is true;
    passing placeholders directly into a numerical routine is a contract error.
    """
    required_names = {
        "candidate_id_field": candidate_id_field,
        "outcome_field": outcome_field,
        "sync_elapsed_seconds_field": sync_elapsed_seconds_field,
    }
    for name, value in required_names.items():
        if not isinstance(value, str) or not value.strip():
            raise CohortInputError(f"{name}_invalid")
    if not isinstance(predictor_fields, Sequence) or isinstance(predictor_fields, (str, bytes)):
        raise CohortInputError("predictor_fields_invalid")
    predictors = tuple(predictor_fields)
    if not predictors or any(not isinstance(item, str) or not item.strip() for item in predictors):
        raise CohortInputError("predictor_fields_invalid")
    if len(predictors) != len(set(predictors)):
        raise CohortInputError("predictor_fields_duplicate")
    all_names = [candidate_id_field, outcome_field, sync_elapsed_seconds_field, *predictors]
    if len(set(all_names)) != len(all_names):
        raise CohortInputError("cohort_field_names_must_be_distinct")
    if not isinstance(sync_window, SyncWindow):
        raise CohortInputError("sync_window_required")
    if not isinstance(temporal_anchor, str) or not temporal_anchor.strip():
        raise CohortInputError("temporal_anchor_invalid")

    rows = list(candidate_rows)
    masks = _normalize_masks(preregistered_masks, len(rows))
    candidate_ids: list[str | int] = []
    sync_reasons: list[str | None] = []
    sync_elapsed_seconds: list[float | None] = []
    eligible_mask: list[bool] = []
    seen_ids: set[str | int] = set()

    # Pass 1: determine eligibility before touching outcome or predictors.
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise CohortInputError("candidate_row_not_mapping")
        candidate_id = row.get(candidate_id_field)
        if isinstance(candidate_id, bool) or not isinstance(candidate_id, (str, int)):
            raise CohortInputError("candidate_id_invalid")
        if isinstance(candidate_id, str) and not candidate_id.strip():
            raise CohortInputError("candidate_id_invalid")
        if candidate_id in seen_ids:
            raise CohortInputError("candidate_id_duplicate")
        seen_ids.add(candidate_id)
        candidate_ids.append(candidate_id)

        if sync_elapsed_seconds_field not in row:
            raise CohortInputError("candidate_sync_elapsed_field_missing")
        raw_elapsed = row[sync_elapsed_seconds_field]
        if raw_elapsed is None:
            if sync_window.missing_policy == MISSING_RAISE:
                raise CohortInputError("sync_elapsed_missing")
            sync_reasons.append("missing_sync_elapsed")
            sync_elapsed_seconds.append(None)
            temporal_ok = False
        else:
            elapsed = _numeric(raw_elapsed, "sync_elapsed_invalid")
            if elapsed < 0:
                raise CohortInputError("sync_elapsed_negative")
            sync_elapsed_seconds.append(elapsed)
            temporal_ok = _inside_window(elapsed, sync_window)
            sync_reasons.append(None if temporal_ok else "outside_sync_window")

        eligible_mask.append(temporal_ok and all(mask[index] for mask in masks.values()))

    # Pass 2: validate analytic fields only for rows which can enter the model.
    outcomes: list[float | None] = []
    design_matrix: list[list[float] | None] = []
    for index, row in enumerate(rows):
        if not eligible_mask[index]:
            outcomes.append(None)
            design_matrix.append(None)
            continue

        if outcome_field not in row:
            raise CohortInputError("candidate_outcome_field_missing")
        outcome = _numeric(row[outcome_field], "candidate_outcome_invalid")
        if outcome < 0:
            raise CohortInputError("candidate_outcome_negative")
        outcomes.append(outcome)

        design_row: list[float] = []
        for field in predictors:
            if field not in row:
                raise CohortInputError("candidate_predictor_field_missing")
            design_row.append(_numeric(row[field], "candidate_predictor_invalid"))
        design_matrix.append(design_row)

    excluded: list[dict[str, Any]] = []
    for index, candidate_id in enumerate(candidate_ids):
        reasons: list[str] = []
        if sync_reasons[index] is not None:
            reasons.append(sync_reasons[index])
        for name, mask in masks.items():
            if not mask[index]:
                reasons.append(f"preregistered_filter:{name}")
        if reasons:
            excluded.append({"candidate_id": candidate_id, "reasons": reasons})

    n_total = len(rows)
    n_eff = sum(eligible_mask)
    n_events = sum(
        1 for outcome, eligible in zip(outcomes, eligible_mask)
        if eligible and outcome is not None and outcome > 0
    )
    if not (
        len(candidate_ids) == len(outcomes) == len(design_matrix)
        == len(sync_elapsed_seconds) == len(eligible_mask) == n_total
    ):
        raise CohortInputError("cohort_alignment_invariant_failed")

    return {
        "candidate_ids": candidate_ids,
        "outcomes": outcomes,
        "design_matrix": design_matrix,
        "sync_elapsed_seconds": sync_elapsed_seconds,
        "eligible_mask": eligible_mask,
        "eligible_candidate_ids": [
            candidate_id for candidate_id, eligible in zip(candidate_ids, eligible_mask) if eligible
        ],
        "excluded": excluded,
        "n_total": n_total,
        "n_eff": n_eff,
        "n_events": n_events,
        "filter_provenance": {
            "elapsed_field": sync_elapsed_seconds_field,
            "elapsed_unit": "seconds",
            "lower_seconds": float(sync_window.lower_seconds),
            "upper_seconds": float(sync_window.upper_seconds),
            "lower_inclusive": sync_window.lower_inclusive,
            "upper_inclusive": sync_window.upper_inclusive,
            "missing_policy": sync_window.missing_policy,
            "temporal_anchor": temporal_anchor,
            "additional_preregistered_filters": list(masks),
            "analytic_validation": "eligible_rows_only",
            "excluded_analytic_placeholders": None,
        },
    }
