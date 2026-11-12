import math

import pytest

from labs.pr_d_cohort_builder import (
    MISSING_EXCLUDE,
    MISSING_RAISE,
    CohortInputError,
    SyncWindow,
    build_preregistered_cohort,
)

WINDOW = SyncWindow(
    lower_seconds=10_800,
    upper_seconds=21_600,
    lower_inclusive=True,
    upper_inclusive=True,
    missing_policy=MISSING_EXCLUDE,
)


def row(candidate_id, *, elapsed=14_400, outcome=3, x=1):
    return {
        "candidate_id": candidate_id,
        "sync_elapsed_seconds": elapsed,
        "outcome": outcome,
        "x": x,
    }


def build(rows, masks=None, window=WINDOW):
    return build_preregistered_cohort(
        rows,
        candidate_id_field="candidate_id",
        outcome_field="outcome",
        predictor_fields=("x",),
        sync_elapsed_seconds_field="sync_elapsed_seconds",
        sync_window=window,
        preregistered_masks={} if masks is None else masks,
    )


def test_temporally_excluded_row_does_not_require_outcome_or_predictors():
    candidate = {
        "candidate_id": "too-early",
        "sync_elapsed_seconds": 10_799,
        # outcome and predictor deliberately absent
    }
    result = build([candidate])
    assert result["candidate_ids"] == ["too-early"]
    assert result["eligible_mask"] == [False]
    assert result["outcomes"] == [None]
    assert result["design_matrix"] == [None]
    assert result["n_total"] == 1
    assert result["n_eff"] == 0
    assert result["excluded"] == [{
        "candidate_id": "too-early",
        "reasons": ["outside_sync_window"],
    }]


def test_missing_sync_timestamp_exclusion_does_not_validate_analytic_fields():
    candidate = {
        "candidate_id": "no-capture",
        "sync_elapsed_seconds": None,
    }
    result = build([candidate])
    assert result["eligible_mask"] == [False]
    assert result["outcomes"] == [None]
    assert result["design_matrix"] == [None]
    assert result["excluded"][0]["reasons"] == ["missing_sync_elapsed"]


def test_mask_excluded_row_does_not_require_analytic_fields():
    candidate = row("masked-out")
    del candidate["outcome"]
    del candidate["x"]
    result = build([candidate], masks={"pre_registered_exclusion": [False]})
    assert result["eligible_mask"] == [False]
    assert result["outcomes"] == [None]
    assert result["design_matrix"] == [None]
    assert result["excluded"] == [{
        "candidate_id": "masked-out",
        "reasons": ["preregistered_filter:pre_registered_exclusion"],
    }]


def test_temporal_and_mask_exclusions_are_both_preserved():
    candidate = {"candidate_id": "both", "sync_elapsed_seconds": 1}
    result = build([candidate], masks={"quality_gate": [False]})
    assert result["excluded"] == [{
        "candidate_id": "both",
        "reasons": ["outside_sync_window", "preregistered_filter:quality_gate"],
    }]


def test_eligible_row_missing_outcome_fails_closed():
    candidate = row("eligible")
    del candidate["outcome"]
    with pytest.raises(CohortInputError, match="candidate_outcome_field_missing"):
        build([candidate])


def test_eligible_row_missing_predictor_fails_closed():
    candidate = row("eligible")
    del candidate["x"]
    with pytest.raises(CohortInputError, match="candidate_predictor_field_missing"):
        build([candidate])


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf, True, "3"])
def test_eligible_row_non_numeric_or_nonfinite_outcome_fails_closed(bad_value):
    with pytest.raises(CohortInputError, match="candidate_outcome_invalid"):
        build([row("eligible", outcome=bad_value)])


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf, True, "1"])
def test_eligible_row_non_numeric_or_nonfinite_predictor_fails_closed(bad_value):
    with pytest.raises(CohortInputError, match="candidate_predictor_invalid"):
        build([row("eligible", x=bad_value)])


def test_excluded_row_with_nan_analytic_values_is_not_used_or_counted():
    result = build([
        row("included", outcome=2, x=1),
        row("excluded", elapsed=30_000, outcome=math.nan, x=math.inf),
    ])
    assert result["eligible_mask"] == [True, False]
    assert result["outcomes"] == [2.0, None]
    assert result["design_matrix"] == [[1.0], None]
    assert result["n_total"] == 2
    assert result["n_eff"] == 1
    assert result["n_events"] == 1


def test_output_arrays_remain_aligned_and_keep_original_order():
    result = build([
        row("a", outcome=2, x=4),
        {"candidate_id": "b", "sync_elapsed_seconds": 1},
        row("c", outcome=0, x=8),
    ])
    assert result["candidate_ids"] == ["a", "b", "c"]
    assert result["eligible_mask"] == [True, False, True]
    assert result["outcomes"] == [2.0, None, 0.0]
    assert result["design_matrix"] == [[4.0], None, [8.0]]
    assert result["eligible_candidate_ids"] == ["a", "c"]
    assert result["n_total"] == 3
    assert result["n_eff"] == 2
    assert result["n_events"] == 1


def test_missing_elapsed_raise_policy_rejects_candidate():
    window = SyncWindow(
        lower_seconds=10_800,
        upper_seconds=21_600,
        lower_inclusive=True,
        upper_inclusive=True,
        missing_policy=MISSING_RAISE,
    )
    with pytest.raises(CohortInputError, match="sync_elapsed_missing"):
        build([{"candidate_id": "missing", "sync_elapsed_seconds": None}], window=window)


def test_mask_length_and_types_must_align_exactly():
    with pytest.raises(CohortInputError, match="preregistered_filter_mask_alignment_invalid"):
        build([row("a")], masks={"filter": []})
    with pytest.raises(CohortInputError, match="preregistered_filter_mask_alignment_invalid"):
        build([row("a")], masks={"filter": [1]})


def test_duplicate_candidate_identity_is_rejected():
    with pytest.raises(CohortInputError, match="candidate_id_duplicate"):
        build([row("same"), row("same")])


def test_boolean_elapsed_is_not_accepted_as_number():
    with pytest.raises(CohortInputError, match="sync_elapsed_invalid"):
        build([row("bad", elapsed=True)])
