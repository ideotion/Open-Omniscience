"""The Wikipedia lane's own search index (``R52``): held texts found from the one search box.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``R52`` («In the lane», 2026-09-28) keeps WARM's texts in ``wiki.db``, under the lane's
budget and never corpus articles by themselves (Q719), with a search index of their own.
The maintainer's intent, stated with the ruling: «when a user searches a term present in
wikipedia articles (whether an article or the edit of an article, or a previous version of
an article), the user can incorporate that in its created corpus for analysis». So this
module answers two questions -- which held Wikipedia texts contain a term, and which exact
version of which page that was -- and ``src/wiki/corpus.py:add_wiki_version_article`` adds
that version to the corpus when the operator asks.

WHAT IS INDEXED, AND WHY NOT EVERYTHING.

* A WARM page's LATEST text, in full, title included. The corpus does not hold it.
* Every OLDER held version -- a WARM page's previous text, and each version of a followed
  (HOT) page but the newest -- by the lines a later edit REMOVED: the lines of that version
  the next held version no longer has (``extent = "dropped"``). The rest of an older version
  is in the newer one, where it is already found. MEASURED before this was built: an FTS5
  index of 1.94 MB of prose weighed 1.03 MB, 1.14x its compressed text, so indexing every
  held version in full would cost about that much again per version for text already found.
* NOT the newest version of a followed page. ``store_version`` hands every version of a
  followed page to the corpus, which keeps the newest, so that one is searched there.

THE ONE THING THIS CANNOT FIND, and every hit list says so (``CAVEAT``): an AND query whose
words sit partly in lines a version kept and partly in lines it lost finds neither version,
because the kept words are indexed with the newer version and the lost ones with the older.

HOW IT STAYS CURRENT. Triggers on ``wiki_warm_pages`` and ``versioned_revisions`` put a row in
``wiki_lane_index_queue`` in the same transaction as the write they follow, so no text change
is missed however the indexer is scheduled. :class:`LaneIndexer` drains that queue in the
lane's idle time, before WARM, for at most :data:`INDEX_SHARE` of each window. The first open
of a lane file that has texts but no index queues every one of them, in the same transaction
that creates the triggers, so nothing written in between is lost (:func:`ensure_index`).

A CONTENTLESS FTS5 TABLE with ``contentless_delete=1`` (SQLite 3.43+). The texts are already
stored, compressed, in the rows above; a second copy inside the index would double what the
operator's budget pays for. Contentless-delete removes an entry by its rowid alone, so an
entry never has to be re-derived to be removed -- the property ``article_fts_norm`` exists to
give the corpus index. An older SQLite (a system library on an older Linux, in plaintext mode
only: SQLCipher brings its own) gets a NAMED refusal, ``sqlite_too_old``, never a half-built
index.

THE TOKENIZER IS ``R39``'s FROM ITS FIRST DAY. ``categories 'L* N* Co M*'`` keeps combining
marks inside a word, so Hindi and Bengali are not split at every vowel sign. ``R39`` pays that
fix for ``article_fts`` inside row B's window because that table must be rebuilt to get it;
this one is new, so being right from the start costs nothing. Arabic folding and Chinese and
Japanese segmentation are ``src.database.fts_norm``'s, exactly as in the corpus index, so one
query finds both.

NOTHING HERE TOUCHES THE NETWORK. It reads what the lane already stored.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from src.database.fts import SearchQueryError, _bm25_weights, build_match
from src.database.fts_norm import (
    SEGMENTERS,
    available_mask,
    fold_arabic,
    index_entry,
    query_variants,
)

_LOG = logging.getLogger("wiki.lane_search")

#: The index table. Contentless, so it holds the index and nothing else.
FTS_TABLE = "wiki_lane_fts"
#: Bumped when what an entry holds changes; :func:`ensure_index` rebuilds an older index
#: rather than trusting it.
FORMAT_VERSION = 1
#: ``contentless_delete`` arrived in SQLite 3.43.0 (2023-08-24).
MIN_SQLITE: tuple[int, int, int] = (3, 43, 0)

SOURCE_WARM = "warm"  # ``owner_id`` is a ``wiki_warm_pages`` row
SOURCE_HOT = "hot"  # ``owner_id`` is a ``versioned_entities`` row, a page the lane follows
EXTENT_FULL = "full"
EXTENT_DROPPED = "dropped"
STATE_KEY = "index"

#: Why the index cannot answer, as TOKENS (the UI composes the words, ×12).
UNAVAILABLE_SQLITE = "sqlite_too_old"
UNAVAILABLE_NOT_BUILT = "index_not_built"

STATE_NOT_STARTED = "not_started"
STATE_INDEXING = "indexing"
STATE_CAUGHT_UP = "caught_up"
STATE_PAUSED = "paused"
STATE_UNAVAILABLE = "unavailable"

#: Queue rows settled per transaction. Small, so a search reading the lane never waits long
#: behind the indexer's write, and a fault rolls back little.
INDEX_BATCH = 100
#: The share of an idle window the indexer may take. The rest is WARM's and the walk's, so a
#: long backlog (a 0.4 lane's every older version, on its first open) never stops them.
INDEX_SHARE = 0.5
#: Characters in one snippet, and the time one search may spend building snippets. A hit
#: past the time budget is still listed, without a snippet, and the answer counts them.
SNIPPET_CHARS = 240
SNIPPET_BUDGET_S = 0.8

#: The one caveat every hit list carries, in the words the UI keys (×12).
CAVEAT = (
    "Older versions are found by the lines a later edit removed. A search whose words sit "
    "partly in kept lines and partly in removed ones finds neither version."
)
METHOD = (
    "SQLite FTS5 over the Wikipedia lane's own texts: each changed page's latest text in "
    "full, and each older held version by the lines the next held version no longer has; "
    "ranked by BM25 with the corpus index's title and body weights"
)

_FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS wiki_lane_fts USING fts5("
    "title, body, content='', contentless_delete=1, "
    "tokenize='unicode61 remove_diacritics 2 categories ''L* N* Co M*''')"
)

#: The queue's feeders. Each fires in the transaction of the write it follows, and an item
#: already waiting -- or one set aside after a failure -- is made pending again rather than
#: queued twice. The WARM update trigger reads OLD against NEW because an ORM update names
#: every column it set, changed or not. (No statement here takes a value from outside it.)
_TRIGGERS: dict[str, str] = {
    "wiki_lane_iq_warm_ai": (
        "CREATE TRIGGER IF NOT EXISTS wiki_lane_iq_warm_ai AFTER INSERT ON wiki_warm_pages "
        "WHEN NEW.latest_revid IS NOT NULL "
        "BEGIN INSERT INTO wiki_lane_index_queue(kind, ref) VALUES ('warm', NEW.id) "
        "ON CONFLICT(kind, ref) DO UPDATE SET failed_at = NULL; END"
    ),
    "wiki_lane_iq_warm_au": (
        "CREATE TRIGGER IF NOT EXISTS wiki_lane_iq_warm_au "
        "AFTER UPDATE OF latest_revid, previous_revid, title ON wiki_warm_pages "
        "WHEN NEW.latest_revid IS NOT OLD.latest_revid "
        "OR NEW.previous_revid IS NOT OLD.previous_revid "
        "OR (NEW.title IS NOT OLD.title AND NEW.latest_revid IS NOT NULL) "
        "BEGIN INSERT INTO wiki_lane_index_queue(kind, ref) VALUES ('warm', NEW.id) "
        "ON CONFLICT(kind, ref) DO UPDATE SET failed_at = NULL; END"
    ),
    "wiki_lane_iq_rev_ai": (
        "CREATE TRIGGER IF NOT EXISTS wiki_lane_iq_rev_ai AFTER INSERT ON versioned_revisions "
        "BEGIN INSERT INTO wiki_lane_index_queue(kind, ref) VALUES ('hot', NEW.id) "
        "ON CONFLICT(kind, ref) DO UPDATE SET failed_at = NULL; END"
    ),
}

#: Items a fault set aside, made pending again (:func:`retry_failed`, :func:`requeue_all`).
_RETRY_FAILED = "UPDATE wiki_lane_index_queue SET failed_at = NULL WHERE failed_at IS NOT NULL"

#: Everything already held, queued: when the index is new, a feeder was missing, or the
#: segmenters changed.
_BACKFILL = (
    "INSERT OR IGNORE INTO wiki_lane_index_queue(kind, ref) "
    "SELECT 'warm', id FROM wiki_warm_pages WHERE latest_revid IS NOT NULL",
    "INSERT OR IGNORE INTO wiki_lane_index_queue(kind, ref) SELECT 'hot', id FROM versioned_revisions",
    _RETRY_FAILED,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _version_tuple(value: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in (value or "").split(".")[:3]:
        digits = re.match(r"\d+", part)
        out.append(int(digits.group(0)) if digits else 0)
    return tuple(out)


def sqlite_supports_index(version: str) -> bool:
    """Whether a SQLite of ``version`` can hold this index (contentless-delete, 3.43+)."""
    return _version_tuple(version) >= MIN_SQLITE


def _as_revid(ref: Any) -> int | None:
    """A lane ``revision_ref`` as a MediaWiki revid, or ``None`` when it is not one."""
    try:
        value = int(str(ref))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# --------------------------------------------------------------------------- #
# The schema: the index table, its feeders, and the backfill
# --------------------------------------------------------------------------- #
def ensure_index(engine: Any) -> str:
    """Create the index and its feeders where missing. Idempotent and cheap when present.

    Returns ``"ready"`` (all there), ``"created"`` (something was missing and is now there,
    with every held text queued), ``"rebuilt"`` (an older format was dropped and started
    again) or :data:`UNAVAILABLE_SQLITE`. Called by ``src.versioned.store.create_schema`` for
    the wiki lane, after its tables exist, so the feeders are in place before the lane's
    first write; ONE transaction, so a text written while this runs is either queued by the
    backfill or by the trigger, never by neither.

    CHEAP ON PURPOSE when all is there -- two reads -- because ``wiki_lane_session`` runs
    ``create_lane``, and so this, on every drain open. Which is also why nothing that must
    happen once per START lives here (:meth:`LaneIndexer.index_for` retries set-aside
    items).
    """
    names = (FTS_TABLE, *_TRIGGERS)
    with engine.begin() as conn:
        version = str(conn.exec_driver_sql("SELECT sqlite_version()").scalar() or "")
        if not sqlite_supports_index(version):
            _LOG.info(
                "the Wikipedia lane search index needs SQLite %s or newer; this one is %s",
                ".".join(map(str, MIN_SQLITE)), version,
            )
            return UNAVAILABLE_SQLITE
        have = {
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')"
            )
        }
        stale = False
        if FTS_TABLE in have:
            fmt = conn.exec_driver_sql(
                "SELECT format_version FROM wiki_lane_index_state WHERE key = ?", (STATE_KEY,)
            ).scalar()
            stale = fmt is not None and int(fmt) < FORMAT_VERSION
        if not stale and all(name in have for name in names):
            return "ready"
        if stale:
            # A format change may change what a feeder queues as well as what an entry
            # holds, so the feeders are made again with the table.
            conn.exec_driver_sql("DROP TABLE IF EXISTS wiki_lane_fts")
            for name in _TRIGGERS:
                conn.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{name}"')
            have.discard(FTS_TABLE)
        if FTS_TABLE not in have:
            # A NEW index: any entry rows left from an earlier one describe entries that no
            # longer exist, so they go with it, and the counts start again.
            conn.exec_driver_sql(_FTS_DDL)
            conn.exec_driver_sql("DELETE FROM wiki_lane_docs")
            conn.exec_driver_sql("DELETE FROM wiki_lane_index_state")
        for ddl in _TRIGGERS.values():
            conn.exec_driver_sql(ddl)
        for sql in _BACKFILL:
            conn.exec_driver_sql(sql)
    _LOG.info("the Wikipedia lane search index is %s", "rebuilt" if stale else "created")
    return "rebuilt" if stale else "created"


def index_available(lane: Any) -> str | None:
    """``None`` when the index can answer on this lane session, else the reason token."""
    have = lane.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'wiki_lane_fts'")
    ).first()
    if have is not None:
        return None
    version = str(lane.execute(text("SELECT sqlite_version()")).scalar() or "")
    return UNAVAILABLE_NOT_BUILT if sqlite_supports_index(version) else UNAVAILABLE_SQLITE


# --------------------------------------------------------------------------- #
# What an entry holds
# --------------------------------------------------------------------------- #
def plain_text(wikitext: str | None) -> str:
    """A held wikitext as the index reads it: the corpus's own reduction, never a second one."""
    if not wikitext:
        return ""
    from src.wiki.corpus import plain_from_wikitext

    return plain_from_wikitext(wikitext)


