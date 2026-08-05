"""
Management commands.

Run them with the ``flask`` launcher from the project directory::

    flask init-db                 create tables, roles and default settings
    flask create-admin            create the first administrator
    flask reset-password <user>   set a new password for somebody
    flask list-users              show accounts and their access
    flask run-job <job>           run a background job once, in the foreground
    flask check                   diagnose the configuration

The deployment scripts call the first two; the rest exist for the moments when
the web interface is exactly what you cannot get to.
"""

from __future__ import annotations

import getpass
import secrets
import sys

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.security import permissions as perms


def register_commands(app) -> None:
    """Attach every command to *app* (called by the application factory)."""
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_admin_command)
    app.cli.add_command(reset_password_command)
    app.cli.add_command(list_users_command)
    app.cli.add_command(seed_roles_command)
    app.cli.add_command(run_job_command)
    app.cli.add_command(check_command)


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
@click.command("init-db")
@click.option("--drop", is_flag=True, help="Drop every table first. Destroys all data.")
@with_appcontext
def init_db_command(drop: bool):
    """Create the database schema, the built-in roles and default settings."""
    from app.services import settings_service

    if drop:
        click.confirm(
            "This deletes every table and everything in them. Continue?", abort=True
        )
        db.drop_all()
        click.echo("Dropped all tables.")

    db.create_all()
    click.echo("Database schema is up to date.")
    _stamp_migrations()

    created = _seed_roles()
    if created:
        click.echo(f"Created built-in roles: {', '.join(created)}.")

    settings_service.ensure_defaults()
    click.echo("Default settings written.")
    click.echo("\nNext: create the first administrator with 'flask create-admin'.")


def _stamp_migrations() -> None:
    """
    Record the schema as being at the latest migration.

    ``init-db`` builds the tables with ``create_all()`` rather than by replaying
    migrations, which is faster and needs no history on a fresh install. But
    Alembic would then see an empty version table, and the first
    ``flask db upgrade`` after an upgrade would try to create tables that
    already exist. Stamping tells it "this database is already at head".
    """
    from flask import current_app

    migrations_dir = current_app.config["BASE_DIR"] / "migrations"
    if not (migrations_dir / "env.py").exists():
        return  # no migration history in this checkout - nothing to stamp

    try:
        from flask_migrate import stamp

        stamp(directory=str(migrations_dir), revision="head")
        click.echo("Migration history stamped at head.")
    except Exception as exc:  # never block a working install over bookkeeping
        click.echo(f"(Could not stamp the migration history: {exc})", err=True)


def _seed_roles() -> list[str]:
    """Create the built-in roles that do not exist yet."""
    from app.models import Role

    created: list[str] = []
    for name, (description, mask) in perms.DEFAULT_ROLES.items():
        role = db.session.query(Role).filter(Role.name == name).first()
        if role is None:
            db.session.add(
                Role(name=name, description=description, permissions=mask, is_system=True)
            )
            created.append(name)
        elif role.is_system:
            # Keep built-in roles current when new permissions are added in an
            # upgrade, but leave custom roles alone.
            role.permissions = mask
            role.description = description
    db.session.commit()
    return created


