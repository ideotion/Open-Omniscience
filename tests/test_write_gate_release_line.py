"""A hold that reached the watchdog threshold says how long it lasted when it ends (2026-10-13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP. The watchdog warns once per hold, at the first sample at or past ``OO_WRITE_GATE_WARN_S``, so its "held 66.0s" is when the hold
was NOTICED: a hold of 20 s under a 3 s threshold and a 1 s sample logs "held 3.0s". The crash logs of 30 Sep read "60.3 to 73.3 s" for
seventeen holds, and a hold of forty minutes would have read the same. The gate keeps only the process's longest hold (``max_hold_s``).

THE LINE. ``write gate released after N.Ns by 'holder'``, written once per hold that ended at or past the threshold, by the thread that
held it, AFTER the gate's lock is dropped, carrying the holder's thread name and the seconds and nothing else (no exception, no
statement, no engine text), so a hold that ended in an error says no more than one that did not.

Each test below fails when the line goes, speaks too often, speaks while the lock is held, or carries the error.
"""

from __future__ import annotations

import logging
import re
import threading
import time

import pytest

import src.database.writer as writer
from src.database.writer import WriterGate, write_lock

LINE = re.compile(r"write gate released after (\d+\.\d)s by '([^']*)'")


@pytest.fixture(autouse=True)
def _short_threshold(monkeypatch):
    """A 10 ms threshold, and no one-second floor, so a test needs no real second."""
    monkeypatch.setenv("OO_WRITE_GATE_WARN_S", "0.01")
    monkeypatch.setattr(writer, "_RELEASE_LINE_FLOOR_S", 0.0)


def _lines(caplog, holder: str) -> list[logging.LogRecord]:
    """The release lines written for THIS test's holder: the logger is the process's, so a hold that some other thread ends during the
    test (the threshold is ten milliseconds here) must not count against it."""
    return [r for r in caplog.records if r.getMessage().startswith("write gate released after") and f" by '{holder}'" in r.getMessage()]


def _hold(gate: WriterGate, seconds: float, name: str) -> None:
    done = threading.Event()

    def _run() -> None:
        gate.acquire()
        time.sleep(seconds)
        gate.release()
        done.set()

    t = threading.Thread(target=_run, name=name)
    t.start()
    assert done.wait(30)
    t.join(timeout=30)


def test_a_hold_past_the_threshold_is_written_with_its_length_and_its_holder(caplog):
    gate = WriterGate()
    with caplog.at_level(logging.WARNING, logger=writer._LOG.name):
        _hold(gate, 0.25, "oo-the-long-writer")

    lines = _lines(caplog, "oo-the-long-writer")
    assert len(lines) == 1
    m = LINE.fullmatch(lines[0].getMessage())
    assert m is not None, lines[0].getMessage()
    assert float(m.group(1)) >= 0.2, "the length of the hold (0.25 s), not the threshold (0.01 s)"
    assert m.group(2) == "oo-the-long-writer"
    assert lines[0].levelno == logging.WARNING


def test_a_hold_under_the_threshold_says_nothing(monkeypatch, caplog):
    monkeypatch.setenv("OO_WRITE_GATE_WARN_S", "5")
    gate = WriterGate()
    with caplog.at_level(logging.WARNING, logger=writer._LOG.name):
        _hold(gate, 0.05, "oo-short")
    assert _lines(caplog, "oo-short") == []


def test_a_nested_release_is_silent_and_the_outermost_covers_the_whole_hold(caplog):
    """The reentrant write inside a long hold is not a hold of its own: one line, for the whole span."""
    gate = WriterGate()
    me = threading.current_thread().name
    with caplog.at_level(logging.WARNING, logger=writer._LOG.name):
        gate.acquire()
        gate.acquire()
        time.sleep(0.25)
        gate.release()
        assert _lines(caplog, me) == [], "depth 2 to 1 ends no hold"
        gate.release()
    lines = _lines(caplog, me)
    assert len(lines) == 1
    assert float(LINE.fullmatch(lines[0].getMessage()).group(1)) >= 0.2


