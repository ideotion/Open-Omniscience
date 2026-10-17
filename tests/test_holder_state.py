"""What the gate holder's thread was doing in the kernel, counted once a second while a hold the journal keeps lasts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS PINS (``src/monitoring/holder_state.py`` and its three seams in ``src/database/writer.py``). The 16 Oct bundles show holds of 30 to
182 s whose holder is a collector thread, and the journal could not say whether the thread was working, waiting for a CPU, waiting for the
GIL or a lock, sleeping in SQLite's busy handler, or waiting for the disk. Each class below has a fake ``/proc`` entry that is that class and
nothing else, so a classification that moves a class into another fails by name; the live cases read the real kernel (Linux only).

Every refusal is pinned as hard as the counting: the first look of a hold counts nothing; an unreadable figure is a named reason and never a
zero; the thread's name (the kernel's ``comm``, which sits in ``stat``) and the kernel symbol never reach the journal; an error's text never
does either. The last block pins the width the budget counts the hold's frames at against every function under ``src/``.
"""

from __future__ import annotations

import ast
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from src.database import writer
from src.monitoring import holder_state as hs
from src.monitoring import storage_events as se

from .test_storage_events import (  # noqa: F401  (journal is a fixture)
    MARKER,
    _events,
    _member,
    journal,
)

TID = 4242
LINUX = sys.platform.startswith("linux")


# --------------------------------------------------------------------------- #
#  A made-up /proc tree: one thread whose state the test turns by hand
# --------------------------------------------------------------------------- #
class _Proc:
    """``<root>/<tid>/{stat,wchan,schedstat}`` for one thread, rewritten between looks."""

    def __init__(self, root: Path, tid: int = TID) -> None:
        self.dir = root / str(tid)
        self.dir.mkdir(exist_ok=True)
        self.tid = tid
        self.cpu_ns = 1_000_000
        self.wait_ns = 0

    def put(self, state: str = "S", wchan: str = "0", *, ran_ns: int = 0, waited_ns: int = 0, comm: str = "python", sched: bool = True) -> None:
        """The thread's next reading: its state, its ``wchan`` and how much it ran and waited on a run queue since the previous one."""
        self.cpu_ns += ran_ns
        self.wait_ns += waited_ns
        (self.dir / "stat").write_text(f"{self.tid} ({comm}) {state} 1 1 1 0 -1 4194560 100 0 0 0 5 1 0 0 20 0 1 0 100 1000 100\n")
        (self.dir / "wchan").write_text(wchan)
        sched_file = self.dir / "schedstat"
        if sched:
            sched_file.write_text(f"{self.cpu_ns} {self.wait_ns} 7\n")
        elif sched_file.exists():
            sched_file.unlink()

    def wchan_unreadable(self) -> None:
        (self.dir / "wchan").unlink()


@pytest.fixture()
def proc(tmp_path, monkeypatch):
    """A fake process: the module reads ``tmp_path`` as Linux's ``/proc/self/task`` and resolves every ident to ``TID``."""
    root = tmp_path / "task"
    root.mkdir()
    monkeypatch.setattr(hs, "_TASK_DIR", str(root))
    monkeypatch.setattr(hs, "_PLATFORM", "linux")
    monkeypatch.setattr(hs, "native_id_of", lambda ident: TID)
    hs.forget()
    p = _Proc(root)
    p.put()
    yield p
    hs.forget()


def _look(started: float, at: float) -> bool:
    return hs.look(started, 111, at)


# --------------------------------------------------------------------------- #
#  The classes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("state", "wchan", "cpu", "wait", "expected"),
    [
        ("R", "0", 900_000_000, 50_000_000, "running"),
        ("R", "0", 100_000_000, 800_000_000, "runnable"),
        ("R", "0", 5, 5, "running"),  # a tie is not a wait for a CPU
        ("R", "0", None, None, "other"),  # running or runnable cannot be told apart without the scheduler's figures
        ("S", "futex_do_wait", None, None, "futex"),
        ("S", "futex_wait_queue", None, None, "futex"),
        ("S", "hrtimer_nanosleep", None, None, "nap"),
        ("S", "do_nanosleep", None, None, "nap"),
        ("S", "do_epoll_wait", None, None, "other"),
        ("S", "pipe_read", None, None, "other"),
        ("S", "0", None, None, "other"),  # a sleep whose wchan cannot be read is not guessed
        ("S", "", None, None, "other"),
        ("D", "io_schedule", None, None, "disk"),
        ("D", "0", None, None, "disk"),
        ("T", "do_signal_stop", None, None, "other"),
        ("Z", "0", None, None, "other"),
        ("I", "0", None, None, "other"),
    ],
)
def test_each_kernel_state_is_counted_in_its_own_class_and_no_other(state, wchan, cpu, wait, expected):
    assert hs.classify(state, wchan, cpu, wait) == expected


