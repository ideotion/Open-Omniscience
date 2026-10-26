"""Audit 0.5.0 (A-012 part 2): every loop in ``src/database`` whose back-edge sits outside an exception-table entry AND that has a ``with``, a
``try/finally`` or an ``except BaseException`` / ``except KeyboardInterrupt`` around it in the SAME scope is listed here with the reason an interrupt cannot
reach it.

THE READING (R162, R163, R165). On CPython 3.13 a loop whose last statement is a bare ``if`` leaves its ``JUMP_BACKWARD`` between two
exception-table entries, so a ``KeyboardInterrupt`` landing there skips the cleanup around it. Only the MAIN thread is sent one, and only
until ``serve`` installs its signal handlers; a daemon or job thread never gets one (R165) and the event loop's handlers are uvicorn's.
tests/test_init_db_loops_survive_an_interrupt.py pins the loops ``init_db`` runs on the main thread (converted to the guard-clause form). THIS file
pins the rest of the package, so a new loop of this shape is classified by whoever writes it instead of found by the next audit.

THREE KINDS OF FLAGGED HEAD, only the third listed. (A) No cleanup around the loop in the same scope: CPython inlines a comprehension with a cleanup
entry of its own that restores the function's locals, which is all the helper sees, and a skipped back-edge there skips nothing. (B) Only an
``except Exception`` (or a narrower tuple): ``KeyboardInterrupt`` is not an ``Exception``, so that handler would not run for it either way. (C) A
``with`` (a lock, a connection, a file), a ``try/finally``, or a handler for ``BaseException`` or ``KeyboardInterrupt``: the cleanup the back-edge can
skip. Only the ``body`` of those counts: a loop in a ``finally`` block, in a handler or in an ``else`` is not protected by the ``try`` it sits in
(a ``finally`` still covers a handler's or an ``else``'s statements), and a comprehension in a ``with`` item runs before the ``with`` is entered. A
caller's ``with`` is another code object and does not count: an interrupt leaves the callee normally. Module bodies and class bodies are scopes like
any other (import time runs on the main thread before any handler is installed); a generator expression or a lambda is its own frame, and the
interrupt reaches its consumer instead.

WHAT THE WORKER-ONLY CLASSIFICATION RESTS ON. Each reason below was written from the callers, found by grep, and from the thread that runs them; the thread
starts were NOT traced line by line. (Inferred, not proven. The review of this file found two rows wrong on exactly that ground, ``corpus_lease.active_leases`` and
``pool_watch._live_rows``, reached from a main thread by ``release_run_fresh_restore`` and by a pool-checkout timeout; both were converted to the guard-clause
form instead of being listed. A row's reason holds for the whole function: a new loop added to a listed function passes unseen, so the person adding it
reads the reason. ``tests/test_worker_only_callers_pinned.py`` pins callers transitively and is the stronger check for the two functions it covers.)
The scripts/ callers: scripts/signal_leak_probe.py is a dev probe. The reading is of CPython 3.13 bytecode, like its siblings.

A row fails when it is MISSING (a new cleanup-covered head: classify it, or write it in the guard-clause form) and when it is STALE (the scope no longer
has such a head: delete the row, so the list never says something that stopped being true). Rows are keyed by the scope's qualified name, so two
methods of one name in one file are two rows."""

from __future__ import annotations

import ast
import builtins
import dis
import types
from collections.abc import Iterator
from pathlib import Path

from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = "src/database"

_WORKER = "worker-only"
_LOOP = "event-loop"

