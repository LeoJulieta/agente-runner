"""Pure, deterministic PR D cohort construction for synthetic fixtures.

This module does not read manifests, databases, environment variables, or
production data. It does not calculate timestamps: callers must supply a
preregistered elapsed-time field whose temporal anchor and derivation are
defined outside this module.

The frozen PR D contract requires a 3--6 hour synchronization filter but
does not itself specify the source timestamp, temporal anchor, endpoint
inclusivity, or null policy. Therefore every such choice is mandatory input
to SyncWindow; there are deliberately no contractual defaults here.
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
    """Explicit preregistered synchronization interval, expressed in seconds."""

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


def build_preregistered_cohort(
    candidate_rows: Iterable[Mapping[str, Any]],
    *,
    candidate_id_field: str,
    outcome_field: str,
    predictor_fields: Sequence[str],
    sync_elapsed_seconds_field: str,
    sync_window: SyncWindow,
) -> dict[str, Any]:
    """Build aligned candidate arrays, one eligibility mask, and auditable counts.

    The supplied elapsed-seconds value must already represent the
    preregistered interval from the preregistered temporal anchor. This
    function intentionally does not infer that anchor from timestamp names.

    Missing elapsed values are either excluded with an explicit
    missing_sync_elapsed reason or rejected, according to the required
    preregistered policy. Exclusion is a row-level cohort decision; it does
    not itself assign an INVALID hypothesis status.
    """
    for name, value in (
        ("candidate_id_field", candidate_id_field),
        ("outcome_field", outcome_field),
        ("sync_elapsed_seconds_field", sync_elapsed_seconds_field),
    ):
        if not isinstance(value, str) or not value.strip():
            raise CohortInputError(f"{name}_invalid")
    if not isinstance(predictor_fields, Sequence) or isinstance(predictor_fields, (str, bytes)):
        raise CohortInputError("predictor_fields_invalid")
    predictors = tuple(predictor_fields)
    if not predictors or any(not isinstance(item, str) or not item.strip() for item in predictors):
        raise CohortInputError("predictor_fields_invalid")
    if len(predictors) != len(set(predictors)):
        raise CohortInputError("predictor_fields_duplicate")
    if len({candidate_id_field, outcome_field, sync_elapsed_seconds_field, *predictors}) != 3 + len(predictors):
        raise CohortInputError("cohort_field_names_must_be_distinct")
    if not isinstance(sync_window, SyncWindow):
        raise CohortInputError("sync_window_required")

    rows = list(candidate_rows)
    candidate_ids: list[str | int] = []
    outcomes: list[float] = []
    design_matrix: list[list[float]] = []
    eligible_mask: list[bool] = []
    excluded: list[dict[str, str | int]] = []
    seen_ids: set[str | int] = set()

    for row in rows:
        if not isinstance(row, Mapping):
            raise CohortInputError("candidate_row_not_mapping")
        candidate_id = row.get(candidate_id_field)
        if isinstance(candidate_id, bool) or not isinstance(candidate_id, (str, int)) or (
            isinstance(candidate_id, str) and not candidate_id.strip()
        ):
            raise CohortInputError("candidate_id_invalid")
        if candidate_id in seen_ids:
            raise CohortInputError("candidate_id_duplicate")
        seen_ids.add(candidate_id)
        candidate_ids.append(candidate_id)

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

        if sync_elapsed_seconds_field not in row:
            raise CohortInputError("candidate_sync_elapsed_field_missing")
        elapsed_raw = row[sync_elapsed_seconds_field]
        if elapsed_raw is None:
            if sync_window.missing_policy == MISSING_RAISE:
                raise CohortInputError("sync_elapsed_missing")
            eligible_mask.append(False)
            excluded.append({"candidate_id": candidate_id, "reason": "missing_sync_elapsed"})
            continue

        elapsed = _numeric(elapsed_raw, "sync_elapsed_invalid")
        if elapsed < 0:
            raise CohortInputError("sync_elapsed_negative")
        if _inside_window(elapsed, sync_window):
            eligible_mask.append(True)
        else:
            eligible_mask.append(False)
            excluded.append({"candidate_id": candidate_id, "reason": "outside_sync_window"})

    n_total = len(rows)
    n_eff = sum(eligible_mask)
    n_events = sum(
        1 for outcome, eligible in zip(outcomes, eligible_mask)
        if eligible and outcome > 0
    )
    if not (len(candidate_ids) == len(outcomes) == len(design_matrix) == len(eligible_mask) == n_total):
        raise CohortInputError("cohort_alignment_invariant_failed")

    return {
        "candidate_ids": candidate_ids,
        "outcomes": outcomes,
        "design_matrix": design_matrix,
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
            "temporal_anchor": "externally_preregistered_not_inferred",
        },
    }
