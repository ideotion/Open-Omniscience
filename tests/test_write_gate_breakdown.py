"""Where a write-gate hold's seconds went: insert, savepoint, other statement, commit, between statements (night list 17 Oct, build (a)).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 16 Oct 2026 bundles held the gate for up to 685 s, and the slow-query ring said which statements were slow (INSERT INTO articles 58.6 %,
SAVEPOINT 11.5 %), but not how the hold itself was spent. The gate now keeps, for the hold in progress, the seconds its owner thread spent in
INSERT statements, savepoint statements, any other statement and commits (listeners on every engine that return at once for any other thread);
what no measured statement covers is ``between_statements``. A hold of ``HOLD_RECORD_S`` or more writes the split as ``seconds_by`` into the
storage-events journal, as a sample (the watchdog, so a hold that never ends still has its latest) and exactly at its end. What must hold:

* each statement's seconds go to its own bucket, and the buckets plus ``between_statements`` are the hold's seconds;
* a statement of another thread, or of the holder outside a hold, is not counted, and a new hold starts from zero;
* a sample counts the statement that is still running, a failed statement ends its seconds where it failed, a session's commit is exact
  and a raw connection's commit is an upper bound (it ends at the next work or the release);
* the journal carries the exact split at the end of a long hold and the latest sample of one that is still going.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import threading
import time

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import src.database.session  # noqa: F401 - registers the gate's listeners on the real engine class and session factory
from src.database import writer
from src.database.models import Base, Source
from src.monitoring import storage_events as se

GATE = writer.write_gate


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A file engine with ``slow(seconds)`` and ``boom(seconds)`` SQL functions, a session factory wired as the real one is (the
    writer's hooks plus its after-commit), and a journal of its own."""
    monkeypatch.setenv("OO_WRITE_GATE_WATCHDOG", "0")
    eng = create_engine(f"sqlite:///{tmp_path / 'bd.db'}")

    @event.listens_for(eng, "connect")
    def _functions(dbapi, _rec):  # pragma: no cover - trivial
        dbapi.create_function("slow", 1, lambda x: (time.sleep(x), 1)[1])

        def boom(x):
            time.sleep(x)
            raise ValueError("boom")

        dbapi.create_function("boom", 1, boom)

    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False)
    event.listen(factory, "before_flush", writer._on_before_flush)
    event.listen(factory, "do_orm_execute", writer._on_orm_execute)
    event.listen(factory, "after_transaction_end", writer._on_after_transaction_end)
    event.listen(factory, "after_commit", writer._on_session_commit)
    path = tmp_path / "storage_events.json"
    monkeypatch.setattr(se, "_path", lambda: path)
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.02)
    monkeypatch.setattr(writer, "_JOURNALED_HOLD", None)
    se.reset_for_tests()
    yield eng, factory
    se.reset_for_tests()
    eng.dispose()


def _raw(kind: int) -> float:
    """The unrounded seconds in one bucket of the hold in progress (the buckets are rounded to a tenth when written)."""
    return GATE._spent[kind]


def _by_kind() -> dict[str, float]:
    return GATE._breakdown_locked(time.monotonic() - GATE._held_since)  # type: ignore[operator]


# --------------------------------------------------------------------------- #
#  which bucket a statement is in
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("statement", "kind"),
    [
        ("INSERT INTO articles (a) VALUES (?)", writer._INSERT),
        ("  insert or replace into t values (1)", writer._INSERT),
        ("SAVEPOINT sa_savepoint_1", writer._SAVEPOINT),
        ("RELEASE SAVEPOINT sa_savepoint_1", writer._SAVEPOINT),
        ("ROLLBACK TO SAVEPOINT sa_savepoint_1", writer._SAVEPOINT),
        ("SELECT 1", writer._OTHER),
        ("UPDATE t SET a = 1", writer._OTHER),
        ("DELETE FROM t", writer._OTHER),
        ("PRAGMA wal_checkpoint(PASSIVE)", writer._OTHER),
        ("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x", writer._OTHER),  # the first word only: documented
        ("", writer._OTHER),
        (None, writer._OTHER),
    ],
)
def test_a_statement_is_sorted_by_its_first_word(statement, kind):
    assert writer._statement_kind(statement) == kind


