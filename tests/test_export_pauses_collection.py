"""
The export pauses background collection while it copies the corpus.

Field terminal extract, 2026-09-29 (v0.4.0): an encrypted export to an external drive
held the single-writer gate for its whole corpus copy. Collector workers and the indexer
queued on that gate from inside ``before_flush``, each on a session that already held a
pooled connection, so the small tier's 6 + 6 pool filled and the task manager's poll
(``GET /api/scheduler/activity``) timed out after 30 s and returned 500 until the copy
ended. Restore already paused collection; the export did not.

What is pinned: the pause is entered BEFORE the gate and left AFTER it (so a pass winds
down through its writes instead of piling up behind the copy), a failing pause never
stops the export or skips the gate, and the newsletter-excluding snapshot path gets the
same pause.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from src.backup import stream_backup


@pytest.fixture
def events(monkeypatch, tmp_path):
    log: list[str] = []
    live = tmp_path / "corpus.db"
    live.write_bytes(b"x")

    import src.backup.sqlite_backup as sqlite_backup
    import src.database.connect as connect
    import src.database.writer as writer
    import src.scheduler.runner as runner

    monkeypatch.setattr(sqlite_backup, "live_db_path", lambda: live)
    monkeypatch.setattr(connect, "is_encrypted_file", lambda _p: True)

    @contextmanager
    def fake_window(timeout: float = 10.0):
        log.append("pause")
        try:
            yield True
        finally:
            log.append("resume")

    @contextmanager
    def fake_lock(timeout=None):
        log.append("gate")
        try:
            yield
        finally:
            log.append("ungate")

    monkeypatch.setattr(runner, "exclusive_window", fake_window)
    monkeypatch.setattr(writer, "write_lock", fake_lock)
    monkeypatch.setattr(writer, "gate_enabled", lambda: True)
    monkeypatch.setattr(stream_backup, "_drain_wal", lambda _p: log.append("drain") or None)

    def fake_snapshot(_src, dest):
        log.append("snapshot")
        dest.write_bytes(b"x")

    monkeypatch.setattr(connect, "snapshot_preserving", fake_snapshot)
    monkeypatch.setattr(stream_backup, "_drop_newsletters_in_file", lambda _p: 0)
    return log, tmp_path


def test_the_corpus_copy_runs_inside_a_collection_pause(events):
    log, tmp = events
    notes: list[str] = []
    src = stream_backup._live_corpus_source(tmp, True, notes)
    assert log == [], "nothing may pause before the copy actually starts"
    with src.freeze():
        log.append("copy")
    assert log == ["pause", "gate", "drain", "copy", "ungate", "resume"]
    assert any("collection was paused" in n for n in notes)


def test_a_failing_pause_never_stops_the_export_or_skips_the_gate(events, monkeypatch):
    log, tmp = events
    import src.scheduler.runner as runner

    def broken(timeout: float = 10.0):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(runner, "exclusive_window", broken)
    notes: list[str] = []
    with stream_backup._live_corpus_source(tmp, True, notes).freeze():
        log.append("copy")
    assert log == ["gate", "drain", "copy", "ungate"]
    assert any("could not be paused" in n for n in notes)


def test_a_collector_left_stopped_is_not_announced_as_paused(events, monkeypatch):
    log, tmp = events
    import src.scheduler.runner as runner

    @contextmanager
    def idle_window(timeout: float = 10.0):
        yield False

    monkeypatch.setattr(runner, "exclusive_window", idle_window)
    notes: list[str] = []
    with stream_backup._live_corpus_source(tmp, True, notes).freeze():
        pass
    assert not any("collection" in n for n in notes)


def test_the_newsletter_excluding_snapshot_gets_the_same_pause(events):
    log, tmp = events
    stream_backup._live_corpus_source(tmp, False, [])
    assert log == ["pause", "snapshot", "resume"]
