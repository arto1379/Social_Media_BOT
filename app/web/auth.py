"""
Authentication: sign in, sign out, change password.

Two details worth knowing:

* The login response is deliberately vague ("username or password is wrong")
  so the form cannot be used to discover which usernames exist.
* Failed attempts are counted on the user row and lock the account for a while
  once the limit is reached - see ``User.register_failed_login``.
"""

from __future__ import annotations

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from urllib.parse import urlparse

from app.extensions import db
from app.models import User
from app.services import audit_service
from app.web.forms import ChangePasswordForm, LoginForm

log = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, template_folder="../templates")


def _safe_redirect_target(candidate: str | None) -> str:
    """
    Validate a ``?next=`` parameter before redirecting to it.

    Without this check an attacker could send a victim to
    ``/auth/login?next=https://evil.example`` and have the site bounce them
    somewhere hostile after a successful sign-in.
    """
    if not candidate:
        return url_for("dashboard.index")
    parsed = urlparse(candidate)
    # Accept same-site paths only: no scheme, no host.
    if parsed.scheme or parsed.netloc or not candidate.startswith("/"):
        return url_for("dashboard.index")
    return candidate


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Sign in with a username and password."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        user = db.session.query(User).filter(User.username == username).first()

        # Same message for every failure mode - see the module docstring.
        generic_error = "That username or password is not correct."

        if user is None:
            flash(generic_error, "danger")
            log.warning("Failed sign-in for unknown user %r from %s", username, request.remote_addr)
            return render_template("auth/login.html", form=form), 401

        if user.is_locked:
            flash(
                "This account is temporarily locked after too many failed "
                "attempts. Try again in a few minutes.",
                "danger",
            )
            return render_template("auth/login.html", form=form), 401

        if not user.check_password(form.password.data):
            user.register_failed_login()
            db.session.commit()
            audit_service.record(
                "auth.failed", target_type="user", target_id=user.id,
                detail=f"Failed sign-in for {user.username}.", user=None,
            )
            flash(generic_error, "danger")
            return render_template("auth/login.html", form=form), 401

        if not user.active:
            flash("This account has been disabled. Ask an administrator.", "danger")
            return render_template("auth/login.html", form=form), 403

        # --- Success ---------------------------------------------------
        user.register_successful_login(request.remote_addr)
        db.session.commit()
        login_user(user, remember=form.remember.data)
        audit_service.record(
            "auth.login", target_type="user", target_id=user.id,
            detail=f"{user.username} signed in.", user=user,
        )
        log.info("User %s signed in from %s", user.username, request.remote_addr)

        if user.must_change_password:
            flash("Please choose a new password before continuing.", "warning")
            return redirect(url_for("auth.change_password"))

        flash(f"Welcome back, {user.full_name or user.username}.", "success")
        return redirect(_safe_redirect_target(request.args.get("next")))

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Sign out. POST-only so a stray link cannot end somebody's session."""
    username = current_user.username
    audit_service.record(
        "auth.logout", target_type="user", target_id=current_user.id,
        detail=f"{username} signed out.",
    )
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    """Change your own password."""
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Your current password is not correct.", "danger")
            return render_template("auth/change_password.html", form=form), 400

        if form.current_password.data == form.new_password.data:
            flash("The new password must be different from the current one.", "warning")
            return render_template("auth/change_password.html", form=form), 400

        current_user.set_password(form.new_password.data)
        current_user.must_change_password = False
        db.session.commit()
        audit_service.record(
            "auth.password_change", target_type="user", target_id=current_user.id,
            detail=f"{current_user.username} changed their password.",
        )
        flash("Your password has been changed.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/change_password.html", form=form)


@bp.route("/profile")
@login_required
def profile():
    """Show the signed-in user's own account details and permissions."""
    return render_template("auth/profile.html", user=current_user)