def test_a_futex_wchan_is_a_futex_only_while_asleep():
    """A thread in state R whose wchan still names a futex (the symbol is stale for a thread the scheduler just woke) is running or runnable."""
    assert hs.classify("R", "futex_do_wait", 10, 1) == "running"
    assert hs.classify("D", "futex_do_wait", None, None) == "disk"


def test_the_classes_are_six_and_in_the_order_the_journal_writes_them():
    assert hs.CLASSES == ("running", "runnable", "futex", "nap", "disk", "other")


def test_the_state_is_read_after_the_last_parenthesis():
    """The kernel writes the thread's name between parentheses and it may hold any character, ``)`` and a state letter among them."""
    assert hs._state_of(b"4242 (python) S 1 1 1 0") == "S"
    assert hs._state_of(b"4242 (evil) R 1 (x) D 1 1 1 0") == "D"
    assert hs._state_of(b"4242 (a b) c) T 1 1") == "T"
    assert hs._state_of(b"4242 (python)") is None
    assert hs._state_of(b"4242 (python) 7 1") is None, "a digit is not a state"
    assert hs._state_of(b"") is None


# --------------------------------------------------------------------------- #
#  Counting one hold
# --------------------------------------------------------------------------- #
def test_the_first_look_of_a_hold_counts_nothing_and_the_second_counts_one(proc):
    proc.put("S", "futex_do_wait")
    assert _look(10.0, 100.0) is True
    assert hs.fields_for(10.0) == {}, "the first look is the baseline: no count, no gap, no reason"
    proc.put("S", "futex_do_wait")
    assert _look(10.0, 101.0) is True
    assert hs.fields_for(10.0) == {"ws": [0, 0, 1, 0, 0, 0], "gap": 1.0}


def test_every_class_is_counted_where_it_belongs_over_a_run_of_looks(proc):
    proc.put("S", "futex_do_wait")
    _look(10.0, 100.0)  # baseline
    script = [
        ("S", "futex_do_wait", 0, 0),
        ("S", "futex_wait_queue", 0, 0),
        ("S", "futex_do_wait", 0, 0),
        ("S", "hrtimer_nanosleep", 0, 0),
        ("S", "hrtimer_nanosleep", 0, 0),
        ("D", "io_schedule", 0, 0),
        ("R", "0", 900_000_000, 10_000_000),
        ("R", "0", 800_000_000, 20_000_000),
        ("R", "0", 100_000_000, 700_000_000),
        ("S", "do_epoll_wait", 0, 0),
    ]
    for i, (state, wchan, ran, waited) in enumerate(script, start=1):
        proc.put(state, wchan, ran_ns=ran, waited_ns=waited)
        _look(10.0, 100.0 + i)
    assert hs.fields_for(10.0) == {"ws": [2, 1, 3, 2, 1, 1], "gap": 1.0}, "two running and one runnable: the columns of schedstat are not interchangeable"


def test_gap_is_the_longest_time_between_two_looks_that_could_be_read(proc):
    _look(10.0, 100.0)
    for at in (101.0, 102.1, 102.4):
        proc.put("S", "futex_do_wait")
        _look(10.0, at)
    assert hs.fields_for(10.0)["gap"] == 1.1
    # An unreadable look is not a look: the time it covered shows in the next gap, so a starved process and a vanished file read alike.
    (proc.dir / "stat").unlink()
    assert _look(10.0, 103.0) is True
    (proc.dir / "stat").write_text("4242 (python) S 1\n")
    _look(10.0, 106.4)
    assert hs.fields_for(10.0)["gap"] == 4.0, "from the last look that was read (102.4) to the next (106.4)"


