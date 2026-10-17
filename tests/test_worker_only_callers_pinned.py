"""The "worker-only" loops of the interrupt-safety allowlist are pinned to the callers that make them worker-only (R162 item 2, R163).

``tests/test_gates_survive_an_interrupt.py`` exempts a locked or try/finally loop from the R161 shape when every way in is a worker thread (only the main
thread receives a KeyboardInterrupt), citing a report. A report is read once; a new caller added next month is not. This test rebuilds, from the
source, the callers of each exempt function, transitively, and requires:

  1. NO main-thread entry among them: an ``async def`` (the event loop), a module under ``scripts/``, or a call at a module's top level (the ``__main__``
     block, or import time). Any of those fails the test, naming the call, and the loop is converted instead of exempted.
  2. EXACTLY the set of functions listed in :data:`_PINNED`. A new caller is not necessarily wrong, but it has to be read: the test fails until the
     pin is edited, and the edit is the review. A pinned function that is gone fails too, so the pins cannot go stale.

What this is NOT: the call graph is read by NAME (a private ``_name`` only within its own file, a public name across the repo), nothing is imported or run,
and calls made through a registry, ``getattr``, a stored callable or a decorator are not seen. The one stored callable on these paths is pinned by hand
(:data:`_ALIASES`, verified against the assignment). A fuller graph with receiver types is ``main_thread_reach.py`` in the RC2 diagnostics tools; it needs a
minute and lives outside the repo, which is why this narrower check is the one CI can run. The four event-loop entries are not covered here: their names
(``record``, ``start``, ``notes``) are too common to follow by name, and they are exempt for a different reason (tests/test_event_loop_signal_exemption.py).
"""

from __future__ import annotations

import ast
import collections
from collections.abc import Mapping
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# A call that hands a function to another thread: the name given to it is a worker boundary, not a path.
_SPAWNERS = frozenset({"submit", "run_in_executor", "to_thread", "run_in_threadpool", "run_heavy", "BackgroundJob", "register_job", "Thread", "Timer", "Process"})

# node -> the simple name under which it is called, where it is stored in a variable first (verified by :func:`_alias_assigned`).
_ALIASES = {"src/scheduler/runner.py::BackgroundScheduler._default_run_once": "_run_once_fn"}
_ALIAS_ASSIGNMENT = ("src/scheduler/runner.py", "_run_once_fn", "_default_run_once")


