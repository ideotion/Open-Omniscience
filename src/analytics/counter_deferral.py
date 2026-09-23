"""The durable marker that keeps a deferred re-index HONEST (ruling R22).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. R22 lets an exclusive drain stop maintaining the denormalised keyword
counters per article and reconcile them ONCE at the end -- "disclosed as estimated
meanwhile". The disclosure is not a nicety; it is the whole reason the ruling is
allowed to skip the maintenance, and without this module it would silently not happen.

THE HOLE IT CLOSES, EXACTLY. :func:`src.analytics.store.counter_envelope` decides
`exact` vs `estimated` from ``Keyword.last_reconciled_at``. A deferred drain never
touches that column -- it just stops updating ``mention_count``/``article_count``. So a
corpus reconciled an hour before the drain started carries FRESH watermarks on keywords
whose counters are now drifting, and the envelope would keep reporting `exact` over
them. That is precisely what R22 forbids: "nothing may report a reconciled figure it has
not reconciled."

WHY IT IS DURABLE AND NOT A PROCESS FLAG. The failure this has to survive is a crash in
the middle of a drain -- the case where the counters are LEAST correct and no code is
left running to know it. An in-process flag dies with the process and the next boot
reports `exact` over drifted counters with nothing anywhere recording that it should
not. So the marker lives in ``derived_meta``, inside the encrypted store, committed
before the first unmaintained article is.

ORDERING IS THE CORRECTNESS CONDITION: open-and-commit BEFORE the first article is
indexed without counter maintenance, never after. Opened-but-not-needed costs one
honest `estimated` until the next complete reconcile; needed-but-not-opened is a false
`exact`, which is the failure mode this exists to prevent. The asymmetry is the whole
design, and :func:`open_deferral` commits for exactly that reason.

CLOSING IS EARNED, NOT ASSUMED. Only a COMPLETE reconcile sweep may close the marker. A
budgeted sweep that stops early has verified some keywords and not others, which is the
state ``reconcile_keyword_counters`` already documents as "half-reconciled counters can
never masquerade as exact" -- so a partial pass leaves the marker open and the envelope
keeps saying `estimated`. Failing to close is safe (an understated freshness claim);
closing early is not.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

# The ``derived_meta`` key. Its VALUE is the ISO timestamp the deferral opened at, so a
# reader can say how long the counters have been unmaintained rather than only that they
# are -- an "estimated since 14:02" is a fact, an "estimated" alone is a shrug.
COUNTER_DEFERRAL_KEY = "counter_deferral_open"


def open_deferral(session: Session, *, reason: str = "", now=None) -> str:
    """Mark the counters as deferred and COMMIT, returning the stored timestamp.

    Committed here deliberately: the marker must be durable before the first article is
    committed without counter maintenance, or a crash between the two leaves drifted
    counters that nothing knows about. This is the one ordering rule of the module.

    Unlike the corpus-epoch bump, this does NOT swallow its failures. A bump that fails
    costs an extra cache rebuild; a marker that fails to open costs a false `exact`, so
    the caller must learn about it and decline to defer.
    """
    from src.database.models import DerivedMeta
    from src.database.writer import write_lock

    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    with write_lock():
        row = session.get(DerivedMeta, COUNTER_DEFERRAL_KEY)
        if row is None:
            session.add(DerivedMeta(key=COUNTER_DEFERRAL_KEY, value=stamp))
        else:
            # An already-open deferral keeps its ORIGINAL timestamp: the honest answer to
            # "since when have these been unmaintained" is the earlier drain's start, not
            # this one's. Re-opening would quietly shorten the disclosed window.
            stamp = row.value
        session.commit()
    if reason:
        _LOG.info("counter deferral open since %s (%s)", stamp, reason)
    return stamp


def deferral_open_since(session: Session) -> str | None:
    """The ISO timestamp the deferral opened at, or ``None`` when counters are maintained.

    Degrades toward the SAFE direction on an unreadable store: an exception here returns
    the marker as OPEN, because a read that failed cannot support an `exact` claim. This
    is the opposite of :func:`src.analytics.corpus_epoch.get_corpus_epoch`, which degrades
    to "never bumped" -- there the safe direction is more work, here it is less certainty.
    """
    from src.database.models import DerivedMeta

    try:
        row = session.get(DerivedMeta, COUNTER_DEFERRAL_KEY)
    except Exception:  # noqa: BLE001 - an unreadable marker cannot support `exact`
        _LOG.warning("counter deferral marker unreadable; disclosing as deferred", exc_info=True)
        return "unknown"
    return row.value if row is not None else None


def is_deferral_open(session: Session) -> bool:
    return deferral_open_since(session) is not None


def close_deferral(session: Session) -> bool:
    """Clear the marker. Returns True when a marker was actually removed.

    Call this ONLY after a reconcile that verified every keyword (a sweep reporting
    ``complete: true``). A partial sweep must leave it open.
    """
    from src.database.models import DerivedMeta
    from src.database.writer import write_lock

    with write_lock():
        row = session.get(DerivedMeta, COUNTER_DEFERRAL_KEY)
        if row is None:
            return False
        session.delete(row)
        session.commit()
    return True