def test_a_running_look_with_no_scheduler_figures_is_other_not_a_guess(proc):
    proc.put("R", "0")
    _look(10.0, 100.0)
    proc.put("R", "0", sched=False)
    _look(10.0, 101.0)
    assert hs.fields_for(10.0)["ws"] == [0, 0, 0, 0, 0, 1]


def test_a_sleep_whose_wchan_cannot_be_read_is_other_not_a_guess(proc):
    proc.put("S", "futex_do_wait")
    _look(10.0, 100.0)
    proc.put("S", "futex_do_wait")
    proc.wchan_unreadable()
    _look(10.0, 101.0)
    assert hs.fields_for(10.0)["ws"] == [0, 0, 0, 0, 0, 1]


def test_a_new_hold_starts_from_none_and_the_old_one_is_not_credited(proc):
    _look(10.0, 100.0)
    proc.put("S", "futex_do_wait")
    _look(10.0, 101.0)
    assert hs.fields_for(10.0)["ws"] == [0, 0, 1, 0, 0, 0]
    _look(55.0, 102.0)  # another hold
    assert hs.fields_for(55.0) == {}, "its own baseline, none of the old hold's counts"
    proc.put("D", "io_schedule")
    _look(55.0, 103.0)
    assert hs.fields_for(55.0) == {"ws": [0, 0, 0, 0, 1, 0], "gap": 1.0}
    assert hs.fields_for(10.0) == {}, "the old hold is gone: its release asks for its counts and is answered with none, not another hold's"
    assert hs.fields_for(None) == {}


def test_a_look_that_finishes_after_a_newer_hold_replaced_its_hold_says_to_stop(proc, monkeypatch):
    """The reads happen outside the lock, so a newer hold can take the place of the one being looked at while its files are read."""
    real = hs._look_at

    def slow(tid):
        monkeypatch.setattr(hs, "_look_at", real)
        _look(55.0, 101.5)  # the newer hold's first look, taken while the older hold's files are being read
        return real(tid)

    _look(10.0, 100.0)
    monkeypatch.setattr(hs, "_look_at", slow)
    proc.put("S", "futex_do_wait")
    assert _look(10.0, 101.0) is False, "the hold this look was for is gone"
    assert hs.fields_for(10.0) == {} and hs.fields_for(55.0) == {}, "nothing was counted for either"


def test_forget_drops_the_counts_of_a_hold_that_ended(proc):
    _look(10.0, 100.0)
    proc.put("S", "futex_do_wait")
    _look(10.0, 101.0)
    hs.forget()
    assert hs.fields_for(10.0) == {}


# --------------------------------------------------------------------------- #
#  A figure the OS cannot give is a reason, never a zero
# --------------------------------------------------------------------------- #
def test_off_linux_the_hold_says_the_os_cannot_and_the_looks_stop(proc, monkeypatch):
    monkeypatch.setattr(hs, "_PLATFORM", "win32")
    assert _look(10.0, 100.0) is False, "the looks do not go on at one a second where they can never be taken"
    assert hs.fields_for(10.0) == {"ws": None, "ws_why": hs.UNSUPPORTED}


def test_a_platform_without_the_task_directory_says_the_same(proc, monkeypatch, tmp_path):
    monkeypatch.setattr(hs, "_TASK_DIR", str(tmp_path / "no-such-proc"))
    assert _look(10.0, 100.0) is False
    assert hs.fields_for(10.0) == {"ws": None, "ws_why": hs.UNSUPPORTED}


def test_a_holder_whose_files_are_gone_says_so_and_keeps_trying(proc):
    for name in ("stat", "wchan", "schedstat"):
        (proc.dir / name).unlink()
    proc.dir.rmdir()
    assert _look(10.0, 100.0) is True, "a thread can reappear in the table only by being a different one, but the next look is cheap"
    assert hs.fields_for(10.0) == {"ws": None, "ws_why": hs.GONE}


def test_an_unreadable_stat_says_proc_unreadable_with_no_error_text(proc):
    (proc.dir / "stat").unlink()
    (proc.dir / "stat").mkdir()  # opening a directory raises an OSError whose text names the path
    assert _look(10.0, 100.0) is True
    f = hs.fields_for(10.0)
    assert f == {"ws": None, "ws_why": hs.UNREADABLE}
    assert "stat" not in json.dumps(f)


