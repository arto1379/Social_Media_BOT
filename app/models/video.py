"""
The video library.

A :class:`Video` is a local asset plus the metadata needed to publish it. The
rights fields are not decoration: YouTube only pays for content you are allowed
to monetise, and "reused content" is the most common reason a channel is
rejected from the Partner Programme. The bot therefore records, for every
asset, *where it came from and under what licence*, and refuses to publish an
asset whose rights have not been confirmed.

That is also what makes the PRD's money rule enforceable: the automation aims
for a configurable majority of monetisable uploads, filling the rest with
royalty-free material that exists to attract views.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VideoStatus:
    """Lifecycle of a video inside the library."""

    DRAFT = "draft"            # uploaded/registered, metadata incomplete
    READY = "ready"            # complete and approved, may be scheduled
    SCHEDULED = "scheduled"    # an upload job exists and is waiting
    PUBLISHING = "publishing"  # an upload job is running right now
    PUBLISHED = "published"    # live on at least one platform
    FAILED = "failed"          # last publishing attempt failed
    ARCHIVED = "archived"      # kept for reference, never auto-published

    ALL = (DRAFT, READY, SCHEDULED, PUBLISHING, PUBLISHED, FAILED, ARCHIVED)
    # Statuses the automatic picker is allowed to draw from.
    SELECTABLE = (READY,)


class VideoSource:
    """How the asset entered the library."""

    MANUAL = "manual"        # a user uploaded it through the website
    LIBRARY = "library"      # dropped into the watch folder on the server
    SPONSORED = "sponsored"  # paid/brand content
    ARCHIVE = "archive"      # own back-catalogue re-cut into Shorts

    ALL = (MANUAL, LIBRARY, SPONSORED, ARCHIVE)


class LicenseType:
    """
    Rights status of the asset - drives monetisation eligibility.

    ``OWNED`` and ``LICENSED`` are monetisable. ``ROYALTY_FREE`` is safe to
    publish but is treated as view-bait rather than revenue. ``UNVERIFIED``
    can never be published: it exists so a file can be registered before its
    paperwork is sorted out.
    """

    OWNED = "owned"                  # produced by the operator
    LICENSED = "licensed"            # commercial licence held (stock, deal)
    ROYALTY_FREE = "royalty_free"    # CC0/CC-BY/public domain, attribution kept
    UNVERIFIED = "unverified"        # rights unknown - blocked from publishing

    ALL = (OWNED, LICENSED, ROYALTY_FREE, UNVERIFIED)
    # Licences that qualify a video as "makes money" for the ratio policy.
    MONETIZABLE = (OWNED, LICENSED)
    # Licences the bot will actually publish.
    PUBLISHABLE = (OWNED, LICENSED, ROYALTY_FREE)

    LABELS = {
        OWNED: "Owned / original",
        LICENSED: "Commercially licensed",
        ROYALTY_FREE: "Royalty-free (views only)",
        UNVERIFIED: "Rights unverified (blocked)",
    }


class Video(db.Model):
    """One publishable asset and its metadata."""

    __tablename__ = "videos"

    id = db.Column(db.Integer, primary_key=True)

    # --- Publishing metadata ------------------------------------------------
    title = db.Column(db.String(180), nullable=False)          # YouTube caps at 100
    description = db.Column(db.Text, default="")
    # Comma-separated keywords; kept as text so it stays portable.
    tags = db.Column(db.Text, default="")
    # YouTube category id (22 = People & Blogs, 24 = Entertainment, ...).
    category_id = db.Column(db.String(8), default="22")
    language = db.Column(db.String(8), default="en")
    privacy = db.Column(db.String(16), default="public")       # public/unlisted/private
    made_for_kids = db.Column(db.Boolean, nullable=False, default=False)

    # --- Files --------------------------------------------------------------
    # Path relative to MEDIA_ROOT, so the media directory can be moved.
    file_path = db.Column(db.String(512), nullable=False)
    thumbnail_path = db.Column(db.String(512), nullable=True)
    file_size = db.Column(db.BigInteger, nullable=True)
    checksum = db.Column(db.String(64), nullable=True)   # sha256, dedupe guard

    # --- Technical properties (filled by ffprobe) --------------------------
    duration_seconds = db.Column(db.Float, nullable=True)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    # True when the file satisfies the vertical <=3 min Shorts requirements.
    is_shorts_ready = db.Column(db.Boolean, nullable=False, default=False)
    # Notes from the last format check, shown next to the video in the UI.
    format_notes = db.Column(db.Text, default="")

    # --- Rights and money ---------------------------------------------------
    license_type = db.Column(db.String(24), nullable=False, default=LicenseType.UNVERIFIED)
    license_source = db.Column(db.String(255), default="")     # where it came from
    license_reference = db.Column(db.String(255), default="")  # invoice/licence id
    attribution = db.Column(db.Text, default="")               # credit line to include
    # Set by a user with "Approve publishing" - the bot will not publish
    # anything where this is False.
    rights_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    rights_confirmed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    rights_confirmed_at = db.Column(db.DateTime, nullable=True)

    # --- Bookkeeping --------------------------------------------------------
    source = db.Column(db.String(24), nullable=False, default=VideoSource.MANUAL)
    status = db.Column(db.String(24), nullable=False, default=VideoStatus.DRAFT, index=True)
    # Optional link to the trend that inspired this video.
    trend_id = db.Column(db.Integer, db.ForeignKey("trends.id"), nullable=True)
    trend = db.relationship("Trend", back_populates="videos")

    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    rights_confirmed_by = db.relationship("User", foreign_keys=[rights_confirmed_by_id])

    upload_jobs = db.relationship(
        "UploadJob",
        back_populates="video",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    stats = db.relationship(
        "StatSnapshot",
        back_populates="video",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------
    @property
    def is_monetizable(self) -> bool:
        """True when this asset counts towards the revenue side of the mix."""
        return self.license_type in LicenseType.MONETIZABLE

    @property
    def license_label(self) -> str:
        """Readable licence name for templates."""
        return LicenseType.LABELS.get(self.license_type, self.license_type)

    @property
    def tag_list(self) -> list[str]:
        """Tags split into a clean list for the API payload."""
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]

    def blocking_reasons(self) -> list[str]:
        """
        Everything that currently prevents this video from being published.

        The UI shows this list on the video page and the upload service calls
        it one last time before touching a platform API, so a video can never
        slip out through a race between approval and publishing.
        """
        problems: list[str] = []
        if self.license_type not in LicenseType.PUBLISHABLE:
            problems.append(
                "The licence is unverified - record where the footage came from "
                "and who owns it before publishing."
            )
        if not self.rights_confirmed:
            problems.append("Rights have not been confirmed by a reviewer.")
        if not self.title or not self.title.strip():
            problems.append("A title is required.")
        if len(self.title or "") > 100:
            problems.append("YouTube titles are limited to 100 characters.")
        if not self.file_path:
            problems.append("No media file is attached.")
        if not self.is_shorts_ready:
            problems.append(
                "The file is not in Shorts format (vertical, 3 minutes or less)."
            )
        if self.status == VideoStatus.ARCHIVED:
            problems.append("The video is archived.")
        return problems

    @property
    def is_publishable(self) -> bool:
        """Convenience wrapper around :meth:`blocking_reasons`."""
        return not self.blocking_reasons()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Video {self.id} {self.title[:32]!r}>"