def dropped_lines(older: str, newer: str) -> str:
    """The lines of ``older`` that ``newer`` does not have, once each, in ``older``'s order.

    Compared as SETS of stripped lines: a line an edit moved is not a line it removed, and
    one that occurs twice is found once. Both texts are plain text (:func:`plain_text`), so
    a markup change that leaves the words alone removes nothing.
    """
    kept = {line.strip() for line in newer.splitlines()}
    out: list[str] = []
    seen: set[str] = set()
    for line in older.splitlines():
        stripped = line.strip()
        if not stripped or stripped in kept or stripped in seen:
            continue
        seen.add(stripped)
        out.append(stripped)
    return "\n".join(out)


@dataclass(slots=True)
class _Entry:
    """One index entry, derived in full -- normalised too -- before anything is written."""

    source: str
    owner_id: int
    edition: str
    page_id: int | None
    title: str | None
    revid: int
    extent: str
    successor_revid: int | None
    revised_at: datetime | None
    #: The ``src.database.fts_norm`` transform applied, and the two values as the index holds them.
    mask: int
    index_title: str
    index_body: str
    #: Characters of plain text the entry was read from, before the transform.
    chars: int


def _entry(
    *,
    source: str,
    owner_id: int,
    edition: str,
    page_id: int | None,
    title: str | None,
    revid: int,
    extent: str,
    successor_revid: int | None,
    revised_at: datetime | None,
    index_title: str,
    body: str,
    caps: int,
) -> _Entry:
    mask, title_value, body_value = index_entry(index_title, body, caps)
    return _Entry(
        source=source, owner_id=owner_id, edition=edition, page_id=page_id,
        title=title[:512] if title else None, revid=revid, extent=extent,
        successor_revid=successor_revid, revised_at=revised_at, mask=mask,
        index_title=title_value or "", index_body=body_value or "",
        chars=len(index_title) + len(body),
    )


