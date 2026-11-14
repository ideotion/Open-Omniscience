"""R101 on an upgraded store: the one-time boot step that brings a store written before 0.5.1 into line.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Kept out of :mod:`src.analytics.quarantine_scope`, which an indexing pass loads: this module imports the store, and a
module a pass loads must not import the file the engine identity narrows (``tests/test_engine_identity_narrowed.py``).
"""

from __future__ import annotations

from typing import Any

from src.analytics.quarantine_scope import quarantined_article_ids, quarantined_ids_select

#: ``derived_meta`` key written once the counters of a store follow R101. Before 0.5.1 every quarantined article
#: still counted in ``Keyword.mention_count`` / ``article_count`` (``index_article`` and the reconcile both
#: counted it), and the rollup and the day counts held its rows.
R101_TRANSITION_KEY = "r101_quarantine_counters"


def heal_r101_transition(engine: Any) -> dict:
    """Bring a store written before R101 into line, once, at boot (inside ``init_db``, so before the scheduler or a
    quarantine pass can write).

    Without it the stores disagree after an upgrade: the live readers leave quarantined articles out at once, while
    the counters, the persisted rollup and the day counts keep them until something rebuilds them, so a figure
    would depend on which store served it, which R101 forbids. So, when the store holds a quarantined article:

    1. bump the corpus epoch first (committed), so the rollup and the day counts rebuild on their next read;
    2. then, under the write gate and in ONE commit with the marker, subtract the quarantined articles' mentions from
       the counters, as the quarantine job does for an article it stamps.

    Order is the crash rule: a crash after (1) repeats both on the next boot; the marker and the subtraction commit
    together, so the subtraction never runs twice. A store with no quarantined article only gets the marker.
    Best-effort: it logs and returns on any failure, and never stops the store from opening; the budgeted reconcile
    repairs the counters in that case, more slowly.
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
        from src.analytics.store import shift_keyword_counters_for_quarantine
        from src.database.writer import connection_first, write_lock

        connection_first(s)
        with write_lock():
            if s.get(DerivedMeta, R101_TRANSITION_KEY) is not None:
                return {"skipped": "done"}
            ids = sorted(quarantined_article_ids(s))
            tally = shift_keyword_counters_for_quarantine(s, ids, quarantined=True) if ids else {"articles": 0}
            s.add(DerivedMeta(key=R101_TRANSITION_KEY, value=datetime.now(UTC).isoformat(timespec="seconds")))
            s.commit()
        if ids:
            log.info("R101 transition: %d quarantined article(s) left the keyword counters", len(ids))
        return tally
    except Exception as exc:  # noqa: BLE001 - opening the store must not depend on this
        s.rollback()
        log_failure(log, "R101 transition did not complete; the reconcile will repair the counters", exc,
                    level=logging.WARNING)
        return {"skipped": "error"}
    finally:
        s.close()
