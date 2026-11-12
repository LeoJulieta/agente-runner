import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from labs.pr_d_youtube_collector import (
    UINT64_MAX,
    YouTubeObservation,
    collect_public_video_observation,
    collect_public_video_observations_batch,
    parse_video_observation,
    parse_video_observations_batch,
)
from labs.pr_d_sync_contract import ObservationExcluded, YouTubeReadError


VIDEO_ID = "abc123"
PUBLISHED = "2026-10-30T02:30:00Z"
CAPTURED = datetime(2026, 10, 30, 5, 30, tzinfo=timezone.utc)


def resource(*, video_id=VIDEO_ID, views="123", privacy="public", published=PUBLISHED):
    return {"items": [{
        "id": video_id,
        "snippet": {"publishedAt": published},
        "status": {"privacyStatus": privacy},
        "statistics": {"viewCount": views},
    }]}


class FakeResponse:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]


def test_parse_observation_derives_elapsed_and_preserves_exact_counter():
    result = parse_video_observation(
        resource(views="18446744073709551615"),
        expected_video_id=VIDEO_ID,
        sync_captured_at=CAPTURED,
    )
    assert isinstance(result, YouTubeObservation)
    assert result.view_count == UINT64_MAX
    assert result.elapsed_seconds == 10800
    assert result.eligible is True
    assert result.published_at.isoformat() == "2026-10-30T02:30:00+00:00"


@pytest.mark.parametrize("raw", [None, True, 1.5, "-1", "", " 1", "18446744073709551616"])
def test_invalid_view_count_is_rejected(raw):
    with pytest.raises(YouTubeReadError):
        parse_video_observation(resource(views=raw), expected_video_id=VIDEO_ID, sync_captured_at=CAPTURED)


def test_private_video_is_excluded():
    with pytest.raises(ObservationExcluded, match="VIDEO_NOT_PUBLIC"):
        parse_video_observation(resource(privacy="unlisted"), expected_video_id=VIDEO_ID, sync_captured_at=CAPTURED)


def test_mismatched_or_missing_video_id_is_rejected():
    with pytest.raises(YouTubeReadError, match="youtube_video_resource_missing"):
        parse_video_observation(resource(video_id="different"), expected_video_id=VIDEO_ID, sync_captured_at=CAPTURED)


def test_out_of_window_observation_is_returned_but_marked_ineligible():
    result = parse_video_observation(
        resource(),
        expected_video_id=VIDEO_ID,
        sync_captured_at=datetime(2026, 10, 30, 4, 30, tzinfo=timezone.utc),
    )
    assert result.eligible is False
    assert result.exclusion_reason == "OUTSIDE_SYNC_WINDOW"
    assert result.elapsed_seconds == 7200


def test_http_collector_requests_exact_id_and_captures_clock_after_body():
    observed = []
    def opener(request, timeout):
        observed.append((request, timeout))
        return FakeResponse(json.dumps(resource(views="2147483648")).encode())
    result = collect_public_video_observation(
        VIDEO_ID, api_key="test-secret",
        opener=opener,
        clock=lambda: CAPTURED,
    )
    request, timeout = observed[0]
    query = parse_qs(urlparse(request.full_url).query)
    assert query["id"] == [VIDEO_ID]
    assert query["part"] == ["snippet,statistics,status"]
    assert query["key"] == ["test-secret"]
    assert timeout == 10.0
    assert result.view_count == 2147483648


def test_http_collector_rejects_oversized_response_body():
    def opener(request, timeout):
        return FakeResponse(b"x" * (1024 * 1024 + 1))
    with pytest.raises(YouTubeReadError, match="youtube_api_response_too_large"):
        collect_public_video_observation(
            VIDEO_ID, api_key="test-secret", opener=opener, clock=lambda: CAPTURED
        )


