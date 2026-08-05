"""
Application factory.

``create_app()`` is the single place where the pieces are assembled:
configuration, extensions, blueprints, CLI commands, error pages, security
headers and the background scheduler. Everything else in the project is
importable without side effects, which is what makes the test suite able to
build a throwaway application in one line.
"""

from __future__ import annotations

import logging
import os
import sys

from flask import Flask, current_app, redirect, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import BaseConfig, get_config
from app.extensions import csrf, db, login_manager, migrate
from app.logging_setup import configure_logging

log = logging.getLogger(__name__)

__version__ = "1.0.0"


def create_app(config_name: str | None = None) -> Flask:
    """Build and return a fully configured Flask application."""
    app = Flask(__name__, instance_relative_config=False)
    config_class = get_config(config_name)
    app.config.from_object(config_class)

    _prepare_directories(app)
    configure_logging(app)
    _check_secrets(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_cli(app)
    _register_error_handlers(app)
    _register_request_hooks(app)
    _register_template_helpers(app)
    _start_scheduler(app)

    log.info(
        "%s %s started in %s mode.",
        app.config["APP_NAME"], __version__, app.config["ENV_NAME"],
    )
    return app


# ---------------------------------------------------------------------------
# Start-up steps
# ---------------------------------------------------------------------------
def _prepare_directories(app: Flask) -> None:
    """Create the media/data/log directories before anything tries to use them."""
    for key in ("MEDIA_ROOT", "DATA_ROOT", "LOG_ROOT"):
        path = app.config[key]
        path.mkdir(parents=True, exist_ok=True)
    # Sub-folders used by the upload form and the converter.
    (app.config["MEDIA_ROOT"] / "uploads").mkdir(exist_ok=True)
    (app.config["MEDIA_ROOT"] / "processed").mkdir(exist_ok=True)
    (app.config["MEDIA_ROOT"] / "thumbnails").mkdir(exist_ok=True)


def _check_secrets(app: Flask) -> None:
    """
    Refuse to run a production server with missing or placeholder secrets.

    A default SECRET_KEY means anybody can forge a session cookie, and a
    missing ENCRYPTION_KEY means OAuth tokens cannot be stored at all - both
    are worth failing loudly at boot rather than quietly at 3 a.m.
    """
    if app.config["ENV_NAME"] != "production":
        # Development and tests get a throwaway key so the app just runs.
        app.config.setdefault("SECRET_KEY", "dev-secret-key")
        if not app.config.get("SECRET_KEY"):
            app.config["SECRET_KEY"] = "dev-secret-key"
        return

    problems: list[str] = []
    secret = app.config.get("SECRET_KEY", "")
    if not secret or secret.startswith("change-me") or len(secret) < 32:
        problems.append(
            "SECRET_KEY is missing or too short. Generate one with:\n"
            '    python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    encryption = app.config.get("ENCRYPTION_KEY", "")
    if not encryption or encryption.startswith("change-me"):
        problems.append(
            "ENCRYPTION_KEY is missing. Generate one with:\n"
            '    python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )

    if problems:
        message = (
            "\n\nRefusing to start in production with an insecure configuration:\n\n"
            + "\n\n".join(f"  * {problem}" for problem in problems)
            + "\n\nEdit the .env file and try again. To run locally without "
              "these checks, set APP_ENV=development.\n"
        )
        print(message, file=sys.stderr)
        raise SystemExit(2)


def _init_extensions(app: Flask) -> None:
    """Bind the extension singletons to this application."""
    # Behind nginx, trust one layer of X-Forwarded-* headers so url_for()
    # builds https:// links and the audit log records the real client IP.
    if app.config.get("BEHIND_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Importing the models registers them with SQLAlchemy's metadata.
    from app import models  # noqa: F401
    # Importing the platform package registers the adapters.
    from app import platforms  # noqa: F401


def _register_blueprints(app: Flask) -> None:
    """Attach every part of the web interface."""
    from app.web.accounts import bp as accounts_bp
    from app.web.api import bp as api_bp
    from app.web.auth import bp as auth_bp
    from app.web.dashboard import bp as dashboard_bp
    from app.web.settings import bp as settings_bp
    from app.web.stats import bp as stats_bp
    from app.web.trends import bp as trends_bp
    from app.web.users import bp as users_bp
    from app.web.videos import bp as videos_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(videos_bp, url_prefix="/videos")
    app.register_blueprint(accounts_bp, url_prefix="/accounts")
    app.register_blueprint(stats_bp, url_prefix="/statistics")
    app.register_blueprint(trends_bp, url_prefix="/trends")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(api_bp, url_prefix="/api")

    # The JSON API authenticates with the session cookie and is read-mostly;
    # its POST endpoints do their own token check, so exempt the blueprint
    # from the form-oriented CSRF handling.
    csrf.exempt(api_bp)


def _register_cli(app: Flask) -> None:
    """Register the ``flask ...`` management commands."""
    from app.cli import register_commands

    register_commands(app)


def _register_error_handlers(app: Flask) -> None:
    """Friendly error pages instead of Werkzeug's default output."""

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template(
            "errors/error.html",
            code=403,
            title="Not allowed",
            message="Your account does not have permission to open that page. "
                    "Ask an administrator to grant it.",
        ), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template(
            "errors/error.html",
            code=404,
            title="Page not found",
            message="That page does not exist.",
        ), 404

    @app.errorhandler(413)
    def too_large(_error):
        limit = current_app.config.get("MAX_UPLOAD_MB", 2048)
        return render_template(
            "errors/error.html",
            code=413,
            title="File too large",
            message=f"The upload exceeds the {limit} MB limit. Raise "
                    f"MAX_UPLOAD_MB in .env and client_max_body_size in the "
                    f"nginx configuration if you need more.",
        ), 413

    @app.errorhandler(500)
    def server_error(error):
        log.exception("Unhandled server error: %s", error)
        db.session.rollback()
        return render_template(
            "errors/error.html",
            code=500,
            title="Something went wrong",
            message="The error has been written to the log. Check it with "
                    "'journalctl -u socialbot -n 100' or in the logs directory.",
        ), 500


def _register_request_hooks(app: Flask) -> None:
    """Cross-cutting request behaviour: HTTPS, password changes, headers."""
    from app.security.access import enforce_password_change

    @app.before_request
    def _force_https():
        """
        Redirect http:// to https:// as a backstop.

        nginx already does this in the recommended deployment; the check here
        covers a misconfigured proxy and costs one comparison per request.
        """
        if not app.config.get("FORCE_HTTPS"):
            return None
        if request.is_secure or request.endpoint == "dashboard.health":
            return None
        forwarded = request.headers.get("X-Forwarded-Proto", "")
        if forwarded == "https":
            return None
        return redirect(request.url.replace("http://", "https://", 1), code=301)

    # Force a password change on first login (see app/security/access.py).
    app.before_request(enforce_password_change)

    @app.after_request
    def _security_headers(response):
        """
        Standard hardening headers.

        The CSP is strict because the interface ships its own CSS and
        JavaScript - nothing is loaded from a CDN, which also means the site
        works on a server with no outbound internet access.
        """
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "  # inline styles size the charts
            "script-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        if app.config.get("FORCE_HTTPS"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def _register_template_helpers(app: Flask) -> None:
    """Globals and filters the templates rely on."""
    from datetime import datetime, timezone

    from app.security import permissions as perms
    from app.services import settings_service

    @app.context_processor
    def _inject_globals():
        return {
            "app_name": app.config["APP_NAME"],
            "app_version": __version__,
            "Permission": perms.Permission,
            "current_year": datetime.now(timezone.utc).year,
        }

    @app.template_filter("datetime")
    def _format_datetime(value, fmt: str = "%Y-%m-%d %H:%M"):
        """Render a stored naive-UTC timestamp, or a dash when it is missing."""
        if not value:
            return "-"
        return value.strftime(fmt)

    @app.template_filter("since")
    def _format_since(value):
        """Human "3 hours ago" style relative time."""
        if not value:
            return "never"
        delta = datetime.now(timezone.utc).replace(tzinfo=None) - value
        seconds = int(delta.total_seconds())
        if seconds < 0:
            return "in the future"
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60} min ago"
        if seconds < 86400:
            return f"{seconds // 3600} h ago"
        return f"{seconds // 86400} d ago"

    @app.template_filter("number")
    def _format_number(value):
        """Thousands separators for view counts."""
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return "0"

    @app.template_filter("duration")
    def _format_duration(seconds):
        """Seconds as m:ss, used in the video library."""
        try:
            total = int(float(seconds))
        except (TypeError, ValueError):
            return "-"
        return f"{total // 60}:{total % 60:02d}"

    @app.template_filter("filesize")
    def _format_filesize(value):
        """Bytes as a readable size."""
        try:
            size = float(value)
        except (TypeError, ValueError):
            return "-"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    @app.template_global("setting")
    def _setting(key, default=None):
        """Read a runtime setting from a template."""
        return settings_service.get(key, default)


#: Set by run.py in the Werkzeug reloader's supervising process so that only
#: the child which actually serves requests owns the scheduler.
SKIP_SCHEDULER_ENV = "SOCIALBOT_SKIP_SCHEDULER"


def _start_scheduler(app: Flask) -> None:
    """
    Start background automation, unless this process should not run it.

    Exactly one process may hold the scheduler - two would plan the same
    upload twice and publish the video twice. So there are four guards:

    * ``SCHEDULER_ENABLED=0`` - the web service on a real server, where the
      separate worker process owns the schedule;
    * tests, which must never start background threads;
    * ``SOCIALBOT_SKIP_SCHEDULER=1`` - set by run.py in the reloader's parent
      process (see the comment there);
    * any ``flask ...`` management command. Those are one-shot and do not need
      it; ``flask run`` is not a supported way to run this application either -
      use ``python run.py`` in development and worker.py in production.
    """
    if not app.config.get("SCHEDULER_ENABLED", True):
        return
    if app.config.get("TESTING"):
        return
    if os.environ.get(SKIP_SCHEDULER_ENV) == "1":
        return
    if os.path.basename(sys.argv[0]) in ("flask", "flask.exe"):
        return

    from app.services import scheduler_service

    scheduler_service.start(app)


__all__ = ["BaseConfig", "create_app", "__version__"]
