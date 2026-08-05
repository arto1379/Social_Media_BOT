"""
Audit trail.

Anything that changes access, credentials or published output is recorded here:
who did it, from which IP, and to what. With several users sharing one bot this
is the only way to answer "who disconnected the channel?" after the fact.

Secrets are never written to this table - only the fact that a secret changed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditLog(db.Model):
    """One recorded action."""

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)

    # NULL when the actor was the scheduler rather than a person.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    user = db.relationship("User", foreign_keys=[user_id])
    # Copied so the entry stays readable after a user is deleted.
    username = db.Column(db.String(64), nullable=True)

    # Dotted verb, e.g. "user.create", "account.disconnect", "video.publish".
    action = db.Column(db.String(64), nullable=False, index=True)
    target_type = db.Column(db.String(32), nullable=True)   # "video", "user", ...
    target_id = db.Column(db.String(64), nullable=True)
    detail = db.Column(db.Text, default="")                 # short human summary

    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuditLog {self.action} by {self.username or 'system'}>"
