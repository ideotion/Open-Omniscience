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
import logging
import re
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
        (self.dir / "stat").write_text(f"{self.tid} ({comm}) {state} 1 1 1 0 -1 4194560 100 0 0 0 5 1 0 0 20 0 1 0 100 1000 100\n", encoding="utf-8")
        (self.dir / "wchan").write_text(wchan, encoding="utf-8")
        sched_file = self.dir / "schedstat"
        if sched:
            sched_file.write_text(f"{self.cpu_ns} {self.wait_ns} 7\n", encoding="utf-8")
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
    ("state", "wchan", "expected"),
    [
        ("R", "0", "run"),
        ("R", "", "run"),  # a thread on a CPU has no wait to name
        ("S", "futex_do_wait", "futex"),
        ("S", "futex_wait_queue", "futex"),
        ("S", "hrtimer_nanosleep", "nap"),
        ("S", "do_nanosleep", "nap"),
        ("S", "do_epoll_wait", "other"),  # a wait the kernel NAMED, and not one of ours
        ("S", "pipe_read", "other"),
        ("S", "poll_schedule_timeout.constprop.0", "other"),
        ("S", "0", "unknown"),  # a sleep the kernel printed nothing for
        ("S", "", "unknown"),  # a sleep whose wchan cannot be read
        ("I", "0", "unknown"),
        ("I", "worker_thread", "other"),
        ("D", "io_schedule", "disk"),
        ("D", "0", "disk"),  # the state decides: a disk wait is a disk wait whatever the symbol
        ("D", "", "disk"),
        ("T", "do_signal_stop", "other"),
        ("T", "0", "other"),  # unknown is a SLEEP the kernel did not name, not any state with no symbol
        ("Z", "0", "other"),
    ],
)
def test_each_kernel_state_is_counted_in_its_own_class_and_no_other(state, wchan, expected):
    assert hs.classify(state, wchan) == expected


def test_a_wchan_that_names_a_wait_is_that_wait_whatever_the_state_read_after_it_says():
    """The kernel prints a symbol only for a thread blocked in the kernel when it is read, and the look reads the wchan FIRST: a state letter
    read after it (R, because the look's own reads gave the GIL up and woke the thread) does not undo the wait that was seen."""
    assert hs.classify("R", "futex_do_wait") == "futex"
    assert hs.classify("R", "hrtimer_nanosleep") == "nap"
    assert hs.classify("R", "0") == "run", "the same R with no symbol is what it says"
    assert hs.classify("D", "io_schedule") == "disk", "a symbol that is not one of the two waits leaves the state to decide"


def test_the_wait_is_read_before_the_state_so_a_holder_the_look_wakes_is_still_read_asleep(proc, monkeypatch):
    """Every file the look reads gives the GIL up, and a holder waiting for the GIL is woken by that: asleep at the first read, awake at the
    second. Scripted here exactly so: the first file of each look is read with the thread asleep on a futex, every later one with it running.
    Read ``stat`` first and the look is S then 0 and lands in ``unknown`` (29 per cent of the looks of a holder beside three spinners)."""
    asleep = {"wchan": b"futex_do_wait", "stat": b"4242 (python) S 1 1 1 0\n"}
    awake = {"wchan": b"0", "stat": b"4242 (python) R 1 1 1 0\n", "schedstat": b"9000000 0 7\n"}
    order: list[str] = []

    def read(path):
        name = Path(path).name
        order.append(name)
        return asleep[name] if len(order) == 1 else awake[name]

    monkeypatch.setattr(hs, "_read", read)
    for at in (100.0, 101.0, 102.0):
        order.clear()
        _look(10.0, at)
        assert order[0] == "wchan", order
    assert hs.fields_for(10.0)["ws"] == [0, 2, 0, 0, 0, 0], "the two looks that count are futex waits: the thread was asleep when the look began"


def test_the_classes_are_six_and_in_the_order_the_journal_writes_them():
    assert hs.CLASSES == ("run", "futex", "nap", "disk", "other", "unknown")


