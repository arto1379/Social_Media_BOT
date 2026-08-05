"""
The video library.

Covers the manual half of the PRD: "upload should happen automatically in the
background, but the user should be able to add a video manually through the
website". Adding a video here does four things:

1. stores the file under MEDIA_ROOT with a collision-proof name;
2. inspects it with ffprobe and records duration and frame size;
3. converts it to vertical Shorts format when it does not already qualify;
4. leaves it as a draft until somebody confirms the rights.

Step 4 is not bureaucracy. Publishing footage you do not own is what gets a
channel struck and demonetised, so approval is a separate, audited action.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import (
    LicenseType,
    Trend,
    UploadJob,
    UploadStatus,
    Video,
    VideoStatus,
)
from app.security.access import Permission, permission_required
from app.services import (
    account_service,
    audit_service,
    content_service,
    settings_service,
    stats_service,
    upload_service,
    video_processing,
)
from app.services.settings_service import SCHEMA_BY_KEY
from app.services.video_processing import MediaError
from app.web.forms import (
    CSRFOnlyForm,
    QueueUploadForm,
    RightsConfirmationForm,
    VideoEditForm,
    VideoUploadForm,
)

log = logging.getLogger(__name__)

bp = Blueprint("videos", __name__, template_folder="../templates")

# How many videos one page of the library shows.
PAGE_SIZE = 25


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _category_choices() -> list[tuple[str, str]]:
    """YouTube categories, taken from the settings schema so there is one list."""
    return list(SCHEMA_BY_KEY["default_category_id"].choices)


def _unique_filename(original: str, suffix: str = "") -> str:
    """
    Build a safe, unique filename.

    ``secure_filename`` strips directory traversal and exotic characters; the
    uuid prefix means two people uploading "clip.mp4" cannot overwrite each
    other.
    """
    cleaned = secure_filename(original) or "upload.mp4"
    return f"{uuid.uuid4().hex[:12]}{suffix}_{cleaned}"


# ---------------------------------------------------------------------------
# Library listing
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@permission_required(Permission.VIEW_VIDEOS)
def index():
    """Browse the library with search and filters."""
    page = max(request.args.get("page", 1, type=int), 1)
    status_filter = request.args.get("status", "").strip()
    license_filter = request.args.get("license", "").strip()
    search = request.args.get("q", "").strip()

    query = db.session.query(Video)
    if status_filter:
        query = query.filter(Video.status == status_filter)
    if license_filter:
        query = query.filter(Video.license_type == license_filter)
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(Video.title.ilike(pattern), Video.tags.ilike(pattern)))

    pagination = query.order_by(Video.created_at.desc()).paginate(
        page=page, per_page=PAGE_SIZE, error_out=False
    )

    return render_template(
        "videos/index.html",
        pagination=pagination,
        videos=pagination.items,
        latest_stats=stats_service.latest_video_stats(),
        library=content_service.library_summary(),
        status_filter=status_filter,
        license_filter=license_filter,
        search=search,
        statuses=VideoStatus.ALL,
        licenses=LicenseType.ALL,
        license_labels=LicenseType.LABELS,
    )


# ---------------------------------------------------------------------------
# Adding a video
# ---------------------------------------------------------------------------
@bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(Permission.MANAGE_VIDEOS)
def create():
    """Upload a video file and register it in the library."""
    form = VideoUploadForm()
    form.category_id.choices = _category_choices()

    # Pre-fill from a trend when arriving via "make a video about this".
    trend = None
    trend_id = request.args.get("trend_id", type=int) or form.trend_id.data
    if trend_id:
        trend = db.session.get(Trend, int(trend_id))
        if trend and request.method == "GET":
            suggestion = content_service.suggest_metadata_from_trend(trend)
            form.title.data = suggestion["title"]
            form.description.data = suggestion["description"]
            form.tags.data = suggestion["tags"]
            form.trend_id.data = str(trend.id)

    if form.validate_on_submit():
        media_root: Path = current_app.config["MEDIA_ROOT"]
        upload_dir = media_root / "uploads"
        filename = _unique_filename(form.video_file.data.filename)
        absolute_path = upload_dir / filename

        try:
            form.video_file.data.save(absolute_path)
        except OSError as exc:
            log.exception("Could not save uploaded file")
            flash(f"The file could not be saved: {exc}", "danger")
            return render_template("videos/form.html", form=form, video=None, trend=trend)

        video = Video(
            title=form.title.data.strip(),
            description=(form.description.data or "").strip(),
            tags=(form.tags.data or "").strip(),
            category_id=form.category_id.data,
            privacy=form.privacy.data,
            language=(form.language.data or "en").strip(),
            made_for_kids=form.made_for_kids.data,
            file_path=video_processing.relative_media_path(absolute_path),
            license_type=form.license_type.data,
            license_source=(form.license_source.data or "").strip(),
            license_reference=(form.license_reference.data or "").strip(),
            attribution=(form.attribution.data or "").strip(),
            source=form.source.data,
            status=VideoStatus.DRAFT,
            created_by_id=current_user.id,
            trend_id=int(form.trend_id.data) if (form.trend_id.data or "").isdigit() else None,
        )
        db.session.add(video)
        db.session.commit()

        # --- Optional thumbnail --------------------------------------------
        if form.thumbnail_file.data:
            _save_thumbnail(video, form.thumbnail_file.data)

        # --- Inspect, and convert if asked ---------------------------------
        _inspect_and_maybe_convert(video, convert=form.convert.data)
        db.session.commit()

        audit_service.record(
            "video.create", target_type="video", target_id=video.id,
            detail=f"Added '{video.title}' ({video.license_label}).",
        )
        flash(
            "Video added. Confirm its rights to make it publishable."
            if not video.rights_confirmed
            else "Video added.",
            "success",
        )
        return redirect(url_for("videos.detail", video_id=video.id))

    return render_template("videos/form.html", form=form, video=None, trend=trend)


def _save_thumbnail(video: Video, file_storage) -> None:
    """Store an uploaded thumbnail next to the video."""
    media_root: Path = current_app.config["MEDIA_ROOT"]
    filename = _unique_filename(file_storage.filename, suffix="_thumb")
    absolute = media_root / "thumbnails" / filename
    try:
        file_storage.save(absolute)
    except OSError as exc:
        log.warning("Could not save thumbnail: %s", exc)
        flash(f"The thumbnail could not be saved: {exc}", "warning")
        return
    video.thumbnail_path = video_processing.relative_media_path(absolute)
    db.session.commit()


def _inspect_and_maybe_convert(video: Video, convert: bool) -> None:
    """
    Probe the file and, when needed and allowed, re-encode it as a Short.

    Conversion runs inline. A Short is at most three minutes, so this is
    typically seconds to a minute - but it is why the deployment sets a
    generous gunicorn timeout (see deploy/socialbot.service).
    """
    info = video_processing.inspect(video)
    if info is None:
        flash(
            f"The file could not be inspected: {video.format_notes}",
            "warning",
        )
        return

    if video.is_shorts_ready:
        video.status = VideoStatus.READY if video.rights_confirmed else VideoStatus.DRAFT
        return

    if not convert or not settings_service.get("auto_convert_to_shorts", True):
        flash(
            "The file is not in Shorts format and was left untouched: "
            f"{video.format_notes}",
            "warning",
        )
        return

    media_root: Path = current_app.config["MEDIA_ROOT"]
    destination = media_root / "processed" / f"{uuid.uuid4().hex[:12]}_short.mp4"
    mode = settings_service.get("conversion_mode", "blur")

    try:
        video_processing.convert_to_shorts(
            video_processing.media_path(video.file_path), destination, mode=mode
        )
    except MediaError as exc:
        log.warning("Conversion failed for video %s: %s", video.id, exc)
        video.format_notes = f"Conversion failed: {exc}"
        flash(f"The video could not be converted: {exc}", "danger")
        return

    video.file_path = video_processing.relative_media_path(destination)
    video_processing.inspect(video)
    if video.is_shorts_ready:
        flash(f"The video was converted to vertical 1080x1920 ({mode}).", "info")
        video.status = VideoStatus.READY if video.rights_confirmed else VideoStatus.DRAFT


# ---------------------------------------------------------------------------
# Viewing and editing
# ---------------------------------------------------------------------------
@bp.route("/<int:video_id>")
@login_required
@permission_required(Permission.VIEW_VIDEOS)
def detail(video_id: int):
    """Everything about one video: metadata, format, rights, upload history."""
    video = db.session.get(Video, video_id) or abort(404)

    queue_form = QueueUploadForm()
    accounts = account_service.usable_accounts()
    queue_form.account_id.choices = [
        (account.id, f"{account.display_name} ({account.platform})") for account in accounts
    ]

    return render_template(
        "videos/detail.html",
        video=video,
        jobs=video.upload_jobs.order_by(UploadJob.created_at.desc()).all(),
        history=stats_service.video_history(video.id),
        latest_stat=stats_service.latest_video_stats().get(video.id),
        queue_form=queue_form,
        rights_form=RightsConfirmationForm(),
        action_form=CSRFOnlyForm(),
        has_accounts=bool(accounts),
    )


@bp.route("/<int:video_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(Permission.MANAGE_VIDEOS)
def edit(video_id: int):
    """Edit a video's metadata."""
    video = db.session.get(Video, video_id) or abort(404)
    form = VideoEditForm(obj=video)
    form.category_id.choices = _category_choices()

    if form.validate_on_submit():
        # Changing the licence invalidates a previous rights confirmation:
        # the reviewer approved the old claim, not the new one.
        license_changed = form.license_type.data != video.license_type

        form.populate_obj(video)
        if license_changed:
            video.rights_confirmed = False
            video.rights_confirmed_by_id = None
            video.rights_confirmed_at = None
            if video.status in (VideoStatus.READY, VideoStatus.SCHEDULED):
                video.status = VideoStatus.DRAFT
            flash(
                "The licence changed, so the rights confirmation was cleared. "
                "Confirm the rights again before publishing.",
                "warning",
            )

        if form.thumbnail_file.data:
            _save_thumbnail(video, form.thumbnail_file.data)

        db.session.commit()
        audit_service.record(
            "video.update", target_type="video", target_id=video.id,
            detail=f"Edited '{video.title}'.",
        )
        flash("Changes saved.", "success")
        return redirect(url_for("videos.detail", video_id=video.id))

    return render_template("videos/form.html", form=form, video=video, trend=video.trend)


