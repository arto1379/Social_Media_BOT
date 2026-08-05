"""
The publishing queue.

Covers scheduling arithmetic, the pre-publish safety checks, metadata assembly
and - most importantly - that a transient failure is retried while a permanent
one is not.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import LicenseType, UploadStatus, VideoStatus
from app.platforms.base import (
    PlatformAuthError,
    PlatformError,
    PlatformRetryableError,
    UploadResult,
)
from app.services import settings_service, upload_service


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
def test_next_slot_picks_the_upcoming_time(app):
    """Mid-morning, the next slot that day is chosen."""
    now = datetime(2026, 8, 4, 10, 30)
    assert upload_service.next_publishing_slot(now, ["09:00", "15:00", "20:00"]) == (
        datetime(2026, 8, 4, 15, 0)
    )


def test_next_slot_rolls_over_to_tomorrow(app):
    """After the last slot of the day, publishing moves to the first tomorrow."""
    now = datetime(2026, 8, 4, 23, 30)
    assert upload_service.next_publishing_slot(now, ["09:00", "15:00"]) == (
        datetime(2026, 8, 5, 9, 0)
    )


def test_next_slot_handles_a_broken_setting(app):
    """Garbage in the setting must not stop publishing entirely."""
    now = datetime(2026, 8, 4, 10, 0)
    assert upload_service.next_publishing_slot(now, ["not a time"]) == now


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------
def test_queue_video_creates_a_pending_job(db, account, make_video, admin):
    video = make_video()
    job = upload_service.queue_video(video, account, user=admin)

    assert job.status == UploadStatus.PENDING
    assert job.platform == "youtube"
    assert job.is_automatic is False
    assert video.status == VideoStatus.SCHEDULED


def test_queue_video_refuses_unapproved_material(db, account, make_video, admin):
    """The queue is the second line of defence after the UI."""
    video = make_video(rights_confirmed=False)
    with pytest.raises(ValueError, match="cannot be published"):
        upload_service.queue_video(video, account, user=admin)


def test_queue_video_refuses_a_disconnected_account(db, account, make_video, admin):
    account.clear_credentials()
    db.session.commit()
    with pytest.raises(ValueError, match="not connected"):
        upload_service.queue_video(make_video(), account, user=admin)


def test_cancel_returns_the_video_to_the_pool(db, account, make_video, admin):
    video = make_video()
    job = upload_service.queue_video(video, account, user=admin)

    upload_service.cancel_job(job, user=admin)

    assert job.status == UploadStatus.CANCELLED
    assert video.status == VideoStatus.READY


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def test_metadata_appends_the_shorts_hashtag(db, make_video):
    settings_service.set_value("append_shorts_hashtag", True)
    metadata = upload_service.build_metadata(make_video(description="A clip."))
    assert "#Shorts" in metadata["description"]


def test_metadata_does_not_duplicate_an_existing_hashtag(db, make_video):
    settings_service.set_value("append_shorts_hashtag", True)
    video = make_video(description="Already tagged #shorts")
    assert upload_service.build_metadata(video)["description"].lower().count("#shorts") == 1


def test_metadata_includes_attribution(db, make_video):
    """Most royalty-free licences require the credit line to be published."""
    settings_service.set_value("include_attribution", True)
    video = make_video(
        license_type=LicenseType.ROYALTY_FREE,
        attribution="Footage by Jane Doe, Pexels licence",
    )
    assert "Jane Doe" in upload_service.build_metadata(video)["description"]


def test_metadata_splits_tags_into_a_list(db, make_video):
    metadata = upload_service.build_metadata(make_video(tags="one, two ,three"))
    assert metadata["tags"] == ["one", "two", "three"]


# ---------------------------------------------------------------------------
# Running a job
# ---------------------------------------------------------------------------
class _FakeAdapter:
    """Stands in for a platform adapter so no network call is made."""

    def __init__(self, behaviour="succeed"):
        self.behaviour = behaviour
        self.uploads = 0

    def upload_video(self, credentials, file_path, metadata, progress_callback=None,
                     resumable_uri=None):
        self.uploads += 1
        if self.behaviour == "retryable":
            raise PlatformRetryableError("rate limited")
        if self.behaviour == "auth":
            raise PlatformAuthError("token revoked")
        if self.behaviour == "permanent":
            raise PlatformError("the title is not acceptable")
        if progress_callback:
            progress_callback(50)
        return UploadResult(
            remote_id="abc123",
            remote_url="https://www.youtube.com/shorts/abc123",
        )

    def set_thumbnail(self, credentials, remote_id, image_path):
        return None


@pytest.fixture()
def patched_platform(monkeypatch):
    """Replace the adapter lookup and credential fetch with test doubles."""

    def _install(behaviour="succeed"):
        adapter = _FakeAdapter(behaviour)
        monkeypatch.setattr(upload_service, "get_adapter", lambda name: adapter)
        monkeypatch.setattr(
            upload_service.account_service, "credentials_for", lambda account: {"token": "x"}
        )
        return adapter

    return _install


def test_successful_upload_records_the_result(db, account, make_video, admin, patched_platform):
    patched_platform("succeed")
    video = make_video()
    job = upload_service.queue_video(video, account, user=admin)

    assert upload_service.run_job(job) is True
    assert job.status == UploadStatus.SUCCEEDED
    assert job.remote_id == "abc123"
    assert job.progress_percent == 100
    assert video.status == VideoStatus.PUBLISHED


def test_transient_failure_is_retried_with_backoff(db, account, make_video, admin, patched_platform):
    """A rate limit should heal itself, not need a human."""
    patched_platform("retryable")
    job = upload_service.queue_video(make_video(), account, user=admin)

    assert upload_service.run_job(job) is False
    assert job.status == UploadStatus.RETRYING
    assert job.next_attempt_at is not None
    assert job.next_attempt_at > datetime.now(timezone.utc).replace(tzinfo=None)
    assert "rate limited" in job.last_error


def test_retries_stop_at_the_budget(db, account, make_video, admin, patched_platform):
    """After the retry budget the job fails so somebody is told about it."""
    patched_platform("retryable")
    job = upload_service.queue_video(make_video(), account, user=admin)
    job.max_attempts = 2
    db.session.commit()

    upload_service.run_job(job)   # attempt 1 -> retrying
    job.next_attempt_at = None
    upload_service.run_job(job)   # attempt 2 -> out of budget

    assert job.status == UploadStatus.FAILED
    assert "Gave up after 2 attempts" in job.last_error


def test_permanent_failure_does_not_retry(db, account, make_video, admin, patched_platform):
    patched_platform("permanent")
    video = make_video()
    job = upload_service.queue_video(video, account, user=admin)

    assert upload_service.run_job(job) is False
    assert job.status == UploadStatus.FAILED
    assert video.status == VideoStatus.FAILED


def test_auth_failure_marks_the_account(db, account, make_video, admin, patched_platform):
    """A revoked token has to surface on the account, not just in the log."""
    patched_platform("auth")
    job = upload_service.queue_video(make_video(), account, user=admin)

    upload_service.run_job(job)

    assert job.status == UploadStatus.FAILED
    assert "revoked" in (account.last_error or "")


def test_approval_withdrawn_after_queueing_blocks_the_upload(
    db, account, make_video, admin, patched_platform
):
    """Publishing re-checks the rules; a withdrawn approval stops the upload."""
    adapter = patched_platform("succeed")
    video = make_video()
    job = upload_service.queue_video(video, account, user=admin)

    video.rights_confirmed = False
    db.session.commit()

    assert upload_service.run_job(job) is False
    assert job.status == UploadStatus.FAILED
    assert "Blocked at publish time" in job.last_error
    assert adapter.uploads == 0


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
def test_planner_respects_the_automation_switch(db, account, make_video):
    settings_service.set_value("automation_enabled", False)
    make_video()
    result = upload_service.plan_automatic_uploads()
    assert result["queued"] == 0
    assert "switched off" in result["messages"][0]


def test_planner_queues_one_upload(db, account, make_video):
    settings_service.set_value("automation_enabled", True)
    make_video()
    assert upload_service.plan_automatic_uploads()["queued"] == 1


def test_planner_will_not_double_book_an_account(db, account, make_video):
    settings_service.set_value("automation_enabled", True)
    make_video(title="First")
    make_video(title="Second")

    upload_service.plan_automatic_uploads()
    second = upload_service.plan_automatic_uploads()

    assert second["queued"] == 0
    assert "already queued" in second["messages"][0]


def test_planner_honours_the_daily_limit(db, account, make_video):
    """Flooding a channel suppresses reach, so the ceiling is a hard stop."""
    from tests.test_content_service import _record_published

    settings_service.set_value("automation_enabled", True)
    settings_service.set_value("daily_upload_limit", 1)
    settings_service.set_value("min_hours_between_uploads", 0)

    published = make_video(title="Already out")
    _record_published(db, published, account)
    make_video(title="Waiting")

    result = upload_service.plan_automatic_uploads()
    assert result["queued"] == 0
    assert "daily limit" in result["messages"][0]


def test_planner_enforces_minimum_spacing(db, account, make_video):
    from tests.test_content_service import _record_published

    settings_service.set_value("automation_enabled", True)
    settings_service.set_value("daily_upload_limit", 10)
    settings_service.set_value("min_hours_between_uploads", 6)

    published = make_video(title="Just published")
    _record_published(db, published, account, when=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1))
    make_video(title="Next in line")

    result = upload_service.plan_automatic_uploads()
    assert result["queued"] == 0
    assert "keep 6h between uploads" in result["messages"][0]
