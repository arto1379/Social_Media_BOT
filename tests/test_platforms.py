"""
The platform plugin layer.

These tests protect the extension point the PRD asks for: "for this version
only YouTube, with potential to add other social media". They check the
registry contract and the pieces of the YouTube adapter that can be exercised
without a network call.
"""

from __future__ import annotations

import pytest

from app.platforms import PlatformAdapter, all_adapters, get_adapter
from app.platforms.registry import UnknownPlatform
from app.platforms.youtube import trends as yt_trends
from app.platforms.youtube.uploader import _build_body


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def test_youtube_is_registered(app):
    adapter = get_adapter("youtube")
    assert isinstance(adapter, PlatformAdapter)
    assert adapter.display_name == "YouTube"


def test_unknown_platform_raises_a_helpful_error(app):
    with pytest.raises(UnknownPlatform, match="known: youtube"):
        get_adapter("myspace")


def test_every_adapter_implements_the_contract(app):
    """A half-finished adapter should fail here, not at 3 a.m. mid-upload."""
    for adapter in all_adapters():
        assert adapter.name
        assert adapter.display_name
        for method in (
            "is_configured", "start_authorization", "complete_authorization",
            "fetch_account_info", "refresh_credentials", "upload_video",
            "fetch_video_metrics", "fetch_channel_metrics",
        ):
            assert callable(getattr(adapter, method)), f"{adapter.name} lacks {method}"


def test_is_configured_reflects_the_environment(app):
    adapter = get_adapter("youtube")
    app.config["YOUTUBE_CLIENT_ID"] = ""
    app.config["YOUTUBE_CLIENT_SECRET"] = ""
    assert adapter.is_configured() is False

    app.config["YOUTUBE_CLIENT_ID"] = "id.apps.googleusercontent.com"
    app.config["YOUTUBE_CLIENT_SECRET"] = "secret"
    assert adapter.is_configured() is True


# ---------------------------------------------------------------------------
# Short-form validation shared by every adapter
# ---------------------------------------------------------------------------
def test_short_form_validation_accepts_a_vertical_clip(app):
    assert get_adapter("youtube").validate_short_form(45.0, 1080, 1920) == []


def test_short_form_validation_rejects_landscape(app):
    problems = get_adapter("youtube").validate_short_form(45.0, 1920, 1080)
    assert any("vertical" in problem for problem in problems)


def test_short_form_validation_rejects_long_video(app):
    problems = get_adapter("youtube").validate_short_form(400.0, 1080, 1920)
    assert any("limit is 180" in problem for problem in problems)


def test_short_form_validation_handles_an_uninspected_file(app):
    assert get_adapter("youtube").validate_short_form(None, None, None) == [
        "The media file has not been inspected yet."
    ]


# ---------------------------------------------------------------------------
# Upload payload construction
# ---------------------------------------------------------------------------
def test_upload_body_truncates_a_long_title():
    """YouTube rejects titles over 100 characters with a hard 400."""
    body = _build_body({"title": "x" * 200})
    assert len(body["snippet"]["title"]) == 100


def test_upload_body_respects_the_tag_character_budget():
    """Tags share a 500 character budget; the tail is dropped, not the request."""
    body = _build_body({"title": "t", "tags": ["a" * 100] * 10})
    joined = sum(len(tag) + 1 for tag in body["snippet"]["tags"])
    assert joined <= 500
    assert len(body["snippet"]["tags"]) < 10


def test_upload_body_sets_the_required_kids_declaration():
    """selfDeclaredMadeForKids is mandatory - a missing value is an API error."""
    body = _build_body({"title": "t"})
    assert body["status"]["selfDeclaredMadeForKids"] is False


def test_scheduled_publication_forces_private():
    """publishAt is only honoured when the video starts private."""
    body = _build_body({"title": "t", "privacy": "public", "publish_at": "2026-09-01T09:00:00Z"})
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-09-01T09:00:00Z"


def test_empty_tags_are_dropped():
    body = _build_body({"title": "t", "tags": ["good", "  ", ""]})
    assert body["snippet"]["tags"] == ["good"]


# ---------------------------------------------------------------------------
# Trend keyword extraction
# ---------------------------------------------------------------------------
def test_keywords_prefer_creator_tags():
    keywords = yt_trends._keywords("Some Video Title", ["street food", "bangkok"])
    assert keywords[0] == "street food"


def test_stopwords_are_filtered_out():
    keywords = yt_trends._keywords("The best of the new video", [])
    assert "the" not in keywords
    assert "best" not in keywords  # "best" is in the stopword list


def test_keywords_are_deduplicated():
    keywords = yt_trends._keywords("Pasta pasta PASTA", ["pasta"])
    assert keywords.count("pasta") == 1


def test_velocity_uses_a_one_hour_floor():
    """A video published seconds ago must not post an absurd velocity."""
    from datetime import datetime, timezone

    just_now = datetime.now(timezone.utc)
    assert yt_trends._velocity(1000, just_now) == 1000.0


def test_velocity_falls_back_to_raw_views_without_a_date():
    assert yt_trends._velocity(500, None) == 500.0
