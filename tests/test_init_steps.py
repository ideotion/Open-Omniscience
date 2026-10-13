"""The per-step time of ``init_db`` (STORE-02, audit 16 finding 9).

The unlock record kept ONE number for the whole call, and the field read 4.1 and 4.2 s of it on two machines
and 0.7 s on a third with nothing able to say which of the 37 steps was the time. ``src/database/init_steps.py``
times every step by name; these tests pin what a reader of the next zip relies on:

* a step runs from its name to the next one, so an import is a step of its own and nothing is charged to the
  step before it;
* a step that raises is recorded by its exception CLASS and never its text (engine text can carry a path or a
  passphrase), and the exception goes on unchanged;
* the record is per call and per thread, the process's first call is kept apart from the latest, and a reader
  gets a copy;
* every step ``init_db`` runs is named, in order, and every name is followed by the thing it names (the AST
  guard, which is what stops a step added later from being charged to its neighbour);
* the record reaches the unlock record, the P0.4 verdict and the sentinel, and an old or damaged record reads as
  absent rather than as a guess.

Isolation: the clock and the module's call counters are patched per test; the sentinel tests point
``OO_DATA_DIR`` at ``tmp_path`` (never the shared data dir).
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
import threading

import pytest

from src.database import init_steps
from src.monitoring import forensics
from src.monitoring import p0_validation as p0


class _Clock:
    """A clock that moves only when the test says so (seconds)."""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture()
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(init_steps, "_clock", c)
    monkeypatch.setattr(init_steps, "_machine_uptime", lambda: {"machine_uptime_s": 12.5})
    monkeypatch.setattr(init_steps, "_CALLS", 0)
    monkeypatch.setattr(init_steps, "_COMPLETE", 0)
    monkeypatch.setattr(init_steps, "_FIRST", None)
    monkeypatch.setattr(init_steps, "_LAST", None)
    monkeypatch.setattr(init_steps, "_LOCAL", threading.local())
    return c


@pytest.fixture()
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    return tmp_path


# --------------------------------------------------------------------------- #
# the recorder
# --------------------------------------------------------------------------- #
def test_a_step_runs_from_its_name_to_the_next_one(clock):
    @init_steps.recorded
    def body():
        init_steps.step("a")
        clock.advance(0.0105)
        init_steps.step("b")
        clock.advance(1.5)

    body()
    rec = init_steps.this_thread_record()
    assert rec["steps"] == [{"step": "a", "ms": 10.5}, {"step": "b", "ms": 1500.0}]
    assert rec["total_ms"] == 1510.5, "the call's wall time, so the steps can be checked against it"
    assert rec["complete"] is True
    assert rec["process_call"] == 1
    assert rec["machine_uptime_s"] == 12.5
    assert rec["at"].endswith("+00:00"), "a UTC time, to the second"


def test_time_before_the_first_name_is_in_the_total_and_in_no_step(clock):
    """The honest accounting: before rounding the total can exceed the steps' sum, never the other way round
    (the published figures are each rounded to 0.1 ms, so they can differ by that rounding either way)."""

    @init_steps.recorded
    def body():
        clock.advance(0.040)
        init_steps.step("only")
        clock.advance(0.010)

    body()
    rec = init_steps.this_thread_record()
    assert rec["steps"] == [{"step": "only", "ms": 10.0}]
    assert rec["total_ms"] == 50.0


def test_a_call_that_names_no_step_records_none_and_still_a_total(clock):
    @init_steps.recorded
    def body():
        clock.advance(0.002)

    body()
    rec = init_steps.this_thread_record()
    assert rec["steps"] == [] and rec["total_ms"] == 2.0 and rec["complete"] is True


def test_naming_a_step_outside_a_recorded_call_does_nothing(clock):
    init_steps.step("stray")  # the benchmark and the repair paths run steps' callees without a recorder
    assert init_steps.this_thread_record() is None
    assert init_steps.first_record() is None and init_steps.last_record() is None


def test_a_raising_step_is_kept_by_class_only_and_the_exception_goes_on_unchanged(clock):
    secret = "hunter2-passphrase-0001"

    class _EngineError(Exception):
        pass

    @init_steps.recorded
    def body():
        init_steps.step("ok_step")
        clock.advance(0.003)
        init_steps.step("bad_step")
        clock.advance(0.007)
        raise _EngineError(f"unable to open /home/someone/{secret}.db")

    with pytest.raises(_EngineError) as caught:
        body()
    assert secret in str(caught.value), "the exception itself is not touched"
    rec = init_steps.this_thread_record()
    assert rec["steps"] == [
        {"step": "ok_step", "ms": 3.0},
        {"step": "bad_step", "ms": 7.0, "raised": "_EngineError"},
    ]
    assert rec["complete"] is False
    assert secret not in json.dumps(rec) and "someone" not in json.dumps(rec)


def test_a_marker_in_a_raising_steps_message_reaches_no_record_and_no_file(clock, dd):
    """The condition the record is built on: the step names are code constants and a raising step is kept by class, so
    text planted in the exception reaches the in-memory record, the unlock record, the sentinel, the P0.4 verdict and
    every file under the data dir NOWHERE. (Each place is read back after the planted failure, not assumed.)"""
    from src.api.main import _note_boot_init_db
    from src.api.unlock import _forensic_timer

    marker = "PLANTED-MARKER-3f9a-passphrase"

    class _Engine(Exception):
        pass

    @init_steps.recorded
    def body():
        init_steps.step("import:models")
        clock.advance(0.001)
        init_steps.step("create_all")
        clock.advance(0.004)
        raise _Engine(f"unable to open {marker} at /home/someone/{marker}.db: key {marker}")

    forensics.record_session_start()
    with pytest.raises(_Engine) as caught:
        body()
    assert marker in str(caught.value), "the exception is untouched; only the record is the subject"

    t = _forensic_timer(wal_state={"bytes": 0, "state": "absent", "reason": "x"})
    t.phase(forensics.UNLOCK_INIT_DB_PHASE)
    t.note_init_db()
    t.finish()
    _note_boot_init_db()

    sf = forensics.session_forensics()
    assert sf["last_unlock"]["init_db_steps"]["steps"][-1] == {"step": "create_all", "ms": 4.0, "raised": "_Engine"}
    assert sf["last_init_db"]["steps"][-1]["raised"] == "_Engine"
    seen = {
        "this_thread": init_steps.this_thread_record(),
        "first": init_steps.first_record(),
        "last": init_steps.last_record(),
        "session_forensics": sf,
        "verdict": p0._unlock_verdict(sf["last_unlock"]),
    }
    for where, value in seen.items():
        assert marker not in json.dumps(value), where
        assert "someone" not in json.dumps(value), where
    for path in dd.rglob("*"):
        if path.is_file():
            assert marker.encode() not in path.read_bytes(), f"the marker reached {path.name}"


def test_a_base_exception_is_recorded_too_and_the_thread_is_left_clean(clock):
    """A KeyboardInterrupt in the middle of a slow unlock is exactly the record worth keeping."""

    @init_steps.recorded
    def body():
        init_steps.step("slow")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        body()
    assert init_steps.this_thread_record()["steps"][-1]["raised"] == "KeyboardInterrupt"
    assert getattr(init_steps._LOCAL, "recorder", None) is None, "no recorder is left active on this thread"
    init_steps.step("after")  # and naming a step now is a no-op
    assert len(init_steps.this_thread_record()["steps"]) == 1


def test_the_first_call_of_the_process_is_kept_apart_from_the_latest(clock):
    @init_steps.recorded
    def body():
        init_steps.step("x")
        clock.advance(0.001)

    body()
    clock.advance(5)
    body()
    first, last = init_steps.first_record(), init_steps.last_record()
    assert first["process_call"] == 1 and last["process_call"] == 2
    assert first["earlier_complete_calls"] == 0 and last["earlier_complete_calls"] == 1
    assert init_steps.this_thread_record()["process_call"] == 2


def test_a_call_that_raised_is_not_the_cold_call_and_the_one_that_got_through_is(clock):
    """The encrypted ``serve`` start: the launcher's ``init_db`` runs against the still-locked store and raises at
    ``create_all`` (process_call 1); the unlock's call is process_call 2 and is the first that opens the store. A reader
    must be able to tell, so ``earlier_complete_calls`` says 0 for it and ``first_record`` is IT, not the failed attempt."""

    class _Locked(Exception):
        pass

    attempts = iter([True, False, False])

    @init_steps.recorded
    def body():
        init_steps.step("create_all")
        clock.advance(0.01)
        if next(attempts):
            raise _Locked("the store is encrypted at /home/someone/x.db")
        init_steps.step("rest")
        clock.advance(0.5)

    with pytest.raises(_Locked):
        body()
    assert init_steps.first_record() is None, "nothing has completed yet"
    failed = init_steps.last_record()
    assert failed["process_call"] == 1 and failed["earlier_complete_calls"] == 0 and failed["complete"] is False

    body()
    cold = init_steps.first_record()
    assert cold["process_call"] == 2 and cold["earlier_complete_calls"] == 0 and cold["complete"] is True
    body()
    assert init_steps.first_record() == cold, "the later warm call does not replace it"
    assert init_steps.last_record()["earlier_complete_calls"] == 1, "the failed attempt is not counted as one that got through"


def test_two_calls_in_flight_at_once_both_know_no_earlier_call_got_through_and_the_first_to_finish_is_the_cold_one(clock):
    started = threading.Event()
    release = threading.Event()

    @init_steps.recorded
    def slow():
        init_steps.step("slow")
        started.set()
        assert release.wait(10)

    @init_steps.recorded
    def quick():
        init_steps.step("quick")

    t = threading.Thread(target=slow)
    t.start()
    assert started.wait(10)
    quick()  # enters after the slow one and finishes before it
    release.set()
    t.join(10)
    first = init_steps.first_record()
    assert first["steps"][0]["step"] == "quick" and first["process_call"] == 2
    assert first["earlier_complete_calls"] == 0
    assert init_steps.last_record()["steps"][0]["step"] == "slow", "the later finisher is the latest record"
    assert init_steps.last_record()["earlier_complete_calls"] == 0, "it began before anything had completed"


def test_each_thread_reads_its_own_call_and_the_process_reads_the_latest(clock):
    @init_steps.recorded
    def body():
        init_steps.step("x")

    body()
    seen: dict[str, object] = {}

    def other():
        seen["before"] = init_steps.this_thread_record()
        body()
        seen["after"] = init_steps.this_thread_record()

    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert seen["before"] is None, "another thread's init_db is not this thread's"
    assert seen["after"]["process_call"] == 2
    assert init_steps.this_thread_record()["process_call"] == 1
    assert init_steps.last_record()["process_call"] == 2


def test_a_reader_gets_a_copy(clock):
    @init_steps.recorded
    def body():
        init_steps.step("x")

    body()
    got = init_steps.this_thread_record()
    got["steps"][0]["ms"] = 999.0
    got["steps"].append({"step": "forged", "ms": 1.0})
    for again in (init_steps.this_thread_record(), init_steps.first_record(), init_steps.last_record()):
        assert again["steps"] == [{"step": "x", "ms": 0.0}]


def test_a_recorded_call_inside_a_recorded_call_keeps_both_records_apart(clock):
    @init_steps.recorded
    def inner():
        init_steps.step("i1")

    @init_steps.recorded
    def outer():
        init_steps.step("o1")
        inner()
        init_steps.step("o2")

    outer()
    assert [s["step"] for s in init_steps.this_thread_record()["steps"]] == ["o1", "o2"]
    assert [s["step"] for s in init_steps.first_record()["steps"]] == ["i1"], "the inner call finished first"


def test_machine_uptime_is_a_reason_where_it_cannot_be_read(monkeypatch):
    """Absent with the exception CLASS, never a placeholder and never the exception's words."""
    import psutil

    def boom():
        raise RuntimeError("/proc is not mounted for user someone")

    monkeypatch.setattr(psutil, "boot_time", boom)
    got = init_steps._machine_uptime()
    assert got == {"machine_uptime_s": None, "machine_uptime_unavailable": "RuntimeError"}

    monkeypatch.setattr(psutil, "boot_time", lambda: __import__("time").time() - 3600.04)
    assert init_steps._machine_uptime()["machine_uptime_s"] == pytest.approx(3600.0, abs=1.0)


