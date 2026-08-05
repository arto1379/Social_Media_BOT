"""
Statistics pages.

Answers the PRD's "give statistic of views over all social medias that
support": one page with the totals across every connected platform, a
per-platform breakdown, a 30-day curve and the per-video table.
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import PlatformAccount, Video
from app.security.access import Permission, permission_required
from app.services import audit_service, stats_service
from app.web.forms import CSRFOnlyForm

bp = Blueprint("stats", __name__, template_folder="../templates")


@bp.route("/")
@login_required
@permission_required(Permission.VIEW_STATISTICS)
def index():
    """Totals, per-platform breakdown and the leaderboard."""
    days = request.args.get("days", 30, type=int)
    days = min(max(days, 7), 365)

    latest = stats_service.latest_video_stats()
    channel_stats = stats_service.latest_channel_stats()
    accounts = {
        account.id: account for account in db.session.query(PlatformAccount).all()
    }
    videos = {
        video.id: video
        for video in db.session.query(Video).filter(Video.id.in_(latest.keys() or [0])).all()
    }

    rows = sorted(
        (
            {"video": videos[video_id], "stat": stat}
            for video_id, stat in latest.items()
            if video_id in videos
        ),
        key=lambda row: row["stat"].views,
        reverse=True,
    )

    return render_template(
        "stats/index.html",
        totals=stats_service.totals(),
        timeseries=stats_service.views_timeseries(days=days),
        rows=rows,
        channel_stats=channel_stats,
        accounts=accounts,
        days=days,
        action_form=CSRFOnlyForm(),
    )


@bp.route("/refresh", methods=["POST"])
@login_required
@permission_required(Permission.RUN_JOBS)
def refresh():
    """Collect fresh statistics right now."""
    if not CSRFOnlyForm().validate_on_submit():
        flash("That request could not be verified.", "danger")
        return redirect(url_for("stats.index"))

    result = stats_service.collect_all()
    errors = [entry for entry in result.get("results", []) if entry.get("error")]
    if errors:
        for entry in errors:
            flash(f"{entry['account']}: {entry['error']}", "danger")
    else:
        flash(
            f"Refreshed statistics for {result['accounts']} account(s) and "
            f"{result['videos']} video(s).",
            "success",
        )

    audit_service.record("stats.refresh", detail="Manual statistics refresh.")
    return redirect(url_for("stats.index"))