# --------------------------------------------------------------------------- #
#  the split of one hold
# --------------------------------------------------------------------------- #
def test_each_kind_of_work_goes_to_its_own_bucket_and_they_add_up_to_the_hold(world):
    eng, factory = world
    s = factory()
    s.connection()  # the pooled connection first, as the app does
    with writer.write_lock():
        t0 = time.monotonic()
        s.execute(text("INSERT INTO sources (name, domain) SELECT 'x' || slow(0.3), 'a.example'"))
        s.execute(text("SELECT slow(0.2)"))
        with s.begin_nested():
            s.execute(text("UPDATE sources SET name = name"))
        time.sleep(0.25)  # Python work: no statement
        s.commit()
        held = time.monotonic() - t0
        got = _by_kind()
        raw = list(GATE._spent)
    assert 0.3 <= got["insert"] < 1.5 and raw[writer._INSERT] >= 0.3
    assert got["other_statement"] >= 0.2 and raw[writer._OTHER] >= 0.2
    assert raw[writer._SAVEPOINT] > 0.0, "SAVEPOINT / RELEASE are their own bucket (fast here, so unrounded)"
    assert raw[writer._COMMIT] > 0.0, "the commit is its own bucket"
    assert got["between_statements"] >= 0.25, "the sleep is no statement: it is between statements"
    assert sum(got.values()) == pytest.approx(held, abs=0.25), f"the five buckets are the hold's seconds: {got} vs {held:.3f}"
    s.close()


def test_a_statement_of_another_thread_or_outside_the_hold_is_not_counted(world):
    eng, factory = world
    with eng.connect() as outside:
        outside.exec_driver_sql("SELECT slow(0.2)")  # not holding the gate
    s = factory()
    s.connection()
    other = []

    def other_thread():
        with eng.connect() as c:
            c.exec_driver_sql("SELECT slow(0.3)")
        other.append(True)

    with writer.write_lock():
        t = threading.Thread(target=other_thread)
        t.start()
        t.join()
        got = _by_kind()
    assert other == [True]
    assert got["other_statement"] < 0.1, f"a statement of another thread was counted for the holder: {got}"
    assert got["between_statements"] >= 0.25, "the holder waited for the thread: that is between statements"
    s.close()


def test_a_new_hold_starts_from_zero(world):
    eng, factory = world
    s = factory()
    s.connection()
    with writer.write_lock():
        s.execute(text("SELECT slow(0.3)"))
        first = _by_kind()
    with writer.write_lock():
        second = _by_kind()
    assert first["other_statement"] >= 0.3
    assert second["other_statement"] == 0.0 and second["insert"] == 0.0, f"the second hold inherited the first one's seconds: {second}"
    s.close()


def test_a_sample_counts_the_statement_that_is_still_running(world):
    eng, factory = world
    sample: list[dict | None] = []
    release = threading.Event()

    def holder():
        s = factory()  # the holder's own session, closed on the holder's thread (a session's gate depth is released by its thread)
        try:
            s.connection()
            with writer.write_lock():
                s.execute(text("INSERT INTO sources (name, domain) SELECT 'y' || slow(0.8), 'b.example'"))
                release.wait(5)
        finally:
            s.rollback()
            s.close()

    t = threading.Thread(target=holder)
    t.start()
    deadline = time.monotonic() + 5
    # THIS hold's INSERT, not whatever an earlier hold left (a raw connection's commit is never closed): a new hold starts with nothing running
    while (GATE._running is None or GATE._running[0] != writer._INSERT) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert GATE._running is not None and GATE._running[0] == writer._INSERT, "the insert never started"
    time.sleep(0.3)
    sample.append(GATE.hold_breakdown(GATE._held_since))
    release.set()
    t.join()
    assert sample[0] is not None and sample[0]["insert"] >= 0.25, f"a statement still running was left out of the sample: {sample[0]}"


def test_a_sample_of_a_hold_that_is_over_is_none(world):
    assert GATE.hold_breakdown(time.monotonic() - 1.0) is None, "no hold: no split"
    with writer.write_lock():
        started = GATE._held_since
    assert GATE.hold_breakdown(started) is None, "the hold ended: its end writes the exact figures"


def test_a_failed_statement_ends_its_seconds_where_it_failed(world):
    eng, factory = world
    s = factory()
    s.connection()
    with writer.write_lock():
        with pytest.raises(Exception, match="boom"):
            s.execute(text("SELECT boom(0.3)"))
        assert GATE._running is None, "a failed statement was left running"
        got = _by_kind()
        time.sleep(0.2)
        later = _by_kind()
    assert got["other_statement"] >= 0.3
    assert later["other_statement"] == got["other_statement"], "the failed statement kept counting after it failed"
    s.close()


def test_a_sessions_commit_is_closed_exactly_by_its_after_commit(world):
    eng, factory = world
    s = factory()
    s.add(Source(name="c", domain="c.example"))
    s.connection()
    with writer.write_lock():
        s.flush()
        s.commit()
        time.sleep(0.3)  # the gate is still held by this block: the commit is over and must not keep counting
        got = _by_kind()
        commit = GATE._spent[writer._COMMIT]
    assert 0.0 < commit < 0.1, f"the session's commit kept counting after it ended: {commit}"
    assert got["between_statements"] >= 0.3
    s.close()


