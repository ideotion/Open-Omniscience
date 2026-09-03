"""
S1.0: the collector must not hold a DB connection across a network fetch.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (field crash analysis 2026-09-02, its #1-ranked mechanism): a
collector worker took a governor permit, opened a session, and then ran the whole
per-source ingest inside it -- the feed's conditional-GET read opens a
transaction, and that transaction stays open across the feed fetch and across
every article fetch until the feed bookkeeping commits at the end. So N
concurrent workers held N connections, each carrying up to ``sqlite_cache_mb`` of
page cache: 3.2 GB at 50 workers and the shipped 64 MiB, against a field machine
whose RSS sat at ~6.7 GB with available RAM between 94 and 135 MB for ~2.5 h
while the bandwidth governor had already cut permits 50 -> 1. The brief's own
honest statement stands: no artifact names the proximate cause of any of the four
deaths, and this is the strongest candidate, not a proven killer.

WHAT THIS ACTUALLY BUYS (measured, and NOT what a first draft of this file
claimed). Ending the transaction does not free a resident connection's page
cache -- a warm 64 MiB cache stayed put across ``rollback()`` + ``malloc_trim``
and fell only on ``PRAGMA shrink_memory`` or ``close()``. What changes is how
MANY connections exist at once: releasing between statements collapses
simultaneous checkouts to the number of statements actually running, so the
``max_overflow`` connections that a held-across-fetch worker forces into
existence are largely never created -- and this pool closes overflow connections
on return, so any that are created hand their cache back. The ``pool_size`` core
stays resident with its cache by design; that floor is S1.1's number, not this
one's. Two further effects are, on the field evidence, the stronger argument: no
worker pins a WAL read snapshot across a Tor fetch any more, and the
read-then-write window that produces ``SQLITE_BUSY_SNAPSHOT`` -- the fleet's most
frequent recorded error -- shrinks to the statements themselves.

WHY NOT THE OBVIOUS FIX. The brief's first option was to restructure the worker
into fetch-then-store -- fetch everything, then open a session to write. This
pipeline's shape argues against it: ``ingest_url`` runs a canonical-URL dedup
READ *before* each article fetch, and the field duplicate rate is ~90%. If most
of that is caught by the pre-fetch canonical check, moving the fetches ahead of
the reads multiplies article fetch volume by up to ten, over Tor, on the machines
already saturating. (The tally does not separate canonical-URL from
content-hash duplicates anywhere in the tree, so that split is an assumption --
which is exactly why the multiplier is stated as an upper bound.) The read is not
incidental to the store; it is what PREVENTS the fetch. The second option was a
semaphore capping how many workers hold a session, which with this interleaving
caps the whole per-source unit of work and so gives up the parallelism the memory
was being spent on.

WHAT IS AND IS NOT COVERED. The wrapper is applied at ONE place --
``_process_source``, the per-source collector loop both the parallel pool and the
sequential path go through -- and it wraps the FETCHER rather than the call
sites, so every network call REACHED FROM THAT LOOP is covered, including ones a
future edit adds inside ``ingest_source``/``crawl_source``. It does NOT cover the
housekeeping lane's own session+fetcher pairings (``_lane_step_crawl``, which
runs the same ``ingest_url`` shape, ``_lane_step_qualification``, which calls the
same ``ingest_source``, ``_lane_step_backfill``/``_law``/``_markets``,
``preflight_sources``, ``field_test``), nor law/markets mode in the pass itself.
Those are ONE session each rather than N, which is why they are not this slice --
but "every network call in the collector path is covered by construction" would
be false, and the non-negotiable that matters here is one fetch CLASS, not one
wrapped INSTANCE. Wrapping them is the obvious follow-up.

Correctness comes from the pipeline's existing discipline AND from the guard:
the article loop already runs on a CLEAN session by design (the feed bookkeeping
is deliberately deferred to after the loop -- see ``ingest_source``), and
``ArticleBatch`` buffers staged articles in PYTHON, touching the session only
inside ``flush()``; and where a session has written, ``release_idle_connection``
declines rather than guessing (see its docstring for what the guard can and
cannot see).

The one behavioural consequence, stated: a read after a release sees a NEWER
snapshot than one before it, and a rollback expires the session's identity map so
an object read after a fetch is re-selected. For the dedup check the newer
snapshot is strictly better -- an article another worker stored meanwhile is now
seen, and skipped, instead of being fetched and discarded at the batch's own
re-check.
"""