def test_the_uptime_is_read_before_the_clock_starts_so_its_import_is_not_the_calls_time(clock, monkeypatch):
    """``import psutil`` on a cold process is not ``init_db``'s cost: the reading is taken before ``t0``."""

    def slow_reading():
        clock.advance(7.0)  # as a cold import of psutil would
        return {"machine_uptime_s": 1.0}

    monkeypatch.setattr(init_steps, "_machine_uptime", slow_reading)

    @init_steps.recorded
    def body():
        init_steps.step("only")
        clock.advance(0.002)

    body()
    rec = init_steps.this_thread_record()
    assert rec["total_ms"] == 2.0 and rec["steps"] == [{"step": "only", "ms": 2.0}]


def test_slowest_step_trusts_nothing_about_a_stored_record():
    s = init_steps.slowest_step
    assert s({"steps": [{"step": "a", "ms": 5.0}, {"step": "b", "ms": 7.5}, {"step": "c", "ms": 1.0}]}) == {
        "step": "b",
        "ms": 7.5,
    }
    for damaged in (
        None,
        "a string",
        {},
        {"steps": "x"},
        {"steps": []},
        {"steps": [None, "x", {"ms": 9.0}, {"step": 3, "ms": 9.0}, {"step": "t", "ms": True}, {"step": "s", "ms": "9"}]},
        {"steps": [{"step": "n", "ms": float("nan")}, {"step": "i", "ms": float("inf")}, {"step": "h", "ms": 10**400}]},
    ):
        assert s(damaged) is None, damaged