def test_a_thread_no_longer_in_the_interpreter_says_it_is_gone(monkeypatch, tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    monkeypatch.setattr(hs, "_TASK_DIR", str(root))
    monkeypatch.setattr(hs, "_PLATFORM", "linux")
    hs.forget()
    assert hs.native_id_of(None) is None
    assert hs.native_id_of(2**40) is None
    assert hs.look(10.0, 2**40, 100.0) is True
    assert hs.fields_for(10.0) == {"ws": None, "ws_why": hs.GONE}
    hs.forget()


def test_a_reason_given_while_the_files_were_unreadable_is_cleared_when_the_counts_come(proc):
    """The journal MERGES updates: a ``ws_why`` written while the holder could not be read would stay beside the counts that followed."""
    (proc.dir / "stat").unlink()
    _look(10.0, 100.0)
    assert hs.fields_for(10.0) == {"ws": None, "ws_why": hs.GONE}
    proc.put("S", "futex_do_wait")
    _look(10.0, 101.0)  # a baseline: nothing is counted yet, and the journal is told so rather than left holding a reason that is over
    assert hs.fields_for(10.0) == {"ws": None, "ws_why": hs.NOT_RECORDED}
    proc.put("S", "futex_do_wait")
    _look(10.0, 102.0)
    assert hs.fields_for(10.0) == {"ws": [0, 0, 1, 0, 0, 0], "gap": 1.0, "ws_why": None}


# --------------------------------------------------------------------------- #
#  What never reaches the journal
# --------------------------------------------------------------------------- #
def test_the_threads_name_the_kernel_symbol_and_an_errors_text_are_never_in_the_fields(proc, monkeypatch):
    proc.put("S", f"futex_{MARKER}", comm=MARKER)
    _look(10.0, 100.0)
    proc.put("S", f"futex_{MARKER}", comm=MARKER)
    _look(10.0, 101.0)
    assert MARKER not in json.dumps(hs.fields_for(10.0)), "the name and the symbol classify and are not kept"

    def refuse(path):
        raise OSError(13, f"Permission denied: '{path}' {MARKER}")

    monkeypatch.setattr(hs, "_read", refuse)
    _look(10.0, 102.0)
    f = hs.fields_for(10.0)
    assert MARKER not in json.dumps(f) and "Permission" not in json.dumps(f)
    hs.forget()
    _look(20.0, 103.0)
    assert hs.fields_for(20.0) == {"ws": None, "ws_why": hs.UNREADABLE}, "a fixed reason, not the error"


# --------------------------------------------------------------------------- #
#  The real kernel
# --------------------------------------------------------------------------- #
def _wchan_readable() -> bool:
    ev = threading.Event()
    box: list[int] = []

    def sleeper() -> None:
        box.append(threading.get_native_id())
        ev.wait(2)

    t = threading.Thread(target=sleeper, daemon=True)
    t.start()
    time.sleep(0.15)
    try:
        with open(f"/proc/self/task/{box[0]}/wchan", "rb") as f:
            return f.read().strip() not in (b"", b"0")
    except OSError:
        return False
    finally:
        ev.set()
        t.join(2)


live = pytest.mark.skipif(not LINUX or not Path("/proc/self/task").is_dir(), reason="needs Linux's /proc")


def _looks_at_a_thread(target, looks: int = 6, every: float = 0.12) -> dict:
    stop = threading.Event()
    ready = threading.Event()

    def run() -> None:
        ready.set()
        target(stop)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    ready.wait(2)
    time.sleep(0.1)
    hs.forget()
    started = time.monotonic()
    try:
        for _ in range(looks):
            hs.look(started, t.ident, time.monotonic())
            time.sleep(every)
        return hs.fields_for(started)
    finally:
        stop.set()
        t.join(3)
        hs.forget()


@live
def test_a_thread_waiting_on_a_lock_is_counted_futex_on_the_real_kernel():
    if not _wchan_readable():
        pytest.skip("this kernel does not show wchan")
    f = _looks_at_a_thread(lambda stop: stop.wait(5))
    assert f["ws"][hs.CLASSES.index("futex")] >= 4, f
    assert f["ws"][hs.CLASSES.index("nap")] == 0 and f["ws"][hs.CLASSES.index("disk")] == 0, f


@live
def test_a_thread_in_time_sleep_is_counted_nap_on_the_real_kernel():
    if not _wchan_readable():
        pytest.skip("this kernel does not show wchan")
    f = _looks_at_a_thread(lambda stop: time.sleep(2))
    assert f["ws"][hs.CLASSES.index("nap")] >= 4, f
    assert f["ws"][hs.CLASSES.index("futex")] == 0, f


@live
def test_a_thread_computing_outside_the_gil_is_counted_running_or_runnable_on_the_real_kernel():
    """SQLite's work inside a statement is this case: the GIL is released, the thread is on a CPU (or waiting for one)."""
    import hashlib

    def compute(stop: threading.Event) -> None:
        h, block = hashlib.sha256(), b"x" * 8_000_000  # hashlib drops the GIL for data of this size
        while not stop.is_set():
            h.update(block)

    f = _looks_at_a_thread(compute)
    busy = f["ws"][hs.CLASSES.index("running")] + f["ws"][hs.CLASSES.index("runnable")]
    assert busy >= 4, f
    assert f["ws"][hs.CLASSES.index("nap")] == 0 and f["ws"][hs.CLASSES.index("disk")] == 0, f


@live
def test_a_thread_computing_in_python_is_never_counted_asleep_and_futex_is_only_a_floor_for_gil_waits():
    """The limit the module states: each read the look makes gives the GIL up, so a holder that is the ONLY thread waiting for it is handed it
    and read running. A pure-Python spinner beside the look therefore reads running, not futex; what must hold is that it is never a nap or a
    disk wait. Pinned so the method's reading of ``futex`` (a floor) cannot drift into a claim."""

    def spin(stop: threading.Event) -> None:
        n = 0
        while not stop.is_set():
            n += 1

    f = _looks_at_a_thread(spin)
    ws = dict(zip(hs.CLASSES, f["ws"], strict=True))
    assert ws["running"] + ws["runnable"] + ws["futex"] >= 4 and ws["nap"] == 0 and ws["disk"] == 0, f


# --------------------------------------------------------------------------- #
#  The seams in the write gate
# --------------------------------------------------------------------------- #
def _hold_the_gate(gate: writer.WriterGate, name: str = "oo-collect_3"):
    """Take the gate on a thread; returns (release event, thread). The gate's holder ident is that thread's."""
    taken, let_go = threading.Event(), threading.Event()

    def hold() -> None:
        gate.acquire()
        taken.set()
        let_go.wait(10)
        gate.release()

    t = threading.Thread(target=hold, name=name, daemon=True)
    t.start()
    assert taken.wait(3)
    return let_go, t


@pytest.mark.usefixtures("journal")
def test_a_long_hold_carries_the_holders_counts_in_the_journal_and_the_looks_up_to_the_release(proc, monkeypatch):
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    gate = writer.WriterGate()
    let_go, t = _hold_the_gate(gate)
    time.sleep(0.1)
    _holder, started, _ident = gate._holder_snapshot()
    assert started is not None
    assert writer.sample_holder_state(gate) is False, "a hold the journal does not have yet is not looked at: the full tick opens the entry first"
    writer.watchdog_tick(gate, None)
    proc.put("S", "futex_do_wait")
    assert writer.sample_holder_state(gate, now=started + 1.0) is True, "the baseline"
    for i in range(1, 4):
        proc.put("S", "futex_do_wait")
        writer.sample_holder_state(gate, now=started + 1.0 + i)
    writer.watchdog_tick(gate, started)  # the 15-second tick carries the counts so far
    (event,) = _events("gate_hold")
    assert event["ws"] == [0, 0, 3, 0, 0, 0] and event["gap"] == 1.0 and event["open"] is True
    for i in range(4, 6):  # two looks after that tick, before the release
        proc.put("S", "hrtimer_nanosleep")
        writer.sample_holder_state(gate, now=started + 1.0 + i)
    let_go.set()
    t.join(5)
    (event,) = _events("gate_hold")
    assert event["open"] is False
    assert event["ws"] == [0, 0, 3, 2, 0, 0], "the release carries the looks taken after the last tick, not the tick's count"


@pytest.mark.usefixtures("journal")
def test_the_gate_going_free_drops_the_counts_so_the_next_hold_starts_from_none(proc, monkeypatch):
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    gate = writer.WriterGate()
    let_go, t = _hold_the_gate(gate)
    time.sleep(0.1)
    writer.watchdog_tick(gate, None)
    _h, started, _i = gate._holder_snapshot()
    writer.sample_holder_state(gate, now=started + 1.0)
    proc.put("S", "futex_do_wait")
    writer.sample_holder_state(gate, now=started + 2.0)
    assert hs.fields_for(started)["ws"] == [0, 0, 1, 0, 0, 0], "anti-vacuity: there are counts to forget"
    let_go.set()
    t.join(5)
    assert hs.fields_for(started) != {}, "the release does not drop them: the watchdog does, at its next look"
    assert writer.sample_holder_state(gate) is False
    assert hs.fields_for(started) == {}, "free gate: forgotten"


@pytest.mark.usefixtures("journal")
def test_a_short_hold_is_never_looked_at(proc):
    """The journal keeps holds of HOLD_RECORD_S or more: below it nothing runs."""
    gate = writer.WriterGate()  # HOLD_RECORD_S is 30 s
    let_go, t = _hold_the_gate(gate)
    writer.watchdog_tick(gate, None)
    assert writer.sample_holder_state(gate) is False
    assert hs.fields_for(gate._holder_snapshot()[1]) == {}
    let_go.set()
    t.join(5)


@pytest.mark.usefixtures("journal")
def test_a_hold_on_a_platform_without_proc_is_journaled_with_the_reason_and_not_looked_at_again(proc, monkeypatch):
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    monkeypatch.setattr(hs, "_PLATFORM", "darwin")
    gate = writer.WriterGate()
    let_go, t = _hold_the_gate(gate)
    time.sleep(0.1)
    writer.watchdog_tick(gate, None)
    assert writer.sample_holder_state(gate) is False
    writer.watchdog_tick(gate, gate._holder_snapshot()[1])
    (event,) = _events("gate_hold")
    assert (event["ws"], event["ws_why"]) == (None, hs.UNSUPPORTED)
    let_go.set()
    t.join(5)


@pytest.mark.usefixtures("journal")
def test_a_failing_sampler_never_raises_into_the_watchdog(proc, monkeypatch):
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)

    def boom(*_a):
        raise RuntimeError(f"cannot look {MARKER}")

    monkeypatch.setattr(hs, "look", boom)
    gate = writer.WriterGate()
    let_go, t = _hold_the_gate(gate)
    time.sleep(0.1)
    writer.watchdog_tick(gate, None)
    assert writer.sample_holder_state(gate) is False
    let_go.set()
    t.join(5)


