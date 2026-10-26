"""A MemoryError inside ``connecting()``'s cleanup must not leave a shared level raised on the library lock (the WAL thread, 17 Oct 2026).

THE QUESTION. ``connecting()`` takes a shared level of the library lock around ONE open of a connection and gives it back in a ``finally``.
The give-back used to be ``if _LOCK.shared_held_here() > before: _LOCK.release_shared()``: a call to learn whether the level is ours, then a call
to give it back. A failure in either skipped the release, and a level that stays raised makes every later ``swap_window`` (repair, restore,
encrypt in place) refuse with ``LibraryBusy`` ("a connection was still being opened") until the process restarts. It is a named refusal and
not a hang, which is why this was a second change after the exclusive window's (``tests/test_swap_window_allocation_failures.py``), and the
same instruction sweep applies.

THE MODEL IS THE SWAP WINDOW'S (read its docstring): the module's frames are traced instruction by instruction, and once the body of
``with connecting():`` is over a MemoryError is raised BEFORE the Nth instruction that can allocate, for every N. Two things differ.

* Small-integer arithmetic is left out as well. ``self._shared -= 1`` and ``self._mine.n -= 1`` make no object: a result below 257 is a cached
  one (``test_the_counter_arithmetic_the_sweep_leaves_out_returns_cached_objects`` pins that on this interpreter). Counting them, as the
  report's first sweep did, flags sites no allocator failure can reach.
* The thing watched is the level, not the holder. After each forced error: is a shared level still raised (the lock's count and this thread's
  record), can a swap take the window at once, and did a swap that was ALREADY WAITING for the opens in flight get through (the give-back wakes
  it with ``notify_all``, the one call after the level is back; a MemoryError in it loses the wake-up and the swap waits out its deadline unless
  its wait takes steps).

THE MODEL IS NOT THE ALLOCATOR. A Python call, an attribute fetch and a ``getattr`` of an existing record do not necessarily allocate on this interpreter;
forced with the allocator itself (``_testcapi.set_nomemory``, warm and cold free lists, the old give-back and the new one) both fail only inside the
``with self._lock:`` of the release: its enter (the level stays raised) and, on cold free lists, its exit (the RLock stays owned). So for a MemoryError the
sweep proves the ORDER (no call between "this level is ours" and "it is given back"), which is also what an interrupt needs, and it does not prove
that the old form was unsafe against the allocator; the measurable gain is the record's initialiser (below). The independent read of the delta found this.

THE ONE SITE IT NAMES. The call of ``release_shared_since`` in ``connecting``'s ``finally``: if the allocator refuses to start THAT call, no
code that runs after it can help. The test allows that site to leave the level raised and no other. The exit of the ``with self._lock:`` inside
the give-back is a second residual the sweep does not model (it builds a 3-tuple on CPython 3.13 and allocates when the free list is empty; a failure
leaves the lock held): see ``tests/test_swap_window_allocation_failures.py``.

THE MUTANTS. A sweep that finds nothing proves nothing until it is seen to find something, so the module's own source is rewritten three ways,
each undoing one thing this change did, and the sweep must report the defect each time.
"""

from __future__ import annotations

import dis
import re
import sys
import threading
import time
from pathlib import Path

from src.database import library_generation as real
from tests.test_swap_window_allocation_failures import _SOURCE, ALLOCATES, _load, _mutant

#: How long the swap that is already waiting has before it gives up: a wait with no step, whose wake-up was lost, sleeps all of it and is refused.
#: The limit is measured from the moment the swap asks, so it is wide enough that a pause of the whole process before the cleanup does not use it up.
SWAP_DEADLINE_S = 3.0
#: How long after BOTH the cleanup has begun and the swap is asking it may take to be through. With the swap's wait taking steps of ``TEST_STEP_S`` a healthy
#: run is through in a few hundredths of a second (0.05-0.11 s measured from the start of the swap's thread, idle and beside 16 busy processes, which
#: includes the body's own 0.05 s); a lost wake-up with no step takes the whole of ``SWAP_DEADLINE_S``, so anything between the two tells them apart and
#: this sits well below the deadline. It is a wall-clock window on a thread, so the figure is put in the failure text: a pause of the process shows
#: as a number, a lost wake-up as a refusal.
SWAP_THROUGH_WITHIN_S = 1.0

