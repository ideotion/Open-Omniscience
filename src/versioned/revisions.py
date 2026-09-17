"""The immutable baseline, the revision store, the diff, and the point-in-time read.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE BASELINE IS WRITTEN ONCE. ``capture_baseline`` refuses a second one by name
rather than updating the row. A baseline that can be overwritten is a rewritten
past: every diff in the lane is ultimately anchored on it, and "what has changed
since we started watching" stops meaning anything the moment the start moves.

THE DIFF IS AGAINST THE PREVIOUS **INGESTED** VERSION. Not against the source's own
predecessor. If a lane under a budget holds revisions 100 and 140, the honest
statement is "between the two versions this corpus holds, these lines changed" —
which is what a reader can check against the two texts in front of them.
``diff_from_ref`` names that version, so the claim is falsifiable; a diff against
revision 139, which this app never saw, would describe an edit it cannot show.

THE DIFF IS BOUNDED, AND THE BOUND IS PUBLISHED. ``difflib.SequenceMatcher`` is
quadratic in the worst case, and a lane ingests other people's documents — the
recorded 412 KB article that cost a field re-index 138 seconds is the same shape of
hazard one module over. Past ``_MAX_DIFF_LINES`` or ``_MAX_DIFF_CHARS`` the unified
diff is NOT computed and ``diff_method`` says ``too-large``; ``diff_added`` and
``diff_removed`` are then NULL rather than filled from a cheaper comparison, because
a line count taken a different way is a different measurement under the same field
name. ``diff_byte_delta`` is exact in every case — it is subtraction.

THE POINT-IN-TIME READ ANSWERS WITH WHAT WE HELD, AND SAYS SO. ``version_at``
returns the newest version whose ``revised_at`` is at or before the asked-for
instant, out of the versions this lane HOLDS. It is not a claim about what the
source said at that instant — a budget may have skipped the version in force — so
its result carries the gap context a caller needs to render that honestly.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.versioned.models import (
    VersionedBaseline,
    VersionedEntity,
    VersionedRevision,
    _utcnow,
)

_LOG = logging.getLogger("versioned.revisions")

#: Above either bound the unified diff is skipped. The bound exists because
#: ``SequenceMatcher`` is quadratic in the worst case and a lane ingests other
#: people's documents; it is set well above anything an ordinary article or statute
#: reaches (those are tens of KB and hundreds of lines) so that skipping is the rare
#: path rather than the common one. NO THIRD-PARTY SIZE LIMIT IS CITED HERE ON
#: PURPOSE: a figure about what MediaWiki will serve is a FROM-MEMORY claim this
#: session cannot verify (the Wikimedia hosts are egress-blocked in this sandbox),
#: and an unverified number written into a justification is how a bound acquires a
#: reason nobody re-checks. The quadratic hazard alone justifies the bound.
_MAX_DIFF_LINES = 40_000
_MAX_DIFF_CHARS = 4 * 1024 * 1024

#: The literal tokens ``VersionedRevision.diff_method`` may carry.
DIFF_UNIFIED = "unified"
DIFF_NO_PREVIOUS = "no-previous-text"
DIFF_TOO_LARGE = "too-large"


class BaselineExistsError(RuntimeError):
    """A second baseline was offered for an entity that already has one."""


@dataclass(frozen=True, slots=True)
class DiffResult:
    """What ``compute_diff`` found. ``added``/``removed`` are ``None`` when not computed."""

    method: str
    added: int | None
    removed: int | None
    byte_delta: int
    text: str | None


def content_hash(text: str) -> str:
    """SHA-256 over the UTF-8 bytes. The identity of a version's CONTENT.

    Used to tell "the source served the same text again" from "the source changed
    it", which a revision id alone cannot: a null edit and a rewrite both produce a
    new revid.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_diff(previous: str | None, current: str) -> DiffResult:
    """Diff ``current`` against ``previous``, or say honestly why it was not diffed.

    Pure — no session, no I/O — so every branch is testable directly and a mutation
    of the bound reddens a named test rather than changing a database.
    """
    new_bytes = len(current.encode("utf-8"))
    if previous is None:
        # The previous version's text is not held (a lane that keeps metadata for
        # every change and text for some). The byte delta cannot be computed
        # against a text we do not have, so it is the whole of the new text and the
        # method says why.
        return DiffResult(
            method=DIFF_NO_PREVIOUS, added=None, removed=None, byte_delta=new_bytes, text=None
        )

    old_bytes = len(previous.encode("utf-8"))
    byte_delta = new_bytes - old_bytes

    old_lines = previous.splitlines(keepends=True)
    new_lines = current.splitlines(keepends=True)
    if (
        len(old_lines) + len(new_lines) > _MAX_DIFF_LINES
        or len(previous) + len(current) > _MAX_DIFF_CHARS
    ):
        return DiffResult(
            method=DIFF_TOO_LARGE, added=None, removed=None, byte_delta=byte_delta, text=None
        )

    lines = list(
        difflib.unified_diff(old_lines, new_lines, fromfile="previous", tofile="current", n=3)
    )
    added = removed = 0
    for ln in lines:
        # The +++/--- file headers start with three markers, so they are excluded by
        # checking the two-character prefix rather than the one-character one. Getting
        # this wrong inflates every diff by exactly one add and one remove, which is
        # small enough to look like rounding and never be questioned.
        if ln.startswith("+") and not ln.startswith("+++"):
            added += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            removed += 1
    return DiffResult(
        method=DIFF_UNIFIED,
        added=added,
        removed=removed,
        byte_delta=byte_delta,
        text="".join(lines) if lines else "",
    )


