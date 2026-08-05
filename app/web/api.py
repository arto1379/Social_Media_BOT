"""
Small JSON API.

Used by the pages that refresh themselves (the upload queue's progress bars)
and available for scripting against the bot. Authentication is the same
session cookie the web interface uses, and every endpoint enforces the same
permission as its HTML counterpart - the API is a second view of the data, not
a way around the access rules.

All endpoints are read-only, which is why the blueprint is exempt from CSRF:
there is no state to protect.
"""

from __future__ import annotations

from flask import Blueprint, jsonify
from flask_login import login_required

from app.extensions import db
from app.models import UploadJob, UploadStatus
from app.security.access import Permission, permission_required
from app.services import content_service, scheduler_service, stats_service

bp = Blueprint("api", __name__)


@bp.route("/queue")
@login_required
@permission_required(Permission.VIEW_VIDEOS)
def queue():
    """Jobs that are queued or running, with their progress."""
    jobs = (
        db.session.query(UploadJob)
        .filter(UploadJob.status.in_(
            (UploadStatus.PENDING, UploadStatus.RUNNING, UploadStatus.RETRYING)
        ))
        .order_by(UploadJob.scheduled_at.asc())
        .limit(50)
        .all()
    )
    return jsonify({
        "jobs": [
            {
                "id": job.id,
                "video_id": job.video_id,
                "title": job.video.title if job.video else None,
                "platform": job.platform,
                "account": job.account.display_name if job.account else None,
                "status": job.status,
                "progress": job.progress_percent,
                "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
                "attempts": job.attempts,
                "last_error": job.last_error,
            }
            for job in jobs
        ]
    })


@bp.route("/stats/summary")
@login_required
@permission_required(Permission.VIEW_STATISTICS)
def stats_summary():
    """Headline totals across every platform."""
    totals = stats_service.totals()
    return jsonify({
        "views": totals["views"],
        "likes": totals["likes"],
        "comments": totals["comments"],
        "subscribers": totals["subscribers"],
        "estimated_revenue": round(totals["estimated_revenue"], 2),
        "watch_time_minutes": round(totals["watch_time_minutes"], 1),
        "tracked_videos": totals["tracked_videos"],
        "by_platform": totals["by_platform"],
        "last_collected": (
            totals["last_collected"].isoformat() if totals["last_collected"] else None
        ),
    })


@bp.route("/stats/timeseries")
@login_required
@permission_required(Permission.VIEW_STATISTICS)
def stats_timeseries():
    """Daily view totals for the last 30 days."""
    return jsonify({"points": stats_service.views_timeseries(days=30)})


@bp.route("/library")
@login_required
@permission_required(Permission.VIEW_VIDEOS)
def library():
    """Library health counters - how much publishable material is left."""
    return jsonify(content_service.library_summary())


@bp.route("/scheduler")
@login_required
@permission_required(Permission.VIEW_DASHBOARD)
def scheduler():
    """Background job names and next run times."""
    return jsonify({
        "jobs": [
            {
                "id": entry["id"],
                "name": entry["name"],
                "next_run": entry["next_run"].isoformat() if entry["next_run"] else None,
            }
            for entry in scheduler_service.job_status()
        ]
    })
