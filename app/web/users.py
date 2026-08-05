"""
User and role administration.

Implements the PRD's access model: the administrator created at deployment
time can add users and give each of them access to different parts of the
website, while administrators themselves always have every permission.

Two safety rails, because locking yourself out of your own bot is a very
annoying way to spend an evening:

* you cannot remove your own administrator flag or disable your own account;
* the last remaining administrator cannot be demoted or deleted.
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Role, User
from app.security import permissions as perms
from app.security.access import Permission, permission_required
from app.services import audit_service
from app.web.forms import CSRFOnlyForm, ResetPasswordForm, RoleForm, UserForm

log = logging.getLogger(__name__)

bp = Blueprint("users", __name__, template_folder="../templates")


def _admin_count() -> int:
    """How many enabled administrators exist."""
    return (
        db.session.query(User)
        .filter(User.is_admin.is_(True), User.active.is_(True))
        .count()
    )


def _role_choices() -> list[tuple[int, str]]:
    """Roles for the user form, with a "no role" option."""
    roles = db.session.query(Role).order_by(Role.name).all()
    return [(0, "No role (individual permissions only)")] + [
        (role.id, role.name) for role in roles
    ]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@permission_required(Permission.MANAGE_USERS)
def index():
    """List users and roles."""
    return render_template(
        "users/index.html",
        users=db.session.query(User).order_by(User.username).all(),
        roles=db.session.query(Role).order_by(Role.name).all(),
        action_form=CSRFOnlyForm(),
        admin_count=_admin_count(),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(Permission.MANAGE_USERS)
def create():
    """Create a user."""
    form = UserForm(is_new=True)
    form.role_id.choices = _role_choices()

    if form.validate_on_submit():
        username = form.username.data.strip()
        if db.session.query(User).filter(User.username == username).first():
            flash("That username is already taken.", "danger")
            return render_template("users/form.html", form=form, user=None)

        user = User(
            username=username,
            full_name=(form.full_name.data or "").strip(),
            email=(form.email.data or "").strip() or None,
            role_id=form.role_id.data or None,
            extra_permissions=perms.bits_from_keys(form.extra_permissions.data),
            is_admin=form.is_admin.data,
            active=form.active.data,
            must_change_password=form.must_change_password.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        audit_service.record(
            "user.create", target_type="user", target_id=user.id,
            detail=f"Created user '{user.username}' with role "
                   f"'{user.role_name}'{' (administrator)' if user.is_admin else ''}.",
        )
        flash(f"User '{user.username}' was created.", "success")
        return redirect(url_for("users.index"))

    return render_template("users/form.html", form=form, user=None)


@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(Permission.MANAGE_USERS)
def edit(user_id: int):
    """Edit a user's details, role and permissions."""
    user = db.session.get(User, user_id) or abort(404)
    form = UserForm(obj=user, is_new=False)
    form.role_id.choices = _role_choices()

    if form.validate_on_submit():
        # --- Safety rails ------------------------------------------------
        if user.id == current_user.id and not form.is_admin.data and user.is_admin:
            flash("You cannot remove your own administrator access.", "danger")
            return render_template("users/form.html", form=form, user=user)
        if user.id == current_user.id and not form.active.data:
            flash("You cannot disable your own account.", "danger")
            return render_template("users/form.html", form=form, user=user)
        if user.is_admin and not form.is_admin.data and _admin_count() <= 1:
            flash("This is the last administrator; the flag cannot be removed.", "danger")
            return render_template("users/form.html", form=form, user=user)

        user.username = form.username.data.strip()
        user.full_name = (form.full_name.data or "").strip()
        user.email = (form.email.data or "").strip() or None
        user.role_id = form.role_id.data or None
        user.extra_permissions = perms.bits_from_keys(form.extra_permissions.data)
        user.is_admin = form.is_admin.data
        user.active = form.active.data
        user.must_change_password = form.must_change_password.data

        # An optional password field: blank means "leave it alone".
        if form.password.data:
            user.set_password(form.password.data)

        db.session.commit()
        audit_service.record(
            "user.update", target_type="user", target_id=user.id,
            detail=f"Updated user '{user.username}' (role: {user.role_name}, "
                   f"admin: {user.is_admin}, enabled: {user.active}).",
        )
        flash("The user was updated.", "success")
        return redirect(url_for("users.index"))

    if not form.is_submitted():
        # Pre-check the individual permission boxes.
        form.extra_permissions.data = perms.keys_from_bits(user.extra_permissions or 0)
        form.role_id.data = user.role_id or 0
        form.must_change_password.data = user.must_change_password

    return render_template("users/form.html", form=form, user=user)


