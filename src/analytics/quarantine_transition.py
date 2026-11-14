"""R101 on an upgraded store: the one-time boot step that brings a store written before 0.5.1 into line.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Kept out of :mod:`src.analytics.quarantine_scope`, which an indexing pass loads: this module imports the store, and a
module a pass loads must not import the file the engine identity narrows (``tests/test_engine_identity_narrowed.py``).
"""

from __future__ import annotations

from typing import Any

from src.analytics.quarantine_scope import not_quarantined, quarantined_ids_select

#: ``derived_meta`` key written once the counters of a store follow R101. Before 0.5.1 every quarantined article
#: still counted in ``Keyword.mention_count`` / ``article_count`` (``index_article`` and the reconcile both
#: counted it), and the rollup and the day counts held its rows.
R101_TRANSITION_KEY = "r101_quarantine_counters"


#: Keywords recomputed per statement: the IN list of one grouped read, and the rows of one executemany.
_KEYWORD_CHUNK = 500


def _recompute_counters_of_quarantined_keywords(session: Any) -> dict:
    """Set the counters of every keyword a quarantined article mentions to their R101 truth: the sum and the
    article count over the mentions of articles that are NOT quarantined (``backfill_keyword_counters``' own
    definition, for just these keywords).

    A recompute, not a subtraction, on purpose: it gives the same answer however many times it runs and whatever
    landed in between (a budgeted reconcile, or a new stamp that already shifted its article out). A one-off
    subtraction would take a quarantined article out twice after a failed attempt the app ran on from. Core
    statements only: no keyword is loaded as an ORM object, so a large store costs a grouped read and an
    executemany per chunk, not one object per keyword held for the whole transaction."""
    from sqlalchemy import func, select, update

    from src.database.derived_views import KeywordMentionRead
    from src.database.models import Keyword

    kids = [
        int(k)
        for (k,) in session.execute(
            select(KeywordMentionRead.keyword_id)
            .where(KeywordMentionRead.article_id.in_(quarantined_ids_select()))
            .distinct()
        )
    ]
    kids.sort()
    for i in range(0, len(kids), _KEYWORD_CHUNK):
        chunk = kids[i : i + _KEYWORD_CHUNK]
        truth = dict.fromkeys(chunk, (0, 0))
        for kid, men, arts in session.execute(
            select(
                KeywordMentionRead.keyword_id,
                func.sum(KeywordMentionRead.count),
                func.count(func.distinct(KeywordMentionRead.article_id)),
            )
            .where(KeywordMentionRead.keyword_id.in_(chunk), not_quarantined(KeywordMentionRead.article_id))
            .group_by(KeywordMentionRead.keyword_id)
        ):
            truth[int(kid)] = (int(men or 0), int(arts or 0))
        # An ORM bulk UPDATE by primary key: one executemany, no object loaded.
        session.execute(
            update(Keyword), [{"id": k, "mention_count": m, "article_count": a} for k, (m, a) in truth.items()]
        )
    return {"keywords": len(kids)}


#: ``derived_meta`` key present while the recompute is owed. Its value says whether :func:`prepare_r101_transition`
#: opened the counter-deferral marker (``opened``) or found it already open (``kept``), so the recompute closes
#: only a deferral it opened.
R101_PENDING_KEY = "r101_quarantine_counters_pending"


def _session(engine: Any):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, future=True)()


