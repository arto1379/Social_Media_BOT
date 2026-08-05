"""
Platform account helpers.

Everything that needs to call a platform API goes through
:func:`credentials_for`, which decrypts the stored blob, refreshes the access
token when it has expired and writes the refreshed blob back. Callers never
have to think about token lifetimes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.extensions import db
from app.models import PlatformAccount
from app.platforms import PlatformAuthError, PlatformError, get_adapter

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def credentials_for(account: PlatformAccount) -> dict[str, Any]:
    """
    Return usable credentials for *account*, refreshing them if needed.

    Raises :class:`PlatformAuthError` when the account has never been connected
    or the grant has been revoked - in both cases a human has to reconnect it,
    so the error is recorded on the row and surfaced in the UI.
    """
    blob = account.get_credentials()
    if not blob:
        raise PlatformAuthError(
            f"Account '{account.display_name}' is not connected. Open the "
            f"Accounts page and connect it."
        )

    adapter = get_adapter(account.platform)
    try:
        refreshed = adapter.refresh_credentials(blob)
    except PlatformAuthError as exc:
        mark_error(account, str(exc))
        raise

    # Persist only when the refresh actually produced new material.
    if refreshed != blob:
        account.set_credentials(refreshed)
        account.last_refreshed_at = _utcnow()
        account.token_expires_at = parse_expiry(refreshed.get("expiry"))
        db.session.commit()
        log.info("Refreshed access token for account %s", account.display_name)

    return refreshed


def parse_expiry(raw: str | None) -> datetime | None:
    """Parse an ISO expiry string into naive UTC for storage."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def mark_error(account: PlatformAccount, message: str, commit: bool = True) -> None:
    """Record the last failure so the accounts page can show it."""
    account.last_error = (message or "")[:2000]
    account.last_checked_at = _utcnow()
    if commit:
        db.session.commit()


def clear_error(account: PlatformAccount, commit: bool = True) -> None:
    """Clear a previously recorded failure after a successful call."""
    if account.last_error:
        account.last_error = None
    account.last_checked_at = _utcnow()
    if commit:
        db.session.commit()


def usable_accounts(platform: str | None = None) -> list[PlatformAccount]:
    """Active, connected accounts - the ones automation is allowed to use."""
    query = db.session.query(PlatformAccount).filter(
        PlatformAccount.is_active.is_(True),
        PlatformAccount.credentials_encrypted.isnot(None),
    )
    if platform:
        query = query.filter(PlatformAccount.platform == platform)
    return query.order_by(PlatformAccount.is_default.desc(), PlatformAccount.id).all()


def default_account(platform: str = "youtube") -> PlatformAccount | None:
    """The account used when the operator does not pick one explicitly."""
    accounts = usable_accounts(platform)
    return accounts[0] if accounts else None


def test_connection(account: PlatformAccount) -> tuple[bool, str]:
    """
    Verify an account by making one cheap API call.

    Used by the "Test connection" button so a broken grant is discovered on
    demand rather than at 3 a.m. when an upload fails.
    """
    try:
        credentials = credentials_for(account)
        adapter = get_adapter(account.platform)
        info = adapter.fetch_account_info(credentials)
    except PlatformError as exc:
        mark_error(account, str(exc))
        return False, str(exc)

    # Keep the stored identity fresh - channels get renamed.
    account.remote_id = info.remote_id
    if info.handle:
        account.remote_handle = info.handle
    clear_error(account, commit=False)
    db.session.commit()
    return True, f"Connected to {info.display_name}."


def sync_account_identity(account: PlatformAccount, credentials: dict[str, Any]) -> None:
    """Fill in channel id/handle right after a successful authorisation."""
    adapter = get_adapter(account.platform)
    info = adapter.fetch_account_info(credentials)
    account.remote_id = info.remote_id
    account.remote_handle = info.handle
    if not account.display_name or account.display_name.strip() in {"", "New account"}:
        account.display_name = info.display_name
