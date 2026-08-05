"""
Runtime settings page.

The form is generated from the schema in app/services/settings_service.py, so
adding a setting there makes it appear here with the right widget, help text
and validation - there is no second list to keep in sync.
"""

from __future__ import annotations

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.security.access import Permission, permission_required
from app.services import audit_service, settings_service
from app.web.forms import CSRFOnlyForm

log = logging.getLogger(__name__)

bp = Blueprint("settings", __name__, template_folder="../templates")


@bp.route("/", methods=["GET", "POST"])
@login_required
@permission_required(Permission.MANAGE_SETTINGS)
def index():
    """Show and save the runtime settings."""
    form = CSRFOnlyForm()

    if form.validate_on_submit():
        changed: list[str] = []
        for spec in settings_service.SCHEMA:
            if spec.kind == "bool":
                # An unchecked checkbox sends nothing at all.
                submitted = spec.key in request.form
            else:
                if spec.key not in request.form:
                    continue
                submitted = request.form.get(spec.key, "")

            previous = settings_service.get(spec.key)
            new_value = settings_service.coerce(spec, submitted)
            if new_value != previous:
                settings_service.set_value(
                    spec.key, new_value, user_id=current_user.id, commit=False
                )
                changed.append(f"{spec.label}: {previous!r} -> {new_value!r}")

        from app.extensions import db

        db.session.commit()

        if changed:
            audit_service.record(
                "settings.update",
                detail="; ".join(changed)[:2000],
            )
            flash(f"Saved {len(changed)} change(s).", "success")
        else:
            flash("Nothing changed.", "info")
        return redirect(url_for("settings.index"))

    return render_template(
        "settings/index.html",
        groups=settings_service.grouped_schema(),
        values=settings_service.all_values(),
        form=form,
    )
