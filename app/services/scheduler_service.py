"""
Background automation.

An APScheduler ``BackgroundScheduler`` runs four recurring jobs:

===================  ==========================================================
 upload_queue         plan the next automatic upload, then run any due jobs
 collect_statistics   refresh view/like/revenue figures from every platform
 research_trends      ask each platform what is trending right now
 maintenance          prune old snapshots and stale trends (daily)
===================  ==========================================================

Every job runs inside an application context, because the services underneath
use ``current_app`` and the SQLAlchemy session.

**Run the scheduler in exactly one process.** With several gunicorn workers,
each would otherwise start its own copy and the same video would be uploaded
several times. The recommended deployment runs the web service with
``SCHEDULER_ENABLED=0`` and a separate ``socialbot-worker`` service with
``SCHEDULER_ENABLED=1`` - see deploy/ and CONFIGURE.md.
"""

from __future__ import annotations

import atexit
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger(__name__)

# Module-level handle so ``flask shell`` and the status page can inspect it.
_scheduler: BackgroundScheduler | None = None

JOB_UPLOADS = "upload_queue"
JOB_STATS = "collect_statistics"
JOB_TRENDS = "research_trends"
JOB_MAINTENANCE = "maintenance"


def get_scheduler() -> BackgroundScheduler | None:
    """The running scheduler, or None when automation is disabled."""
    return _scheduler


# ---------------------------------------------------------------------------
# Job bodies
# ---------------------------------------------------------------------------
def _with_context(app, func, name: str):
    """
    Wrap a job so it runs inside an app context and can never kill the thread.

    APScheduler swallows exceptions from job functions, so anything that
    escapes would disappear silently; catching and logging here makes failures
    visible in the journal.
    """
    def runner():
        with app.app_context():
            started = datetime.now(timezone.utc)
            try:
                result = func()
                log.info(
                    "Job %s finished in %.1fs: %s",
                    name,
                    (datetime.now(timezone.utc) - started).total_seconds(),
                    result,
                )
            except Exception:
                log.exception("Job %s raised an exception", name)

    runner.__name__ = f"job_{name}"
    return runner


def run_upload_cycle() -> dict:
    """Plan the next automatic upload, then run whatever is due."""
    from app.services import upload_service

    planned = upload_service.plan_automatic_uploads()
    processed = upload_service.process_due_jobs()
    return {"planned": planned["queued"], **processed}


def run_statistics_cycle() -> dict:
    """Refresh statistics for every connected account."""
    from app.services import stats_service

    return stats_service.collect_all()


def run_trend_cycle() -> dict:
    """Research trends on every platform that supports it."""
    from app.services import trend_service

    return trend_service.research_all()


def run_maintenance_cycle() -> dict:
    """Housekeeping: drop data that is too old to be useful."""
    from app.services import stats_service, trend_service

    return {
        "snapshots_pruned": stats_service.prune_old_snapshots(),
        "trends_pruned": trend_service.prune(),
    }


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def start(app) -> BackgroundScheduler | None:
    """Create and start the scheduler for *app* (idempotent)."""
    global _scheduler

    if not app.config.get("SCHEDULER_ENABLED", True):
        log.info("Scheduler disabled (SCHEDULER_ENABLED=0); no background jobs will run.")
        return None
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    scheduler = BackgroundScheduler(
        timezone="UTC",
        job_defaults={
            # Never let two copies of the same job overlap - uploads are slow
            # and a double run would publish twice.
            "max_instances": 1,
            # If the process was asleep past a run time, do one catch-up run
            # rather than firing every missed interval at once.
            "coalesce": True,
            "misfire_grace_time": 300,
        },
    )

    upload_minutes = int(app.config.get("UPLOAD_POLL_MINUTES", 5))
    stats_minutes = int(app.config.get("STATS_INTERVAL_MINUTES", 180))
    trend_hours = int(app.config.get("TREND_INTERVAL_HOURS", 6))

    scheduler.add_job(
        _with_context(app, run_upload_cycle, JOB_UPLOADS),
        trigger=IntervalTrigger(minutes=upload_minutes),
        id=JOB_UPLOADS,
        name="Plan and run uploads",
        replace_existing=True,
    )
    scheduler.add_job(
        _with_context(app, run_statistics_cycle, JOB_STATS),
        trigger=IntervalTrigger(minutes=stats_minutes),
        id=JOB_STATS,
        name="Collect statistics",
        replace_existing=True,
    )
    scheduler.add_job(
        _with_context(app, run_trend_cycle, JOB_TRENDS),
        trigger=IntervalTrigger(hours=trend_hours),
        id=JOB_TRENDS,
        name="Research trends",
        replace_existing=True,
    )
    scheduler.add_job(
        _with_context(app, run_maintenance_cycle, JOB_MAINTENANCE),
        # 03:30 UTC: quiet hours, and well clear of the YouTube quota reset.
        trigger=CronTrigger(hour=3, minute=30),
        id=JOB_MAINTENANCE,
        name="Prune old data",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    log.info(
        "Scheduler started: uploads every %s min, statistics every %s min, "
        "trends every %s h.",
        upload_minutes, stats_minutes, trend_hours,
    )

    # Stop cleanly on shutdown so a restart does not leave a job mid-flight.
    atexit.register(shutdown)
    return scheduler


def shutdown() -> None:
    """Stop the scheduler if it is running."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        log.info("Stopping scheduler.")
        _scheduler.shutdown(wait=False)
    _scheduler = None


def job_status() -> list[dict]:
    """Job names and next run times, for the status panel on the dashboard."""
    if _scheduler is None or not _scheduler.running:
        return []
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time,
        }
        for job in _scheduler.get_jobs()
    ]


# Manual triggers exposed to the web interface ("Run now" buttons).
MANUAL_JOBS = {
    JOB_UPLOADS: ("Plan and run uploads", run_upload_cycle),
    JOB_STATS: ("Collect statistics", run_statistics_cycle),
    JOB_TRENDS: ("Research trends", run_trend_cycle),
    JOB_MAINTENANCE: ("Prune old data", run_maintenance_cycle),
}


def run_now(job_id: str) -> dict:
    """
    Run one job immediately, in the caller's thread.

    Used by the "Run now" buttons and the ``flask run-job`` command. Running
    inline (rather than nudging the scheduler) means the operator sees the
    result and any error straight away.
    """
    entry = MANUAL_JOBS.get(job_id)
    if entry is None:
        raise ValueError(f"Unknown job: {job_id}")
    _label, func = entry
    return func()