_COUNTER_STEP = re.compile(r"[-+]= 1\b")


class Run:
    def __init__(self) -> None:
        self.sites: list[str] = []
        self.raised: str | None = None
        self.where: str | None = None
        self.where_is_the_release_call = False
        self.level_left = 0
        self.record_left = 0
        self.swap_through_s: float | None = None  # from the later of "the cleanup began" and "the swap asked" to "through"; None: refused at its deadline
        self.swap_afterwards: bool | None = None


def _run(path: Path, *, mode: str, nth: int = 0) -> Run:
    """One open. ``mode``: ``count`` (list the allocating instructions of the cleanup), ``fail`` (raise before the nth)."""
    lg = _load(path)
    text = Path(lg.__file__).read_text(encoding="utf-8").splitlines()
    out = Run()
    state = {"armed": False, "count": 0}
    decoded: dict = {}

    def instruction(code, offset):
        table = decoded.get(code)
        if table is None:
            table = decoded[code] = {i.offset: i for i in dis.get_instructions(code)}
        return table.get(offset)

    def local(frame, event, arg):
        if event == "line":
            frame.f_trace_opcodes = True  # CPython 3.13 honours it from the first line event on, not from the call event, in a frame it just entered
        if event == "opcode" and state["armed"]:
            ins = instruction(frame.f_code, frame.f_lasti)
            line = ins.positions.lineno if ins is not None and ins.positions and ins.positions.lineno else 0
            line_text = text[line - 1].strip() if 0 < line <= len(text) else ""
            counter = ins is not None and ins.opname == "BINARY_OP" and bool(_COUNTER_STEP.search(line_text))
            if ins is not None and ins.opname in ALLOCATES and not counter and not line_text.startswith("with "):
                state["count"] += 1
                out.sites.append(f"{frame.f_code.co_name}:{line} {ins.opname}")
                if mode == "fail" and state["count"] == nth:
                    out.where = f"{frame.f_code.co_name}:{line} {ins.opname}"
                    out.where_is_the_release_call = frame.f_code.co_name == "connecting" and ins.opname == "CALL" and "release_shared_since(" in line_text
                    raise MemoryError
        return local

    def tracer(frame, event, arg):
        if frame.f_code.co_filename == lg.__file__:
            frame.f_trace_opcodes = True
            return local
        return None

    swap_box: dict = {}

    def swapping() -> None:
        swap_box["asked"] = time.monotonic()
        try:
            lg._LOCK.exclusive(SWAP_DEADLINE_S)
        except lg.LibraryBusy:
            return
        swap_box["through"] = time.monotonic()
        lg._LOCK.release_exclusive()

    swapper = threading.Thread(target=swapping, daemon=True)
    previous = sys.gettrace()
    try:
        sys.settrace(tracer)
        with lg.connecting():
            # a swap that wants the window while an open is in flight: blocked on the level this thread holds, as the repair and the restore are
            swapper.start()
            threading.Event().wait(0.05)  # let it reach the lock's wait
            swap_box["cleanup_began"] = time.monotonic()
            state["armed"] = True  # the body is over: what runs from here is the cleanup
    except MemoryError:
        out.raised = "MemoryError"
    except BaseException as exc:  # noqa: BLE001 - any other end is reported, not hidden
        out.raised = type(exc).__name__
    finally:
        sys.settrace(previous)
    out.level_left = lg._LOCK._shared
    out.record_left = lg._LOCK.shared_held_here()
    # a level still raised means the swap cannot get through, so it is not waited for (it ends at its own deadline; the thread is a daemon on this copy's lock)
    swapper.join(0 if out.level_left else SWAP_DEADLINE_S + 1.0)
    if "through" in swap_box:  # not from the thread's start: that includes the body's own wait and any pause before the swap asked
        out.swap_through_s = max(0.0, swap_box["through"] - max(swap_box["asked"], swap_box["cleanup_began"]))
    if not out.level_left:  # a level still raised makes this certain to fail: do not pay for it
        try:
            lg._LOCK.exclusive(SWAP_THROUGH_WITHIN_S)
            lg._LOCK.release_exclusive()
            out.swap_afterwards = True
        except lg.LibraryBusy:
            out.swap_afterwards = False
    sys.modules.pop(lg.__name__, None)
    return out


