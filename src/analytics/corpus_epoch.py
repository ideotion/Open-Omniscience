"""The canonical CORPUS EPOCH -- the D3 double-count guard's source of truth.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (docs/design/SCALING_DERIVED_LAYER_1000X.md, D3). The disposable
columnar rollup (``src/analytics/columnar.py``) keeps a per-day keyword rollup fresh by
merging only the NEW mention tail (``id > last_mention_id``) on most passes -- fast,
because it never re-scans the multi-GB mention table. That incremental merge is correct
ONLY for APPEND. But ``index_article`` is delete-then-reinsert: every re-index of an
existing article DELETES its mentions and RE-INSERTS them with fresh higher ids, and
``prune_orphan_keywords`` DELETES rows. An id-watermark merge would then keep the OLD
contribution in the rollup AND re-add the reinserted higher-id rows = a fabricated
(doubled) number.

THE GUARD. Those non-append mutators bump a monotonic *corpus epoch*; a rollup records
the epoch it was BUILT at, and :func:`src.analytics.columnar.refresh_keyword_daily`
FULL-rebuilds (never incrementally merges) whenever the current epoch differs from the
built epoch. Normal new-article ingest does NOT bump the epoch (else every scrape pass
would full-rebuild).

This module is the canonical side: it stores the epoch in the ``derived_meta`` table and
the mutators call :func:`bump_corpus_epoch`. Over-bumping is HARMLESS -- it can only
force an extra (correct) full rebuild, never a wrong number -- so the helpers err toward
bumping and never raise into the mutator they ride.

Not an analytic and never a score: a coordination watermark for a disposable cache.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

# The one key held in ``derived_meta`` today (the table is a general key->value store).
CORPUS_EPOCH_KEY = "corpus_epoch"


def get_corpus_epoch(session: Session) -> int:
    """The current corpus epoch (``0`` if never bumped / unparseable).

    A read; safe to call from any read path (e.g. a rollup deciding full-vs-incremental).
    Degrades to ``0`` rather than raising -- an unreadable watermark just means the rollup
    treats the store as never-bumped and full-rebuilds, which is the safe direction.
    """
    from src.database.models import DerivedMeta

    try:
        row = session.get(DerivedMeta, CORPUS_EPOCH_KEY)
    except Exception:  # noqa: BLE001 - a coordination read must never break its caller
        return 0
    if row is None:
        return 0
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return 0


def bump_corpus_epoch(session: Session, *, reason: str = "") -> int:
    """Increment the corpus epoch and return the NEW value (starts at 1).

    Called by exactly the non-append mutators (re-index / prune / restore-merge) so the
    disposable rollup full-rebuilds instead of merging across a delete-then-reinsert (the
    double-count trap). Takes the single-writer gate (reentrant, so it composes with a
    mutator that already holds it) and commits its own tiny change.

    BEST-EFFORT BY DESIGN: a failure to bump must NEVER break the mutator it rides. A
    missed bump degrades only to a rollup that lags one mutation -- the next real bump (or
    the columnar store's own compatibility rebuild) corrects it -- which is strictly safer
    than aborting a re-index/prune/restore for a cache-coordination write. So it swallows
    and logs, returning the (unchanged) current epoch on failure.

    Idempotency note: this is deliberately NOT idempotent -- each call increments -- so a
    caller should invoke it ONCE per logical mutation (e.g. once per re-index batch),
    never in a per-row loop. Over-bumping is harmless but wasteful.
    """
    from src.database.models import DerivedMeta
    from src.database.writer import write_lock

    try:
        with write_lock():
            row = session.get(DerivedMeta, CORPUS_EPOCH_KEY)
            if row is None:
                new_val = 1
                session.add(
                    DerivedMeta(
                        key=CORPUS_EPOCH_KEY,
                        value=str(new_val),
                        updated_at=datetime.now(UTC),
                    )
                )
            else:
                try:
                    new_val = int(row.value) + 1
                except (TypeError, ValueError):
                    new_val = 1  # unparseable -> restart the counter (still a change)
                row.value = str(new_val)
                row.updated_at = datetime.now(UTC)
            session.commit()
        _LOG.info("corpus epoch -> %d (%s)", new_val, reason or "mutation")
        return new_val
    except Exception:  # noqa: BLE001 - a coordination bump must never break its mutator
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        _LOG.warning(
            "corpus-epoch bump failed (%s); the rollup may lag until the next bump",
            reason or "mutation",
            exc_info=True,
        )
        return get_corpus_epoch(session)