# --------------------------------------------------------------------------- #
# init_db itself
# --------------------------------------------------------------------------- #
def _init_db_function_ast():
    from src.database.session import init_db

    tree = ast.parse(textwrap.dedent(inspect.getsource(init_db)))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "init_db")


def _callee_names(stmt):
    out = []
    for node in ast.walk(stmt):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name:
                out.append(name)
    return out


#: Calls that are not steps: the logger line and the dict read that follow a step (``_LOG.info``, ``_stamp.get``).
_NOT_A_STEP = {"info", "get"}


def _label_of(stmt):
    """What a top-level statement of ``init_db`` is, for the name that must precede it, or None when it is not a step."""
    if isinstance(stmt, ast.ImportFrom):
        return "import:" + (stmt.module or "").split(".")[-1]
    if isinstance(stmt, ast.Import):
        return "import:" + stmt.names[0].name.split(".")[-1]
    called = [n for n in _callee_names(stmt) if n not in _NOT_A_STEP]
    return called[0] if called else None


def test_every_step_init_db_runs_is_named_before_it_runs():
    """A step with no name is charged to the one before it, which is the misattribution this module exists to
    stop: the cold-process cost of an import landing on the step that happened to run first. So EVERY top-level
    statement of ``init_db`` that imports or calls anything (the logger line and a dict read apart) is preceded by
    ``_init_step("<its own name>")``, and every name is followed by the thing it names. A later ``repair_x(engine)`` or
    a plain ``import foo`` fails here too. A name used twice takes a suffix after a colon."""
    fn = _init_db_function_ast()
    pending: str | None = None
    named: list[str] = []
    for stmt in fn.body:
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and getattr(stmt.value.func, "id", None) == "_init_step"
        ):
            args = stmt.value.args
            assert len(args) == 1 and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str)
            assert pending is None, f"the name {pending!r} is followed by another name, not by what it names"
            pending = args[0].value
            continue
        label = _label_of(stmt)
        if label is None:
            assert pending is None, f"the name {pending!r} is followed by a statement that is not a step"
            continue
        assert pending is not None, f"{label!r} (line {stmt.lineno} of init_db) runs unnamed"
        assert pending == label or pending.startswith(label + ":"), f"{label!r} runs under the name {pending!r}"
        named.append(pending)
        pending = None
    assert pending is None, f"the last name, {pending!r}, names nothing"
    assert len(named) == len(set(named)), "a step name is used once, so a record can say WHICH of two it was"

    ensures = {n.split(":")[0] for n in named if n.startswith("ensure_")}
    called = {n for stmt in fn.body for n in _callee_names(stmt) if n.startswith("ensure_")}
    assert ensures == called and len(ensures) >= 30, "a name for every self-heal init_db calls, and nothing else"
    assert "ensure_derived_views:after_align" in named and "ensure_derived_views" in named
    assert named[0] == "import:models" and named[-1] == "ensure_derived_views:after_align"


