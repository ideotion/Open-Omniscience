"""The feed entry's own date, kept as the feed's claim for an article whose page gave none (row 457, R847).

Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``Article.published_at`` comes only from the page's own metadata (src/ingest/extract.py). The field analysis (PR #2418,
quality.md "Dates") measured 6.6-9.0% of sampled sources with an article that has no publication date, while the feed item
that brought it usually carries one, and that date was dropped (only ``entry.link`` was kept).

The ruling (R847): the feed entry's date is a FALLBACK, used only when the article has no date of its own; it is stored with
its origin, and shown flagged as the feed's date wherever a date is displayed or used in a time series. New articles only;
no stored row is rewritten.

So it lives in its own column, ``Article.feed_entry_published_at``, and is never written into ``published_at``. A surface
that has not been taught to flag it simply does not see it, which is the safe way round: the date it shows is still the
article's own, or none. :func:`article_date` is the one reading for a surface that does use it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

#: The words beside a feed's date wherever one is shown, and the hover that says why (both x12 in the locale files; the
#: server-rendered reader writes them in English and the page translates them as it does every label there).
FEED_DATE_LABEL = "the feed's date"
FEED_DATE_HOVER = (
    "This page gave no date of its own. This is the date the source's feed gave the item, which can be when it was posted "
    "or last updated in the feed rather than when it was first published."
)

#: The two values :func:`article_date` gives as the origin of the date it returns.
ORIGIN_ARTICLE = "article"
ORIGIN_FEED = "feed"

#: How far past the moment the feed was read an entry's date may lie and still be kept. A feed that dates an item later
#: than that is wrong about it (a server clock, a scheduled post's planned time, a time zone written as UTC); one day covers
#: every honest time-zone slip. Nothing older is refused: an old date is a claim the flag already labels as the feed's.
FUTURE_SLACK = timedelta(days=1)

#: The feedparser fields tried, in order. ``published_parsed`` is the entry's publication date (RSS pubDate, Atom
#: published); ``updated_parsed`` (Atom updated, RSS dc:date) is the only date many Atom feeds give. feedparser hands both
#: over as UTC ``time.struct_time`` values, already normalised from whatever zone the feed wrote.
_ENTRY_FIELDS = ("published_parsed", "updated_parsed")


def entry_date(entry: Any, *, read_at: datetime | None = None) -> datetime | None:
    """The date a feed entry gives its item, as naive UTC, or None when it gives no usable one.

    None (never a guess) when the entry has neither field, when a field does not make a real date, or when the date lies
    more than :data:`FUTURE_SLACK` after ``read_at`` (default: now). ``entry`` is a feedparser entry (a dict), or any
    mapping with the same keys; anything else gives None.
    """
    now = read_at or datetime.now(UTC)
    # A naive ``read_at`` is taken as UTC, as every timestamp in the store is, never as the machine's local time.
    limit = (now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo is not None else now) + FUTURE_SLACK
    for field in _ENTRY_FIELDS:
        parts = entry.get(field) if hasattr(entry, "get") else None
        if not parts:
            continue
        try:
            when = datetime(*tuple(parts)[:6])
        except (TypeError, ValueError, OverflowError):
            continue
        if when > limit:
            return None  # the feed's own date for this item is wrong; a later field would not make it right
        return when
    return None


def article_date(published_at: datetime | None, feed_entry_published_at: datetime | None) -> tuple[datetime | None, str | None]:
    """The date to show for an article and where it came from: ``(date, ORIGIN_ARTICLE | ORIGIN_FEED | None)``.

    The article's own date always wins. The feed entry's date is used only when the article has none, and then the origin
    says so, so the surface can flag it. ``(None, None)`` when neither is recorded.
    """
    if published_at is not None:
        return published_at, ORIGIN_ARTICLE
    if feed_entry_published_at is not None:
        return feed_entry_published_at, ORIGIN_FEED
    return None, None


def feed_date_fields(published_at: datetime | None, feed_entry_published_at: datetime | None) -> dict:
    """``feed_entry_published_at`` and ``date_origin`` for a payload that carries an article's ``published_at``.

    ``published_at`` stays the article's own date (null when it has none), exactly as before, so a reader that knows
    nothing of this field still never shows a feed date. ``feed_entry_published_at`` is the feed's date only when it is the
    fallback (the article has no date of its own), and ``date_origin`` names which one the article's date is:
    ``"article"``, ``"feed"`` or null when neither is recorded. One place, so every payload agrees about one article.
    """
    when, origin = article_date(published_at, feed_entry_published_at)
    return {
        "feed_entry_published_at": when.isoformat() if origin == ORIGIN_FEED and when is not None else None,
        "date_origin": origin,
    }
