"""The change feed: a cursor, dedup, and gap detection that PUBLISHES rather than heals.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT A CHANGE FEED IS HERE. An adapter hands the substrate a ``ChangeBatch``: the
changes it was given, the cursor token the source says comes next, the token it
asked to resume FROM, and — when the source refused that token — the source's own
statement that it could not. The substrate dedups, records, and decides one thing:
whether this app can still claim to have seen every change.

THE TWO CLAIMS ARE DIFFERENT AND THEY GET DIFFERENT COLUMNS. ``token`` is "the last
place the feed handed us"; ``contiguous_through`` is "the point up to which we
believe we saw EVERYTHING". Conflating them is how a gap disappears: a cursor that
advances past a refused resume looks exactly like a cursor that advanced normally,
and every freshness reading downstream then describes a corpus with holes in it as
complete. ``contiguous_through`` advances ONLY through a batch that reported no gap.

WHAT THIS MODULE REFUSES TO INFER. A gap is recorded when something SAYS there is
one — the source refused a resume token, the operator's budget stopped the read, a
connection dropped, a fetch was refused. It is never inferred from a jump in
identifiers: ``change_ref`` is the source's own opaque id, sources skip ids for
their own reasons (a deleted revision, a suppressed edit, a sharded counter), and
a substrate that read a numeric hole as a coverage hole would manufacture gaps out
of someone else's bookkeeping. The mirror refusal matters as much: a batch that
arrives with no gap report does NOT prove there was no gap — it proves nobody said
so — which is why a cold start against a non-empty cursor is itself a gap.

DEDUP IS ON THE SOURCE'S OWN ID. ``UNIQUE (feed, change_ref)``. A reconnect that
replays is then free, and a cursor that goes BACKWARDS costs nothing but a few
ignored rows — which is the property that lets a resume be optimistic.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.versioned.lanes import CHUNK_SIZE
from src.versioned.models import VersionedChange, VersionedCursor, VersionedGap

_LOG = logging.getLogger("versioned.feed")

#: Why a stretch of a feed was not seen. Closed, because a reader acts differently
#: on each: ``retention`` is the source's limit, ``budget`` is the operator's own
#: choice, ``disconnect`` is the network, ``refused`` is a gate (airplane mode, a
#: transport that was unavailable). Merging them into "missing" would hide which.
GapReason = Literal["retention", "disconnect", "budget", "refused"]

#: A change's shape. Anything a source reports that is not one of these is stored
#: VERBATIM and reported as unknown — mapping it onto the nearest member would
#: invent a fact about someone else's data.
KNOWN_CHANGE_KINDS: frozenset[str] = frozenset({"edit", "create", "delete", "move"})


@dataclass(frozen=True, slots=True)
class FeedChange:
    """One change as the source reported it. The adapter's job is to build these."""

    change_ref: str
    change_kind: str
    #: The adapter's ``external_id`` for the entity, or ``None`` when the feed
    #: reports a change to something we do not track. Those are still RECORDED:
    #: a lane that only counts what it already follows cannot say how much it is
    #: not following.
    external_id: str | None = None
    occurred_at: datetime | None = None
    cursor_token: str | None = None
    byte_delta: int | None = None


