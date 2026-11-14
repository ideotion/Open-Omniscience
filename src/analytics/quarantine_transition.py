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


def heal_r101_transition(engine: Any) -> dict:
    """Bring a store written before R101 into line, once, at boot (inside ``init_db``, so before the scheduler or a
    quarantine pass can write).

    Without it the stores disagree after an upgrade: the live readers leave quarantined articles out at once, while
    the counters, the persisted rollup and the day counts keep them until something rebuilds them, so a figure
    would depend on which store served it, which R101 forbids. So, when the store holds a quarantined article:

    1. bump the corpus epoch first (committed), so the rollup and the day counts rebuild on their next read;
    2. then, under the write gate and in ONE commit with the marker, recompute the counters of every keyword a
       quarantined article mentions without those articles (:func:`_recompute_counters_of_quarantined_keywords`).

    Order is the crash rule: a crash after (1) repeats both on the next boot, and the marker commits with the
    recompute. The recompute is idempotent, so a failed attempt the app then ran on from (a reconcile or a new stamp
    landing before the marker) cannot make the next attempt take anything out twice. A store with no quarantined
    article only gets the marker. Best-effort: it logs and returns on any failure, and never stops the store from
    opening; it runs again at the next start.
    """
    import logging
    from datetime import UTC, datetime

    from sqlalchemy.orm import sessionmaker

    from src.monitoring.secret_scrub import log_failure

    log = logging.getLogger(__name__)
    if engine.url.get_backend_name() != "sqlite":
        return {"skipped": "not sqlite"}
    from src.database.models import DerivedMeta

    s = sessionmaker(bind=engine, future=True)()
    try:
        if s.get(DerivedMeta, R101_TRANSITION_KEY) is not None:
            return {"skipped": "done"}
        any_quarantined = s.execute(quarantined_ids_select().limit(1)).first() is not None
        if any_quarantined:
            from src.analytics.corpus_epoch import bump_corpus_epoch

            bump_corpus_epoch(s, reason="r101-transition", strict=True)
        from src.database.writer import connection_first, write_lock

        connection_first(s)
        with write_lock():
            if s.get(DerivedMeta, R101_TRANSITION_KEY) is not None:
                return {"skipped": "done"}
            tally = _recompute_counters_of_quarantined_keywords(s) if any_quarantined else {"keywords": 0}
            s.add(DerivedMeta(key=R101_TRANSITION_KEY, value=datetime.now(UTC).isoformat(timespec="seconds")))
            s.commit()
        if tally["keywords"]:
            log.info("R101 transition: recomputed the counters of %d keyword(s) without quarantined articles",
                     tally["keywords"])
        return tally
    except Exception as exc:  # noqa: BLE001 - opening the store must not depend on this
        s.rollback()
        # The next boot runs it again (a recompute, so repeating it is safe), and bumps the epoch again, which costs
        # one more rebuild of the rollup and the day counts: said here so a repeat is visible in the log.
        log_failure(log, "R101 transition did not complete; it runs again at the next start, rebuilding the keyword "
                    "rollup and day counts once more", exc, level=logging.WARNING)
        return {"skipped": "error"}
    finally:
        s.close()
