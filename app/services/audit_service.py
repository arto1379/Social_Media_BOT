"""
Audit trail recording.

One entry point, :func:`record`, used by every view and service that changes
something worth remembering. It is deliberately forgiving: a failure to write
an audit row must never abort the operation the user actually asked for, so
errors are logged and swallowed.
"""

from __future__ import annotations

import logging

from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog

log = logging.getLogger(__name__)


def _client_ip() -> str | None:
    """
    Best-effort client IP.

    Behind nginx the real address is in X-Forwarded-For; ProxyFix (wired up in
    the app factory) already normalises ``request.remote_addr`` when
    BEHIND_PROXY is on, so reading it here is enough.
    """
    if not has_request_context():
        return None
    return (request.remote_addr or "")[:64] or None


def record(
    action: str,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: str = "",
    user=None,
    commit: bool = True,
) -> None:
    """
    Record one action.

    *action* is a dotted verb ("video.publish"). *user* defaults to the signed
    in user, or stays empty when the scheduler is the actor.
    """
    try:
        actor = user
        if actor is None and has_request_context():
            actor = current_user if getattr(current_user, "is_authenticated", False) else None

        entry = AuditLog(
            user_id=getattr(actor, "id", None),
            username=getattr(actor, "username", None) or "system",
            action=action[:64],
            target_type=(target_type or None),
            target_id=str(target_id) if target_id is not None else None,
            detail=(detail or "")[:2000],
            ip_address=_client_ip(),
        )
        db.session.add(entry)
        if commit:
            db.session.commit()
    except Exception as exc:  # never let auditing break the real work
        log.warning("Could not write audit entry %s: %s", action, exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - session already unusable
            pass


def recent(limit: int = 100):
    """Most recent entries, newest first (for the audit log page)."""
    return (
        db.session.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