@pytest.mark.usefixtures("journal")
def test_the_member_names_a_hold_without_the_holders_state_and_never_shows_zeros():
    se.record("gate_hold", {"holder": "old", "seconds": 40.0}, key=("hold", 1))  # written by a build without the field, or ended before the second look
    se.record("gate_hold", {"holder": "new", "seconds": 50.0, "ws": [1, 2, 3, 4, 5, 6], "gap": 1.1}, key=("hold", 2))
    se.record("gate_hold", {"holder": "win", "seconds": 60.0, "ws": None, "ws_why": hs.UNSUPPORTED}, key=("hold", 3))
    holds = {e["holder"]: e for e in _events("gate_hold")}
    assert (holds["old"]["ws"], holds["old"]["ws_why"]) == (None, hs.NOT_RECORDED)
    assert holds["new"]["ws"] == [1, 2, 3, 4, 5, 6] and "ws_why" not in holds["new"]
    assert (holds["win"]["ws"], holds["win"]["ws_why"]) == (None, hs.UNSUPPORTED)


# --------------------------------------------------------------------------- #
#  The pace of the looks
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("due", "now", "looking", "expected"),
    [
        (15.0, 0.0, False, 15.0),  # idle: the full tick's own pace, nothing else wakes
        (15.0, 0.0, True, writer.HOLD_LOOK_S),  # a long hold: one look a second
        (0.4, 0.0, True, 0.4),  # the full tick comes first
        (0.0, 1.0, True, 0.0),  # overdue
        (0.0, 1.0, False, 0.0),
    ],
)
def test_the_watchdog_sleeps_until_the_full_tick_or_the_next_look_whichever_is_first(due, now, looking, expected):
    assert writer._next_wait_s(15.0, due, now, looking) == expected