#: (file, qualified scope name) -> the reason. A reason starts with ``worker-only`` or ``event-loop`` and names who runs it.
_CLASS_C: dict[tuple[str, str], str] = {
    ("src/database/article_indexes.py", "_refresh_stats"):
        f"{_WORKER}: the article-list index build, a BackgroundJob thread",
    ("src/database/fts_reindex.py", "SearchReindexJobManager._park"):
        f"{_WORKER}: the search-reindex-job daemon thread",
    ("src/database/fts_reindex.py", "SearchReindexJobManager._run"):
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
_INLINED = (ast.ListComp, ast.DictComp, ast.SetComp)  # inlined into the enclosing frame on 3.12+
_OWN_FRAME = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda, ast.GeneratorExp)
_CATCHES_AN_INTERRUPT = frozenset({"BaseException", "KeyboardInterrupt"})
_TRIES = tuple(t for t in (ast.Try, getattr(ast, "TryStar", None)) if t is not None)


def _flagged_heads(text: str, filename: str) -> dict[str, set[int]]:
    """``{co_qualname: {head line}}`` for every loop head whose ``JUMP_BACKWARD`` is outside the exception entries that cover the head: the reading
    of :func:`tests.test_gates_survive_an_interrupt._uncovered_loop_heads`, for every code object of one compiled source at once."""
    out: dict[str, set[int]] = {}

    def walk(code: types.CodeType) -> Iterator[types.CodeType]:
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
                out.setdefault(code.co_qualname, set()).add(head.positions.lineno or 0 if head.positions else 0)
    return out


def _scopes(tree: ast.Module) -> dict[str, ast.AST]:
    """``{co_qualname: node}`` for the module body, every class body and every function, named as CPython names their code objects."""
    out: dict[str, ast.AST] = {"<module>": tree}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualname = prefix + child.name
                out[qualname] = child
                visit(child, qualname + (".<locals>." if not isinstance(child, ast.ClassDef) else "."))
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def _own_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """The nodes that run in ``scope``'s own frame: not those of a nested function, class, lambda or generator expression."""
    for child in ast.iter_child_nodes(scope):
        if isinstance(child, _OWN_FRAME):
            continue
        yield child
        yield from _own_nodes(child)


def _trail(parent: ast.AST, node: ast.AST) -> list[tuple[ast.AST, str]] | None:
    """The ``(ancestor, field)`` pairs from ``parent`` down to ``node`` within one frame, or None."""
    for field, value in ast.iter_fields(parent):
        for child in value if isinstance(value, list) else [value]:
            if not isinstance(child, ast.AST):
                continue
            if child is node:
                return [(parent, field)]
            if isinstance(child, _OWN_FRAME):
                continue
            found = _trail(child, node)
            if found is not None:
                return [(parent, field), *found]
    return None


def _caught_names(handler: ast.ExceptHandler) -> set[str] | None:
    """The exception names a handler lists, or None for a bare ``except:``."""
    if handler.type is None:
        return None
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    names: set[str] = set()
    for n in nodes:
        name = n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute) else "?"
        # A handler named through a variable or a constant (``except _INTERRUPTS``) may catch anything: read it as catching, so the head is listed.
        names.add("KeyboardInterrupt" if name == "?" or (isinstance(n, ast.Name) and not hasattr(builtins, name) and (name[0] == "_" or name.isupper())) else name)
    return names


def _cleanup_around(scope: ast.AST, node: ast.AST) -> bool:
    """Whether, inside ``scope`` only, ``node`` sits in the body of a ``with``, in a ``try`` with a ``finally`` (its body, a handler or its ``else``), or in
    the body of a ``try`` with a handler that also catches ``BaseException``, ``KeyboardInterrupt`` or everything."""
    for anc, field in _trail(scope, node) or []:
        if isinstance(anc, (ast.With, ast.AsyncWith)) and field == "body":
            return True
        if isinstance(anc, _TRIES):
            if anc.finalbody and field in ("body", "handlers", "orelse"):
                return True
            if field == "body":
                for handler in anc.handlers:
                    caught = _caught_names(handler)
                    if caught is None or caught & _CATCHES_AN_INTERRUPT:
                        return True
    return False