def _sweep(path: Path) -> tuple[list[str], list[str]]:
    """Every allocating instruction of the cleanup, and the ones whose failure leaves something wrong (the named release call apart)."""
    listed = _run(path, mode="count")
    assert listed.raised is None, f"the unforced open ended in {listed.raised}"
    assert listed.level_left == 0 and listed.swap_through_s is not None, "the unforced open did not give its level back"
    wrong: list[str] = []
    for n in range(1, len(listed.sites) + 1):
        r = _run(path, mode="fail", nth=n)
        assert r.raised == "MemoryError", f"site {n} ({r.where}) did not surface the error: {r.raised}"
        problems = []
        if (r.level_left or r.record_left) and not r.where_is_the_release_call:
            problems.append("a shared level is still raised")
        if not r.level_left and (r.swap_through_s is None or r.swap_through_s > SWAP_THROUGH_WITHIN_S):
            took = "was refused at its deadline" if r.swap_through_s is None else f"took {r.swap_through_s:.2f} s"
            problems.append(f"a swap that was already waiting for the open did not get through (it {took}; the limit is {SWAP_THROUGH_WITHIN_S} s)")
        if r.swap_afterwards is False:
            problems.append("a swap asked for afterwards was refused")
        if problems:
            wrong.append(f"{r.where}: " + "; ".join(problems))
    return listed.sites, wrong


def test_a_memory_error_at_any_instruction_of_the_cleanup_leaves_no_level_raised_except_at_the_release_call():
    sites, wrong = _sweep(_SOURCE)
    # anti-vacuity: the sweep saw the call of the release and the wake-up inside it
    assert any(s.startswith("connecting:") and s.endswith("CALL") for s in sites), sites
    assert any(s.startswith("release_shared_since:") and s.endswith("CALL") for s in sites), sites
    assert wrong == [], wrong


def test_the_sweep_catches_a_cleanup_that_asks_the_lock_a_second_time_whether_the_level_is_ours(tmp_path):
    """The shape before this change: a call to learn it, then a call to release; a failure in the first skips the second."""
    path = _mutant(
        tmp_path,
        r"        _LOCK\.release_shared_since\(before\)\n",
        "        if _LOCK.shared_held_here() > before:\n            _LOCK.release_shared()\n",
        "ask_again",
    )
    _, wrong = _sweep(path)
    assert any(w.startswith("connecting:") and "a shared level is still raised" in w for w in wrong), wrong


def test_the_sweep_catches_a_release_that_makes_a_call_before_it_gives_the_level_back(tmp_path):
    path = _mutant(
        tmp_path,
        r"(def release_shared_since\(self, before: int\) -> None:\n        \"\"\".*?\"\"\"\n        with self\._lock:\n            if )self\._mine\.n > before:",
        r"\1self.shared_held_here() > before:",
        "call_first",
    )
    _, wrong = _sweep(path)
    assert any(w.startswith("shared_held_here:") or w.startswith("release_shared_since:") for w in wrong), wrong
    assert any("a shared level is still raised" in w for w in wrong), wrong


def test_the_sweep_catches_a_swap_wait_with_no_step_when_the_wake_up_is_lost(tmp_path):
    path = _mutant(tmp_path, r"_wait\(self\._cond, self\._lock, min\(left, _RECHECK_S\)\)", "_wait(self._cond, self._lock, left)", "swap_nostep")
    _, wrong = _sweep(path)
    assert any(w.startswith("release_shared_since:") and "already waiting" in w for w in wrong), wrong


