"""One pass of one lane: read the feed, store what the budget allows, index the latest.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the module the brief's S1 acceptance clause names: *"one fixture page
round-trips baseline -> change -> revision -> Article; point in time reads."* It
composes the pieces and adds nothing the pieces do not already own — the store
opens the file, the feed dedups and detects gaps, the revision store diffs, the
adapter speaks the source's language, and ``index_article`` indexes.

TWO KINDS OF "WE DID NOT SEE IT", AND THEY MUST NOT MERGE.

* A **feed gap** is a stretch of the CHANGE LOG this app was never handed. It is
  recorded in ``versioned_gaps`` and it is a claim about coverage.
* An **un-ingested change** is a change we WERE told about and chose not to fetch
  the text of, because the budget ran out. It is an ordinary
  ``versioned_changes`` row with ``ingested_revision_id IS NULL``.

The first means "we cannot say what happened"; the second means "we know exactly
what happened and did not keep the text". Merging them would let a lane under a
tight budget report itself as having holes in its knowledge when it has holes only
in its storage — and, worse, would let a real retention gap hide among them.

* A **withheld text** (added for S04-09) is the THIRD member of that family and
  gets its own counter and its own reason string: the caller's ``text_policy`` said
  not to fetch this one, and said WHY. A storage budget that is full and a tier this
  release does not ingest are both legitimate answers and they are not the same
  answer — folding either into ``text_deferred`` would report a lane working exactly
  as ruled as a lane that ran out of room.

NOTHING HERE REACHES THE NETWORK. Every outbound call belongs to the adapter's
client, which the caller supplies. That is what lets the whole pass run in CI with
the airplane socket guard armed, and it is the property
``tests/test_versioned_lane.py::test_a_full_pass_makes_ZERO_NAME_RESOLUTIONS`` asserts
by counting resolutions rather than requests — a DNS lookup is itself egress. The
wiki lane (``tests/test_wiki_lane_end_to_end.py``) and the law lane
(``tests/test_law_lane_offline.py``) are measured the same way end to end.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.versioned import feed as feedmod
from src.versioned import revisions as revmod
from src.versioned.adapters.base import FetchedVersion, ReadBudget, VersionedAdapter
from src.versioned.feed import FeedChange
from src.versioned.models import VersionedChange, VersionedEntity, _utcnow

_LOG = logging.getLogger("versioned.pipeline")


@dataclass(slots=True)
class PassResult:
    """What one pass did. Counts and named refusals — never a verdict about the lane."""

    feed: str
    changes_recorded: int = 0
    changes_duplicate: int = 0
    changes_unknown_kind: int = 0
    gap_recorded: bool = False
    baselines_captured: int = 0
    revisions_stored: int = 0
    revisions_unchanged: int = 0
    articles_indexed: int = 0
    #: Changes recorded whose text this pass did not fetch, because the budget ran
    #: out. NOT a gap — see the module docstring.
    text_deferred: int = 0
    #: Entities this pass STARTED following because ``admit`` said to. Its own
    #: counter because "the lane grew" is a fact an operator is owed: a rule that
    #: admits pages is still the operator's choice, but it is a choice they made
    #: once and this is where its consequences become visible.
    entities_admitted: int = 0
    #: Entities whose text ``text_policy`` withheld, and the tally by REASON. Two
    #: fields rather than one because the total is what a status line shows and the
    #: breakdown is what makes it actionable — a lane withholding 100,000 texts
    #: because a tier is not built yet and one withholding them because the disk is
    #: full need opposite responses from the operator.
    text_withheld: int = 0
    text_withheld_reasons: dict[str, int] = field(default_factory=dict)
    #: Entities the source reported as GONE this pass. Its own counter and NOT an
    #: error: a deletion is a fact about the source, and filing it under errors
    #: would make a lane that is working correctly look like one that is failing —
    #: and would bury a real failure among the deletions.
    deleted_reported: int = 0
    #: Per-entity failures, named. A pass never dies on one bad entity, and it never
    #: swallows the reason either.
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        """A plain dict for a job report. No field name carries a banned fragment."""
        return {
            "feed": self.feed,
            "changes_recorded": self.changes_recorded,
            "changes_duplicate": self.changes_duplicate,
            "changes_unknown_kind": self.changes_unknown_kind,
            "gap_recorded": self.gap_recorded,
            "baselines_captured": self.baselines_captured,
            "revisions_stored": self.revisions_stored,
            "revisions_unchanged": self.revisions_unchanged,
            "articles_indexed": self.articles_indexed,
            "text_deferred": self.text_deferred,
            "entities_admitted": self.entities_admitted,
            "text_withheld": self.text_withheld,
            "text_withheld_reasons": dict(self.text_withheld_reasons),
            "deleted_reported": self.deleted_reported,
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class Admission:
    """What an ``admit`` callback returns when a lane should START following a thing.

    A dataclass rather than a bare ``True`` because the moment of admission is the
    only moment the caller has the source's own words for this entity in hand — the
    title it was changed under, its language, a QID if the change carried one. Losing
    them here costs a second request later, per entity, to learn what we were already
    told.

    ``None`` from the callback means "do not follow this", which stays the default
    for every lane that passes no callback at all.
    """

    title: str | None = None
    qid: str | None = None
    language: str | None = None
    country_alpha3: str | None = None
    #: Whether the operator asked for this page BY HAND (Q716's pin). Never set by a
    #: rule: a rule that could pin would make the operator's own mark unreadable.
    pinned: bool = False
    #: The token naming WHY the lane is admitting this. Stored on the entity, so a
    #: surface listing 40,000 followed pages can say which rule brought each one in
    #: rather than asking the operator to take the count on faith.
    reason: str | None = None


def ensure_entity(
    lane: Session,
    external_id: str,
    *,
    title: str | None = None,
    qid: str | None = None,
    language: str | None = None,
    country_alpha3: str | None = None,
    pinned: bool = False,
    admitted_reason: str | None = None,
) -> VersionedEntity:
    """Get or create the tracked entity for ``external_id``.

    Fills a NULL, never overwrites a value. The rule is the recorded
    qualification one, one subject over: an existing row's ``title`` may have been
    corrected by an operator, and a later automated read must not revert it.
    ``pinned`` is the exception and is deliberately one-way here — a caller asking
    to pin means it; unpinning is its own action, not a side effect of a read.
    """
    row = lane.execute(
        select(VersionedEntity).where(VersionedEntity.external_id == external_id)
    ).scalar_one_or_none()
    if row is None:
        row = VersionedEntity(
            external_id=external_id,
            title=title,
            qid=qid,
            language=language,
            country_alpha3=country_alpha3,
            pinned=pinned,
            admitted_reason=admitted_reason,
        )
        lane.add(row)
        lane.flush()
        return row
    if title and not row.title:
        row.title = title
    if qid and not row.qid:
        row.qid = qid
    if language and not row.language:
        row.language = language
    if country_alpha3 and not row.country_alpha3:
        row.country_alpha3 = country_alpha3
    if pinned:
        row.pinned = True
    if admitted_reason and not row.admitted_reason:
        # FILLS A NULL, never overwrites. A page admitted for one reason and later
        # matching another was admitted ONCE, and rewriting the record of that to
        # the newest matching rule would erase the history the column exists to keep.
        row.admitted_reason = admitted_reason
    return row


def store_version(
    lane: Session,
    adapter: VersionedAdapter,
    entity: VersionedEntity,
    version: FetchedVersion,
    *,
    corpus: Session | None = None,
) -> tuple[str, int | None]:
    """Store one fetched version in the LANE and, given a corpus session, index it.

    TWO SESSIONS, NAMED, BECAUSE THERE ARE TWO FILES. ``lane`` writes
    ``wiki.db``/``law.db``/``osm.db``; ``corpus`` writes ``corpus.db`` through the
    existing ``index_article`` path. Passing one session for both would be a
    silent bug the type system cannot see — and hiding the second behind a global
    would hide exactly the architecture Q719/Q1004 are about. ``corpus=None`` means
    "store the version, index nothing", which is a real mode (a lane catching up on
    history it does not want in the corpus yet).

    THEY ARE NOT ONE TRANSACTION, AND THEY CANNOT BE. Two SQLite files have two
    transactions; there is no two-phase commit here and none is pretended. The
    order is chosen so the failure mode is the recoverable one: the Article is
    written FIRST and the lane revision second, so a crash between them leaves a
    corpus article with no lane revision pointing at it — which the next pass
    re-links, because ``upsert_wiki_corpus_article`` is idempotent on the content
    hash. The other order would leave a lane revision claiming an ``article_id``
    that was never committed, which nothing later can detect.

    Returns ``(outcome, article_id)`` where outcome is ``baseline`` | ``revision`` |
    ``unchanged``.

    ``unchanged`` is a REAL outcome, not a failure: a source can publish a new
    version whose text is identical to the one we hold (a null edit; a template
    change that our reduction drops). The change was already recorded by the feed,
    so nothing is lost by declining to store a duplicate body — and storing one
    would put a row in the timeline that a reader opening the diff would find empty
    with no explanation.
    """
    base = revmod.baseline_for(lane, entity.id)
    if base is None:
        article_id = adapter.to_article(corpus, version) if corpus is not None else None
        row = revmod.capture_baseline(
            lane,
            entity,
            revision_ref=version.revision_ref,
            text=version.text,
            revised_at=version.revised_at,
        )
        entity.last_checked_at = _utcnow()
        # The baseline has no article column: the ARTICLE is the latest state and
        # the baseline is the anchor. Linking it would make the corpus row read as
        # a record of the FIRST version forever.
        _LOG.debug("baseline %s, corpus article %s", row.revision_ref, article_id)
        return ("baseline", article_id)

    held = revmod.previous_ingested(lane, entity.id)
    # The hash comparison is guarded by the two None checks rather than nested under
    # them (SIM102): a lane that holds a version's METADATA without its TEXT is a real
    # state, and it is not the same as holding no previous version at all.
    if (
        held is not None
        and held[1] is not None
        and revmod.content_hash(held[1]) == revmod.content_hash(version.text)
    ):
        entity.last_checked_at = _utcnow()
        return ("unchanged", None)

    article_id = adapter.to_article(corpus, version) if corpus is not None else None
    revmod.record_revision(
        lane,
        entity,
        revision_ref=version.revision_ref,
        text=version.text,
        revised_at=version.revised_at,
        article_id=article_id,
    )
    return ("revision", article_id)


def run_feed_once(
    lane: Session,
    adapter: VersionedAdapter,
    feed: str,
    *,
    corpus: Session | None = None,
    budget: ReadBudget | None = None,
    admit: Callable[[FeedChange], Admission | None] | None = None,
    text_policy: Callable[[VersionedEntity], tuple[bool, str | None]] | None = None,
) -> PassResult:
    """One pass: read the feed, record every change, fetch what the budget allows.

    THE ORDER IS THE HONESTY. Changes are recorded FIRST, in full, before a single
    text is fetched — so a pass that dies half way through fetching still leaves a
    complete record of what it was told, and the next pass can tell which of those
    it has not yet stored. Fetching first and recording after would lose exactly the
    changes a crash interrupted, with nothing anywhere to say they existed.

    ``admit`` lets a lane start following something it was merely TOLD about. It runs
    BEFORE the batch is recorded, so a page admitted on the edit that first mentions
    it has that very change linked to it — running it afterwards would leave the
    admitting change orphaned and the page would wait for its NEXT edit before any
    text arrived. It exists because S04-09's HOT tier (Q707) is a rule the operator
    set once — "follow the pages my corpus mentions" — and the default without it is
    unchanged: no callback, no lane ever grows by itself.

    ``text_policy`` answers "fetch this entity's text?" and, when the answer is no,
    says WHY in a word the caller chose. It runs INSIDE the per-entity loop, after
    the budget allowance, because the two refusals are different and both belong on
    the record. An adapter must never express either of them by returning ``None``
    from ``fetch_version``: that value means the source says the thing is GONE, and
    a lane that said "gone" when it meant "not this tier" would mark live pages
    deleted.
    """
    budget = budget or ReadBudget()
    result = PassResult(feed=feed)

    since = feedmod.stored_token(lane, feed)
    batch = adapter.read_changes(feed=feed, since=since, budget=budget)

    # Every entity this lane already KNOWS gets an id — including ones it is not
    # currently watching. This query deliberately does NOT filter on ``watching``:
    # a change to a page the operator unwatched still belongs to that page, and
    # orphaning it would throw away an attribution we have in hand. ``watching``
    # governs FETCHING, one layer down, where the bandwidth is actually spent.
    #
    # What it does NOT do is CREATE entities. A feed reports changes to things
    # nobody asked to follow, and materialising an entity for each would make the
    # watch list grow by itself — what this lane follows is the operator's choice.
    wanted = {c.external_id for c in batch.changes if c.external_id}
    entity_ids: dict[str, int] = {}
    if wanted:
        for row in lane.execute(
            select(VersionedEntity).where(VersionedEntity.external_id.in_(list(wanted)))
        ).scalars():
            entity_ids[row.external_id] = row.id

    # ADMISSION, before the batch is recorded. See the docstring for why the order
    # matters: a page admitted here has its admitting change linked to it, and one
    # admitted after ``record_batch`` would not.
    if admit is not None:
        for change in batch.changes:
            eid = change.external_id
            if not eid or eid in entity_ids:
                continue
            decision = admit(change)
            if decision is None:
                continue
            row = ensure_entity(
                lane,
                eid,
                title=decision.title,
                qid=decision.qid,
                language=decision.language,
                country_alpha3=decision.country_alpha3,
                pinned=decision.pinned,
                admitted_reason=decision.reason,
            )
            lane.flush()
            entity_ids[eid] = row.id
            result.entities_admitted += 1

    ingest = feedmod.record_batch(lane, batch, entity_ids=entity_ids)
    result.changes_recorded = ingest.recorded
    result.changes_duplicate = ingest.duplicates
    result.changes_unknown_kind = ingest.unknown_kind
    result.gap_recorded = ingest.gap_recorded
    lane.flush()

    # Which KNOWN entities actually changed in this batch, oldest change first so
    # a budget spends itself on the longest-waiting page rather than on whichever
    # the source happened to list first.
    touched: list[str] = []
    seen: set[str] = set()
    for change in sorted(
        (c for c in batch.changes if c.external_id in entity_ids),
        key=lambda c: (c.occurred_at is None, c.occurred_at),
    ):
        if change.external_id not in seen:
            seen.add(change.external_id or "")
            touched.append(change.external_id or "")

    allowance = budget.max_versions if budget.max_versions is not None else len(touched)
    for external_id in touched:
        if allowance <= 0:
            result.text_deferred += 1
            continue
        entity = lane.get(VersionedEntity, entity_ids[external_id])
        if entity is None or not entity.watching:
            continue
        if text_policy is not None:
            fetch, why = text_policy(entity)
            if not fetch:
                # WITHHELD, not deferred and not a gap. The reason is the caller's
                # own word and is counted under it; an empty reason is stored as
                # ``"unstated"`` rather than dropped, because a withheld text with
                # no reason anywhere is the shape this whole family of counters
                # exists to prevent.
                result.text_withheld += 1
                key = why or "unstated"
                result.text_withheld_reasons[key] = result.text_withheld_reasons.get(key, 0) + 1
                continue
        try:
            version = adapter.fetch_version(external_id)
        except Exception as exc:  # noqa: BLE001 - one entity must not end the pass
            result.errors.append(f"{external_id}: {type(exc).__name__}: {exc}")
            continue
        allowance -= 1
        if version is None:
            # The source says it is gone. Recorded as a change by the feed; the
            # entity keeps its history, because deleting it would destroy evidence.
            #
            # THE COUNT IS NOT THE MARK. ``deleted_reported`` lives for the length of
            # this pass and is then a number in a log; Q713 asks for the page to BE
            # marked, which only a column can do. Without it, a reader coming back
            # tomorrow sees an entity whose text simply stopped changing — the exact
            # shape of a page nobody edits, which is a different fact entirely.
            if entity.deleted_at is None:
                entity.deleted_at = _utcnow()
                # FLUSHED HERE, not left to the caller's commit. A pass that dies
                # after this point — a later entity raising, a kill switch, a crash —
                # would otherwise lose the one fact this iteration learned, and the
                # next pass would see a page that merely stopped changing.
                lane.flush()
            result.deleted_reported += 1
            continue
        if entity.deleted_at is not None:
            # The source answered with a version, so the page is back. The column
            # tracks the SOURCE's current state, not our history of it.
            entity.deleted_at = None
            lane.flush()
        outcome, article_id = store_version(lane, adapter, entity, version, corpus=corpus)
        if outcome == "baseline":
            result.baselines_captured += 1
        elif outcome == "revision":
            result.revisions_stored += 1
        else:
            result.revisions_unchanged += 1
        if article_id is not None:
            result.articles_indexed += 1
        _link_ingested(lane, feed, external_id, entity.id)

    return result


def _link_ingested(lane: Session, feed: str, external_id: str, entity_id: int) -> None:
    """Point this entity's un-ingested changes at the version they produced.

    Best effort and deliberately coarse: a pass that fetched the CURRENT text has
    covered every change up to it, so every un-ingested change for this entity is
    marked against the newest revision. Claiming a one-to-one mapping between a
    change row and a revision row would be a fabrication — a single fetch can
    subsume a dozen edits, and which of them the text reflects is not knowable from
    a current-text read.
    """
    newest = lane.execute(
        select(revmod.VersionedRevision)
        .where(revmod.VersionedRevision.entity_id == entity_id)
        .order_by(
            revmod.VersionedRevision.revised_at.desc().nullslast(),
            revmod.VersionedRevision.id.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    if newest is None:
        return
    for change in lane.execute(
        select(VersionedChange).where(
            VersionedChange.entity_id == entity_id,
            VersionedChange.feed == feed,
            VersionedChange.ingested_revision_id.is_(None),
        )
    ).scalars():
        change.ingested_revision_id = newest.id