def test_init_db_records_every_step_and_the_steps_account_for_the_call():
    """Run the real ``init_db`` against the suite's scratch store and read its record back."""
    from src.database.session import init_db

    init_db()
    rec = init_steps.this_thread_record()
    names = [s["step"] for s in rec["steps"]]
    assert rec["complete"] is True and rec["process_call"] >= 1
    for must in ("import:models", "create_all", "ensure_fts", "stamp_if_unstamped", "heal_bulk_build",
                 "ensure_hot_indexes", "align_stamp_to_head", "ensure_keyword_counter_columns"):
        assert must in names, must
    assert len(names) >= 40
    total_of_steps = sum(s["ms"] for s in rec["steps"])
    rounding = 0.05 * (len(rec["steps"]) + 1)  # every figure is rounded to 0.1 ms, so the sums differ by up to that
    assert -rounding <= rec["total_ms"] - total_of_steps <= 25.0, "the steps account for the call, nothing is untimed"
    assert all(isinstance(s["ms"], float) and s["ms"] >= 0 for s in rec["steps"])


def test_a_full_record_stays_small_enough_to_ride_three_places_in_the_diagnostics_zip():
    """What the size protects: a record is carried three times in ``session-forensics.json`` (``last_unlock``, the
    previous session's ``last_unlock`` and the sentinel's ``last_init_db``), and the zip has a 4 MB budget (R119).
    Measured 2,390 bytes for the real 44-entry record (7 imports and 37 calls), so three copies are about 7 KB of the
    member's ~125 KB; the ceiling is the measurement with room, and a step name that grows into a sentence, or a step
    list that doubles, fails here before it reaches a zip."""
    from src.database.session import init_db

    init_db()
    rec = init_steps.this_thread_record()
    size = len(json.dumps(rec))
    assert 1_000 <= size <= 4_000, size
    assert max(len(s["step"]) for s in rec["steps"]) <= 48, "step names are short code identifiers, not sentences"


