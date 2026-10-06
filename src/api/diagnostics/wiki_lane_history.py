"""The Wikipedia lane's own hourly history, as a diagnostics route (2026-10-06).

A NEW slice imported late, for the reason ``keyword_parts.py`` gives: the split guard pins every
earlier route's POSITION, so a route is added by a file imported near the end, which appends and
moves nothing. It sits just BEFORE ``release_run.py``, whose eight routes ``test_release_run``
pins as the package's last.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from ._base import router


@router.get("/wiki-lane-history")
def wiki_lane_history() -> dict:
    """The Wikipedia lane's own hourly history of the last seven days, whole.

    What the lane did per hour, kept in its own file so a restart and an update do not erase
    it: the walk's requests, answer times, bytes, pages, refusals by kind with the longest
    Retry-After and the bookmark, each drain's duration and stages, where every tick's seconds
    went, and the stream's per-tick counter differences. Counts and milliseconds with the
    method beside them; read-only and local.
    """
    from src.wiki.service import lane_history

    return lane_history()
