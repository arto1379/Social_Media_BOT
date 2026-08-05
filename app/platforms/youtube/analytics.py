"""
Statistics collection.

Numbers come from two different APIs and are merged into one
:class:`VideoMetrics` per video:

* **Data API v3** (`videos.list`) - views, likes, comments, favourites. Cheap
  (1 quota unit for up to 50 videos) and available for every channel.
* **Analytics API v2** (`reports.query`) - watch time, average view percentage,
  subscribers gained and estimated revenue. Only the channel owner can read it,
  and revenue additionally needs the monetary scope plus a monetised channel.

The Analytics part is best-effort on purpose: a brand new channel has no
analytics rows at all, and that must not stop view counts from being recorded.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Iterable

from app.platforms.base import ChannelMetrics, PlatformError, VideoMetrics
from app.platforms.youtube import auth
from app.platforms.youtube.client import (
    build_analytics_service,
    build_data_service,
    execute,
)

log = logging.getLogger(__name__)

# videos.list accepts at most 50 ids per call.
DATA_API_BATCH = 50
# The Analytics API accepts at most 500 ids in a filter, but keeping batches
# aligned with the Data API keeps the merge logic simple.
ANALYTICS_BATCH = 50

MONETARY_SCOPE = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"


def _to_int(value: Any) -> int:
    """API counters arrive as strings; missing ones as None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    """Split *items* into lists of at most *size* elements."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


# ---------------------------------------------------------------------------
# Public statistics (Data API)
# ---------------------------------------------------------------------------
def fetch_public_stats(
    credentials_blob: dict[str, Any], remote_ids: list[str]
) -> dict[str, VideoMetrics]:
    """Views/likes/comments for each id, keyed by video id."""
    if not remote_ids:
        return {}

    service = build_data_service(credentials_blob)
    results: dict[str, VideoMetrics] = {}

    for batch in _chunks(remote_ids, DATA_API_BATCH):
        response = execute(
            service.videos().list(part="statistics", id=",".join(batch)),
            "reading video statistics",
        )
        for item in response.get("items", []):
            stats = item.get("statistics", {})
            results[item["id"]] = VideoMetrics(
                remote_id=item["id"],
                views=_to_int(stats.get("viewCount")),
                likes=_to_int(stats.get("likeCount")),
                comments=_to_int(stats.get("commentCount")),
                favorites=_to_int(stats.get("favoriteCount")),
            )
    return results


# ---------------------------------------------------------------------------
# Owner analytics (Analytics API)
# ---------------------------------------------------------------------------
def enrich_with_analytics(
    credentials_blob: dict[str, Any],
    metrics_by_id: dict[str, VideoMetrics],
    days: int = 365,
) -> None:
    """
    Add watch time, subscribers gained and revenue to *metrics_by_id* in place.

    Failures are logged and swallowed: analytics are a bonus on top of the
    public counters, never a reason to lose a collection run.
    """
    if not metrics_by_id:
        return

    wants_revenue = auth.has_scope(credentials_blob, MONETARY_SCOPE)
    metrics = ["estimatedMinutesWatched", "averageViewPercentage", "subscribersGained"]
    if wants_revenue:
        metrics.append("estimatedRevenue")

    # The Analytics API needs an explicit window; "since the channel started"
    # is approximated with a generous lookback.
    end = date.today()
    start = end - timedelta(days=days)

    try:
        service = build_analytics_service(credentials_blob)
    except PlatformError as exc:
        log.warning("Analytics client unavailable: %s", exc)
        return

    for batch in _chunks(list(metrics_by_id), ANALYTICS_BATCH):
        try:
            response = execute(
                service.reports().query(
                    ids="channel==MINE",
                    startDate=start.isoformat(),
                    endDate=end.isoformat(),
                    metrics=",".join(metrics),
                    dimensions="video",
                    filters="video==" + ",".join(batch),
                    maxResults=len(batch),
                ),
                "reading analytics report",
            )
        except PlatformError as exc:
            # Most common cause: the monetary scope was not granted, or the
            # channel has no analytics data yet. Retry once without revenue.
            if wants_revenue:
                log.info("Revenue metrics unavailable (%s); retrying without them.", exc)
                wants_revenue = False
                metrics = [m for m in metrics if m != "estimatedRevenue"]
                try:
                    response = execute(
                        service.reports().query(
                            ids="channel==MINE",
                            startDate=start.isoformat(),
                            endDate=end.isoformat(),
                            metrics=",".join(metrics),
                            dimensions="video",
                            filters="video==" + ",".join(batch),
                            maxResults=len(batch),
                        ),
                        "reading analytics report",
                    )
                except PlatformError as inner:
                    log.warning("Analytics unavailable for this batch: %s", inner)
                    continue
            else:
                log.warning("Analytics unavailable for this batch: %s", exc)
                continue

        # Rows are positional: column 0 is the "video" dimension, the rest
        # follow the order of the requested metrics.
        headers = [col["name"] for col in response.get("columnHeaders", [])]
        for row in response.get("rows", []) or []:
            row_map = dict(zip(headers, row))
            video_id = row_map.get("video")
            target = metrics_by_id.get(video_id)
            if target is None:
                continue
            target.watch_time_minutes = float(row_map.get("estimatedMinutesWatched") or 0)
            avg = row_map.get("averageViewPercentage")
            target.average_view_percentage = float(avg) if avg is not None else None
            revenue = row_map.get("estimatedRevenue")
            if revenue is not None:
                target.estimated_revenue = float(revenue)
                target.currency = "USD"  # the API always reports in USD


def fetch_video_metrics(
    credentials_blob: dict[str, Any], remote_ids: Iterable[str]
) -> list[VideoMetrics]:
    """Public counters plus owner analytics for every id."""
    ids = [rid for rid in remote_ids if rid]
    if not ids:
        return []
    metrics_by_id = fetch_public_stats(credentials_blob, ids)
    enrich_with_analytics(credentials_blob, metrics_by_id)
    return list(metrics_by_id.values())


# ---------------------------------------------------------------------------
# Channel level
# ---------------------------------------------------------------------------
def fetch_channel_metrics(credentials_blob: dict[str, Any]) -> ChannelMetrics:
    """Subscribers, lifetime views and video count for the connected channel."""
    service = build_data_service(credentials_blob)
    response = execute(
        service.channels().list(part="statistics,snippet", mine=True),
        "reading channel statistics",
    )
    items = response.get("items", [])
    if not items:
        raise PlatformError("The connected Google account has no YouTube channel.")

    channel = items[0]
    stats = channel.get("statistics", {})
    result = ChannelMetrics(
        remote_id=channel["id"],
        views=_to_int(stats.get("viewCount")),
        subscribers=_to_int(stats.get("subscriberCount")),
        video_count=_to_int(stats.get("videoCount")),
    )

    # Watch time and revenue are owner-only; treat them as optional extras.
    try:
        analytics = build_analytics_service(credentials_blob)
        end = date.today()
        start = end - timedelta(days=28)
        wanted = ["estimatedMinutesWatched"]
        if auth.has_scope(credentials_blob, MONETARY_SCOPE):
            wanted.append("estimatedRevenue")
        response = execute(
            analytics.reports().query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics=",".join(wanted),
            ),
            "reading channel analytics",
        )
        rows = response.get("rows") or []
        if rows:
            headers = [col["name"] for col in response.get("columnHeaders", [])]
            row_map = dict(zip(headers, rows[0]))
            result.watch_time_minutes = float(row_map.get("estimatedMinutesWatched") or 0)
            if "estimatedRevenue" in row_map:
                result.estimated_revenue = float(row_map["estimatedRevenue"] or 0)
                result.currency = "USD"
    except PlatformError as exc:
        log.info("Channel analytics unavailable: %s", exc)

    return result


def fetch_channel_identity(credentials_blob: dict[str, Any]) -> dict[str, Any]:
    """Channel id, title and handle - used right after connecting an account."""
    service = build_data_service(credentials_blob)
    response = execute(
        service.channels().list(part="snippet,contentDetails", mine=True),
        "identifying channel",
    )
    items = response.get("items", [])
    if not items:
        raise PlatformError(
            "This Google account has no YouTube channel. Create one at "
            "youtube.com first, then connect again."
        )
    channel = items[0]
    snippet = channel.get("snippet", {})
    return {
        "id": channel["id"],
        "title": snippet.get("title", "YouTube channel"),
        "handle": snippet.get("customUrl", ""),
        "raw": channel,
    }