@dataclass(slots=True)
class _Plan:
    """One unit's entries, and which of its old entries they replace (``None``: all of them)."""

    source: str
    owner_id: int
    revids: list[int] | None
    entries: list[_Entry] = field(default_factory=list)


@dataclass(slots=True)
class _Tally:
    written: int = 0
    removed: int = 0
    docs: int = 0
    chars: int = 0

    def add(self, other: _Tally) -> None:
        self.written += other.written
        self.removed += other.removed
        self.docs += other.docs
        self.chars += other.chars


def _apply(lane: Any, plan: _Plan) -> _Tally:
    """Remove the owner's entries ``plan`` replaces, then write its entries. Writes only.

    Removal before writing, always. MEASURED on SQLite 3.45: a contentless FTS5 table
    ACCEPTS a second entry under a rowid it already holds, and after that the first entry's
    words stay findable even once the rowid is deleted -- an entry nothing can remove. A
    rowid deleted first and then written again is clean.
    """
    from src.wiki.lane_models import WikiLaneDoc

    tally = _Tally()
    wanted = None if plan.revids is None else sorted(set(plan.revids))
    if wanted is None or wanted:
        query = select(WikiLaneDoc).where(
            WikiLaneDoc.source == plan.source, WikiLaneDoc.owner_id == plan.owner_id
        )
        if wanted:
            query = query.where(WikiLaneDoc.revid.in_(wanted))
        for doc in lane.execute(query).scalars().all():
            # The index entry and its row go together, in one transaction: an entry whose
            # row is gone could never be deleted again, and a row whose entry is gone would
            # count words nothing can find.
            lane.execute(text("DELETE FROM wiki_lane_fts WHERE rowid = :id"), {"id": doc.id})
            tally.removed += 1
            tally.docs -= 1
            tally.chars -= int(doc.chars or 0)
            lane.delete(doc)
        lane.flush()
    for entry in plan.entries:
        doc = WikiLaneDoc(
            source=entry.source, owner_id=entry.owner_id, edition=entry.edition,
            page_id=entry.page_id, title=entry.title, revid=entry.revid, extent=entry.extent,
            successor_revid=entry.successor_revid, revised_at=entry.revised_at,
            mask=entry.mask, chars=entry.chars,
        )
        lane.add(doc)
        lane.flush()
        lane.execute(
            text("INSERT INTO wiki_lane_fts(rowid, title, body) VALUES (:id, :title, :body)"),
            {"id": doc.id, "title": entry.index_title, "body": entry.index_body},
        )
        tally.written += 1
        tally.docs += 1
        tally.chars += entry.chars
    return tally


def _warm_text(lane: Any, row_id: int, which: str) -> str | None:
    """ONE of a WARM row's two texts. Read column by column, so a text that cannot be
    decompressed takes down only what needs it, never its sibling."""
    from src.wiki.lane_models import WikiWarmPage

    column = WikiWarmPage.latest_text if which == "latest" else WikiWarmPage.previous_text
    return lane.execute(select(column).where(WikiWarmPage.id == row_id)).scalar()


def _plan_warm(lane: Any, row_id: int, caps: int) -> _Plan:
    """One WARM page's entries: its latest in full, its previous by dropped lines.

    EVERY entry of the row is replaced, not only those of the two held revids: the text a
    third fetch dropped (Q710) must stop being found the moment it stops being held.
    """
    from src.wiki.lane_models import WikiWarmPage

    plan = _Plan(SOURCE_WARM, row_id, None)
    head = lane.execute(
        select(
            WikiWarmPage.edition, WikiWarmPage.page_id, WikiWarmPage.title,
            WikiWarmPage.latest_revid, WikiWarmPage.latest_revised_at,
            WikiWarmPage.previous_revid, WikiWarmPage.previous_revised_at,
        ).where(WikiWarmPage.id == row_id)
    ).first()
    if head is None or not head.latest_revid:
        return plan
    raw = _warm_text(lane, row_id, "latest")
    if raw is None:
        return plan
    latest = plain_text(raw)
    title = head.title or ""
    common: dict[str, Any] = {"source": SOURCE_WARM, "owner_id": row_id, "edition": head.edition,
                              "page_id": head.page_id, "title": head.title, "caps": caps}
    if latest.strip() or title.strip():
        plan.entries.append(
            _entry(**common, revid=int(head.latest_revid), extent=EXTENT_FULL,
                   successor_revid=None, revised_at=head.latest_revised_at,
                   index_title=title, body=latest)
        )
    if head.previous_revid:
        before = _warm_text(lane, row_id, "previous")
        gone = dropped_lines(plain_text(before), latest) if before is not None else ""
        if gone:
            plan.entries.append(
                _entry(**common, revid=int(head.previous_revid), extent=EXTENT_DROPPED,
                       successor_revid=int(head.latest_revid),
                       revised_at=head.previous_revised_at, index_title="", body=gone)
            )
    return plan


