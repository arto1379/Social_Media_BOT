"""
Media inspection and Shorts conversion (ffmpeg / ffprobe).

Why this exists: YouTube decides whether an upload is a Short by looking at the
file, not at a flag in the API request. A video is a Short when it is vertical
(taller than it is wide) and at most three minutes long. So the job of getting
"upload in YouTube Short format" right belongs here, before the upload.

Three operations:

* :func:`probe`             - read duration and frame size with ffprobe
* :func:`inspect`           - probe a Video row and record the results on it
* :func:`convert_to_shorts` - re-encode anything that does not already qualify

ffmpeg is called through ``subprocess`` rather than a Python binding: it keeps
the dependency list short, and the exact command line ends up in the log, which
makes a failed conversion something an operator can reproduce by hand.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from flask import current_app

log = logging.getLogger(__name__)

# A long Short is three minutes; conversions are given generous head-room over
# real time before being considered hung.
CONVERSION_TIMEOUT_SECONDS = 60 * 30
PROBE_TIMEOUT_SECONDS = 60


class MediaError(RuntimeError):
    """Raised when ffmpeg/ffprobe is missing or fails."""


@dataclass
class MediaInfo:
    """What ffprobe could tell us about a file."""

    duration_seconds: float
    width: int
    height: int
    has_audio: bool
    size_bytes: int
    format_name: str = ""

    @property
    def is_vertical(self) -> bool:
        """True when the frame is taller than it is wide."""
        return self.height > self.width


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------
def _binary(kind: str) -> str:
    """Resolve the configured ffmpeg/ffprobe path, or raise a useful error."""
    configured = current_app.config.get(
        "FFMPEG_BINARY" if kind == "ffmpeg" else "FFPROBE_BINARY", kind
    )
    resolved = shutil.which(configured) or (configured if Path(configured).is_file() else None)
    if not resolved:
        raise MediaError(
            f"{kind} was not found (looked for {configured!r}). Install it with "
            f"'sudo apt install ffmpeg' on Ubuntu, or set "
            f"{'FFMPEG_BINARY' if kind == 'ffmpeg' else 'FFPROBE_BINARY'} in .env "
            f"to its full path."
        )
    return resolved


def tools_available() -> tuple[bool, str]:
    """
    Check both binaries. Returns ``(ok, message)``.

    The dashboard shows this so a missing ffmpeg is visible as a warning rather
    than as a mysterious failure on the first conversion.
    """
    try:
        _binary("ffmpeg")
        _binary("ffprobe")
        return True, "ffmpeg and ffprobe are available."
    except MediaError as exc:
        return False, str(exc)


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run a command, capturing output, and raise MediaError on failure."""
    log.debug("Running: %s", " ".join(command))
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{command[0]} timed out after {timeout}s.") from exc
    except OSError as exc:
        raise MediaError(f"Could not run {command[0]}: {exc}") from exc

    if result.returncode != 0:
        # ffmpeg puts the real explanation in the last lines of stderr.
        tail = "\n".join((result.stderr or "").strip().splitlines()[-6:])
        raise MediaError(f"{Path(command[0]).name} failed (exit {result.returncode}):\n{tail}")
    return result


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------
def probe(file_path: str | Path) -> MediaInfo:
    """Read duration, frame size and audio presence from a media file."""
    path = Path(file_path)
    if not path.is_file():
        raise MediaError(f"Media file not found: {path}")

    result = _run(
        [
            _binary("ffprobe"),
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        PROBE_TIMEOUT_SECONDS,
    )

    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise MediaError("ffprobe returned output that could not be parsed.") from exc

    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video_stream is None:
        raise MediaError("The file contains no video stream.")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    fmt = data.get("format", {})
    # Duration can live on either the format or the stream depending on codec.
    duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    # A rotation tag means the stored frame is sideways to how it will play,
    # so swap the dimensions to reflect what a viewer actually sees.
    rotation = _rotation_of(video_stream)
    if rotation in (90, 270):
        width, height = height, width

    return MediaInfo(
        duration_seconds=duration,
        width=width,
        height=height,
        has_audio=has_audio,
        size_bytes=int(fmt.get("size") or path.stat().st_size),
        format_name=fmt.get("format_name", ""),
    )


def _rotation_of(stream: dict) -> int:
    """Read the display rotation from tags or side data (0/90/180/270)."""
    tags = stream.get("tags") or {}
    raw = tags.get("rotate")
    if raw is None:
        for entry in stream.get("side_data_list") or []:
            if "rotation" in entry:
                raw = entry["rotation"]
                break
    try:
        return int(abs(float(raw))) % 360 if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def checksum(file_path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 of a file, streamed so a 2 GB upload does not enter memory."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(video, commit: bool = False) -> MediaInfo | None:
    """
    Probe a :class:`~app.models.Video` and record the findings on the row.

    Sets duration/width/height, the ``is_shorts_ready`` flag and human-readable
    ``format_notes``. Returns None (and writes the reason into format_notes)
    when the file cannot be read, so a broken upload shows up in the library
    instead of raising in a request handler.
    """
    from app.models import Video  # local import keeps this module import-light

    assert isinstance(video, Video)
    absolute = media_path(video.file_path)

    try:
        info = probe(absolute)
    except MediaError as exc:
        video.is_shorts_ready = False
        video.format_notes = str(exc)
        if commit:
            from app.extensions import db

            db.session.commit()
        return None

    video.duration_seconds = round(info.duration_seconds, 2)
    video.width = info.width
    video.height = info.height
    video.file_size = info.size_bytes

    problems = shorts_problems(info)
    video.is_shorts_ready = not problems
    video.format_notes = (
        "Ready to publish as a Short."
        if not problems
        else " ".join(problems)
    )

    if commit:
        from app.extensions import db

        db.session.commit()
    return info


def shorts_problems(info: MediaInfo) -> list[str]:
    """Everything about *info* that disqualifies the file as a Short."""
    max_seconds = current_app.config.get("SHORTS_MAX_SECONDS", 180)
    problems: list[str] = []
    if info.duration_seconds <= 0:
        problems.append("Duration could not be determined.")
    elif info.duration_seconds > max_seconds:
        problems.append(
            f"Too long: {info.duration_seconds:.0f}s (Shorts allow {max_seconds}s)."
        )
    if info.width <= 0 or info.height <= 0:
        problems.append("Frame size could not be determined.")
    elif not info.is_vertical:
        problems.append(f"Not vertical: the frame is {info.width}x{info.height}.")
    if not info.has_audio:
        # Not fatal - silent clips are allowed - but worth flagging.
        problems.append("The file has no audio track.")
    return problems


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------
def _video_filter(mode: str, width: int, height: int) -> str:
    """
    Build the ffmpeg filter chain that fits any frame into *width* x *height*.

    * ``crop`` - scale up until the frame covers the canvas, then centre-crop.
      Fills the screen; the sides of a landscape shot are lost.
    * ``pad``  - scale down to fit and add black bars.
    * ``blur`` - the usual Shorts look: a blurred, zoomed copy of the frame as
      the background with the untouched frame centred on top.
    """
    if mode == "crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1"
        )
    if mode == "pad":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )
    # Default: blurred background.
    return (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=luma_radius=30:luma_power=2[bg];"
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )


