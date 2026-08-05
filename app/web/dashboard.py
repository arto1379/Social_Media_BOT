"""
The dashboard.

One page that answers the three questions an operator actually has: is the
channel growing, is the queue moving, and is anything broken? The health panel
is the important part - a missing ffmpeg or an expired token shows up here
instead of silently stopping the automation.
"""

from __future__ import annotations

import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.models import UploadJob, UploadStatus
from app.platforms import all_adapters
from app.security.access import Permission, permission_required
from app.services import (
    account_service,
    content_service,
    scheduler_service,
    settings_service,
    stats_service,
    video_processing,
)
from app.web.forms import CSRFOnlyForm

log = logging.getLogger(__name__)

bp = Blueprint("dashboard", __name__, template_folder="../templates")


def _health_checks() -> list[dict]:
    """
    Build the health panel.

    Each entry is ``{level, title, detail}`` where level is ok/warn/error, so
    the template can render them without knowing what any of them mean.
    """
    checks: list[dict] = []

    # --- ffmpeg -------------------------------------------------------------
    ffmpeg_ok, ffmpeg_message = video_processing.tools_available()
    checks.append({
        "level": "ok" if ffmpeg_ok else "error",
        "title": "Media tools",
        "detail": ffmpeg_message,
    })

    # --- Platform API credentials ------------------------------------------
    for adapter in all_adapters():
        configured = adapter.is_configured()
        checks.append({
            "level": "ok" if configured else "warn",
            "title": f"{adapter.display_name} API",
            "detail": "API credentials are configured."
                      if configured else adapter.configuration_hint(),
        })

    # --- Connected accounts -------------------------------------------------
    accounts = account_service.usable_accounts()
    if not accounts:
        checks.append({
            "level": "warn",
            "title": "Connected accounts",
            "detail": "No account is connected yet. Nothing can be published "
                      "until you connect one on the Accounts page.",
        })
    else:
        broken = [account for account in accounts if account.last_error]
        checks.append({
            "level": "error" if broken else "ok",
            "title": "Connected accounts",
            "detail": (
                f"{len(broken)} of {len(accounts)} account(s) reported an error: "
                + "; ".join(f"{a.display_name}: {a.last_error[:120]}" for a in broken)
            ) if broken else f"{len(accounts)} account(s) connected and working.",
        })

    # --- Automation ---------------------------------------------------------
    automation_on = settings_service.get("automation_enabled", True)
    scheduler = scheduler_service.get_scheduler()
    if not automation_on:
        checks.append({
            "level": "warn",
            "title": "Automatic publishing",
            "detail": "Switched off in Settings. Manual uploads still work.",
        })
    elif scheduler is None or not scheduler.running:
        checks.append({
            "level": "warn",
            "title": "Background worker",
            "detail": "The scheduler is not running in this process. On a server "
                      "it runs as the separate 'socialbot-worker' service - check "
                      "it with 'systemctl status socialbot-worker'.",
        })
    else:
        checks.append({
            "level": "ok",
            "title": "Background worker",
            "detail": "The scheduler is running.",
        })

    # --- Library ------------------------------------------------------------
    library = content_service.library_summary()
    if library["ready_total"] == 0:
        checks.append({
            "level": "warn",
            "title": "Video library",
            "detail": "No video is ready to publish. Add videos, confirm their "
                      "rights and make sure they are in Shorts format.",
        })
    elif library["ready_total"] < 3:
        checks.append({
            "level": "warn",
            "title": "Video library",
            "detail": f"Only {library['ready_total']} video(s) are ready. The "
                      f"automation will run out shortly.",
        })
    else:
        checks.append({
            "level": "ok",
            "title": "Video library",
            "detail": f"{library['ready_total']} video(s) ready to publish "
                      f"({library['ready_monetizable']} monetisable, "
                      f"{library['ready_royalty_free']} royalty-free).",
        })

    return checks


@bp.route("/")
@login_required
@permission_required(Permission.VIEW_DASHBOARD)
def index():
    """The home page."""
    totals = stats_service.totals()
    library = content_service.library_summary()

    active_jobs = (
        db.session.query(UploadJob)
        .filter(UploadJob.status.in_(
            (UploadStatus.PENDING, UploadStatus.RUNNING, UploadStatus.RETRYING)
        ))
        .order_by(UploadJob.scheduled_at.asc())
        .limit(10)
        .all()
    )
    recent_jobs = (
        db.session.query(UploadJob)
        .filter(UploadJob.status.in_(UploadStatus.TERMINAL))
        .order_by(UploadJob.finished_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "dashboard/index.html",
        totals=totals,
        library=library,
        active_jobs=active_jobs,
        recent_jobs=recent_jobs,
        top_videos=stats_service.top_videos(limit=5),
        timeseries=stats_service.views_timeseries(days=30),
        health=_health_checks(),
        scheduler_jobs=scheduler_service.job_status(),
        manual_jobs=scheduler_service.MANUAL_JOBS,
        action_form=CSRFOnlyForm(),
        monetizable_target=float(settings_service.get("monetizable_ratio", 0.8)),
    )


@bp.route("/jobs/<job_id>/run", methods=["POST"])
@login_required
@permission_required(Permission.RUN_JOBS)
def run_job(job_id: str):
    """
    Run a background job immediately.

    Runs inline so the operator sees the outcome straight away - useful when
    setting a server up, and the only way to test the pipeline without waiting
    for the next interval.
    """
    form = CSRFOnlyForm()
    if not form.validate_on_submit():
        flash("That request could not be verified. Try again.", "danger")
        return redirect(url_for("dashboard.index"))

    try:
        result = scheduler_service.run_now(job_id)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("dashboard.index"))
    except Exception as exc:  # a manual run should report, not crash the page
        log.exception("Manual run of job %s failed", job_id)
        flash(f"The job failed: {exc}", "danger")
        return redirect(url_for("dashboard.index"))

    label = scheduler_service.MANUAL_JOBS[job_id][0]
    flash(f"{label} finished: {result}", "success")
    return redirect(url_for("dashboard.index"))


@bp.route("/health")
def health():
    """
    Unauthenticated liveness probe for monitoring and the installer.

    Reports only whether the process is up and the database answers - no
    counts, no names, nothing an outsider could use.
    """
    try:
        db.session.execute(db.text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # pragma: no cover - only when the DB is down
        log.error("Health check database error: %s", exc)
        database_ok = False

    status = "ok" if database_ok else "degraded"
    return jsonify({"status": status, "database": database_ok}), (200 if database_ok else 503)