@dataclass(slots=True)
class _Version:
    """One held version of a followed page, in the lane's own order."""

    kind: str  # "baseline" | "revision"
    row_id: int
    revid: int | None
    revised_at: datetime | None


def hot_chain(lane: Any, entity_id: int) -> list[_Version]:
    """A followed page's held versions, oldest first: the baseline, then the revisions.

    The revisions in the order ``src.versioned.revisions.previous_ingested`` reads them
    newest-first -- by ``revised_at``, an unknown date oldest, then by ``id`` -- so "the next
    held version" here is the version that function would have named.
    """
    from src.versioned.models import VersionedBaseline, VersionedRevision

    out: list[_Version] = []
    base = lane.execute(
        select(VersionedBaseline.id, VersionedBaseline.revision_ref, VersionedBaseline.revised_at)
        .where(VersionedBaseline.entity_id == entity_id)
    ).first()
    if base is not None:
        out.append(_Version("baseline", int(base[0]), _as_revid(base[1]), base[2]))
    for rid, ref, at in lane.execute(
        select(VersionedRevision.id, VersionedRevision.revision_ref, VersionedRevision.revised_at)
        .where(VersionedRevision.entity_id == entity_id)
        .order_by(VersionedRevision.revised_at.asc().nullsfirst(), VersionedRevision.id.asc())
    ).all():
        out.append(_Version("revision", int(rid), _as_revid(ref), at))
    return out


def _version_text(lane: Any, version: _Version) -> str | None:
    from src.versioned.models import VersionedBaseline, VersionedRevision

    model = VersionedBaseline if version.kind == "baseline" else VersionedRevision
    return lane.execute(select(model.content).where(model.id == version.row_id)).scalar()


def _plan_hot(lane: Any, entity_id: int, queued: set[int], caps: int) -> _Plan:
    """The entries a followed page's new versions changed.

    A new version makes the one before it OLDER (so it is now indexed by what the new one
    removed) and is itself the NEWEST (so it has no entry: the corpus article is it). A
    version that arrived out of order (a backfill) sits between two held ones, so both it
    and the one before it are re-derived. Everything else about the page is unchanged.
    """
    from src.versioned.models import VersionedEntity
    from src.wiki.identity import parse_external_id

    entity = lane.get(VersionedEntity, entity_id)
    if entity is None:
        return _Plan(SOURCE_HOT, entity_id, None)
    try:
        ident = parse_external_id(entity.external_id)
    except ValueError:
        _LOG.info("lane search: entity %s has no wiki identity; not indexed", entity_id)
        return _Plan(SOURCE_HOT, entity_id, [])
    title = entity.title or ident.title
    chain = hot_chain(lane, entity_id)
    positions: set[int] = set()
    for pos, version in enumerate(chain):
        if version.kind == "revision" and version.row_id in queued:
            positions.add(pos)
            if pos > 0:
                positions.add(pos - 1)
    touched: list[int] = []
    plan = _Plan(SOURCE_HOT, entity_id, touched)
    plains: dict[int, str | None] = {}

    def plain_at(pos: int) -> str | None:
        if pos not in plains:
            raw = _version_text(lane, chain[pos])
            plains[pos] = plain_text(raw) if raw is not None else None
            # Two texts at a time is all a pass needs; a page with hundreds of versions must
            # not hold them all in memory.
            for old in [p for p in plains if p < pos - 1]:
                plains.pop(old, None)
        return plains[pos]

    common: dict[str, Any] = {"source": SOURCE_HOT, "owner_id": entity_id, "edition": ident.wiki,
                              "page_id": ident.page_id, "title": title, "caps": caps}
    for pos in sorted(positions):
        version = chain[pos]
        if version.revid is None:
            continue
        touched.append(version.revid)
        if pos == len(chain) - 1:
            continue  # the newest: the corpus article holds it
        body = plain_at(pos)
        if not body:
            continue
        successor = chain[pos + 1]
        after = plain_at(pos + 1)
        if after is None:
            # The next version's text is not held, so nothing else covers this one.
            plan.entries.append(
                _entry(**common, revid=version.revid, extent=EXTENT_FULL,
                       successor_revid=successor.revid, revised_at=version.revised_at,
                       index_title="", body=body)
            )
            continue
        gone = dropped_lines(body, after)
        if gone:
            plan.entries.append(
                _entry(**common, revid=version.revid, extent=EXTENT_DROPPED,
                       successor_revid=successor.revid, revised_at=version.revised_at,
                       index_title="", body=gone)
            )
    return plan


@dataclass(slots=True)
class BatchResult:
    """What one queue batch did. Counts, never a verdict.

    ``settled`` is every queue row the batch took off the pending list, the ``failed`` ones
    among them."""

    settled: int = 0
    written: int = 0
    removed: int = 0
    failed: int = 0
    chars: int = 0
    stopped_early: bool = False


def _state(lane: Any, caps: int, now: datetime) -> Any:
    from src.wiki.lane_models import WikiLaneIndexState

    state = lane.get(WikiLaneIndexState, STATE_KEY)
    if state is None:
        state = WikiLaneIndexState(
            key=STATE_KEY, format_version=FORMAT_VERSION, segmenters=caps & SEGMENTERS,
            docs=0, chars=0, created_at=now, updated_at=now,
        )
        lane.add(state)
    return state


