"""Every thread the rollup serve canary starts carries a name (F4 of the 0.5.0 side-effect audit).

The canary starts a peak poller and a ``threading.Timer`` for the interrupt. The poller was named ``rollup-canary-peak``; the timer was the bare
``Thread-N`` a side-effect monitor cannot attribute to anything. This reads the threads alive while the canary's own query runs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import threading

from src.analytics import columnar


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class _Con:
    """A connection whose main query records the names of the threads alive while it runs."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        if "duckdb_memory" in sql:
            return _Rows([(500.0,)])
        self.seen = [t.name for t in threading.enumerate()]
        return _Rows([("t", "t", "k", "en", 3, 2)])

    def cursor(self):
        return self

    def close(self) -> None:
        pass

    def interrupt(self) -> None:
        pass


def test_the_canary_names_both_threads_it_starts():
    con = _Con()
    out = columnar.serve_canary(con)
    assert out["outcome"] == "ok"
    assert "rollup-canary-peak" in con.seen and "rollup-canary-timer" in con.seen, con.seen
