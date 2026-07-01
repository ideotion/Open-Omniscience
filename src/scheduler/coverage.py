"""Per-tag scraping coverage — an honest read of how far the rotating,
per-tag collection has reached, built ENTIRELY from real fetch timestamps.

The scheduler scrapes continuously, stratified by language and tag (a rotation,
never a fixed queue), so collection never "finishes". This module answers the
plain questions a user actually asks — *which tags have been scraped, how many
sources remain, at what percentage* — without inventing a number or a score.

The only signal used is what the collector already records: one
:class:`~src.database.models.FeedFetchState` row per RSS source, written on
every fetch (``last_checked_at`` / ``last_status`` / ``skip_until``). A source
with no state row has simply not been reached yet. Nothing here writes, and no
migration is needed.

Honesty notes carried into the payload:
  * ``reach`` = the headline (ever-fetched / total): the "how many remain" answer
    while a fresh catalog gets its first pass. ``fresh`` (within a STATED window)
    and ``backed_off`` (de-churn, NOT failure) sit alongside so steady-state is
    never misread as stalled.
  * A source with several tags counts under EACH of its tags (overlapping,
    stated) — this is coverage, not a partition.
  * CRAWL sources (no ``rss_url``) get no per-fetch state, so their reach is not
    tracked; they are counted separately and never silently dropped.
  * Counts and percentages only. No quality/priority score anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from src.database.models import FeedFetchState, Source

DEFAULT_FRESH_WINDOW_HOURS = 24
_UNTAGGED = "·untagged"


def _split_tags(raw: str | None) -> list[str]:
    """The catalog's comma-separated tag string → a clean list (order kept)."""
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _status_bucket(status: int | None) -> str:
    if status is None:
        return "unknown"
    if status == 304:
        return "unchanged"
    if 200 <= status < 400:
        return "ok"
    return "error"


def _new_bucket() -> dict:
    return {
        "total": 0,  # enabled RSS sources carrying this tag
        "reached": 0,  # have been fetched at least once
        "fresh": 0,  # fetched within the window
        "backed_off": 0,  # currently in de-churn backoff (not a failure)
        "crawl": 0,  # crawl (non-RSS) sources — reach not tracked
        "_oldest": None,  # oldest last_checked_at among reached (datetime)
        "status": {"ok": 0, "unchanged": 0, "error": 0, "unknown": 0},
    }


def _finalize(bucket: dict, now: datetime) -> dict:
    total = bucket["total"]
    reached = bucket["reached"]
    oldest = bucket.pop("_oldest")
    bucket["never_reached"] = total - reached
    bucket["stale"] = reached - bucket["fresh"]
    bucket["reach_pct"] = round(reached / total, 4) if total else 0.0
    bucket["fresh_pct"] = round(bucket["fresh"] / total, 4) if total else 0.0
    bucket["oldest_reached_age_seconds"] = (
        int((now - oldest).total_seconds()) if oldest is not None else None
    )
    return bucket


def tag_coverage(
    session: Session, *, fresh_window_hours: int = DEFAULT_FRESH_WINDOW_HOURS
) -> dict:
    """Compute per-tag scraping coverage from real fetch state.

    ``fresh_window_hours`` defines what "fresh" means and is echoed in the
    payload so the window is always visible (never an implicit judgement).
    """
    now = datetime.now(UTC)
    window = timedelta(hours=max(1, int(fresh_window_hours)))

    # One row per RSS source that has ever been fetched.
    states: dict[int, FeedFetchState] = {
        st.source_id: st for st in session.query(FeedFetchState).all()
    }

    tags: dict[str, dict] = {}
    totals = _new_bucket()
    crawl_total = 0

    def bucket_for(tag: str) -> dict:
        return tags.setdefault(tag, _new_bucket())

    rows = (
        session.query(Source.id, Source.tags, Source.rss_url)
        .filter(Source.enabled.is_(True))
        .all()
    )
    for sid, raw_tags, rss_url in rows:
        tag_list = _split_tags(raw_tags) or [_UNTAGGED]

        if not rss_url:  # crawl source — reach not tracked, but counted honestly
            crawl_total += 1
            totals["crawl"] += 1
            for tag in tag_list:
                bucket_for(tag)["crawl"] += 1
            continue

        st = states.get(sid)
        checked = st.last_checked_at if st else None
        if checked is not None and checked.tzinfo is None:
            checked = checked.replace(tzinfo=UTC)
        fresh = checked is not None and (now - checked) <= window
        skip_until = st.skip_until if st else None
        if skip_until is not None and skip_until.tzinfo is None:
            skip_until = skip_until.replace(tzinfo=UTC)
        backed_off = skip_until is not None and skip_until > now
        sbucket = _status_bucket(st.last_status if st else None)

        for target in (totals, *(bucket_for(t) for t in tag_list)):
            target["total"] += 1
            if checked is not None:
                target["reached"] += 1
                oldest = target["_oldest"]
                if oldest is None or checked < oldest:
                    target["_oldest"] = checked
            if fresh:
                target["fresh"] += 1
            if backed_off:
                target["backed_off"] += 1
            target["status"][sbucket] += 1

    out_tags = [
        {"tag": tag, **_finalize(bucket, now)}
        for tag, bucket in tags.items()
    ]
    # Least-reached first: the honest worklist of what still needs a pass.
    out_tags.sort(key=lambda b: (b["reach_pct"], -b["total"]))

    return {
        "as_of": now.isoformat(),
        "fresh_window_hours": int(fresh_window_hours),
        "method": (
            "Reach = RSS sources ever fetched / total, per tag, from the "
            "collector's own fetch timestamps. Fresh = fetched within the window "
            "above. A source counts under each of its tags. Counts only, no score."
        ),
        "caveat": (
            "Continuous scraping never finishes — this is reach and freshness, "
            "not completion. Backed-off feeds are a temporary de-churn, not "
            "failures. Crawl (non-RSS) sources have no per-fetch state, so their "
            "reach is not tracked (counted separately)."
        ),
        "totals": _finalize(totals, now),
        "crawl_sources": crawl_total,
        "tags": out_tags,
    }