def test_init_db_keeps_its_signature_and_is_the_recorded_one():
    from src.database.session import init_db

    assert inspect.signature(init_db, follow_wrapped=False).parameters == {}, "the wrapper takes nothing"
    assert inspect.signature(init_db).parameters == {}, "and neither does init_db"
    assert inspect.getsource(init_db).lstrip().startswith("@_record_init_steps"), "the decorator is what records"


# --------------------------------------------------------------------------- #
# the unlock record and the P0.4 verdict
# --------------------------------------------------------------------------- #
def _record(total=4300.0, slowest=("align_stamp_to_head", 3100.0)):
    return {
        "steps": [
            {"step": "create_all", "ms": 400.0},
            {"step": slowest[0], "ms": slowest[1]},
            {"step": "ensure_fts", "ms": 3.0},
        ],
        "total_ms": total,
        "process_call": 1,
        "complete": True,
        "machine_uptime_s": 240.0,
        "at": "2026-10-13T10:00:00+00:00",
    }


def test_the_unlock_timer_carries_the_step_record_of_its_own_thread(dd, clock):
    from src.api.unlock import _forensic_timer

    @init_steps.recorded
    def body():
        init_steps.step("create_all")
        clock.advance(0.2)
        init_steps.step("ensure_fts")
        clock.advance(0.004)

    body()
    t = _forensic_timer(wal_state={"bytes": 0, "state": "absent", "reason": "x"})
    t.phase(forensics.UNLOCK_INIT_DB_PHASE)
    t.note_init_db()
    forensics.record_session_start()
    t.finish()
    rec = forensics.session_forensics()["last_unlock"]
    assert rec["init_db_steps"]["steps"] == [{"step": "create_all", "ms": 200.0}, {"step": "ensure_fts", "ms": 4.0}]
    assert rec["phases"][0]["phase"] == forensics.UNLOCK_INIT_DB_PHASE