def test_a_release_by_a_thread_that_does_not_hold_the_gate_says_nothing(caplog):
    gate = WriterGate()
    with caplog.at_level(logging.WARNING, logger=writer._LOG.name):
        t = threading.Thread(target=gate.release, name="not-the-holder")
        t.start()
        t.join(timeout=30)
    assert _lines(caplog, "not-the-holder") == []


def test_a_hold_that_ends_in_an_exception_is_written_and_carries_none_of_it(caplog):
    """``write_lock`` releases in a ``finally``: the error passes through, the line is written, and it holds no engine text."""
    secret = "database disk image is malformed: s3cr3t-passphrase-0001"
    with caplog.at_level(logging.WARNING, logger=writer._LOG.name), pytest.raises(RuntimeError), write_lock():
        time.sleep(0.25)
        raise RuntimeError(secret)

    lines = _lines(caplog, threading.current_thread().name)
    assert len(lines) == 1
    text = lines[0].getMessage()
    assert LINE.fullmatch(text) is not None
    assert "s3cr3t" not in caplog.text and "malformed" not in caplog.text
    assert lines[0].exc_info is None, "no traceback rides the line"
    assert not writer.write_gate.held_by_current_thread(), "and the gate is free"


def test_the_line_is_written_after_the_gates_lock_is_dropped(caplog):
    """A handler that blocks must not hold the lock every other writer queues on."""
    gate = WriterGate()
    owned: list[bool] = []

    class _Probe(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.getMessage().startswith("write gate released after") and " by 'oo-probe'" in record.getMessage():
                owned.append(gate._lock._is_owned())

    probe = _Probe(level=logging.WARNING)
    writer._LOG.addHandler(probe)
    try:
        with caplog.at_level(logging.WARNING, logger=writer._LOG.name):
            _hold(gate, 0.25, "oo-probe")
    finally:
        writer._LOG.removeHandler(probe)

    assert owned == [False], "logged while the gate's lock was still taken"


def test_a_hold_shorter_than_the_floor_never_reads_the_threshold(monkeypatch, caplog):
    """The common hold (milliseconds) pays one float comparison: the environment is read only past the floor."""
    monkeypatch.setattr(writer, "_RELEASE_LINE_FLOOR_S", 1.0)
    reads: list[int] = []
    real = writer._watchdog_threshold_s
    monkeypatch.setattr(writer, "_watchdog_threshold_s", lambda: reads.append(1) or real())
    gate = WriterGate()
    with caplog.at_level(logging.WARNING, logger=writer._LOG.name):
        _hold(gate, 0.25, "oo-under-the-floor")
    assert reads == [] and _lines(caplog, "oo-under-the-floor") == []


def test_a_broken_threshold_read_never_breaks_a_release(monkeypatch):
    def _boom() -> float:
        raise RuntimeError("no threshold")

    monkeypatch.setattr(writer, "_watchdog_threshold_s", _boom)
    gate = WriterGate()
    _hold(gate, 0.02, "oo-quiet")
    assert gate.stats()["held"] is False and gate.stats()["grants"] == 1


def test_a_holder_named_with_the_passphrase_has_it_taken_out_of_the_release_line(monkeypatch, caplog):
    """A thread's name can be chosen by a request (``oo-osm-{code}``, ``served-cache-{key}``): the line is a log sink, so the name
    passes the scrub the journal's holders pass."""
    from src.database import connect as connect_mod

    secret = "MARKER-passphrase-4711-correct-horse"
    monkeypatch.setattr(connect_mod, "_passphrase", secret)
    gate = WriterGate()
    with caplog.at_level(logging.WARNING, logger=writer._LOG.name):
        _hold(gate, 0.25, f"worker-{secret}")
    lines = [r for r in caplog.records if r.getMessage().startswith("write gate released after")]
    assert len(lines) == 1 and "worker-" in lines[0].getMessage(), "the line is still written, with the name's other words"
    assert secret not in caplog.text
