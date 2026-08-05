"""
The publishing queue.

Two halves:

* **Planning** - :func:`plan_automatic_uploads` decides *whether* and *when* to
  publish next for each connected account, honouring the automation switch, the
  daily limit, the minimum spacing and the publishing time slots.
* **Execution** - :func:`process_due_jobs` runs the jobs whose time has come,
  transferring the file through the platform adapter and recording the result.

Both halves are pure functions over the database, which is why the web
interface can call the same code for a manual upload as the scheduler does for
an automatic one.

Failures are classified: a transient error (rate limit, 503, dropped
connection) reschedules the job with exponential backoff, while a permanent one
(rejected metadata, revoked token) fails it immediately so somebody is told.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from app.extensions import db
from app.models import (
    PlatformAccount,
    UploadJob,
    UploadStatus,
    Video,
    VideoStatus,
)
from app.platforms import (
    PlatformAuthError,
    PlatformError,
    PlatformRetryableError,
    get_adapter,
)
from app.services import (
    account_service,
    audit_service,
    content_service,
    settings_service,
    video_processing,
)

log = logging.getLogger(__name__)

# Backoff schedule for transient failures: 5 min, 15 min, 45 min, 135 min.
BACKOFF_BASE_MINUTES = 5
BACKOFF_FACTOR = 3

# How many jobs one worker pass will run. Uploads are slow and quota is
# limited, so a small batch keeps the worker responsive.
DEFAULT_BATCH_SIZE = 2


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------
def queue_video(
    video: Video,
    account: PlatformAccount,
    scheduled_at: datetime | None = None,
    user=None,
    automatic: bool = False,
    commit: bool = True,
) -> UploadJob:
    """
    Create an upload job for *video* on *account*.

    Raises ValueError when the video is not publishable - the check runs here
    as well as in the view so the scheduler cannot bypass it.
    """
    problems = video.blocking_reasons()
    if problems:
        raise ValueError("This video cannot be published yet: " + " ".join(problems))
    if not account.is_usable:
        raise ValueError(
            f"Account '{account.display_name}' is not connected or is disabled."
        )

    job = UploadJob(
        video_id=video.id,
        account_id=account.id,
        platform=account.platform,
        status=UploadStatus.PENDING,
        scheduled_at=scheduled_at or _utcnow(),
        is_automatic=automatic,
        created_by_id=getattr(user, "id", None),
    )
    db.session.add(job)

    # Reflect the queued state on the video so the library reads correctly.
    if video.status in (VideoStatus.READY, VideoStatus.FAILED):
        video.status = VideoStatus.SCHEDULED

    if commit:
        db.session.commit()

    audit_service.record(
        "upload.queue",
        target_type="video",
        target_id=video.id,
        detail=(
            f"{'Automatic' if automatic else 'Manual'} upload of "
            f"'{video.title}' to {account.display_name} at "
            f"{job.scheduled_at:%Y-%m-%d %H:%M} UTC."
        ),
        user=user,
    )
    return job


def cancel_job(job: UploadJob, user=None) -> None:
    """Stop a job that has not finished yet."""
    if job.is_terminal:
        raise ValueError("That job has already finished.")
    job.status = UploadStatus.CANCELLED
    job.finished_at = _utcnow()
    # Put the video back in circulation unless another job still covers it.
    if job.video and job.video.status == VideoStatus.SCHEDULED:
        job.video.status = VideoStatus.READY
    db.session.commit()
    audit_service.record(
        "upload.cancel", target_type="upload_job", target_id=job.id,
        detail=f"Cancelled upload of '{job.video.title if job.video else job.video_id}'.",
        user=user,
    )


def retry_job(job: UploadJob, user=None) -> None:
    """Put a failed job back in the queue for an immediate retry."""
    if job.status not in (UploadStatus.FAILED, UploadStatus.CANCELLED):
        raise ValueError("Only failed or cancelled jobs can be retried.")
    job.status = UploadStatus.PENDING
    job.scheduled_at = _utcnow()
    job.next_attempt_at = None
    job.attempts = 0
    job.last_error = None
    job.progress_percent = 0
    if job.video:
        job.video.status = VideoStatus.SCHEDULED
    db.session.commit()
    audit_service.record(
        "upload.retry", target_type="upload_job", target_id=job.id,
        detail="Requeued by hand.", user=user,
    )


# ---------------------------------------------------------------------------
# Metadata assembly
# ---------------------------------------------------------------------------
def build_metadata(video: Video) -> dict:
    """
    Turn a Video row into the normalised metadata dict adapters consume.

    Two policy settings are applied here so they affect every upload path:
    the ``#Shorts`` hashtag and the attribution line required by most
    royalty-free licences.
    """
    description = (video.description or "").strip()

    if settings_service.get("include_attribution", True) and (video.attribution or "").strip():
        description = f"{description}\n\n{video.attribution.strip()}".strip()

    if settings_service.get("append_shorts_hashtag", True):
        if "#shorts" not in description.lower():
            description = f"{description}\n\n#Shorts".strip()

    return {
        "title": (video.title or "Untitled").strip(),
        "description": description,
        "tags": video.tag_list,
        "category_id": video.category_id or settings_service.get("default_category_id", "22"),
        "privacy": video.privacy or settings_service.get("default_privacy", "public"),
        "made_for_kids": bool(video.made_for_kids),
        "language": video.language or "en",
    }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def due_jobs(limit: int = DEFAULT_BATCH_SIZE) -> list[UploadJob]:
    """Jobs that are ready to run right now, oldest scheduled first."""
    now = _utcnow()
    return (
        db.session.query(UploadJob)
        .filter(
            UploadJob.status.in_(UploadStatus.ACTIONABLE),
            UploadJob.scheduled_at <= now,
            db.or_(UploadJob.next_attempt_at.is_(None), UploadJob.next_attempt_at <= now),
        )
        .order_by(UploadJob.scheduled_at.asc())
        .limit(limit)
        .all()
    )


def run_job(job: UploadJob) -> bool:
    """
    Execute one upload job. Returns True on success.

    Never raises: every outcome is written to the job row, because this runs on
    a background thread where an exception would simply vanish into the log.
    """
    video = job.video
    account = job.account

    if video is None or account is None:
        _fail(job, "The video or account behind this job no longer exists.")
        return False

    # Re-check the rules immediately before publishing. Approval could have
    # been withdrawn while the job sat in the queue.
    problems = video.blocking_reasons()
    if problems:
        _fail(job, "Blocked at publish time: " + " ".join(problems))
        return False

    job.status = UploadStatus.RUNNING
    job.started_at = _utcnow()
    job.attempts += 1
    job.progress_percent = 0
    video.status = VideoStatus.PUBLISHING
    db.session.commit()

    def report_progress(percent: int) -> None:
        """Persist progress so the queue page can show a live bar."""
        job.progress_percent = max(0, min(100, percent))
        db.session.commit()

    try:
        credentials = account_service.credentials_for(account)
        adapter = get_adapter(account.platform)
        file_path = str(video_processing.media_path(video.file_path))

        result = adapter.upload_video(
            credentials,
            file_path,
            build_metadata(video),
            progress_callback=report_progress,
        )

        # A custom thumbnail is optional; a failure here must not fail the
        # upload, which has already succeeded.
        if video.thumbnail_path:
            try:
                adapter.set_thumbnail(
                    credentials,
                    result.remote_id,
                    str(video_processing.media_path(video.thumbnail_path)),
                )
            except PlatformError as exc:
                log.warning("Thumbnail upload failed for %s: %s", result.remote_id, exc)

    except PlatformRetryableError as exc:
        _reschedule(job, str(exc))
        return False
    except PlatformAuthError as exc:
        account_service.mark_error(account, str(exc), commit=False)
        _fail(job, str(exc))
        return False
    except (PlatformError, ValueError, OSError) as exc:
        _fail(job, str(exc))
        return False
    except Exception as exc:  # unexpected - fail loudly but keep the worker up
        log.exception("Unexpected error while running upload job %s", job.id)
        _fail(job, f"Unexpected error: {type(exc).__name__}: {exc}")
        return False

    # --- Success ---------------------------------------------------------
    job.status = UploadStatus.SUCCEEDED
    job.finished_at = _utcnow()
    job.progress_percent = 100
    job.remote_id = result.remote_id
    job.remote_url = result.remote_url
    job.last_error = None
    video.status = VideoStatus.PUBLISHED
    account_service.clear_error(account, commit=False)
    db.session.commit()

    log.info("Published '%s' to %s as %s", video.title, account.display_name, result.remote_id)
    audit_service.record(
        "upload.success",
        target_type="video",
        target_id=video.id,
        detail=f"Published '{video.title}' to {account.display_name}: {result.remote_url}",
    )
    return True


def _reschedule(job: UploadJob, message: str) -> None:
    """Handle a transient failure with exponential backoff."""
    job.last_error = message[:2000]
    if job.can_retry:
        delay = BACKOFF_BASE_MINUTES * (BACKOFF_FACTOR ** (job.attempts - 1))
        job.status = UploadStatus.RETRYING
        job.next_attempt_at = _utcnow() + timedelta(minutes=delay)
        if job.video:
            job.video.status = VideoStatus.SCHEDULED
        db.session.commit()
        log.warning(
            "Upload job %s failed (attempt %s/%s), retrying in %s minutes: %s",
            job.id, job.attempts, job.max_attempts, delay, message,
        )
    else:
        _fail(job, f"Gave up after {job.attempts} attempts. Last error: {message}")


def _fail(job: UploadJob, message: str) -> None:
    """Mark a job as permanently failed and record why."""
    job.status = UploadStatus.FAILED
    job.finished_at = _utcnow()
    job.last_error = message[:2000]
    if job.video and job.video.status in (VideoStatus.PUBLISHING, VideoStatus.SCHEDULED):
        job.video.status = VideoStatus.FAILED
    db.session.commit()
    log.error("Upload job %s failed: %s", job.id, message)
    audit_service.record(
        "upload.failed",
        target_type="upload_job",
        target_id=job.id,
        detail=message[:500],
    )


def process_due_jobs(limit: int = DEFAULT_BATCH_SIZE) -> dict:
    """Run every due job, up to *limit*. Returns a small summary for logging."""
    jobs = due_jobs(limit)
    succeeded = failed = 0
    for job in jobs:
        if run_job(job):
            succeeded += 1
        else:
            failed += 1
    if jobs:
        log.info("Upload pass complete: %s succeeded, %s did not.", succeeded, failed)
    return {"processed": len(jobs), "succeeded": succeeded, "failed": failed}


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
def next_publishing_slot(now: datetime, slots: list[str]) -> datetime:
    """
    The next configured publishing time at or after *now*.

    Times are UTC "HH:MM" strings; if all of today's slots have passed, the
    first slot tomorrow is returned.
    """
    parsed: list[time] = []
    for slot in slots:
        try:
            hour, minute = (int(part) for part in slot.split(":"))
            parsed.append(time(hour=hour, minute=minute))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return now

    for slot_time in sorted(parsed):
        candidate = datetime.combine(now.date(), slot_time)
        if candidate >= now:
            return candidate
    return datetime.combine(now.date() + timedelta(days=1), sorted(parsed)[0])


def _has_open_job(account: PlatformAccount) -> bool:
    """True when a job for this account is already queued or running."""
    return (
        db.session.query(UploadJob.id)
        .filter(
            UploadJob.account_id == account.id,
            UploadJob.status.in_(
                (UploadStatus.PENDING, UploadStatus.RUNNING, UploadStatus.RETRYING)
            ),
        )
        .first()
        is not None
    )


def plan_for_account(account: PlatformAccount) -> tuple[UploadJob | None, str]:
    """
    Decide whether to queue one more upload for *account*.

    Returns ``(job_or_None, explanation)``. The explanation is logged and shown
    on the dashboard, so "why did nothing publish today?" always has an answer.
    """
    now = _utcnow()

    if _has_open_job(account):
        return None, f"{account.display_name}: an upload is already queued."

    limit = int(settings_service.get("daily_upload_limit", 3))
    if limit <= 0:
        return None, f"{account.display_name}: the daily upload limit is set to zero."

    published_today = content_service.recent_upload_count(account, hours=24)
    if published_today >= limit:
        return None, (
            f"{account.display_name}: the daily limit of {limit} uploads is reached "
            f"({published_today} in the last 24 hours)."
        )

    min_gap = float(settings_service.get("min_hours_between_uploads", 3.0))
    last = content_service.last_upload_time(account)
    if last and (now - last) < timedelta(hours=min_gap):
        wait = timedelta(hours=min_gap) - (now - last)
        return None, (
            f"{account.display_name}: waiting {wait.seconds // 60} more minutes to "
            f"keep {min_gap:g}h between uploads."
        )

    selection = content_service.pick_next_video(account)
    if selection.video is None:
        return None, f"{account.display_name}: {selection.reason}"

    slot = next_publishing_slot(now, settings_service.get("publish_times", ["09:00"]))
    lookahead = int(settings_service.get("queue_lookahead_hours", 24))
    if slot > now + timedelta(hours=lookahead):
        return None, (
            f"{account.display_name}: the next publishing slot is further away than "
            f"the {lookahead}h lookahead."
        )

    job = queue_video(selection.video, account, scheduled_at=slot, automatic=True)
    return job, (
        f"{account.display_name}: queued '{selection.video.title}' for "
        f"{slot:%Y-%m-%d %H:%M} UTC. {selection.reason}"
    )


def plan_automatic_uploads() -> dict:
    """Run the planner for every usable account."""
    if not settings_service.get("automation_enabled", True):
        return {"queued": 0, "messages": ["Automatic publishing is switched off in Settings."]}

    accounts = account_service.usable_accounts()
    if not accounts:
        return {"queued": 0, "messages": ["No connected account is available."]}

    queued = 0
    messages: list[str] = []
    for account in accounts:
        try:
            job, message = plan_for_account(account)
        except Exception as exc:  # one bad account must not stop the others
            log.exception("Planning failed for account %s", account.id)
            messages.append(f"{account.display_name}: planning error - {exc}")
            continue
        messages.append(message)
        if job is not None:
            queued += 1

    for message in messages:
        log.info("Planner: %s", message)
    return {"queued": queued, "messages": messages}