def convert_to_shorts(
    source: str | Path,
    destination: str | Path,
    mode: str = "blur",
    max_seconds: int | None = None,
) -> MediaInfo:
    """
    Re-encode *source* into a vertical, correctly sized, trimmed Short.

    Returns the :class:`MediaInfo` of the produced file. The output is H.264 +
    AAC in an MP4 with ``+faststart``, which every platform accepts.
    """
    source_path = Path(source)
    dest_path = Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    width = current_app.config.get("SHORTS_TARGET_WIDTH", 1080)
    height = current_app.config.get("SHORTS_TARGET_HEIGHT", 1920)
    limit = max_seconds or current_app.config.get("SHORTS_MAX_SECONDS", 180)

    filter_chain = _video_filter(mode, width, height)
    # A multi-input graph needs -filter_complex; a linear chain uses -vf.
    filter_flag = "-filter_complex" if "[bg]" in filter_chain else "-vf"

    command = [
        _binary("ffmpeg"),
        "-y",                      # overwrite the destination
        "-i", str(source_path),
        filter_flag, filter_chain,
        "-t", str(limit),          # hard trim to the Shorts limit
        "-r", "30",                # normalise frame rate
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "21",              # visually lossless enough for mobile
        "-pix_fmt", "yuv420p",     # required for playback on all devices
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-movflags", "+faststart", # metadata first, so playback starts sooner
        str(dest_path),
    ]

    log.info("Converting %s -> %s (mode=%s)", source_path.name, dest_path.name, mode)
    _run(command, CONVERSION_TIMEOUT_SECONDS)
    return probe(dest_path)


def extract_thumbnail(
    source: str | Path, destination: str | Path, at_second: float = 1.0
) -> Path:
    """Grab a single frame as a JPEG, used as a fallback thumbnail."""
    dest_path = Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        _binary("ffmpeg"),
        "-y",
        "-ss", str(max(at_second, 0)),
        "-i", str(source),
        "-frames:v", "1",
        "-q:v", "3",
        str(dest_path),
    ]
    _run(command, PROBE_TIMEOUT_SECONDS)
    return dest_path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def media_path(relative: str | None) -> Path:
    """
    Resolve a stored (relative) media path against MEDIA_ROOT.

    Paths are stored relative so the whole media directory can be moved to a
    bigger disk without a database migration.
    """
    root = Path(current_app.config["MEDIA_ROOT"])
    if not relative:
        return root
    candidate = Path(relative)
    return candidate if candidate.is_absolute() else root / candidate


def relative_media_path(absolute: str | Path) -> str:
    """Inverse of :func:`media_path`, with forward slashes for portability."""
    root = Path(current_app.config["MEDIA_ROOT"])
    try:
        return Path(absolute).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # Outside MEDIA_ROOT - store the absolute path rather than lie about it.
        return Path(absolute).as_posix()
