"""The storage guard's drain copies the log with PASSIVE before it asks for the gate, so a gate a long writer holds does not cost it the copy.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 16 Oct 2026 bundles: three of the ten kept checkpoint events were ``skipped, WriteGateBusy, 30.0 s`` while the log grew from 1.4 to 1.6 GB.
``checkpoint_wal`` took the write gate around BOTH steps, although PASSIVE needs no write lock (busy timeout zero, it never blocks a writer or a
reader, and it copies every frame up to the oldest reader's mark): the drain was starved by the gate that was overloaded. ``passive_without_gate``
(only the guard's drain passes it) runs PASSIVE first with no gate, then asks for the gate for TRUNCATE exactly as before.

What it buys, at its true size: the frames committed before the busy hold are copied, so the next restart of the log can reuse the file, and the
copy leaves the gate holds. It does NOT shrink the file (only TRUNCATE does), free a log a reader pins, or move the frames of a transaction still open.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

from src.database.writer import write_lock
from src.monitoring import storage_events
from src.scheduler import hygiene, runner, storage_guard
from src.scheduler.hygiene import checkpoint_wal
from src.scheduler.storage_guard import GIB, StorageGuard

ROOT = Path(__file__).resolve().parents[1]
#: What a record of a checkpoint that ran carries, in the order a reader of it knows.
RUN_KEYS = {"busy", "log_frames", "checkpointed_frames", "wal_bytes_before", "wal_bytes_after", "page_size", "duration_ms", "passive", "readers"}


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")
    monkeypatch.setenv("OO_WAL_CHECKPOINT", "1")
    monkeypatch.setattr(runner, "_ensure_storage_supervisor", lambda: None)
    monkeypatch.setenv("OO_WRITE_GATE_WATCHDOG", "0")


def _wal_engine(tmp_path, name="pw.db"):
    db = tmp_path / name
    eng = create_engine(f"sqlite:///{db}", future=True)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi, _rec):
        cur = dbapi.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA wal_autocheckpoint=0")
        cur.close()

    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t(id INTEGER PRIMARY KEY, b BLOB)")
    return db, eng


def _burst(eng) -> None:
    with eng.begin() as c:
        c.exec_driver_sql("INSERT INTO t(b) VALUES " + ",".join(["(zeroblob(3000))"] * 128))


class _GateHeldElsewhere:
    """Another thread holds the write gate until released: the long writer that starved the drain."""

    def __enter__(self):
        self.taken, self.release = threading.Event(), threading.Event()

        def hold():
            with write_lock():
                self.taken.set()
                self.release.wait(30)

        self.thread = threading.Thread(target=hold, name="oo-long-writer")
        self.thread.start()
        assert self.taken.wait(5)
        return self

    def __exit__(self, *exc):
        self.release.set()
        self.thread.join(10)


# --------------------------------------------------------------------------- #
#  what it buys
# --------------------------------------------------------------------------- #
def test_a_gate_held_past_the_bound_still_gets_the_copy_and_says_so(tmp_path):
    """The gate stays busy for the whole bounded wait: the record says ``skipped`` AND carries the passive step, and the frames were really copied
    into the database file. RED WITHOUT the flag: no ``passive`` key, and the database file is still the empty one it was."""
    db, eng = _wal_engine(tmp_path)
    for _ in range(3):
        _burst(eng)
    before = db.stat().st_size
    try:
        with _GateHeldElsewhere():
            rec = checkpoint_wal(engine=eng, force=True, gate_timeout_s=0.3, passive_without_gate=True)
        assert rec is not None and rec["skipped"] == "gate busy" and rec["detail"] == "WriteGateBusy"
        assert rec["passive"]["busy"] == 0
        assert rec["passive"]["log_frames"] > 0
        assert rec["passive"]["checkpointed_frames"] == rec["passive"]["log_frames"], "nothing pins the log: every frame was copied"
        assert rec["page_size"] and isinstance(rec["page_size"], int)
        assert db.stat().st_size > before, "the frames were copied into the database file"
        assert "busy" not in rec and "log_frames" not in rec, "TRUNCATE never ran: its figures are not in the record"
    finally:
        eng.dispose()


def test_the_default_call_still_loses_the_copy_to_a_busy_gate(tmp_path):
    """The control: the pass boundary keeps both steps inside the gate, so a busy gate costs it both and its record is today's three keys."""
    db, eng = _wal_engine(tmp_path)
    _burst(eng)
    before = db.stat().st_size
    try:
        with _GateHeldElsewhere():
            rec = checkpoint_wal(engine=eng, force=True, gate_timeout_s=0.3)
        assert rec is not None and set(rec) == {"skipped", "detail", "waited_s"}
        assert db.stat().st_size == before, "nothing was copied: the gate was the only door"
    finally:
        eng.dispose()


