"""
Runtime settings.

Settings describe *how the operation runs* (how often to publish, how much of
the output must be monetisable) as opposed to *how the machine is wired*
(secrets and paths, which live in .env). They are editable from the web
interface and take effect on the next background run - no restart.

The schema below is the single source of truth: it drives the defaults, the
form rendering, and the coercion of submitted strings back into real types.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.extensions import db
from app.models import Setting

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SettingSpec:
    """Description of one editable setting."""

    key: str
    label: str
    kind: str           # bool | int | float | str | choice | time_list
    default: Any
    group: str
    help: str = ""
    choices: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    minimum: float | None = None
    maximum: float | None = None


# ---------------------------------------------------------------------------
# The catalogue of settings
# ---------------------------------------------------------------------------
SCHEMA: tuple[SettingSpec, ...] = (
    # --- Automation ---------------------------------------------------------
    SettingSpec(
        "automation_enabled", "Automatic publishing", "bool", True, "Automation",
        "Master switch. When off, the bot still collects statistics and "
        "researches trends but never publishes on its own. Manual uploads from "
        "the website always work.",
    ),
    SettingSpec(
        "daily_upload_limit", "Uploads per account per day", "int", 3, "Automation",
        "A hard ceiling that protects both the API quota and the channel: "
        "flooding a new channel with uploads suppresses reach.",
        minimum=0, maximum=50,
    ),
    SettingSpec(
        "publish_times", "Publishing times (UTC)", "time_list", ["09:00", "15:00", "20:00"],
        "Automation",
        "Comma-separated HH:MM slots at which the bot queues its next video. "
        "Spreading uploads across the day beats posting them all at once.",
    ),
    SettingSpec(
        "min_hours_between_uploads", "Minimum hours between uploads", "float", 3.0,
        "Automation",
        "Enforced per account, on top of the publishing times.",
        minimum=0, maximum=48,
    ),
    SettingSpec(
        "queue_lookahead_hours", "Queue lookahead (hours)", "int", 24, "Automation",
        "How far ahead the planner is allowed to schedule jobs.",
        minimum=1, maximum=168,
    ),

    # --- Content policy -----------------------------------------------------
    SettingSpec(
        "monetizable_ratio", "Share of monetisable uploads", "float", 0.8, "Content policy",
        "Fraction of automatically published videos that must be owned or "
        "commercially licensed material. The rest may be royalty-free filler "
        "published purely to attract views. 0.8 means four in five.",
        minimum=0.0, maximum=1.0,
    ),
    SettingSpec(
        "require_rights_confirmation", "Require rights confirmation", "bool", True,
        "Content policy",
        "Refuse to publish any video whose rights a reviewer has not confirmed. "
        "Turning this off risks copyright strikes and demonetisation - leave it on.",
    ),
    SettingSpec(
        "append_shorts_hashtag", "Append #Shorts to the description", "bool", True,
        "Content policy",
        "Helps YouTube classify the upload as a Short.",
    ),
    SettingSpec(
        "include_attribution", "Include attribution in the description", "bool", True,
        "Content policy",
        "Appends the credit line stored on the video. Required by most "
        "royalty-free licences (CC-BY and similar).",
    ),
    SettingSpec(
        "default_privacy", "Default privacy", "choice", "public", "Content policy",
        "Privacy applied to new videos.",
        choices=(("public", "Public"), ("unlisted", "Unlisted"), ("private", "Private")),
    ),
    SettingSpec(
        "default_category_id", "Default YouTube category", "choice", "22", "Content policy",
        "Category assigned to uploads that do not set one.",
        choices=(
            ("1", "Film & Animation"), ("2", "Autos & Vehicles"), ("10", "Music"),
            ("15", "Pets & Animals"), ("17", "Sports"), ("19", "Travel & Events"),
            ("20", "Gaming"), ("22", "People & Blogs"), ("23", "Comedy"),
            ("24", "Entertainment"), ("25", "News & Politics"),
            ("26", "Howto & Style"), ("27", "Education"),
            ("28", "Science & Technology"),
        ),
    ),

    # --- Research -----------------------------------------------------------
    SettingSpec(
        "trend_region", "Trend region", "str", "US", "Research",
        "Two-letter country code the trend research runs against (US, GB, DE, ...).",
    ),
    SettingSpec(
        "trend_results", "Trends stored per run", "int", 25, "Research",
        "How many topics to keep from each research run.",
        minimum=5, maximum=50,
    ),

    # --- Media processing ---------------------------------------------------
    SettingSpec(
        "auto_convert_to_shorts", "Convert uploads to Shorts format", "bool", True,
        "Media processing",
        "Re-encode landscape or over-long uploads into a vertical 1080x1920 "
        "clip with ffmpeg. When off, files that are not already vertical are "
        "flagged instead of converted.",
    ),
    SettingSpec(
        "conversion_mode", "Conversion style", "choice", "blur", "Media processing",
        "How a landscape frame is fitted into a vertical one.",
        choices=(
            ("blur", "Blurred background (keeps the whole frame)"),
            ("crop", "Centre crop (fills the screen, loses the sides)"),
            ("pad", "Black bars"),
        ),
    ),
)

SCHEMA_BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in SCHEMA}
DEFAULTS: dict[str, Any] = {spec.key: spec.default for spec in SCHEMA}


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------
def get(key: str, default: Any = None) -> Any:
    """
    Read a setting.

    Order of precedence: stored value, schema default, explicit *default*.
    Reads never fail - a missing settings table (very early in a first install)
    falls back to defaults so the app can still boot and show its own UI.
    """
    fallback = DEFAULTS.get(key, default)
    try:
        row = db.session.get(Setting, key)
    except Exception as exc:  # database not migrated yet
        log.debug("Settings lookup failed for %r (%s); using default.", key, exc)
        return fallback
    if row is None:
        return fallback
    value = row.value
    return fallback if value is None else value


def set_value(key: str, value: Any, user_id: int | None = None, commit: bool = True) -> None:
    """
    Write a setting (validated and coerced against the schema).

    Named ``set_value`` rather than ``set`` on purpose: a module-level function
    called ``set`` shadows the builtin for every other function in this file,
    which silently breaks anything using ``set(...)`` for deduplication.
    """
    spec = SCHEMA_BY_KEY.get(key)
    if spec is not None:
        value = coerce(spec, value)
    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key)
        db.session.add(row)
    row.value = value
    row.updated_by_id = user_id
    if commit:
        db.session.commit()


def all_values() -> dict[str, Any]:
    """Every setting, defaults filled in - used by the settings page."""
    values = dict(DEFAULTS)
    try:
        for row in db.session.query(Setting).all():
            if row.key in values or row.key in SCHEMA_BY_KEY:
                values[row.key] = row.value
    except Exception as exc:  # pragma: no cover - only before first migration
        log.debug("Could not read settings table: %s", exc)
    return values


def grouped_schema() -> dict[str, list[SettingSpec]]:
    """Settings grouped by section, in catalogue order (drives the form)."""
    groups: dict[str, list[SettingSpec]] = {}
    for spec in SCHEMA:
        groups.setdefault(spec.group, []).append(spec)
    return groups


# ---------------------------------------------------------------------------
# Coercion / validation
# ---------------------------------------------------------------------------
def coerce(spec: SettingSpec, raw: Any) -> Any:
    """
    Turn a submitted form value into the type the setting expects.

    Anything unparsable falls back to the schema default rather than raising:
    a typo in one field must not wipe out the whole settings page.
    """
    try:
        if spec.kind == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in {"1", "true", "yes", "on"}

        if spec.kind == "int":
            value = int(float(raw))
            return int(_clamp(value, spec))

        if spec.kind == "float":
            return float(_clamp(float(raw), spec))

        if spec.kind == "choice":
            allowed = {key for key, _label in spec.choices}
            text = str(raw).strip()
            return text if text in allowed else spec.default

        if spec.kind == "time_list":
            return _parse_times(raw, spec.default)

        return str(raw).strip()
    except (TypeError, ValueError):
        log.warning("Invalid value %r for setting %s; keeping the default.", raw, spec.key)
        return spec.default


def _clamp(value: float, spec: SettingSpec) -> float:
    """Keep a numeric setting inside its documented range."""
    if spec.minimum is not None:
        value = max(spec.minimum, value)
    if spec.maximum is not None:
        value = min(spec.maximum, value)
    return value


def _parse_times(raw: Any, default: list[str]) -> list[str]:
    """Parse "09:00, 15:00" into a sorted list of valid HH:MM strings."""
    if isinstance(raw, (list, tuple)):
        candidates = [str(item) for item in raw]
    else:
        candidates = str(raw).replace(";", ",").split(",")

    times: list[str] = []
    for candidate in candidates:
        text = candidate.strip()
        if not text:
            continue
        parts = text.split(":")
        if len(parts) != 2:
            continue
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            times.append(f"{hour:02d}:{minute:02d}")

    return sorted(set(times)) or list(default)


def ensure_defaults(commit: bool = True) -> None:
    """Write any missing setting rows. Called once by "flask init-db"."""
    changed = False
    for spec in SCHEMA:
        if db.session.get(Setting, spec.key) is None:
            row = Setting(key=spec.key)
            row.value = spec.default
            db.session.add(row)
            changed = True
    if changed and commit:
        db.session.commit()
