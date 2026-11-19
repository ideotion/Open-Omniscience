"""The autouse ``_remembered_sweep_joined`` fixture (tests/conftest.py) waits out a remembered-drive sweep a test started.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

An app boot starts ``oo-backup-remembered-sweep`` on a daemon thread; one a test left running finished in a later test
and rewrote that test's ``backup-temp-dests.json`` (row 166 g). The second test runs after the first in this file
(pytest keeps file order) and starts nothing: it is red if the first test's slow sweep survived it.
"""

from __future__ import annotations

import threading

from src.backup import stream_backup as sb


def _sweeps():
    return [t for t in threading.enumerate() if t.name == "oo-backup-remembered-sweep" and t.is_alive()]


def test_a_test_that_leaves_a_slow_sweep_running(monkeypatch):
    released = threading.Event()
    monkeypatch.setattr(sb, "sweep_remembered_destinations", lambda: released.wait(2.0) and 0)
    t = sb.sweep_remembered_destinations_in_background()
    assert t is not None and t.is_alive()


def test_the_next_test_finds_no_sweep_alive():
    assert not _sweeps()
