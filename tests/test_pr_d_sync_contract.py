"""Synthetic acceptance tests for PR D producer temporal provenance (E12)."""
from datetime import datetime, timedelta, timezone
import math

import pytest

from labs.pr_d_cohort_builder import (
    MISSING_EXCLUDE,
    SyncWindow,
    build_preregistered_cohort,
)
from labs.pr_d_family_ii import fit_ols_log_positive_hc3
from labs.pr_d_sync_contract import (
    LOWER_SYNC_SECONDS,
    UPPER_SYNC_SECONDS,
    ObservationExcluded,
    YouTubeReadError,
    evaluate_sync_window,
    exclusion_record,
    extract_published_at,
    parse_sync_captured_at,
    publication_datetime_ushuaia,
)


VIDEO_ID = "fixture-video-001"
PUBLISHED = "2026-10-30T02:30:00Z"


def youtube_resource(published_at=PUBLISHED, *, video_id=VIDEO_ID, privacy="public"):
    snippet = {}
    if published_at is not ...:
        snippet["publishedAt"] = published_at
    return {
        "items": [{
            "id": video_id,
            "snippet": snippet,
            "status": {"privacyStatus": privacy},
        }]
    }


def make_builder_cohort(n_rows, *, positive_events=None):
    published = datetime.fromisoformat(PUBLISHED.replace("Z", "+00:00"))
    rows = []
    for index in range(n_rows):
        condition = 1 if index >= n_rows // 2 else 0
        capture = published + timedelta(seconds=4 * 60 * 60)
        decision = evaluate_sync_window(published, capture)
        assert decision.eligible is True
        outcome = 10 + (index % 5) + condition * 2
        if positive_events is not None and index >= positive_events:
            outcome = 0
        rows.append({
            "candidate_id": f"fixture-{index:03d}",
            "created_at": "2026-10-30T02:31:00Z",  # Deliberately not the publication anchor.
            "sync_elapsed_seconds": decision.elapsed_seconds,
            "outcome": outcome,
            "intercept": 1,
            "condition": condition,
        })
    return build_preregistered_cohort(
        rows,
        candidate_id_field="candidate_id",
        outcome_field="outcome",
        predictor_fields=("intercept", "condition"),
        sync_elapsed_seconds_field="sync_elapsed_seconds",
        sync_window=SyncWindow(
            lower_seconds=LOWER_SYNC_SECONDS,
            upper_seconds=UPPER_SYNC_SECONDS,
            lower_inclusive=True,
            upper_inclusive=True,
            missing_policy=MISSING_EXCLUDE,
        ),
        preregistered_masks={},
    )


def test_sync_t26_extracts_published_at_not_created_at():
    result = extract_published_at(youtube_resource(), expected_video_id=VIDEO_ID)
    assert result == datetime(2026, 10, 30, 2, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("value", "expected_code"),
    [
        (None, "MISSING_PUBLICATION_TIMESTAMP"),
        (..., "MISSING_PUBLICATION_TIMESTAMP"),
        ("not-a-timestamp", "INVALID_PUBLICATION_TIMESTAMP"),
        ("2026-10-30T02:30:00", "INVALID_PUBLICATION_TIMESTAMP"),
    ],
)
def test_sync_t26b_missing_or_malformed_published_at_is_row_level_exclusion(value, expected_code):
    with pytest.raises(ObservationExcluded) as exc:
        extract_published_at(youtube_resource(value), expected_video_id=VIDEO_ID)
    assert exc.value.code == expected_code
    assert exclusion_record("fixture-row-1", exc.value) == {
        "candidate_id": "fixture-row-1",
        "reasons": [expected_code],
    }


def test_sync_t26b_api_failure_is_not_mislabeled_as_missing_timestamp():
    with pytest.raises(YouTubeReadError, match="youtube_items_missing_or_invalid"):
        extract_published_at({"error": {"code": 403}}, expected_video_id=VIDEO_ID)
    with pytest.raises(YouTubeReadError, match="youtube_video_resource_missing"):
        extract_published_at({"items": []}, expected_video_id=VIDEO_ID)