def prepare_r101_transition(engine: Any) -> dict:
    """The fast half, inside ``init_db`` (R101 on a store written before 0.5.1).

    Without it the stores disagree after an upgrade: the live readers leave quarantined articles out at once,
    while the counters, the persisted rollup and the day counts keep them, so a figure would depend on which store
    served it, which R101 forbids. When the store holds a quarantined article and the recompute is still owed:

    1. bump the corpus epoch, so the rollup and the day counts rebuild and the live path serves until they do;
    2. open the counter-deferral marker (``counter_deferral.py``) if nothing else holds it open, so every
       counter-backed figure says ``estimated`` until :func:`heal_r101_transition` has recomputed them. That
       recompute runs in the start-up upkeep (``src/api/main.py`` ``_run_startup_upkeep``), after the store is
       queryable on the unlock path, not here: on a large store it takes tens of seconds and must not hold the store
       closed.

    A store with no quarantined article is already in line and only gets the done marker. One ``derived_meta`` read
    on every later start. Best-effort: never stops the store from opening."""
    import logging
    from datetime import UTC, datetime

    from src.monitoring.secret_scrub import log_failure

    log = logging.getLogger(__name__)
    if engine.url.get_backend_name() != "sqlite":
        return {"skipped": "not sqlite"}
    from src.database.models import DerivedMeta

    s = _session(engine)
    try:
        if s.get(DerivedMeta, R101_TRANSITION_KEY) is not None:
            return {"skipped": "done"}
        if s.execute(quarantined_ids_select().limit(1)).first() is None:
            s.add(DerivedMeta(key=R101_TRANSITION_KEY, value=datetime.now(UTC).isoformat(timespec="seconds")))
            s.commit()
            return {"owed": False}
        from src.analytics.corpus_epoch import bump_corpus_epoch
        from src.analytics.counter_deferral import is_deferral_open, open_deferral

        bump_corpus_epoch(s, reason="r101-transition", strict=True)
        if s.get(DerivedMeta, R101_PENDING_KEY) is None:
            opened = not is_deferral_open(s)
            if opened:
                open_deferral(s, reason="R101: quarantined articles leave the keyword counters")
            s.add(DerivedMeta(key=R101_PENDING_KEY, value="opened" if opened else "kept"))
            s.commit()
        return {"owed": True}
    except Exception as exc:  # noqa: BLE001 - opening the store must not depend on this
        s.rollback()
        log_failure(log, "R101 transition could not be prepared; it is tried again at the next start", exc,
                    level=logging.WARNING)
        return {"skipped": "error"}
    finally:
        s.close()


def heal_r101_transition(engine: Any) -> dict:
    """The slow half, in the start-up upkeep after :func:`prepare_r101_transition`: under the write gate and in ONE
    commit with the done marker, recompute the counters of every keyword a quarantined article mentions without
    those articles (:func:`_recompute_counters_of_quarantined_keywords`), and close the counter deferral when
    :func:`prepare_r101_transition` opened it.

    The recompute is idempotent, so a failed attempt the app then ran on from (a reconcile or a new stamp landing
    before the marker) cannot make the next attempt take anything out twice; a crash before the commit leaves the
    deferral open, so the counters keep saying ``estimated`` until the next start finishes the job.
    Best-effort: it logs and returns on any failure."""
    import logging
    from datetime import UTC, datetime

    from src.monitoring.secret_scrub import log_failure

    log = logging.getLogger(__name__)
    if engine.url.get_backend_name() != "sqlite":
        return {"skipped": "not sqlite"}
    from src.database.models import DerivedMeta

    s = _session(engine)
    try:
        if s.get(DerivedMeta, R101_TRANSITION_KEY) is not None:
            return {"skipped": "done"}
        from src.analytics.counter_deferral import COUNTER_DEFERRAL_KEY
        from src.database.writer import connection_first, write_lock

        connection_first(s)
        with write_lock():
            if s.get(DerivedMeta, R101_TRANSITION_KEY) is not None:
                return {"skipped": "done"}
            tally = _recompute_counters_of_quarantined_keywords(s)
            pending = s.get(DerivedMeta, R101_PENDING_KEY)
            if pending is not None:
                if pending.value == "opened":
                    deferral = s.get(DerivedMeta, COUNTER_DEFERRAL_KEY)
                    if deferral is not None:
                        s.delete(deferral)
                s.delete(pending)
            s.add(DerivedMeta(key=R101_TRANSITION_KEY, value=datetime.now(UTC).isoformat(timespec="seconds")))
            s.commit()  # the recompute, the marker and the deferral's close land together
        if tally["keywords"]:
            log.info("R101 transition: recomputed the counters of %d keyword(s) without quarantined articles",
                     tally["keywords"])
        return tally
    except Exception as exc:  # noqa: BLE001 - a boot step must not take the app down
        s.rollback()
        log_failure(log, "R101 keyword counter recompute did not complete; the counters stay marked estimated and "
                    "it runs again at the next start", exc, level=logging.WARNING)
        return {"skipped": "error"}
    finally:
        s.close()
