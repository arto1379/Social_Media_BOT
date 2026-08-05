"""
The money rule.

"The point is making money from video so majority of video should make money,
a few royalty-free videos are ok to get views" - these tests pin down what
"majority" means in practice and prove the rights gate cannot be bypassed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import LicenseType, UploadJob, UploadStatus, VideoStatus
from app.services import content_service, settings_service


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record_published(db, video, account, automatic=True, when=None):
    """Pretend a video was published, so it counts towards the recent mix."""
    finished = when or _naive_utcnow()
    job = UploadJob(
        video_id=video.id,
        account_id=account.id,
        platform=account.platform,
        status=UploadStatus.SUCCEEDED,
        scheduled_at=finished,
        finished_at=finished,
        is_automatic=automatic,
        remote_id=f"remote-{video.id}",
    )
    db.session.add(job)
    video.status = VideoStatus.PUBLISHED
    db.session.commit()
    return job


# ---------------------------------------------------------------------------
# Measuring the mix
# ---------------------------------------------------------------------------
def test_empty_history_reports_zero_ratio(account):
    """With nothing published, the ratio is 0 - so the first pick must earn."""
    assert content_service.current_monetizable_ratio(account) == 0.0


def test_ratio_counts_only_automatic_uploads(db, account, make_video):
    """Manual uploads are the operator's call and must not skew the policy."""
    owned = make_video(title="Owned", license_type=LicenseType.OWNED)
    free = make_video(title="Free", license_type=LicenseType.ROYALTY_FREE)
    _record_published(db, owned, account, automatic=True)
    _record_published(db, free, account, automatic=False)

    # Only the automatic one counts, and it was monetisable.
    assert content_service.current_monetizable_ratio(account) == 1.0


def test_ratio_is_the_share_of_monetizable(db, account, make_video):
    """Three monetisable out of four automatic uploads reads as 0.75."""
    for index in range(3):
        video = make_video(title=f"Owned {index}", license_type=LicenseType.OWNED)
        _record_published(db, video, account)
    free = make_video(title="Free", license_type=LicenseType.ROYALTY_FREE)
    _record_published(db, free, account)

    assert content_service.current_monetizable_ratio(account) == 0.75


# ---------------------------------------------------------------------------
# Choosing the next video
# ---------------------------------------------------------------------------
def test_first_pick_prefers_monetizable(db, account, make_video):
    """Starting from an empty history the bot reaches for revenue first."""
    make_video(title="Royalty free", license_type=LicenseType.ROYALTY_FREE)
    owned = make_video(title="Owned", license_type=LicenseType.OWNED)

    selection = content_service.pick_next_video(account)

    assert selection.wanted_monetizable is True
    assert selection.video.id == owned.id


def test_filler_is_allowed_once_the_target_is_met(db, account, make_video):
    """Above target, the bot may spend a slot on a royalty-free clip."""
    settings_service.set_value("monetizable_ratio", 0.8)

    # Five automatic uploads, all monetisable -> ratio 1.0, target 0.8.
    for index in range(5):
        video = make_video(title=f"Owned {index}", license_type=LicenseType.OWNED)
        _record_published(db, video, account)

    make_video(title="Spare owned", license_type=LicenseType.OWNED)
    free = make_video(title="Free filler", license_type=LicenseType.ROYALTY_FREE)

    selection = content_service.pick_next_video(account)

    assert selection.wanted_monetizable is False
    assert selection.video.id == free.id


def test_mix_recovers_when_it_slips_below_target(db, account, make_video):
    """Once the mix drops under the target the next pick must be monetisable."""
    settings_service.set_value("monetizable_ratio", 0.8)

    # Two of three automatic uploads monetisable -> 0.67, below 0.8.
    for index in range(2):
        video = make_video(title=f"Owned {index}", license_type=LicenseType.OWNED)
        _record_published(db, video, account)
    published_free = make_video(title="Free", license_type=LicenseType.ROYALTY_FREE)
    _record_published(db, published_free, account)

    make_video(title="Spare free", license_type=LicenseType.ROYALTY_FREE)
    owned = make_video(title="Spare owned", license_type=LicenseType.OWNED)

    selection = content_service.pick_next_video(account)

    assert selection.wanted_monetizable is True
    assert selection.video.id == owned.id


