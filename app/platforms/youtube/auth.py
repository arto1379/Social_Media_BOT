"""
YouTube OAuth 2.0.

Flow used by the web interface:

1. ``build_authorization_url()`` sends the operator to Google's consent screen.
2. Google redirects back to ``/accounts/oauth/callback/youtube`` with a code.
3. ``exchange_code()`` turns that callback URL into a credential blob.
4. The blob is encrypted (app/security/crypto.py) and stored on the account.

``access_type="offline"`` plus ``prompt="consent"`` are required: without them
Google returns no refresh token on a repeat authorisation and the bot would
stop working the moment the one-hour access token expired.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from flask import current_app
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.platforms.base import PlatformAuthError, PlatformNotConfigured

log = logging.getLogger(__name__)

# Google frequently grants *more* scopes than were requested (for example when
# the user has already approved a broader set). oauthlib treats that as an
# error by default, which breaks an otherwise valid authorisation, so relax it.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Scopes the bot asks for. Each one maps to a feature required by the PRD.
SCOPES = [
    # Publish videos to the channel.
    "https://www.googleapis.com/auth/youtube.upload",
    # Read channel/video metadata and public statistics.
    "https://www.googleapis.com/auth/youtube.readonly",
    # Watch time, average view duration, subscribers gained.
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    # Estimated revenue - only useful once the channel is monetised, and the
    # consent screen makes clear it is optional.
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"


# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------
def client_config() -> dict[str, Any]:
    """
    Build the "web application" client config google-auth-oauthlib expects.

    Uses YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET from .env rather than a
    downloaded client_secret.json, so the deployment only has to manage one
    secrets file.
    """
    client_id = current_app.config.get("YOUTUBE_CLIENT_ID", "")
    client_secret = current_app.config.get("YOUTUBE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise PlatformNotConfigured(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET are not set in .env. "
            "Create an OAuth client (type: Web application) in the Google Cloud "
            "console and copy the values there."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
        }
    }


def _flow(redirect_uri: str, state: str | None = None) -> Flow:
    """Create a configured OAuth flow object."""
    flow = Flow.from_client_config(client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = redirect_uri
    return flow


# ---------------------------------------------------------------------------
# Step 1 - send the browser to Google
# ---------------------------------------------------------------------------
def build_authorization_url(redirect_uri: str, state: str | None = None) -> tuple[str, str]:
    """Return ``(authorization_url, state)`` for the consent screen."""
    flow = _flow(redirect_uri, state)
    url, returned_state = flow.authorization_url(
        access_type="offline",       # ask for a refresh token
        include_granted_scopes="true",
        prompt="consent",            # force a refresh token even on re-auth
    )
    return url, returned_state


# ---------------------------------------------------------------------------
# Step 2 - exchange the callback for tokens
# ---------------------------------------------------------------------------
def exchange_code(
    redirect_uri: str, authorization_response: str, state: str | None = None
) -> dict[str, Any]:
    """Turn the full callback URL into a serialisable credential blob."""
    flow = _flow(redirect_uri, state)
    try:
        flow.fetch_token(authorization_response=authorization_response)
    except Exception as exc:  # oauthlib raises a wide variety of errors
        raise PlatformAuthError(f"Google rejected the authorisation: {exc}") from exc

    credentials = flow.credentials
    if not credentials.refresh_token:
        raise PlatformAuthError(
            "Google did not return a refresh token. Remove this app from "
            "https://myaccount.google.com/permissions and connect again so the "
            "consent screen is shown in full."
        )
    return credentials_to_dict(credentials)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------
def credentials_to_dict(credentials: Credentials) -> dict[str, Any]:
    """Flatten a Credentials object into JSON-safe primitives for storage."""
    expiry = credentials.expiry
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri or TOKEN_URI,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or SCOPES),
        "expiry": expiry.replace(tzinfo=timezone.utc).isoformat() if expiry else None,
    }


def credentials_from_dict(blob: dict[str, Any]) -> Credentials:
    """Rebuild a Credentials object from a stored blob."""
    if not blob or not blob.get("refresh_token"):
        raise PlatformAuthError(
            "This account has no stored refresh token. Reconnect it from the "
            "Accounts page."
        )
    credentials = Credentials(
        token=blob.get("token"),
        refresh_token=blob.get("refresh_token"),
        token_uri=blob.get("token_uri") or TOKEN_URI,
        client_id=blob.get("client_id"),
        client_secret=blob.get("client_secret"),
        scopes=blob.get("scopes") or SCOPES,
    )
    # google-auth compares expiry against naive UTC, so strip the timezone.
    raw_expiry = blob.get("expiry")
    if raw_expiry:
        try:
            parsed = datetime.fromisoformat(raw_expiry)
            credentials.expiry = (
                parsed.astimezone(timezone.utc).replace(tzinfo=None)
                if parsed.tzinfo
                else parsed
            )
        except ValueError:
            log.warning("Ignoring unparsable token expiry %r", raw_expiry)
    return credentials


def refresh_if_needed(blob: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """
    Refresh an expired access token.

    Returns ``(blob, changed)``. The caller persists the blob only when
    *changed* is True, which keeps the database quiet on the common path.
    """
    credentials = credentials_from_dict(blob)
    if credentials.valid:
        return blob, False
    try:
        credentials.refresh(GoogleAuthRequest())
    except Exception as exc:
        raise PlatformAuthError(
            "Could not refresh the YouTube access token - the authorisation was "
            f"probably revoked. Reconnect the account. ({exc})"
        ) from exc
    return credentials_to_dict(credentials), True


def has_scope(blob: dict[str, Any], scope: str) -> bool:
    """True when the stored grant includes *scope* (used to skip revenue calls)."""
    return scope in (blob or {}).get("scopes", [])
