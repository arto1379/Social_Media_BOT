"""
Users and roles.

Access control model:

* A :class:`Role` carries a permission bitmask (see app/security/permissions).
* A :class:`User` points at one role and may also hold *extra* permission bits
  granted individually, so the administrator can hand out one-off access
  without inventing a new role every time.
* ``is_admin`` overrides everything - administrators always have full access.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager
from app.security import permissions as perms


def _utcnow() -> datetime:
    """Timezone-aware "now"; stored naive-UTC for cross-database portability."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(db.Model):
    """A named bundle of permissions that can be assigned to users."""

    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255), default="")
    # Bitmask of app.security.permissions.Permission values.
    permissions = db.Column(db.Integer, nullable=False, default=0)
    # Built-in roles cannot be deleted, only edited (except Administrator).
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    users = db.relationship("User", back_populates="role", lazy="dynamic")

    def has(self, permission: int) -> bool:
        """True when this role includes *permission*."""
        return bool(self.permissions & permission)

    @property
    def permission_keys(self) -> list[str]:
        """Permission keys for pre-checking boxes in the role editor."""
        return perms.keys_from_bits(self.permissions)

    @property
    def permission_labels(self) -> list[str]:
        """Human-readable labels used in the roles table."""
        return perms.describe(self.permissions)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Role {self.name}>"


class User(UserMixin, db.Model):
    """A person who can sign in to the web interface."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=True)
    full_name = db.Column(db.String(128), default="")

    # Werkzeug PBKDF2/scrypt hash - the plain password is never stored.
    password_hash = db.Column(db.String(255), nullable=False)

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=True)
    role = db.relationship("Role", back_populates="users")

    # Extra permission bits granted on top of the role.
    extra_permissions = db.Column(db.Integer, nullable=False, default=0)

    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    # Named "active" (not "is_active") because Flask-Login's UserMixin already
    # defines an ``is_active`` property that we override below.
    active = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)

    # --- Brute-force protection --------------------------------------------
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    # ------------------------------------------------------------------
    # Password handling
    # ------------------------------------------------------------------
    def set_password(self, password: str) -> None:
        """Hash and store *password* (Werkzeug picks a strong default KDF)."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Constant-time comparison of *password* against the stored hash."""
        return check_password_hash(self.password_hash, password)

    # ------------------------------------------------------------------
    # Authorisation
    # ------------------------------------------------------------------
    @property
    def effective_permissions(self) -> int:
        """Role bits OR individual grants; administrators get everything."""
        if self.is_admin:
            return perms.EVERYTHING
        mask = self.extra_permissions or 0
        if self.role is not None:
            mask |= self.role.permissions
        return mask

    def can(self, permission: int) -> bool:
        """True when the user holds *permission* (bitmask constant)."""
        return bool(self.effective_permissions & permission)

    @property
    def permission_labels(self) -> list[str]:
        """Readable list of everything this user may do."""
        return perms.describe(self.effective_permissions)

    # ------------------------------------------------------------------
    # Account state
    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:  # consulted by Flask-Login on every request
        """Disabled or temporarily locked accounts cannot hold a session."""
        return bool(self.active) and not self.is_locked

    @property
    def is_locked(self) -> bool:
        """True while a lockout from repeated failed logins is in effect."""
        return self.locked_until is not None and self.locked_until > _utcnow()

    def register_failed_login(self) -> None:
        """Count a bad password and lock the account once the limit is hit."""
        self.failed_logins = (self.failed_logins or 0) + 1
        limit = current_app.config.get("LOGIN_MAX_FAILURES", 8)
        if self.failed_logins >= limit:
            minutes = current_app.config.get("LOGIN_LOCKOUT_MINUTES", 15)
            self.locked_until = _utcnow() + timedelta(minutes=minutes)
            self.failed_logins = 0  # restart the count after the lockout

    def register_successful_login(self, ip: str | None = None) -> None:
        """Clear the failure counter and record when/where the user signed in."""
        self.failed_logins = 0
        self.locked_until = None
        self.last_login_at = _utcnow()
        self.last_login_ip = (ip or "")[:64]

    @property
    def role_name(self) -> str:
        """Label shown in the users table."""
        if self.is_admin:
            return "Administrator"
        return self.role.name if self.role else "No role"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.username}>"


@login_manager.user_loader
def load_user(user_id: str):
    """Flask-Login callback: turn the session's user id back into a User."""
    return db.session.get(User, int(user_id))