def test_a_raw_connections_commit_is_an_upper_bound_closed_at_the_release(world):
    """A raw connection has no end event for its commit: it is closed at the next work or the release. The bound is stated, not hidden."""
    eng, factory = world
    with eng.connect() as conn, writer.write_lock():
        conn.exec_driver_sql("INSERT INTO sources (name, domain) VALUES ('r', 'r.example')")
        conn.commit()
        time.sleep(0.3)
        got = GATE._breakdown_locked(time.monotonic() - GATE._held_since)  # type: ignore[operator]
    assert got["commit"] >= 0.25, f"the raw connection's commit stayed open to the release: {got}"


# --------------------------------------------------------------------------- #
#  the journal
# --------------------------------------------------------------------------- #
def test_the_exact_split_is_written_when_a_long_hold_ends(world, monkeypatch):
    eng, factory = world
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.0)
    s = factory()
    s.connection()
    with writer.write_lock():
        s.execute(text("SELECT slow(0.3)"))
        time.sleep(0.2)
    (event_,) = se.diagnostics_member(10**9)["kinds"]["gate_hold"]["events"]
    by = event_["seconds_by"]
    assert set(by) == {"insert", "savepoint", "other_statement", "commit", "between_statements"}
    assert by["other_statement"] >= 0.3 and by["between_statements"] >= 0.2
    assert sum(by.values()) == pytest.approx(event_["seconds"], abs=0.25)
    s.close()


def test_a_hold_shorter_than_the_journals_threshold_writes_nothing(world):
    eng, factory = world
    s = factory()
    s.connection()
    with writer.write_lock():
        s.execute(text("SELECT slow(0.1)"))
    assert se.diagnostics_member(10**9)["kinds"]["gate_hold"]["events"] == []
    s.close()


def test_the_watchdogs_sample_carries_the_split_of_a_hold_that_has_not_ended(world, monkeypatch):
    eng, factory = world
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.0)
    s = factory()
    s.connection()
    with writer.write_lock():
        s.execute(text("SELECT slow(0.3)"))
        writer.watchdog_tick(GATE, None)
        (sampled,) = se.diagnostics_member(10**9)["kinds"]["gate_hold"]["events"]
        assert sampled.get("open") is True or "ended" not in sampled
        assert sampled["seconds_by"]["other_statement"] >= 0.3
    s.close()


# --------------------------------------------------------------------------- #
#  the wiring: listeners where the process's engines and sessions will find them
# --------------------------------------------------------------------------- #
def test_the_listeners_are_on_the_engine_class_and_the_real_session_factory():
    from src.database.session import SessionLocal

    assert event.contains(Engine, "before_cursor_execute", writer._on_statement_start)
    assert event.contains(Engine, "after_cursor_execute", writer._on_statement_end)
    assert event.contains(Engine, "handle_error", writer._on_statement_error)
    assert event.contains(Engine, "commit", writer._on_commit_start)
    assert event.contains(SessionLocal, "after_commit", writer._on_session_commit)


def test_the_real_ingest_path_is_measured_end_to_end(tmp_path, monkeypatch):
    """The real session (not a test factory) writing an article under the real hooks: its INSERT lands in the insert bucket."""
    from src.database.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        s.add(Source(name="bd-real", domain="bd-real.example"))
        s.flush()  # the gate is taken here, by the real before_flush
        assert GATE.held_by_current_thread()
        assert GATE._spent_for == GATE._grants and GATE._spent[writer._INSERT] > 0.0, "the real INSERT was not counted"
        s.commit()


# --------------------------------------------------------------------------- #
#  the read of the delta (17 Oct): a new hold inherits nothing, and what between_statements holds
# --------------------------------------------------------------------------- #
def test_a_new_hold_starts_with_nothing_running_whatever_the_last_hold_left_unclosed(world):
    """A raw connection's commit has no end event, so the hold it ended on leaves ``_running`` set. The next hold must not see it: a sample taken
    between the new hold publishing its number and its first statement starting would book everything since that old commit as this hold's."""
    eng, _factory = world
    with eng.connect() as conn, writer.write_lock():
        conn.exec_driver_sql("SELECT 1")
        conn.commit()
    assert GATE._running is not None and GATE._running[0] == writer._COMMIT, "ANTI-VACUITY: the raw commit stays running after its hold"
    with writer.write_lock():
        assert GATE._running is None, "the new hold inherited the last hold's unclosed commit"
        assert GATE.hold_breakdown(GATE._held_since)["commit"] == 0.0


