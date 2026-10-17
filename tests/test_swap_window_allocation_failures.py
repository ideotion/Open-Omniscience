"""A MemoryError inside the swap window's cleanup must not leave the library lock held (the WAL thread, 17 Oct 2026).

THE QUESTION. ``swap_window`` gives the library lock back in a ``finally``. A failure inside that cleanup used to skip the release: the lock
stayed held, and every later ``connecting()`` (every new pooled connection, which is the first thing any request does once the pool is empty)
blocked in ``shared()``, which had no timeout, until the process was restarted. The write gate was never at risk: the caller's ``with
write_lock():`` unwinds on the error (the sweep below checks that too, because the restore and the encrypt route hold the gate around the window).

WHY AN INSTRUCTION SWEEP AND NOT A LINE SWEEP. A MemoryError is raised by an instruction that asks the allocator for memory (a call, a ``BUILD_*``, a
binary operation that makes a new object, an iterator), never between two statements; a line-boundary sweep is right for a KeyboardInterrupt and
puts a MemoryError where none can happen. So the module's frames are traced instruction by instruction, and once the body of the window is over a
MemoryError is raised BEFORE the Nth instruction that can allocate (the instruction does not run: the allocation it needed failed), for every N.
Left out on purpose: attribute loads, truth tests, comparisons (they return the two singletons), stores, jumps, pops, loads of locals and
globals, and the enter and exit of every ``with <lock>:`` (a harness cannot inject at the exits of the non-reentrant ``_STATE`` without deadlocking on its own lock, and nothing can protect any of them:
the enter is a ``BEFORE_WITH`` making the bound ``__enter__`` and ``__exit__``, and the exit calls ``__exit__(None, None, None)``, which builds a 3-tuple on
CPython 3.13 and so DOES allocate when the tuple free list is empty; a failure there leaves the lock held, measured with the allocator).
A call into the standard library is ONE instruction at its call site: "the call could not start", not "it failed half way".

WHAT IT PROVES, AND THE ONE SITE IT NAMES. At every such instruction: the lock is given back, a thread that was already waiting for a
connection got through, and one that arrived afterwards did, and the write gate is free again. The single exception it models is the call of
``release_if_held_here`` itself: if the allocator refuses to start THAT call, no code that runs after it can help (natively the site is the
``BEFORE_WITH`` inside it), so it is named here, in the docstring of ``swap_window`` and in the report, not hidden. The test allows that site to
leave the lock held and no other. The exit of a ``with <lock>:`` is a second residual the sweep does not model (see above), named in the same
places.

THE MUTANTS. A sweep that finds nothing proves nothing until it is seen to find something, so the module's own source is rewritten three ways
(each undoes one thing this fix or ``#1426`` did) and the sweep must report the defect each time: the release that asks for the thread
identity, the cleanup whose second statement is skipped when the first fails, and the wait with no step.
"""

from __future__ import annotations

import ast
import dis
import importlib.util
import re
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from src.database import library_generation as real

#: Instructions that can ask the allocator for memory (CPython 3.13 names; a name another release lacks is simply never seen).
ALLOCATES = frozenset({
    "CALL", "CALL_KW", "CALL_FUNCTION_EX", "BUILD_LIST", "BUILD_TUPLE", "BUILD_SET", "BUILD_MAP", "BUILD_STRING", "BUILD_SLICE", "BINARY_OP",
    "BINARY_SUBSCR", "LIST_EXTEND", "SET_UPDATE", "DICT_UPDATE", "DICT_MERGE", "GET_ITER", "FORMAT_SIMPLE", "FORMAT_WITH_SPEC", "CONVERT_VALUE",
    "BEFORE_WITH", "LOAD_SPECIAL", "MAKE_FUNCTION", "CALL_INTRINSIC_1", "CALL_INTRINSIC_2",
})

#: How long the test waits for a thread that SHOULD get through. Nothing in a passing run waits for it; a failing one pays it once per defect.
GET_THROUGH_S = 2.0
#: The step the module under test waits in, so a lost wake-up costs 50 ms here and not the production second.
TEST_STEP_S = 0.05

_SOURCE = Path(real.__file__)
_loaded = 0