def test_the_counter_arithmetic_the_sweep_leaves_out_returns_cached_objects():
    """The claim behind leaving ``+= 1`` / ``-= 1`` out of the sweep: the result of a small-integer step is the interpreter's own object for
    that number, so no allocation is asked for. It holds for every count the lock can reach (one per thread that is opening a connection, far
    below 257); if a release stops caching them this fails and the counters join the sweep."""
    base = list(range(-5, 257))  # what range hands out for these values are the interpreter's own objects
    for i in range(1, len(base) - 1):
        x = base[i]
        assert (x + 1) is base[i + 1], x
        assert (x - 1) is base[i - 1], x


def test_the_release_checks_the_record_and_decrements_with_no_call_before_the_level_is_back():
    """The structural pin for the same fix: from the start of ``release_shared_since`` to the store that lowers the lock's count there is no
    call (the ``with`` enter is ``BEFORE_WITH``, not a call); ``notify_all`` comes after it."""
    instructions = list(dis.get_instructions(real._Lock.release_shared_since.__code__))
    store = next(i for i, ins in enumerate(instructions) if ins.opname == "STORE_ATTR" and ins.argval == "_shared")
    assert [ins.opname for ins in instructions[:store] if ins.opname.startswith("CALL")] == []
    assert any(ins.opname.startswith("CALL") for ins in instructions[store:]), "notify_all should follow the store"
    assert real._Lock.release_shared_since.__code__.co_varnames[1] == "before"


def test_the_take_has_no_call_between_the_count_and_the_record():
    """``shared()``'s comment says the count and the thread's record are one step with no call between them; this holds it to that."""
    instructions = list(dis.get_instructions(real._Lock.shared.__code__))
    count = next(i for i, ins in enumerate(instructions) if ins.opname == "STORE_ATTR" and ins.argval == "_shared")
    record = next(i for i, ins in enumerate(instructions) if i > count and ins.opname == "STORE_ATTR" and ins.argval == "n")
    assert [ins.opname for ins in instructions[count:record] if ins.opname.startswith("CALL")] == []


def test_a_threads_record_holds_its_count_from_the_first_read_so_the_take_replaces_a_value():
    """The first store into a thread's empty record allocates; a failure there after the lock's count was raised left the count at 1 and the
    record at 0, and ``release_shared_since`` saw nothing to give back (the independent read of #1435's head, finding L1: forced with the
    allocator, cold free lists, the level stayed raised). ``connecting`` reads the record before it asks for a level, so the record must
    already hold ``n`` after that read: the take then replaces a value and allocates no entry."""
    seen: dict = {}

    def other() -> None:
        lock = real._Lock()
        seen["at_first_use"] = dict(vars(lock._mine))  # looking at the record is the thread's first use of it, so its initialiser has run
        lock.shared_held_here()
        seen["after_the_read"] = dict(vars(lock._mine))

    t = threading.Thread(target=other)
    t.start()
    t.join(5)
    assert seen["at_first_use"] == seen["after_the_read"] == {"n": 0}, f"a thread's record is empty at its first use, so the take makes an entry: {seen}"


def test_a_thread_that_never_opened_a_connection_holds_no_level_and_the_pieces_still_pair_up():
    seen: dict = {}

    def other() -> None:
        seen["before"] = real._LOCK.shared_held_here()
        with real.connecting():
            seen["inside"] = real._LOCK.shared_held_here()
            with real.connecting():
                seen["nested"] = real._LOCK.shared_held_here()
        seen["after"] = real._LOCK.shared_held_here()

    t = threading.Thread(target=other)
    t.start()
    t.join(5)
    assert seen == {"before": 0, "inside": 1, "nested": 2, "after": 0}, seen
    assert real._LOCK._shared == 0
