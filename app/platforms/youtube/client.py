"""
Google API service factory and error translation.

Two jobs:

* build the ``youtube`` (Data API v3) and ``youtubeAnalytics`` (v2) service
  objects from a stored credential blob;
* translate ``HttpError`` into the project's own exception types, so the upload
  worker can tell "try again in ten minutes" (quota, 503) apart from "this will
  never work" (bad metadata, revoked token).

That distinction is the difference between a queue that heals itself overnight
and one that has to be poked by hand every morning.
"""

from __future__ import annotations

import json
import logging
import socket
import ssl
from typing import Any

import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.platforms.base import (
    PlatformAuthError,
    PlatformError,
    PlatformQuotaError,
    PlatformRetryableError,
)
from app.platforms.youtube.auth import credentials_from_dict

log = logging.getLogger(__name__)

# API surfaces used by this adapter.
DATA_API = ("youtube", "v3")
ANALYTICS_API = ("youtubeAnalytics", "v2")

# HTTP statuses that are worth retrying rather than failing permanently.
_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}

# Google "reason" strings that mean "slow down" rather than "you are wrong".
_QUOTA_REASONS = {
    "quotaExceeded",
    "dailyLimitExceeded",
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "backendError",
}

# Reasons that mean the grant itself is broken and a human must reconnect.
_AUTH_REASONS = {
    "authError",
    "unauthorized",
    "forbidden",
    "youtubeSignupRequired",
    "accountDelegationForbidden",
}

# Network-level exceptions that should be retried.
RETRYABLE_EXCEPTIONS = (
    socket.timeout,
    socket.error,
    ssl.SSLError,
    ConnectionError,
    httplib2.HttpLib2Error,
    OSError,
)


def build_data_service(credentials_blob: dict[str, Any]):
    """Return a YouTube Data API v3 client for the given credentials."""
    return _build(DATA_API, credentials_blob)


def build_analytics_service(credentials_blob: dict[str, Any]):
    """Return a YouTube Analytics API v2 client for the given credentials."""
    return _build(ANALYTICS_API, credentials_blob)


def _build(api: tuple[str, str], credentials_blob: dict[str, Any]):
    """Shared service construction with the discovery cache disabled."""
    name, version = api
    credentials = credentials_from_dict(credentials_blob)
    # cache_discovery=False avoids a noisy warning (and a stale cache) when the
    # process runs without a writable oauth2client cache directory.
    return build(name, version, credentials=credentials, cache_discovery=False)


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------
def _error_details(error: HttpError) -> tuple[str, str]:
    """Pull ``(reason, message)`` out of a Google API error body."""
    reason = ""
    message = ""
    try:
        body = json.loads(error.content.decode("utf-8"))
        err = body.get("error", {})
        message = err.get("message", "") or ""
        errors = err.get("errors") or []
        if errors:
            reason = errors[0].get("reason", "") or ""
        if not reason:
            reason = err.get("status", "") or ""
    except (ValueError, AttributeError, UnicodeDecodeError):
        message = str(error)
    return reason, message


def translate_error(error: Exception, context: str = "") -> PlatformError:
    """
    Convert any exception raised by the Google client into a project error.

    ``context`` is a short phrase such as "uploading video" that is prefixed to
    the message so log lines say what was being attempted.
    """
    prefix = f"{context}: " if context else ""

    if isinstance(error, HttpError):
        status = getattr(error.resp, "status", None)
        reason, message = _error_details(error)
        detail = f"{prefix}HTTP {status} {reason} - {message}".strip()

        if reason in _QUOTA_REASONS or status == 429:
            return PlatformQuotaError(
                f"{detail}\nThe daily YouTube API quota is limited (10,000 units "
                f"by default, and one upload costs about 1,600). Uploads resume "
                f"automatically once the quota resets at midnight Pacific time."
            )
        if status in (401,) or reason in _AUTH_REASONS:
            # 403 is ambiguous: it covers both revoked access and quota. The
            # reason string above already routed the quota cases away.
            return PlatformAuthError(
                f"{detail}\nReconnect the account from the Accounts page."
            )
        if status == 403:
            return PlatformError(detail)
        if status in _RETRYABLE_STATUSES:
            return PlatformRetryableError(detail)
        return PlatformError(detail)

    if isinstance(error, RETRYABLE_EXCEPTIONS):
        return PlatformRetryableError(f"{prefix}network error: {error}")

    if isinstance(error, PlatformError):
        return error

    return PlatformError(f"{prefix}{type(error).__name__}: {error}")


def execute(request, context: str = "") -> Any:
    """
    Run a Google API request and raise a translated error on failure.

    Every call in this package goes through here so error handling is
    consistent and lives in exactly one place.
    """
    try:
        return request.execute()
    except Exception as exc:  # translated below into a typed PlatformError
        raise translate_error(exc, context) from exc