from __future__ import annotations

from typing import Any

from src.database.session import release_idle_connection

# The fetcher methods that reach the network and are therefore intercepted.
# LOAD-BEARING, not documentation: the overrides below are generated from this
# tuple, so a name added here really is wrapped and a name removed really is
# delegated -- the two can never disagree. ``fetch`` is the single fetch path
# (robots, politeness, kill switch, proxy); ``declared_sitemaps`` reads a host's
# robots.txt. Anything else on the fetcher is delegated untouched, INCLUDING the
# private network helpers (``_guarded_redirect_get``, ``_http_get``,
# ``_get_robots``) that ``monitoring/preflight.py`` and ``feed_preflight.py``
# already call directly -- those paths are outside this wrapper either way.
_NETWORK_METHODS = ("fetch", "declared_sitemaps")


class SessionReleasingFetcher:
    """A fetcher proxy that hands ``session``'s pooled connection back first.

    Transparent by delegation for everything local. Not a drop-in for every use
    of a fetcher: it declines attribute WRITES (``__slots__``), is not an
    ``EthicalFetcher`` by ``isinstance``, and is not copyable or picklable. No
    production path does any of those to a fetcher; the limits are stated rather
    than claimed away.
    """

    __slots__ = ("_fetcher", "_session", "_released")

    def __init__(self, fetcher: Any, session: Any) -> None:
        self._fetcher = fetcher
        self._session = session
        # Counted, not assumed: a caller that wants to report the effect reads a
        # measurement rather than trusting that the wrapper did anything. It
        # counts transactions ENDED; on the production QueuePool that is also a
        # connection returned, on a single-connection test pool it is not.
        self._released = 0

    def __getattr__(self, name: str) -> Any:
        # Bail out on private/dunder names BEFORE touching a slot: an instance
        # built without __init__ (copy, pickle) has no ``_fetcher``, and reading
        # it here would recurse instead of raising AttributeError.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._fetcher, name)

    def _release(self) -> None:
        if release_idle_connection(self._session):
            self._released += 1

    @property
    def releases(self) -> int:
        """Transactions ended before a network call (measured)."""
        return self._released


def _make_override(name: str):
    def _wrapped(self: SessionReleasingFetcher, *args: Any, **kwargs: Any) -> Any:
        self._release()
        return getattr(self._fetcher, name)(*args, **kwargs)

    _wrapped.__name__ = name
    _wrapped.__qualname__ = f"SessionReleasingFetcher.{name}"
    _wrapped.__doc__ = f"Release the session's connection, then delegate to ``{name}``."
    return _wrapped


for _name in _NETWORK_METHODS:
    setattr(SessionReleasingFetcher, _name, _make_override(_name))
del _name


def wrap_fetcher(fetcher: Any, session: Any) -> Any:
    """Pair ``fetcher`` with ``session`` so no fetch runs on a held connection.

    Returns the fetcher unchanged when either side is missing, so a caller with
    no session (or no fetcher) is never broken by the wrapping. Re-wrapping an
    already-wrapped fetcher rebinds it to the NEW session rather than nesting:
    a nested pair would roll back a session the caller never named.
    """
    if fetcher is None or session is None:
        return fetcher
    if isinstance(fetcher, SessionReleasingFetcher):
        return SessionReleasingFetcher(fetcher._fetcher, session)
    return SessionReleasingFetcher(fetcher, session)
