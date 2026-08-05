"""
The upload queue.

Publishing is never done inline with a web request: the website creates an
:class:`UploadJob` row and returns immediately, and the background worker
(app/services/scheduler_service.py) picks up jobs whose ``scheduled_at`` has
passed. That is what makes uploads "automatic in the background" while still
letting a user add a video by hand from the website.

Each job also stores the resumable-upload URI, so a transfer interrupted by a
network drop or a server restart resumes instead of starting over.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UploadStatus:
    """Lifecycle of one publish attempt to one account."""

    PENDING = "pending"      # waiting for its scheduled time
    RUNNING = "running"      # actively transferring
    RETRYING = "retrying"    # failed, will be tried again after a backoff
    SUCCEEDED = "succeeded"  # live on the platform
    FAILED = "failed"        # gave up after the retry budget
    CANCELLED = "cancelled"  # a user stopped it

    ALL = (PENDING, RUNNING, RETRYING, SUCCEEDED, FAILED, CANCELLED)
    # Jobs the worker may pick up.
    ACTIONABLE = (PENDING, RETRYING)
    # Jobs that are finished one way or another.
    TERMINAL = (SUCCEEDED, FAILED, CANCELLED)


class UploadJob(db.Model):
    """One video going to one platform account at one point in time."""

    __tablename__ = "upload_jobs"

    id = db.Column(db.Integer, primary_key=True)

    video_id = db.Column(db.Integer, db.ForeignKey("videos.id"), nullable=False, index=True)
    video = db.relationship("Video", back_populates="upload_jobs")

    account_id = db.Column(
        db.Integer, db.ForeignKey("platform_accounts.id"), nullable=False, index=True
    )
    account = db.relationship("PlatformAccount", back_populates="upload_jobs")

    # Denormalised so job history survives an account being deleted.
    platform = db.Column(db.String(32), nullable=False, index=True)

    status = db.Column(db.String(16), nullable=False, default=UploadStatus.PENDING, index=True)
    # When the worker may start. Defaults to "now" for immediate uploads.
    scheduled_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    # --- Retry bookkeeping --------------------------------------------------
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=4)
    next_attempt_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=True)

    # --- Resumable upload state --------------------------------------------
    # Google hands out a session URI; keeping it lets an interrupted transfer
    # continue from the byte it stopped at.
    resumable_uri = db.Column(db.Text, nullable=True)
    progress_percent = db.Column(db.Integer, nullable=False, default=0)

    # --- Result -------------------------------------------------------------
    remote_id = db.Column(db.String(128), nullable=True, index=True)  # e.g. video id
    remote_url = db.Column(db.String(512), nullable=True)

    # True when the automation created this job, False when a user did.
    is_automatic = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    @property
    def is_terminal(self) -> bool:
        """True when no further work will happen on this job."""
        return self.status in UploadStatus.TERMINAL

    @property
    def can_retry(self) -> bool:
        """True when the retry budget still allows another attempt."""
        return self.attempts < self.max_attempts

    @property
    def duration_seconds(self) -> float | None:
        """Wall-clock time the transfer took, for the job history table."""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<UploadJob {self.id} video={self.video_id} {self.status}>"
