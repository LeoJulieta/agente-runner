"""Full synthetic E2E: YouTube API video + viewCount -> temporal eligibility -> cohort -> Family II."""
from labs.pr_d_cohort_builder import MISSING_EXCLUDE, SyncWindow, build_preregistered_cohort
from labs.pr_d_family_ii import fit_ols_log_positive_hc3
from labs.pr_d_sync_contract import LOWER_SYNC_SECONDS, UPPER_SYNC_SECONDS, evaluate_sync_window, extract_published_at, parse_sync_captured_at


def _extract_view_count(api_response: dict, *, expected_video_id: str) -> int:
    """Read statistics.viewCount only from the exact API resource under test."""
    items = api_response.get("items")
    if not isinstance(items, list):
        raise AssertionError("fixture_api_items_invalid")
    matches = [item for item in items if isinstance(item, dict) and item.get("id") == expected_video_id]
    if len(matches) != 1:
        raise AssertionError("fixture_video_id_missing_or_ambiguous")
    statistics = matches[0].get("statistics")
    if not isinstance(statistics, dict):
        raise AssertionError("fixture_statistics_missing")
    raw = statistics.get("viewCount")
    if not isinstance(raw, str) or not raw.isdecimal():
        raise AssertionError("fixture_view_count_invalid")
    return int(raw)


def _run_full_pipeline(n_rows: int):
    rows = []
    for index in range(n_rows):
        video_id = f"api-fixture-{index:03d}"
        condition = 1 if index >= n_rows // 2 else 0
        # A decoy resource comes first: both timestamps and outcome must bind
        # to the requested video_id, not merely to the first API item.
        view_count = 10 + (index % 5) + 2 * condition
        api_response = {
            "items": [
                {
                    "id": f"decoy-{video_id}",
                    "snippet": {"publishedAt": "2026-10-30T01:00:00Z"},
                    "status": {"privacyStatus": "public"},
                    "statistics": {"viewCount": "999999"},
                },
                {
                    "id": video_id,
                    "snippet": {"publishedAt": "2026-10-30T02:30:00Z"},
                    "status": {"privacyStatus": "public"},
                    "statistics": {"viewCount": str(view_count)},
                },
            ]
        }
        published_at = extract_published_at(api_response, expected_video_id=video_id)
        outcome = _extract_view_count(api_response, expected_video_id=video_id)
        captured_at = parse_sync_captured_at("2026-10-30T06:30:00Z")
        temporal = evaluate_sync_window(published_at, captured_at)
        assert temporal.eligible is True
        rows.append({
            "candidate_id": video_id,
            "created_at": "2026-10-30T02:31:00Z",
            "published_at": published_at.isoformat(),
            "sync_captured_at": captured_at.isoformat(),
            "sync_elapsed_seconds": temporal.elapsed_seconds,
            "outcome": outcome,
            "api_view_count": outcome,
            "intercept": 1,
            "condition": condition,
        })
    cohort = build_preregistered_cohort(
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
    estimate = fit_ols_log_positive_hc3(
        cohort["outcomes"],
        cohort["design_matrix"],
        coefficient_index=1,
        eligible_mask=cohort["eligible_mask"],
        min_n_eff=30,
    )
    return rows, cohort, estimate


def test_sync_full_e2e_api_view_count_by_video_id_to_family_ii_estimator():
    rows, cohort, estimate = _run_full_pipeline(40)
    assert len(rows) == 40
    assert all(row["published_at"] != row["created_at"] for row in rows)
    assert all(row["sync_elapsed_seconds"] == 4 * 60 * 60 for row in rows)
    assert all(row["outcome"] == row["api_view_count"] for row in rows)
    assert rows[0]["outcome"] == 10
    assert rows[-1]["outcome"] == 16
    assert (cohort["n_total"], cohort["n_eff"], cohort["n_events"]) == (40, 40, 40)
    assert estimate["status"] == "ESTIMABLE"
    assert estimate["metrics"]["covariance_type"] == "HC3"
    assert (estimate["metrics"]["n_eff"], estimate["metrics"]["n_events"]) == (40, 40)


def test_sync_full_e2e_insufficient_api_view_count_cohort_never_becomes_favorable():
    rows, cohort, estimate = _run_full_pipeline(20)
    assert len(rows) == 20
    assert all(row["outcome"] == row["api_view_count"] for row in rows)
    assert (cohort["n_total"], cohort["n_eff"]) == (20, 20)
    assert estimate["status"] == "INSUFFICIENT_POWER"
    assert estimate["metrics"]["insufficient_power_reason"] == "n_eff_below_minimum"
    assert estimate["bh_input_p"] == 1.0
