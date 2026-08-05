"""
Access control decorators for view functions.

Usage in a blueprint::

    @bp.route("/videos")
    @login_required
    @permission_required(Permission.VIEW_VIDEOS)
    def index(): ...

An administrator always passes every check (the PRD requires "admin should
have every access"), so ``User.can()`` short-circuits for admins and these
decorators simply delegate to it.
"""

from __future__ import annotations

from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from app.security.permissions import Permission


def permission_required(permission: int):
    """Require a single permission bit; 403 otherwise."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                # Send anonymous visitors to the login page, remembering where
                # they wanted to go so they land there after signing in.
                return redirect(url_for("auth.login", next=request.full_path))
            if not current_user.can(permission):
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def any_permission_required(*permissions: int):
    """Require at least one of several permission bits."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.full_path))
            if not any(current_user.can(bit) for bit in permissions):
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(view):
    """Restrict a view to administrators only."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.full_path))
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


# Endpoints a user with an expired password may still reach.
_PASSWORD_CHANGE_EXEMPT = {"auth.change_password", "auth.logout", "auth.login", "static"}


def enforce_password_change():
    """
    Force a password change before anything else.

    Registered as a ``before_request`` hook by the application factory. The
    deployment scripts can create the first administrator with a generated
    password and set ``must_change_password``, so the very first login is
    funnelled to the change-password form instead of the dashboard.

    Returns a redirect response when a change is due, or None to continue.
    """
    if not current_user.is_authenticated:
        return None
    if not getattr(current_user, "must_change_password", False):
        return None
    if request.endpoint in _PASSWORD_CHANGE_EXEMPT:
        return None
    flash("Please choose a new password before continuing.", "warning")
    return redirect(url_for("auth.change_password"))


__all__ = [
    "Permission",
    "admin_required",
    "any_permission_required",
    "enforce_password_change",
    "permission_required",
]
