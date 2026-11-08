"""Building Q707's HOT membership from what this machine has actually measured.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q707 = a names three things that put a page in HOT — "pages the corpus already
mentions, tracked pages, and the pageview top-1,000" — and Q716 = a adds the
operator's own pin. This module turns those four sentences into four MEASURED SETS,
per edition, and hands them to :class:`src.wiki.tiers.HotSet`, which decides. The
split is deliberate: the deciding is pure and testable with sets a test writes by
hand, and the querying is here, where the databases are.

WHAT "THE CORPUS ALREADY MENTIONS" MEANS HERE, STATED BECAUSE IT IS A CHOICE. The
ruling does not define "mentions", and there are several defensible readings — a
full-text search per candidate title (a query per page, unaffordable), a named-entity
index (this app does not keep one keyed by wiki title), or the corpus's OWN extracted
keywords, which exist, are already normalised, and are what every other surface in
this app means when it says what a corpus is about. This module takes the third and
SAYS SO in :data:`MENTION_SOURCE`, which travels with the numbers to the UI. It is not
exhaustive — an article that discusses a subject without the extractor keeping it as a
keyword will not put that page in HOT — and that limit is the caveat the surface
shows, never a footnote in a design document.

IT IS BOUNDED, AND THE BOUND IS VISIBLE. A corpus with a million keywords would make
the HOT tier the whole of Wikipedia, which is the tail walk Q108 puts in 0.6. The
mention set is capped at :data:`MENTION_LIMIT` most-frequent keywords, the cap is
reported beside the set, and a corpus that hits it is told so — a silently truncated
set is a silently wrong tier.

NO NETWORK. Every source read here is a local database or a value the caller already
fetched. The pageview top-1,000 arrives as an argument precisely so this module never
becomes a second fetch path.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from src.wiki.identity import parse_external_id
from src.wiki.tiers import HotSet

_LOG = logging.getLogger("wiki.hotset")

#: How the mention set is built, in the words the UI shows. A string, not a comment,
#: because a method that lives only in a docstring is a method the operator never sees.
MENTION_SOURCE: str = "corpus keywords (the extractor's own terms), most frequent first"

#: The cap on the mention set. Not a tuning number pulled from the air: it is the
#: order of magnitude at which a HOT tier stops being "the pages my corpus is about"
#: and starts being a general crawl, which Q108 assigns to a later release.
MENTION_LIMIT: int = 5000


def pageview_kv_key(edition: str) -> str:
    """The ``app_state`` key one edition's cached top-1,000 lives under.

    In the CORPUS key-value store, so it inherits the corpus's encryption rather than
    sitting beside it as a plaintext file. The list itself is public — it is the same
    list for every reader in the world — but a file naming what this machine asked
    Wikimedia about is still one more thing on an operator's disk that nothing
    required.
    """
    return f"wiki.pageviews.top.{edition}"


def _mention_statement(limit: int):
    """The one statement that reads the mention set: the first ``limit + 1`` terms by frequency."""
    from src.database.models import Keyword

    return (
        select(Keyword.term)
        .where(Keyword.term.is_not(None))
        .order_by(Keyword.frequency.desc(), Keyword.term)
        .limit(limit + 1)
    )


#: A mention read slower than this (seconds) logs the statement's query plan once per process.
SLOW_MENTION_READ_S: float = 1.0

#: The share of wall time a cached mention set may spend being re-read: it is reused for ``1 / MENTION_READ_DUTY`` times what the read cost.
MENTION_READ_DUTY: float = 0.01


def _log_mention_plan(corpus: Any, limit: int, elapsed: float) -> None:
    """Say how SQLite planned the slow read. The 2026-11-07 Windows run measured 8.4 s a call (1,516 calls) on a build that already had the
    index-order fix, and a synthetic table of the same shape runs in 9 ms: the real plan is the missing fact. Table, index and column names only."""
    try:
        from sqlalchemy import text

        bind = corpus.get_bind()
        if bind.dialect.name != "sqlite":
            return
        sql = str(_mention_statement(limit).compile(dialect=bind.dialect, compile_kwargs={"literal_binds": True}))
        plan = [str(r[3]) for r in corpus.execute(text("EXPLAIN QUERY PLAN " + sql)).all()]
        _LOG.warning("slow corpus mention read: %.1f s for %d terms; query plan: %s", elapsed, limit, " | ".join(plan))
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never break the drain that asked for it
        from src.monitoring.secret_scrub import log_failure

        log_failure(_LOG, "could not read the plan of the slow mention query", exc, level=logging.DEBUG)


class MentionCache:
    """Reuses the mention set for a time DERIVED FROM WHAT THE READ COST, so a slow corpus pays for it rarely and a fast one barely caches.

    The set is the corpus's most frequent keyword terms and it moves slowly; the wiki drain asked for it about every 98 s and each read cost
    8.4 s on average (3.5 h in total over 41 h). A read that took ``c`` seconds is reused for ``c / MENTION_READ_DUTY`` seconds, so the read
    itself is at most 1% of the wall time whatever the corpus size. NOT SHARED BETWEEN CORPORA OR LIMITS: it is one instance held by the one
    caller that owns a corpus, and a different ``limit`` reads again. A failed read raises and keeps nothing. STATED TRADE: the window has no upper bound, so a read
    that took 60 s keeps the set for 100 minutes, during which a keyword that became frequent in that time is not yet in the HOT tier (it joins at the next read)."""

    def __init__(self, monotonic: Any = None) -> None:
        import threading
        import time

        self._monotonic = monotonic or time.monotonic
        self._lock = threading.Lock()
        self._held: tuple[int, set[str], bool, float, str] | None = None  # limit, titles, capped, valid until, corpus
        self._plan_logged = False

    @staticmethod
    def _corpus_key(corpus: Any) -> str:
        """Which corpus database this session reads (the URL, whose password SQLAlchemy masks). Unreadable: a key no read can match."""
        try:
            return str(corpus.get_bind().url)
        except Exception:  # noqa: BLE001
            return f"unknown-{id(corpus)}"

    def get(self, corpus: Any, *, limit: int = MENTION_LIMIT) -> tuple[set[str], bool]:
        with self._lock:
            now = self._monotonic()
            held = self._held
            key = self._corpus_key(corpus)
            if held is not None and held[0] == limit and held[4] == key and now < held[3]:
                return set(held[1]), held[2]
            titles, capped = corpus_mention_titles(corpus, limit=limit)
            elapsed = max(0.0, self._monotonic() - now)
            if elapsed >= SLOW_MENTION_READ_S and not self._plan_logged:
                self._plan_logged = True
                _log_mention_plan(corpus, limit, elapsed)
            self._held = (limit, titles, capped, self._monotonic() + elapsed / MENTION_READ_DUTY, key)
            return set(titles), capped


def corpus_mention_titles(corpus: Any, *, limit: int = MENTION_LIMIT) -> tuple[set[str], bool]:
    """The corpus's own most-frequent keyword terms, and whether the cap was hit.

    TWO RETURN VALUES ON PURPOSE. A caller that got only the set could not tell a
    corpus with 4,000 keywords from one with 400,000 truncated to 5,000, and those
    lead to opposite readings of the same HOT tier size.

    THE ORDER IS THE INDEX'S, NOT AN EXPRESSION OF IT. ``ORDER BY coalesce(frequency, 0) DESC, term``
    was a scan of every keyword and a sort of all of them for the first 5,001: no index serves an
    expression, and on the 2.26 million keywords of the 16 Oct 2026 bundles it took 9.5 s on average
    over 224 calls (max 78 s) and held a read snapshot the whole time (the 08:34 pin report names
    this select, 56 s old). ``ORDER BY frequency DESC, term`` is read from ``idx_keyword_frequency``
    and the sort is only of the ties inside one frequency, so the first 5,001 are the first 5,001
    index entries (0.22 s to 0.013 s on a synthetic 2.3 million-keyword table). ONE DIFFERENCE, stated:
    a keyword with no frequency (NULL) now sorts after the ones with frequency 0 instead of tied
    with them, which can only change WHICH zero-frequency terms fill the last slots, and only on a
    corpus with fewer than 5,000 keywords that have a frequency of 1 or more. SQLAlchemy renders the
    ``limit`` as ``LIMIT ? OFFSET ?`` on SQLite (an OFFSET bound to 0): this is one page, not a pager.
    """
    rows = corpus.execute(_mention_statement(limit)).scalars().all()
    capped = len(rows) > limit
    return {r for r in rows[:limit] if r}, capped


def tracked_titles(corpus: Any, edition: str) -> set[str]:
    """Titles the operator already tracks in THIS edition (the legacy watch list).

    Reads ``wiki_pages`` — the surface that existed before this lane and still owns
    "the pages I follow by hand". Reading it rather than migrating it is what keeps a
    lane the operator turns on from silently dropping a watch list they built.
    """
    from src.database.models import WikiPage

    rows = (
        corpus.execute(select(WikiPage.title).where(WikiPage.wiki == edition)).scalars().all()
    )
    return {r for r in rows if r}


def followed_page_ids_by_edition(
    lane: Any, editions: tuple[str, ...]
) -> dict[str, tuple[set[int], set[int]]]:
    """``{edition: (pinned_ids, followed_ids)}`` from ONE read of the lane's entities.

    The drain builds its HOT sets every cycle (30 s), and this read used to run once PER
    EDITION: twelve full selects over every entity, each parsing every id and keeping the
    one edition's share. Measured on 200,000 entities: 2.3 s of one thread's CPU per drain
    (about 6,600 s a day; one pass reads it in 0.34 s), which the October bundles show as 2.4 to 6.1 thousand seconds
    of ``oo-wiki-drain`` CPU per session. One pass buckets by edition, so the cost no longer
    grows with the number of editions followed.
    """
    from src.versioned.models import VersionedEntity

    wanted = set(editions)
    out: dict[str, tuple[set[int], set[int]]] = {e: (set(), set()) for e in editions}
    rows = lane.execute(select(VersionedEntity.external_id, VersionedEntity.pinned)).all()
    for external_id, is_pinned in rows:
        # The edition prefix decides most rows before the id is parsed at all.
        if external_id.partition(":")[0] not in wanted:
            continue
        try:
            ident = parse_external_id(external_id)
        except ValueError:
            # An id this build cannot parse is SKIPPED and logged, never guessed at.
            _LOG.debug("skipping an unparseable entity id %r", external_id)
            continue
        if ident.page_id is None:
            continue
        pinned, followed = out[ident.wiki]
        followed.add(ident.page_id)
        if is_pinned:
            pinned.add(ident.page_id)
    return out


def followed_page_ids(lane: Any, edition: str) -> tuple[set[int], set[int]]:
    """``(pinned_ids, followed_ids)`` for one edition, from the lane's own entities.

    ``followed_ids`` is every entity this lane already has — the set that keeps a page
    HOT across a MOVE, since a move changes the title every other source speaks.
    ``pinned_ids`` is the subset the operator marked by hand (Q716).
    """
    return followed_page_ids_by_edition(lane, (edition,))[edition]


def build_hot_sets(
    *,
    corpus: Any,
    lane: Any,
    editions: tuple[str, ...],
    pageview_tops: dict[str, set[str]] | None = None,
    mention_limit: int = MENTION_LIMIT,
    mention_cache: MentionCache | None = None,
) -> tuple[dict[str, HotSet], dict[str, Any]]:
    """One :class:`HotSet` per edition, plus a report of how each was built.

    The report is not decoration. Every number in it is measured here and nowhere
    else, and it is what the task manager and the wizard show instead of asserting
    that the tier is working.
    """
    tops = pageview_tops or {}
    if mention_cache is not None:
        mentions, capped = mention_cache.get(corpus, limit=mention_limit)
    else:
        mentions, capped = corpus_mention_titles(corpus, limit=mention_limit)
    sets: dict[str, HotSet] = {}
    per_edition: dict[str, Any] = {}
    by_edition = followed_page_ids_by_edition(lane, editions)
    for edition in editions:
        pinned, followed = by_edition[edition]
        hs = HotSet(
            edition,
            pinned_ids=pinned,
            tracked_titles=tracked_titles(corpus, edition),
            corpus_mention_titles=mentions,
            pageview_top_titles=tops.get(edition, set()),
            hot_page_ids=followed,
        )
        sets[edition] = hs
        per_edition[edition] = hs.sizes()
    return sets, {
        "editions": per_edition,
        "mention_source": MENTION_SOURCE,
        "mention_limit": mention_limit,
        "mention_capped": capped,
        "pageview_editions_loaded": sorted(k for k, v in tops.items() if v),
        "caveat": (
            "HOT membership is measured from this machine: the corpus's own extracted "
            "keywords, the pages you track by hand, the editions' top-1,000 where a "
            "reading exists, and your pins. A subject the extractor did not keep as a "
            "keyword will not put its page in HOT."
            + (
                " The keyword set hit its cap, so the least frequent terms are not in it."
                if capped
                else ""
            )
        ),
    }
