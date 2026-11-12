import copy

import pytest

from labs.pr_d_cohort_builder import SyncWindow, build_preregistered_cohort
from labs.pr_d_cohort_estimator import E12_METHOD_FINGERPRINT, fit_eligible_cohort_hc3
from labs.pr_d_family_ii import METHOD_FINGERPRINT_OLS_HC3


def _cohort():
    return build_preregistered_cohort(
        [
            {"id": "v1", "views_primeras_3h": 120, "x": 1.0, "elapsed": 10800},
            {"id": "v2", "views_primeras_3h": 0, "x": 0.0, "elapsed": 10900},
        ],
        candidate_id_field="id",
        outcome_field="views_primeras_3h",
        predictor_fields=["x"],
        sync_elapsed_seconds_field="elapsed",
        sync_window=SyncWindow(
            lower_seconds=10500,
            upper_seconds=11100,
            lower_inclusive=True,
            upper_inclusive=True,
            missing_policy="exclude_with_reason",
        ),
        preregistered_masks={},
        temporal_anchor="publishedAt",
    )


def test_valid_e12_provenance_is_required_before_fingerprint_assignment():
    result = fit_eligible_cohort_hc3(_cohort(), coefficient_index=0)
    assert result["metrics"]["method_fingerprint"] == E12_METHOD_FINGERPRINT
    assert E12_METHOD_FINGERPRINT != METHOD_FINGERPRINT_OLS_HC3


def test_missing_filter_provenance_is_rejected():
    cohort = _cohort()
    del cohort["filter_provenance"]
    with pytest.raises(ValueError, match="e12_filter_provenance_required"):
        fit_eligible_cohort_hc3(cohort, coefficient_index=0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lower_seconds", 10499.0),
        ("upper_seconds", 11101.0),
        ("lower_inclusive", False),
        ("upper_inclusive", False),
        ("missing_policy", "raise"),
        ("elapsed_unit", "milliseconds"),
        ("temporal_anchor", "sync_captured_at"),
    ],
)
def test_any_contradictory_e12_provenance_field_is_rejected(field, value):
    cohort = copy.deepcopy(_cohort())
    cohort["filter_provenance"][field] = value
    with pytest.raises(ValueError, match=f"e12_filter_provenance_mismatch:{field}"):
        fit_eligible_cohort_hc3(cohort, coefficient_index=0)


def test_missing_elapsed_field_provenance_is_rejected():
    cohort = copy.deepcopy(_cohort())
    del cohort["filter_provenance"]["elapsed_field"]
    with pytest.raises(ValueError, match="e12_filter_provenance_mismatch:elapsed_field"):
        fit_eligible_cohort_hc3(cohort, coefficient_index=0)


def test_default_unanchored_builder_provenance_cannot_claim_e12():
    cohort = build_preregistered_cohort(
        [{"id": "v1", "views": 10, "x": 1.0, "elapsed": 10800}],
        candidate_id_field="id",
        outcome_field="views",
        predictor_fields=["x"],
        sync_elapsed_seconds_field="elapsed",
        sync_window=SyncWindow(10500, 11100, True, True, "exclude_with_reason"),
        preregistered_masks={},
    )
    with pytest.raises(ValueError, match="e12_filter_provenance_mismatch:temporal_anchor"):
        fit_eligible_cohort_hc3(cohort, coefficient_index=0)
