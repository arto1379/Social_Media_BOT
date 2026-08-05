"""
Trend research.

Method: read the ``mostPopular`` chart for the configured region, then rank the
results by **view velocity** - views divided by hours since publication -
rather than by raw view count. A three-day-old video with 400k views is a
better signal of what is rising *now* than a two-month-old one with 2M.

From each entry the bot keeps the topic and its keywords. It never keeps or
downloads the file. Re-uploading someone else's video is copyright
infringement, YouTube demotes it as reused content, and it cannot be monetised
- so the useful output of research is the subject to film, not the footage.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.platforms.base import TrendItem
from app.platforms.youtube.client import build_data_service, execute

log = logging.getLogger(__name__)

# Words that carry no topical meaning and would otherwise dominate keywords.
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "for", "to", "with",
    "is", "are", "was", "were", "be", "been", "at", "by", "from", "as", "it",
    "this", "that", "these", "those", "you", "your", "my", "we", "our", "i",
    "how", "what", "why", "when", "who", "not", "no", "do", "does", "did",
    "new", "best", "top", "vs", "ft", "feat", "official", "video", "shorts",
    "short", "full", "part", "episode", "ep", "hd", "4k",
}

# Only words of at least this length become keywords.
MIN_KEYWORD_LENGTH = 3

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _parse_published(value: str | None) -> datetime | None:
    """Parse the RFC 3339 timestamp the API returns."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _velocity(views: int, published_at: datetime | None) -> float:
    """Views per hour since publication (the ranking signal)."""
    if not published_at:
        return float(views)
    age_hours = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600
    # Floor the age at one hour so a video published minutes ago cannot post an
    # absurd velocity purely because of a tiny denominator.
    return views / max(age_hours, 1.0)


def _keywords(title: str, tags: list[str]) -> list[str]:
    """Pick the words that describe the topic, tags first then title words."""
    picked: list[str] = []
    seen: set[str] = set()

    # Creator-supplied tags are the highest quality signal available.
    for tag in tags[:8]:
        cleaned = tag.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            picked.append(cleaned)

    for word in _WORD_RE.findall(title.lower()):
        if len(word) < MIN_KEYWORD_LENGTH or word in STOPWORDS or word in seen:
            continue
        seen.add(word)
        picked.append(word)
        if len(picked) >= 12:
            break

    return picked


def _category_names(service) -> dict[str, str]:
    """Map YouTube category ids to names for display on the trends page."""
    try:
        response = execute(
            service.videoCategories().list(part="snippet", regionCode="US"),
            "listing video categories",
        )
    except Exception as exc:  # non-fatal: categories are cosmetic
        log.info("Could not load category names: %s", exc)
        return {}
    return {
        item["id"]: item.get("snippet", {}).get("title", "")
        for item in response.get("items", [])
    }


def fetch_trends(
    credentials_blob: dict[str, Any], region: str = "US", limit: int = 25
) -> list[TrendItem]:
    """Return up to *limit* trending topics for *region*, best first."""
    service = build_data_service(credentials_blob)
    categories = _category_names(service)

    response = execute(
        service.videos().list(
            part="snippet,statistics,contentDetails",
            chart="mostPopular",
            regionCode=region,
            maxResults=min(max(limit, 1), 50),
        ),
        "reading trending videos",
    )

    items = response.get("items", [])
    if not items:
        log.info("YouTube returned no trending videos for region %s", region)
        return []

    # First pass: gather raw signals so the score can be normalised afterwards.
    raw: list[dict[str, Any]] = []
    for item in items:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        published = _parse_published(snippet.get("publishedAt"))
        views = int(stats.get("viewCount") or 0)
        raw.append(
            {
                "title": snippet.get("title", ""),
                "channel": snippet.get("channelTitle", ""),
                "category_id": snippet.get("categoryId", ""),
                "tags": snippet.get("tags", []) or [],
                "views": views,
                "likes": int(stats.get("likeCount") or 0),
                "comments": int(stats.get("commentCount") or 0),
                "published_at": snippet.get("publishedAt"),
                "video_id": item.get("id", ""),
                "velocity": _velocity(views, published),
            }
        )

    # Normalise velocity onto 0-100 so scores are comparable between runs.
    top_velocity = max((entry["velocity"] for entry in raw), default=0.0) or 1.0

    trends: list[TrendItem] = []
    for entry in raw:
        score = round(100.0 * entry["velocity"] / top_velocity, 2)
        trends.append(
            TrendItem(
                topic=entry["title"][:255],
                keywords=_keywords(entry["title"], entry["tags"]),
                category=categories.get(entry["category_id"], entry["category_id"]),
                score=score,
                signals={
                    "views": entry["views"],
                    "likes": entry["likes"],
                    "comments": entry["comments"],
                    "views_per_hour": round(entry["velocity"], 1),
                    "published_at": entry["published_at"],
                    "channel": entry["channel"],
                    # Reference only - so an operator can watch the example and
                    # decide what to film. The bot never downloads it.
                    "reference_url": f"https://www.youtube.com/watch?v={entry['video_id']}",
                },
            )
        )

    trends.sort(key=lambda t: t.score, reverse=True)
    return trends[:limit]


def summarise_keywords(trends: list[TrendItem], top_n: int = 20) -> list[tuple[str, int]]:
    """
    Most frequent keywords across a set of trends.

    A word that shows up across many trending videos is a stronger signal than
    one that appears in a single viral hit, so the trends page shows this list
    as "what the region is talking about".
    """
    counter: Counter[str] = Counter()
    for trend in trends:
        counter.update(trend.keywords)
    return counter.most_common(top_n)
