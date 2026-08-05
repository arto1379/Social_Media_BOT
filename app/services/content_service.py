"""
Choosing what to publish next.

This module implements the PRD's money rule: *the majority of published videos
must be able to make money, and a few royalty-free clips to gather views are
fine.* It does that with a running mix rather than a fixed rotation.

How the pick works:

1. Look at the last *N* videos this account published automatically and measure
   what share of them were monetisable.
2. If that share has fallen below the configured target, the next pick must be
   monetisable. Otherwise a royalty-free clip is allowed.
3. Inside the chosen class, rank candidates by how promising they are: linked
   to a fresh high-scoring trend first, then oldest-waiting first so nothing
   sits in the library forever.
4. If the preferred class has no candidates, fall back to the other one rather
   than skipping the slot - publishing something beats publishing nothing, and
   the ratio self-corrects on the following pick.

Nothing is selected unless :meth:`Video.blocking_reasons` is empty, so an asset
with unconfirmed rights can never be chosen no matter what the mix says.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.extensions import db
from app.models import (
    LicenseType,
    PlatformAccount,
    Trend,
    UploadJob,
    UploadStatus,
    Video,
    VideoStatus,
)
from app.services import settings_service

log = logging.getLogger(__name__)

# How many recent automatic uploads the mix is measured over. Small enough to
# react within a day or two, large enough not to swing on a single upload.
MIX_WINDOW = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class Selection:
    """The outcome of a pick, including why it turned out that way."""

    video: Video | None
    reason: str
    wanted_monetizable: bool
    current_ratio: float


# ---------------------------------------------------------------------------
# Measuring the current mix
# ---------------------------------------------------------------------------
def current_monetizable_ratio(account: PlatformAccount, window: int = MIX_WINDOW) -> float:
    """
    Share of the last *window* automatic uploads that were monetisable.

    Returns 0.0 when nothing has been published yet, which makes the first pick
    monetisable - the right bias for a channel that exists to earn.
    """
    rows = (
        db.session.query(Video.license_type)
        .join(UploadJob, UploadJob.video_id == Video.id)
        .filter(
            UploadJob.account_id == account.id,
            UploadJob.status == UploadStatus.SUCCEEDED,
            UploadJob.is_automatic.is_(True),
        )
        .order_by(UploadJob.finished_at.desc())
        .limit(window)
        .all()
    )
    if not rows:
        return 0.0
    monetizable = sum(1 for (license_type,) in rows if license_type in LicenseType.MONETIZABLE)
    return monetizable / len(rows)


# ---------------------------------------------------------------------------
# Finding candidates
# ---------------------------------------------------------------------------
def _published_video_ids(account: PlatformAccount) -> set[int]:
    """Videos already published to, or queued for, this account."""
    rows = (
        db.session.query(UploadJob.video_id)
        .filter(
            UploadJob.account_id == account.id,
            UploadJob.status.in_(
                (UploadStatus.SUCCEEDED, UploadStatus.PENDING,
                 UploadStatus.RUNNING, UploadStatus.RETRYING)
            ),
        )
        .distinct()
        .all()
    )
    return {video_id for (video_id,) in rows}


def candidate_videos(
    account: PlatformAccount, monetizable: bool | None = None
) -> list[Video]:
    """
    Videos that could be published to *account* right now.

    *monetizable* filters by licence class; None returns both.
    """
    require_rights = settings_service.get("require_rights_confirmation", True)

    query = db.session.query(Video).filter(
        Video.status.in_(VideoStatus.SELECTABLE),
        Video.is_shorts_ready.is_(True),
        Video.license_type.in_(LicenseType.PUBLISHABLE),
    )
    if require_rights:
        query = query.filter(Video.rights_confirmed.is_(True))
    if monetizable is True:
        query = query.filter(Video.license_type.in_(LicenseType.MONETIZABLE))
    elif monetizable is False:
        query = query.filter(Video.license_type == LicenseType.ROYALTY_FREE)

    excluded = _published_video_ids(account)
    if excluded:
        query = query.filter(~Video.id.in_(excluded))

    candidates = query.all()
    # Final safety net: re-run the full per-video check. The query above and
    # blocking_reasons() must agree, and this is where a mismatch surfaces.
    return [video for video in candidates if not video.blocking_reasons()]


def _rank(video: Video) -> tuple:
    """
    Sort key for candidates - lower sorts first.

    Trend-linked videos go first (they are time-sensitive and were made for a
    moment that is passing), then the longest-waiting asset.
    """
    trend_score = 0.0
    if video.trend_id and video.trend is not None:
        # Only count a trend while it is still fresh; a week-old trend is noise.
        age_days = (_utcnow() - video.trend.captured_at).days
        if age_days <= 7:
            trend_score = video.trend.score
    return (-trend_score, video.created_at or _utcnow())


# ---------------------------------------------------------------------------
# The pick
# ---------------------------------------------------------------------------
def pick_next_video(account: PlatformAccount) -> Selection:
    """Choose the next video to publish to *account*."""
    target = float(settings_service.get("monetizable_ratio", 0.8))
    ratio = current_monetizable_ratio(account)
    # Below target -> the next slot has to earn. At or above -> filler allowed.
    want_monetizable = ratio < target

    preferred = candidate_videos(account, monetizable=want_monetizable)
    if preferred:
        chosen = sorted(preferred, key=_rank)[0]
        kind = "monetisable" if want_monetizable else "royalty-free"
        return Selection(
            video=chosen,
            reason=(
                f"Picked a {kind} video: the recent mix is {ratio:.0%} monetisable "
                f"against a target of {target:.0%}."
            ),
            wanted_monetizable=want_monetizable,
            current_ratio=ratio,
        )

    # Nothing in the preferred class - fall back so the slot is not wasted.
    fallback = candidate_videos(account, monetizable=not want_monetizable)
    if fallback:
        chosen = sorted(fallback, key=_rank)[0]
        missing = "monetisable" if want_monetizable else "royalty-free"
        return Selection(
            video=chosen,
            reason=(
                f"No {missing} video was available, so a "
                f"{'royalty-free' if want_monetizable else 'monetisable'} one was "
                f"used instead. Add more {missing} material to hold the "
                f"{target:.0%} target."
            ),
            wanted_monetizable=want_monetizable,
            current_ratio=ratio,
        )

    return Selection(
        video=None,
        reason=(
            "No video is ready to publish. A video needs status 'ready', a "
            "confirmed licence and a file in Shorts format."
        ),
        wanted_monetizable=want_monetizable,
        current_ratio=ratio,
    )


# ---------------------------------------------------------------------------
# Library health - shown on the dashboard
# ---------------------------------------------------------------------------
def library_summary() -> dict:
    """Counts the dashboard uses to warn before the library runs dry."""
    def _count(*filters) -> int:
        return db.session.query(func.count(Video.id)).filter(*filters).scalar() or 0

    ready_monetizable = _count(
        Video.status == VideoStatus.READY,
        Video.rights_confirmed.is_(True),
        Video.is_shorts_ready.is_(True),
        Video.license_type.in_(LicenseType.MONETIZABLE),
    )
    ready_royalty_free = _count(
        Video.status == VideoStatus.READY,
        Video.rights_confirmed.is_(True),
        Video.is_shorts_ready.is_(True),
        Video.license_type == LicenseType.ROYALTY_FREE,
    )
    return {
        "total": _count(),
        "ready_monetizable": ready_monetizable,
        "ready_royalty_free": ready_royalty_free,
        "ready_total": ready_monetizable + ready_royalty_free,
        "awaiting_rights": _count(
            Video.rights_confirmed.is_(False),
            Video.status != VideoStatus.ARCHIVED,
        ),
        "needs_conversion": _count(
            Video.is_shorts_ready.is_(False),
            Video.status != VideoStatus.ARCHIVED,
        ),
        "published": _count(Video.status == VideoStatus.PUBLISHED),
    }


def suggest_metadata_from_trend(trend: Trend) -> dict:
    """
    Seed a new video's metadata from a researched trend.

    Used by the "create a video from this trend" button. It suggests a title
    and tags to *film*; it never copies the source video.
    """
    keywords = trend.keyword_list[:10]
    return {
        "title": trend.topic[:100],
        "tags": ", ".join(keywords),
        "description": (
            f"Trending topic: {trend.topic}\n\n"
            f"Keywords: {', '.join(keywords)}\n"
            f"Observed on {trend.platform} in {trend.region} "
            f"on {trend.captured_at:%Y-%m-%d} with a score of {trend.score:.0f}/100.\n\n"
            "Replace this text with your own description before publishing."
        ),
    }


def recent_upload_count(account: PlatformAccount, hours: int = 24) -> int:
    """Successful uploads to *account* in the last *hours* (daily-limit check)."""
    since = _utcnow() - timedelta(hours=hours)
    return (
        db.session.query(func.count(UploadJob.id))
        .filter(
            UploadJob.account_id == account.id,
            UploadJob.status == UploadStatus.SUCCEEDED,
            UploadJob.finished_at >= since,
        )
        .scalar()
        or 0
    )


def last_upload_time(account: PlatformAccount) -> datetime | None:
    """When this account last published, for the minimum-spacing rule."""
    return (
        db.session.query(func.max(UploadJob.finished_at))
        .filter(
            UploadJob.account_id == account.id,
            UploadJob.status == UploadStatus.SUCCEEDED,
        )
        .scalar()
    )