def index_batch(
    lane: Any,
    *,
    limit: int = INDEX_BATCH,
    caps: int | None = None,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = _utcnow,
) -> BatchResult:
    """Take up to ``limit`` pending queue rows off the queue, in ``lane``'s ONE transaction.

    The caller commits (``lane_session`` does), so a batch is all or nothing: a crash, or a
    fault in the lane itself (a ``SQLAlchemyError``, re-raised), leaves every row it took
    still pending and every entry as it was, and the counts cannot drift from the entries.

    NO SAVEPOINTS, deliberately. MEASURED on this driver's default transaction handling: a
    SAVEPOINT issued before a transaction's first write OPENS the transaction, its RELEASE
    COMMITS it, and a rollback afterwards undoes nothing -- so a savepoint per unit would
    commit unit by unit while its code read as one transaction. Instead each unit (one WARM
    page, or one followed page with every version of it the batch names) is DERIVED in full
    -- its texts read, reduced, compared and normalised -- before a single write of it, and
    only a unit that derived cleanly is written. A text that cannot be read or normalised
    fails its unit with nothing half-written: its rows are set aside with ``failed_at``,
    logged with the cause, and retried when the lane next starts or the page next changes
    (:func:`retry_failed`, the feeders).
    """
    from src.versioned.models import VersionedRevision
    from src.wiki.lane_models import WikiLaneIndexQueue

    result = BatchResult()
    rows = lane.execute(
        select(WikiLaneIndexQueue.kind, WikiLaneIndexQueue.ref)
        .where(WikiLaneIndexQueue.failed_at.is_(None))
        .order_by(WikiLaneIndexQueue.kind, WikiLaneIndexQueue.ref)
        .limit(max(1, int(limit)))
    ).all()
    if not rows:
        return result
    caps = available_mask() if caps is None else caps
    warm_refs = [int(ref) for kind, ref in rows if kind == SOURCE_WARM]
    hot_refs = [int(ref) for kind, ref in rows if kind == SOURCE_HOT]
    unknown = [(kind, ref) for kind, ref in rows if kind not in (SOURCE_WARM, SOURCE_HOT)]
    entity_of: dict[int, int] = {}
    if hot_refs:
        entity_of = {
            int(rid): int(eid)
            for rid, eid in lane.execute(
                select(VersionedRevision.id, VersionedRevision.entity_id).where(
                    VersionedRevision.id.in_(hot_refs)
                )
            ).all()
        }
    groups: dict[int, set[int]] = {}
    for ref in hot_refs:
        eid = entity_of.get(ref)
        if eid is not None:
            groups.setdefault(eid, set()).add(ref)

    units: list[tuple[str, int, set[int], list[int]]] = [
        (SOURCE_WARM, ref, set(), [ref]) for ref in warm_refs
    ]
    units += [(SOURCE_HOT, eid, refs, sorted(refs)) for eid, refs in groups.items()]
    # A queued revision that no longer exists has nothing to index; it is settled as is.
    done: dict[str, list[int]] = {SOURCE_WARM: [], SOURCE_HOT: [ref for ref in hot_refs if ref not in entity_of]}
    failed: dict[str, list[int]] = {SOURCE_WARM: [], SOURCE_HOT: []}
    tally = _Tally()
    for source, owner, queued, refs in units:
        if deadline is not None and monotonic() >= deadline and (
            done[SOURCE_WARM] or done[SOURCE_HOT] or failed[SOURCE_WARM] or failed[SOURCE_HOT]
        ):
            result.stopped_early = True
            break
        try:
            plan = _plan_warm(lane, owner, caps) if source == SOURCE_WARM else _plan_hot(lane, owner, queued, caps)
        except (SQLAlchemyError, MemoryError):
            raise  # the lane or the process, not this text: the whole batch waits
        except Exception as exc:  # noqa: BLE001 - one unreadable text must not stop the index
            # BROAD ON PURPOSE, and around the DERIVING only, which writes nothing: what fails
            # here is reading back a stored text (the decompressor's own errors), reducing its
            # markup, or a segmenter on a text it cannot take -- each this unit's alone.
            failed[source].extend(refs)
            result.failed += len(refs)
            _LOG.warning(
                "lane search: could not index %s %s (%s: %s); set aside, and tried again when "
                "the lane next starts or the page next changes",
                source, owner, type(exc).__name__, exc,
            )
            continue
        tally.add(_apply(lane, plan))
        done[source].extend(refs)
    for source, refs in done.items():
        if refs:
            lane.execute(
                delete(WikiLaneIndexQueue).where(
                    WikiLaneIndexQueue.kind == source, WikiLaneIndexQueue.ref.in_(refs)
                )
            )
    stamp = now()
    for source, refs in failed.items():
        if refs:
            lane.execute(
                update(WikiLaneIndexQueue)
                .where(WikiLaneIndexQueue.kind == source, WikiLaneIndexQueue.ref.in_(refs))
                .values(failed_at=stamp)
            )
    for kind, ref in unknown:
        _LOG.warning("lane search: an unknown queue kind %r (ref %s) was dropped", kind, ref)
        lane.execute(
            delete(WikiLaneIndexQueue).where(
                WikiLaneIndexQueue.kind == kind, WikiLaneIndexQueue.ref == ref
            )
        )
    state = _state(lane, caps, stamp)
    state.docs = max(0, int(state.docs or 0) + tally.docs)
    state.chars = max(0, int(state.chars or 0) + tally.chars)
    state.updated_at = stamp
    result.settled = sum(map(len, done.values())) + sum(map(len, failed.values())) + len(unknown)
    result.written = tally.written
    result.removed = tally.removed
    result.chars = tally.chars
    return result


def requeue_all(lane: Any) -> int:
    """Queue every held text again, and make every failed item pending. Returns the queue size.

    For the day the segmenters change (:meth:`LaneIndexer.index_for` notices): entries
    written without jieba hold a Chinese sentence as one token, and a query split by jieba
    would never find them. Re-deriving an entry REPLACES it, so this is safe at any time.
    """
    from src.wiki.lane_models import WikiLaneIndexQueue

    for sql in _BACKFILL:
        lane.execute(text(sql))
    return int(lane.execute(select(func.count()).select_from(WikiLaneIndexQueue)).scalar() or 0)


def retry_failed(lane: Any) -> int:
    """Make every set-aside item pending again. Returns how many.

    Once per START of the lane (:meth:`LaneIndexer.index_for`), so a fault since repaired
    -- a segmenter installed, a disk cleaned -- never keeps a text out for good, and one that
    still cannot be read costs one attempt and one log line per start, never a loop.
    """
    return int(lane.execute(text(_RETRY_FAILED)).rowcount or 0)


def follow_segmenters(lane: Any, caps: int) -> int:
    """Queue every held text again when this process's segmenters differ from the index's.

    Returns how many queue rows that left pending (0 when nothing changed). An index with no
    state row yet was just queued in full by :func:`ensure_index`, so it is left alone.
    """
    from src.wiki.lane_models import WikiLaneIndexState

    state = lane.get(WikiLaneIndexState, STATE_KEY)
    want = int(caps) & SEGMENTERS
    if state is None or int(state.segmenters or 0) == want:
        return 0
    queued = requeue_all(lane)
    _LOG.info(
        "lane search: the segmenters changed (%s to %s); %d held texts are queued again",
        state.segmenters, want, queued,
    )
    state.segmenters = want
    return queued


def queue_counts(lane: Any) -> tuple[int, int]:
    """``(pending, failed)``: counted over the queue's own rows, never kept as a tally."""
    from src.wiki.lane_models import WikiLaneIndexQueue

    pending = failed = 0
    for is_failed, n in lane.execute(
        select(WikiLaneIndexQueue.failed_at.is_not(None), func.count())
        .group_by(WikiLaneIndexQueue.failed_at.is_not(None))
    ).all():
        if is_failed:
            failed = int(n)
        else:
            pending = int(n)
    return pending, failed


