"""Import time is not a publication date (R727, R730; field test 2026-11-14 row 63).

The PDF import and the official-statistics corpus wrote ``datetime.now()`` into ``articles.published_at`` for every
document they stored: neither knows when the document was published, so the IMPORT time was recorded as the
publication time. Every surface then read it as a fact about the document ("Published 2026-11-14" on a report from
2009), and the date extractor used it as the anchor that places a date written without a year.

The writers now store NULL ("not known"); the import time already has its own column, ``created_at``, which the
reader shows as the day the app captured the document. This module clears the same false value from rows stored
before the change. It is safe to run any number of times and runs at every boot (``init_db``), because an older
backup merged in later brings the old values back:

  * it touches only the sources these two importers own: the one PDF source (``pdf.import.local``) and the
    per-agency statistics sources (``statistics.<agency>.local`` with ``source_type = 'statistics'``), never a
    catalogue source, whatever its type;
  * it clears a value only where ``published_at`` sits within :data:`TOLERANCE_HOURS` of ``created_at``, which is
    what ``now()`` at insert time looks like. A date some later path filled in from the document itself is left
    alone, so nothing is guessed in either direction;
  * after the first run it finds nothing: the ``(source_id, published_at)`` index answers ``published_at IS NOT
    NULL`` for those few sources without reading an article row.

Wikipedia articles are NOT cleared here. Their date is the page's last revision when one was recorded, which is a
true date of that text, and a fallback to the check time cannot be told apart from a real revision made at the same
moment; the writer is fixed forward only (OPEN_QUEUE 2026-11-16, R727 entry).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

_LOG = logging.getLogger("database.import_dates")

#: How far apart ``published_at`` and ``created_at`` may be for ``published_at`` to count as the insert time.
TOLERANCE_HOURS = 1

#: The sources whose articles carried the import time as their publication date. ``LIKE`` patterns over
#: ``sources.domain``; the statistics pattern is also gated on ``source_type`` below.
PDF_DOMAIN = "pdf.import.local"
STATISTICS_DOMAIN_LIKE = "statistics.%.local"


def _source_ids_sql() -> str:
    return (
        "SELECT id FROM sources WHERE domain = :pdf "
        "OR (domain LIKE :stats AND source_type = 'statistics')"
    )


def clear_import_time_publication_dates(engine: Engine) -> int:
    """Set ``published_at`` to NULL where an importer stored its import time there. Returns the rows changed.

    Idempotent and additive-safe: a second run changes nothing, and a row whose ``published_at`` is not the insert
    time (beyond :data:`TOLERANCE_HOURS`) is never touched. A store without the tables yet is left as it is.
    """
    with engine.begin() as conn:
        tables = {
            r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if not {"articles", "sources"} <= tables:
            return 0
        ids = [int(r[0]) for r in conn.execute(
            text(_source_ids_sql()), {"pdf": PDF_DOMAIN, "stats": STATISTICS_DOMAIN_LIKE}
        )]
        if not ids:
            return 0
        params: dict[str, object] = {f"s{i}": sid for i, sid in enumerate(ids)}
        params["tol"] = TOLERANCE_HOURS / 24.0
        in_list = ", ".join(f":s{i}" for i in range(len(ids)))
        res = conn.execute(
            text(
                f"UPDATE articles SET published_at = NULL WHERE source_id IN ({in_list}) "  # nosec B608 # bound names only
                "AND published_at IS NOT NULL AND created_at IS NOT NULL "
                "AND abs(julianday(published_at) - julianday(created_at)) <= :tol"
            ),
            params,
        )
        n = int(res.rowcount or 0)
    if n:
        _LOG.info("cleared the import time from published_at on %d imported article(s)", n)
    return n