@bp.route("/<int:user_id>/reset-password", methods=["GET", "POST"])
@login_required
@permission_required(Permission.MANAGE_USERS)
def reset_password(user_id: int):
    """Set a new password for another user."""
    user = db.session.get(User, user_id) or abort(404)
    form = ResetPasswordForm()

    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.must_change_password = form.must_change_password.data
        user.failed_logins = 0
        user.locked_until = None
        db.session.commit()
        audit_service.record(
            "user.reset_password", target_type="user", target_id=user.id,
            detail=f"Reset the password for '{user.username}'.",
        )
        flash(
            f"The password for '{user.username}' was reset. Give it to them "
            f"over a channel other than email if you can.",
            "success",
        )
        return redirect(url_for("users.index"))

    return render_template("users/reset_password.html", form=form, user=user)


@bp.route("/<int:user_id>/delete", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_USERS)
def delete(user_id: int):
    """Delete a user."""
    user = db.session.get(User, user_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("users.index"))
    if user.is_admin and _admin_count() <= 1:
        flash("This is the last administrator and cannot be deleted.", "danger")
        return redirect(url_for("users.index"))

    username = user.username
    db.session.delete(user)
    db.session.commit()
    audit_service.record(
        "user.delete", target_type="user", target_id=user_id,
        detail=f"Deleted user '{username}'.",
    )
    flash(f"User '{username}' was deleted.", "info")
    return redirect(url_for("users.index"))


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
@bp.route("/roles/new", methods=["GET", "POST"])
@login_required
@permission_required(Permission.MANAGE_USERS)
def create_role():
    """Create a role."""
    form = RoleForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        if db.session.query(Role).filter(Role.name == name).first():
            flash("A role with that name already exists.", "danger")
            return render_template("users/role_form.html", form=form, role=None)

        role = Role(
            name=name,
            description=(form.description.data or "").strip(),
            permissions=perms.bits_from_keys(form.permissions.data),
        )
        db.session.add(role)
        db.session.commit()
        audit_service.record(
            "role.create", target_type="role", target_id=role.id,
            detail=f"Created role '{role.name}' with {len(role.permission_labels)} "
                   f"permission(s).",
        )
        flash(f"Role '{role.name}' was created.", "success")
        return redirect(url_for("users.index"))

    return render_template("users/role_form.html", form=form, role=None)


@bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(Permission.MANAGE_USERS)
def edit_role(role_id: int):
    """Edit a role's permissions."""
    role = db.session.get(Role, role_id) or abort(404)
    form = RoleForm(obj=role)

    if form.validate_on_submit():
        role.name = form.name.data.strip()
        role.description = (form.description.data or "").strip()
        role.permissions = perms.bits_from_keys(form.permissions.data)
        db.session.commit()
        audit_service.record(
            "role.update", target_type="role", target_id=role.id,
            detail=f"Updated role '{role.name}': "
                   f"{', '.join(role.permission_labels) or 'no permissions'}.",
        )
        flash(f"Role '{role.name}' was updated.", "success")
        return redirect(url_for("users.index"))

    if not form.is_submitted():
        form.permissions.data = role.permission_keys

    return render_template("users/role_form.html", form=form, role=role)


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_USERS)
def delete_role(role_id: int):
    """Delete a role that nobody is using."""
    role = db.session.get(Role, role_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)

    if role.is_system:
        flash("Built-in roles cannot be deleted, only edited.", "warning")
        return redirect(url_for("users.index"))
    if role.users.count():
        flash(
            "This role is still assigned to somebody. Move those users to "
            "another role first.",
            "warning",
        )
        return redirect(url_for("users.index"))

    name = role.name
    db.session.delete(role)
    db.session.commit()
    audit_service.record(
        "role.delete", target_type="role", target_id=role_id,
        detail=f"Deleted role '{name}'.",
    )
    flash(f"Role '{name}' was deleted.", "info")
    return redirect(url_for("users.index"))


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
@bp.route("/audit")
@login_required
@permission_required(Permission.VIEW_AUDIT_LOG)
def audit_log():
    """Who did what, most recent first."""
    return render_template("users/audit.html", entries=audit_service.recent(limit=250))
