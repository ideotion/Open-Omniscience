"""The all-diagnostics runs and the files served, as a diagnostics route.

A NEW slice imported late, for the reason ``vitals_history.py`` gives: the split guard pins every
earlier route's POSITION, so a route is added by a file imported near the end, which appends and
moves nothing. It sits just BEFORE ``release_run.py``, whose eight routes ``test_release_run``
pins as the package's last.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from ._base import router


@router.get("/runs")
def diagnostics_runs_report() -> dict:
    """The last ten all-diagnostics runs and the files the server sent (R119).

    Each run: when it began, its profile and build, and how it ended (``done``, ``cancelled``,
    ``failed`` with a one-line reason, or ``no-end``: the app or the machine ended it). Each
    served file: its name, size and whether the server sent the last byte. Names, counts and
    times, and a failure's one-line reason (taken through the whole-text scrub, then cut); read-only
    and local; the browser saving a file is not observable and is not claimed.
    """
    from src.monitoring.diagnostics_runs import diagnostics_member

    return diagnostics_member()