def test_falls_back_rather_than_wasting_a_slot(db, account, make_video):
    """With no monetisable material left, filler is better than nothing."""
    free = make_video(title="Only free", license_type=LicenseType.ROYALTY_FREE)

    selection = content_service.pick_next_video(account)

    assert selection.video.id == free.id
    assert "No monetisable video was available" in selection.reason


# ---------------------------------------------------------------------------
# The rights gate
# ---------------------------------------------------------------------------
def test_unconfirmed_rights_block_selection(db, account, make_video):
    """A video nobody has approved can never be picked."""
    make_video(title="Unapproved", rights_confirmed=False)
    assert content_service.pick_next_video(account).video is None


def test_unverified_licence_blocks_selection(db, account, make_video):
    """An unverified licence is not publishable even if somebody ticked approve."""
    make_video(
        title="Unknown origin",
        license_type=LicenseType.UNVERIFIED,
        rights_confirmed=True,
    )
    assert content_service.pick_next_video(account).video is None


def test_non_shorts_video_is_not_selected(db, account, make_video):
    """A landscape or over-long file is not eligible for a Shorts upload."""
    make_video(title="Landscape", is_shorts_ready=False, width=1920, height=1080)
    assert content_service.pick_next_video(account).video is None


def test_already_published_video_is_not_repicked(db, account, make_video):
    """The same video must not be published to the same channel twice."""
    video = make_video(title="Once is enough")
    _record_published(db, video, account)
    video.status = VideoStatus.READY  # pretend somebody reset it
    db.session.commit()

    assert content_service.pick_next_video(account).video is None


def test_queued_video_is_not_repicked(db, account, make_video):
    """A pending job already covers this video."""
    video = make_video(title="Queued")
    db.session.add(
        UploadJob(
            video_id=video.id,
            account_id=account.id,
            platform=account.platform,
            status=UploadStatus.PENDING,
            scheduled_at=_naive_utcnow(),
        )
    )
    db.session.commit()

    assert content_service.pick_next_video(account).video is None


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def test_fresh_trend_videos_are_published_first(db, account, make_video):
    """Trend-linked videos are time sensitive, so they jump the queue."""
    from app.models import Trend

    trend = Trend(
        platform="youtube",
        region="US",
        topic="Something rising",
        score=95.0,
        captured_at=_naive_utcnow(),
    )
    db.session.add(trend)
    db.session.commit()

    older = make_video(title="Evergreen")
    older.created_at = _naive_utcnow() - timedelta(days=10)
    trending = make_video(title="Topical", trend_id=trend.id)
    db.session.commit()

    selection = content_service.pick_next_video(account)
    assert selection.video.id == trending.id
    assert older.id != selection.video.id


def test_stale_trends_lose_their_priority(db, account, make_video):
    """A month-old trend is noise; the longest-waiting video wins instead."""
    from app.models import Trend

    trend = Trend(
        platform="youtube",
        region="US",
        topic="Old news",
        score=99.0,
        captured_at=_naive_utcnow() - timedelta(days=30),
    )
    db.session.add(trend)
    db.session.commit()

    old = make_video(title="Waiting a long time")
    old.created_at = _naive_utcnow() - timedelta(days=20)
    make_video(title="Stale trend video", trend_id=trend.id)
    db.session.commit()

    assert content_service.pick_next_video(account).video.id == old.id


# ---------------------------------------------------------------------------
# Library summary
# ---------------------------------------------------------------------------
def test_library_summary_counts_by_class(db, make_video):
    """The dashboard numbers have to reflect what is actually publishable."""
    make_video(title="Owned", license_type=LicenseType.OWNED)
    make_video(title="Free", license_type=LicenseType.ROYALTY_FREE)
    make_video(title="Unapproved", rights_confirmed=False)
    make_video(title="Needs conversion", is_shorts_ready=False)

    summary = content_service.library_summary()

    assert summary["total"] == 4
    assert summary["ready_monetizable"] == 1
    assert summary["ready_royalty_free"] == 1
    assert summary["awaiting_rights"] == 1
    assert summary["needs_conversion"] == 1
