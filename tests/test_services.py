"""
Supporting services: settings, encryption, Shorts format rules and statistics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.security.crypto import EncryptionError, decrypt_json, encrypt_json, mask_secret
from app.services import settings_service, stats_service, video_processing
from app.services.video_processing import MediaInfo


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def test_missing_setting_falls_back_to_the_schema_default(app):
    assert settings_service.get("monetizable_ratio") == 0.8


def test_setting_round_trips(db):
    settings_service.set_value("daily_upload_limit", 7)
    assert settings_service.get("daily_upload_limit") == 7


def test_numeric_settings_are_clamped(db):
    """A typo in the form must not schedule 500 uploads a day."""
    settings_service.set_value("daily_upload_limit", 9999)
    assert settings_service.get("daily_upload_limit") == 50

    settings_service.set_value("monetizable_ratio", 5)
    assert settings_service.get("monetizable_ratio") == 1.0


def test_checkbox_values_are_coerced(db):
    spec = settings_service.SCHEMA_BY_KEY["automation_enabled"]
    assert settings_service.coerce(spec, "on") is True
    assert settings_service.coerce(spec, "false") is False


def test_publish_times_are_parsed_and_sorted(db):
    spec = settings_service.SCHEMA_BY_KEY["publish_times"]
    assert settings_service.coerce(spec, "20:00, 09:00 , 15:30") == ["09:00", "15:30", "20:00"]


def test_invalid_times_are_dropped(db):
    spec = settings_service.SCHEMA_BY_KEY["publish_times"]
    assert settings_service.coerce(spec, "09:00, 99:99, banana") == ["09:00"]


def test_all_invalid_times_fall_back_to_the_default(db):
    """An empty schedule would silently stop publishing - refuse to store it."""
    spec = settings_service.SCHEMA_BY_KEY["publish_times"]
    assert settings_service.coerce(spec, "banana") == spec.default


def test_unknown_choice_falls_back(db):
    spec = settings_service.SCHEMA_BY_KEY["default_privacy"]
    assert settings_service.coerce(spec, "world-readable") == "public"


# ---------------------------------------------------------------------------
# Encryption of stored tokens
# ---------------------------------------------------------------------------
def test_credentials_are_encrypted_at_rest(app, account):
    """The stored blob must not contain the token in readable form."""
    assert "refresh_token" not in (account.credentials_encrypted or "")
    assert account.get_credentials()["refresh_token"] == "y"


def test_json_encryption_round_trips(app):
    payload = {"token": "abc", "scopes": ["one", "two"]}
    assert decrypt_json(encrypt_json(payload)) == payload


def test_decryption_fails_loudly_with_the_wrong_key(app):
    """A rotated ENCRYPTION_KEY must produce a clear error, not garbage."""
    ciphertext = encrypt_json({"token": "abc"})
    app.config["ENCRYPTION_KEY"] = "b3RoZXIta2V5LTMyLWJ5dGVzLWxvbmctZXhhY3RseSE="
    with pytest.raises(EncryptionError, match="ENCRYPTION_KEY changed"):
        decrypt_json(ciphertext)


def test_mask_secret_keeps_only_the_edges():
    assert mask_secret("abcdefghijklmnop") == "abcd...mnop"
    assert mask_secret("short") == "*****"
    assert mask_secret(None) == "-"


# ---------------------------------------------------------------------------
# Shorts format rules
# ---------------------------------------------------------------------------
def _info(**overrides) -> MediaInfo:
    defaults = dict(
        duration_seconds=45.0, width=1080, height=1920,
        has_audio=True, size_bytes=1024,
    )
    defaults.update(overrides)
    return MediaInfo(**defaults)


def test_a_vertical_short_clip_passes(app):
    assert video_processing.shorts_problems(_info()) == []


def test_landscape_video_is_rejected(app):
    problems = video_processing.shorts_problems(_info(width=1920, height=1080))
    assert any("Not vertical" in problem for problem in problems)


def test_square_video_is_rejected(app):
    """Square is not vertical - YouTube will not treat it as a Short."""
    problems = video_processing.shorts_problems(_info(width=1080, height=1080))
    assert any("Not vertical" in problem for problem in problems)


def test_over_long_video_is_rejected(app):
    problems = video_processing.shorts_problems(_info(duration_seconds=240))
    assert any("Too long" in problem for problem in problems)


def test_exactly_three_minutes_is_allowed(app):
    """180 seconds is the documented limit, so it must not be off by one."""
    assert video_processing.shorts_problems(_info(duration_seconds=180.0)) == []


def test_silent_video_is_flagged(app):
    problems = video_processing.shorts_problems(_info(has_audio=False))
    assert any("no audio" in problem for problem in problems)


def test_media_path_stays_inside_media_root(app):
    """Stored paths are relative so the media directory can be moved."""
    resolved = video_processing.media_path("uploads/clip.mp4")
    assert resolved == app.config["MEDIA_ROOT"] / "uploads" / "clip.mp4"


def test_relative_media_path_is_the_inverse(app):
    absolute = app.config["MEDIA_ROOT"] / "uploads" / "clip.mp4"
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.touch()
    assert video_processing.relative_media_path(absolute) == "uploads/clip.mp4"


# ---------------------------------------------------------------------------
# Statistics aggregation
# ---------------------------------------------------------------------------
def test_totals_use_only_the_newest_snapshot(db, account, make_video):
    """Snapshots accumulate; the totals must not sum a video's whole history."""
    from app.models import StatSnapshot

    video = make_video()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.add_all([
        StatSnapshot(
            platform="youtube", account_id=account.id, video_id=video.id,
            remote_id="abc", views=100, likes=5, captured_at=now - timedelta(days=2),
        ),
        StatSnapshot(
            platform="youtube", account_id=account.id, video_id=video.id,
            remote_id="abc", views=450, likes=22, captured_at=now,
        ),
    ])
    db.session.commit()

    totals = stats_service.totals()
    assert totals["views"] == 450
    assert totals["likes"] == 22
    assert totals["tracked_videos"] == 1


def test_totals_break_down_by_platform(db, account, make_video):
    from app.models import StatSnapshot

    video = make_video()
    db.session.add(
        StatSnapshot(
            platform="youtube", account_id=account.id, video_id=video.id,
            remote_id="abc", views=200, likes=10,
        )
    )
    db.session.commit()

    assert stats_service.totals()["by_platform"]["youtube"]["views"] == 200


def test_old_snapshots_are_pruned(db, account, make_video):
    from app.models import StatSnapshot

    video = make_video()
    db.session.add_all([
        StatSnapshot(
            platform="youtube", video_id=video.id, views=1,
            captured_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=500),
        ),
        StatSnapshot(platform="youtube", video_id=video.id, views=2),
    ])
    db.session.commit()

    assert stats_service.prune_old_snapshots(keep_days=400) == 1
    assert db.session.query(StatSnapshot).count() == 1


def test_empty_database_produces_zero_totals(app):
    """The dashboard must render on a fresh install, not divide by zero."""
    totals = stats_service.totals()
    assert totals["views"] == 0
    assert totals["by_platform"] == {}
    assert totals["last_collected"] is None
