"""
Performance statistics.

The PRD asks for "statistics of views over all social medias that support" it,
so metrics are stored in one platform-neutral table. Rows are *snapshots*: the
collector appends a new row each run instead of overwriting, which is what
makes it possible to draw a growth curve and to compute "views in the last
7 days" rather than only a lifetime total.

A row with ``video_id = NULL`` is a channel-level snapshot (subscribers, total
channel views).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class StatSnapshot(db.Model):
    """One measurement of one video (or channel) at one moment."""

    __tablename__ = "stat_snapshots"

    id = db.Column(db.Integer, primary_key=True)

    platform = db.Column(db.String(32), nullable=False, index=True)
    account_id = db.Column(
        db.Integer, db.ForeignKey("platform_accounts.id"), nullable=True, index=True
    )
    account = db.relationship("PlatformAccount")

    # NULL for channel-level rows.
    video_id = db.Column(db.Integer, db.ForeignKey("videos.id"), nullable=True, index=True)
    video = db.relationship("Video", back_populates="stats")
    # Platform-side id, kept so stats survive the local video being deleted.
    remote_id = db.Column(db.String(128), nullable=True, index=True)

    # --- Metrics (all cumulative lifetime totals unless noted) -------------
    views = db.Column(db.BigInteger, nullable=False, default=0)
    likes = db.Column(db.BigInteger, nullable=False, default=0)
    comments = db.Column(db.BigInteger, nullable=False, default=0)
    shares = db.Column(db.BigInteger, nullable=False, default=0)
    favorites = db.Column(db.BigInteger, nullable=False, default=0)
    watch_time_minutes = db.Column(db.Float, nullable=False, default=0.0)
    average_view_percentage = db.Column(db.Float, nullable=True)
    subscribers_gained = db.Column(db.BigInteger, nullable=False, default=0)
    # Only available when the channel is in the Partner Programme and the
    # monetary scope was granted; NULL otherwise.
    estimated_revenue = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(8), nullable=True)

    captured_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)

    __table_args__ = (
        # The dashboard queries "latest snapshot per video", so index the pair.
        db.Index("ix_stat_video_captured", "video_id", "captured_at"),
        db.Index("ix_stat_account_captured", "account_id", "captured_at"),
    )

    @property
    def is_channel_level(self) -> bool:
        """True for channel totals rather than a single video."""
        return self.video_id is None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StatSnapshot {self.platform} video={self.video_id} views={self.views}>"