def test_the_state_is_read_after_the_last_parenthesis():
    """The kernel writes the thread's name between parentheses and it may hold any character, ``)`` and a state letter among them."""
    assert hs._state_of(b"4242 (python) S 1 1 1 0") == "S"
    assert hs._state_of(b"4242 (evil) R 1 (x) D 1 1 1 0") == "D"
    assert hs._state_of(b"4242 (a b) c) T 1 1") == "T"
    assert hs._state_of(b"4242 (python)") is None
    assert hs._state_of(b"4242 (python) 7 1") is None, "a digit is not a state"
    assert hs._state_of(b"") is None
    assert hs._state_of(b"4242 (pyth") is None, "a line cut inside the name"
    assert hs._state_of(b"python S 1 1") is None, "no closing parenthesis: not a stat line, so its first letter is not a state"
    assert hs._state_of(b"S") is None


# --------------------------------------------------------------------------- #
#  Counting one hold
# --------------------------------------------------------------------------- #
def test_the_first_look_of_a_hold_counts_nothing_and_the_second_counts_one(proc):
    proc.put("S", "futex_do_wait")
    assert _look(10.0, 100.0) is True
    assert hs.fields_for(10.0) == {}, "the first look is the baseline: no count, no gap, no reason"
    proc.put("S", "futex_do_wait")
    assert _look(10.0, 101.0) is True
    assert hs.fields_for(10.0) == {"ws": [0, 1, 0, 0, 0, 0], "gap": 1.0, "rq": 0.0}, "both looks read the scheduler's total and it did not move: a measured zero"


def test_every_class_is_counted_where_it_belongs_over_a_run_of_looks(proc):
    proc.put("S", "futex_do_wait")
    _look(10.0, 100.0)  # baseline
    script = [
        ("S", "futex_do_wait", 0),
        ("S", "futex_wait_queue", 0),
        ("S", "futex_do_wait", 0),
        ("S", "hrtimer_nanosleep", 0),
        ("S", "hrtimer_nanosleep", 0),
        ("D", "io_schedule", 0),
        ("R", "0", 10_000_000),
        ("R", "0", 20_000_000),
        ("R", "0", 700_000_000),
        ("S", "do_epoll_wait", 0),
        ("S", "0", 0),
        ("S", "0", 0),
    ]
    for i, (state, wchan, waited) in enumerate(script, start=1):
        proc.put(state, wchan, waited_ns=waited)
        _look(10.0, 100.0 + i)
    assert hs.fields_for(10.0) == {"ws": [3, 3, 2, 1, 1, 2], "gap": 1.0, "rq": 0.7}, (
        "three runs, whatever each waited for a CPU; the time they waited (10 + 20 + 700 ms) is rq, not a count"
    )


def test_gap_is_the_longest_time_between_two_looks_that_could_be_read(proc):
    _look(10.0, 100.0)
    for at in (101.0, 102.1, 102.4):
        proc.put("S", "futex_do_wait")
        _look(10.0, at)
    assert hs.fields_for(10.0)["gap"] == 1.1
    # An unreadable look is not a look: the time it covered shows in the next gap, so a starved process and a vanished file read alike.
    (proc.dir / "stat").unlink()
    assert _look(10.0, 103.0) is True
    (proc.dir / "stat").write_text("4242 (python) S 1\n", encoding="utf-8")
    _look(10.0, 106.4)
    assert hs.fields_for(10.0)["gap"] == 4.0, "from the last look that was read (102.4) to the next (106.4)"


def test_a_running_look_with_no_scheduler_figures_is_still_run_and_rq_is_null_never_zero(proc):
    proc.put("R", "0", sched=False)
    _look(10.0, 100.0)
    proc.put("R", "0", sched=False)
    _look(10.0, 101.0)
    f = hs.fields_for(10.0)
    assert f["ws"] == [1, 0, 0, 0, 0, 0] and f["rq"] is None, f
    assert json.dumps(f["rq"]) == "null", "unreadable is null in the journal, not 0.0 (which would say the thread never waited)"


