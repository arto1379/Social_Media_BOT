"""
Configuration objects.

Everything the application needs to know about its environment is read here,
in one place, from environment variables (usually supplied by the .env file).
No other module is allowed to call ``os.environ`` for configuration, so that
"what can I tune?" always has a single answer: this file plus .env.example.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Absolute path of the repository root (this file lives in <root>/app/).
BASE_DIR = Path(__file__).resolve().parent.parent

# Load <root>/.env into os.environ. Values already present in the real
# environment win, which lets systemd/Docker override the file.
load_dotenv(BASE_DIR / ".env", override=False)


# ---------------------------------------------------------------------------
# Small helpers for reading typed values out of the environment
# ---------------------------------------------------------------------------
def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env var. Accepts 1/true/yes/on (case-insensitive)."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Read an integer env var, falling back to *default* if unset/invalid."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_path(name: str, default: str) -> Path:
    """
    Read a filesystem path env var.

    Relative values are resolved against the repository root so that the app
    behaves the same no matter which directory systemd starts it from.
    """
    raw = os.environ.get(name, "").strip() or default
    path = Path(raw)
    return path if path.is_absolute() else (BASE_DIR / path)


# ---------------------------------------------------------------------------
# Base configuration - shared by every environment
# ---------------------------------------------------------------------------
class BaseConfig:
    """Settings common to development, testing and production."""

    # --- Identity -----------------------------------------------------------
    APP_NAME = "Social Media BOT"
    BASE_DIR = BASE_DIR

    # --- Secrets ------------------------------------------------------------
    # SECRET_KEY signs session cookies and CSRF tokens.
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    # ENCRYPTION_KEY (Fernet) encrypts OAuth refresh tokens before they are
    # written to the database. See app/security/crypto.py.
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

    # --- Public address -----------------------------------------------------
    # Used to build absolute URLs (OAuth redirect URIs, e-mail links, ...).
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

    # --- Database -----------------------------------------------------------
    # Default: SQLite inside DATA_ROOT. Overridden by DATABASE_URL.
    DATA_ROOT = _env_path("DATA_ROOT", "data")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_ROOT / 'socialbot.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,  # drop dead connections instead of erroring
    }

    # --- Storage ------------------------------------------------------------
    MEDIA_ROOT = _env_path("MEDIA_ROOT", "media")
    LOG_ROOT = _env_path("LOG_ROOT", "logs")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Flask rejects request bodies larger than this (bytes).
    MAX_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 2048)
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024

    # Video container formats the web upload form accepts.
    ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
    ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

    # --- Session / cookie hardening ----------------------------------------
    BEHIND_PROXY = _env_bool("BEHIND_PROXY", True)
    FORCE_HTTPS = _env_bool("FORCE_HTTPS", True)
    SESSION_COOKIE_NAME = "socialbot_session"
    SESSION_COOKIE_HTTPONLY = True          # JavaScript cannot read the cookie
    SESSION_COOKIE_SAMESITE = "Lax"         # blocks most CSRF vectors
    SESSION_COOKIE_SECURE = FORCE_HTTPS     # HTTPS-only when TLS is in use
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = FORCE_HTTPS
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12   # 12 hours
    WTF_CSRF_TIME_LIMIT = None                  # CSRF token lives with session

    # --- Login throttling ---------------------------------------------------
    # After this many consecutive failures an account is locked for a while.
    LOGIN_MAX_FAILURES = _env_int("LOGIN_MAX_FAILURES", 8)
    LOGIN_LOCKOUT_MINUTES = _env_int("LOGIN_LOCKOUT_MINUTES", 15)

    # --- ffmpeg -------------------------------------------------------------
    FFMPEG_BINARY = os.environ.get("FFMPEG_BINARY", "ffmpeg")
    FFPROBE_BINARY = os.environ.get("FFPROBE_BINARY", "ffprobe")

    # --- Background scheduler ----------------------------------------------
    SCHEDULER_ENABLED = _env_bool("SCHEDULER_ENABLED", True)
    UPLOAD_POLL_MINUTES = _env_int("UPLOAD_POLL_MINUTES", 5)
    STATS_INTERVAL_MINUTES = _env_int("STATS_INTERVAL_MINUTES", 180)
    TREND_INTERVAL_HOURS = _env_int("TREND_INTERVAL_HOURS", 6)

    # --- YouTube ------------------------------------------------------------
    YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
    YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
    YOUTUBE_TREND_REGION = os.environ.get("YOUTUBE_TREND_REGION", "US").upper()

    # --- Shorts format constraints -----------------------------------------
    # YouTube treats a video as a Short when it is vertical (or square) and at
    # most 3 minutes long. These numbers drive both validation and the ffmpeg
    # conversion in app/services/video_processing.py.
    SHORTS_MAX_SECONDS = 180
    SHORTS_TARGET_WIDTH = 1080
    SHORTS_TARGET_HEIGHT = 1920

    # --- Monetisation policy ------------------------------------------------
    # Share of automatically published videos that must come from monetisable
    # (owned or commercially licensed) assets. The remainder may be
    # royalty-free filler used purely to gather views. Editable in the UI.
    DEFAULT_MONETIZABLE_RATIO = 0.8

    # --- First administrator (consumed by "flask create-admin") ------------
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

    # Overridden by subclasses.
    DEBUG = False
    TESTING = False
    ENV_NAME = "base"


class ProductionConfig(BaseConfig):
    """Hardened settings for a real server. Refuses to start without secrets."""

    ENV_NAME = "production"
    DEBUG = False


class DevelopmentConfig(BaseConfig):
    """Local development: debug on, TLS-only cookies off."""

    ENV_NAME = "development"
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    FORCE_HTTPS = False


class TestingConfig(BaseConfig):
    """Used by the pytest suite: in-memory DB, no CSRF, no scheduler."""

    ENV_NAME = "testing"
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SCHEDULER_ENABLED = False
    SESSION_COOKIE_SECURE = False
    FORCE_HTTPS = False
    SECRET_KEY = "testing-secret-key"
    # Deterministic Fernet key so tests can encrypt/decrypt without setup.
    ENCRYPTION_KEY = "dGVzdGluZy1mZXJuZXQta2V5LTMyLWJ5dGVzLWxvbmc="


# Maps APP_ENV values to the class that implements them.
CONFIG_BY_NAME = {
    "production": ProductionConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
}


def get_config(name: str | None = None) -> type[BaseConfig]:
    """
    Resolve a configuration class.

    *name* wins if given, otherwise APP_ENV, otherwise production (safe
    default: an unconfigured server should behave strictly, not loosely).
    """
    key = (name or os.environ.get("APP_ENV") or "production").strip().lower()
    return CONFIG_BY_NAME.get(key, ProductionConfig)