def test_the_rows_a_select_hands_back_after_its_first_are_between_statements_and_the_text_says_so(world):
    """SQLite steps the rows after the first while the caller reads them, after the statement's end event: a read's seconds are booked as
    ``between_statements`` and ``other_statement`` holds only the work up to the first row. Pinned so nobody reads ``other_statement`` as 'the
    reads' (the member's method sentence names it)."""
    eng, factory = world
    s = factory()
    s.connection()
    with writer.write_lock():
        s.execute(text("SELECT slow(0.2) AS x FROM (SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4)")).fetchall()
        got = GATE.hold_breakdown(GATE._held_since)
    s.close()
    assert got["between_statements"] >= 0.5, f"the rows after the first were not left to between_statements: {got}"
    assert got["other_statement"] <= 0.4, f"only the first row's work belongs to the statement: {got}"
    assert "rows after the first" in se._METHOD, "the member must say what between_statements holds"


@pytest.mark.parametrize("failure", [KeyboardInterrupt, MemoryError])
@pytest.mark.parametrize("measuring", ["_breakdown_locked", "_account_holder_locked"])
def test_a_measurement_that_raises_in_the_release_never_keeps_the_gate(world, monkeypatch, measuring, failure):
    """What the release measures once the gate is free (the long-hold split, which loops over the ledger, and the per-holder row, which every
    outermost release adds) can be interrupted or run out of memory. Measured BEFORE the free, that left the gate owned with its depth at 0 for
    good (a second ``release`` returns at the depth check and every other ``acquire`` queues), on the main-thread route ``write_lock`` ->
    ``release`` of a script (the independent reads of #1429's and #1435's heads, findings L1 and M1). The release still raises (the signal is
    not swallowed); the next writer is granted."""
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.0)
    original = getattr(writer.WriterGate, measuring)

    def _raises(self, *args, **kwargs):
        raise failure

    monkeypatch.setattr(writer.WriterGate, measuring, _raises)
    assert GATE.acquire()
    with pytest.raises(failure):
        GATE.release()
    assert GATE._owner is None, "the release raised with the gate still owned: nothing frees it now"
    monkeypatch.setattr(writer.WriterGate, measuring, original)  # the next writer's own release must not raise again
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 10**9)
    granted: list[bool] = []

    def other():
        granted.append(GATE.acquire(timeout=2.0))
        if granted[-1]:
            GATE.release()

    t = threading.Thread(target=other)
    t.start()
    t.join(5)
    assert granted == [True], f"another writer could not take the gate after {measuring} raised in the release"


def test_nothing_that_can_allocate_runs_between_the_last_read_of_the_release_and_the_free():
    """The branch of ``release`` that ends the outermost hold reads the holder, the start and the usage, clears the owner and calls
    ``_wake_head``: no call before that point (the clock, the sums and the per-holder row come after). A MemoryError needs an instruction that
    allocates, and the interrupt tests above reach the helpers by patching them, which cannot reach the clock's call or the arithmetic; this
    pins the order for everything they cannot."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(writer.WriterGate.release)))
    (branch,) = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare)
        and ast.unparse(n.test) == "self._depth == 0"
    ]
    before_the_free: list[ast.stmt] = []
    for stmt in branch.body:
        if ast.unparse(stmt) == "self._wake_head()":
            break
        before_the_free.append(stmt)
    else:
        pytest.fail("the outermost branch of release no longer calls _wake_head at its own level")
    assigned = {ast.unparse(t) for st in before_the_free if isinstance(st, ast.Assign) for t in st.targets}
    assert {"self._owner", "self._held_since"} <= assigned, "the gate must be cleared before the first call of the branch"
    calls = [ast.unparse(n) for st in before_the_free for n in ast.walk(st) if isinstance(n, ast.Call)]
    assert not calls, f"a call runs before the gate is freed in release(): {calls}"


def test_the_exact_split_still_counts_the_statement_running_at_the_release(world, monkeypatch):
    """The split is now measured after ``_held_since`` is cleared, so the release hands it the hold's start: a raw connection's commit, which
    no end event closes, is still counted up to the release in the journal's exact figures, as it was before the move."""
    eng, factory = world
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.0)
    with eng.connect() as conn, writer.write_lock():
        conn.exec_driver_sql("INSERT INTO sources (name, domain) VALUES ('r', 'r.example')")
        conn.commit()
        time.sleep(0.3)
    (event_,) = se.diagnostics_member(10**9)["kinds"]["gate_hold"]["events"]
    assert event_["seconds_by"]["commit"] >= 0.25, f"the commit open at the release was left out of the exact split: {event_['seconds_by']}"
