"""The vitals history (memory, drive, database and log counts over days), as a diagnostics route.

A NEW slice imported late, for the reason ``keyword_parts.py`` gives: the split guard pins every
earlier route's POSITION, so a route is added by a file imported near the end, which appends and
moves nothing. It sits just BEFORE ``release_run.py``, whose eight routes ``test_release_run``
pins as the package's last.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from ._base import router


@router.get("/vitals-history")
def vitals_history_report() -> dict:
    """The install's vitals as a history, whole (R119).

    Five-minute rows for 48 hours and hourly rows for 14 days of the process's memory, the
    machine's available memory and swap, thread count, the data drive's free space and the sizes
    of the database, its write-ahead log and the columnar file; the last 60 minutes with the
    busiest threads of each minute; and the log lines that reached the root logger, per hour by
    logger and level. Counts, sizes and times with the method beside them, read-only and local;
    a reading that could not be taken is ``null``, never zero.
    """
    from src.monitoring.vitals_history import diagnostics_member

    return diagnostics_member()
