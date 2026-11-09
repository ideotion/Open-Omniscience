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

A FEED STORED TWICE BEFORE R628 (R634): once with a login and once without, or with two logins, had two keys,
and R628 derives one for both. Re-deriving would break ``UNIQUE (domain, feed_key)``, so such a row keeps the
key it has (:func:`key_to_write`, asked by every writer that re-derives a key) and the pair stays two rows; an
add or an import of one of the two URLs finds its own row (:func:`lookup_key`). A kept key still holds the
login: no writer puts it in a statement's parameters and nothing reports a key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:  # annotations only: no src module is imported here (engine_identity triages this file)
    from collections.abc import Container, Iterable, Sequence

#: ``Source.feed_key`` column width, the same as ``Source.rss_url``.
FEED_KEY_MAX = 500

#: Every feed key starts with this and a feed-less source's key is ``''``, so the two namespaces cannot meet: a
#: domain-only identity can never equal a feed identity, whatever a feed URL looks like (R145 point 1).
FEED_PREFIX = "f:"


def feed_key(rss_url: str | None) -> str:
    """The normalised feed identity of ``rss_url``; ``''`` when the source has no feed."""
    return _derived_key(rss_url, keep_userinfo=False)


def legacy_feed_key(rss_url: str | None) -> str:
    """The key a build before R628 derived for ``rss_url``: :func:`feed_key` with the userinfo kept. Equal to :func:`feed_key`
    for a URL that carries none. Read only to recognise a stored row's own pre-R628 key (R634), never written for a new one."""
    return _derived_key(rss_url, keep_userinfo=True)


def _derived_key(rss_url: str | None, *, keep_userinfo: bool) -> str:
    if not rss_url:
        return ""
    text = str(rss_url).strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text if "//" in text else "//" + text)
        # the host and port: the userinfo is everything before the LAST @, as urllib.parse reads it (R628)
        netloc = parts.netloc or ""
        host = (netloc if keep_userinfo else netloc.rpartition("@")[2]).lower()
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


def keeps_a_stored_key(stored_key: str | None, rss_url: str | None) -> bool:
    """R634's gate, no I/O: is ``stored_key`` its own feed's pre-R628 key (it holds the userinfo of ``rss_url``), which today's
    key differs from? Only such a row may keep its stored key, and only then is the collision asked (:func:`key_to_write`). A row
    whose feed URL was edited since does not pass: its stored key is another URL's, and the edit is re-derived as before."""
    key = stored_key or ""
    if "@" not in key:
        return False
    return key == legacy_feed_key(rss_url) and key != feed_key(rss_url)


def _claims(mate_key: str | None, mate_url: str | None, key: str) -> bool:
    """Does another row of the domain hold ``key`` (its stored key, which ``UNIQUE`` compares), or would it take ``key`` when it is
    next written (its own URL's key: a stored key can be stale, written round the ORM)?"""
    return (mate_key or "") == key or feed_key(mate_url) == key


def key_to_write(
    stored_key: str | None, rss_url: str | None, mates: Iterable[tuple[str | None, str | None]] = ()
) -> str:
    """The key a STORED row is written (and matched) under (R634): :func:`feed_key` of its feed, EXCEPT a row that keeps its
    stored key (:func:`keeps_a_stored_key`) when another row of its domain holds that key or would take it. ``mates`` are the
    ``(feed_key, rss_url)`` of the domain's OTHER rows.

    Why: one feed stored twice before R628 (once with a login and once without, or with two logins) had two keys, and R628 derives
    one for both. Re-deriving the credentialed row's key would then break ``UNIQUE (domain, feed_key)`` on its next write, so that
    row keeps the key it has, and the pair stays two rows. Both rows of a pair that are both credentialed keep theirs (each would
    take the other's), so the answer never depends on which is written first. A kept key is not written out: the writers leave the
    column untouched, and nothing reports a key."""
    new = feed_key(rss_url)
    if not keeps_a_stored_key(stored_key, rss_url):
        return new
    if any(_claims(k, u, new) for k, u in mates):
        return stored_key or ""
    return new


def domain_keys(rows: Sequence[tuple[str | None, str | None]]) -> list[str]:
    """The keys an import matches the ``(feed_key, rss_url)`` rows of ONE domain under: :func:`read_feed_key` (R628), except a row
    that keeps its stored key beside a twin (:func:`key_to_write`, the others its mates). Costs a pass over the mates only for a row
    that may keep its key."""
    out: list[str] = []
    for i, (stored, url) in enumerate(rows):
        if keeps_a_stored_key(stored, url):
            out.append(key_to_write(stored, url, (r for j, r in enumerate(rows) if j != i)))
        else:
            out.append(read_feed_key(stored, url))
    return out


def lookup_key(rss_url: str | None, held_keys: Container[str]) -> str:
    """The key an INCOMING feed URL (an add, an import record) is matched under: its pre-R628 key when the domain still holds that
    key (the same URL, stored before R628 and kept beside its twin, or not yet rewritten), else :func:`feed_key`. ``held_keys``
    are the keys the domain's rows are matched under. Never raises."""
    new = feed_key(rss_url)
    old = legacy_feed_key(rss_url)
    return old if old != new and old in held_keys else new