@bp.route("/<int:video_id>/confirm-rights", methods=["POST"])
@login_required
@permission_required(Permission.PUBLISH_VIDEOS)
def confirm_rights(video_id: int):
    """
    Record that a named reviewer takes responsibility for this footage.

    Refused for unverified licences: there is nothing to confirm until somebody
    has written down where the material came from.
    """
    video = db.session.get(Video, video_id) or abort(404)
    form = RightsConfirmationForm()

    if not form.validate_on_submit():
        flash("Tick the confirmation box first.", "warning")
        return redirect(url_for("videos.detail", video_id=video.id))

    if video.license_type == LicenseType.UNVERIFIED:
        flash(
            "Set the rights field to owned, licensed or royalty-free first, and "
            "record where the material came from.",
            "danger",
        )
        return redirect(url_for("videos.detail", video_id=video.id))

    video.rights_confirmed = True
    video.rights_confirmed_by_id = current_user.id
    video.rights_confirmed_at = _utcnow()
    if video.status == VideoStatus.DRAFT and video.is_shorts_ready:
        video.status = VideoStatus.READY
    db.session.commit()

    audit_service.record(
        "video.rights_confirmed", target_type="video", target_id=video.id,
        detail=f"{current_user.username} confirmed rights for '{video.title}' "
               f"({video.license_label}, source: {video.license_source or 'not stated'}).",
    )
    flash("Rights confirmed. The video can now be published.", "success")
    return redirect(url_for("videos.detail", video_id=video.id))


