"""The pin report says how far behind the log's end the oldest reader holds it, and ranks the holders by what they do NOW.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 16 Oct 2026 bundles: a pin report listed the oldest checkouts, and the oldest is usually a worker that is idle. SQLite does record one
thing about a pin: the frame up to which PASSIVE could copy (the oldest reader's mark). It does not record which connection owns it, so
the report gives the figure as a measurement and the holders as candidates, the ones inside a statement or a commit first.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import QueuePool

from src.database import pool_watch, writer
from src.scheduler import storage_guard
from src.scheduler.hygiene import checkpoint_wal


def _wal_engine(tmp_path, *, with_pause: bool = False):
    db = tmp_path / "pin.db"
    eng = create_engine(f"sqlite:///{db}", future=True)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi, _rec):
        cur = dbapi.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA wal_autocheckpoint=0")
        cur.close()
        if with_pause:
            dbapi.create_function("pause", 1, lambda s: time.sleep(s) or 1)

    return db, eng


def _burst(eng) -> None:
    with eng.begin() as c:
        c.exec_driver_sql("INSERT INTO t(b) VALUES " + ",".join(["(zeroblob(3000))"] * 256))


# --------------------------------------------------------------------------- #
#  the measured side: the pin equals what SQLite itself says
# --------------------------------------------------------------------------- #
def test_the_pin_is_the_oldest_readers_mark_and_its_bytes_are_the_files_own_arithmetic(tmp_path):
    db, eng = _wal_engine(tmp_path)
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t(id INTEGER PRIMARY KEY, b BLOB)")
    _burst(eng)
    reader = eng.connect()
    held = reader.exec_driver_sql("SELECT id FROM t")
    held.fetchone()  # an open cursor: the snapshot is held
    for _ in range(3):
        _burst(eng)
    try:
        rec = checkpoint_wal(engine=eng, force=True)
        assert rec is not None and rec["busy"] == 1, "the reader keeps TRUNCATE from resetting the log"
        rep = storage_guard._pin_report(rec)

        # SQLite's own figures, asked a second time with nothing written in between: the same mark, the same end of log.
        import sqlite3

        probe = sqlite3.connect(db, isolation_level=None)
        try:
            _busy, log, done = probe.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            page = probe.execute("PRAGMA page_size").fetchone()[0]
        finally:
            probe.close()
        assert 0 < done < log, "the reader sits behind the end of the log"
        assert rep["pin"] == {
            "mark_frame": done,
            "frames_behind": log - done,
            "bytes_behind": (log - done) * (page + 24),
        }
        # The 24 is not a guess: the file is its 32-byte header plus one page-and-header per frame, and nothing reset it.
        assert Path(str(db) + "-wal").stat().st_size == 32 + log * (page + 24)
        assert "pin_note" not in rep
    finally:
        held.close()
        reader.close()
        eng.dispose()


def test_the_checkpoint_record_carries_the_page_size_it_read(tmp_path):
    db, eng = _wal_engine(tmp_path)
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t(id INTEGER PRIMARY KEY, b BLOB)")
    _burst(eng)
    try:
        rec = checkpoint_wal(engine=eng, force=True)
        assert rec is not None and rec["page_size"] == eng.connect().exec_driver_sql("PRAGMA page_size").scalar()
    finally:
        eng.dispose()


def test_a_passive_pass_that_copied_everything_claims_no_pin_and_does_not_claim_nothing_pins():
    rep = storage_guard._pin_report({"passive": {"busy": 0, "log_frames": 40, "checkpointed_frames": 40}, "page_size": 4096})
    assert rep["pin"] is None
    note = rep["pin_note"]
    assert "does not prove" in note and "snapshot is at the end of the log" in note


@pytest.mark.parametrize(
    "drain, key",
    [
        (None, "no-passive"),
        ({"skipped": "gate busy", "detail": "x", "waited_s": 30.0}, "no-passive"),
        ({"busy": 1}, "no-passive"),
        ({"passive": {"busy": 1, "log_frames": None, "checkpointed_frames": None}}, "no-passive"),
        ({"passive": {"busy": 0, "log_frames": True, "checkpointed_frames": 3}}, "no-passive"),
        ({"passive": {"busy": 0, "log_frames": -1, "checkpointed_frames": -1}}, "unreadable"),
        ({"passive": {"busy": 0, "log_frames": 5, "checkpointed_frames": 9}}, "unreadable"),
    ],
)
def test_a_drain_without_a_readable_mark_gives_no_pin_and_a_fixed_sentence_saying_why(drain, key):
    rep = storage_guard._pin_report(drain)
    assert rep["pin"] is None
    assert rep["pin_note"] == storage_guard._PIN_NOTES[key]


def test_bytes_behind_is_absent_when_the_page_size_was_not_read_not_a_guessed_4096():
    rep = storage_guard._pin_report({"passive": {"busy": 1, "log_frames": 100, "checkpointed_frames": 60}})
    assert rep["pin"] == {"mark_frame": 60, "frames_behind": 40}
    rep = storage_guard._pin_report({"passive": {"busy": 1, "log_frames": 100, "checkpointed_frames": 60}, "page_size": 0})
    assert "bytes_behind" not in rep["pin"]


def test_the_log_line_states_the_pin_in_frames_and_bytes(caplog, monkeypatch):
    from src.scheduler import runner

    monkeypatch.setenv("OO_STORAGE_GUARD", "1")  # the suite switches the guard off; this file feeds it injected readings
    monkeypatch.setattr(runner, "_ensure_storage_supervisor", lambda: None)
    gib = storage_guard.GIB
    drain = {
        "busy": 1,
        "wal_bytes_before": 3 * gib,
        "wal_bytes_after": 3 * gib,
        "page_size": 4096,
        "passive": {"busy": 1, "log_frames": 1000, "checkpointed_frames": 250},
    }
    g = storage_guard.StorageGuard(drain_fn=lambda: drain, trip_after=2, resume_after=2, clock=lambda: 1000.0)
    for _ in range(2):
        g.observe(wal_bytes=3 * gib, corpus_bytes=10 * gib, disk_free_bytes=300 * gib, disk_total_bytes=500 * gib)
    caplog.set_level("INFO", logger=storage_guard._LOG.name)
    assert g.drain_if_due() is not None
    text = " ".join(r.getMessage() for r in caplog.records)
    # 750 frames behind, each a 4096-byte page and a 24-byte header
    assert "holds the log 750 frames (3090000 bytes) behind its end" in text, text


# --------------------------------------------------------------------------- #
#  the candidates: ranked by what the thread does now, then by age
# --------------------------------------------------------------------------- #
def _rows(n_idle: int, *, statement_ident: int | None = None):
    rows = [
        {"ident": 1000 + i, "thread": f"idle-{i}", "pool": "corpus", "age_s": 900.0 - i, "endpoint": None}
        for i in range(n_idle)
    ]
    if statement_ident is not None:
        rows.append(
            {"ident": statement_ident, "thread": "in-statement", "pool": "corpus", "age_s": 2.0, "endpoint": "GET /x"}
        )
    return rows


def test_a_thread_inside_a_statement_is_listed_before_older_idle_ones_even_past_the_cap(monkeypatch):
    rows = _rows(storage_guard.PIN_HOLDERS_MAX + 4, statement_ident=77)
    phases = {r["ident"]: "python" for r in rows}
    phases[77] = "execute"
    monkeypatch.setattr(pool_watch, "is_registered", lambda: True)
    monkeypatch.setattr(pool_watch, "checked_out", lambda: rows)
    monkeypatch.setattr(pool_watch, "stacks_for", lambda idents, *, depth=12: {})
    monkeypatch.setattr(writer, "thread_phases", lambda idents: {i: phases.get(i) for i in idents})
    rep = storage_guard._pin_report({"busy": 1})
    assert rep["checkouts"] == len(rows), "the cap shrinks what is printed, never what is counted"
    assert len(rep["holders"]) == storage_guard.PIN_HOLDERS_MAX
    assert rep["holders"][0]["thread"] == "in-statement" and rep["holders"][0]["phase"] == "execute"
    # inside each group the order stays oldest first
    assert [h["thread"] for h in rep["holders"][1:4]] == ["idle-0", "idle-1", "idle-2"]
    assert rep["oldest_thread"] == "idle-0", "the episode key follows the oldest checkout, not the ranking"


def test_a_thread_in_a_commit_ranks_with_the_statements_and_a_gone_thread_has_no_phase(monkeypatch):
    rows = _rows(2) + [
        {"ident": 31, "thread": "committing", "pool": "corpus", "age_s": 1.0},
        {"ident": 32, "thread": "gone", "pool": "read_snapshot", "age_s": 5000.0},
    ]
    phases = {1000: "python", 1001: "pool-wait", 31: "commit", 32: None}
    monkeypatch.setattr(pool_watch, "is_registered", lambda: True)
    monkeypatch.setattr(pool_watch, "checked_out", lambda: rows)
    monkeypatch.setattr(pool_watch, "stacks_for", lambda idents, *, depth=12: {})
    monkeypatch.setattr(writer, "thread_phases", lambda idents: {i: phases.get(i) for i in idents})
    rep = storage_guard._pin_report({"busy": 1})
    assert [(h["thread"], h["phase"]) for h in rep["holders"]] == [
        ("committing", "commit"),
        ("idle-0", "python"),
        ("idle-1", "pool-wait"),
        ("gone", None),
    ]


def test_the_phases_of_real_threads_rank_the_one_inside_a_statement_first(tmp_path):
    db, eng = _wal_engine(tmp_path, with_pause=True)
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t(id INTEGER PRIMARY KEY, b BLOB)")
    release = threading.Event()
    idle_up = threading.Event()
    stmt_up = threading.Event()

    def idle():
        idle_up.set()
        release.wait(10)

    def in_statement():
        with eng.connect() as c:
            stmt_up.set()
            c.exec_driver_sql("SELECT pause(2)").fetchall()

    t_idle = threading.Thread(target=idle, name="pin-idle")
    t_stmt = threading.Thread(target=in_statement, name="pin-statement")
    t_idle.start()
    assert idle_up.wait(5)
    t_stmt.start()
    assert stmt_up.wait(5)
    time.sleep(0.4)  # into the statement
    pool_watch.register(eng)
    try:
        import unittest.mock as mock

        rows = [  # the idle thread's checkout is the OLDER one
            {"ident": t_idle.ident, "thread": "pin-idle", "pool": "corpus", "age_s": 600.0, "endpoint": None},
            {"ident": t_stmt.ident, "thread": "pin-statement", "pool": "corpus", "age_s": 1.0, "endpoint": None},
        ]
        with mock.patch.object(pool_watch, "checked_out", lambda: rows):
            rep = storage_guard._pin_report({"busy": 1})
        assert [(h["thread"], h["phase"]) for h in rep["holders"]] == [("pin-statement", "execute"), ("pin-idle", "python")]
    finally:
        release.set()
        t_idle.join(10)
        t_stmt.join(15)
        eng.dispose()


def test_the_caveat_says_the_pin_is_measured_and_no_holder_is_proof_of_it():
    caveat = storage_guard._pin_report(None)["caveat"]
    assert "SQLite records how far behind the end of the log the oldest reader holds it" in caveat
    assert "none is proof" in caveat
    assert "not how long a statement ran" in caveat
    assert "likeliest" not in caveat, "the age no longer picks the culprit"


def test_the_report_holds_only_numbers_names_and_fixed_sentences():
    """The report rides the bundle: a drain record with a stray text field must not reach it through the pin."""
    rep = storage_guard._pin_report(
        {"passive": {"busy": 1, "log_frames": 9, "checkpointed_frames": 4}, "page_size": 4096, "error": "secret-ish text"}
    )
    assert set(rep["pin"]) == {"mark_frame", "frames_behind", "bytes_behind"}
    assert all(type(v) is int for v in rep["pin"].values())
    assert "secret-ish" not in repr({k: v for k, v in rep.items() if k != "drain"})


# --------------------------------------------------------------------------- #
#  the four things the first version of these tests let through
# --------------------------------------------------------------------------- #
def test_a_page_size_that_cannot_be_read_leaves_the_record_and_the_bytes_absent_not_a_guessed_4096(tmp_path):
    import sqlite3

    db = tmp_path / "nopage.db"

    class _Cursor(sqlite3.Cursor):
        def execute(self, sql, *args):
            if "page_size" in sql:
                raise sqlite3.OperationalError("refused")
            return super().execute(sql, *args)

    class _Conn(sqlite3.Connection):
        def cursor(self, factory=_Cursor):
            return super().cursor(factory)

    def creator():
        c = sqlite3.connect(db, factory=_Conn, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA wal_autocheckpoint=0")
        return c

    eng = create_engine("sqlite://", creator=creator, poolclass=QueuePool, pool_size=5, future=True)
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t(id INTEGER PRIMARY KEY, b BLOB)")
    _burst(eng)
    reader = eng.connect()
    held = reader.exec_driver_sql("SELECT id FROM t")
    held.fetchone()
    _burst(eng)
    try:
        rec = checkpoint_wal(engine=eng, force=True)
        assert rec is not None and rec["busy"] == 1
        assert rec["page_size"] is None, "an unread page size is absent, never a default"
        pin = storage_guard._pin_report(rec)["pin"]
        assert pin is not None and pin["frames_behind"] > 0 and "bytes_behind" not in pin
    finally:
        held.close()
        reader.close()
        eng.dispose()


def _episode_guard(monkeypatch):
    from src.scheduler import runner

    monkeypatch.setenv("OO_STORAGE_GUARD", "1")
    monkeypatch.setattr(runner, "_ensure_storage_supervisor", lambda: None)
    gib = storage_guard.GIB
    now = [1000.0]
    g = storage_guard.StorageGuard(
        drain_fn=lambda: {"busy": 1, "wal_bytes_before": 3 * gib, "wal_bytes_after": 3 * gib},
        trip_after=2,
        resume_after=2,
        clock=lambda: now[0],
    )
    for _ in range(2):
        g.observe(wal_bytes=3 * gib, corpus_bytes=10 * gib, disk_free_bytes=300 * gib, disk_total_bytes=500 * gib)

    def tick():
        now[0] += storage_guard.PIN_REPORT_EVERY_S + 1
        g.drain_if_due()

    return g, tick


def test_a_change_in_who_is_inside_a_statement_is_not_news_but_a_change_of_the_oldest_checkout_is(monkeypatch, caplog):
    """The listing is ranked by what each thread does NOW, which changes between reports; the episode key follows the oldest
    checkout, so a worker stepping in and out of a statement does not bring the one-warning-a-minute flood back."""
    g, tick = _episode_guard(monkeypatch)
    shown = [
        {
            "holders": [{"thread": "worker-a", "age_s": 2.0, "phase": "execute"}, {"thread": "pinner", "age_s": 900.0, "phase": "python"}],
            "oldest_thread": "pinner",
        }
    ]
    monkeypatch.setattr(storage_guard, "_pin_report", lambda rec: shown[0])
    with caplog.at_level("INFO", logger=storage_guard._LOG.name):
        tick()
        shown[0] = {
            "holders": [{"thread": "pinner", "age_s": 960.0, "phase": "execute"}, {"thread": "worker-b", "age_s": 1.0, "phase": "commit"}],
            "oldest_thread": "pinner",
        }
        tick()
        shown[0] = {
            "holders": [{"thread": "worker-c", "age_s": 3.0, "phase": "execute"}, {"thread": "pinner", "age_s": 1020.0, "phase": "python"}],
            "oldest_thread": "pinner",
        }
        tick()
        levels = [r.levelname for r in caplog.records if "TRUNCATE is busy" in r.getMessage()]
        assert levels == ["WARNING", "INFO", "INFO"], levels
        shown[0] = {"holders": [{"thread": "newcomer", "age_s": 5000.0, "phase": "python"}], "oldest_thread": "newcomer"}
        tick()
        levels = [r.levelname for r in caplog.records if "TRUNCATE is busy" in r.getMessage()]
        assert levels[-1] == "WARNING", "a different oldest checkout is a different pin"


def test_the_log_line_names_the_phase_each_listed_holder_is_in(monkeypatch, caplog):
    g, tick = _episode_guard(monkeypatch)
    monkeypatch.setattr(
        storage_guard,
        "_pin_report",
        lambda rec: {
            "holders": [
                {"thread": "oo-api", "age_s": 4.0, "pool": "corpus", "phase": "execute", "stack": ["src/api/x.py:1 handler"]},
                {"thread": "oo-idle", "age_s": 700.0, "pool": "corpus", "phase": None},
            ],
            "oldest_thread": "oo-idle",
        },
    )
    with caplog.at_level("INFO", logger=storage_guard._LOG.name):
        tick()
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "oo-api (4 s) [corpus pool] in execute at src/api/x.py:1 handler" in text, text
    assert "oo-idle (700 s) [corpus pool];" in text or text.rstrip().endswith("oo-idle (700 s) [corpus pool]"), text


def test_many_threads_are_classified_from_one_snapshot_of_the_frames(monkeypatch):
    """The pin report asks for a handful at once; reading the stacks thread by thread would read them at different instants."""
    import sys

    real = sys._current_frames
    calls = []

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(sys, "_current_frames", counting)
    me = threading.get_ident()
    got = writer.thread_phases([me, me, 2**62, None])
    assert len(calls) == 1
    assert got[me] == "python" and got[2**62] is None
