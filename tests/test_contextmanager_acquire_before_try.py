"""A ``@contextmanager`` must not take anything between its first statement and the ``try`` that gives it back (R161 / R163).

``library_generation.swap_window`` took the exclusive lock, read the earlier validity and reset a flag BEFORE its ``try``; an interrupt
delivered between "the holder was set" and "the ``try`` began" left the window held for ever (``scripts/signal_leak_probe.py
gate_swap_window``: 7,013 of 30,872 interrupts, before the fix). The same shape exists in any context manager that does work before its
``try``, so this scan lists every ``@contextmanager`` in ``src/`` whose statements before the first ``yield`` hold a ``with`` block, an
assignment to a subscript or attribute, or a call that is not a known pure query. Each one is named below with the reason it is allowed;
a new one fails until it is read. The reasons are checked in the other direction too: an entry whose function no longer has such a
statement fails, so the list cannot grow stale (the ratchet of ``tests/test_gates_survive_an_interrupt.py``'s allowlists).

Scope, stated: this is a scan of the SOURCE SHAPE, not a measurement. It does not decide whether a function runs on the main thread (only the
main thread receives a KeyboardInterrupt; see ``tests/test_event_loop_signal_exemption.py`` for why the server's event loop does not); R163 counts a CLI
entry as main-thread, and the name-based call graph reaches a script ``main`` from nearly every helper, so each entry below is argued by what
the gap would leak and not by who calls it.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"

# Calls that read or build a value and leave nothing behind that a ``finally`` has to give back.
_PURE_CALLS = frozenset(
    {
        "monotonic", "perf_counter", "time", "get_ident", "getattr", "str", "int", "float", "max", "min", "len", "Path", "resolve",
        "tuple", "frozenset", "list", "dict", "set", "isinstance", "object", "Event", "next", "bool", "repr", "strip", "join", "hasattr",
        "get", "unparse",
        # queries of a lock or window this module owns: they say what is held, they do not hold anything
        "held_here", "shared_held_here", "exclusive_window_open",
    }
)

_THREAD_LOCAL = "the value lives in this thread's own context (thread-local or ContextVar): a leak stays in the interrupted thread, whose Ctrl-C ends it"
_SESSION = "the object made in the gap is a SQLAlchemy Session nobody can reach; the pool takes its connection back when it is collected"
_DURABLE = "durable by design: what the gap leaves is the record that makes the boot heal finish the job"

# (path under src/, function) -> why a statement before the try is allowed to stay. Every entry was read, not pattern-matched.
_ALLOWED: dict[tuple[str, str], str] = {
    ("analytics/bulk_build.py", "bulk_index_window"): _DURABLE + ": open_state writes the marker BEFORE the indexes are dropped, so a gap leaves a marker and no drop",
    ("api/main.py", "lifespan"): "the lifespan runs on the event loop, which uvicorn's signal capture covers (tests/test_event_loop_signal_exemption.py); its pre-yield work is the boot",
    ("backup/merge.py", "_fts_insert_suspended"): "works on a disposable working copy (its docstring), and a DROP TRIGGER that an interrupt strands is undone by the copy's rollback or its discard",
    ("backup/merge.py", "_step_watch"): "two nested function definitions: a def takes nothing",
    ("backup/runlog.py", "run"): "begin() writes a run row; an unfinished row is what the run journal reads as 'did not end', which is the truth after an interrupt",
    ("backup/runlog.py", "stage"): "a journal milestone line; an unfinished stage is what the journal shows after an interrupt",
    ("backup/timing.py", "stage"): "emits a 'begin' event to a callback; nothing is held",
    ("backup/timing.py", "sub"): "emits a 'begin' event to a callback; nothing is held",
    ("briefing/registry.py", "_wal_guard"): "drains a list of pending items in the session the caller owns; the session's own scope releases it",
    ("config/kv_store.py", "_write_slot"): "an environment read then the slot token; the slot is taken inside the try (tests/test_kv_store_write_hold.py)",
    ("database/connect.py", "_interrupt_when"): "starts a daemon watcher thread that ends with the process; the Event it waits on is local and set by the finally",
    ("database/maintenance.py", "statement_deadline"): "reads a setting; the progress handler is installed after the memory check and removed in a finally",
    ("database/pool_reserve.py", "collector_role"): _THREAD_LOCAL,
    ("database/read_snapshot.py", "read_snapshot_session"): _SESSION,
    ("database/session.py", "session_scope"): _SESSION,
    ("ingest/ssrf_guard.py", "connect_scope"): _THREAD_LOCAL + " (the scope stack is per thread)",
    ("monitoring/tasks.py", "track"): "a task row the snapshot ages out (its docstring); no lock or count outlives it",
    ("testing/scale_bench.py", "sample_peak_rss"): "a bench helper; its sampler is a daemon thread",
    ("versioned/store.py", "lane_session"): _SESSION,
    ("wiki/service.py", "wiki_lane_session"): "create_lane is idempotent and takes nothing a gap could leave",
    ("wiki/service.py", "walk_lane_session"): "a once-per-process schema flag set after the lane exists; a gap repeats the schema check",
}


# Owed: the function takes shared state before its try today, and the lane that owns the file converts it in the hunk pair named (r163-cm/<lane>). The
# entry passes both before and after that commit lands (the stale check skips it), so no bundle edits this file; it is deleted here, by the Q thread, once the
# owner's commit is in the base. An owed name must still be a real context manager (test_each_owed_entry_names_a_real_context_manager).
_OWED: dict[tuple[str, str], str] = {
    ("scheduler/runner.py", "exclusive_window"): "WAL: r163-cm/wal, the scheduler stays held if the interrupt lands inside the pause",
    ("backup/stream_backup.py", "active_staging"): "RC2: r163-cm/rc2, the path stays marked as a live job's staging",
}

# Owed IF PRESENT: two context managers of #1421's run records (WAL) that take shared state before their try. They exist only on a tree that has that
# PR, and this file must pass on a tree that has not (the follow-on alone) and on one that has. So, unlike _OWED, a name here need not exist: if the
# file defines it, it must still be a @contextmanager; if it no longer takes anything before its try (WAL's conversion landed) the entry is REPORTED as
# stale by a warning and does not fail, because the conversion merges after this file and its owner cannot edit it. Delete the entries here, by the Q
# thread, once WAL's follow-on is in the base.
_OWED_IF_PRESENT: dict[tuple[str, str], str] = {
    ("monitoring/storage_events.py", "run_open"): "WAL: R171 in its follow-on, the run record's open is taken before the try",
    ("monitoring/storage_events.py", "run_refusals_net"): "WAL: R171 in its follow-on, the refusal round's hold is taken before the try",
}


def _is_cm(fn: ast.AST) -> bool:
    return isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        ast.unparse(d).split(".")[-1] in ("contextmanager", "asynccontextmanager") for d in fn.decorator_list
    )


def _has_yield(node: ast.AST) -> bool:
    return any(isinstance(x, (ast.Yield, ast.YieldFrom)) for x in ast.walk(node))


def _call_name(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "?")


def _takes(stmt: ast.stmt) -> bool:
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return True
    for x in ast.walk(stmt):
        if isinstance(x, ast.Call) and _call_name(x) not in _PURE_CALLS:
            return True
        if isinstance(x, (ast.Assign, ast.AugAssign)):
            targets = x.targets if isinstance(x, ast.Assign) else [x.target]
            if any(isinstance(t, (ast.Subscript, ast.Attribute)) for t in targets):
                return True
    return False


def pre_yield_takers(source: str) -> dict[str, list[str]]:
    """``function name -> the statements before its first yield that take something``, for every context manager in ``source``."""
    found: dict[str, list[str]] = {}
    for fn in ast.walk(ast.parse(source)):
        if not _is_cm(fn):
            continue
        first = next((k for k, st in enumerate(fn.body) if _has_yield(st)), None)  # type: ignore[attr-defined]
        if first is None:
            continue
        pre = [st for st in fn.body[:first] if not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant))]  # type: ignore[attr-defined]
        taking = [ast.unparse(st).splitlines()[0][:70] for st in pre if _takes(st)]
        if taking:
            found[fn.name] = taking  # type: ignore[attr-defined]
    return found


def _scan() -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        hits = pre_yield_takers(path.read_text(encoding="utf-8"))  # a file this interpreter cannot parse fails the test: the scan must not skip it
        out.update({(rel, name): stmts for name, stmts in hits.items()})
    return out


def test_every_context_manager_that_takes_something_before_its_try_is_named():
    found = _scan()
    new = sorted(set(found) - set(_ALLOWED) - set(_OWED) - set(_OWED_IF_PRESENT))
    assert not new, (
        "a @contextmanager takes something before its yield (an interrupt in that gap skips its give-back); read it, then either move the take "
        "inside the try (R161 shape: release by asking the lock, or an idempotent finally) or name it in _ALLOWED with the reason:\n"
        + "\n".join(f"  {p}::{n}: {found[(p, n)]}" for p, n in new)
    )


def test_every_allowed_entry_still_has_a_statement_to_allow():
    found = _scan()
    stale = sorted(set(_ALLOWED) - set(found))
    assert not stale, f"allowed, but no statement before the yield takes anything any more (delete the entry): {stale}"


def test_each_owed_entry_names_a_real_context_manager():
    for (rel, name), lane in _OWED.items():
        tree = ast.parse((_SRC / rel).read_text(encoding="utf-8"))
        assert any(_is_cm(fn) and fn.name == name for fn in ast.walk(tree)), f"{rel}::{name} ({lane}) is not a @contextmanager any more: delete the owed entry"  # type: ignore[attr-defined]
    assert not set(_OWED) & set(_ALLOWED), "an entry is both allowed and owed"


def _check_owed_if_present(table: dict[tuple[str, str], str], found: dict[tuple[str, str], list[str]]) -> None:
    for (rel, name), lane in table.items():
        path = _SRC / rel
        if not path.exists():
            continue  # a tree without that file (or that PR): nothing is owed yet
        defined = [fn for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name]
        if not defined:
            continue
        assert any(_is_cm(fn) for fn in defined), f"{rel}::{name} ({lane}) exists but is not a @contextmanager: delete the owed entry"
        if (rel, name) not in found:
            warnings.warn(f"{rel}::{name} ({lane}) no longer takes anything before its try: delete the _OWED_IF_PRESENT entry", stacklevel=2)


def test_each_owed_if_present_entry_is_a_context_manager_where_it_exists():
    assert not set(_OWED_IF_PRESENT) & (set(_ALLOWED) | set(_OWED)), "an entry is in two tables"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a stale entry is reported by the check itself; here only the failures count
        _check_owed_if_present(_OWED_IF_PRESENT, _scan())


def test_an_owed_if_present_entry_that_was_converted_is_reported_not_failed():
    converted = {("database/corpus_lease.py", "corpus_lease"): "a context manager that takes inside its try"}
    with pytest.warns(UserWarning, match="delete the _OWED_IF_PRESENT entry"):
        _check_owed_if_present(converted, _scan())


def test_an_owed_if_present_entry_that_is_not_a_context_manager_fails():
    not_a_cm = {("database/corpus_lease.py", "active_leases"): "a plain function"}
    with pytest.raises(AssertionError, match="is not a @contextmanager"):
        _check_owed_if_present(not_a_cm, _scan())


def test_an_owed_if_present_entry_for_a_missing_function_or_file_is_fine():
    _check_owed_if_present({("database/corpus_lease.py", "not_there"): "x", ("no/such_file.py", "f"): "y"}, _scan())


@pytest.mark.parametrize("key", sorted(_ALLOWED))
def test_each_allowed_entry_states_its_reason(key):
    assert len(_ALLOWED[key]) > 20, f"{key}: a reason, not a label"


# --- the scan itself, on shapes -------------------------------------------------------------------------------------------


_SHAPES = '''
from contextlib import contextmanager

@contextmanager
def takes_before_try():
    _LOCK.exclusive(5)
    try:
        yield
    finally:
        _LOCK.release()

@contextmanager
def takes_inside_try():
    try:
        _LOCK.exclusive(5)
        yield
    finally:
        _LOCK.release()

@contextmanager
def queries_only():
    before = _LOCK.held_here()
    t0 = time.monotonic()
    try:
        yield
    finally:
        pass

@contextmanager
def sets_a_global_before_try():
    _STATE.flag = True
    try:
        yield
    finally:
        _STATE.flag = False

@contextmanager
def holds_a_with_before_try():
    with _LOCK:
        _COUNT["n"] = 1
    try:
        yield
    finally:
        pass

def not_a_context_manager():
    _LOCK.exclusive(5)
    yield
'''


def test_the_scan_reads_shapes_correctly():
    assert set(pre_yield_takers(_SHAPES)) == {"takes_before_try", "sets_a_global_before_try", "holds_a_with_before_try"}