def test_the_real_unlock_keeps_the_record_of_the_init_db_call_it_made_not_another_threads(dd, clock, monkeypatch):
    """``_finish_unlock`` end to end (its collaborators patched out, ``init_db`` replaced by a recorded stand-in): the
    record that lands in ``last_unlock`` is the one THIS thread's call published, even when another thread (a restore, a
    repair) published a later one. MUTATION TARGETS: dropping ``_t.note_init_db()`` from ``_finish_unlock``; reading the
    process's latest record instead of the thread's own."""
    from src.api import main as main_mod
    from src.api import startup_status
    from src.api import unlock as unlock_mod
    from src.database import session as session_mod

    @init_steps.recorded
    def own():
        init_steps.step("own_step")
        clock.advance(0.25)

    @init_steps.recorded
    def other():
        init_steps.step("another_threads_step")
        clock.advance(0.5)

    def fake_init_db():
        own()
        worker = threading.Thread(target=other)
        worker.start()
        worker.join()  # published AFTER ours, so the process's latest record is not ours

    monkeypatch.setattr(main_mod, "init_db", fake_init_db)
    monkeypatch.setattr(main_mod, "_run_startup_upkeep", lambda: None)
    monkeypatch.setattr(session_mod, "dispose_engine", lambda: None)
    monkeypatch.setattr(startup_status, "mark_queryable", lambda: None)
    monkeypatch.setattr(startup_status, "set_startup", lambda *a, **k: None)
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")

    forensics.record_session_start()
    unlock_mod._finish_unlock(wal_state=None, verify_ms=None)

    assert init_steps.last_record()["steps"][0]["step"] == "another_threads_step", "the stand-in did publish a later record"
    rec = forensics.session_forensics()["last_unlock"]["init_db_steps"]
    assert [s["step"] for s in rec["steps"]] == ["own_step"]
    assert rec["steps"][0]["ms"] == 250.0


def test_an_unlock_with_no_step_record_writes_no_key(dd, clock):
    """Nothing was recorded on this thread: the key is absent, not an empty record that reads as a fast one."""
    from src.api.unlock import _forensic_timer

    t = _forensic_timer(wal_state={"bytes": 0, "state": "absent", "reason": "x"})
    t.note_init_db()
    forensics.record_session_start()
    t.finish()
    assert "init_db_steps" not in forensics.session_forensics()["last_unlock"]


