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
globals, and the enter and exit of every ``with <lock>:`` (nothing can protect them: the enter is a ``BEFORE_WITH`` making the bound ``__enter__``
and ``__exit__``, and the exit calls ``__exit__(None, None, None)``, which builds a 3-tuple on CPython 3.13 and so DOES allocate when the tuple free
list is empty; a failure there leaves a plain lock held, measured with the allocator, which is why the module's state has no lock of its own, see the
last part of this file).
A call into the standard library is ONE instruction at its call site: "the call could not start", not "it failed half way".

WHAT IT PROVES, AND THE ONE SITE IT NAMES. At every such instruction: the lock is given back, a thread that was already waiting for a
connection got through, and one that arrived afterwards did, and the write gate is free again. The single exception it models is the call of
``release_if_held_here`` itself: if the allocator refuses to start THAT call, no code that runs after it can help (natively the site is the
``BEFORE_WITH`` inside it), so it is named here, in the docstring of ``swap_window`` and in the report, not hidden. The test allows that site to
leave the lock held and no other. The exit of the ``with self._lock:`` inside that call is a second residual the sweep does not model (see above), named in the
same places.

THE VALID SET. The cleanup also decides which connections may run again, and a failure in it must land on the safe side: with a second sweep whose
body calls ``disk_changing()`` (as every restore, repair and encrypt does), at every instruction of the cleanup, the only connections valid afterwards
are the new generation's, never the window's own or an earlier one, whose files had their log names removed.

