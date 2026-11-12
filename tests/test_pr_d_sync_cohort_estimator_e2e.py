from datetime import datetime, timedelta, timezone

import math
import pytest

from labs.pr_d_cohort_builder import MISSING_EXCLUDE, SyncWindow, build_preregistered_cohort
from labs.pr_d_cohort_estimator import fit_eligible_cohort_hc3
from labs.pr_d_sync_contract import (
    LOWER_SYNC_SECONDS, UPPER_SYNC_SECONDS,
    evaluate_sync_window, extract_published_at, parse_sync_captured_at,
)

VIDEO_ID = "fixture-video-001"
PUBLISHED = "2026-10-30T02:30:00Z"


def _api_resource(video_id, views, published=PUBLISHED):
    return {
        "items": [
            {"id": "decoy", "snippet": {"publishedAt": "2026-10-30T01:00:00Z"},
             "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "999999"}},
            {"id": video_id, "snippet": {"publishedAt": published},
             "status": {"privacyStatus": "public"}, "statistics": {"viewCount": str(views)}},
        ]
    }


def _view_count(response, expected_video_id):
    matches = [item for item in response["items"] if item.get("id") == expected_video_id]
    if len(matches) != 1:
        raise ValueError("fixture_video_id_missing_or_ambiguous")
    raw = matches[0]["statistics"]["viewCount"]
    if not isinstance(raw, str) or not raw.isdecimal():
        raise ValueError("fixture_view_count_invalid")
    return int(raw)


def _build(n_rows, *, include_out_of_window=False):
    rows = []
    for i in range(n_rows):
        video_id = f"fixture-{i:03d}"
        publication_text = (
            datetime(2026, 10, 30, 2, 30, tzinfo=timezone.utc)
            + timedelta(days=i)
        ).isoformat().replace("+00:00", "Z")
        api = _api_resource(
            video_id, 20 + (i % 7) + (2 if i >= n_rows // 2 else 0),
            published=publication_text,
        )
        publication = extract_published_at(api, expected_video_id=video_id)
        captured = parse_sync_captured_at(
            (publication + timedelta(hours=3 if not (include_out_of_window and i == n_rows - 1) else 2)).isoformat()
        )
        decision = evaluate_sync_window(publication, captured)
        row = {
            "candidate_id": video_id,
            "sync_elapsed_seconds": decision.elapsed_seconds,
            "outcome": _view_count(api, video_id),
            "intercept": 1,
            "condition": 1 if i >= n_rows // 2 else 0,
        }
        if include_out_of_window and i == n_rows - 1:
            # The excluded candidate deliberately has no usable analytic fields.
            row.pop("outcome")
            row.pop("intercept")
            row.pop("condition")
        rows.append(row)
    return build_preregistered_cohort(
        rows,
        candidate_id_field="candidate_id",
        outcome_field="outcome",
        predictor_fields=("intercept", "condition"),
        sync_elapsed_seconds_field="sync_elapsed_seconds",
        sync_window=SyncWindow(
            lower_seconds=LOWER_SYNC_SECONDS, upper_seconds=UPPER_SYNC_SECONDS,
            lower_inclusive=True, upper_inclusive=True, missing_policy=MISSING_EXCLUDE,
        ),
        preregistered_masks={},
        temporal_anchor="publishedAt",
    )


def test_e12_api_to_eligibility_first_cohort_to_hc3_estimator():
    cohort = _build(40)
    assert cohort["n_total"] == 40
    assert cohort["n_eff"] == 40
    assert cohort["n_events"] == 40
    assert cohort["filter_provenance"]["lower_seconds"] == LOWER_SYNC_SECONDS == 10_500
    assert cohort["filter_provenance"]["upper_seconds"] == UPPER_SYNC_SECONDS == 11_100
    assert cohort["filter_provenance"]["lower_inclusive"] is True
    assert cohort["filter_provenance"]["upper_inclusive"] is True
    result = fit_eligible_cohort_hc3(cohort, coefficient_index=1, min_n_eff=30)
    assert result["status"] == "ESTIMABLE"
    assert result["metrics"]["covariance_type"] == "HC3"
    assert (result["metrics"]["n_total"], result["metrics"]["n_eff"], result["metrics"]["n_events"]) == (40, 40, 40)
    assert math.isfinite(result["metrics"]["effect_size"])


def test_excluded_none_placeholders_are_compacted_before_numpy_and_counts_preserved():
    cohort = _build(40, include_out_of_window=True)
    assert cohort["eligible_mask"] == [True] * 39 + [False]
    assert cohort["sync_elapsed_seconds"] == [10_800.0] * 39 + [7_200.0]
    assert cohort["outcomes"][-1] is None
    assert cohort["design_matrix"][-1] is None
    result = fit_eligible_cohort_hc3(cohort, coefficient_index=1, min_n_eff=30)
    assert result["status"] == "ESTIMABLE"
    assert (result["metrics"]["n_total"], result["metrics"]["n_eff"], result["metrics"]["n_events"]) == (40, 39, 39)


def test_insufficient_valid_cohort_never_becomes_favorable():
    cohort = _build(20)
    result = fit_eligible_cohort_hc3(cohort, coefficient_index=1, min_n_eff=30)
    assert result["status"] == "INSUFFICIENT_POWER"
    assert result["metrics"]["insufficient_power_reason"] == "n_eff_below_minimum"
    assert result["bh_input_p"] == 1.0


def test_adapter_rejects_non_null_analytic_values_on_excluded_rows():
    cohort = _build(40)
    cohort["outcomes"][-1] = 0.0
    cohort["design_matrix"][-1] = [1.0, 0.0]
    cohort["eligible_mask"][-1] = False
    cohort["n_eff"] = 39
    cohort["n_events"] = 39
    with pytest.raises(ValueError, match="excluded_analytic_placeholder_must_be_null"):
        fit_eligible_cohort_hc3(cohort, coefficient_index=1)


@pytest.mark.parametrize(
    ("elapsed", "expected_eligible"),
    [
        (timedelta(hours=3) - timedelta(minutes=5), True),
        (timedelta(hours=3) + timedelta(minutes=5), True),
        (timedelta(hours=3) - timedelta(minutes=5, microseconds=1), False),
        (timedelta(hours=3) + timedelta(minutes=5, microseconds=1), False),
    ],
)
def test_three_hour_target_with_closed_five_minute_tolerance(elapsed, expected_eligible):
    published = datetime.fromisoformat(PUBLISHED.replace("Z", "+00:00"))
    captured = published + elapsed
    decision = evaluate_sync_window(published, captured.isoformat())
    assert decision.eligible is expected_eligible
    assert decision.elapsed_seconds == elapsed.total_seconds()
    assert decision.reason is (None if expected_eligible else "OUTSIDE_SYNC_WINDOW")


def test_sync_window_normalizes_equivalent_timezone_offsets():
    published_utc = "2026-10-30T02:30:00Z"
    captured_with_offset = "2026-10-30T08:30:00+03:00"
    decision = evaluate_sync_window(published_utc, captured_with_offset)
    assert decision.eligible is True
    assert decision.elapsed_seconds == 3 * 60 * 60


@pytest.mark.parametrize(
    ("counts", "error"),
    [
        ((-1, 10, None, 10), "d_init_positive_count_out_of_range"),
        ((11, 10, None, 10), "d_init_positive_count_out_of_range"),
        ((1, 0, None, 10), "d_init_total_must_be_positive"),
        ((1, 10, None, 0), "d_init_total_must_be_positive"),
        ((True, 10, None, 10), "d_init_counts_must_be_integers"),
        ((1, 10, 2.0, 10), "d_init_counts_must_be_integers"),
    ],
)
def test_d_init_invalid_present_counts_are_not_hidden_by_missing_values(counts, error):
    from labs.pr_d_family_ii import compute_d_init

    with pytest.raises(ValueError, match=error):
        compute_d_init(*counts)


def test_d_init_returns_insufficient_only_after_validating_all_present_counts():
    from labs.pr_d_family_ii import compute_d_init

    assert compute_d_init(2, 10, None, 10) == {
        "d_init": None, "d_init_reason": "insufficient_data"
    }
    assert compute_d_init(None, None, 3, 10) == {
        "d_init": None, "d_init_reason": "insufficient_data"
    }


def test_duplicate_youtube_resource_id_is_rejected():
    from labs.pr_d_sync_contract import YouTubeReadError

    response = _api_resource(VIDEO_ID, 10)
    response["items"].append(response["items"][1].copy())
    with pytest.raises(YouTubeReadError, match="youtube_video_resource_ambiguous"):
        extract_published_at(response, expected_video_id=VIDEO_ID)


def test_publication_datetime_uses_iana_ushuaia_zone():
    from labs.pr_d_sync_contract import publication_datetime_ushuaia

    converted = publication_datetime_ushuaia("2026-10-30T02:30:00Z")
    assert converted.tzinfo is not None
    assert converted.tzinfo.key == "America/Argentina/Ushuaia"
    assert converted.hour == 23
