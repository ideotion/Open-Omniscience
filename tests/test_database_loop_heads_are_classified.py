"""Audit 0.5.0 (A-012 part 2): every loop in ``src/database`` whose back-edge sits outside an exception-table entry AND that has a ``with``, a
``try/finally`` or an ``except BaseException`` around it in the SAME function is listed here with the reason an interrupt cannot reach it.

THE READING (R162, R163, R165). On CPython 3.13 a loop whose last statement is a bare ``if`` leaves its ``JUMP_BACKWARD`` between two
exception-table entries, so a ``KeyboardInterrupt`` landing there skips the cleanup around it. Only the MAIN thread is sent one, and only
until ``serve`` installs its signal handlers; a daemon or job thread never gets one (R165) and the event loop's handlers are uvicorn's.
tests/test_init_db_loops_survive_an_interrupt.py pins the loops ``init_db`` runs on the main thread (converted to the guard-clause form). THIS file
pins the rest of the package, so a new loop of this shape is classified by whoever writes it instead of found by the next audit.

THREE KINDS OF FLAGGED ROW, only the third listed. (A) No cleanup around the loop in the same function: CPython inlines a comprehension with a cleanup
entry of its own that restores the function's locals, which is all the helper sees, and a skipped back-edge there skips nothing. (B) Only an
``except Exception`` (or a narrower tuple): ``KeyboardInterrupt`` is not an ``Exception``, so that handler would not run for it either way. (C) A
``with`` (a lock, a connection, a file), a ``try/finally`` or an ``except BaseException``: the cleanup the back-edge can skip. A caller's ``with`` is another
code object and does not count: an interrupt leaves the callee normally.

WHAT THE WORKER-ONLY CLASSIFICATION RESTS ON. Each reason below was written from the callers, found by grep, and from the thread that runs them; the thread
starts were NOT traced line by line. The one caller outside the server is scripts/signal_leak_probe.py, a dev probe. (Inferred, not proven: a CLI or script
entry that reaches one of these functions on the main thread would make its row wrong, and the fix then is the guard-clause form, as in #1489.)
The full table is /mnt/project-files/osm-lane/audit12-part2-heads-table-2026-10-26.md.

A row fails when it is MISSING (a new cleanup-covered head: classify it, or write it in the guard-clause form) and when it is STALE (the function no longer
has such a head: delete the row, so the list never says something that stopped being true)."""

from __future__ import annotations

import ast
import dis
import types
from pathlib import Path

from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = "src/database"

_WORKER = "worker-only"
_LOOP = "event-loop"

#: (file, function) -> the reason. A reason starts with ``worker-only`` or ``event-loop`` and names who runs it.
_CLASS_C: dict[tuple[str, str], str] = {
    ("src/database/corpus_lease.py", "active_leases"):
        f"{_WORKER}: the scheduler's memstop, the oo-offline-maintenance thread, and repair's quiescence wait (a repair job thread)",
    ("src/database/pool_watch.py", "_live_rows"):
        f"{_LOOP}/{_WORKER}: the checked_out / standing_holders readers (diagnostics, the writer, the memory budget), on request threads or the event loop",
    ("src/database/article_indexes.py", "_refresh_stats"):
        f"{_WORKER}: the article-list index build, a BackgroundJob thread",
    ("src/database/fts_reindex.py", "_park"):
        f"{_WORKER}: the search-reindex-job daemon thread",
    ("src/database/fts_reindex.py", "_run"):
        f"{_WORKER}: the search-reindex-job daemon thread (threading.Thread(target=self._run, daemon=True))",
    ("src/database/maintenance.py", "maybe_incremental_vacuum"):
        f"{_WORKER}: the scheduler's maintenance thread (src/scheduler/maintenance.py), not an init_db step",
    ("src/database/query.py", "grouped_counts"):
        f"{_LOOP}/{_WORKER}: analytics.emergence, on request or job threads",
    ("src/database/repair.py", "_disk_unread_pages"):
        f"{_WORKER}: the repair job, started from the boot-sequence daemon thread",
    ("src/database/repair.py", "_swap"):
        f"{_WORKER}: the repair job, started from the boot-sequence daemon thread",
    ("src/database/verify.py", "inspect_file"):
        f"{_WORKER}: verify's own re-inspect, salvage and damage, all on their daemon threads",
    ("src/database/verify.py", "_recheck_main"):
        f"{_WORKER}: the oo-database-recheck daemon thread",
    ("src/database/verify.py", "_reread_main"):
        f"{_WORKER}: the oo-database-reread daemon thread",
}

