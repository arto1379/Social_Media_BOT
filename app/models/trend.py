"""
Trend research results.

The bot periodically asks each platform what is currently getting attention in
the configured region and stores the result here with a score. Those rows then
drive two things:

1. the "Trends" page, where an operator picks topics worth producing;
2. the automatic metadata helper, which suggests titles/tags for a new video.

A trend is a *topic*, not a file. The bot never downloads and re-posts somebody
else's video: that is copyright infringement, it is what gets channels demoted
for reused content, and demonetised uploads defeat the purpose. What the bot
takes from a trending video is the signal - subject, keywords, timing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TrendStatus:
    """Where a researched topic stands in the production pipeline."""

    NEW = "new"            # freshly discovered
    PLANNED = "planned"    # somebody intends to make a video about it
    USED = "used"          # a video was produced and linked to it
    REJECTED = "rejected"  # deliberately skipped, do not surface again

    ALL = (NEW, PLANNED, USED, REJECTED)


class Trend(db.Model):
    """One trending topic observed on one platform at one time."""

    __tablename__ = "trends"

    id = db.Column(db.Integer, primary_key=True)

    platform = db.Column(db.String(32), nullable=False, index=True)
    region = db.Column(db.String(8), nullable=False, default="US", index=True)

    # The topic itself plus the keywords that describe it.
    topic = db.Column(db.String(255), nullable=False)
    keywords = db.Column(db.Text, default="")          # comma separated
    category = db.Column(db.String(64), default="")

    # 0-100 relative interest score computed by the adapter, used for ranking.
    score = db.Column(db.Float, nullable=False, default=0.0)
    # Raw signals behind the score (view counts, growth rate, sample videos),
    # kept as JSON text so adapters can record whatever their API returns.
    signals_json = db.Column(db.Text, default="{}")

    status = db.Column(db.String(16), nullable=False, default=TrendStatus.NEW, index=True)
    notes = db.Column(db.Text, default="")

    captured_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)
    # Set when a user moves the trend out of "new".
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])

    videos = db.relationship("Video", back_populates="trend", lazy="dynamic")

    __table_args__ = (
        db.Index("ix_trend_platform_captured", "platform", "captured_at"),
    )

    # ------------------------------------------------------------------
    # Signal helpers
    # ------------------------------------------------------------------
    @property
    def signals(self) -> dict:
        """Parsed ``signals_json``; an empty dict if it is missing/corrupt."""
        try:
            data = json.loads(self.signals_json or "{}")
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}

    @signals.setter
    def signals(self, value: dict) -> None:
        self.signals_json = json.dumps(value or {}, separators=(",", ":"))

    @property
    def keyword_list(self) -> list[str]:
        """Keywords as a clean list, ready to seed a video's tags."""
        return [k.strip() for k in (self.keywords or "").split(",") if k.strip()]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Trend {self.platform}:{self.topic[:32]!r} score={self.score:.0f}>"