THE MUTANTS. A sweep that finds nothing proves nothing until it is seen to find something, so the module's own source is rewritten four ways
(each undoes one thing this fix or ``#1426`` did) and the sweep must report the defect each time: the release that asks for the thread
identity, the cleanup whose second statement is skipped when the first fails, the wait with no step, and the decision about the flag made in
a step of its own before the close (the shape that revived the window's connections after ``disk_changing``). The last part of this file pins
that the module's state has no lock of its own, with a synthetic source that does.
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
        self.valid_after: frozenset[int] | None = None
        self.generation: int | None = None


def _run(path: Path, *, source_present: bool, mode: str, nth: int = 0, changes_disk: bool = False) -> Run:
    """One window. ``mode``: ``count`` (list the allocating instructions of the cleanup), ``fail`` (raise before the nth). ``changes_disk``: the
    body calls ``disk_changing()`` first, as every restore, repair and encrypt does before it moves the file."""
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
            if changes_disk:
                lg.disk_changing()
            state["armed"] = True  # the body is over: what runs from here is the cleanup
    except MemoryError:
        out.raised = "MemoryError"
    except BaseException as exc:  # noqa: BLE001 - any other end is reported, not hidden
        out.raised = type(exc).__name__
    finally:
        sys.settrace(previous)
    out.lock_held = lg._LOCK._holder is not None
    out.valid_after, out.generation = lg._VALID, lg._GENERATION
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


def _sweep(path: Path, *, source_present: bool, changes_disk: bool = False) -> tuple[list[str], list[str]]:
    """Every allocating instruction of the cleanup, and the ones whose failure leaves something wrong (the named release call apart).
    With ``changes_disk`` a failure must also leave ONLY the new generation valid: a connection from before the swap, or the window's own, opens
    a file whose log names were removed."""
    listed = _run(path, source_present=source_present, mode="count", changes_disk=changes_disk)
    assert listed.raised is None, f"the unforced window ended in {listed.raised}"
    wrong: list[str] = []
    for n in range(1, len(listed.sites) + 1):
        r = _run(path, source_present=source_present, mode="fail", nth=n, changes_disk=changes_disk)
        assert r.raised == "MemoryError", f"site {n} ({r.where}) did not surface the error: {r.raised}"
        problems = []
        if changes_disk and (r.generation is None or r.valid_after != frozenset({r.generation})):
            problems.append(f"after disk_changing the valid set is {sorted(r.valid_after or ())}, not only the new generation {r.generation}")
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


@pytest.mark.parametrize("source_present", [True, False], ids=["swap_did_not_happen", "swap_happened"])
def test_a_memory_error_at_any_instruction_of_the_cleanup_leaves_only_the_new_generation_valid_after_disk_changing(source_present):
    """The swap changed the disk and the cleanup is interrupted by the allocator anywhere: the connections made inside the window, and the ones from
    before it, stay refused, because the files under them had their log names removed. The decision and the write are one step in
    ``_close_window``, so a failure before it lands on the safe side. (The old cleanup read the flag in a section of its own, and a failure
    between that read and the close revived the window's stamp: found by the independent read of PR 1442, reproduced on main with a stand-in lock.)

    The flag only matters while the source is still there: with the source gone (``swap_happened``) the swap happened, the close never revives, and
    that case re-runs the same sites as the ordinary sweep above. It is kept so the claim holds in both states, not because it can fail through the flag."""
    sites, wrong = _sweep(_SOURCE, source_present=source_present, changes_disk=True)
    assert len(sites) >= 6, sites
    assert wrong == [], wrong


def test_the_sweep_catches_a_decision_about_the_flag_made_in_a_step_of_its_own():
    """Red without the one-step close: the cleanup decides whether the disk changed in a statement of its own that can ALLOCATE (here a ``bool(...)``
    call; a plain read of the flag cannot fail under the MemoryError model, and is not what this catches), and the close acts on that decision
    without looking at the flag."""
    edits = [
        (
            r"            try:\n                swapped = not source\.exists\(\)\n            except OSError:",
            "            try:\n                swapped = not source.exists()\n                changed = bool(_DISK_CHANGED)\n                swapped = swapped or changed\n            except OSError:",
        ),
        (r"if not swapped and not _DISK_CHANGED:", "if not swapped:"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = _mutant_of(Path(tmp), edits, "flag_decided_apart")
        _, wrong = _sweep(path, source_present=True, changes_disk=True)
    assert any(w.startswith("swap_window:") and "the valid set" in w for w in wrong), wrong


# --- the module's state has no lock of its own ---------------------------------------------------------------------------------------------
#
# A plain lock whose ``with`` exit fails stays held (measured with the allocator on 3.13), and every later section waits behind it. The four names
# the swap writes are written only inside the exclusive window, so a lock of their own guarded nothing; it was removed, and these pins keep it
# from coming back in a writer. That every CALL of a writer is made inside a window is pinned in ``test_library_generation_writers_run_in_the_window.py``.

_WRITERS = ("swap_window", "bump", "_open_window", "_close_window", "disk_changing")


def _lock_sections(source_text: str) -> dict[str, list[str]]:
    """What takes a lock where the module's state is written: the ``with`` statements inside each writer AND inside any module function a writer
    calls by name, followed to any depth (a section moved into a helper is still a section in the cleanup), and any module-level
    ``threading.Lock()`` / ``RLock()`` (the window's own lock is the ``_Lock`` class, built from the ``RLock`` inside its ``__init__``; a call
    through an attribute, such as ``_LOCK.exclusive(...)``, is not followed: the window's own sections are not this pin's subject)."""
    tree = ast.parse(source_text)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def reached(name: str) -> list[ast.FunctionDef]:
        seen: dict[str, ast.FunctionDef] = {}
        todo = [name]
        while todo:
            current = todo.pop()
            if current in seen or current not in functions:
                continue
            seen[current] = functions[current]
            todo += [c.func.id for c in ast.walk(functions[current]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
        return list(seen.values())

    found: dict[str, list[str]] = {
        name: [ast.unparse(item.context_expr) for fn in reached(name) for w in ast.walk(fn) if isinstance(w, ast.With) for item in w.items]
        for name in _WRITERS
    }
    found["module"] = [
        ast.unparse(n.value)
        for n in tree.body
        if isinstance(n, (ast.Assign, ast.AnnAssign))
        and isinstance(n.value, ast.Call)
        and ast.unparse(n.value.func) in ("threading.Lock", "threading.RLock", "Lock", "RLock")
    ]
    return found


def test_the_modules_state_has_no_lock_and_no_writer_takes_one():
    found = _lock_sections(_SOURCE.read_text(encoding="utf-8"))
    assert found == {name: [] for name in (*_WRITERS, "module")}, found
    assert not hasattr(real, "_STATE") and not hasattr(real, "_revive")


def test_the_pin_sees_a_state_lock_in_a_writer_and_at_module_level():
    synthetic = (
        "import threading\n_STATE = threading.Lock()\n_LOCK = _Lock()\n"
        "def swap_window(source):\n    pass\n"
        "def bump():\n    with _STATE:\n        pass\n"
        "def _open_window():\n    pass\n"
        "def _close_window(*, swapped):\n    _helper()\n"
        "def _helper():\n    _deeper()\n"
        "def _deeper():\n    with _STATE:\n        pass\n"
        "def disk_changing():\n    with _STATE:\n        pass\n"
    )
    assert _lock_sections(synthetic) == {
        "swap_window": [],
        "bump": ["_STATE"],
        "_open_window": [],
        "_close_window": ["_STATE"],  # a section in a helper of a helper of the writer is still the writer's
        "disk_changing": ["_STATE"],
        "module": ["threading.Lock()"],
    }