def read_sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for base in ("src", "scripts"):
        for path in sorted((_ROOT / base).rglob("*.py")):
            if "static" in path.parts:
                continue
            out[path.relative_to(_ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return out


class Graph:
    def __init__(self, sources: Mapping[str, str]) -> None:
        self.funcs: dict[str, tuple[bool, tuple[str, ...]]] = {}  # id -> (is_async, decorators)
        self.calls: dict[str, set[str]] = collections.defaultdict(set)  # simple name -> ids of the functions that call it
        self.starts: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)  # simple name -> (starter id, spawner)
        self.module_calls: dict[str, set[str]] = collections.defaultdict(set)  # simple name -> files calling it at top level
        for rel, text in sources.items():
            tree = ast.parse(text)
            self._visit(tree, rel, [])
            for stmt in tree.body:
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._scan(stmt, rel, None)  # a class body's own statements too: they run at import

    @staticmethod
    def _call_name(call: ast.Call) -> str | None:
        f = call.func
        return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)

    def _scan(self, node: ast.AST, rel: str, owner: str | None) -> None:
        todo = [node]
        while todo:
            n = todo.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # a nested def has its own id
            if isinstance(n, ast.Call):
                name = self._call_name(n)
                if name:
                    (self.calls[name].add(owner) if owner else self.module_calls[name].add(rel))
                    if name in _SPAWNERS:
                        for arg in [*n.args, *(k.value for k in n.keywords)]:
                            given = arg.id if isinstance(arg, ast.Name) else (arg.attr if isinstance(arg, ast.Attribute) else None)
                            if given:
                                self.starts[given].add((owner or f"{rel}::<module>", name))
            todo.extend(ast.iter_child_nodes(n))

    def _visit(self, node: ast.AST, rel: str, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = [*stack, child.name]
                ident = f"{rel}::{'.'.join(inner)}"
                self.funcs[ident] = (isinstance(child, ast.AsyncFunctionDef), tuple(ast.unparse(d) for d in child.decorator_list))
                for stmt in child.body:
                    self._scan(stmt, rel, ident)
                self._visit(child, rel, inner)
            elif isinstance(child, ast.ClassDef):
                self._visit(child, rel, [*stack, child.name])
            else:
                self._visit(child, rel, stack)

    def _route_kind(self, ident: str) -> str | None:
        is_async, decorators = self.funcs[ident]
        if any(d.startswith(("router.", "app.")) for d in decorators):
            return "async route" if is_async else "sync route"
        return "async def" if is_async else None

    def closure(self, entry: str) -> tuple[list[str], list[str], list[str], list[str]]:
        """``(functions that can reach entry, worker boundaries met, main-thread entries met, open ends)``."""
        nodes, seen = [entry], {entry}
        workers: set[str] = set()
        main: set[str] = set()
        has_way_in: set[str] = set()
        i = 0
        while i < len(nodes):
            node = nodes[i]
            i += 1
            rel, qual = node.split("::")
            own = qual.split(".")[-1]
            for starter, how in self.starts.get(own, ()):
                if own.startswith("_") and starter.split("::")[0] != rel:
                    continue
                workers.add(f"{node} started by {how} in {starter}")
                has_way_in.add(node)
            for used_as in {own, _ALIASES.get(node, own)}:
                if not used_as.startswith("_"):
                    for f in self.module_calls.get(used_as, ()):
                        main.add(f"{node} called at the top level of {f}")
                        has_way_in.add(node)
                for caller in self.calls.get(used_as, ()):
                    cfile = caller.split("::")[0]
                    if used_as.startswith("_") and cfile != rel:
                        continue
                    has_way_in.add(node)
                    kind = self._route_kind(caller)
                    if kind == "sync route":
                        workers.add(f"{caller} (sync route) calls {node}")
                    elif kind:
                        main.add(f"{caller} ({kind}) calls {node}")
                    elif cfile.startswith("scripts/"):
                        main.add(f"{caller} (a script) calls {node}")
                    elif caller not in seen:
                        seen.add(caller)
                        nodes.append(caller)
        open_ends = [n for n in nodes if n not in has_way_in]
        return sorted(nodes), sorted(workers), sorted(main), sorted(open_ends)


def _alias_assigned(sources: Mapping[str, str]) -> bool:
    rel, target_attr, value_attr = _ALIAS_ASSIGNMENT
    for node in ast.walk(ast.parse(sources[rel])):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == target_attr for t in node.targets)
            and value_attr in ast.unparse(node.value)
        ):
            return True
    return False


# entry (file::function, as the allowlist's functions are named) -> every function that can reach it by name, entry first-sorted
_PINNED: dict[str, tuple[str, ...]] = {
    "src/analytics/keyword_fold.py::fold_page": (
        "src/analytics/keyword_fold.py::KeywordFoldJobManager._fold_phase",
        "src/analytics/keyword_fold.py::KeywordFoldJobManager._run",
        "src/analytics/keyword_fold.py::fold_page",
    ),
    "src/analytics/source_topics.py::_apply_source_topics_on_a_shared_session": (
        "src/analytics/source_topics.py::_apply_source_topics_on_a_shared_session",
        "src/analytics/source_topics.py::apply_source_topics",
        "src/analytics/source_topics.py::run_auto_source_enrichment",
        "src/scheduler/runner.py::BackgroundScheduler._default_run_once",
        "src/scheduler/runner.py::BackgroundScheduler._do_run",
        "src/scheduler/runner.py::BackgroundScheduler._loop",
        "src/scheduler/runner.py::BackgroundScheduler._loop_recorded",
    ),
    "src/database/article_indexes.py::_refresh_stats": (
        "src/database/article_indexes.py::_refresh_stats",
        "src/database/article_indexes.py::_worker",
        "src/database/article_indexes.py::build_missing",
    ),
    "src/database/maintenance.py::maybe_incremental_vacuum": (
        "src/database/maintenance.py::maybe_incremental_vacuum",
        "src/scheduler/maintenance.py::run_idle_maintenance",
        "src/scheduler/runner.py::BackgroundScheduler._loop",
        "src/scheduler/runner.py::BackgroundScheduler._loop_recorded",
        "src/scheduler/runner.py::BackgroundScheduler._run_off_peak_maintenance",
    ),
    "src/ai_layer/coordinator.py::run_coordinator": (
        "src/ai_layer/coordinator.py::run_coordinator",
        "src/api/diagnostics/ai_coordinator.py::_ai_coordinator_worker",
    ),
}


