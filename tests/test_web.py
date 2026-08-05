"""
Web interface behaviour.

Authentication, access control and that every page actually renders. The
render checks are shallow on purpose - they catch the broken template or bad
url_for that a unit test never would.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def test_anonymous_visitors_are_sent_to_the_login_page(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_login_succeeds_with_the_right_password(client, admin):
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "correct-horse-battery-staple"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Dashboard" in response.data


def test_login_fails_with_the_wrong_password(client, admin):
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "wrong"},
        follow_redirects=True,
    )
    assert response.status_code == 401
    assert b"not correct" in response.data


def test_login_does_not_reveal_whether_a_user_exists(client, admin):
    """Both failure modes must produce the same message."""
    unknown = client.post(
        "/auth/login", data={"username": "nobody", "password": "x"}, follow_redirects=True
    )
    wrong = client.post(
        "/auth/login", data={"username": "admin", "password": "x"}, follow_redirects=True
    )
    assert b"That username or password is not correct." in unknown.data
    assert b"That username or password is not correct." in wrong.data


def test_repeated_failures_lock_the_account(client, admin, db, app):
    """Brute forcing has to become expensive."""
    limit = app.config["LOGIN_MAX_FAILURES"]
    for _ in range(limit):
        client.post("/auth/login", data={"username": "admin", "password": "wrong"})

    assert admin.is_locked
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "correct-horse-battery-staple"},
        follow_redirects=True,
    )
    assert b"temporarily locked" in response.data


def test_disabled_account_cannot_sign_in(client, admin, db):
    admin.active = False
    db.session.commit()
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "correct-horse-battery-staple"},
        follow_redirects=True,
    )
    assert b"disabled" in response.data


def test_open_redirect_is_refused(client, admin):
    """?next= must not be able to bounce a signed-in user off-site."""
    response = client.post(
        "/auth/login?next=https://evil.example/steal",
        data={"username": "admin", "password": "correct-horse-battery-staple"},
        follow_redirects=False,
    )
    assert "evil.example" not in response.headers.get("Location", "")


def test_forced_password_change_blocks_the_rest_of_the_site(client, admin, db):
    admin.must_change_password = True
    db.session.commit()
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "correct-horse-battery-staple"},
    )
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/password" in response.headers["Location"]


def test_logout_requires_a_post(logged_in_admin):
    """A GET logout link could be triggered by an image tag on another site."""
    assert logged_in_admin.get("/auth/logout").status_code == 405


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def test_analyst_cannot_reach_user_administration(client, analyst):
    client.post(
        "/auth/login", data={"username": "analyst", "password": "read-only-passphrase"}
    )
    assert client.get("/users/").status_code == 403


def test_analyst_cannot_reach_settings(client, analyst):
    client.post(
        "/auth/login", data={"username": "analyst", "password": "read-only-passphrase"}
    )
    assert client.get("/settings/").status_code == 403


def test_analyst_can_read_statistics(client, analyst):
    client.post(
        "/auth/login", data={"username": "analyst", "password": "read-only-passphrase"}
    )
    assert client.get("/statistics/").status_code == 200


def test_navigation_hides_what_a_user_cannot_open(client, analyst):
    client.post(
        "/auth/login", data={"username": "analyst", "password": "read-only-passphrase"}
    )
    body = client.get("/statistics/").data
    assert b"Users &amp; roles" not in body
    assert b"Statistics" in body


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------
def test_every_main_page_renders(logged_in_admin, account, make_video):
    """A broken template or a bad url_for shows up here immediately."""
    video = make_video()
    pages = [
        "/",
        "/videos/",
        "/videos/new",
        f"/videos/{video.id}",
        f"/videos/{video.id}/edit",
        "/videos/jobs",
        "/accounts/",
        "/accounts/new",
        "/statistics/",
        "/trends/",
        "/users/",
        "/users/new",
        "/users/roles/new",
        "/users/audit",
        "/settings/",
        "/auth/profile",
        "/auth/password",
    ]
    for path in pages:
        response = logged_in_admin.get(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}"


def test_json_api_endpoints_answer(logged_in_admin):
    for path in ("/api/queue", "/api/stats/summary", "/api/library", "/api/scheduler"):
        response = logged_in_admin.get(path)
        assert response.status_code == 200
        assert response.is_json


def test_health_endpoint_is_public(client):
    """Monitoring must not need a session."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_missing_page_renders_the_error_template(logged_in_admin):
    response = logged_in_admin.get("/videos/999999")
    assert response.status_code == 404
    assert b"Page not found" in response.data


def test_security_headers_are_present(client):
    headers = client.get("/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in headers


# ---------------------------------------------------------------------------
# Rights workflow through the web interface
# ---------------------------------------------------------------------------
def test_confirming_rights_makes_a_draft_publishable(logged_in_admin, db, make_video):
    from app.models import LicenseType, VideoStatus

    video = make_video(
        rights_confirmed=False,
        status=VideoStatus.DRAFT,
        license_type=LicenseType.OWNED,
    )

    response = logged_in_admin.post(
        f"/videos/{video.id}/confirm-rights", data={"confirm": "y"}, follow_redirects=True
    )

    assert response.status_code == 200
    db.session.refresh(video)
    assert video.rights_confirmed is True
    assert video.status == VideoStatus.READY


def test_unverified_licence_cannot_be_confirmed(logged_in_admin, db, make_video):
    from app.models import LicenseType

    video = make_video(rights_confirmed=False, license_type=LicenseType.UNVERIFIED)

    response = logged_in_admin.post(
        f"/videos/{video.id}/confirm-rights", data={"confirm": "y"}, follow_redirects=True
    )

    db.session.refresh(video)
    assert video.rights_confirmed is False
    assert b"owned, licensed or royalty-free" in response.data


def test_actions_are_recorded_in_the_audit_log(logged_in_admin, db, make_video):
    from app.models import AuditLog

    video = make_video(rights_confirmed=False)
    logged_in_admin.post(f"/videos/{video.id}/confirm-rights", data={"confirm": "y"})

    entry = (
        db.session.query(AuditLog)
        .filter(AuditLog.action == "video.rights_confirmed")
        .first()
    )
    assert entry is not None
    assert entry.username == "admin"