def test_a_sleep_whose_wchan_cannot_be_read_is_unknown_not_a_guess(proc):
    proc.put("S", "futex_do_wait")
    _look(10.0, 100.0)
    proc.put("S", "futex_do_wait")
    proc.wchan_unreadable()
    _look(10.0, 101.0)
    assert hs.fields_for(10.0)["ws"] == [0, 0, 0, 0, 0, 1]


def test_rq_is_the_scheduler_total_from_the_first_look_that_read_it_to_the_last_and_to_a_tenth_of_a_second(proc):
    proc.put("S", "futex_do_wait")
    _look(10.0, 100.0)  # the first look: where rq starts
    proc.put("S", "futex_do_wait", waited_ns=149_000_000)
    _look(10.0, 101.0)
    assert hs.fields_for(10.0)["rq"] == 0.1, "149 ms to a tenth: 0.1"
    proc.put("S", "futex_do_wait", waited_ns=2_000_000_000)
    _look(10.0, 102.0)
    assert hs.fields_for(10.0)["rq"] == 2.1, "2.149 s: 2.1"


def test_rq_spans_looks_that_could_not_read_the_total_and_needs_two_that_could(proc):
    """Only the first and last reading of the total matter, so a look in between that cannot read it costs nothing; ONE reading is not a span."""
    proc.put("S", "futex_do_wait")
    _look(10.0, 100.0)
    proc.put("S", "futex_do_wait", waited_ns=500_000_000, sched=False)  # the middle look cannot read it
    _look(10.0, 101.0)
    f = hs.fields_for(10.0)
    assert f["ws"] == [0, 1, 0, 0, 0, 0] and f["rq"] is None, "one reading of the total: no span, null, not 0"
    proc.put("S", "futex_do_wait", waited_ns=900_000_000)
    _look(10.0, 102.0)
    assert hs.fields_for(10.0)["rq"] == 1.4, "first look to last: 500 + 900 ms of waiting, the unreadable look's share included"


@pytest.mark.parametrize(
    "stat",
    [b"4242 (pyth", b"4242 (python)", b"python S 1 1", b"", b"4242 (python) 7 1"],
    ids=["cut-in-the-name", "cut-after-the-name", "no-closing-parenthesis", "empty", "no-state-letter"],
)
def test_a_look_whose_state_cannot_be_read_is_left_uncounted_with_its_cause_never_classified(proc, stat):
    """The state is what decides every class the symbol did not, so a state that cannot be read must not fall through to ``other`` (or any
    class): the look is not counted, and the hold says ``proc-unreadable``. A baseline is taken first so the next look WOULD count."""
    proc.put("S", "futex_do_wait")
    _look(10.0, 100.0)
    (proc.dir / "stat").write_bytes(stat)
    (proc.dir / "wchan").write_text("futex_do_wait", encoding="utf-8")
    _look(10.0, 101.0)
    assert sum(hs._CURRENT.counts) == 0, "not counted in any class"
    assert hs.fields_for(10.0) == {"ws": None, "ws_why": hs.UNREADABLE}


def test_a_new_hold_starts_from_none_and_the_old_one_is_not_credited(proc):
    _look(10.0, 100.0)
    proc.put("S", "futex_do_wait")
    _look(10.0, 101.0)
    assert hs.fields_for(10.0)["ws"] == [0, 1, 0, 0, 0, 0]
    _look(55.0, 102.0)  # another hold
    assert hs.fields_for(55.0) == {}, "its own baseline, none of the old hold's counts"
    proc.put("D", "io_schedule")
    _look(55.0, 103.0)
    assert hs.fields_for(55.0) == {"ws": [0, 0, 0, 1, 0, 0], "gap": 1.0, "rq": 0.0}
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


