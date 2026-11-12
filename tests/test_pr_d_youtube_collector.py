import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from labs.pr_d_youtube_collector import (
    UINT64_MAX,
    YouTubeObservation,
    collect_public_video_observation,
    parse_video_observation,
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