@dataclass(frozen=True, slots=True)
class GapReport:
    """The source's (or the caller's) own statement that a stretch was not seen."""

    reason: GapReason
    from_token: str | None = None
    to_token: str | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChangeBatch:
    """What an adapter returns from one read of a feed."""

    feed: str
    changes: Sequence[FeedChange] = field(default_factory=tuple)
    #: The token the source says comes next. ``None`` means the source offered no
    #: resume point, which is a different thing from "the same token as before".
    next_token: str | None = None
    #: The token this read ASKED to resume from. ``None`` for a deliberate cold
    #: start. Compared against the stored cursor by ``detect_gap``.
    resumed_from: str | None = None
    #: Set when the source (or the caller) says a stretch was skipped.
    gap: GapReport | None = None


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What ``record_batch`` did. Counts only — no verdict about the batch."""

    recorded: int
    duplicates: int
    unknown_kind: int
    gap_recorded: bool
    contiguous_advanced: bool


def detect_gap(
    *,
    stored_token: str | None,
    batch: ChangeBatch,
) -> GapReport | None:
    """Decide whether this batch leaves a hole, WITHOUT inventing one.

    Pure, so the decision can be tested at every combination rather than inferred
    from a store's behaviour. Three ways a gap is real, in order:

    1. **The batch says so.** An adapter that was refused its resume token, or a
       caller that stopped on a budget, hands us a ``GapReport``. We believe it.
    2. **A cold start against a live cursor.** ``resumed_from is None`` while a
       token is stored means this read began again from the source's HEAD while we
       had a position: everything between the two is unseen, and nothing else in
       the system will ever notice. The gap's ends are exactly those two tokens.
    3. **A resume from somewhere other than where we were.** ``resumed_from`` not
       equal to the stored token means the read started at a point we did not
       leave off at. Whether it is ahead or behind is not knowable here — the
       token is opaque — so the gap is recorded with both ends named and no claim
       about direction.

    And the refusals, which are the reason this function exists at all: an empty
    batch is NOT a gap (a quiet feed is the common case and the honest reading),
    a duplicate-only batch is NOT a gap (a replay after a reconnect), and a jump
    in ``change_ref`` is NOT a gap (the source's ids are its own business).
    """
    if batch.gap is not None:
        return batch.gap
    if stored_token is None:
        # Nothing was stored, so nothing was skipped. A first read cannot have a
        # hole behind it, and reporting one would put every fresh install's lane
        # permanently in a state it can never leave.
        return None
    if batch.resumed_from is None:
        return GapReport(
            reason="disconnect",
            from_token=stored_token,
            to_token=batch.next_token,
        )
    if batch.resumed_from != stored_token:
        return GapReport(
            reason="disconnect",
            from_token=stored_token,
            to_token=batch.resumed_from,
        )
    return None


def cursor_row(session: Session, feed: str) -> VersionedCursor | None:
    """The stored cursor for ``feed``, or ``None`` when the feed has never run."""
    return session.execute(
        select(VersionedCursor).where(VersionedCursor.feed == feed)
    ).scalar_one_or_none()


def stored_token(session: Session, feed: str) -> str | None:
    """Just the token. ``None`` when the feed has never run OR carries no token —
    two states this helper deliberately merges, because ``detect_gap`` treats them
    the same and a caller that needed them apart should read the row."""
    row = cursor_row(session, feed)
    return row.token if row is not None else None


def _existing_refs(session: Session, feed: str, refs: Iterable[str]) -> set[str]:
    """Which of ``refs`` this feed already holds. One query per ``CHUNK_SIZE`` refs.

    Chunked for the reason measured beside ``CHUNK_SIZE`` in ``lanes.py``: this machine's
    ``sqlite3`` (3.45.1) and ``sqlcipher3`` (3.51.1) both accept 250,000 host
    parameters, NOT the 999 that circulates as SQLite's limit — but that ceiling is a
    per-build setting, and this app ships to whatever SQLCipher an operator's platform
    provides. A query that works here and raises ``too many SQL variables`` on a
    user's build fails only in the field, only on large corpora.
    """
    found: set[str] = set()
    batch: list[str] = []
    for ref in refs:
        batch.append(ref)
        if len(batch) >= CHUNK_SIZE:
            found.update(
                session.execute(
                    select(VersionedChange.change_ref).where(
                        VersionedChange.feed == feed,
                        VersionedChange.change_ref.in_(batch),
                    )
                ).scalars()
            )
            batch = []
    if batch:
        found.update(
            session.execute(
                select(VersionedChange.change_ref).where(
                    VersionedChange.feed == feed,
                    VersionedChange.change_ref.in_(batch),
                )
            ).scalars()
        )
    return found


def record_batch(
    session: Session,
    batch: ChangeBatch,
    *,
    entity_ids: dict[str, int] | None = None,
) -> IngestResult:
    """Record one batch: dedup, publish any gap, then advance the cursor.

    ORDER IS LOAD-BEARING. The gap is written BEFORE the cursor advances, in the
    same transaction, so a crash between the two can only ever leave a gap with a
    stale cursor — which re-reads a stretch already covered. The other order can
    leave an advanced cursor with no gap, which is a permanent, silent hole.

    ``entity_ids`` maps ``external_id`` to the lane's own entity row id. The caller
    supplies it because the substrate does not create entities from a feed: a feed
    reports changes to things nobody asked to follow, and materialising them would
    make the watch list grow by itself.
    """
    ids = entity_ids or {}
    changes = list(batch.changes)
    refs = [c.change_ref for c in changes]
    seen = _existing_refs(session, batch.feed, refs)

    recorded = duplicates = unknown_kind = 0
    # Dedup WITHIN the batch too: a source that repeats a ref inside one delivery
    # would otherwise hit the unique constraint and roll the whole batch back.
    in_batch: set[str] = set()
    for change in changes:
        if change.change_ref in seen or change.change_ref in in_batch:
            duplicates += 1
            continue
        in_batch.add(change.change_ref)
        if change.change_kind not in KNOWN_CHANGE_KINDS:
            unknown_kind += 1
        session.add(
            VersionedChange(
                entity_id=ids.get(change.external_id or ""),
                external_id=change.external_id,
                change_ref=change.change_ref,
                feed=batch.feed,
                change_kind=change.change_kind,
                occurred_at=change.occurred_at,
                cursor_token=change.cursor_token or batch.next_token,
                byte_delta=change.byte_delta,
            )
        )
        recorded += 1

    row = cursor_row(session, batch.feed)
    gap = detect_gap(stored_token=row.token if row else None, batch=batch)
    if gap is not None:
        session.add(
            VersionedGap(
                feed=batch.feed,
                from_token=gap.from_token,
                to_token=gap.to_token,
                from_time=gap.from_time,
                to_time=gap.to_time,
                reason=gap.reason,
            )
        )
        _LOG.info(
            "versioned feed %s: recorded a %s gap (%s -> %s)",
            batch.feed,
            gap.reason,
            gap.from_token,
            gap.to_token,
        )

    # The newest change we were handed bounds what "contiguous" can mean. An empty
    # batch advances nothing: a quiet feed tells us nothing new about coverage, and
    # stamping the clock would claim we had seen up to now when nobody said so.
    newest = max(
        (c.occurred_at for c in changes if c.occurred_at is not None),
        default=None,
    )
    advanced = False
    if row is None:
        row = VersionedCursor(feed=batch.feed)
        session.add(row)
    row.token = batch.next_token
    row.updated_at = _now()
    # TWO separate refusals, written as one condition because the nesting that would
    # let each carry its own line is what SIM102 forbids:
    #   (1) a batch that straddles a GAP must not advance contiguity at all — the hole
    #       is the whole reason the claim cannot be extended across it;
    #   (2) contiguity moves only FORWARD — a backfill or an out-of-order delivery must
    #       never REDUCE a claim already earned.
    if (
        gap is None
        and newest is not None
        and (row.contiguous_through is None or newest > row.contiguous_through)
    ):
        row.contiguous_through = newest
        advanced = True

    # FLUSH BEFORE RETURNING. The lane session factory sets ``autoflush=False``
    # (matching the corpus's), so without this every row written above is invisible
    # to a query on the SAME session until somebody else happens to flush — and
    # ``cursor_row`` would answer ``None`` immediately after the cursor was created.
    # Relying on each caller to flush is an implicit contract, and the failure is
    # silent in the direction that reads as "nothing was recorded". A flush is not a
    # commit, so the "gap before cursor, both or neither" ordering above is
    # unaffected: the transaction is still the caller's to finish.
    session.flush()

    return IngestResult(
        recorded=recorded,
        duplicates=duplicates,
        unknown_kind=unknown_kind,
        gap_recorded=gap is not None,
        contiguous_advanced=advanced,
    )


def open_gaps(session: Session, feed: str | None = None) -> list[VersionedGap]:
    """Gaps nobody has closed, newest first. The Living sources view's own input."""
    stmt = select(VersionedGap).where(VersionedGap.closed_at.is_(None))
    if feed is not None:
        stmt = stmt.where(VersionedGap.feed == feed)
    return list(session.execute(stmt.order_by(VersionedGap.detected_at.desc())).scalars())


def close_gap(session: Session, gap_id: int) -> bool:
    """Mark a gap filled by another route. Returns False when it was already closed.

    Only a caller that actually re-read the stretch may call this. There is no
    path here that closes a gap because time passed or because later changes
    arrived — a gap that ages out silently is the whole failure this table exists
    to prevent.
    """
    row = session.get(VersionedGap, gap_id)
    if row is None or row.closed_at is not None:
        return False
    row.closed_at = _now()
    return True


def _now() -> datetime:
    from src.versioned.models import _utcnow

    return _utcnow()
