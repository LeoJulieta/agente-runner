"""Pure temporal provenance and eligibility helpers for PR D synthetic fixtures.

This module performs no YouTube API calls, database access, persistence,
environment reads, or production orchestration. It validates fixture-shaped
API resources and produces elapsed seconds for the isolated cohort builder.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


LOWER_SYNC_SECONDS = 3 * 60 * 60
UPPER_SYNC_SECONDS = 6 * 60 * 60
USHUAIA_ZONE = "America/Argentina/Ushuaia"


class ObservationExcluded(ValueError):
    """A single video/capture is ineligible for a stable, auditable reason."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class YouTubeReadError(RuntimeError):
    """The API response/resource cannot support a row-level data decision."""


@dataclass(frozen=True)
class SyncEligibility:
    eligible: bool
    elapsed_seconds: float
    reason: str | None


def _parse_aware_timestamp(value: Any, *, missing_code: str, invalid_code: str) -> datetime:
    if value is None:
        raise ObservationExcluded(missing_code)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            text = value.strip()
            if not text:
                raise ValueError("empty_timestamp")
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        except (TypeError, ValueError, OverflowError):
            raise ObservationExcluded(invalid_code) from None
    else:
        raise ObservationExcluded(invalid_code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ObservationExcluded(invalid_code)
    try:
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ObservationExcluded(invalid_code) from None


def extract_published_at(
    videos_list_response: Mapping[str, Any],
    *,
    expected_video_id: str,
) -> datetime:
    """Extract the publication instant from a complete videos.list response.

    API/read failures are deliberately distinct from an individual resource
    whose snippet exists but has a missing or malformed publishedAt field.
    """
    if not isinstance(videos_list_response, Mapping):
        raise YouTubeReadError("youtube_response_invalid")
    items = videos_list_response.get("items")
    if not isinstance(items, list):
        raise YouTubeReadError("youtube_items_missing_or_invalid")
    if not isinstance(expected_video_id, str) or not expected_video_id.strip():
        raise ValueError("expected_video_id_invalid")

    resource = next(
        (item for item in items if isinstance(item, Mapping) and item.get("id") == expected_video_id),
        None,
    )
    if resource is None:
        raise YouTubeReadError("youtube_video_resource_missing")

    status = resource.get("status")
    snippet = resource.get("snippet")
    if not isinstance(status, Mapping) or not isinstance(snippet, Mapping):
        raise YouTubeReadError("youtube_video_resource_incomplete")
    if status.get("privacyStatus") != "public":
        raise ObservationExcluded("VIDEO_NOT_PUBLIC")

    return _parse_aware_timestamp(
        snippet.get("publishedAt"),
        missing_code="MISSING_PUBLICATION_TIMESTAMP",
        invalid_code="INVALID_PUBLICATION_TIMESTAMP",
    )


def parse_sync_captured_at(value: Any) -> datetime:
    """Parse the UTC instant at which the statistics were actually observed."""
    return _parse_aware_timestamp(
        value,
        missing_code="MISSING_SYNC_TIMESTAMP",
        invalid_code="INVALID_SYNC_TIMESTAMP",
    )


def evaluate_sync_window(published_at: Any, sync_captured_at: Any) -> SyncEligibility:
    """Evaluate the closed [3 h, 6 h] window using exact timedelta boundaries."""
    published = _parse_aware_timestamp(
        published_at,
        missing_code="MISSING_PUBLICATION_TIMESTAMP",
        invalid_code="INVALID_PUBLICATION_TIMESTAMP",
    )
    captured = parse_sync_captured_at(sync_captured_at)
    elapsed = captured - published
    elapsed_seconds = elapsed.total_seconds()
    eligible = timedelta(seconds=LOWER_SYNC_SECONDS) <= elapsed <= timedelta(seconds=UPPER_SYNC_SECONDS)
    return SyncEligibility(
        eligible=eligible,
        elapsed_seconds=elapsed_seconds,
        reason=None if eligible else "OUTSIDE_SYNC_WINDOW",
    )


def publication_datetime_ushuaia(published_at: Any) -> datetime:
    """Convert a publication instant to Ushuaia civil time using IANA tz data."""
    published = _parse_aware_timestamp(
        published_at,
        missing_code="MISSING_PUBLICATION_TIMESTAMP",
        invalid_code="INVALID_PUBLICATION_TIMESTAMP",
    )
    try:
        zone = ZoneInfo(USHUAIA_ZONE)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError("ushuaia_timezone_database_unavailable") from exc
    return published.astimezone(zone)