@pytest.mark.usefixtures("journal")
def test_the_watchdog_loop_looks_every_second_of_a_long_hold_and_ticks_at_its_own_pace(proc, monkeypatch):
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    monkeypatch.setattr(writer, "HOLD_LOOK_S", 0.02)
    monkeypatch.setenv("OO_WRITE_GATE_WATCH_INTERVAL_S", "0.5")
    gate = writer.WriterGate()
    monkeypatch.setattr(writer, "write_gate", gate)
    ticks: list[float] = []
    real_tick = writer.watchdog_tick
    monkeypatch.setattr(writer, "watchdog_tick", lambda g, w: (ticks.append(time.monotonic()), real_tick(g, w))[1])
    proc.put("S", "futex_do_wait")
    let_go, t = _hold_the_gate(gate)
    stop = threading.Event()
    loop = threading.Thread(target=writer._watchdog_loop, args=(stop,), daemon=True)
    loop.start()
    time.sleep(1.8)
    stop.set()
    loop.join(3)
    let_go.set()
    t.join(5)
    (event,) = _events("gate_hold")
    looks = sum(event["ws"])
    assert looks >= 20, f"one look every 0.02 s for most of 1.8 s, not one every 0.5 s: {event['ws']}"
    assert 2 <= len(ticks) <= 5, f"the full tick stayed at its 0.5 s pace: {len(ticks)} ticks"


