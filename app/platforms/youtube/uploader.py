"""
Resumable video upload.

Uploads run in chunks through Google's resumable protocol. Two reasons:

* a Short is small but a server's uplink is not always reliable, and a chunked
  transfer survives a hiccup instead of restarting from byte zero;
* ``next_chunk()`` reports progress, which is what the queue page shows.

There is no separate "publish as a Short" API call. YouTube classifies a video
as a Short automatically when it is vertical and at most three minutes long -
so the work of making Shorts happens in app/services/video_processing.py, and
this module just uploads the resulting file.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from googleapiclient.http import MediaFileUpload

from app.platforms.base import PlatformError, UploadResult
from app.platforms.youtube.client import build_data_service, execute, translate_error

log = logging.getLogger(__name__)

# 4 MB per request: large enough to keep overhead low, small enough that a
# retry after a dropped connection is cheap.
CHUNK_SIZE = 4 * 1024 * 1024

# Number of times a single chunk is retried before the whole attempt fails.
# The job-level retry in the upload service handles anything beyond this.
MAX_CHUNK_RETRIES = 5

WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
SHORTS_URL = "https://www.youtube.com/shorts/{video_id}"


def _build_body(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Translate normalised metadata into the Data API's ``videos.insert`` body.

    Field limits enforced here (title 100 chars, description 5000, 500 tag
    characters) match YouTube's own limits - exceeding them is a hard 400.
    """
    title = (metadata.get("title") or "Untitled").strip()[:100]
    description = (metadata.get("description") or "").strip()[:5000]

    # Tags share a 500-character budget; drop the tail rather than be rejected.
    tags: list[str] = []
    budget = 500
    for tag in metadata.get("tags") or []:
        tag = str(tag).strip()
        if not tag:
            continue
        if len(tag) + 1 > budget:
            break
        tags.append(tag)
        budget -= len(tag) + 1

    body: dict[str, Any] = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": str(metadata.get("category_id") or "22"),
            "defaultLanguage": metadata.get("language") or "en",
            "defaultAudioLanguage": metadata.get("language") or "en",
        },
        "status": {
            "privacyStatus": metadata.get("privacy") or "public",
            # Required field since 2020; the value comes from the video form.
            "selfDeclaredMadeForKids": bool(metadata.get("made_for_kids")),
            "license": metadata.get("license") or "youtube",
            "embeddable": True,
        },
    }

    # Optional scheduled publication (requires privacyStatus=private).
    publish_at = metadata.get("publish_at")
    if publish_at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at

    return body


def upload_video(
    credentials_blob: dict[str, Any],
    file_path: str,
    metadata: dict[str, Any],
    progress_callback: Callable[[int], None] | None = None,
) -> UploadResult:
    """
    Upload *file_path* to YouTube and return its id and URL.

    *progress_callback* receives an integer percentage after each chunk; the
    upload service uses it to keep the queue page live.
    """
    if not os.path.isfile(file_path):
        raise PlatformError(f"Media file not found: {file_path}")

    service = build_data_service(credentials_blob)
    body = _build_body(metadata)

    media = MediaFileUpload(
        file_path,
        chunksize=CHUNK_SIZE,
        resumable=True,
        mimetype="video/*",
    )
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
        # Ask the API to report progress on the way in.
        notifySubscribers=bool(metadata.get("notify_subscribers", True)),
    )

    response: dict[str, Any] | None = None
    consecutive_errors = 0
    last_percent = -1

    while response is None:
        try:
            status, response = request.next_chunk()
            consecutive_errors = 0
            if status and progress_callback:
                percent = int(status.progress() * 100)
                # Only report real movement - avoids hammering the database.
                if percent != last_percent:
                    last_percent = percent
                    progress_callback(percent)
        except Exception as exc:
            translated = translate_error(exc, "uploading video")
            # Permanent problems (bad metadata, revoked token) abort at once;
            # transient ones are retried a few times inside this attempt.
            from app.platforms.base import PlatformRetryableError

            if not isinstance(translated, PlatformRetryableError):
                raise translated from exc
            consecutive_errors += 1
            if consecutive_errors >= MAX_CHUNK_RETRIES:
                raise translated from exc
            log.warning(
                "Chunk failed (%s/%s), retrying: %s",
                consecutive_errors,
                MAX_CHUNK_RETRIES,
                translated,
            )

    video_id = response.get("id")
    if not video_id:
        raise PlatformError(f"YouTube accepted the upload but returned no id: {response}")

    if progress_callback:
        progress_callback(100)

    log.info("Uploaded video %s (%s)", video_id, metadata.get("title"))
    return UploadResult(
        remote_id=video_id,
        # Shorts URL: YouTube redirects to /watch when the video is not a Short,
        # so this link is correct either way.
        remote_url=SHORTS_URL.format(video_id=video_id),
        raw=response,
    )


def set_thumbnail(credentials_blob: dict[str, Any], video_id: str, image_path: str) -> None:
    """Attach a custom thumbnail (channel must be verified for this to work)."""
    if not os.path.isfile(image_path):
        raise PlatformError(f"Thumbnail file not found: {image_path}")
    service = build_data_service(credentials_blob)
    media = MediaFileUpload(image_path, mimetype="image/*")
    execute(
        service.thumbnails().set(videoId=video_id, media_body=media),
        "setting thumbnail",
    )
    log.info("Thumbnail set for video %s", video_id)


def delete_video(credentials_blob: dict[str, Any], video_id: str) -> None:
    """Remove a video from YouTube (used by the "unpublish" action)."""
    service = build_data_service(credentials_blob)
    execute(service.videos().delete(id=video_id), "deleting video")
    log.info("Deleted YouTube video %s", video_id)