@click.command("seed-roles")
@with_appcontext
def seed_roles_command():
    """Create or refresh the built-in roles."""
    created = _seed_roles()
    click.echo(
        f"Created: {', '.join(created)}." if created else "Built-in roles are up to date."
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@click.command("create-admin")
@click.option("--username", default=None, help="Username. Defaults to ADMIN_USERNAME from .env.")
@click.option("--password", default=None, help="Password. Prompted for if omitted.")
@click.option("--email", default=None, help="Optional email address.")
@click.option(
    "--generate-password",
    is_flag=True,
    help="Generate a random password and print it once. The user must change it "
         "at first sign-in.",
)
@with_appcontext
def create_admin_command(username, password, email, generate_password):
    """
    Create the first administrator.

    This is what the PRD means by "one admin user/pass should be set up at
    deployment time". Reads ADMIN_USERNAME/ADMIN_PASSWORD from .env when no
    flags are given, so the Ubuntu installer can run it unattended.
    """
    from flask import current_app

    from app.models import Role, User

    username = username or current_app.config.get("ADMIN_USERNAME") or "admin"

    existing = db.session.query(User).filter(User.username == username).first()
    if existing is not None:
        click.echo(
            f"User '{username}' already exists. Use 'flask reset-password "
            f"{username}' to change the password.",
            err=True,
        )
        sys.exit(1)

    must_change = False
    if generate_password:
        # 4 random words would be friendlier, but a token needs no word list.
        password = secrets.token_urlsafe(18)
        must_change = True
    if not password:
        password = current_app.config.get("ADMIN_PASSWORD") or ""
    if not password:
        password = getpass.getpass("Password for the administrator: ")
        repeat = getpass.getpass("Repeat the password: ")
        if password != repeat:
            click.echo("The passwords do not match.", err=True)
            sys.exit(1)

    if len(password) < 12:
        click.echo("Use a password of at least 12 characters.", err=True)
        sys.exit(1)

    _seed_roles()
    admin_role = db.session.query(Role).filter(Role.name == "Administrator").first()

    user = User(
        username=username,
        email=email,
        full_name="Administrator",
        role_id=admin_role.id if admin_role else None,
        is_admin=True,
        active=True,
        must_change_password=must_change,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    click.echo(f"Administrator '{username}' created.")
    if generate_password:
        click.echo("")
        click.echo(f"  Password: {password}")
        click.echo("")
        click.echo("Write it down now - it is not stored anywhere and will not be")
        click.echo("shown again. You will be asked to change it at first sign-in.")


@click.command("reset-password")
@click.argument("username")
@click.option("--password", default=None, help="New password. Prompted for if omitted.")
@with_appcontext
def reset_password_command(username: str, password: str | None):
    """Set a new password for USERNAME and clear any lockout."""
    from app.models import User

    user = db.session.query(User).filter(User.username == username).first()
    if user is None:
        click.echo(f"No user named '{username}'.", err=True)
        sys.exit(1)

    if not password:
        password = getpass.getpass(f"New password for {username}: ")
        repeat = getpass.getpass("Repeat the password: ")
        if password != repeat:
            click.echo("The passwords do not match.", err=True)
            sys.exit(1)

    if len(password) < 12:
        click.echo("Use a password of at least 12 characters.", err=True)
        sys.exit(1)

    user.set_password(password)
    user.failed_logins = 0
    user.locked_until = None
    user.active = True
    db.session.commit()
    click.echo(f"Password for '{username}' has been reset and the account unlocked.")


@click.command("list-users")
@with_appcontext
def list_users_command():
    """List every user with their role and state."""
    from app.models import User

    users = db.session.query(User).order_by(User.username).all()
    if not users:
        click.echo("No users exist. Create one with 'flask create-admin'.")
        return

    click.echo(f"{'USERNAME':<20} {'ROLE':<18} {'ADMIN':<7} {'STATE':<10} LAST SIGN-IN")
    click.echo("-" * 78)
    for user in users:
        state = "disabled" if not user.active else ("locked" if user.is_locked else "active")
        last = user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else "never"
        click.echo(
            f"{user.username:<20} {user.role_name:<18} "
            f"{'yes' if user.is_admin else 'no':<7} {state:<10} {last}"
        )


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------
@click.command("run-job")
@click.argument("job_id")
@with_appcontext
def run_job_command(job_id: str):
    """
    Run one background job in the foreground.

    Job ids: upload_queue, collect_statistics, research_trends, maintenance.
    Useful for testing a fresh install without waiting for the scheduler.
    """
    from app.services import scheduler_service

    if job_id not in scheduler_service.MANUAL_JOBS:
        click.echo(
            f"Unknown job '{job_id}'. Available: "
            f"{', '.join(scheduler_service.MANUAL_JOBS)}.",
            err=True,
        )
        sys.exit(1)

    label, _func = scheduler_service.MANUAL_JOBS[job_id]
    click.echo(f"Running: {label} ...")
    try:
        result = scheduler_service.run_now(job_id)
    except Exception as exc:
        click.echo(f"The job failed: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Finished: {result}")


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
@click.command("check")
@with_appcontext
def check_command():
    """
    Check the configuration and report what is missing.

    Run this first when something does not work - it covers the handful of
    problems behind most failed installs.
    """
    from flask import current_app

    from app.models import PlatformAccount, User
    from app.platforms import all_adapters
    from app.services import video_processing

    problems = 0

    def report(ok: bool, title: str, fix: str = "", info: str = "") -> None:
        """
        Print one check.

        *fix* is shown only when the check fails and *info* only when it
        passes, so a clean run reads as a short list of ticks rather than a
        wall of advice for problems that do not exist.
        """
        nonlocal problems
        click.echo(f"[{'OK  ' if ok else 'FAIL'}] {title}")
        detail = info if ok else fix
        if detail:
            click.echo(f"       {detail}")
        if not ok:
            problems += 1

    click.echo(f"\n{current_app.config['APP_NAME']} configuration check")
    click.echo("=" * 60)

    # --- Secrets ------------------------------------------------------------
    secret = current_app.config.get("SECRET_KEY", "")
    report(
        bool(secret) and not secret.startswith("change-me") and len(secret) >= 32,
        "SECRET_KEY is set and long enough",
        fix='Generate one: python -c "import secrets; print(secrets.token_urlsafe(48))"',
    )
    encryption = current_app.config.get("ENCRYPTION_KEY", "")
    report(
        bool(encryption) and not encryption.startswith("change-me"),
        "ENCRYPTION_KEY is set",
        fix='Generate one: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"',
    )

    # --- Database -----------------------------------------------------------
    user_count = None
    try:
        db.session.execute(db.text("SELECT 1"))
        user_count = db.session.query(User).count()
        report(True, "Database reachable", info=f"{user_count} user(s) registered.")
    except Exception as exc:
        report(False, "Database reachable", fix=f"{exc}. Run 'flask init-db'.")

    if user_count is not None:
        report(
            user_count > 0,
            "At least one user exists",
            fix="Run 'flask create-admin'.",
        )

    # --- Media tools --------------------------------------------------------
    ffmpeg_ok, ffmpeg_message = video_processing.tools_available()
    report(
        ffmpeg_ok,
        "ffmpeg and ffprobe available",
        fix=ffmpeg_message,
        info="Videos can be inspected and converted to Shorts format.",
    )

    # --- Platforms ----------------------------------------------------------
    for adapter in all_adapters():
        report(
            adapter.is_configured(),
            f"{adapter.display_name} API credentials",
            fix=adapter.configuration_hint(),
        )

    if user_count is not None:
        connected = (
            db.session.query(PlatformAccount)
            .filter(PlatformAccount.credentials_encrypted.isnot(None))
            .count()
        )
        report(
            connected > 0,
            "At least one account connected",
            fix="Connect one from the Accounts page in the web interface.",
            info=f"{connected} account(s) connected.",
        )

    # --- Public URL ---------------------------------------------------------
    base = current_app.config.get("PUBLIC_BASE_URL", "")
    report(
        base.startswith("https://") or current_app.config["ENV_NAME"] != "production",
        "PUBLIC_BASE_URL uses https",
        fix=f"Currently {base!r}. It must be the https address of this site and "
            f"match the OAuth redirect URI registered with the platform.",
        info=base,
    )

    click.echo("=" * 60)
    if problems:
        click.echo(f"{problems} problem(s) found. See CONFIGURE.md for the fixes.\n")
        sys.exit(1)
    click.echo("Everything checks out.\n")