# --- the checks ---------------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return read_sources()


@pytest.fixture(scope="module")
def graph(sources) -> Graph:
    return Graph(sources)


@pytest.mark.parametrize("entry", sorted(_PINNED))
def test_no_main_thread_entry_reaches_a_worker_only_function(graph, entry):
    nodes, workers, main, open_ends = graph.closure(entry)
    assert not main, "a main-thread entry now reaches a function the allowlist calls worker-only: convert its loop instead (R163):\n  " + "\n  ".join(main)
    assert workers, f"{entry}: no worker boundary was found on any way in, so nothing shows it is worker-only"
    assert not open_ends, f"these have no caller and no thread start the scan can see (used as a value? pin it in _ALIASES after reading it): {open_ends}"
    assert tuple(nodes) == tuple(sorted(_PINNED[entry])), (
        f"the functions that can reach {entry} changed; read the new caller, then edit _PINNED:\n  now: {nodes}\n  pinned: {sorted(_PINNED[entry])}"
    )


def test_the_pins_cover_exactly_the_worker_only_allowlist():
    from tests.test_gates_survive_an_interrupt import _worker_only_loops

    ids = {f"{Path(fn.__code__.co_filename).resolve().relative_to(_ROOT).as_posix()}::{fn.__qualname__}" for fn, _reason in _worker_only_loops().values()}
    inside_a_pinned_closure = {i for i in ids if any(i in pinned for pinned in _PINNED.values())}  # apply_source_topics is inside its inner function's closure
    unpinned = sorted(ids - set(_PINNED) - inside_a_pinned_closure)
    assert not unpinned, f"worker-only allowlist entries without a pin: {unpinned}"
    stale = sorted(set(_PINNED) - ids)
    assert not stale, f"pins whose function is not in the worker-only allowlist any more: {stale}"


def test_the_stored_callable_is_still_assigned_as_pinned(sources):
    assert _alias_assigned(sources), "the scheduler no longer stores _default_run_once in _run_once_fn: re-read how it is called and edit _ALIASES"


# --- the scan, on planted shapes ------------------------------------------------------------------------------------------------------

_BASE = {
    "src/a.py": "def target():\n    pass\n\ndef _worker():\n    target()\n\ndef start():\n    import threading\n    threading.Thread(target=_worker).start()\n",
}


def _closure(extra: Mapping[str, str]):
    return Graph({**_BASE, **extra}).closure("src/a.py::target")


def test_a_worker_only_function_reads_as_worker_only():
    nodes, workers, main, open_ends = _closure({})
    assert nodes == ["src/a.py::_worker", "src/a.py::target"] and workers and not main and not open_ends


def test_a_script_that_calls_it_is_a_main_thread_entry():
    _n, _w, main, _o = _closure({"scripts/run.py": "from src.a import target\n\ndef main():\n    target()\n"})
    assert main and "scripts/run.py" in main[0]


def test_a_module_level_call_is_a_main_thread_entry():
    _n, _w, main, _o = _closure({"src/b.py": "from src.a import target\ntarget()\n"})
    assert main and "top level of src/b.py" in main[0]


def test_an_async_def_that_calls_it_is_a_main_thread_entry():
    _n, _w, main, _o = _closure({"src/b.py": "from src.a import target\n\nasync def handler():\n    target()\n"})
    assert main and "async def" in main[0]


def test_a_sync_route_that_calls_it_is_a_worker():
    _n, workers, main, _o = _closure({"src/b.py": "from src.a import target\n\n@router.get('/x')\ndef handler():\n    target()\n"})
    assert not main and any("sync route" in w for w in workers)


def test_a_new_plain_caller_changes_the_closure():
    nodes, _w, main, _o = _closure({"src/b.py": "from src.a import target\n\ndef helper():\n    target()\n"})
    assert "src/b.py::helper" in nodes and not main and any("helper" in n for n in nodes)


def test_a_private_name_is_followed_only_inside_its_own_file():
    nodes, _w, _m, _o = _closure({"src/b.py": "def _worker():\n    pass\n\ndef unrelated():\n    _worker()\n"})
    assert "src/b.py::unrelated" not in nodes


def test_a_function_nobody_calls_is_an_open_end():
    _n, _w, _m, open_ends = Graph({"src/a.py": "def target():\n    pass\n"}).closure("src/a.py::target")
    assert open_ends == ["src/a.py::target"]