def test_forgetting_one_hold_leaves_another_alone(proc):
    """The thread that released a gate forgets ITS hold after it read the counts; a newer hold the watchdog has begun to look at is not its to drop."""
    _look(10.0, 100.0)
    proc.put("S", "futex_do_wait")
    _look(10.0, 101.0)
    hs.forget(55.0)
    assert hs.fields_for(10.0)["ws"] == [0, 1, 0, 0, 0, 0], "another hold's forget"
    hs.forget(10.0)
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
    assert hs.fields_for(10.0) == {"ws": [0, 1, 0, 0, 0, 0], "gap": 1.0, "rq": 0.0, "ws_why": None}


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
def test_a_thread_computing_outside_the_gil_is_counted_run_on_the_real_kernel():
    """SQLite's work inside a statement is this case: the GIL is released, the thread is on a CPU (or waiting for one)."""
    import hashlib

    def compute(stop: threading.Event) -> None:
        h, block = hashlib.sha256(), b"x" * 8_000_000  # hashlib drops the GIL for data of this size
        while not stop.is_set():
            h.update(block)

    f = _looks_at_a_thread(compute)
    assert f["ws"][hs.CLASSES.index("run")] >= 4, f
    assert f["ws"][hs.CLASSES.index("nap")] == 0 and f["ws"][hs.CLASSES.index("disk")] == 0, f


@live
def test_a_thread_computing_in_python_is_never_counted_asleep_and_futex_is_only_a_floor_for_gil_waits():
    """The limit the module states: each read the look makes gives the GIL up, so a holder that is the ONLY thread waiting for it is handed it
    and read running. A pure-Python spinner beside the look therefore reads run, not futex; what must hold is that it is never a nap or a
    disk wait. Pinned so the method's reading of ``futex`` (a floor) cannot drift into a claim."""

    def spin(stop: threading.Event) -> None:
        n = 0
        while not stop.is_set():
            n += 1

    f = _looks_at_a_thread(spin)
    ws = dict(zip(hs.CLASSES, f["ws"], strict=True))
    assert ws["run"] + ws["futex"] >= 4 and ws["nap"] == 0 and ws["disk"] == 0, f


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
    assert event["ws"] == [0, 3, 0, 0, 0, 0] and event["gap"] == 1.0 and event["rq"] == 0.0 and event["open"] is True
    for i in range(4, 6):  # two looks after that tick, before the release
        proc.put("S", "hrtimer_nanosleep")
        writer.sample_holder_state(gate, now=started + 1.0 + i)
    let_go.set()
    t.join(5)
    (event,) = _events("gate_hold")
    assert event["open"] is False
    assert event["ws"] == [0, 3, 2, 0, 0, 0], "the release carries the looks taken after the last tick, not the tick's count"


@pytest.mark.usefixtures("journal")
def test_a_watchdog_look_on_the_free_gate_leaves_the_counts_for_the_release_to_read_and_the_release_forgets_them(proc, monkeypatch):
    """The release frees the gate and THEN reads the holder's counts (after the long-release log, the thread numbers and the memory read). A
    watchdog look that lands in that window sees a free gate; it used to drop the counts, so the end carried the last 15-second sample's
    (up to 15 s of looks missing, or none: 'not-recorded') on about one look in eight under four busy threads. Forced here: the watchdog's look
    is run on the releasing thread in that window."""
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    gate = writer.WriterGate()
    let_go, t = _hold_the_gate(gate)
    time.sleep(0.1)
    writer.watchdog_tick(gate, None)
    _h, started, _i = gate._holder_snapshot()
    writer.sample_holder_state(gate, now=started + 1.0)
    for i in range(1, 4):
        proc.put("S", "futex_do_wait")
        writer.sample_holder_state(gate, now=started + 1.0 + i)
    writer.watchdog_tick(gate, started)  # the tick carries three looks
    for i in range(4, 6):
        proc.put("S", "hrtimer_nanosleep")
        writer.sample_holder_state(gate, now=started + 1.0 + i)
    window: list[bool] = []
    real_memory = writer._memory_numbers

    def memory_and_a_look_on_the_free_gate():
        window.append(gate._holder_snapshot()[1] is None)  # the gate is free here
        window.append(writer.sample_holder_state(gate) is False)  # the watchdog's look finds it free
        return real_memory()

    monkeypatch.setattr(writer, "_memory_numbers", memory_and_a_look_on_the_free_gate)
    let_go.set()
    t.join(5)
    assert window == [True, True], "anti-vacuity: the look did land in the window, on a free gate"
    (event,) = _events("gate_hold")
    assert event["open"] is False
    assert event["ws"] == [0, 3, 2, 0, 0, 0], "all five looks, not the tick's three"
    assert hs.fields_for(started) == {}, "the releasing thread forgot its hold after it had read it"


