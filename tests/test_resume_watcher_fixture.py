"""The autouse ``_resume_watchers_retired`` fixture (tests/conftest.py) retires a resume watcher a test left running.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The second test runs after the first in this file (pytest keeps file order) and starts nothing: it is red if the first test's 30 s watcher survived it.
"""

from __future__ import annotations

import threading

from src.scheduler import runner


class _Sched:
    _thread = None

    def start(self):
        return False

    def holds_exclusive(self):
        return False


def _watchers():
    return [t for t in threading.enumerate() if t.name == "oo-resume-watch"]


def test_a_test_that_leaves_a_watcher_with_a_long_poll_running():
    runner._watch_for_resume(_Sched(), poll_s=5.0)
    assert _watchers()


def test_the_next_test_finds_no_watcher_alive():
    assert not _watchers()
