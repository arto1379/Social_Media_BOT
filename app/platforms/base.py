"""
The platform adapter contract.

Every social network the bot supports implements :class:`PlatformAdapter`.
The interface is intentionally small - authorise, upload, measure, research -
because those are the only four things the rest of the application asks a
platform to do.

Return values are plain dataclasses rather than raw API responses so that a
YouTube quirk never leaks into the database layer or a template.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class PlatformError(RuntimeError):
    """Base class for every platform-level failure."""


class PlatformNotConfigured(PlatformError):
    """The adapter has no API credentials configured (missing client id/secret)."""


class PlatformAuthError(PlatformError):
    """Tokens are missing, revoked or expired beyond refresh - reconnect needed."""


class PlatformRetryableError(PlatformError):
    """
    A transient failure: rate limit, 5xx, network drop.

    The upload worker treats this differently from a permanent error - it
    schedules another attempt with exponential backoff instead of failing the
    job outright.
    """


class PlatformQuotaError(PlatformRetryableError):
    """The daily API quota is exhausted; retry after the quota resets."""


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------
@dataclass
class AuthStart:
    """Everything needed to send a browser into the platform's consent screen."""

    authorization_url: str
    state: str


@dataclass
class AccountInfo:
    """Identity of the channel/profile behind a set of credentials."""

    remote_id: str
    display_name: str
    handle: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class UploadResult:
    """Outcome of a successful publish."""

    remote_id: str
    remote_url: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoMetrics:
    """Per-video performance numbers, normalised across platforms."""

    remote_id: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    favorites: int = 0
    watch_time_minutes: float = 0.0
    average_view_percentage: float | None = None
    estimated_revenue: float | None = None
    currency: str | None = None


@dataclass
class ChannelMetrics:
    """Channel/profile level totals."""

    remote_id: str
    views: int = 0
    subscribers: int = 0
    video_count: int = 0
    watch_time_minutes: float = 0.0
    estimated_revenue: float | None = None
    currency: str | None = None


@dataclass
class TrendItem:
    """One trending topic discovered by research."""

    topic: str
    keywords: list[str] = field(default_factory=list)
    category: str = ""
    score: float = 0.0
    signals: dict[str, Any] = field(default_factory=dict)


# Callback signature used to report upload progress (0-100).
ProgressCallback = Callable[[int], None]


# ---------------------------------------------------------------------------
# The adapter interface
# ---------------------------------------------------------------------------
class PlatformAdapter(ABC):
    """Base class for a social platform integration."""

    #: Stable machine key, stored in the database ("youtube").
    name: str = ""
    #: Label shown in the web interface ("YouTube").
    display_name: str = ""
    #: Maximum duration accepted for the platform's short-form format.
    short_form_max_seconds: int = 180
    #: Aspect ratio the short-form format expects (width / height).
    short_form_aspect: tuple[int, int] = (9, 16)
    #: Whether this adapter can report revenue figures.
    supports_revenue: bool = False
    #: Whether this adapter can research trends.
    supports_trends: bool = False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @abstractmethod
    def is_configured(self) -> bool:
        """True when API client credentials are present in the configuration."""

    def configuration_hint(self) -> str:
        """Message shown in the UI when :meth:`is_configured` is False."""
        return f"{self.display_name} API credentials are not configured."

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------
    @abstractmethod
    def start_authorization(self, redirect_uri: str, state: str | None = None) -> AuthStart:
        """Build the consent-screen URL the operator's browser is sent to."""

    @abstractmethod
    def complete_authorization(
        self, redirect_uri: str, authorization_response: str, state: str | None = None
    ) -> dict[str, Any]:
        """Exchange the callback URL for a credential blob to store encrypted."""

    @abstractmethod
    def fetch_account_info(self, credentials: dict[str, Any]) -> AccountInfo:
        """Identify the channel/profile the credentials belong to."""

    @abstractmethod
    def refresh_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """
        Return a refreshed credential blob.

        Implementations must return the blob unchanged when no refresh was
        necessary; the caller persists it only if it differs.
        """

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------
    @abstractmethod
    def upload_video(
        self,
        credentials: dict[str, Any],
        file_path: str,
        metadata: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
        resumable_uri: str | None = None,
    ) -> UploadResult:
        """
        Publish *file_path* with *metadata* and return the platform's ids.

        ``metadata`` keys are normalised by the upload service: title,
        description, tags, category_id, privacy, made_for_kids, language.
        """

    def set_thumbnail(
        self, credentials: dict[str, Any], remote_id: str, image_path: str
    ) -> None:
        """Attach a custom thumbnail. Optional - default is a no-op."""
        return None

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------
    @abstractmethod
    def fetch_video_metrics(
        self, credentials: dict[str, Any], remote_ids: Iterable[str]
    ) -> list[VideoMetrics]:
        """Current performance numbers for the given platform video ids."""

    @abstractmethod
    def fetch_channel_metrics(self, credentials: dict[str, Any]) -> ChannelMetrics:
        """Channel-level totals (subscribers, lifetime views)."""

    # ------------------------------------------------------------------
    # Research
    # ------------------------------------------------------------------
    def fetch_trends(
        self, credentials: dict[str, Any] | None, region: str, limit: int = 25
    ) -> list[TrendItem]:
        """Discover trending topics. Default: the platform offers none."""
        return []

    # ------------------------------------------------------------------
    # Format rules
    # ------------------------------------------------------------------
    def validate_short_form(
        self, duration_seconds: float | None, width: int | None, height: int | None
    ) -> list[str]:
        """
        Check a file against this platform's short-form rules.

        Returns a list of human-readable problems; empty means the file is
        acceptable as-is. Shared by the library ("is this Shorts ready?") and
        by the converter, which uses it to decide whether work is needed.
        """
        problems: list[str] = []
        if duration_seconds is None or width is None or height is None:
            return ["The media file has not been inspected yet."]
        if duration_seconds > self.short_form_max_seconds:
            problems.append(
                f"Duration is {duration_seconds:.0f}s; the limit is "
                f"{self.short_form_max_seconds}s."
            )
        if duration_seconds < 1:
            problems.append("The video is shorter than one second.")
        if height <= width:
            problems.append(
                f"Frame is {width}x{height}; short-form video must be vertical "
                f"({self.short_form_aspect[0]}:{self.short_form_aspect[1]})."
            )
        return problems

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {self.name}>"