@pytest.mark.usefixtures("journal")
def test_the_release_forgets_only_its_own_hold(proc, monkeypatch):
    """A newer hold the watchdog is already looking at is not the releasing thread's to drop, and an end with no start time forgets nothing."""
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    gate = writer.WriterGate()
    let_go, t = _hold_the_gate(gate)
    time.sleep(0.1)
    writer.watchdog_tick(gate, None)
    _h, started, _i = gate._holder_snapshot()
    real_memory = writer._memory_numbers

    def memory_while_a_newer_hold_is_looked_at():
        _look(started + 500.0, 100.0)  # another hold, taken up by the watchdog between the release and this read
        return real_memory()

    monkeypatch.setattr(writer, "_memory_numbers", memory_while_a_newer_hold_is_looked_at)
    let_go.set()
    t.join(5)
    assert hs._CURRENT is not None and hs._CURRENT.started == started + 500.0
    writer._note_hold_end("oo-collect_3", 40.0, None)  # an end that never knew its start
    assert hs._CURRENT is not None and hs._CURRENT.started == started + 500.0, "forget(None) would have dropped whatever is kept"


@pytest.mark.usefixtures("journal")
def test_a_hold_that_ended_before_the_next_tick_still_carries_the_looks_it_was_given(proc, monkeypatch):
    """The other outcome of the same race: the tick had not yet written any counts, and the end said 'not-recorded' for a hold that had been looked at."""
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    gate = writer.WriterGate()
    let_go, t = _hold_the_gate(gate)
    time.sleep(0.1)
    writer.watchdog_tick(gate, None)
    _h, started, _i = gate._holder_snapshot()
    writer.sample_holder_state(gate, now=started + 1.0)
    proc.put("S", "futex_do_wait")
    writer.sample_holder_state(gate, now=started + 2.0)
    real_memory = writer._memory_numbers
    monkeypatch.setattr(writer, "_memory_numbers", lambda: (writer.sample_holder_state(gate), real_memory())[1])
    let_go.set()
    t.join(5)
    (event,) = _events("gate_hold")
    assert event["ws"] == [0, 1, 0, 0, 0, 0] and event.get("ws_why") is None


@pytest.mark.usefixtures("journal")
def test_the_looks_stop_when_the_gate_is_free_and_touch_nothing(proc, monkeypatch):
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    gate = writer.WriterGate()
    let_go, t = _hold_the_gate(gate)
    time.sleep(0.1)
    writer.watchdog_tick(gate, None)
    _h, started, _i = gate._holder_snapshot()
    writer.sample_holder_state(gate, now=started + 1.0)
    proc.put("S", "futex_do_wait")
    writer.sample_holder_state(gate, now=started + 2.0)
    let_go.set()
    t.join(5)
    assert writer.sample_holder_state(gate) is False
    assert hs._CURRENT is None, "the releasing thread forgot; a look on the free gate neither made nor kept anything"


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
def test_a_failing_sampler_never_raises_into_the_watchdog_and_says_so_once_in_the_log(proc, monkeypatch, caplog):
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)

    def boom(*_a):
        raise RuntimeError("cannot look")

    monkeypatch.setattr(hs, "look", boom)
    gate = writer.WriterGate()
    let_go, t = _hold_the_gate(gate)
    time.sleep(0.1)
    writer.watchdog_tick(gate, None)
    with caplog.at_level(logging.DEBUG, logger=writer._LOG.name):
        assert writer.sample_holder_state(gate) is False
    let_go.set()
    t.join(5)
    lines = [r.getMessage() for r in caplog.records if "holder state could not be sampled" in r.getMessage()]
    assert len(lines) == 1 and "RuntimeError" in lines[0], lines


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