def test_a_reader_that_pins_the_log_is_named_by_the_copy_that_ran_without_the_gate(tmp_path):
    """The passive step copies up to the reader's mark and no further; the skipped record carries exactly that mark, and the pin report built
    from it names how far behind the end of the log the reader holds it. RED WITHOUT the passive figures in the record: ``pin`` is None."""
    db, eng = _wal_engine(tmp_path)
    _burst(eng)
    reader = eng.connect()
    held = reader.exec_driver_sql("SELECT id FROM t")
    held.fetchone()
    for _ in range(3):
        _burst(eng)
    try:
        with _GateHeldElsewhere():
            rec = checkpoint_wal(engine=eng, force=True, gate_timeout_s=0.3, passive_without_gate=True)
        assert rec is not None and "skipped" in rec
        p = rec["passive"]
        assert 0 < p["checkpointed_frames"] < p["log_frames"], "the reader sits behind the end of the log"
        pin = storage_guard._pin_report(rec)["pin"]
        assert pin is not None
        assert pin["mark_frame"] == p["checkpointed_frames"] and pin["frames_behind"] == p["log_frames"] - p["checkpointed_frames"]
        assert pin["bytes_behind"] == pin["frames_behind"] * (rec["page_size"] + 24)
    finally:
        held.close()
        reader.close()
        eng.dispose()


def test_the_journal_says_the_copy_was_all_that_ran(tmp_path, monkeypatch):
    """A gate that stayed busy after a copy is ``passive-only`` in the journal, with the passive row; a gate that stayed busy with no copy is
    ``skipped`` with none. The two are different facts."""
    seen: list[dict] = []
    monkeypatch.setattr(storage_events, "note_checkpoint", lambda trigger, **kw: seen.append({"trigger": trigger, **kw}))
    db, eng = _wal_engine(tmp_path)
    _burst(eng)
    try:
        with _GateHeldElsewhere():
            checkpoint_wal(engine=eng, force=True, gate_timeout_s=0.3, passive_without_gate=True)
            checkpoint_wal(engine=eng, force=True, gate_timeout_s=0.3)
        with_copy, without = seen
        assert with_copy["outcome"] == "passive-only" and with_copy["error"] == "WriteGateBusy"
        assert with_copy["passive"] is not None and with_copy["passive"][1] > 0
        assert without["outcome"] == "skipped" and without["passive"] is None
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- #
#  what it must not change
# --------------------------------------------------------------------------- #
def test_with_the_gate_free_the_record_is_the_one_the_default_call_makes(tmp_path):
    """On twin files, the flag changes neither the keys nor any figure of a checkpoint that ran (the timings aside)."""
    _, a = _wal_engine(tmp_path, "a.db")
    _, b = _wal_engine(tmp_path, "b.db")
    for eng in (a, b):
        for _ in range(3):
            _burst(eng)
    try:
        plain = checkpoint_wal(engine=a, force=True)
        flagged = checkpoint_wal(engine=b, force=True, passive_without_gate=True)
        assert plain is not None and flagged is not None
        assert set(plain) == set(flagged) == RUN_KEYS
        for key in ("busy", "log_frames", "checkpointed_frames", "page_size", "passive"):
            assert plain[key] == flagged[key], key
        assert flagged["busy"] == 0 and flagged["passive"]["checkpointed_frames"] == flagged["passive"]["log_frames"] > 0
    finally:
        a.dispose()
        b.dispose()


def test_the_copy_runs_once_per_call_whichever_way_it_is_asked(tmp_path, monkeypatch):
    """Early without the gate or inside it, never both: a second copy inside the gate would put back the work the flag took out of the hold."""
    calls: list[int] = []
    real = hygiene._passive_step
    monkeypatch.setattr(hygiene, "_passive_step", lambda cur: calls.append(1) or real(cur))
    _, eng = _wal_engine(tmp_path)
    _burst(eng)
    try:
        checkpoint_wal(engine=eng, force=True, passive_without_gate=True)
        assert calls == [1]
        calls.clear()
        checkpoint_wal(engine=eng, force=True)
        assert calls == [1]
    finally:
        eng.dispose()


def test_the_truncate_still_waits_for_the_gate_after_the_copy(tmp_path):
    """The copy does not replace TRUNCATE: a gate released inside the bound lets TRUNCATE run, and the log is reset."""
    db, eng = _wal_engine(tmp_path)
    for _ in range(3):
        _burst(eng)
    wal = Path(str(db) + "-wal")
    try:
        with _GateHeldElsewhere() as held:
            threading.Timer(0.3, held.release.set).start()
            rec = checkpoint_wal(engine=eng, force=True, gate_timeout_s=10, passive_without_gate=True)
        assert rec is not None and "skipped" not in rec and rec["busy"] == 0
        assert rec["wal_bytes_before"] > 0 and wal.stat().st_size == 0, "TRUNCATE reset the log"
    finally:
        eng.dispose()


