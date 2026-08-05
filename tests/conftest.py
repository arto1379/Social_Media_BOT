"""
Shared pytest fixtures.

Each test gets a throwaway application backed by a temporary SQLite file and a
temporary media directory, so tests never touch the developer's real database
or media library and can run in any order.

A file-backed SQLite database is used rather than ``:memory:`` because
SQLAlchemy hands out a fresh in-memory database per connection, which makes
anything involving more than one session behave surprisingly.
"""

from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Role, User
from app.security import permissions as perms


@pytest.fixture()
def app(tmp_path):
    """A configured application with an empty database."""
    application = create_app("testing")
    application.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}",
        MEDIA_ROOT=tmp_path / "media",
        DATA_ROOT=tmp_path / "data",
        LOG_ROOT=tmp_path / "logs",
        WTF_CSRF_ENABLED=False,
        SERVER_NAME="localhost",
        # Pretend the YouTube OAuth client is configured. No network call is
        # ever made in the tests, but pages that offer "connect an account"
        # only render when at least one platform has credentials.
        YOUTUBE_CLIENT_ID="test-client-id.apps.googleusercontent.com",
        YOUTUBE_CLIENT_SECRET="test-client-secret",
    )
    for key in ("MEDIA_ROOT", "DATA_ROOT", "LOG_ROOT"):
        application.config[key].mkdir(parents=True, exist_ok=True)

    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    """The SQLAlchemy session, bound to the test application."""
    return _db


@pytest.fixture()
def client(app):
    """A Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def roles(db):
    """The three built-in roles."""
    created = {}
    for name, (description, mask) in perms.DEFAULT_ROLES.items():
        role = Role(name=name, description=description, permissions=mask, is_system=True)
        db.session.add(role)
        created[name] = role
    db.session.commit()
    return created


@pytest.fixture()
def admin(db, roles):
    """An administrator with every permission."""
    user = User(
        username="admin",
        full_name="Test Administrator",
        role_id=roles["Administrator"].id,
        is_admin=True,
        active=True,
    )
    user.set_password("correct-horse-battery-staple")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def analyst(db, roles):
    """A read-only user - useful for checking that access control bites."""
    user = User(
        username="analyst",
        role_id=roles["Analyst"].id,
        is_admin=False,
        active=True,
    )
    user.set_password("read-only-passphrase")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def logged_in_admin(client, admin):
    """A test client with an authenticated administrator session."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "correct-horse-battery-staple"},
        follow_redirects=True,
    )
    return client


# ---------------------------------------------------------------------------
# Content fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def account(db, admin):
    """A connected YouTube account (with a dummy credential blob)."""
    from app.models import PlatformAccount

    entry = PlatformAccount(
        platform="youtube",
        display_name="Test channel",
        remote_id="UC_test_channel",
        is_active=True,
        is_default=True,
        created_by_id=admin.id,
    )
    entry.set_credentials({"token": "x", "refresh_token": "y", "scopes": []})
    db.session.add(entry)
    db.session.commit()
    return entry


@pytest.fixture()
def make_video(db, admin):
    """
    Factory for publishable videos.

    Defaults produce a video that passes every publishing check, so a test only
    has to state the one attribute it cares about.
    """
    from app.models import LicenseType, Video, VideoStatus

    def _make(**overrides):
        defaults = dict(
            title="Test video",
            description="A test video.",
            tags="test, demo",
            file_path="uploads/test.mp4",
            duration_seconds=45.0,
            width=1080,
            height=1920,
            is_shorts_ready=True,
            license_type=LicenseType.OWNED,
            license_source="Filmed in-house",
            rights_confirmed=True,
            status=VideoStatus.READY,
            created_by_id=admin.id,
        )
        defaults.update(overrides)
        video = Video(**defaults)
        db.session.add(video)
        db.session.commit()
        return video

    return _make