class _SteppedClock:
    """A monotonic clock that moves only when the watchdog loop WAITS, and the ``stop`` the loop waits on: ``wait(t)`` advances the clock by ``t`` and
    returns False (not stopped), until the next wait would cross ``run_for`` seconds or ``max_waits`` waits were made, and then returns True (stopped).

    The loop used to run on a real thread for a fixed 1.7 s and the tests counted its calls in that window, so a stall of the thread on a loaded runner
    changed the count: the same assertion read ``1 >= 3`` on CI and passed locally. A 0.68 s stall of the first tick reproduces that exact failure, and
    so does a first tick that fails to open the journal entry the looks need. On this clock the loop runs to the end on the calling thread, a stall is
    not a thing that can happen, and the counts are the loop's own. ``max_waits`` ends a loop that spins (waits of zero never move the clock) so that
    the old bug fails an assertion by name instead of hanging the test."""

    def __init__(self, start: float, run_for: float, max_waits: int = 5000) -> None:
        self.start, self.now, self.run_for, self.max_waits = start, start, run_for, max_waits
        self.waits = 0

    def wait(self, timeout: float | None = None) -> bool:
        step = 0.0 if timeout is None else timeout
        if self.waits >= self.max_waits or self.now + step > self.start + self.run_for + 1e-9:
            return True
        self.waits += 1
        self.now += step
        return False

    def elapsed(self) -> float:
        return self.now - self.start


class _ClockedTime:
    """``writer.time`` for the length of a test: the module's own ``time.monotonic()`` reads the stepped clock, everything else is the real ``time``."""

    def __init__(self, clock: _SteppedClock) -> None:
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock.now

    def __getattr__(self, name: str):
        return getattr(time, name)


def _run_the_loop_over_a_long_hold(monkeypatch, seconds: float = 1.8, tick=None, look=None) -> list[tuple[str, float]]:
    """The watchdog's own loop on a gate held for ``seconds`` of simulated time: a 0.5 s full tick, a look every 0.02 s. Returns what the loop called,
    in order, as ``("tick" | "look", simulated seconds since the start)``. ``tick`` and ``look`` replace the real ones (each is still recorded)."""
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    monkeypatch.setattr(writer, "HOLD_LOOK_S", 0.02)
    monkeypatch.setenv("OO_WRITE_GATE_WATCH_INTERVAL_S", "0.5")
    gate = writer.WriterGate()
    monkeypatch.setattr(writer, "write_gate", gate)
    let_go, t = _hold_the_gate(gate)
    clock = _SteppedClock(time.monotonic(), seconds)
    monkeypatch.setattr(writer, "time", _ClockedTime(clock))
    calls: list[tuple[str, float]] = []
    real_tick, real_look = writer.watchdog_tick, writer.sample_holder_state
    # Only THIS thread runs the loop. The module's names are patched for every thread, and the process's own watchdog (armed by the first hold of the
    # whole run, a tick every 15 s) resolves them at call time: one of its wakes inside the ~50 ms this simulation takes was recorded as a tick of
    # the loop at the simulated time it landed on (ticks [0.5, 1.0, 1.5, 1.68] on a Core-only run). Any other thread gets the no-op a gate with
    # nothing to report returns, as tests/test_write_gate_phase.py's journal fixture does.
    me = threading.get_ident()

    def recorded_tick(g, w):
        if threading.get_ident() != me:
            return w
        calls.append(("tick", clock.elapsed()))
        return (tick or real_tick)(g, w)

    def recorded_look(g, now=None):
        if threading.get_ident() != me:
            return False
        calls.append(("look", clock.elapsed()))
        return (look or real_look)(g, now)

    monkeypatch.setattr(writer, "watchdog_tick", recorded_tick)
    monkeypatch.setattr(writer, "sample_holder_state", recorded_look)
    try:
        writer._watchdog_loop(clock)
    finally:
        let_go.set()
        t.join(5)
    return calls