def test_the_phase_name_the_writer_uses_is_the_one_the_reader_matches():
    src = inspect.getsource(__import__("src.api.unlock", fromlist=["x"]))
    assert "_t.phase(UNLOCK_INIT_DB_PHASE)" in src, "unlock.py names the phase through the shared constant"
    assert 'phase("init_db (schema self-heal' not in src, "and not through a second copy of its words"


def test_a_failing_unlock_names_the_slowest_init_db_step():
    base = {
        "synchronous_total_ms": 5356.0,
        "phases": [
            {"phase": "passphrase verify + WAL recovery + checkpoint-on-close", "ms": 700.0},
            {"phase": forensics.UNLOCK_INIT_DB_PHASE, "ms": 4200.0},
            {"phase": "airplane guard", "ms": 3.0},
        ],
        "at": "x",
        "init_db_steps": _record(),
    }
    c = p0._unlock_verdict(base)
    assert c["verdict"] == "fail"
    assert "Slowest phase: init_db" in c["reason"]
    assert "Its slowest step: align_stamp_to_head (3100 ms)." in c["reason"]
    m = c["measurements"]
    assert m["slowest_init_db_step"] == {"step": "align_stamp_to_head", "ms": 3100.0}
    assert m["init_db_steps"] == base["init_db_steps"]
    assert "page cache" in m["init_db_steps_method"] and "mapper configuration" in m["init_db_steps_method"]


def test_the_slowest_step_is_not_named_when_init_db_is_not_the_slowest_phase():
    base = {
        "synchronous_total_ms": 9000.0,
        "phases": [
            {"phase": "passphrase verify + WAL recovery + checkpoint-on-close", "ms": 8000.0},
            {"phase": forensics.UNLOCK_INIT_DB_PHASE, "ms": 900.0},
        ],
        "at": "x",
        "init_db_steps": _record(),
    }
    c = p0._unlock_verdict(base)
    assert c["verdict"] == "fail" and "Its slowest step" not in c["reason"]
    assert c["measurements"]["slowest_init_db_step"]["step"] == "align_stamp_to_head", "still measured, not asserted"


def test_a_record_from_a_build_before_the_steps_were_timed_reads_as_absent():
    old = {"synchronous_total_ms": 5356.0, "phases": [{"phase": forensics.UNLOCK_INIT_DB_PHASE, "ms": 4200.0}], "at": "x"}
    c = p0._unlock_verdict(old)
    assert c["verdict"] == "fail" and "Its slowest step" not in c["reason"]
    assert "init_db_steps" not in c["measurements"] and "slowest_init_db_step" not in c["measurements"]
    for damaged in ("a string", {"steps": "x"}, {"steps": [{"step": "a", "ms": "slow"}]}, 7, []):
        c = p0._unlock_verdict({**old, "init_db_steps": damaged})
        assert c["verdict"] == "fail" and "Its slowest step" not in c["reason"], damaged
        assert "init_db_steps" not in c["measurements"], damaged


def test_a_passing_unlock_carries_the_steps_without_a_failure_sentence():
    ok = {"synchronous_total_ms": 700.0, "phases": [{"phase": forensics.UNLOCK_INIT_DB_PHASE, "ms": 600.0}],
          "at": "x", "init_db_steps": _record(total=600.0, slowest=("create_all", 400.0))}
    c = p0._unlock_verdict(ok)
    assert c["verdict"] == "pass" and "Its slowest step" not in c["reason"]
    assert c["measurements"]["slowest_init_db_step"]["step"] == "create_all"


# --------------------------------------------------------------------------- #
# the sentinel (a start with no unlock)
# --------------------------------------------------------------------------- #
def test_the_sentinel_keeps_the_record_and_the_next_boot_carries_it_forward(dd):
    forensics.record_session_start()
    forensics.record_init_db(_record())
    assert forensics.session_forensics()["last_init_db"] == _record()
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    assert forensics.session_forensics()["last_init_db"] == _record(), "a locked boot keeps the last cold record"