_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_COMPREHENSIONS = (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _flagged_heads(text: str, filename: str) -> dict[str, set[tuple[int, str]]]:
    """``{function name: {(head line, head text)}}`` for every loop head whose ``JUMP_BACKWARD`` is outside the exception entries that cover the head: the reading
    of :func:`tests.test_gates_survive_an_interrupt._uncovered_loop_heads`, for every function of one compiled source at once."""
    lines = text.splitlines()
    out: dict[str, set[tuple[int, str]]] = {}

    def walk(code: types.CodeType):
        yield code
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                yield from walk(const)

    for code in walk(compile(text, filename, "exec")):
        ranges = [(e.start, e.end) for e in dis.Bytecode(code).exception_entries]
        instructions = list(dis.get_instructions(code))
        for ins in instructions:
            if ins.opname != "JUMP_BACKWARD" or any(start <= ins.offset < end for start, end in ranges):
                continue
            if any(start <= ins.argval < end for start, end in ranges):
                head = next(i for i in instructions if i.offset == ins.argval)
                lineno = head.positions.lineno if head.positions else None
                out.setdefault(code.co_name, set()).add((lineno or 0, lines[lineno - 1].strip() if lineno else "?"))
    return out


def _cleanup_around(fn: ast.AST, node: ast.AST) -> bool:
    """Whether, inside ``fn`` only (never across a nested function), ``node`` sits in a ``with``, a ``try`` with a ``finally``, or a ``try`` with a
    handler that also catches ``BaseException`` or everything."""

    def path_to(parent: ast.AST, trail: list[ast.AST]) -> list[ast.AST] | None:
        for child in ast.iter_child_nodes(parent):
            if child is node:
                return trail
            if isinstance(child, _FUNCTIONS):
                continue
            found = path_to(child, [*trail, child])
            if found is not None:
                return found
        return None

    for anc in path_to(fn, [fn]) or []:
        if isinstance(anc, (ast.With, ast.AsyncWith)):
            return True
        if isinstance(anc, ast.Try):
            if anc.finalbody:
                return True
            for handler in anc.handlers:
                if handler.type is None or "BaseException" in ast.dump(handler.type):
                    return True
    return False


def _cleanup_covered(text: str, filename: str) -> set[str]:
    """The names of the functions with a flagged head that has a cleanup construct around it in the same function. A head no AST node can be matched to is
    counted as covered: the classifier fails closed."""
    flagged = _flagged_heads(text, filename)
    if not flagged:
        return set()
    tree = ast.parse(text)
    covered: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name not in flagged:
            continue
        for lineno, _text in flagged[fn.name]:
            matched = False
            for node in ast.walk(fn):
                if isinstance(node, _COMPREHENSIONS):  # may span lines: its head is the ``for`` clause, wherever it sits
                    hit = node.lineno <= lineno <= (node.end_lineno or node.lineno)
                elif isinstance(node, _LOOPS):
                    hit = lineno == node.lineno or (isinstance(node, ast.While) and lineno == node.body[0].lineno)
                else:
                    continue
                if hit:
                    matched = True
                    if _cleanup_around(fn, node):
                        covered.add(fn.name)
            if not matched:
                covered.add(fn.name)
    return covered


def _package_class_c() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted((_ROOT / _PACKAGE).glob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        for name in _cleanup_covered(path.read_text(encoding="utf-8"), rel):
            found.add((rel, name))
    return found


def test_every_cleanup_covered_loop_head_in_the_package_is_classified_and_none_is_stale():
    found = _package_class_c()
    listed = set(_CLASS_C)
    missing = sorted(found - listed)
    stale = sorted(listed - found)
    assert not missing, (
        f"a loop in src/database has its back-edge outside the with/try/finally around it and is not classified: {missing}. "
        "Write it in the guard-clause form (`if cond: continue`, then the body; see tests/test_init_db_loops_survive_an_interrupt.py), "
        "or, if only a worker or job thread runs it, add a row here with the reason."
    )
    assert not stale, f"these rows no longer have such a head; delete them: {stale}"


def test_every_row_names_who_runs_it():
    for key, reason in _CLASS_C.items():
        assert reason.startswith((_WORKER, _LOOP)), (key, reason)
        assert len(reason) > 40, (key, reason)


def test_every_row_still_flags_under_the_projects_own_helper():
    """The classifier above is this file's own reading; the project's helper (tests/test_gates_survive_an_interrupt.py) is the one every other
    ratchet trusts, so a row it does not flag any more is stale whatever this file says."""
    for rel, name in sorted(_CLASS_C):
        assert _uncovered_loop_heads(rel, name), f"{rel}::{name} has no uncovered loop head under the shared helper any more"


_SHAPES = '''
import threading
LOCK = threading.Lock()

def under_with(items):
    out = []
    with LOCK:
        for x in items:
            if x:
                out.append(x)
    return out

def under_finally(items):
    out = []
    try:
        for x in items:
            if x:
                out.append(x)
    finally:
        out.clear()
    return out

def under_base_exception(items):
    out = []
    try:
        for x in items:
            if x:
                out.append(x)
    except BaseException:
        raise
    return out

def under_exception_only(items):
    out = []
    try:
        for x in items:
            if x:
                out.append(x)
    except Exception:
        raise
    return out

def comprehension_without_cleanup(items):
    return [x for x in items if x]

def comprehension_under_with(items):
    with LOCK:
        return [x for x in items if x]

def guard_clause_under_with(items):
    out = []
    with LOCK:
        for x in items:
            if not x:
                continue
            out.append(x)
    return out
'''


def test_the_classifier_sees_the_shapes_it_claims_to():
    """Anti-vacuity, so a green run means something: the cleanup-covered shapes are found and the harmless ones are not."""
    covered = _cleanup_covered(_SHAPES, "shapes.py")
    assert covered == {"under_with", "under_finally", "under_base_exception", "comprehension_under_with"}, covered
    flagged = _flagged_heads(_SHAPES, "shapes.py")
    assert "under_exception_only" in flagged and "comprehension_without_cleanup" in flagged, flagged
    assert "guard_clause_under_with" not in flagged, flagged


def test_the_package_holds_what_the_table_says_it_does():
    assert len(_CLASS_C) >= 10
    assert len(_package_class_c()) >= 10