def _at(calls: list[tuple[str, float]], what: str) -> list[float]:
    return [at for kind, at in calls if kind == what]


@pytest.mark.usefixtures("journal")
def test_the_watchdog_loop_looks_every_second_of_a_long_hold_and_ticks_at_its_own_pace(proc, monkeypatch):
    proc.put("S", "futex_do_wait")
    calls = _run_the_loop_over_a_long_hold(monkeypatch)
    (event,) = _events("gate_hold")
    looks = sum(event["ws"])
    assert looks >= 60, f"one look every 0.02 s from the first tick's journal entry to 1.8 s, not one every 0.5 s: {event['ws']}"
    assert len(_at(calls, "tick")) == 3, f"the full tick stayed at its 0.5 s pace: {_at(calls, 'tick')}"


@pytest.mark.usefixtures("journal")
def test_another_thread_calling_the_watchdogs_functions_mid_window_is_not_a_call_of_the_loop(proc, monkeypatch):
    """The process's own watchdog thread runs the same module functions the simulation patches, and one of its wakes can land inside the window
    (a Core-only run recorded a fourth tick at 1.68 s). Here a thread of that name makes both calls at about 1.3 s of simulated time, on purpose
    and at the same point every run: the loop's ticks are still its own three, and the stranger got the no-op answers back."""
    proc.put("S", "futex_do_wait")
    me = threading.get_ident()
    real_look = writer.sample_holder_state
    looked = {"n": 0}
    stranger: dict[str, object] = {}

    def stranger_calls():
        stranger["tick"] = writer.watchdog_tick(writer.write_gate, 7.0)
        stranger["look"] = writer.sample_holder_state(writer.write_gate)

    def look(g, now=None):
        if threading.get_ident() == me:
            looked["n"] += 1
            if looked["n"] == 40:
                t = threading.Thread(target=stranger_calls, name="oo-write-gate-watchdog")
                t.start()
                t.join(30)
                assert not t.is_alive(), "the stranger's calls came back"
        return real_look(g, now)

    calls = _run_the_loop_over_a_long_hold(monkeypatch, look=look)
    assert _at(calls, "tick") == pytest.approx([0.5, 1.0, 1.5], abs=0.03), f"only the loop's own ticks are recorded: {_at(calls, 'tick')}"
    assert stranger == {"tick": 7.0, "look": False}, f"another thread got the no-op answers, not the real ones: {stranger}"
    assert looked["n"] >= 40, "the stranger really came in mid-window"


@pytest.mark.usefixtures("journal")
def test_a_watchdog_tick_that_raises_waits_its_interval_and_does_not_stop_the_looks(proc, monkeypatch):
    """The loop moved ``due`` only after the tick returned, so a tick that raised was due again at once: the loop ran it at full speed (290,307
    times in a second) and, with the look in the same ``try``, took no look. The first tick is real (it journals the hold); every later one raises."""
    proc.put("S", "futex_do_wait")
    real_tick = writer.watchdog_tick
    ticked: list[int] = []

    def tick(g, w):
        ticked.append(1)
        if len(ticked) == 1:
            return real_tick(g, w)
        raise RuntimeError("the tick failed")

    calls = _run_the_loop_over_a_long_hold(monkeypatch, tick=tick)
    ticks = _at(calls, "tick")
    assert len(ticks) == 3, f"a raising tick waits its 0.5 s: {len(ticks)} ticks in 1.8 s (a spinning loop is cut off at 5,000 waits)"
    assert ticks == pytest.approx([0.5, 1.0, 1.5], abs=0.03), ticks
    tick_at = [i for i, (kind, _when) in enumerate(calls) if kind == "tick"]
    between = [kind for kind, _when in calls[tick_at[1] + 1 : tick_at[2]]]
    assert between.count("look") >= 20, f"the looks go on between the raising ticks at their own 0.02 s pace: {between.count('look')} looks in 0.5 s"


