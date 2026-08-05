"""
Statistics collection and aggregation.

Collection appends a new :class:`StatSnapshot` per video per run rather than
overwriting a counter. That costs a little disk and buys everything else: a
growth curve, "views in the last 7 days", and an audit of when a number
changed. Because the table is platform-neutral, the dashboard totals already
work for whatever platform is added next - the PRD's "statistics of views over
all social medias that support it".
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.extensions import db
from app.models import (
    PlatformAccount,
    StatSnapshot,
    UploadJob,
    UploadStatus,
    Video,
)
from app.platforms import PlatformError, get_adapter
from app.services import account_service

log = logging.getLogger(__name__)

# Videos published within this window are refreshed on every run; older ones
# barely move, so refreshing them constantly just burns API quota.
HOT_WINDOW_DAYS = 30
# Cap on how many videos one collection pass will ask about per account.
MAX_VIDEOS_PER_RUN = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
def _published_jobs(account: PlatformAccount, hot_only: bool = True) -> list[UploadJob]:
    """Successful uploads for this account that have a platform id."""
    query = db.session.query(UploadJob).filter(
        UploadJob.account_id == account.id,
        UploadJob.status == UploadStatus.SUCCEEDED,
        UploadJob.remote_id.isnot(None),
    )
    if hot_only:
        cutoff = _utcnow() - timedelta(days=HOT_WINDOW_DAYS)
        query = query.filter(UploadJob.finished_at >= cutoff)
    return query.order_by(UploadJob.finished_at.desc()).limit(MAX_VIDEOS_PER_RUN).all()


def collect_for_account(account: PlatformAccount, hot_only: bool = True) -> dict:
    """
    Refresh statistics for one account.

    Returns a summary dict. Errors are recorded on the account and returned
    rather than raised, so one broken connection does not stop the others.
    """
    jobs = _published_jobs(account, hot_only=hot_only)
    result = {"account": account.display_name, "videos": 0, "error": None}

    try:
        credentials = account_service.credentials_for(account)
        adapter = get_adapter(account.platform)

        # --- Channel level ---------------------------------------------
        channel = adapter.fetch_channel_metrics(credentials)
        db.session.add(
            StatSnapshot(
                platform=account.platform,
                account_id=account.id,
                video_id=None,
                remote_id=channel.remote_id,
                views=channel.views,
                subscribers_gained=channel.subscribers,
                watch_time_minutes=channel.watch_time_minutes,
                estimated_revenue=channel.estimated_revenue,
                currency=channel.currency,
            )
        )

        # --- Per video --------------------------------------------------
        if jobs:
            by_remote_id = {job.remote_id: job for job in jobs}
            metrics = adapter.fetch_video_metrics(credentials, list(by_remote_id))
            for entry in metrics:
                job = by_remote_id.get(entry.remote_id)
                db.session.add(
                    StatSnapshot(
                        platform=account.platform,
                        account_id=account.id,
                        video_id=job.video_id if job else None,
                        remote_id=entry.remote_id,
                        views=entry.views,
                        likes=entry.likes,
                        comments=entry.comments,
                        shares=entry.shares,
                        favorites=entry.favorites,
                        watch_time_minutes=entry.watch_time_minutes,
                        average_view_percentage=entry.average_view_percentage,
                        estimated_revenue=entry.estimated_revenue,
                        currency=entry.currency,
                    )
                )
            result["videos"] = len(metrics)

        db.session.commit()
        account_service.clear_error(account)

    except PlatformError as exc:
        db.session.rollback()
        account_service.mark_error(account, str(exc))
        result["error"] = str(exc)
        log.warning("Statistics collection failed for %s: %s", account.display_name, exc)
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        result["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("Unexpected error collecting statistics for %s", account.display_name)

    return result


def collect_all(hot_only: bool = True) -> dict:
    """Refresh statistics for every connected account."""
    accounts = account_service.usable_accounts()
    if not accounts:
        return {"accounts": 0, "videos": 0, "results": []}

    results = [collect_for_account(account, hot_only=hot_only) for account in accounts]
    total_videos = sum(entry["videos"] for entry in results)
    log.info(
        "Statistics collected for %s account(s), %s video(s).", len(results), total_videos
    )
    return {"accounts": len(results), "videos": total_videos, "results": results}


# ---------------------------------------------------------------------------
# Aggregation for the UI
# ---------------------------------------------------------------------------
def latest_video_stats() -> dict[int, StatSnapshot]:
    """
    The newest snapshot for each video, keyed by video id.

    Done in two queries (max timestamps, then the matching rows) so it stays
    correct on SQLite, which has no ``DISTINCT ON``.
    """
    newest = (
        db.session.query(
            StatSnapshot.video_id.label("video_id"),
            func.max(StatSnapshot.captured_at).label("captured_at"),
        )
        .filter(StatSnapshot.video_id.isnot(None))
        .group_by(StatSnapshot.video_id)
        .subquery()
    )
    rows = (
        db.session.query(StatSnapshot)
        .join(
            newest,
            db.and_(
                StatSnapshot.video_id == newest.c.video_id,
                StatSnapshot.captured_at == newest.c.captured_at,
            ),
        )
        .all()
    )
    return {row.video_id: row for row in rows}


def latest_channel_stats() -> dict[int, StatSnapshot]:
    """The newest channel-level snapshot per account, keyed by account id."""
    newest = (
        db.session.query(
            StatSnapshot.account_id.label("account_id"),
            func.max(StatSnapshot.captured_at).label("captured_at"),
        )
        .filter(StatSnapshot.video_id.is_(None), StatSnapshot.account_id.isnot(None))
        .group_by(StatSnapshot.account_id)
        .subquery()
    )
    rows = (
        db.session.query(StatSnapshot)
        .join(
            newest,
            db.and_(
                StatSnapshot.account_id == newest.c.account_id,
                StatSnapshot.captured_at == newest.c.captured_at,
            ),
        )
        .all()
    )
    return {row.account_id: row for row in rows}


def totals() -> dict:
    """Headline numbers for the dashboard, summed across every platform."""
    latest = latest_video_stats()
    channels = latest_channel_stats()

    video_views = sum(row.views for row in latest.values())
    likes = sum(row.likes for row in latest.values())
    comments = sum(row.comments for row in latest.values())
    watch_time = sum(row.watch_time_minutes for row in latest.values())
    revenue = sum(row.estimated_revenue or 0.0 for row in latest.values())
    subscribers = sum(row.subscribers_gained for row in channels.values())

    # Per-platform breakdown so the UI can show one row per network.
    by_platform: dict[str, dict] = defaultdict(
        lambda: {"views": 0, "likes": 0, "videos": 0, "revenue": 0.0}
    )
    for row in latest.values():
        bucket = by_platform[row.platform]
        bucket["views"] += row.views
        bucket["likes"] += row.likes
        bucket["videos"] += 1
        bucket["revenue"] += row.estimated_revenue or 0.0

    return {
        "views": video_views,
        "likes": likes,
        "comments": comments,
        "watch_time_minutes": watch_time,
        "estimated_revenue": revenue,
        "subscribers": subscribers,
        "tracked_videos": len(latest),
        "by_platform": dict(by_platform),
        "last_collected": max(
            (row.captured_at for row in latest.values()), default=None
        ),
    }


def views_timeseries(days: int = 30) -> list[dict]:
    """
    Total views per day over the last *days*, for the dashboard chart.

    Each point is the sum of the latest snapshot per video on that day, which
    gives a cumulative curve of the whole catalogue.
    """
    cutoff = _utcnow() - timedelta(days=days)
    rows = (
        db.session.query(
            func.date(StatSnapshot.captured_at).label("day"),
            StatSnapshot.video_id,
            func.max(StatSnapshot.views).label("views"),
        )
        .filter(StatSnapshot.captured_at >= cutoff, StatSnapshot.video_id.isnot(None))
        .group_by("day", StatSnapshot.video_id)
        .all()
    )

    per_day: dict[str, int] = defaultdict(int)
    for day, _video_id, views in rows:
        per_day[str(day)] += int(views or 0)

    return [{"date": day, "views": per_day[day]} for day in sorted(per_day)]


def top_videos(limit: int = 10) -> list[tuple[Video, StatSnapshot]]:
    """The best performing videos, most viewed first."""
    latest = latest_video_stats()
    if not latest:
        return []
    videos = {
        video.id: video
        for video in db.session.query(Video).filter(Video.id.in_(latest.keys())).all()
    }
    pairs = [
        (videos[video_id], snapshot)
        for video_id, snapshot in latest.items()
        if video_id in videos
    ]
    pairs.sort(key=lambda pair: pair[1].views, reverse=True)
    return pairs[:limit]


def video_history(video_id: int, days: int = 90) -> list[StatSnapshot]:
    """Every snapshot for one video, oldest first (the per-video chart)."""
    cutoff = _utcnow() - timedelta(days=days)
    return (
        db.session.query(StatSnapshot)
        .filter(StatSnapshot.video_id == video_id, StatSnapshot.captured_at >= cutoff)
        .order_by(StatSnapshot.captured_at.asc())
        .all()
    )


def prune_old_snapshots(keep_days: int = 400) -> int:
    """
    Delete snapshots older than *keep_days*.

    Called by a weekly maintenance job: at three collections a day, a busy
    channel would otherwise accumulate millions of rows over a few years.
    """
    cutoff = _utcnow() - timedelta(days=keep_days)
    deleted = (
        db.session.query(StatSnapshot)
        .filter(StatSnapshot.captured_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    if deleted:
        log.info("Pruned %s statistics snapshots older than %s days.", deleted, keep_days)
    return deleted