def test_batch_parser_accepts_multiple_videos_and_preserves_row_exclusions():
    payload = {
        "items": [
            {
                "id": "video-a",
                "snippet": {"publishedAt": PUBLISHED},
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "100"},
            },
            {
                "id": "video-b",
                "snippet": {"publishedAt": PUBLISHED},
                "status": {"privacyStatus": "private"},
                "statistics": {"viewCount": "200"},
            },
            {
                "id": "video-c",
                "snippet": {"publishedAt": "2026-10-30T00:30:00Z"},
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "300"},
            },
        ]
    }
    observations, excluded = parse_video_observations_batch(
        payload,
        expected_video_ids=["video-a", "video-b", "video-c", "video-missing"],
        sync_captured_at=CAPTURED,
    )
    assert observations["video-a"].eligible is True
    assert observations["video-a"].view_count == 100
    assert excluded["video-b"] == "VIDEO_NOT_PUBLIC"
    assert observations["video-c"].eligible is False
    assert observations["video-c"].exclusion_reason == "OUTSIDE_SYNC_WINDOW"
    assert excluded["video-missing"] == "youtube_video_resource_missing"


def test_batch_parser_rejects_duplicate_response_resource_for_that_video():
    payload = {"items": [resource()["items"][0], resource()["items"][0]]}
    observations, excluded = parse_video_observations_batch(
        payload,
        expected_video_ids=[VIDEO_ID],
        sync_captured_at=CAPTURED,
    )
    assert observations == {}
    assert excluded[VIDEO_ID] == "youtube_video_resource_ambiguous"


def test_batch_parser_rejects_duplicate_or_invalid_requested_ids():
    with pytest.raises(ValueError, match="youtube_video_ids_duplicate"):
        parse_video_observations_batch(
            {}, expected_video_ids=["same", "same"], sync_captured_at=CAPTURED
        )
    with pytest.raises(ValueError, match="youtube_video_id_invalid"):
        parse_video_observations_batch(
            {}, expected_video_ids=[""], sync_captured_at=CAPTURED
        )
    with pytest.raises(ValueError, match="youtube_batch_limit_exceeded"):
        parse_video_observations_batch(
            {}, expected_video_ids=[f"id-{i}" for i in range(51)], sync_captured_at=CAPTURED
        )


def test_http_batch_collector_uses_one_request_and_one_capture_instant():
    observed = []
    payload = {
        "items": [
            {
                "id": "video-a",
                "snippet": {"publishedAt": PUBLISHED},
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "2147483648"},
            },
            {
                "id": "video-b",
                "snippet": {"publishedAt": PUBLISHED},
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "42"},
            },
        ]
    }

    def opener(request, timeout):
        observed.append((request, timeout))
        return FakeResponse(json.dumps(payload).encode())

    observations, excluded = collect_public_video_observations_batch(
        ["video-a", "video-b"],
        api_key="test-secret",
        opener=opener,
        clock=lambda: CAPTURED,
    )
    request, timeout = observed[0]
    query = parse_qs(urlparse(request.full_url).query)
    assert len(observed) == 1
    assert query["id"] == ["video-a,video-b"]
    assert query["part"] == ["snippet,statistics,status"]
    assert query["key"] == ["test-secret"]
    assert timeout == 15.0
    assert excluded == {}
    assert observations["video-a"].view_count == 2147483648
    assert observations["video-a"].sync_captured_at == CAPTURED
    assert observations["video-b"].sync_captured_at == CAPTURED


def test_http_batch_collector_rejects_invalid_batch_and_oversized_response():
    def opener(request, timeout):
        return FakeResponse(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="youtube_video_ids_duplicate"):
        collect_public_video_observations_batch(
            ["same", "same"], api_key="test-secret", opener=opener, clock=lambda: CAPTURED
        )
    with pytest.raises(YouTubeReadError, match="youtube_api_response_too_large"):
        collect_public_video_observations_batch(
            ["video-a"], api_key="test-secret", opener=opener, clock=lambda: CAPTURED
        )