def _cleanup_covered(text: str, filename: str) -> set[str]:
    """The qualified names of the scopes with a flagged head that has a cleanup construct around it in the same scope. A head no AST node can be matched
    to, and a code object no scope has a name for, is counted as covered: the classifier fails closed."""
    flagged = _flagged_heads(text, filename)
    if not flagged:
        return set()
    scopes = _scopes(ast.parse(text))
    covered: set[str] = set()
    for qualname, heads in flagged.items():
        scope = scopes.get(qualname)
        if scope is None:
            if qualname.endswith(("<genexpr>", "<lambda>")):  # its own frame: the interrupt is caught at its consumer
                continue
            covered.add(qualname)  # a name no scope has (a ``global`` def, say): fail closed
            continue
        for lineno in heads:
            matched = False
            for node in _own_nodes(scope):
                if isinstance(node, _INLINED):  # may span lines: its head is the ``for`` clause, wherever it sits
                    hit = node.lineno <= lineno <= (node.end_lineno or node.lineno)
                elif isinstance(node, _LOOPS):
                    hit = lineno == node.lineno or (isinstance(node, ast.While) and lineno == node.body[0].lineno)
                else:
                    continue
                if hit:
                    matched = True
                    if _cleanup_around(scope, node):
                        covered.add(qualname)
            if not matched:
                covered.add(qualname)
    return covered


def _package_class_c() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted((_ROOT / _PACKAGE).glob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        for qualname in _cleanup_covered(path.read_text(encoding="utf-8"), rel):
            found.add((rel, qualname))
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
    ratchet trusts, so a row it does not flag any more is stale whatever this file says. (The helper names a scope by its bare name.)"""
    for rel, qualname in sorted(_CLASS_C):
        name = qualname.rsplit(".", 1)[-1]
        assert _uncovered_loop_heads(rel, name), f"{rel}::{qualname} has no uncovered loop head under the shared helper any more"


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

def under_keyboard_interrupt(items):
    out = []
    try:
        for x in items:
            if x:
                out.append(x)
    except (KeyboardInterrupt, SystemExit):
        out.clear()
        raise
    return out

_INTERRUPTS = (KeyboardInterrupt,)

def under_an_aliased_handler(items):
    out = []
    try:
        for x in items:
            if x:
                out.append(x)
    except _INTERRUPTS:
        raise
    return out

def outer():
    global later
    def later(items):
        with LOCK:
            for x in items:
                if x:
                    pass

def comprehension_under_with(items):
    with LOCK:
        return [x for x in items if x]

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

def guard_clause_under_with(items):
    out = []
    with LOCK:
        for x in items:
            if not x:
                continue
            out.append(x)
    return out

def loop_in_the_finally_body(items):
    out = []
    try:
        out.append(1)
    finally:
        for x in items:
            if x:
                out.append(x)
    return out

def comprehension_in_a_with_item(items):
    with open([x for x in items if x][0]):
        pass

class First:
    def run(self, items):
        with LOCK:
            return [x for x in items if x]

class Second:
    def run(self, items):
        return [x for x in items if x]

with LOCK:
    for x in range(3):
        if x:
            pass
'''


def test_the_classifier_sees_the_shapes_it_claims_to():
    """Anti-vacuity, so a green run means something: the cleanup-covered shapes are found and the harmless ones are not."""
    covered = _cleanup_covered(_SHAPES, "shapes.py")
    assert covered == {
        "under_with",
        "under_finally",
        "under_base_exception",
        "under_keyboard_interrupt",
        "under_an_aliased_handler",
        "later",
        "comprehension_under_with",
        "First.run",
        "<module>",
    }, covered
    flagged = _flagged_heads(_SHAPES, "shapes.py")
    for name in ("under_exception_only", "comprehension_without_cleanup", "loop_in_the_finally_body", "comprehension_in_a_with_item", "Second.run"):
        assert name in flagged, (name, flagged)
    assert "guard_clause_under_with" not in flagged, flagged


def test_the_package_holds_what_the_table_says_it_does():
    assert len(_CLASS_C) >= 8
    assert len(_package_class_c()) >= 8
