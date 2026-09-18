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

from sqlalchemy import func, select

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


def corpus_mention_titles(corpus: Any, *, limit: int = MENTION_LIMIT) -> tuple[set[str], bool]:
    """The corpus's own most-frequent keyword terms, and whether the cap was hit.

    TWO RETURN VALUES ON PURPOSE. A caller that got only the set could not tell a
    corpus with 4,000 keywords from one with 400,000 truncated to 5,000, and those
    lead to opposite readings of the same HOT tier size.
    """
    from src.database.models import Keyword

    rows = (
        corpus.execute(
            select(Keyword.term)
            .where(Keyword.term.is_not(None))
            .order_by(func.coalesce(Keyword.frequency, 0).desc(), Keyword.term)
            .limit(limit + 1)
        )
        .scalars()
        .all()
    )
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


def followed_page_ids(lane: Any, edition: str) -> tuple[set[int], set[int]]:
    """``(pinned_ids, followed_ids)`` for one edition, from the lane's own entities.

    ``followed_ids`` is every entity this lane already has — the set that keeps a page
    HOT across a MOVE, since a move changes the title every other source speaks.
    ``pinned_ids`` is the subset the operator marked by hand (Q716).
    """
    from src.versioned.models import VersionedEntity

    pinned: set[int] = set()
    followed: set[int] = set()
    rows = lane.execute(
        select(VersionedEntity.external_id, VersionedEntity.pinned)
    ).all()
    for external_id, is_pinned in rows:
        try:
            ident = parse_external_id(external_id)
        except ValueError:
            # An id this build cannot parse is SKIPPED and logged, never guessed at.
            _LOG.debug("skipping an unparseable entity id %r", external_id)
            continue
        if ident.wiki != edition or ident.page_id is None:
            continue
        followed.add(ident.page_id)
        if is_pinned:
            pinned.add(ident.page_id)
    return pinned, followed


def build_hot_sets(
    *,
    corpus: Any,
    lane: Any,
    editions: tuple[str, ...],
    pageview_tops: dict[str, set[str]] | None = None,
    mention_limit: int = MENTION_LIMIT,
) -> tuple[dict[str, HotSet], dict[str, Any]]:
    """One :class:`HotSet` per edition, plus a report of how each was built.

    The report is not decoration. Every number in it is measured here and nowhere
    else, and it is what the task manager and the wizard show instead of asserting
    that the tier is working.
    """
    tops = pageview_tops or {}
    mentions, capped = corpus_mention_titles(corpus, limit=mention_limit)
    sets: dict[str, HotSet] = {}
    per_edition: dict[str, Any] = {}
    for edition in editions:
        pinned, followed = followed_page_ids(lane, edition)
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