def index_status(lane: Any) -> dict[str, Any]:
    """The index's counts from its own rows, or a named absence. Never counts the index."""
    from src.wiki.lane_models import WikiLaneIndexState

    reason = index_available(lane)
    if reason is not None:
        return {"available": False, "reason": reason}
    state = lane.get(WikiLaneIndexState, STATE_KEY)
    pending, failed = queue_counts(lane)
    return {
        "available": True,
        "entries": int(state.docs) if state else 0,
        "chars": int(state.chars) if state else 0,
        "pending": pending,
        "failed": failed,
        "updated_at": state.updated_at.isoformat() if state and state.updated_at else None,
    }


def search_coverage(lane: Any) -> dict[str, Any]:
    """What a lane search looked through: which editions, and how many pages hold a text there.

    OWED by ``R52`` so that a search with no Wikipedia hit is never read as «Wikipedia does not
    say this»: the lane holds only what THIS machine's stream and WARM fetched, and a hit list is
    about those texts and nothing wider. Counted from rows kept beside the texts (WARM's own
    per-edition counts, the stream's pages, the index's state and queue), never by counting the
    index itself.
    """
    from src.versioned.models import VersionedEntity
    from src.wiki.warm import warm_coverage

    warm = warm_coverage(lane)
    warm_editions = (
        [{"edition": r["edition"], "pages": r["pages_with_text"]} for r in warm["editions"]]
        if warm.get("measured")
        else []
    )
    # ``external_id`` is ``<edition>:p<pageid>`` or, for the few log events without a page
    # id, ``<edition>:<title>`` (``src/wiki/identity.py``); an edition name has no colon.
    edition = func.substr(
        VersionedEntity.external_id, 1, func.instr(VersionedEntity.external_id, ":") - 1
    )
    stream = [
        {"edition": str(name), "pages": int(n)}
        for name, n in lane.execute(
            select(edition, func.count(VersionedEntity.id)).group_by(edition).order_by(edition)
        ).all()
        if name
    ]
    warm_editions = [r for r in warm_editions if r["pages"]]  # an edition only QUEUED holds none
    status = index_status(lane)
    return {
        "editions": sorted({r["edition"] for r in warm_editions} | {r["edition"] for r in stream}),
        # Changed pages whose latest (and previous) text WARM holds: found by that text.
        "changed_pages": {
            "pages": sum(r["pages"] for r in warm_editions),
            "editions": warm_editions,
        },
        # Pages the stream follows or has followed (an entity the operator stops following
        # keeps its versions): their OLDER versions are found here; the newest is the corpus
        # article and is found among the corpus hits.
        "stream_pages": {"pages": sum(r["pages"] for r in stream), "editions": stream},
        "entries": status.get("entries"),
        "pending": status.get("pending"),
        "failed": status.get("failed"),
        "method": (
            "wiki_warm_editions' counts of pages holding text, versioned_entities grouped by "
            "edition, and the index's own state row and queue; the lane holds what this "
            "machine's Wikipedia stream and WARM fetched, nothing wider"
        ),
    }


# --------------------------------------------------------------------------- #
# The indexer, in the lane's idle time
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class IndexReport:
    """What one indexing window did."""

    batches: int = 0
    settled: int = 0
    written: int = 0
    removed: int = 0
    failed: int = 0
    chars: int = 0
    paused: str | None = None
    unavailable: str | None = None
    #: Held texts queued again this window because the segmenters changed (0 almost always).
    requeued: int = 0
    #: Set-aside items made pending again: the first window after a start only.
    retried: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "batches": self.batches,
            "settled": self.settled,
            "written": self.written,
            "removed": self.removed,
            "failed": self.failed,
            "chars": self.chars,
            "paused": self.paused,
            "unavailable": self.unavailable,
            "requeued": self.requeued,
            "retried": self.retried,
        }


def budget_pause(budget: Any) -> str | None:
    """The reason the indexer may not grow the lane file under ``budget``, or ``None``.

    The index lives in the lane file, so it is paid for from the lane's budget like the
    texts. A SPENT budget pauses it under the drain's own word; an unmeasured one pauses
    nothing, for the reason ``BudgetState.exhausted`` gives.
    """
    from src.wiki.walk import PAUSED_BUDGET

    return PAUSED_BUDGET if getattr(budget, "exhausted", False) else None