def test_the_boot_keeps_the_processs_first_call_not_the_warm_one_after_it(dd, clock):
    from src.api.main import _note_boot_init_db

    @init_steps.recorded
    def body():
        init_steps.step(f"call{init_steps._CALLS}")

    body()  # serve(): the cold call
    body()  # the lifespan: the warm one
    forensics.record_session_start()
    _note_boot_init_db()
    kept = forensics.session_forensics()["last_init_db"]
    assert kept["process_call"] == 1 and kept["steps"][0]["step"] == "call1"


def test_the_boot_keeps_the_call_that_got_through_over_a_failed_attempt_before_it(dd, clock):
    """An encrypted ``serve`` start: the launcher's attempt on the locked store raised; the boot that follows the
    unlock keeps the call that completed, and a failed attempt alone is kept when it is all there is."""
    from src.api.main import _note_boot_init_db

    class _Locked(Exception):
        pass

    @init_steps.recorded
    def failing():
        init_steps.step("create_all")
        raise _Locked("encrypted")

    @init_steps.recorded
    def working():
        init_steps.step("create_all")
        clock.advance(0.3)

    with pytest.raises(_Locked):
        failing()
    forensics.record_session_start()
    _note_boot_init_db()
    alone = forensics.session_forensics()["last_init_db"]
    assert alone["complete"] is False and alone["steps"][0]["raised"] == "_Locked", "a failed call is all there is"

    working()
    _note_boot_init_db()
    kept = forensics.session_forensics()["last_init_db"]
    assert kept["complete"] is True and kept["process_call"] == 2 and kept["earlier_complete_calls"] == 0


def test_the_boot_keeps_nothing_when_no_init_db_ran(dd, clock):
    from src.api.main import _note_boot_init_db

    forensics.record_session_start()
    _note_boot_init_db()
    assert forensics.session_forensics()["last_init_db"] is None


def test_the_boot_helper_never_fails_a_boot(dd, clock, monkeypatch):
    from src.api.main import _note_boot_init_db

    def boom(_record):
        raise OSError("disk full: /home/someone/secret")

    monkeypatch.setattr(forensics, "record_init_db", boom)

    @init_steps.recorded
    def body():
        init_steps.step("x")

    body()
    _note_boot_init_db()  # returns


def test_a_boot_whose_init_db_raised_still_keeps_the_record_and_the_error_goes_on(dd, clock, monkeypatch):
    """The cold call that fails is the record worth most (it names the step and the class). ``run_deferred_startup``
    keeps it in the sentinel and lets the exception through; the upkeep does not run."""
    from src.api import main as main_mod
    from src.api import startup_status

    class _Boom(Exception):
        pass

    @init_steps.recorded
    def failing():
        init_steps.step("create_all")
        clock.advance(0.02)
        raise _Boom("unable to open /home/someone/x.db")

    ran: list[str] = []
    monkeypatch.setattr(main_mod, "init_db", failing)
    monkeypatch.setattr(main_mod, "_run_startup_upkeep", lambda: ran.append("upkeep"))
    monkeypatch.setattr(startup_status, "set_startup", lambda *a, **k: None)
    forensics.record_session_start()
    with pytest.raises(_Boom):
        main_mod.run_deferred_startup()
    assert ran == []
    kept = forensics.session_forensics()["last_init_db"]
    assert kept["complete"] is False and kept["steps"][-1] == {"step": "create_all", "ms": 20.0, "raised": "_Boom"}
    assert "someone" not in json.dumps(kept)


def test_the_lifespan_records_right_after_init_db_and_before_the_upkeep():
    """Anchored to the source, not to the shared app singleton."""
    from src.api import main

    src = inspect.getsource(main.run_deferred_startup)
    assert src.index("init_db()") < src.index("_note_boot_init_db()") < src.index("_run_startup_upkeep()")