@bp.route("/<int:video_id>/convert", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_VIDEOS)
def convert(video_id: int):
    """Re-run the Shorts conversion on an existing video."""
    video = db.session.get(Video, video_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)

    _inspect_and_maybe_convert(video, convert=True)
    db.session.commit()
    audit_service.record(
        "video.convert", target_type="video", target_id=video.id,
        detail=f"Re-ran Shorts conversion: {video.format_notes}",
    )
    flash(video.format_notes or "Conversion finished.", "info")
    return redirect(url_for("videos.detail", video_id=video.id))


@bp.route("/<int:video_id>/queue", methods=["POST"])
@login_required
@permission_required(Permission.PUBLISH_VIDEOS)
def queue(video_id: int):
    """Queue this video for publishing on a chosen account."""
    video = db.session.get(Video, video_id) or abort(404)

    form = QueueUploadForm()
    accounts = account_service.usable_accounts()
    form.account_id.choices = [(account.id, account.display_name) for account in accounts]

    if not form.validate_on_submit():
        flash("Choose an account to publish to.", "warning")
        return redirect(url_for("videos.detail", video_id=video.id))

    account = next((a for a in accounts if a.id == form.account_id.data), None)
    if account is None:
        flash("That account is not available.", "danger")
        return redirect(url_for("videos.detail", video_id=video.id))

    scheduled_at = None
    if form.when.data == "slot":
        scheduled_at = upload_service.next_publishing_slot(
            _utcnow(), settings_service.get("publish_times", ["09:00"])
        )

    try:
        job = upload_service.queue_video(
            video, account, scheduled_at=scheduled_at, user=current_user
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("videos.detail", video_id=video.id))

    flash(
        f"Queued for {account.display_name} at {job.scheduled_at:%Y-%m-%d %H:%M} UTC. "
        f"The background worker will publish it.",
        "success",
    )
    return redirect(url_for("videos.detail", video_id=video.id))