class LaneIndexer:
    """Drains the index queue in the lane's idle time. Every moving part is injected."""

    def __init__(
        self,
        *,
        lane_session: Callable[[], Any],
        budget: Callable[[], Any],
        batch: int = INDEX_BATCH,
        caps: Callable[[], int] = available_mask,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        if int(batch) < 1:
            raise ValueError("an index batch settles at least one queue row")
        self._lane_session = lane_session
        self._budget = budget
        self._batch = int(batch)
        self._caps = caps
        self._monotonic = monotonic
        self._now = now
        self.state: str = STATE_NOT_STARTED
        self.reason: str | None = None
        self.entries_this_process = 0
        self.last_indexed_at: datetime | None = None
        self._retried = False

    def _set(self, state: str, reason: str | None) -> None:
        if (state, reason) != (self.state, self.reason):
            _LOG.info("the Wikipedia lane search index is %s%s", state, f" ({reason})" if reason else "")
        self.state, self.reason = state, reason

    def index_for(self, seconds: float, *, should_stop: Callable[[], bool] = lambda: False) -> IndexReport:
        """Settle queue rows until ``seconds`` pass, the queue is empty, or a pause holds."""
        report = IndexReport()
        paused = budget_pause(self._budget())
        if paused:
            report.paused = paused
            self._set(STATE_PAUSED, paused)
            return report
        deadline = self._monotonic() + max(0.0, float(seconds))
        caps = self._caps()
        followed = False
        while not should_stop() and self._monotonic() < deadline:
            with self._lane_session() as lane:
                reason = index_available(lane)
                if reason is not None:
                    report.unavailable = reason
                    self._set(STATE_UNAVAILABLE, reason)
                    return report
                if not followed:
                    followed = True
                    report.requeued = follow_segmenters(lane, caps)
                    if not self._retried:
                        self._retried = True
                        report.retried = retry_failed(lane)
                out = index_batch(
                    lane, limit=self._batch, caps=caps, deadline=deadline,
                    monotonic=self._monotonic, now=self._now,
                )
            report.batches += 1
            report.settled += out.settled
            report.written += out.written
            report.removed += out.removed
            report.failed += out.failed
            report.chars += out.chars
            self.entries_this_process += out.written
            if out.settled:
                self.last_indexed_at = self._now()
            if out.settled < self._batch and not out.stopped_early:
                self._set(STATE_CAUGHT_UP, None)
                return report
        self._set(STATE_INDEXING, None)
        return report

    def status(self) -> dict[str, Any]:
        """This process's indexer state. No row read; the counts are :func:`index_status`'s."""
        return {
            "state": self.state,
            "reason": self.reason,
            "entries_this_process": self.entries_this_process,
            "last_indexed_at": self.last_indexed_at.isoformat() if self.last_indexed_at else None,
            "share": INDEX_SHARE,
        }


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
_QUERY_TOKEN = re.compile(r'"[^"]*"|\(|\)|[^\s()"]+')
_SPACES = re.compile(r"\s+")


def snippet_literals(query: str | None) -> list[str]:
    """The words and phrases a snippet should mark: the query's terms, less operators and
    the term after a NOT. Only for marking -- which entries match is FTS5's answer."""
    out: list[str] = []
    negate = False
    for tok in _QUERY_TOKEN.findall(query or ""):
        upper = tok.upper()
        if tok in ("(", ")") or upper in ("AND", "OR"):
            negate = False
            continue
        if upper == "NOT":
            negate = True
            continue
        value = tok[1:-1].strip() if len(tok) >= 2 and tok[0] == tok[-1] == '"' else tok
        if negate:
            negate = False
            continue
        if re.search(r"\w", value) and value not in out:
            out.append(value)
    return out


@lru_cache(maxsize=8192)
def _fold_char(ch: str) -> str:
    decomposed = unicodedata.normalize("NFKD", ch)
    kept = "".join(c for c in decomposed if not unicodedata.combining(c))
    return fold_arabic(kept).casefold() if kept else ""


def _folded(value: str) -> tuple[str, list[int]]:
    """``value`` case-, accent- and Arabic-folded, with each folded character's source index."""
    chars: list[str] = []
    where: list[int] = []
    for i, ch in enumerate(value):
        for out in _fold_char(ch):
            chars.append(out)
            where.append(i)
    return "".join(chars), where


def _spans(body: str, literals: list[str]) -> list[tuple[int, int]]:
    """Where the literals occur in ``body``: exact-case-insensitive first, folded if none."""
    found: list[tuple[int, int]] = []
    for lit in literals:
        for m in re.finditer(re.escape(lit), body, flags=re.IGNORECASE):
            if m.end() > m.start():
                found.append((m.start(), m.end()))
    if found:
        return sorted(set(found))
    folded, where = _folded(body)
    for lit in literals:
        needle, _ = _folded(lit)
        if not needle:
            continue
        start = folded.find(needle)
        while start >= 0:
            end = start + len(needle) - 1
            found.append((where[start], where[end] + 1))
            start = folded.find(needle, start + len(needle))
    return sorted(set(found))


def snippet(body: str, literals: list[str], *, width: int = SNIPPET_CHARS) -> list[dict[str, Any]]:
    """A window of ``body`` around its first match, as ``[{"text", "hit"}]`` parts.

    PARTS, NOT OFFSETS: a browser counts a string in UTF-16 units and Python in code
    points, so an offset into a text with an emoji or a rare Han character would mark the
    wrong letters. Parts carry their own text and need no counting.
    """
    body = body or ""
    spans = _spans(body, literals) if literals else []
    if not spans:
        cut = body[:width]
        return [{"text": _SPACES.sub(" ", cut).strip() + ("…" if len(body) > width else ""), "hit": False}]
    first = spans[0][0]
    start = max(0, first - width // 3)
    end = min(len(body), start + width)
    if start > 0:
        space = body.find(" ", start, first)
        start = space + 1 if space >= 0 else start
    if end < len(body):
        space = body.rfind(" ", spans[0][1], end)
        end = space if space > 0 else end
    parts: list[dict[str, Any]] = []
    if start > 0:
        parts.append({"text": "…", "hit": False})
    cursor = start
    for s, e in spans:
        if s < cursor or s >= end:
            continue
        e = min(e, end)
        if s > cursor:
            parts.append({"text": _SPACES.sub(" ", body[cursor:s]), "hit": False})
        parts.append({"text": body[s:e], "hit": True})
        cursor = e
    if cursor < end:
        parts.append({"text": _SPACES.sub(" ", body[cursor:end]), "hit": False})
    if end < len(body):
        parts.append({"text": "…", "hit": False})
    return parts


@dataclass(slots=True)
class HeldVersion:
    """One version this lane holds, addressed as a search hit addresses it."""

    source: str
    owner_id: int
    edition: str
    page_id: int | None
    title: str | None
    revid: int
    revised_at: datetime | None
    text: str
    #: The newest held version of a followed page: the corpus article already is it.
    newest_followed: bool = False
    deleted: bool = False


def held_version(
    lane: Any, source: str, owner_id: int, revid: int, *, check_newest: bool = True
) -> HeldVersion | None:
    """The text of ``revid`` of one page, when this lane holds it; ``None`` otherwise.

    ``check_newest`` reads the followed page's version list to say whether this is its
    newest, which the corpus article already is; a snippet needs only the text."""
    from src.versioned.models import VersionedBaseline, VersionedEntity, VersionedRevision
    from src.wiki.identity import parse_external_id
    from src.wiki.lane_models import WikiWarmPage

    if source == SOURCE_WARM:
        head = lane.execute(
            select(
                WikiWarmPage.edition, WikiWarmPage.page_id, WikiWarmPage.title,
                WikiWarmPage.deleted_at, WikiWarmPage.latest_revid, WikiWarmPage.latest_revised_at,
                WikiWarmPage.previous_revid, WikiWarmPage.previous_revised_at,
            ).where(WikiWarmPage.id == owner_id)
        ).first()
        if head is None:
            return None
        if head.latest_revid == revid:
            which, warm_at = "latest", head.latest_revised_at
        elif head.previous_revid == revid:
            which, warm_at = "previous", head.previous_revised_at
        else:
            return None
        warm_text = _warm_text(lane, owner_id, which)
        if warm_text is None:
            return None
        return HeldVersion(
            source=SOURCE_WARM, owner_id=owner_id, edition=head.edition, page_id=head.page_id,
            title=head.title, revid=revid, revised_at=warm_at, text=warm_text,
            deleted=head.deleted_at is not None,
        )
    if source != SOURCE_HOT:
        return None
    entity = lane.get(VersionedEntity, owner_id)
    if entity is None:
        return None
    try:
        ident = parse_external_id(entity.external_id)
    except ValueError:
        return None
    ref = str(revid)
    body: str | None = None
    at: datetime | None = None
    rev = lane.execute(
        select(VersionedRevision).where(
            VersionedRevision.entity_id == owner_id, VersionedRevision.revision_ref == ref
        )
    ).scalar_one_or_none()
    if rev is not None:
        body, at = rev.content, rev.revised_at
    else:
        base = lane.execute(
            select(VersionedBaseline).where(
                VersionedBaseline.entity_id == owner_id, VersionedBaseline.revision_ref == ref
            )
        ).scalar_one_or_none()
        if base is not None:
            body, at = base.content, base.revised_at
    if body is None:
        return None
    newest = False
    if check_newest:
        chain = hot_chain(lane, owner_id)
        newest = bool(chain) and chain[-1].revid == revid
    return HeldVersion(
        source=SOURCE_HOT, owner_id=owner_id, edition=ident.wiki, page_id=ident.page_id,
        title=entity.title or ident.title, revid=revid, revised_at=at, text=body,
        newest_followed=newest, deleted=entity.deleted_at is not None,
    )


def _indexed_body(lane: Any, doc: Any) -> str | None:
    """The plain text an entry was indexed from, re-derived the way it was derived."""
    held = held_version(lane, doc.source, doc.owner_id, doc.revid, check_newest=False)
    if held is None:
        return None
    body = plain_text(held.text)
    if doc.extent != EXTENT_DROPPED or doc.successor_revid is None:
        return body
    after = held_version(
        lane, doc.source, doc.owner_id, int(doc.successor_revid), check_newest=False
    )
    if after is None:
        return body
    return dropped_lines(body, plain_text(after.text))


def _unavailable(reason: str, query: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "query": query, "total": None, "items": []}


def search(
    lane: Any,
    query: str | None,
    *,
    limit: int = 20,
    offset: int = 0,
    snippets: bool = True,
    queue: bool = True,
    snippet_budget_s: float = SNIPPET_BUDGET_S,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """The held Wikipedia texts matching ``query``, best first, with an EXACT total.

    ``queue`` adds how many texts wait for the index and how many were set aside -- a count
    over the queue, which a long first backlog makes worth skipping per keystroke.

    ``total`` is ``count(*)`` over the same MATCH the ranked rows come from, so the number
    and the list describe one set, and a limit never becomes a count (the 2026-07-18
    ruling: «a cap may bound which EXAMPLES are listed; it must never bound a displayed
    NUMBER»). ``None`` means the query had nothing to search for, never "no match".
    """
    from src.versioned.models import VersionedEntity
    from src.wiki.corpus import wiki_version_url
    from src.wiki.lane_models import WikiLaneDoc, WikiWarmPage

    q = " ".join((query or "").split())
    reason = index_available(lane)
    if reason is not None:
        return _unavailable(reason, q)
    base: dict[str, Any] = {"available": True, "query": q, "method": METHOD, "caveat": CAVEAT}
    if queue:
        base["pending"], base["failed"] = queue_counts(lane)
    try:
        match = build_match(q, variants=query_variants)
    except SearchQueryError as exc:
        return {**base, "total": None, "items": [], "error": "query_invalid", "detail": str(exc)}
    if match is None:
        return {**base, "total": None, "items": []}
    total = int(
        lane.execute(
            text("SELECT count(*) FROM wiki_lane_fts WHERE wiki_lane_fts MATCH :q"), {"q": match}
        ).scalar()
        or 0
    )
    wt, wb = _bm25_weights()
    ids = [
        int(r[0])
        for r in lane.execute(
            text(
                "SELECT rowid FROM wiki_lane_fts WHERE wiki_lane_fts MATCH :q "
                "ORDER BY bm25(wiki_lane_fts, :wt, :wb) LIMIT :lim OFFSET :off"
            ),
            {"q": match, "wt": wt, "wb": wb, "lim": max(1, int(limit)), "off": max(0, int(offset))},
        ).all()
    ]
    docs = {d.id: d for d in lane.execute(select(WikiLaneDoc).where(WikiLaneDoc.id.in_(ids))).scalars()} if ids else {}
    warm_ids = sorted({d.owner_id for d in docs.values() if d.source == SOURCE_WARM})
    hot_ids = sorted({d.owner_id for d in docs.values() if d.source == SOURCE_HOT})
    warm_rows = {
        r[0]: r[1:]
        for r in lane.execute(
            select(WikiWarmPage.id, WikiWarmPage.title, WikiWarmPage.deleted_at).where(
                WikiWarmPage.id.in_(warm_ids)
            )
        ).all()
    } if warm_ids else {}
    entities = {
        r[0]: r[1:]
        for r in lane.execute(
            select(VersionedEntity.id, VersionedEntity.title, VersionedEntity.deleted_at).where(
                VersionedEntity.id.in_(hot_ids)
            )
        ).all()
    } if hot_ids else {}
    literals = snippet_literals(q)
    started = monotonic()
    skipped = 0
    items: list[dict[str, Any]] = []
    for doc_id in ids:
        doc = docs.get(doc_id)
        if doc is None:
            continue
        owner = warm_rows.get(doc.owner_id) if doc.source == SOURCE_WARM else entities.get(doc.owner_id)
        title = (owner[0] if owner and owner[0] else None) or doc.title
        item: dict[str, Any] = {
            "doc_id": doc.id,
            "source": doc.source,
            "owner_id": doc.owner_id,
            "edition": doc.edition,
            "page_id": doc.page_id,
            "title": title,
            "revid": doc.revid,
            "extent": doc.extent,
            "successor_revid": doc.successor_revid,
            "revised_at": doc.revised_at.isoformat() if doc.revised_at else None,
            "deleted": bool(owner and owner[1] is not None),
            "url": wiki_version_url(doc.edition, title, doc.revid),
            "snippet": None,
        }
        if snippets:
            if monotonic() - started <= snippet_budget_s:
                try:
                    body = _indexed_body(lane, doc)
                except MemoryError:
                    raise
                except Exception:  # noqa: BLE001 - a snippet must never fail the search
                    # The hit stands without one: the list and the total are the index's
                    # answer, and a text that cannot be read back is the indexer's to report.
                    _LOG.debug("lane search: no snippet for entry %s", doc.id, exc_info=True)
                    body = None
                if body is not None:
                    item["snippet"] = snippet(body, literals)
            else:
                skipped += 1
        items.append(item)
    return {**base, "total": total, "items": items, "snippets_skipped": skipped}
