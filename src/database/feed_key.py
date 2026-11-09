"""The feed half of a source's identity (row J, S05-10).

A source is identified by its domain AND its feed: ``UNIQUE (domain, feed_key)``. ``feed_key`` is
``FEED_PREFIX`` plus the feed URL reduced to what makes two spellings the same feed, or ``''`` for a source
with no feed (R145: such a source is keyed by its domain alone). It is
computed here and nowhere else -- the migration, the seeder, the restore-merge (registered as a SQLite
function on the merge connection) and the importers all call this one function, because a second
implementation is how two surfaces come to disagree about one identity.

What counts as the same feed: the scheme (``http`` and ``https`` serve one feed), the case of the host,
a userinfo (R628: a user name and password written into the feed URL are how it is fetched, not which feed
it is, and they are not kept in the key), a fragment, and a trailing slash on the path. What does NOT: a
``www.`` prefix and the query string -- a query is part of what a feed is (``?cat=7``), and a host prefix is
a different server until someone has measured otherwise. Never raises: an unparseable value keeps its
stripped, lower-cased text, because a key that refuses is a source that cannot be created (its userinfo
included, stated: ``urllib.parse`` could not read where the authority is).

A KEY STORED BEFORE R628 kept the userinfo, and a stored key moves only when its row is next written through
the ORM (the ``before_update`` event re-derives it) or by a bulk writer that re-derives it. Such a key holds
an ``@`` where today's key of the same URL does not, so :func:`read_feed_key` reads it as the key its own
feed has now.
"""

from __future__ import annotations

from urllib.parse import urlsplit

#: ``Source.feed_key`` column width, the same as ``Source.rss_url``.
FEED_KEY_MAX = 500

#: Every feed key starts with this and a feed-less source's key is ``''``, so the two namespaces cannot meet: a
#: domain-only identity can never equal a feed identity, whatever a feed URL looks like (R145 point 1).
FEED_PREFIX = "f:"


def feed_key(rss_url: str | None) -> str:
    """The normalised feed identity of ``rss_url``; ``''`` when the source has no feed."""
    if not rss_url:
        return ""
    text = str(rss_url).strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text if "//" in text else "//" + text)
        # the host and port: the userinfo is everything before the LAST @, as urllib.parse reads it (R628)
        host = (parts.netloc or "").rpartition("@")[2].lower()
        path = parts.path.rstrip("/")
        key = host + path + ("?" + parts.query if parts.query else "")
    except ValueError:
        key = ""
    return (FEED_PREFIX + (key or text.lower()))[:FEED_KEY_MAX]


def read_feed_key(stored_key: str | None, rss_url: str | None) -> str:
    """The key a STORED row is matched under (R628): its stored ``feed_key``, or, when that key holds an ``@``, the key of the
    row's own ``rss_url`` as :func:`feed_key` computes it today.

    A key written before R628 kept the feed URL's userinfo (``f:alice:pw@news.example/rss``) and stays so until its row is next
    written; read as stored, it would stop matching the same feed, and an add or an import of that feed would make a second row.
    Today's key holds an ``@`` only where it is not a userinfo (a path, a query, or a URL ``urllib.parse`` could not read), and
    there re-deriving it gives the stored key back, so the reading is exact for every key and costs a call only for those. Read by
    ``src.database.source_lookup`` and the CSV import; the restore merge and the seeder compare the stored column (stated in
    R628's ledger row). Never raises (:func:`feed_key` never does)."""
    key = stored_key or ""
    return feed_key(rss_url) if "@" in key else key