@bp.route("/<int:video_id>/delete", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_VIDEOS)
def delete(video_id: int):
    """
    Delete a video from the library.

    Only the local record and files are removed - anything already published
    stays on the platform, which is deliberate: deleting a live video is a
    separate, more consequential action.
    """
    video = db.session.get(Video, video_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)

    open_jobs = video.upload_jobs.filter(
        UploadJob.status.in_((UploadStatus.RUNNING,))
    ).count()
    if open_jobs:
        flash("This video is being uploaded right now. Wait for it to finish.", "warning")
        return redirect(url_for("videos.detail", video_id=video.id))

    title = video.title
    # Remove the files; a missing file is not an error worth stopping for.
    for relative in (video.file_path, video.thumbnail_path):
        if not relative:
            continue
        try:
            path = video_processing.media_path(relative)
            if path.is_file():
                path.unlink()
        except OSError as exc:
            log.warning("Could not delete %s: %s", relative, exc)

    db.session.delete(video)
    db.session.commit()
    audit_service.record(
        "video.delete", target_type="video", target_id=video_id,
        detail=f"Deleted '{title}' from the library.",
    )
    flash(f"'{title}' was deleted from the library.", "info")
    return redirect(url_for("videos.index"))


# ---------------------------------------------------------------------------
# Media serving
# ---------------------------------------------------------------------------
@bp.route("/media/<path:relative_path>")
@login_required
@permission_required(Permission.VIEW_VIDEOS)
def media(relative_path: str):
    """
    Serve a file from MEDIA_ROOT for preview in the browser.

    ``send_from_directory`` refuses paths that escape the directory, so a
    crafted ``../../etc/passwd`` returns 404 rather than a file.
    """
    media_root: Path = current_app.config["MEDIA_ROOT"]
    return send_from_directory(media_root, relative_path, conditional=True)


# ---------------------------------------------------------------------------
# Job actions
# ---------------------------------------------------------------------------
@bp.route("/jobs")
@login_required
@permission_required(Permission.VIEW_VIDEOS)
def jobs():
    """The upload queue and its history."""
    page = max(request.args.get("page", 1, type=int), 1)
    pagination = (
        db.session.query(UploadJob)
        .order_by(UploadJob.created_at.desc())
        .paginate(page=page, per_page=PAGE_SIZE, error_out=False)
    )
    return render_template(
        "videos/jobs.html",
        pagination=pagination,
        jobs=pagination.items,
        action_form=CSRFOnlyForm(),
    )


@bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
@login_required
@permission_required(Permission.PUBLISH_VIDEOS)
def cancel_job(job_id: int):
    """Cancel a queued upload."""
    job = db.session.get(UploadJob, job_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)
    try:
        upload_service.cancel_job(job, user=current_user)
        flash("The upload was cancelled.", "info")
    except ValueError as exc:
        flash(str(exc), "warning")
    return redirect(request.referrer or url_for("videos.jobs"))


@bp.route("/jobs/<int:job_id>/retry", methods=["POST"])
@login_required
@permission_required(Permission.PUBLISH_VIDEOS)
def retry_job(job_id: int):
    """Put a failed upload back in the queue."""
    job = db.session.get(UploadJob, job_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)
    try:
        upload_service.retry_job(job, user=current_user)
        flash("The upload was requeued.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    return redirect(request.referrer or url_for("videos.jobs"))