def _load(path: Path):
    """The module from this FILE under a fresh name, so its lock, generation and valid set start clean for every run."""
    global _loaded
    _loaded += 1
    spec = importlib.util.spec_from_file_location(f"lg_allocation_sweep_{_loaded}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    mod.__dict__["_RECHECK_S"] = TEST_STEP_S  # read by shared() at call time
    return mod


def _is_the_release_call(co_name: str, line_text: str, opname: str) -> bool:
    """THE named site: the call of ``release_if_held_here`` in ``swap_window``'s last ``finally``."""
    return co_name == "swap_window" and opname == "CALL" and "release_if_held_here(" in line_text


class Run:
    def __init__(self) -> None:
        self.sites: list[str] = []
        self.raised: str | None = None
        self.where: str | None = None
        self.where_is_the_release_call = False
        self.lock_held = False
        self.waiter_through: bool | None = None
        self.later_through: bool | None = None
        self.gate_held_here: bool | None = None
        self.gate_taken_by_another: bool | None = None


def _run(path: Path, *, source_present: bool, mode: str, nth: int = 0) -> Run:
    """One window. ``mode``: ``count`` (list the allocating instructions of the cleanup), ``fail`` (raise before the nth)."""
    from src.database.writer import write_gate, write_lock

    lg = _load(path)
    text = Path(lg.__file__).read_text(encoding="utf-8").splitlines()
    source = Path(tempfile.mkdtemp()) / "working.db"
    if source_present:
        source.write_bytes(b"x")
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
            if ins is not None and ins.opname in ALLOCATES and not line_text.startswith("with "):
                state["count"] += 1
                out.sites.append(f"{frame.f_code.co_name}:{line} {ins.opname}")
                if mode == "fail" and state["count"] == nth:
                    out.where = f"{frame.f_code.co_name}:{line} {ins.opname}"
                    out.where_is_the_release_call = _is_the_release_call(frame.f_code.co_name, line_text, ins.opname)
                    raise MemoryError
        return local

    def tracer(frame, event, arg):
        if frame.f_code.co_filename == lg.__file__:
            frame.f_trace_opcodes = True
            return local
        return None

    waiter_done = threading.Event()
    threads: list[threading.Thread] = []  # every thread this run starts, so none outlives it (see the end of the function)

    def waiting() -> None:
        with lg.connecting():
            pass
        waiter_done.set()

    previous = sys.gettrace()
    try:
        sys.settrace(tracer)
        with write_lock(), lg.swap_window(source, timeout=2.0):
            # a thread that wants a connection while the window is held: blocked on the lock, as the pool's connect is
            threads.append(threading.Thread(target=waiting, daemon=True))
            threads[-1].start()
            threading.Event().wait(0.05)  # let it reach the lock's wait
            state["armed"] = True  # the body is over: what runs from here is the cleanup
    except MemoryError:
        out.raised = "MemoryError"
    except BaseException as exc:  # noqa: BLE001 - any other end is reported, not hidden
        out.raised = type(exc).__name__
    finally:
        sys.settrace(previous)
    out.lock_held = lg._LOCK._holder is not None
    out.gate_held_here = write_gate.held_by_current_thread()
    got = threading.Event()

    def take() -> None:
        with write_lock():
            got.set()

    threads.append(threading.Thread(target=take, daemon=True))
    threads[-1].start()
    out.gate_taken_by_another = got.wait(GET_THROUGH_S)
    if not out.lock_held:  # a lock still held makes both waits certain to fail: do not pay for them
        out.waiter_through = waiter_done.wait(GET_THROUGH_S)
        opened = threading.Event()

        def opener() -> None:
            with lg.connecting():
                pass
            opened.set()

        threads.append(threading.Thread(target=opener, daemon=True))
        threads[-1].start()
        out.later_through = opened.wait(GET_THROUGH_S)
    # A site that leaves the window held (the named call, and the mutants' sites) leaves every thread that waits for it polling on this copy of
    # the module for the rest of the session (11 daemon threads, each waking every TEST_STEP_S, measured after the two files ran). The run
    # has its answers: give the window back and let them end.
    if lg._LOCK._holder is not None:
        lg._LOCK.release_exclusive()
    for thread in threads:
        thread.join(GET_THROUGH_S)
    sys.modules.pop(lg.__name__, None)
    return out


def _sweep(path: Path, *, source_present: bool) -> tuple[list[str], list[str]]:
    """Every allocating instruction of the cleanup, and the ones whose failure leaves something wrong (the named release call apart)."""
    listed = _run(path, source_present=source_present, mode="count")
    assert listed.raised is None, f"the unforced window ended in {listed.raised}"
    wrong: list[str] = []
    for n in range(1, len(listed.sites) + 1):
        r = _run(path, source_present=source_present, mode="fail", nth=n)
        assert r.raised == "MemoryError", f"site {n} ({r.where}) did not surface the error: {r.raised}"
        problems = []
        if r.lock_held and not r.where_is_the_release_call:
            problems.append("the library lock is still held")
        if r.waiter_through is False:
            problems.append("a connection that was already waiting never got through")
        if r.later_through is False:
            problems.append("a connection opened afterwards never got through")
        if r.gate_held_here:
            problems.append("the write gate is still held by this thread")
        if r.gate_taken_by_another is False:
            problems.append("another thread could not take the write gate")
        if problems:
            wrong.append(f"{r.where}: " + "; ".join(problems))
    return listed.sites, wrong


def _mutant(tmp_path: Path, pattern: str, replacement: str, name: str) -> Path:
    """The module's own source with ONE rewrite (it must match exactly once, so a reformatted source fails here and not silently)."""
    return _mutant_of(tmp_path, [(pattern, replacement)], name)


def _mutant_of(tmp_path: Path, edits: list[tuple[str, str]], name: str) -> Path:
    """The module's own source with several rewrites, each of which must match exactly once."""
    text = _SOURCE.read_text(encoding="utf-8")
    for pattern, replacement in edits:
        text, count = re.subn(pattern, replacement, text, flags=re.S)
        assert count == 1, f"the mutant {name!r} found its anchor {pattern[:40]!r} {count} times: the source changed, update the pattern"
    path = tmp_path / f"library_generation_{name}.py"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("source_present", [True, False], ids=["swap_did_not_happen", "swap_happened"])
def test_a_memory_error_at_any_instruction_of_the_cleanup_leaves_nothing_held_except_the_release_call(source_present):
    sites, wrong = _sweep(_SOURCE, source_present=source_present)
    # anti-vacuity: the sweep saw the cleanup, and saw the one site it names
    assert len(sites) >= 6, sites
    assert any(s.startswith("swap_window:") and "CALL" in s for s in sites), sites
    assert wrong == [], wrong


def test_the_sweep_catches_a_release_that_asks_for_the_thread_identity_after_the_holder_is_found(tmp_path):
    path = _mutant(tmp_path, r"if self\._holder == me:(\n\s+self\._holder = None)", r"if self._holder == threading.get_ident():\1", "ident")
    _, wrong = _sweep(path, source_present=True)
    assert any(w.startswith("release_if_held_here:") and "the library lock is still held" in w for w in wrong), wrong


def test_the_sweep_catches_a_cleanup_whose_release_is_skipped_when_the_first_call_fails(tmp_path):
    pattern = (
        r"        try:\n            if not before and _LOCK\.held_here\(\):[^\n]*\n                _close_window\(swapped=swapped, earlier=earlier\)\n"
        r"        finally:\n            if not before:\n                _LOCK\.release_if_held_here\(me\)[^\n]*\n"
    )
    replacement = (
        "        if not before and _LOCK.held_here():\n            _close_window(swapped=swapped, earlier=earlier)\n"
        "        if not before:\n            _LOCK.release_if_held_here(me)\n"
    )
    path = _mutant(tmp_path, pattern, replacement, "sequential")
    _, wrong = _sweep(path, source_present=True)
    assert any(w.startswith(("_close_window:", "held_here:", "swap_window:")) and "the library lock is still held" in w for w in wrong), wrong


def test_the_sweep_catches_a_wait_with_no_step_when_the_wake_up_is_lost(tmp_path):
    path = _mutant(tmp_path, r"_wait\(self\._cond, self\._lock, _RECHECK_S\)", "_wait(self._cond, self._lock)", "nostep")
    _, wrong = _sweep(path, source_present=True)
    assert any(w.startswith("release_if_held_here:") and "a connection that was already waiting never got through" in w for w in wrong), wrong


def test_the_step_is_one_second_and_the_open_passes_it_to_its_wait():
    """The number names what it protects (the longest a lost wake-up may cost) and is pinned here, not left to a reader."""
    assert real._RECHECK_S == 1.0
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    shared = next(f for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "_Lock" for f in c.body if isinstance(f, ast.FunctionDef) and f.name == "shared")
    waits = [n for n in ast.walk(shared) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_wait"]
    assert len(waits) == 1
    names = [a.id if isinstance(a, ast.Name) else (a.attr if isinstance(a, ast.Attribute) else None) for a in waits[0].args]
    assert names == ["_cond", "_lock", "_RECHECK_S"], names


def test_an_open_waits_as_long_as_the_window_is_held_the_step_is_not_a_timeout():
    lg = _load(_SOURCE)
    lg._RECHECK_S = 0.02
    try:
        done = threading.Event()
        with lg.swap_window(Path(tempfile.mkdtemp()) / "absent.db", timeout=2.0):

            def opener() -> None:
                with lg.connecting():
                    done.set()

            threading.Thread(target=opener, daemon=True).start()
            assert not done.wait(0.5), "an open got through while the window was held: the step acted as a timeout"
        assert done.wait(GET_THROUGH_S), "the open never got through after the window was given back"
    finally:
        sys.modules.pop(lg.__name__, None)


def test_the_release_compares_an_identity_it_already_has_and_calls_nothing_before_the_holder_is_clear():
    """The structural pin for the same fix: from the start of ``release_if_held_here`` to the store that clears the holder there is no call
    (the ``with`` enter is ``BEFORE_WITH``, not a call). ``notify_all`` comes after the store."""
    code = real._Lock.release_if_held_here.__code__
    instructions = list(dis.get_instructions(code))
    store = next(i for i, ins in enumerate(instructions) if ins.opname == "STORE_ATTR" and ins.argval == "_holder")
    calls = [ins.opname for ins in instructions[:store] if ins.opname.startswith("CALL")]
    assert calls == [], calls
    assert any(ins.opname.startswith("CALL") for ins in instructions[store:]), "notify_all should follow the store"
    assert "me" in code.co_varnames[: code.co_argcount], code.co_varnames


# --- the sections of ``_STATE`` the cleanup passes ---------------------------------------------------------------------------------------
#
# THE SECOND PROPERTY (after the lock is given back): a failed EXIT of ``with _STATE:`` leaves that plain lock held (measured with the allocator
# on 3.13), and every later ``with _STATE:`` then blocks for ever. If the cleanup passed three such sections (the read of ``_DISK_CHANGED``, the
# revive, the close), a failure at the first two blocked the cleanup's own next section with the window held. The cleanup now passes ONE. The
# sweep cannot see this (it never injects at an exit), so the pin counts the sections in the source and the stand-in below fails an exit the way
# the allocator does.


def _sections_of_state_in_the_cleanup(source_text: str) -> int:
    """How many ``with _STATE:`` sections ``swap_window``'s ``finally`` blocks pass: the ones written there, and one for each call of a module
    function that has them (a section moved into a helper is still a section)."""
    tree = ast.parse(source_text)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def sections(node: ast.AST) -> int:
        return sum(1 for n in ast.walk(node) if isinstance(n, ast.With) and any(isinstance(i.context_expr, ast.Name) and i.context_expr.id == "_STATE" for i in n.items))

    cleanup = [stmt for node in ast.walk(functions["swap_window"]) if isinstance(node, ast.Try) for stmt in node.finalbody]
    calls = [n.func.id for stmt in cleanup for n in ast.walk(stmt) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in functions]
    return sum(sections(stmt) for stmt in cleanup) + sum(sections(functions[name]) for name in calls)


def test_the_cleanup_passes_one_section_of_the_state_lock_and_revive_is_gone():
    text = _SOURCE.read_text(encoding="utf-8")
    assert _sections_of_state_in_the_cleanup(text) == 1
    assert not hasattr(real, "_revive"), "the revive is a section of its own again: it belongs inside _close_window"


def test_the_pin_sees_the_cleanup_that_passed_three_sections(tmp_path):
    path = _three_section_cleanup(tmp_path)
    assert _sections_of_state_in_the_cleanup(path.read_text(encoding="utf-8")) == 3


def _three_section_cleanup(tmp_path: Path) -> Path:
    """The module with the cleanup it had before the merge: a read of ``_DISK_CHANGED``, ``_revive`` and ``_close_window``, three sections."""
    return _mutant_of(
        tmp_path,
        [
            (
                r"            try:\n                swapped = not source\.exists\(\)\n            except OSError:",
                "            try:\n                swapped = not source.exists()\n                with _STATE:\n                    changed = _DISK_CHANGED\n"
                "                if not swapped and not changed:\n                    _revive(earlier)\n                swapped = swapped or changed\n            except OSError:",
            ),
            (
                r"def _open_window\(\) -> None:",
                "def _revive(earlier: frozenset[int]) -> None:\n    global _VALID\n    with _STATE:\n        _VALID = frozenset(earlier | _VALID)\n\n\ndef _open_window() -> None:",
            ),
        ],
        "three_sections",
    )


class _StateWhoseExitFails:
    """Stands in for ``_STATE``. The exit told to fail raises MemoryError and leaves the real lock held, which is what a failed
    ``__exit__(None, None, None)`` does on 3.13. ``phase`` is ``open`` for the sections the window passes before its body and ``cleanup`` for the
    ones after it; ``nth`` counts the exits of that phase."""

    def __init__(self, *, phase: str, nth: int, settled: threading.Event) -> None:
        self._lock = threading.Lock()
        self._settled = settled
        self.phase = phase
        self.nth = nth
        self.body_is_over = False
        self.exits = {"open": 0, "cleanup": 0}
        self.failed = False
        self.blocked = threading.Event()

    def __enter__(self):
        if self.failed:  # a section is waiting behind an exit that failed: it will not get the lock
            self.blocked.set()
            self._settled.set()
        self._lock.acquire()
        return self

    def __exit__(self, *exc):
        phase = "cleanup" if self.body_is_over else "open"
        self.exits[phase] += 1
        if not self.failed and phase == self.phase and self.exits[phase] == self.nth:
            self.failed = True
            raise MemoryError
        self._lock.release()
        return False


class _Swap:
    def __init__(self) -> None:
        self.raised: str | None = None
        self.blocked = False
        self.window_held = False
        self.pool_serves: bool | None = None
        self.failed = False


def _swap_whose_state_exit_fails(path: Path, *, phase: str, nth: int) -> _Swap:
    """One swap (the source still there: it did not happen) whose Nth ``_STATE`` exit of the phase fails. It runs in a thread: a block is an answer."""
    lg = _load(path)
    settled = threading.Event()
    stand_in = _StateWhoseExitFails(phase=phase, nth=nth, settled=settled)
    lg._STATE = stand_in
    source = Path(tempfile.mkdtemp()) / "working.db"
    source.write_bytes(b"x")
    out = _Swap()
    threads: list[threading.Thread] = []

    def swap() -> None:
        try:
            with lg.swap_window(source, timeout=GET_THROUGH_S):
                stand_in.body_is_over = True
        except BaseException as exc:  # noqa: BLE001 - reported
            out.raised = type(exc).__name__
        finally:
            settled.set()

    threads.append(threading.Thread(target=swap, daemon=True))
    threads[-1].start()
    assert settled.wait(GET_THROUGH_S), "the swap neither ended nor blocked"
    out.blocked = stand_in.blocked.is_set()
    out.failed = stand_in.failed
    out.window_held = lg._LOCK._holder is not None
    if not out.window_held:
        opened = threading.Event()

        def opener() -> None:
            with lg.connecting():
                pass
            opened.set()

        threads.append(threading.Thread(target=opener, daemon=True))
        threads[-1].start()
        out.pool_serves = opened.wait(GET_THROUGH_S)
    # give everything back so no thread outlives the run: the failed exit left the stand-in's lock held, which is what the blocked section waits on
    if stand_in._lock.locked():
        stand_in._lock.release()
    threads[0].join(GET_THROUGH_S)
    if lg._LOCK._holder is not None:
        lg._LOCK.release_exclusive()
    for thread in threads[1:]:
        thread.join(GET_THROUGH_S)
    sys.modules.pop(lg.__name__, None)
    return out


def test_a_failed_exit_of_the_cleanups_one_section_still_gives_the_window_back():
    """The residual after the merge, said exactly: the error surfaces, the window is given back, the pool keeps serving. ``_STATE`` stays held,
    so the NEXT swap blocks at its first section (said in ``swap_window``'s docstring); that is not tested here because it needs a second swap."""
    r = _swap_whose_state_exit_fails(_SOURCE, phase="cleanup", nth=1)
    assert r.failed, "the exit was never failed: the test proved nothing"
    assert (r.raised, r.blocked, r.window_held, r.pool_serves) == ("MemoryError", False, False, True), vars(r)


def test_the_same_failed_exit_blocked_the_cleanup_that_passed_three_sections(tmp_path):
    """Red without the merge: the first section's exit fails, the second section waits for ever, and the window is still held."""
    r = _swap_whose_state_exit_fails(_three_section_cleanup(tmp_path), phase="cleanup", nth=1)
    assert r.failed
    assert (r.blocked, r.window_held) == (True, True), vars(r)


@pytest.mark.parametrize("nth", [1, 2, 3], ids=["reset_the_flag", "bump", "open_the_stamp"])
def test_a_failed_exit_of_a_section_that_opens_the_window_still_blocks_its_own_close_the_named_residual(nth):
    """Not merged, on purpose, and pinned so the claim cannot drift: the swap's three opening sections are the same exits, and a failure there
    blocks this swap's own ``_close_window`` with the window held. Merging them would move the block to the next swap, not remove it. A change
    that really removes it makes this test fail, and then the docstring of ``swap_window`` and the lesson change with it."""
    r = _swap_whose_state_exit_fails(_SOURCE, phase="open", nth=nth)
    assert r.failed
    assert (r.blocked, r.window_held) == (True, True), vars(r)
