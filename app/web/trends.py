"""
Trend research pages.

Shows what is trending, ranked by view velocity, and lets an operator turn a
topic into a planned video. The "Create a video from this trend" button
pre-fills the upload form's title, tags and description - it does not fetch
anybody's footage.
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Trend, TrendStatus
from app.platforms import all_adapters
from app.security.access import Permission, permission_required
from app.services import audit_service, settings_service, trend_service
from app.web.forms import CSRFOnlyForm, TrendStatusForm

log = logging.getLogger(__name__)

bp = Blueprint("trends", __name__, template_folder="../templates")


@bp.route("/")
@login_required
@permission_required(Permission.VIEW_TRENDS)
def index():
    """The trends board."""
    status = request.args.get("status", TrendStatus.NEW).strip()
    platform = request.args.get("platform", "").strip()

    return render_template(
        "trends/index.html",
        trends=trend_service.recent_trends(
            limit=100, status=status or None, platform=platform or None
        ),
        keywords=trend_service.keyword_cloud(limit=30),
        status=status,
        platform=platform,
        statuses=TrendStatus.ALL,
        platforms=[adapter.name for adapter in all_adapters() if adapter.supports_trends],
        region=settings_service.get("trend_region", "US"),
        action_form=CSRFOnlyForm(),
    )


@bp.route("/<int:trend_id>")
@login_required
@permission_required(Permission.VIEW_TRENDS)
def detail(trend_id: int):
    """One trend with its raw signals and the videos made from it."""
    trend = db.session.get(Trend, trend_id) or abort(404)
    form = TrendStatusForm(status=trend.status, notes=trend.notes)
    return render_template("trends/detail.html", trend=trend, form=form)


@bp.route("/<int:trend_id>/status", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_TRENDS)
def set_status(trend_id: int):
    """Move a trend through the pipeline."""
    trend = db.session.get(Trend, trend_id) or abort(404)
    form = TrendStatusForm()

    if not form.validate_on_submit():
        flash("The form could not be validated.", "danger")
        return redirect(url_for("trends.detail", trend_id=trend.id))

    try:
        trend_service.set_status(trend, form.status.data, user=current_user, notes=form.notes.data)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("trends.detail", trend_id=trend.id))

    audit_service.record(
        "trend.status", target_type="trend", target_id=trend.id,
        detail=f"Set '{trend.topic[:80]}' to {form.status.data}.",
    )
    flash("The trend was updated.", "success")
    return redirect(url_for("trends.detail", trend_id=trend.id))


@bp.route("/research", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_TRENDS)
def research():
    """Run trend research immediately."""
    if not CSRFOnlyForm().validate_on_submit():
        flash("That request could not be verified.", "danger")
        return redirect(url_for("trends.index"))

    result = trend_service.research_all()
    errors = [entry for entry in result.get("results", []) if entry.get("error")]
    for entry in errors:
        flash(f"{entry['platform']}: {entry['error']}", "danger")
    if not errors:
        flash(
            f"Research finished: {result['new']} new topic(s), "
            f"{result['updated']} updated.",
            "success",
        )

    audit_service.record("trend.research", detail="Manual trend research run.")
    return redirect(url_for("trends.index"))