def baseline_for(session: Session, entity_id: int) -> VersionedBaseline | None:
    """This entity's baseline, or ``None`` when it has never been captured."""
    return session.execute(
        select(VersionedBaseline).where(VersionedBaseline.entity_id == entity_id)
    ).scalar_one_or_none()


def capture_baseline(
    session: Session,
    entity: VersionedEntity,
    *,
    revision_ref: str,
    text: str,
    revised_at: datetime | None = None,
) -> VersionedBaseline:
    """Write the one immutable baseline for ``entity``. Refuses a second.

    The refusal is the feature. A caller that believes it needs to replace a
    baseline wants a REVISION — that is what ``record_revision`` is for — and the
    two are not interchangeable: one is the anchor, the other is a change against it.
    """
    existing = baseline_for(session, entity.id)
    if existing is not None:
        raise BaselineExistsError(
            f"{entity.external_id!r} already has a baseline at revision "
            f"{existing.revision_ref!r}; a later version is a revision, not a baseline"
        )
    row = VersionedBaseline(
        entity_id=entity.id,
        revision_ref=revision_ref,
        revised_at=revised_at,
        content_hash=content_hash(text),
        content=text,
        byte_size=len(text.encode("utf-8")),
    )
    session.add(row)
    session.flush()
    return row


