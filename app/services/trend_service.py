"""
Trend research.

Runs each adapter's research call, stores the results and keeps the table from
growing without bound. Topics already seen recently are updated in place rather
than duplicated, so the trends page shows a topic once with its newest score.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import Trend, TrendStatus
from app.platforms import PlatformError, all_adapters, get_adapter
from app.services import account_service, settings_service

log = logging.getLogger(__name__)

# A topic seen again within this window updates the existing row.
DEDUPE_WINDOW_HOURS = 48
# Trends older than this are deleted by :func:`prune`.
RETENTION_DAYS = 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def research_platform(platform: str, region: str | None = None, limit: int | None = None) -> dict:
    """
    Research one platform and store the results.

    Needs a connected account: the APIs that expose trending data require an
    authorised client.
    """
    adapter = get_adapter(platform)
    result = {"platform": platform, "found": 0, "new": 0, "updated": 0, "error": None}

    if not adapter.supports_trends:
        result["error"] = f"{adapter.display_name} does not offer trend research."
        return result

    account = account_service.default_account(platform)
    if account is None:
        result["error"] = (
            f"Connect a {adapter.display_name} account first - trend research uses "
            f"its API credentials."
        )
        return result

    region = (region or settings_service.get("trend_region", "US") or "US").upper()
    limit = int(limit or settings_service.get("trend_results", 25))

    try:
        credentials = account_service.credentials_for(account)
        items = adapter.fetch_trends(credentials, region=region, limit=limit)
    except PlatformError as exc:
        result["error"] = str(exc)
        log.warning("Trend research failed for %s: %s", platform, exc)
        return result

    cutoff = _utcnow() - timedelta(hours=DEDUPE_WINDOW_HOURS)
    for item in items:
        existing = (
            db.session.query(Trend)
            .filter(
                Trend.platform == platform,
                Trend.region == region,
                Trend.topic == item.topic[:255],
                Trend.captured_at >= cutoff,
            )
            .first()
        )
        if existing is not None:
            # Refresh the score but never resurrect a rejected topic.
            existing.score = item.score
            existing.signals = item.signals
            existing.captured_at = _utcnow()
            if existing.status == TrendStatus.NEW:
                existing.keywords = ", ".join(item.keywords)
                existing.category = item.category
            result["updated"] += 1
            continue

        trend = Trend(
            platform=platform,
            region=region,
            topic=item.topic[:255],
            keywords=", ".join(item.keywords),
            category=item.category,
            score=item.score,
            status=TrendStatus.NEW,
        )
        trend.signals = item.signals
        db.session.add(trend)
        result["new"] += 1

    db.session.commit()
    result["found"] = len(items)
    log.info(
        "Trend research on %s/%s: %s found (%s new, %s updated).",
        platform, region, result["found"], result["new"], result["updated"],
    )
    return result


def research_all(region: str | None = None) -> dict:
    """Research every adapter that supports it."""
    results = []
    for adapter in all_adapters():
        if not adapter.supports_trends:
            continue
        results.append(research_platform(adapter.name, region=region))
    return {
        "platforms": len(results),
        "new": sum(entry["new"] for entry in results),
        "updated": sum(entry["updated"] for entry in results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Queries used by the web interface
# ---------------------------------------------------------------------------
def recent_trends(
    limit: int = 50, status: str | None = None, platform: str | None = None
) -> list[Trend]:
    """Trends ordered by score, newest capture first on a tie."""
    query = db.session.query(Trend)
    if status:
        query = query.filter(Trend.status == status)
    if platform:
        query = query.filter(Trend.platform == platform)
    return (
        query.order_by(Trend.score.desc(), Trend.captured_at.desc()).limit(limit).all()
    )


def set_status(trend: Trend, status: str, user=None, notes: str | None = None) -> None:
    """Move a trend through the pipeline (new -> planned/used/rejected)."""
    if status not in TrendStatus.ALL:
        raise ValueError(f"Unknown trend status: {status}")
    trend.status = status
    trend.reviewed_at = _utcnow()
    trend.reviewed_by_id = getattr(user, "id", None)
    if notes is not None:
        trend.notes = notes[:2000]
    db.session.commit()


def prune(days: int = RETENTION_DAYS) -> int:
    """Delete stale trends. Planned and used ones are kept as a record."""
    cutoff = _utcnow() - timedelta(days=days)
    deleted = (
        db.session.query(Trend)
        .filter(
            Trend.captured_at < cutoff,
            Trend.status.in_((TrendStatus.NEW, TrendStatus.REJECTED)),
        )
        .delete(synchronize_session=False)
    )
    db.session.commit()
    if deleted:
        log.info("Pruned %s trends older than %s days.", deleted, days)
    return deleted


def keyword_cloud(limit: int = 25) -> list[tuple[str, int]]:
    """
    Most common keywords across recent, unreviewed trends.

    A word that appears across many trending videos is a stronger signal than
    one viral hit, so the trends page leads with this.
    """
    from collections import Counter

    counter: Counter[str] = Counter()
    for trend in recent_trends(limit=100, status=TrendStatus.NEW):
        counter.update(trend.keyword_list)
    return counter.most_common(limit)
