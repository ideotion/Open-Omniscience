"""The Wikipedia lane's own tables in ``wiki.db``: the ``allpages`` walk's page list and bookmark.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q701 = c, verbatim: «Stream-forward plus a slow ``allpages`` walk for the tail, batched 50
per request, serial, under the storage budget (Q707), coverage reported per edition.» The
stream is ``versioned_*`` (0.4, S04-09). The walk is these three tables, and it is 0.5's
row F (S05-06, S2 + S3).

WHY THE WALK DOES NOT WRITE ``versioned_entities``. That table is the list of pages the
lane FOLLOWS: ``src/wiki/hotset.py`` loads every entity on every drain as a HOT page id,
so an entity row is a page whose every change fetches its full text and indexes it into
the corpus. A walked page is COLD (Q707: "the tail reached by the walk (metadata now; text
as budget allows)") and must not become that by accident. Keeping the walk's pages in a
table the tier decision never reads is what makes that impossible rather than merely
avoided -- and it is why the walk could ship before WARM (``R40``, 2026-09-28).

WHAT A ROW SAYS AND WHAT IT DOES NOT. A ``wiki_walk_pages`` row says the edition LISTED this
page, under this title, with this size and this newest revision, when this machine asked.
It does not say the page still exists: a page deleted after the walk passed it keeps its
row, and the only honest reading of a row not refreshed by the latest pass is "not seen
since pass N", never "deleted". Nothing here guesses which.

THE WALK'S HISTORY LIVES HERE, AND IT RIDES A BACKUP WHEN THE LANE DOES. The Q701 NOTE asks
that every page request ride backups, with a "trust the backup scrapping history" toggle
on restore. These rows ARE that history for the walk. The lane is not a backup member yet
(``src/backup/inventory.py``: "its backup format is not settled yet"; Q721 rules it an
opt-in member, unbuilt), so the round trip waits on the lane riding, and the toggle
(``src/backup/fetch_history.py``) applies when it does. Stated rather than implied.

The three tables are three different kinds of thing when that day comes, by the rule
``fetch_history.py`` already applies to the corpus. ``wiki_walk_cursors`` is fetch history
in its exact sense -- state whose only purpose is to decide what to ask the server next --
so it is what the trust toggle gates. ``wiki_walk_pages`` is CONTENT (the COLD tier's
metadata), and untrusting a history must never delete content. ``wiki_walk_samples``
measures THIS machine's transport, so it stays behind, for the reason ``last_checked_at``
does: a foreign instance's rate would claim a measurement this machine never made.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.versioned.models import LaneBase, LaneUTCDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WikiWalkPage(LaneBase):
    """One article page the walk listed, keyed ``(edition, page_id)`` like the lane itself (Q715).

    ``WITHOUT ROWID`` because the key IS the row: a rowid table would store a second
    b-tree over the same two columns, and at twenty-four million rows across twelve
    editions that duplicate is gigabytes of an operator's disk for nothing.

    Every column but the key is what the source SAID, as it said it, or NULL when it said
    nothing. ``qid`` is NULL for a page the edition has not linked to Wikidata -- a real
    state, not a missing read -- and a later pass that finds one fills it.
    """

    __tablename__ = "wiki_walk_pages"

    edition: Mapped[str] = mapped_column(String(16), primary_key=True)
    page_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    #: The Wikidata item (``pageprops.wikibase_item``). The cross-edition key Q712's
    #: analytic 4 reads, hence the index below.
    qid: Mapped[str | None] = mapped_column(String(16))
    #: ``info.length``: the page's current size in BYTES of wikitext, as the edition
    #: reports it. Not the bytes this app stored -- the walk stores no text.
    length_bytes: Mapped[int | None] = mapped_column(Integer)
    #: ``info.lastrevid``. A later pass that sees a different one knows the page changed.
    last_revid: Mapped[int | None] = mapped_column(Integer)
    #: When THIS machine read the row, and in which pass. ``pass_no`` is what lets
    #: "seen in the current pass" be counted without a second table.
    walked_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    pass_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_wiki_walk_page_qid", "qid"),
        {"sqlite_with_rowid": False},
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WikiWalkPage({self.edition}:{self.page_id} {self.title!r})>"


class WikiWalkCursor(LaneBase):
    """Where one edition's walk got to: its bookmark, its counts, and its last refusal.

    ONE ROW PER EDITION, and the bookmark is the SOURCE's own continuation object, kept
    verbatim as JSON. MediaWiki's continuation contract is "send back exactly what you
    were given"; a walk that rebuilt it from the last title would skip or repeat pages
    the moment the edition's collation disagreed with ours, and nothing would say so.

    The counts are the walk's OWN, written in the same transaction as the page rows they
    count, so the two cannot disagree -- and a status read touches twelve rows instead of
    counting millions. ``edition_articles`` is the EDITION's own statistic, read from
    ``meta=siteinfo`` once a pass: the denominator of "pages seen of the edition", taken
    from the source, never estimated here. It counts content pages the edition's way,
    which is not exactly the set ``allpages`` lists, so the ratio can pass 100% and the
    surfaces say so.
    """

    __tablename__ = "wiki_walk_cursors"

    #: The edition code IS the key: one bookmark per edition, never two.
    edition: Mapped[str] = mapped_column(String(16), primary_key=True)
    #: 1 for the first walk of this edition. A later pass starts over from the top.
    pass_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The source's ``continue`` object, verbatim; NULL before the first request of a pass.
    continue_json: Mapped[str | None] = mapped_column(Text)
    #: Distinct pages recorded in THIS pass (a page listed twice counts once).
    pages_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Answered requests in this pass, and the bytes those answers weighed.
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: BIG, because one pass over the English edition answers several gigabytes of JSON
    #: and a 32-bit column (PostgreSQL's ``integer``, the Q1140 note) would overflow.
    response_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    #: Set when the source answered "no more pages". NULL while the pass is under way.
    completed_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    edition_articles: Mapped[int | None] = mapped_column(Integer)
    edition_articles_read_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    #: The refusals in a row since the last answered request, and the latest one's
    #: TOKEN (see ``src/wiki/walk.py``): what a status surface reads to say why an
    #: edition is waiting, which a log line cannot tell it.
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(32))
    last_error_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WikiWalkCursor({self.edition} pass {self.pass_no}: {self.pages_seen} seen)>"


class WikiWalkSample(LaneBase):
    """The walk's measured throughput, per hour and per TRANSPORT (Q722 = b; S05-06's S3).

    Q722 sends the walk over whatever transport the operator chose, Tor included, and the
    row asks for "the measured rate on the chosen transport". A rate needs a quantity and
    a time, both measured: this is requests, pages and bytes answered, and the time spent
    INSIDE those requests (``busy_ms``), summed per hour. The one-second pause between
    requests is etiquette, not throughput, and is not counted in ``busy_ms``; the hour
    itself says how much wall-clock time that was spread over.

    ``transport`` is the fetch path's own token (``src/safety/fetcher.py:transport_summary``):
    ``direct``, ``proxy`` or ``pool``. A refused transport sends nothing and has no rows.
    """

    __tablename__ = "wiki_walk_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hour_start: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False)
    transport: Mapped[str] = mapped_column(String(16), nullable=False)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    busy_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("hour_start", "transport", name="uq_wiki_walk_sample_hour"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WikiWalkSample({self.hour_start} {self.transport}: {self.pages} pages)>"


#: The wiki lane's own tables. ``src/versioned/store.create_schema`` materialises these in
#: ``wiki.db`` ONLY, exactly as ``LAW_LANE_MODELS`` go to ``law.db`` only.
WIKI_LANE_MODELS: tuple[type[LaneBase], ...] = (WikiWalkPage, WikiWalkCursor, WikiWalkSample)