# --------------------------------------------------------------------------- #
#  The width of a frame: a measured maximum, pinned against every function under src/
# --------------------------------------------------------------------------- #
def _longest_frames() -> list[tuple[int, str]]:
    """Every ``module:function:line`` string a frame of app code can produce, at its widest line number (the digits of the file's last line),
    longest first. Names are every function, class, lambda and comprehension scope in every module under ``src/``."""
    root = Path(__file__).resolve().parents[1]
    found: list[tuple[int, str]] = []
    for path in sorted((root / "src").rglob("*.py")):
        parts = list(path.relative_to(root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(parts)
        text = path.read_text(encoding="utf-8")
        digits = len(str(text.count("\n") + 1))
        names = {"<module>", "<lambda>", "<genexpr>", "<listcomp>", "<dictcomp>", "<setcomp>"}
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
        for name in names:
            frame = f"{module}:{name}:{'9' * digits}"
            found.append((len(frame), frame))
    found.sort(reverse=True)
    return found


def test_no_function_under_src_can_produce_a_frame_wider_than_the_width_the_budget_counts():
    """``writer.FRAME_CHARS`` is what ``storage_events``' budget counts each of a hold's three frames at (the journal's own cut is 160, which
    no frame reaches). It is a MEASURED MAXIMUM: this walks every module, so a new function with a longer name than the budget assumes fails
    HERE, with the name, and the fix is to raise ``FRAME_CHARS`` and re-measure the slot with ``test_the_storage_events_budget_holds_a_full_journal``."""
    found = _longest_frames()
    assert len(found) > 5_000, f"the walk saw only {len(found)} names: it is not looking at src/"
    widest, name = found[0]
    assert widest >= 60, f"the walk found nothing longer than {widest} ({name}): it is not measuring the names"
    too_wide = [f"{n} ({w})" for w, n in found if w > writer.FRAME_CHARS]
    assert not too_wide, f"frames wider than FRAME_CHARS={writer.FRAME_CHARS}, which the storage-events budget counts: {too_wide[:5]}"


def test_a_frame_exactly_as_wide_as_the_budget_is_whole_and_one_character_wider_is_cut_and_says_so():
    module = "src.fake_module_for_the_frame_test"
    # ``f_lineno`` of the call is line 2 of the source below: one digit.
    exact_name = "f" * (writer.FRAME_CHARS - len(module) - len(":") - len(":2"))
    for name, whole in ((exact_name, True), (exact_name + "g", False)):
        ns: dict = {"__name__": module, "_app_frames": writer._app_frames, "threading": threading}
        exec(compile(f"def {name}():\n    return _app_frames(threading.get_ident(), 1)\n", "<frame-test>", "exec"), ns)  # noqa: S102 - test fixture
        (frame,) = ns[name]()
        assert len(frame) == writer.FRAME_CHARS
        assert frame.endswith(":2") == whole, frame
        assert frame.endswith("…") == (not whole), "a cut frame ends in the journal's own ellipsis, so it is never mistaken for a whole name"