@pytest.mark.usefixtures("journal")
def test_a_sampler_that_raises_does_not_spin_the_loop_or_stop_the_ticks(proc, monkeypatch):
    def look(g, now=None):
        raise RuntimeError("the look failed")

    calls = _run_the_loop_over_a_long_hold(monkeypatch, look=look)
    ticks, looks = _at(calls, "tick"), _at(calls, "look")
    assert ticks == pytest.approx([0.5, 1.0, 1.5], abs=0.03), f"the ticks go on at the full tick's own pace: {ticks}"
    assert len(looks) == len(ticks), f"one failed look per wake, each wake at the full tick's pace: the loop did not spin ({len(looks)} looks)"


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
                if getattr(node, "type_params", None):  # PEP 695: ``def f[T](...)`` runs its annotations in a scope of its own
                    names.add(f"<generic parameters of {node.name}>")
            elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
                names.add(f"<generic parameters of {node.name.id}>")
        for name in names:
            frame = f"{module}:{name}:{'9' * digits}"
            found.append((len(frame), frame))
    found.sort(reverse=True)
    return found


def test_no_function_under_src_can_produce_a_frame_wider_than_the_width_the_budget_counts():
    """``writer.FRAME_CHARS`` is what ``storage_events``' budget counts each of a hold's three frames at (the journal's own cut is 160, which
    no frame reaches). It is a MEASURED MAXIMUM with no slack, pinned BOTH WAYS by walking every module: a new function with a longer name than
    the budget assumes fails HERE, with the name (raise ``FRAME_CHARS`` and re-measure the slot with
    ``test_the_storage_events_budget_holds_a_full_journal``), and a constant wider than any frame can be fails here too (lower it: the bytes
    are the budget's, and a width nothing measured is a margin, which is what a measured maximum is not)."""
    found = _longest_frames()
    assert len(found) > 5_000, f"the walk saw only {len(found)} names: it is not looking at src/"
    widest, name = found[0]
    assert widest >= 60, f"the walk found nothing longer than {widest} ({name}): it is not measuring the names"
    assert all(n.isascii() for _w, n in found), "the budget counts a character as a byte: a frame with a non-ASCII name is wider than it looks"
    assert any("<generic parameters of " in n for _w, n in found), "the walk lists PEP 695 scopes (src/database/write.py has one)"
    too_wide = [f"{n} ({w})" for w, n in found if w > writer.FRAME_CHARS]
    assert not too_wide, f"frames wider than FRAME_CHARS={writer.FRAME_CHARS}, which the storage-events budget counts: {too_wide[:5]}"
    assert widest == writer.FRAME_CHARS, (
        f"FRAME_CHARS={writer.FRAME_CHARS} is wider than the widest frame any function under src/ can produce ({widest}: {name}): "
        "lower it to the measured maximum, because the budget counts every one of those characters for each of 3 frames x 20 holds"
    )


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


def test_the_method_defines_every_class_the_journal_counts_and_the_two_ways_a_nap_and_a_gap_arise():
    sentence = se._METHOD.split("A hold's 'ws'")[1].split("Else 'ws' is null")[0]
    for name in hs.CLASSES:
        assert re.search(rf"\b{name}\b", sentence), name
    assert re.search(r"\bother a wait the kernel named otherwise\b", sentence) and "socket" in sentence, "'other' is defined, not only listed"
    assert re.search(r"\bunknown a wait it did not name\b", sentence), "'unknown' is told apart from 'other' in words"
    assert "They count looks, not time" in sentence, "a count of looks is not a share of time, and the method says so"
    assert "'rq'" in sentence and "first look to the last" in sentence and "never 0" in sentence, "rq: its span and its one way to be absent"
    assert "streaming backup" in sentence, "a nap is not only SQLite's busy handler: the backup sleeps between its WAL tries while it holds the gate"
    assert "could not be read" in sentence and "tick" in sentence, "a gap over a second is not only a starved process"
