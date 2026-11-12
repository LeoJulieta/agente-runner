"""Read-only YouTube videos.list collector for candidate E12 observations.

No credentials are read from the environment and no persistence occurs here.
The caller supplies an API key at runtime; errors never include the request URL.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from labs.pr_d_sync_contract import (
    ObservationExcluded,
    YouTubeReadError,
    evaluate_sync_window,
    extract_published_at,
)

YOUTUBE_VIDEOS_LIST_URL = "https://www.googleapis.com/youtube/v3/videos"
UINT64_MAX = (1 << 64) - 1
MAX_RESPONSE_BYTES = 1024 * 1024
_VIEW_COUNT_RE = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class YouTubeObservation:
    video_id: str
    published_at: datetime
    sync_captured_at: datetime
    view_count: int
    elapsed_seconds: float
    eligible: bool
    exclusion_reason: str | None
    source: str = "youtube_data_api_v3_videos_list"


def _parse_view_count(resource: dict[str, Any]) -> int:
    statistics = resource.get("statistics")
    if not isinstance(statistics, dict):
        raise YouTubeReadError("youtube_statistics_missing")
    raw = statistics.get("viewCount")
    # Google serializes unsigned-long counters as decimal strings. Reject
    # floats and booleans to avoid precision loss or Python bool/int confusion.
    if not isinstance(raw, str) or not _VIEW_COUNT_RE.fullmatch(raw):
        raise YouTubeReadError("youtube_view_count_invalid")
    value = int(raw, 10)
    if value > UINT64_MAX:
        raise YouTubeReadError("youtube_view_count_out_of_uint64_range")
    return value


def parse_video_observation(
    response: Any,
    *,
    expected_video_id: str,
    sync_captured_at: datetime,
) -> YouTubeObservation:
    """Validate one videos.list resource and derive elapsed from source times."""
    published_at = extract_published_at(response, expected_video_id=expected_video_id)
    items = response["items"]
    resource = next(item for item in items if isinstance(item, dict) and item.get("id") == expected_video_id)
    view_count = _parse_view_count(resource)
    if sync_captured_at.tzinfo is None or sync_captured_at.utcoffset() is None:
        raise YouTubeReadError("youtube_capture_clock_not_timezone_aware")
    captured_utc = sync_captured_at.astimezone(timezone.utc)
    decision = evaluate_sync_window(published_at, captured_utc)
    return YouTubeObservation(
        video_id=expected_video_id,
        published_at=published_at,
        sync_captured_at=captured_utc,
        view_count=view_count,
        elapsed_seconds=decision.elapsed_seconds,
        eligible=decision.eligible,
        exclusion_reason=decision.reason,
    )


def collect_public_video_observation(
    video_id: str,
    *,
    api_key: str,
    opener: Callable[..., Any] = urlopen,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    timeout_seconds: float = 10.0,
) -> YouTubeObservation:
    """Fetch a single public video and timestamp the received statistics.

    The capture clock is sampled immediately after the HTTP response body is
    read, before JSON parsing. API keys are sent only as HTTPS query parameters
    and are never included in raised exception messages.
    """
    if not isinstance(video_id, str) or not video_id.strip():
        raise ValueError("youtube_video_id_invalid")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("youtube_api_key_required")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("youtube_timeout_invalid")

    query = urlencode({
        "part": "snippet,statistics,status",
        "id": video_id,
        "key": api_key,
    })
    request = Request(
        f"{YOUTUBE_VIDEOS_LIST_URL}?{query}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            captured_at = clock()
        if len(body) > MAX_RESPONSE_BYTES:
            raise YouTubeReadError("youtube_api_response_too_large")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise YouTubeReadError(f"youtube_api_transport_error:{type(exc).__name__}") from None

    try:
        payload = json.loads(body)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise YouTubeReadError("youtube_api_json_invalid") from None
    return parse_video_observation(
        payload,
        expected_video_id=video_id,
        sync_captured_at=captured_at,
    )


def parse_video_observations_batch(
    response: Any,
    *,
    expected_video_ids: list[str],
    sync_captured_at: datetime,
) -> tuple[dict[str, YouTubeObservation], dict[str, str]]:
    """Parse a videos.list batch into accepted observations and row exclusions.

    A malformed individual resource excludes only that video. A malformed
    top-level response rejects the batch because no row-level provenance can
    be trusted. Duplicate requested IDs are rejected before parsing.
    """
    if not isinstance(expected_video_ids, list) or not expected_video_ids:
        raise ValueError("youtube_video_ids_required")
    if len(expected_video_ids) > 50:
        raise ValueError("youtube_batch_limit_exceeded")
    if any(not isinstance(video_id, str) or not video_id.strip() for video_id in expected_video_ids):
        raise ValueError("youtube_video_id_invalid")
    if len(set(expected_video_ids)) != len(expected_video_ids):
        raise ValueError("youtube_video_ids_duplicate")
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        raise YouTubeReadError("youtube_items_missing_or_invalid")

    observations: dict[str, YouTubeObservation] = {}
    excluded: dict[str, str] = {}
    for video_id in expected_video_ids:
        try:
            observations[video_id] = parse_video_observation(
                response,
                expected_video_id=video_id,
                sync_captured_at=sync_captured_at,
            )
        except ObservationExcluded as exc:
            excluded[video_id] = exc.code
        except YouTubeReadError as exc:
            excluded[video_id] = str(exc)
    return observations, excluded


def collect_public_video_observations_batch(
    video_ids: list[str],
    *,
    api_key: str,
    opener: Callable[..., Any] = urlopen,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    timeout_seconds: float = 15.0,
) -> tuple[dict[str, YouTubeObservation], dict[str, str]]:
    """Fetch up to 50 public videos in one call and timestamp the received body."""
    if not isinstance(video_ids, list) or not video_ids:
        raise ValueError("youtube_video_ids_required")
    if len(video_ids) > 50:
        raise ValueError("youtube_batch_limit_exceeded")
    if any(not isinstance(video_id, str) or not video_id.strip() for video_id in video_ids):
        raise ValueError("youtube_video_id_invalid")
    if len(set(video_ids)) != len(video_ids):
        raise ValueError("youtube_video_ids_duplicate")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("youtube_api_key_required")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("youtube_timeout_invalid")

    query = urlencode({
        "part": "snippet,statistics,status",
        "id": ",".join(video_ids),
        "key": api_key,
    })
    request = Request(
        f"{YOUTUBE_VIDEOS_LIST_URL}?{query}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            captured_at = clock()
        if len(body) > MAX_RESPONSE_BYTES:
            raise YouTubeReadError("youtube_api_response_too_large")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise YouTubeReadError(f"youtube_api_transport_error:{type(exc).__name__}") from None

    try:
        payload = json.loads(body)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise YouTubeReadError("youtube_api_json_invalid") from None
    return parse_video_observations_batch(
        payload,
        expected_video_ids=video_ids,
        sync_captured_at=captured_at,
    )
