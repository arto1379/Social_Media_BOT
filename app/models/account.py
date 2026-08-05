"""
Connected social-media accounts.

One row per channel/profile the bot may publish to. The OAuth credential blob
(access token, refresh token, scopes, expiry) is stored **encrypted** - see
app/security/crypto.py - so a database dump alone does not hand an attacker
publishing rights on the channel.

The table is deliberately platform-agnostic: adding Instagram or TikTok later
means adding an adapter under app/platforms/, not a new table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.extensions import db
from app.security.crypto import decrypt_json, encrypt_json


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlatformAccount(db.Model):
    """A single authorised destination channel on one platform."""

    __tablename__ = "platform_accounts"

    id = db.Column(db.Integer, primary_key=True)

    # Adapter key, e.g. "youtube". Matches PlatformAdapter.name.
    platform = db.Column(db.String(32), nullable=False, index=True)
    # Friendly label shown in the UI ("Main channel", "Gaming shorts", ...).
    display_name = db.Column(db.String(128), nullable=False)
    # Platform-side identifiers, filled in after the OAuth handshake.
    remote_id = db.Column(db.String(128), nullable=True)      # e.g. channel id
    remote_handle = db.Column(db.String(128), nullable=True)  # e.g. @handle

    # Fernet-encrypted JSON credential blob. Never rendered in a template.
    credentials_encrypted = db.Column(db.Text, nullable=True)
    # Space-separated OAuth scopes actually granted, kept for diagnostics.
    scopes = db.Column(db.Text, default="")
    # When the stored access token expires (refresh happens automatically).
    token_expires_at = db.Column(db.DateTime, nullable=True)
    last_refreshed_at = db.Column(db.DateTime, nullable=True)

    # An account is only used by the automation when it is active *and* has
    # working credentials.
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)

    # Last error seen while talking to this account's API, surfaced in the UI
    # so a broken connection is visible without digging through logs.
    last_error = db.Column(db.Text, nullable=True)
    last_checked_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    upload_jobs = db.relationship("UploadJob", back_populates="account", lazy="dynamic")

    __table_args__ = (
        db.UniqueConstraint("platform", "remote_id", name="uq_account_platform_remote"),
    )

    # ------------------------------------------------------------------
    # Credential access
    # ------------------------------------------------------------------
    def set_credentials(self, data: dict[str, Any]) -> None:
        """Encrypt and store the OAuth credential blob."""
        self.credentials_encrypted = encrypt_json(data)

    def get_credentials(self) -> dict[str, Any] | None:
        """Decrypt the credential blob, or None when the account is unlinked."""
        if not self.credentials_encrypted:
            return None
        return decrypt_json(self.credentials_encrypted)

    def clear_credentials(self) -> None:
        """Forget the tokens (used by the "disconnect" button)."""
        self.credentials_encrypted = None
        self.token_expires_at = None
        self.scopes = ""

    # ------------------------------------------------------------------
    # Convenience properties for templates
    # ------------------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        """True when a credential blob is present."""
        return bool(self.credentials_encrypted)

    @property
    def is_usable(self) -> bool:
        """True when the automation may publish through this account."""
        return self.is_active and self.is_connected

    @property
    def status_label(self) -> str:
        """Short status word for the accounts table."""
        if not self.is_connected:
            return "not connected"
        if not self.is_active:
            return "disabled"
        if self.last_error:
            return "error"
        return "connected"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PlatformAccount {self.platform}:{self.display_name}>"
