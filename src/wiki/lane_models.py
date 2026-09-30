"""The Wikipedia lane's own tables in ``wiki.db``: the ``allpages`` walk, WARM's texts, and their search.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q701 = c, verbatim: «Stream-forward plus a slow ``allpages`` walk for the tail, batched 50
per request, serial, under the storage budget (Q707), coverage reported per edition.» The
stream is ``versioned_*`` (0.4, S04-09). The walk is the three ``wiki_walk_*`` tables (0.5's
row F, S05-06's S2 + S3), and Q707's WARM tier the three ``wiki_warm_*`` ones (S1).

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

The walk's three tables are three different kinds of thing when that day comes, by the
rule ``fetch_history.py`` already applies to the corpus. ``wiki_walk_cursors`` is fetch
history in its exact sense -- state whose only purpose is to decide what to ask the server
next -- so it is what the trust toggle gates. ``wiki_walk_pages`` is CONTENT (the COLD
tier's metadata), and untrusting a history must never delete content. ``wiki_walk_samples``
measures THIS machine's transport, so it stays behind, for the reason ``last_checked_at``
does: a foreign instance's rate would claim a measurement this machine never made.

WARM's three follow the same rule. ``wiki_warm_pages`` is CONTENT (Q707's WARM texts,
latest + previous per Q710). ``wiki_warm_editions`` counts what THIS machine fetched, and
``wiki_warm_scan`` is a bookmark into this lane file's own change-row ids, which mean
nothing in another file -- so both stay behind.

The search index's four (``R52``/``R54``, ``src/wiki/lane_search.py``) are DERIVED, all of them:
``wiki_lane_docs`` says which stretch of which held text each index entry came from,
``wiki_lane_index_queue`` what is waiting to be (re)indexed, ``wiki_lane_index_state`` the
counts, and ``wiki_lane_tracked`` which of the old page tracker's versions the index has
already read. Every one of them can be rebuilt from the texts above, the stream's own
versions and the tracker's rows in ``corpus.db``, so none needs to ride a backup, and a
restore rebuilds rather than trusts them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.versioned.models import LaneBase, LaneCompressedText, LaneUTCDateTime


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


class WikiWarmPage(LaneBase):
    """One page of Q707's WARM tier: a changed page that is not HOT, and its text.

    Q707 = a: «WARM = every other changed page (full text, indexed lazily under the daily
    budget)». Q710 🔒 = a: «WARM: latest + previous». So a row holds AT MOST TWO texts --
    the latest this machine fetched and the one before it -- and a third fetch moves the
    latest into ``previous_*`` and drops the older. Two columns rather than a revisions
    table because two is the ruling, and a table would need a pruning pass to enforce what
    the shape here enforces by construction.

    WHY NOT ``versioned_entities``. For the reason the walk gives (see this module's
    docstring): every entity is a followed page, loaded on every drain as a HOT page id,
    whose every change is fetched and indexed. A WARM page kept there would be HOT by
    accident on its first fetch and forever after.

    THE QUEUE IS ``due_since``. It is set when the stream reports a revision newer than the
    stored text, cleared when a fetch stores one at least that new, and indexed with the
    edition so the next batch -- the pages that have waited longest -- is one range scan.
    ``wanted_revid`` is the newest revision the stream reported; ``wanted_at`` is when this
    app recorded that change. Both are the stream's, never guessed.

    A NORMAL ROWID TABLE, unlike ``wiki_walk_pages``: these rows carry whole wikitexts, and
    ``WITHOUT ROWID`` suits rows that are small beside a page of the file, which these are
    not.
    """

    __tablename__ = "wiki_warm_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edition: Mapped[str] = mapped_column(String(16), nullable=False)
    page_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The page's name as the latest answer gave it. NULL until the first fetch: the
    #: stream's change rows carry the page id, and a title guessed from elsewhere would
    #: be a second, unmeasured source for the same fact.
    title: Mapped[str | None] = mapped_column(String(512))
    wanted_revid: Mapped[int | None] = mapped_column(Integer)
    wanted_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    due_since: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    #: The latest text this machine fetched (Q704: the WIKITEXT, the source of truth).
    latest_revid: Mapped[int | None] = mapped_column(Integer)
    latest_text: Mapped[str | None] = mapped_column(LaneCompressedText)
    #: The UNCOMPRESSED length in UTF-8 bytes, as ``versioned_revisions.byte_size`` is --
    #: never the disk figure, which only the lane file's own size can give.
    latest_bytes: Mapped[int | None] = mapped_column(Integer)
    latest_revised_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    fetched_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    previous_revid: Mapped[int | None] = mapped_column(Integer)
    previous_text: Mapped[str | None] = mapped_column(LaneCompressedText)
    previous_bytes: Mapped[int | None] = mapped_column(Integer)
    previous_revised_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    #: Set when the stream reported a deletion, or the wiki answered that the page is
    #: missing. The texts are KEPT (Q713: «a deleted page keeps its last text and is
    #: marked deleted»); only the queue stops asking.
    deleted_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    #: Set when the page became HOT (the drain now follows it). WARM stops asking for it
    #: and KEEPS the texts it held: they are the page's history from BEFORE it was
    #: followed, which HOT's own versions start after, so dropping them would lose the
    #: one local copy of an older version.
    promoted_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    #: Why the latest answer stored no text for a page that still exists, as a token:
    #: ``not_an_article`` (moved out of the main namespace, or now a redirect -- Q703's
    #: scope), ``text_hidden`` (the wiki suppressed the revision's text) or ``unreadable``
    #: (a complete answer this app could not read as a text). NULL when the latest answer
    #: stored text. The next change the stream reports queues the page again.
    no_text_reason: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        UniqueConstraint("edition", "page_id", name="uq_wiki_warm_page"),
        Index("ix_wiki_warm_due", "edition", "due_since"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WikiWarmPage({self.edition}:{self.page_id} r{self.latest_revid})>"


class WikiWarmEdition(LaneBase):
    """One edition's WARM counts, written in the SAME transaction as the rows they count.

    For the reason ``WikiWalkCursor`` keeps its own: a status read touches twelve rows
    rather than counting a million, and a count written beside the rows it counts cannot
    disagree with them. ``pages_with_text`` is pages holding at least one stored text;
    ``texts_fetched`` counts every text stored, a page fetched three times counting three.
    """

    __tablename__ = "wiki_warm_editions"

    edition: Mapped[str] = mapped_column(String(16), primary_key=True)
    pages_with_text: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    texts_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: BIG for the reason ``WikiWalkCursor.response_bytes`` is.
    response_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: Pages that became HOT after WARM queued them. WARM stops asking for them and keeps
    #: the texts it already held; HOT keeps every version from then on (Q710).
    promoted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)


class WikiWarmScan(LaneBase):
    """How far WARM has read the stream's own change log: ONE row, keyed ``"changes"``.

    WARM is fed from ``versioned_changes`` -- the rows the drain already records for EVERY
    edit of every page (Q708 = b) -- rather than from a second listener on the stream, so
    there is one record of what the wiki reported and WARM reads it. The bookmark is the
    last change row's id, which only grows.
    """

    __tablename__ = "wiki_warm_scan"

    key: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_change_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)


class WikiLaneDoc(LaneBase):
    """One entry of the lane's own search index (``R52``): which held text it was read from.

    R52 keeps WARM's texts in the lane and gives them a search index of their own, so a
    term in a changed page's text, or in an older version of a page, is found from the one
    search box and can be added to the corpus as THAT version. The index is a contentless
    FTS5 table (``wiki_lane_fts``, created by ``src/wiki/lane_search.py``); its rowid is this
    row's ``id``, and this row is how a hit is traced back to the text it came from.

    ``extent`` says HOW MUCH of the version the entry holds, and it is the one thing a
    reader of a hit must know:

    * ``full`` -- the whole text. A WARM page's latest text, which the corpus does not hold;
      and an older version whose next version's text this lane does not keep, since nothing
      else would cover it.
    * ``dropped`` -- only the lines this version has and the next held version
      (``successor_revid``) no longer has: the lines an edit removed. Everything else in the
      older version is in the newer one, where it is already searchable, and indexing it
      again for every version would roughly double the lane's size for text that is
      already found. So an older version is found by what a later edit took out of it.

    ``source`` is ``warm`` (``owner_id`` is the ``wiki_warm_pages`` row), ``hot``
    (``owner_id`` is the ``versioned_entities`` row, the page the stream follows, whose
    NEWEST text is the corpus article and is searched there, never here) or ``tracked``
    (``R54``: ``owner_id`` is the page tracker's ``wiki_pages`` row in ``corpus.db``, whose
    stored versions are read from there; its newest version is indexed in full only when no
    corpus article is that revision). ``mask`` is the
    ``src.database.fts_norm`` transform the entry was indexed under (Arabic folding, CJK
    segmentation), recorded for the reason ``article_fts_norm`` records it.
    """

    __tablename__ = "wiki_lane_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)
    edition: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The wiki's page id where the lane knows it (a legacy title-keyed HOT page has none).
    page_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(512))
    #: The version this entry was read from.
    revid: Mapped[int] = mapped_column(Integer, nullable=False)
    extent: Mapped[str] = mapped_column(String(8), nullable=False)
    #: For ``dropped``: the later version these lines are gone from. NULL for a ``full`` latest.
    successor_revid: Mapped[int | None] = mapped_column(Integer)
    #: When the SOURCE says this version came into being, where it says so.
    revised_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    mask: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Characters of plain text indexed, a measurement of the entry rather than of the page.
    chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("source", "owner_id", "revid", "extent", name="uq_wiki_lane_doc"),
        Index("ix_wiki_lane_doc_owner", "source", "owner_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WikiLaneDoc({self.source}:{self.owner_id} r{self.revid} {self.extent})>"


class WikiLaneIndexQueue(LaneBase):
    """What waits to be (re)indexed: a WARM page whose text changed, a HOT version just stored.

    Filled by TRIGGERS on ``wiki_warm_pages`` and ``versioned_revisions``
    (``src/wiki/lane_search.py`` creates them), in the same transaction as the write they
    follow, so no text change can be missed however the indexer is scheduled and whatever
    the clock does. ``kind`` is ``warm`` (``ref`` = the WARM row) or ``hot`` (``ref`` = the
    revision). One row per thing, however often it changed while it waited.

    ``failed_at`` marks an item whose text could not be read into the index. It STAYS here,
    out of the way of the pending ones, so the count of such items is a count of rows rather
    than a tally that could drift from them, and it is tried again when the lane next starts
    or the page next changes -- a text a fault kept out is never out for good.
    """

    __tablename__ = "wiki_lane_index_queue"

    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    ref: Mapped[int] = mapped_column(Integer, primary_key=True)
    failed_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)

    __table_args__ = ({"sqlite_with_rowid": False},)


class WikiLaneIndexState(LaneBase):
    """The index's one state row, keyed ``"index"``: its format, its segmenters, its counts.

    The counts are written in the SAME transaction as the entries they count, for the
    reason ``WikiWarmEdition`` keeps its own: a status read touches one row instead of
    counting millions, and cannot disagree with the rows. ``format_version`` is what a later
    build compares to decide the index must be rebuilt rather than trusted.
    """

    __tablename__ = "wiki_lane_index_state"

    key: Mapped[str] = mapped_column(String(16), primary_key=True)
    format_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The ``src.database.fts_norm`` segmenters (jieba, sudachipy) the entries were written
    #: with. When this process has a different set, every held text is queued again, so the
    #: lane's Chinese and Japanese are split the way a query now splits them -- what the
    #: corpus's own re-index job does for ``article_fts``.
    segmenters: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    docs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: BIG: characters of text indexed across every entry, which can pass 2**31.
    chars: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)


class WikiLaneTracked(LaneBase):
    """Which versions of a TRACKED page the search index has read (``R54``): a derived mirror.

    ``R54`` («Track now», 2026-09-29): the versions the old page tracker stores in
    ``corpus.db`` (``wiki_revisions.full_text``) become searchable, indexed here in the lane's
    own file beside its other texts. The texts stay where they are; this table is what lets the
    indexer read a page's new versions only. One row per revision the tracker holds for a page,
    text or not, so a page's rows can be counted against the tracker's own without reading a
    single text (``owner_id`` = the tracker's ``wiki_pages`` row, which is what an index entry
    of source ``tracked`` names as its owner).

    ``successor_revid`` is the next version WITH a stored text when the entry was derived: an
    older version is indexed by the lines that version removed, so a different successor means
    the entry is stale. ``article_rev`` is the revision the tracker recorded as the page's
    newest text (the corpus article's) at that time: the newest version is indexed in full
    only while the article does not hold it. Both are recorded rather than recomputed because
    a comparison of the two stores would otherwise need every text read on every scan.

    ``WITHOUT ROWID`` as the walk's pages are: the key IS the row.
    """

    __tablename__ = "wiki_lane_tracked"

    owner_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    revid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    successor_revid: Mapped[int | None] = mapped_column(Integer)
    edition: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 1 when the tracker stored this revision's text, 0 when it stored none.
    has_text: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    article_rev: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = ({"sqlite_with_rowid": False},)


#: The wiki lane's own tables. ``src/versioned/store.create_schema`` materialises these in
#: ``wiki.db`` ONLY, exactly as ``LAW_LANE_MODELS`` go to ``law.db`` only.
WIKI_LANE_MODELS: tuple[type[LaneBase], ...] = (
    WikiWalkPage,
    WikiWalkCursor,
    WikiWalkSample,
    WikiWarmPage,
    WikiWarmEdition,
    WikiWarmScan,
    WikiLaneDoc,
    WikiLaneIndexQueue,
    WikiLaneIndexState,
    WikiLaneTracked,
)