def test_the_passive_step_does_not_wait_for_the_gate(tmp_path):
    """While another thread holds the gate, the copy completes at once: the whole call takes the bound (the wait for TRUNCATE) and not much
    more, and the copy is done before the wait began. RED WITHOUT the early step: the copy is behind the wait."""
    db, eng = _wal_engine(tmp_path)
    _burst(eng)
    marks: list[float] = []
    real = hygiene._passive_step

    def timed(cur):
        out = real(cur)
        marks.append(time.monotonic())
        return out

    try:
        with _GateHeldElsewhere():
            hygiene._passive_step = timed
            try:
                t0 = time.monotonic()
                checkpoint_wal(engine=eng, force=True, gate_timeout_s=0.6, passive_without_gate=True)
                t1 = time.monotonic()
            finally:
                hygiene._passive_step = real
        assert marks and marks[0] - t0 < 0.4, "the copy waited for the gate"
        assert t1 - t0 >= 0.55, "TRUNCATE still waited its bound for the gate"
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- #
#  who may ask for it
# --------------------------------------------------------------------------- #
def test_only_the_guards_drain_passes_the_flag():
    """A source-level pin: ``passive_without_gate=True`` appears in ``_default_drain`` and nowhere else in ``src/``. The pass boundary, the
    restore's checkpoint before a swap and every other caller keep both steps inside the gate (RED WITHOUT this test: a caller that adds the flag
    to a path that must not race a writer is not seen)."""
    found: list[tuple[str, str]] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "passive_without_gate" not in text:
            continue
        tree = ast.parse(text)
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(func):
                if isinstance(call, ast.Call) and any(
                    k.arg == "passive_without_gate" and not (isinstance(k.value, ast.Constant) and k.value.value is False) for k in call.keywords
                ):
                    found.append((str(path.relative_to(ROOT)), func.name))
    assert set(found) == {("src/scheduler/storage_guard.py", "_default_drain")}, found


def test_the_guards_drain_passes_it_and_keeps_its_bound(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(hygiene, "checkpoint_wal", lambda **kw: seen.update(kw) or {"busy": 0})
    storage_guard._default_drain()
    assert seen["passive_without_gate"] is True and seen["force"] is True and seen["gate_timeout_s"] <= storage_guard.DRAIN_GATE_TIMEOUT_S


def test_a_drain_that_finds_the_machine_owned_takes_neither_step(monkeypatch):
    calls: list = []
    monkeypatch.setattr(hygiene, "checkpoint_wal", lambda **kw: calls.append(kw) or {"busy": 0})
    monkeypatch.setattr(runner, "owns_the_machine", lambda: True)
    g = StorageGuard(trip_after=2, resume_after=2)
    for _ in range(2):
        g.observe(wal_bytes=2 * GIB, corpus_bytes=10 * GIB, disk_free_bytes=300 * GIB, disk_total_bytes=500 * GIB)
    assert g.engaged and g.drain_if_due() is None
    assert calls == [], "a checkpoint ran while an exclusive operation owned the machine"


# --------------------------------------------------------------------------- #
#  what the log line says
# --------------------------------------------------------------------------- #
def test_a_busy_gate_after_a_copy_says_how_far_behind_the_oldest_reader_holds_the_log(caplog, monkeypatch):
    """The copy ran, so the pin is a measurement even though TRUNCATE never did: the line carries it. RED WITHOUT it in the message: the
    operator reads 'the gate was busy' and cannot tell that a reader also holds the log."""
    rec = {
        "skipped": "gate busy",
        "detail": "WriteGateBusy",
        "waited_s": 30.0,
        "passive": {"busy": 0, "log_frames": 300, "checkpointed_frames": 100},
        "page_size": 4096,
    }
    caplog.set_level("INFO", logger="scheduler.storage_guard")
    g = StorageGuard(trip_after=2, resume_after=2, drain_fn=lambda: rec)
    for _ in range(2):
        g.observe(wal_bytes=2 * GIB, corpus_bytes=10 * GIB, disk_free_bytes=300 * GIB, disk_total_bytes=500 * GIB)
    monkeypatch.setattr(runner, "owns_the_machine", lambda: False)
    g.drain_if_due()
    assert "write gate stayed busy" in caplog.text
    assert "the oldest reader holds the log 200 frames" in caplog.text
