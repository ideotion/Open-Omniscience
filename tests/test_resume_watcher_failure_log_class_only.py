"""The log line for a resume watcher that cannot start names the exception's CLASS only.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``resume_after_exclusive_operation`` runs in the ``finally`` of an exclusive operation (encrypt, restore, diagnostics bundle ...) that may
have held a passphrase. Its start-refusal log was already class-only; the line for a watcher thread that could not be started went through
``log_failure``, which takes out the secrets the process KNOWS and writes the rest of the exception's first line, so a passphrase the process
did not hold yet could reach the log (and the error ring the diagnostics bundle carries). A thread that cannot be created says nothing its
class does not.
"""

from __future__ import annotations

import logging

import pytest

import src.scheduler.runner as R

WORDS = "words-that-could-carry-a-passphrase"


class _Sched:
    def __init__(self) -> None:
        self.releases = 0

    def hold_exclusive(self) -> None:
        pass

    def release_exclusive(self) -> None:
        self.releases += 1

    def stop(self, timeout: float = 10.0) -> bool:
        return True

    def take_deferred_start(self) -> bool:
        return False

    def start(self) -> bool:
        return False


@pytest.fixture()
def sched(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    s = _Sched()
    monkeypatch.setattr(R, "get_scheduler", lambda: s)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)
    monkeypatch.setattr(R, "_EXCL_DEPTH", 0)
    monkeypatch.setattr(R, "_EXCL_BASE", False)
    monkeypatch.setattr(R, "_EXCL_PAUSED", False)
    monkeypatch.setattr(R, "_start_or_stand_down", lambda retries, retry_delay: False)
    R.cancel_pending_resume()
    yield s
    R.cancel_pending_resume()


def _refuse(*a, **k):
    raise RuntimeError("can't start new thread " + WORDS)


def test_the_watcher_failure_line_has_the_class_and_none_of_the_words(sched, monkeypatch, caplog):
    monkeypatch.setattr(R, "_watch_for_resume", _refuse)
    caplog.set_level(logging.DEBUG, logger=R._LOG.name)
    R.resume_after_exclusive_operation(True, retries=0, retry_delay=0.0)
    assert sched.releases == 1
    lines = [r for r in caplog.records if "watcher thread could not be started" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING
    assert "RuntimeError" in lines[0].getMessage()
    assert lines[0].exc_info is None
    assert WORDS not in caplog.text, "the exception's words reached a log record"
    assert "Traceback" not in caplog.text