def test_sync_t27_created_at_does_not_replace_publication_anchor():
    published = extract_published_at(youtube_resource(), expected_video_id=VIDEO_ID)
    captured = "2026-10-30T06:30:00Z"
    result = evaluate_sync_window(published, captured)
    assert result.eligible is True
    assert result.elapsed_seconds == 4 * 60 * 60


def test_sync_t28_lower_boundary_is_inclusive_exactly():
    result = evaluate_sync_window(PUBLISHED, "2026-10-30T05:30:00Z")
    assert result.eligible is True
    assert result.elapsed_seconds == LOWER_SYNC_SECONDS


def test_sync_t29_upper_boundary_is_inclusive_exactly():
    result = evaluate_sync_window(PUBLISHED, "2026-10-30T08:30:00Z")
    assert result.eligible is True
    assert result.elapsed_seconds == UPPER_SYNC_SECONDS


@pytest.mark.parametrize(
    "captured",
    ["2026-10-30T05:29:59Z", "2026-10-30T08:30:01Z"],
)
def test_sync_t30_values_outside_closed_window_are_excluded(captured):
    result = evaluate_sync_window(PUBLISHED, captured)
    assert result.eligible is False
    assert result.reason == "OUTSIDE_SYNC_WINDOW"


@pytest.mark.parametrize(
    ("value", "expected_code"),
    [
        (None, "MISSING_SYNC_TIMESTAMP"),
        ("bad-sync-time", "INVALID_SYNC_TIMESTAMP"),
        ("2026-10-30T06:30:00", "INVALID_SYNC_TIMESTAMP"),
    ],
)
def test_sync_t31_missing_or_invalid_capture_timestamp_is_excluded(value, expected_code):
    with pytest.raises(ObservationExcluded) as exc:
        parse_sync_captured_at(value)
    assert exc.value.code == expected_code


def test_sync_t32b_utc_to_ushuaia_handles_local_date_rollover():
    local = publication_datetime_ushuaia("2026-10-30T02:30:00Z")
    assert local.isoformat() == "2026-10-29T23:30:00-03:00"
    assert local.tzinfo.key == "America/Argentina/Ushuaia"


def test_sync_e2e_a_sufficient_synthetic_cohort_reaches_family_ii_estimator():
    cohort = make_builder_cohort(40)
    result = fit_ols_log_positive_hc3(
        cohort["outcomes"],
        cohort["design_matrix"],
        coefficient_index=1,
        eligible_mask=cohort["eligible_mask"],
        min_n_eff=30,
    )
    assert cohort["n_total"] == 40
    assert cohort["n_eff"] == 40
    assert cohort["n_events"] == 40
    assert result["status"] == "ESTIMABLE"
    assert result["metrics"]["covariance_type"] == "HC3"
    assert math.isfinite(result["metrics"]["effect_size"])
    assert math.isfinite(result["metrics"]["p_empirical"])


def test_sync_e2e_b_valid_but_insufficient_synthetic_cohort_returns_insufficient_power():
    cohort = make_builder_cohort(20, positive_events=20)
    result = fit_ols_log_positive_hc3(
        cohort["outcomes"],
        cohort["design_matrix"],
        coefficient_index=1,
        eligible_mask=cohort["eligible_mask"],
        min_n_eff=30,
    )
    assert cohort["n_total"] == 20
    assert cohort["n_eff"] == 20
    assert cohort["n_events"] == 20
    assert result["status"] == "INSUFFICIENT_POWER"
    assert result["metrics"]["insufficient_power_reason"] == "n_eff_below_minimum"
    assert result["bh_input_p"] == 1.0


def test_sync_t34_non_public_video_is_excluded_with_identity_and_cause():
    with pytest.raises(ObservationExcluded) as exc:
        extract_published_at(youtube_resource(privacy="unlisted"), expected_video_id=VIDEO_ID)
    assert exclusion_record("fixture-row-2", exc.value) == {
        "candidate_id": "fixture-row-2",
        "reasons": ["VIDEO_NOT_PUBLIC"],
    }