def previous_ingested(session: Session, entity_id: int) -> tuple[str, str | None] | None:
    """The version a new revision's diff must be taken against.

    The newest REVISION this lane holds, falling back to the baseline. Returns
    ``(revision_ref, text)`` where ``text`` may be ``None`` — a lane that keeps a
    revision's metadata without its text is a real and intended state, and the
    caller must be able to tell it from "there is no previous version at all"
    (which is ``None``, the whole tuple).

    Ordered by ``revised_at`` with ``id`` as the tie-break, never by ``id`` alone:
    ids are insertion order, and a backfill inserts older versions later.
    """
    row = session.execute(
        select(VersionedRevision)
        .where(VersionedRevision.entity_id == entity_id)
        .order_by(VersionedRevision.revised_at.desc().nullslast(), VersionedRevision.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is not None:
        return (row.revision_ref, row.content)
    base = baseline_for(session, entity_id)
    if base is not None:
        return (base.revision_ref, base.content)
    return None


def record_revision(
    session: Session,
    entity: VersionedEntity,
    *,
    revision_ref: str,
    text: str,
    revised_at: datetime | None = None,
    article_id: int | None = None,
) -> tuple[VersionedRevision, bool]:
    """Store one ingested version with its diff. Returns ``(row, created)``.

    Idempotent on ``(entity_id, revision_ref)``: re-offering a version this lane
    already holds returns the existing row and ``created=False`` rather than
    raising, because a retry after a partial pass is the normal case and a unique
    violation there would roll back the whole batch.
    """
    existing = session.execute(
        select(VersionedRevision).where(
            VersionedRevision.entity_id == entity.id,
            VersionedRevision.revision_ref == revision_ref,
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Fill an article link learned after the fact; never overwrite one.
        if article_id is not None and existing.article_id is None:
            existing.article_id = article_id
        return (existing, False)

    prev = previous_ingested(session, entity.id)
    prev_ref, prev_text = prev if prev is not None else (None, None)
    diff = compute_diff(prev_text, text)

    row = VersionedRevision(
        entity_id=entity.id,
        revision_ref=revision_ref,
        observed_at=_utcnow(),
        revised_at=revised_at,
        content_hash=content_hash(text),
        content=text,
        byte_size=len(text.encode("utf-8")),
        diff_from_ref=prev_ref,
        diff_added=diff.added,
        diff_removed=diff.removed,
        diff_byte_delta=diff.byte_delta if prev is not None else None,
        diff_text=diff.text,
        diff_method=diff.method if prev is not None else None,
        article_id=article_id,
    )
    session.add(row)
    session.flush()
    entity.last_checked_at = _utcnow()
    return (row, True)


@dataclass(frozen=True, slots=True)
class PointInTime:
    """A point-in-time answer, WITH what it cannot claim.

    ``held`` is the version this lane holds that was in force at the instant asked
    for. ``is_baseline`` says whether that version is the anchor rather than a
    recorded change. ``newer_unheld`` counts the changes the feed REPORTED between
    that version and the instant, which this lane did not ingest — the number that
    turns "here is the text" into "here is the text we have, and N changes we were
    told about but did not fetch happened in between".
    """

    held: VersionedRevision | VersionedBaseline | None
    is_baseline: bool
    newer_unheld: int


def version_at(session: Session, entity_id: int, when: datetime) -> PointInTime:
    """What this lane held as being in force at ``when``.

    Returns the newest held version at or before ``when``. A version with no
    ``revised_at`` is EXCLUDED rather than treated as very old: an unknown date is
    not a date, and admitting it would let an undated version answer for any
    instant at all.
    """
    from src.versioned.models import VersionedChange

    row = session.execute(
        select(VersionedRevision)
        .where(
            VersionedRevision.entity_id == entity_id,
            VersionedRevision.revised_at.is_not(None),
            VersionedRevision.revised_at <= when,
        )
        .order_by(VersionedRevision.revised_at.desc(), VersionedRevision.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    held: VersionedRevision | VersionedBaseline | None = row
    is_baseline = False
    if row is None:
        base = baseline_for(session, entity_id)
        if base is not None and base.revised_at is not None and base.revised_at <= when:
            held, is_baseline = base, True
        elif base is not None and base.revised_at is None:
            # A baseline with no source date cannot answer a point-in-time question
            # either. Saying so beats handing back a text with an invented claim.
            held, is_baseline = None, False

    since = getattr(held, "revised_at", None)
    unheld_q = select(VersionedChange).where(
        VersionedChange.entity_id == entity_id,
        VersionedChange.ingested_revision_id.is_(None),
        VersionedChange.occurred_at.is_not(None),
        VersionedChange.occurred_at <= when,
    )
    if since is not None:
        unheld_q = unheld_q.where(VersionedChange.occurred_at > since)
    newer_unheld = len(list(session.execute(unheld_q).scalars()))

    return PointInTime(held=held, is_baseline=is_baseline, newer_unheld=newer_unheld)


def timeline(
    session: Session, entity_id: int, *, limit: int = 50, offset: int = 0
) -> tuple[list[VersionedRevision], int]:
    """One entity's revisions, newest first, WITH the exact total.

    The total is counted, not inferred from the page: a displayed figure is never
    secretly a cap (the anti-capping rule), and "50" beside a list of 50 is exactly
    the shape that reads as a measurement and is not one.
    """
    from sqlalchemy import func

    total = int(
        session.execute(
            select(func.count())
            .select_from(VersionedRevision)
            .where(VersionedRevision.entity_id == entity_id)
        ).scalar_one()
    )
    rows = list(
        session.execute(
            select(VersionedRevision)
            .where(VersionedRevision.entity_id == entity_id)
            .order_by(
                VersionedRevision.revised_at.desc().nullslast(),
                VersionedRevision.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return (rows, total)
