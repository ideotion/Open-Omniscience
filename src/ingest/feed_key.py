"""The feed half of a source's identity (row J, S05-10).

A source is identified by its domain AND its feed: ``UNIQUE (domain, feed_key)``. ``feed_key`` is the
feed URL reduced to what makes two spellings the same feed, or ``''`` for a source with no feed. It is
computed here and nowhere else -- the migration, the seeder, the restore-merge (registered as a SQLite
function on the merge connection) and the importers all call this one function, because a second
implementation is how two surfaces come to disagree about one identity.

What counts as the same feed: the scheme (``http`` and ``https`` serve one feed), the case of the host,
a fragment, and a trailing slash on the path. What does NOT: a ``www.`` prefix and the query string -- a
query is part of what a feed is (``?cat=7``), and a host prefix is a different server until someone has
measured otherwise. Never raises: an unparseable value keeps its stripped, lower-cased text, because a
key that refuses is a source that cannot be created.
"""

from __future__ import annotations

from urllib.parse import urlsplit

#: ``Source.feed_key`` column width, the same as ``Source.rss_url``.
FEED_KEY_MAX = 500


def feed_key(rss_url: str | None) -> str:
    """The normalised feed identity of ``rss_url``; ``''`` when the source has no feed."""
    if not rss_url:
        return ""
    text = str(rss_url).strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text if "//" in text else "//" + text)
        host = (parts.netloc or "").lower()
        path = parts.path.rstrip("/")
        key = host + path + ("?" + parts.query if parts.query else "")
    except ValueError:
        return text.lower()[:FEED_KEY_MAX]
    return (key or text.lower())[:FEED_KEY_MAX]
