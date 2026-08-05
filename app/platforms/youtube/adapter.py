"""
The YouTube adapter.

Implements :class:`PlatformAdapter` by delegating to the focused modules in
this package. Keeping the glue in one thin file makes the shape of a platform
integration obvious for whoever adds Instagram Reels or TikTok next: copy this
file, swap the four delegations.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from flask import current_app

from app.platforms.base import (
    AccountInfo,
    AuthStart,
    ChannelMetrics,
    PlatformAdapter,
    ProgressCallback,
    TrendItem,
    UploadResult,
    VideoMetrics,
)
from app.platforms.registry import register_adapter
from app.platforms.youtube import analytics, auth, trends, uploader

log = logging.getLogger(__name__)


@register_adapter
class YouTubeAdapter(PlatformAdapter):
    """Publishes Shorts to YouTube and reads back their performance."""

    name = "youtube"
    display_name = "YouTube"
    # YouTube counts a video as a Short at up to 3 minutes.
    short_form_max_seconds = 180
    short_form_aspect = (9, 16)
    supports_revenue = True
    supports_trends = True

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        """True when the OAuth client id and secret are present in .env."""
        return bool(
            current_app.config.get("YOUTUBE_CLIENT_ID")
            and current_app.config.get("YOUTUBE_CLIENT_SECRET")
        )

    def configuration_hint(self) -> str:
        return (
            "Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env. Create the "
            "credentials in the Google Cloud console: enable the YouTube Data "
            "API v3 and the YouTube Analytics API, then add an OAuth client of "
            "type 'Web application'."
        )

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------
    def start_authorization(self, redirect_uri: str, state: str | None = None) -> AuthStart:
        url, returned_state = auth.build_authorization_url(redirect_uri, state)
        return AuthStart(authorization_url=url, state=returned_state)

    def complete_authorization(
        self, redirect_uri: str, authorization_response: str, state: str | None = None
    ) -> dict[str, Any]:
        return auth.exchange_code(redirect_uri, authorization_response, state)

    def fetch_account_info(self, credentials: dict[str, Any]) -> AccountInfo:
        identity = analytics.fetch_channel_identity(credentials)
        return AccountInfo(
            remote_id=identity["id"],
            display_name=identity["title"],
            handle=identity.get("handle") or None,
            raw=identity.get("raw", {}),
        )

    def refresh_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        refreshed, _changed = auth.refresh_if_needed(credentials)
        return refreshed

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------
    def upload_video(
        self,
        credentials: dict[str, Any],
        file_path: str,
        metadata: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
        resumable_uri: str | None = None,
    ) -> UploadResult:
        return uploader.upload_video(credentials, file_path, metadata, progress_callback)

    def set_thumbnail(
        self, credentials: dict[str, Any], remote_id: str, image_path: str
    ) -> None:
        uploader.set_thumbnail(credentials, remote_id, image_path)

    def delete_video(self, credentials: dict[str, Any], remote_id: str) -> None:
        """Not part of the base interface, but handy for the "remove" action."""
        uploader.delete_video(credentials, remote_id)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------
    def fetch_video_metrics(
        self, credentials: dict[str, Any], remote_ids: Iterable[str]
    ) -> list[VideoMetrics]:
        return analytics.fetch_video_metrics(credentials, remote_ids)

    def fetch_channel_metrics(self, credentials: dict[str, Any]) -> ChannelMetrics:
        return analytics.fetch_channel_metrics(credentials)

    # ------------------------------------------------------------------
    # Research
    # ------------------------------------------------------------------
    def fetch_trends(
        self, credentials: dict[str, Any] | None, region: str, limit: int = 25
    ) -> list[TrendItem]:
        if not credentials:
            log.info("Trend research needs a connected account to call the API.")
            return []
        return trends.fetch_trends(credentials, region=region, limit=limit)
