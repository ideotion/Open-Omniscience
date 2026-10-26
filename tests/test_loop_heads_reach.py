"""Audit 0.5.0 (A-012 part 3): a loop outside ``src/database`` whose back-edge sits outside the ``with`` / ``try``-``finally`` around it must not be reachable
from a MAIN-THREAD entry (R162, R163).

THE READING. On CPython 3.13 a loop (or an inlined filtered comprehension) whose last statement is a bare ``if`` leaves its ``JUMP_BACKWARD`` outside the
exception-table entry of an enclosing ``with`` or ``try``/``finally``, so a ``KeyboardInterrupt`` there skips the cleanup. Only the main thread is sent one, and
only until ``serve`` installs its signal handlers (R165: the event loop's handlers are uvicorn's). tests/test_database_loop_heads_are_classified.py lists the
scopes of ``src/database`` with a reason each, and tests/test_database_worker_only_pins.py pins eight of those to their callers. THIS file covers the rest of
``src/`` WITHOUT a hand-written reason per scope: it finds every such scope with the same classifier, computes who can reach it, and fails on a main-thread entry.
A scope nobody on the main thread reaches passes unlisted, so a new worker-only one costs nothing and a new main-thread one has to be converted (the guard-clause
form, or ``src.utils.interrupts.kept`` / ``kept_items`` for a filtered comprehension) or listed here ON PURPOSE.

WHAT COUNTS AS A MAIN-THREAD ENTRY. The project's console script (``[project.scripts]``), any function called at a module's top level (the ``__main__`` block, import
time), and a ``scripts/`` function (Q's Graph already treats these as main-thread). An ``async def`` is the event loop (R165). Five kinds are LISTED, never
failed: ``script`` (a dev or operator tool; the process ends on the interrupt), ``event-loop`` (R165), ``dev-tool`` (a harness under ``src/testing``), ``atexit``
and ``signal-handler`` (a registered handler runs on the main thread, after ``serve`` has installed its own). Anything
else is ``main:<entry>`` and fails.

WHAT THIS CANNOT DO, and the mark of it. The call graph is read by NAME (tests/test_worker_only_callers_pinned.py's Graph; nothing is imported or run). A call
through ``getattr``, a registry, a stored callable or a decorator is not seen. A name that is also a builtin or a common method (``update``, ``get``, ``run``,
``digest``) or is defined in three or more files is followed only inside its own file, because otherwise ``subprocess.run`` pulls in thousands of functions: that
UNDER-APPROXIMATES a real cross-file call through such a name. And two files that share a rarer name produce a path that is not a call: :data:`_DISMISSED` lists
those, each with the exact entries it dismisses AND the one colliding name they are owed to, so a NEW entry through the same scope still fails. A call that
resolves to ONE function through an import (``from x import f``, ``from x import f as _g``, ``import x as m`` then ``m.f()``), and a function handed to
``atexit.register`` or ``signal.signal``, ARE followed (:class:`_ResolvingGraph`), even when the name is a common one; a call through a re-export, an instance
attribute or a name assigned from another call is not. ``atexit`` and ``signal-handler`` entries are listed like the other kinds. A forward reachability with every ambiguous name expanded was
read once by hand when this file was written (16 extra rows, all collisions: ``subprocess.run`` in ``_run_ephemeral``, ``core_guard.engage`` calling its own
``status``); it is not rerun here.

The reading is of CPython 3.13 bytecode, like its siblings."""

from __future__ import annotations

import ast
import collections
import tomllib
from pathlib import Path

from tests.test_database_loop_heads_are_classified import _cleanup_covered
from tests.test_database_worker_only_pins import _LocalGraph
from tests.test_worker_only_callers_pinned import read_sources

_ROOT = Path(__file__).resolve().parents[1]

_COMMON_METHODS = frozenset(
    {"digest", "hexdigest", "read", "write", "close", "flush", "seek", "tell", "start", "stop", "join", "run", "get", "put", "wait", "clear", "submit", "result",
     "cancel", "connect", "execute", "commit", "rollback", "send", "recv", "open", "load", "dump", "loads", "dumps", "format", "step", "end", "status", "snapshot",
     "add", "observe", "lookup", "search", "build", "check", "parse", "main"}
)

_KINDS = frozenset({"script", "event-loop", "dev-tool", "atexit", "signal-handler"})

#: scope -> (the kinds of non-failing entry that reach it, and why that is fine). A scope reached by no listed kind and no main-thread entry is not here.
_LISTED: dict[str, tuple[frozenset[str], str]] = {
    "src/analytics/claim_bundle.py::verify_trail_bundle": (frozenset({"script"}), "scripts/verify_claim_trail.py, an operator tool that verifies one bundle and exits"),
    "src/backup/newsletter_export.py::_read_back": (frozenset({"script"}), "reached from the scale bench and the migration evidence scripts (dev tools)"),
    "src/backup/stream_backup.py::_emit_member": (frozenset({"script"}), "reached from the scale bench and the migration evidence scripts (dev tools)"),
    "src/backup/stream_backup.py::remember_snapshot_destination": (frozenset({"script"}), "reached from the scale bench and the migration evidence scripts (dev tools)"),
    "src/catalog/qualification_integrity.py::_confirm_applied_runs": (frozenset({"event-loop"}), "run_deferred_startup, called synchronously from the lifespan on the event loop (R165)"),
    "src/catalog/qualification_merge.py::rows_from_bundle_bytes": (frozenset({"script"}), "scripts/merge_source_qualification.py, an operator tool that merges one bundle and exits"),
    "src/entities/gazetteer_build.py::read_places": (frozenset({"script"}), "scripts/build_place_gazetteer.py, a build tool"),
    "src/ingest/pipeline.py::ingest_source": (frozenset({"script", "dev-tool"}), "src/testing/collect_soak.py and the collection bench script, harnesses that run one pass and exit"),
    "src/monitoring/expedition.py::_memory": (frozenset({"script"}), "scripts/country_migration_evidence.py's p0 step (build_p0_report, session_forensics, expedition.digest), an operator evidence tool that ends on the interrupt"),
    "src/monitoring/swap.py::swap_readings": (frozenset({"script", "dev-tool"}), "the collection bench script and the soak harness reach it through MemoryGuard.poll (observe, release_residents); both are dev tools that end on the interrupt"),
    "src/monitoring/vitals_history.py::start": (frozenset({"event-loop"}), "session_history.start_liveness calls it through an import alias (_vitals_start) from the lifespan (event loop, R165)"),
    "src/monitoring/forensics.py::_filesystem_type": (frozenset({"script", "event-loop"}), "the lifespan's data_dir_persistence (event loop, R165) and the migration evidence script"),
    "src/monitoring/secret_scrub.py::scrubbed_copy": (frozenset({"script"}), "the migration evidence and scale bench scripts (dev tools)"),
    "src/osm/history.py::ingest_history": (frozenset({"script"}), "scripts/osm_history_ingest.py, an operator tool that ingests one history file and exits"),
    "src/osm/pbf.py::_records": (frozenset({"script"}), "scripts/build_admin_boundaries.py reads a .pbf through the reader and exits"),
    "src/osm/places.py::build_search_index": (frozenset({"script"}), "scripts/osm_ingest.py, an operator tool that ingests one country and exits"),
    "src/osm/reader.py::available_memory_bytes": (frozenset({"script"}), "scripts/osm_ingest.py (as above)"),
    "src/osm/view.py::build_view_index": (frozenset({"script"}), "scripts/osm_ingest.py (as above)"),
}

#: scope -> (the entry tokens that reach it by NAME only, the colliding name, and what the collision is). The tokens must ALL vanish when that one name is
#: followed only inside its own file (:func:`test_every_dismissed_token_is_owed_to_its_colliding_name`), so a real call through any other name still fails.
_DISMISSED: dict[str, tuple[frozenset[str], str, str]] = {
    "src/osm/pbf.py::_records": (
        frozenset({"main:src/api/main.py::main", "event-loop"}),
        "read_header",
        "forensics.pages_state_before_open calls read_header of monitoring/page_reading.py; osm/pbf.py defines a read_header too, and the graph cannot tell them apart",
    ),
    "src/wiki/dump_index.py::build_index": (
        frozenset({"script", "dev-tool", "main:src/monitoring/release_run_fresh_restore.py::main"}),
        "build_index",
        "scripts/collect_throughput_bench.py reaches catalog/cities.py::cached_index, which calls ITS OWN build_index; wiki/dump_index.py defines one too",
    ),
    "src/wiki/dumpread.py::_read_stream_block": (
        frozenset({"script", "dev-tool", "main:src/monitoring/release_run_fresh_restore.py::main"}),
        "build_index",
        "only wiki/dump_index.build_index calls it (through iter_pages), and that is reached by the name collision above",
    ),
    "src/wiki/dumpread.py::iter_pages": (
        frozenset({"script", "dev-tool", "main:src/monitoring/release_run_fresh_restore.py::main"}),
        "build_index",
        "only wiki/dump_index.build_index calls it, and that is reached by the name collision above",
    ),
}


class _ResolvingGraph(_LocalGraph):
    """:class:`_LocalGraph` plus the calls it cannot see by NAME: a function imported (``from x import f`` / ``from x import f as _g``), a function reached through
    a module (``import x as m`` then ``m.f()``), and a function handed to ``atexit.register`` or ``signal.signal``. Each resolves to ONE function, so it is followed
    even when its name is a common one (``start``, ``end``), which the by-name graph has to cut at the file edge."""

    def __init__(self, sources):
        super().__init__(sources)
        self.precise_callers: dict[str, set[str]] = collections.defaultdict(set)  # target id -> ids of functions calling it through an import
        self.precise_modules: dict[str, set[str]] = collections.defaultdict(set)  # target id -> files calling it at the top level through an import
        self.handlers: dict[str, set[str]] = collections.defaultdict(set)  # target id -> "atexit" / "signal-handler" registrations
        self._files = set(sources)
        for rel, text in sources.items():
            tree = ast.parse(text)
            names, modules = self._imports(rel, tree)
            self._resolve(tree, rel, [], names, modules)

    def _module_file(self, dotted: str) -> str | None:
        base = dotted.replace(".", "/")
        for cand in (f"{base}.py", f"{base}/__init__.py"):
            if cand in self._files:
                return cand
        return None

    def _imports(self, rel: str, tree: ast.AST) -> tuple[dict[str, str], dict[str, str]]:
        """``(local name -> function id, local dotted name -> module file)`` for every import in the file, anywhere in it."""
        names: dict[str, str] = {}
        modules: dict[str, str] = {}
        package = rel.rsplit("/", 1)[0].replace("/", ".") if "/" in rel else ""
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    up = package.split(".")[: len(package.split(".")) - (node.level - 1)] if package else []
                    base = ".".join([*up, base] if base else up)
                for a in node.names:
                    local = a.asname or a.name
                    file = self._module_file(base)
                    if file and f"{file}::{a.name}" in self.funcs:
                        names[local] = f"{file}::{a.name}"
                    sub = self._module_file(f"{base}.{a.name}")
                    if sub:
                        modules[local] = sub
            elif isinstance(node, ast.Import):
                for a in node.names:
                    file = self._module_file(a.name)
                    if file:
                        modules[a.asname or a.name] = file
        return names, modules

    @staticmethod
    def _dotted(node: ast.AST) -> str | None:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            return ".".join([node.id, *reversed(parts)])
        return None

    def _resolve(self, node: ast.AST, rel: str, stack: list[str], names: dict[str, str], modules: dict[str, str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = [*stack, child.name]
                owner = f"{rel}::{'.'.join(inner)}"
                for stmt in child.body:
                    self._calls(stmt, rel, owner, names, modules)
                self._resolve(child, rel, inner, names, modules)
            elif isinstance(child, ast.ClassDef):
                self._resolve(child, rel, [*stack, child.name], names, modules)
            else:
                if not stack:
                    self._calls(child, rel, None, names, modules)
                self._resolve(child, rel, stack, names, modules)

    def _calls(self, node: ast.AST, rel: str, owner: str | None, names: dict[str, str], modules: dict[str, str]) -> None:
        todo = [node]
        while todo:
            n = todo.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(n, ast.Call):
                target = self._target(n.func, names, modules)
                if target:
                    (self.precise_callers[target].add(owner) if owner else self.precise_modules[target].add(rel))
                self._registration(n, rel)
            todo.extend(ast.iter_child_nodes(n))

    def _target(self, func: ast.AST, names: dict[str, str], modules: dict[str, str]) -> str | None:
        if isinstance(func, ast.Name):
            return names.get(func.id)
        if isinstance(func, ast.Attribute):
            mod = self._dotted(func.value)
            file = modules.get(mod) if mod else None
            if file and f"{file}::{func.attr}" in self.funcs:
                return f"{file}::{func.attr}"
        return None

    def _registration(self, call: ast.Call, rel: str) -> None:
        func = call.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
            return
        kind, handler = None, None
        if func.value.id == "atexit" and func.attr == "register" and call.args:
            kind, handler = "atexit", call.args[0]
        elif func.value.id == "signal" and func.attr == "signal" and len(call.args) > 1:
            kind, handler = "signal-handler", call.args[1]
        given = handler.id if isinstance(handler, ast.Name) else (handler.attr if isinstance(handler, ast.Attribute) else None)
        if not given:
            return
        same_file = [i for i in self.funcs if i.startswith(f"{rel}::") and i.split("::")[1].split(".")[-1] == given]
        for ident in same_file or [i for i in self.funcs if i.split("::")[1].split(".")[-1] == given and not given.startswith("_")]:
            self.handlers[ident].add(f"{kind} in {rel}")

    def closure_local(self, entry, local_only):
        nodes: list[str] = []
        workers: set[str] = set()
        main: set[str] = set()
        open_ends: list[str] = []
        pending = [entry]
        while pending:
            start = pending.pop()
            if start in nodes:
                continue
            got_nodes, got_workers, got_main, got_open = super().closure_local(start, local_only)
            workers.update(got_workers)
            main.update(got_main)
            open_ends.extend(n for n in got_open if n not in open_ends)
            for node in got_nodes:
                if node not in nodes:
                    nodes.append(node)
                for how in sorted(self.handlers.get(node, ())):
                    main.add(f"{node} ({how.split(' ')[0]} handler) registered in {how.split(' in ')[1]}")
                for f in sorted(self.precise_modules.get(node, ())):
                    main.add(f"{node} called at the top level of {f}")
                for caller in sorted(self.precise_callers.get(node, ())):
                    kind = self._route_kind(caller)
                    if kind == "sync route":
                        workers.add(f"{caller} (sync route) calls {node}")
                    elif kind:
                        main.add(f"{caller} ({kind}) calls {node}")
                    elif caller.startswith("scripts/"):
                        main.add(f"{caller} (a script) calls {node}")
                    elif caller not in nodes:
                        pending.append(caller)
        return sorted(nodes), sorted(workers), sorted(main), sorted(open_ends)


def _scopes_in_src() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted((_ROOT / "src").rglob("*.py")):
        if "static" in path.parts or path.relative_to(_ROOT).parts[:2] == ("src", "database"):
            continue
        rel = path.relative_to(_ROOT).as_posix()
        for qualname in sorted(_cleanup_covered(path.read_text(encoding="utf-8"), rel)):
            found.append((rel, qualname))
    return found


def _console_entries() -> frozenset[str]:
    scripts = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8")).get("project", {}).get("scripts", {})
    out = set()
    for target in scripts.values():
        module, _, func = str(target).partition(":")
        out.add(f"{module.replace('.', '/')}.py::{func}")
    return frozenset(out)


def _ambiguous(graph: _LocalGraph) -> frozenset[str]:
    """Names followed only inside their own file: common methods and builtins, and any public name defined in three or more files."""
    defined: dict[str, set[str]] = collections.defaultdict(set)
    for ident in graph.funcs:
        rel, qual = ident.split("::")
        defined[qual.split(".")[-1]].add(rel)
    names = {n for n, files in defined.items() if len(files) >= 3 and not n.startswith("_")}
    builtin_names = set(dir(__builtins__)) if not isinstance(__builtins__, dict) else set(__builtins__)
    for kind in (dict, list, str, set, bytes):
        builtin_names |= set(dir(kind))
    return frozenset(names | builtin_names | _COMMON_METHODS)


def _tokens(graph: _LocalGraph, ident: str, ambiguous: frozenset[str], console: frozenset[str]) -> set[str]:
    """What reaches ``ident`` on a main thread, as tokens: ``script``, ``event-loop``, ``dev-tool``, or ``main:<function>``."""
    nodes, _workers, main, _open = graph.closure_local(ident, ambiguous)
    out: set[str] = set()
    for text in main:
        if "(a script)" in text:
            out.add("script")
        elif "(async" in text:
            out.add("event-loop")
        elif "(atexit handler)" in text:
            out.add("atexit")
        elif "(signal-handler handler)" in text:
            out.add("signal-handler")
        elif "called at the top level of" in text:
            called, _, caller_file = text.partition(" called at the top level of ")
            out.add("dev-tool" if caller_file.startswith("src/testing/") else "script" if caller_file.startswith("scripts/") else f"main:{called}")
        else:
            out.add(f"main:{text}")
    for node in nodes:
        if node in console:
            out.add(f"main:{node}")
    return {("dev-tool" if t.startswith("main:src/testing/") else t) for t in out}


def test_no_cleanup_covered_loop_outside_the_database_package_is_reachable_on_the_main_thread():
    graph = _ResolvingGraph(read_sources())
    ambiguous, console = _ambiguous(graph), _console_entries()
    problems: list[str] = []
    seen_scopes: set[str] = set()
    seen_dismissed: dict[str, set[str]] = collections.defaultdict(set)
    for rel, qualname in _scopes_in_src():
        ident = f"{rel}::{qualname.replace('.<locals>.', '.')}"
        seen_scopes.add(ident)
        if ident not in graph.funcs:
            problems.append(f"{ident}: no function of that name in the graph (a module or class body runs at import time on the main thread): convert it")
            continue
        tokens = _tokens(graph, ident, ambiguous, console)
        dismissed = _DISMISSED.get(ident, (frozenset(), "", ""))[0]
        seen_dismissed[ident] |= tokens & dismissed
        real = tokens - dismissed
        mains = sorted(t for t in real if t.startswith("main:"))
        if mains:
            problems.append(f"{ident}: reachable from {mains}: write the loop in the guard-clause form (src/utils/interrupts.py) or, if the path is a name collision, dismiss it")
            continue
        if not real:
            if ident in _LISTED:
                problems.append(f"{ident}: listed as {sorted(_LISTED[ident][0])} but nothing of that kind reaches it any more: delete the row")
            continue
        listed = _LISTED.get(ident)
        if listed is None:
            problems.append(f"{ident}: reached by {sorted(real)} and not listed (script, event-loop and dev-tool entries are listed with a reason, never silently allowed)")
        elif not real <= listed[0]:
            problems.append(f"{ident}: reached by {sorted(real)}, listed for {sorted(listed[0])}")
    for ident in _LISTED:
        if ident not in seen_scopes:
            problems.append(f"{ident}: listed but no longer a cleanup-covered loop head: delete the row")
    for ident, (tokens, _name, _why) in _DISMISSED.items():
        if ident not in seen_scopes:
            problems.append(f"{ident}: dismissed but no longer a cleanup-covered loop head: delete the row")
        elif tokens - seen_dismissed[ident]:
            problems.append(f"{ident}: dismisses {sorted(tokens - seen_dismissed[ident])}, which no longer reach it: delete them from the row")
    assert not problems, "\n".join(problems)


def test_every_listed_row_has_a_reason_and_a_known_kind():
    for ident, (kinds, reason) in _LISTED.items():
        assert kinds and kinds <= _KINDS, (ident, kinds)
        assert len(reason) > 20, (ident, reason)
    for ident, (tokens, name, reason) in _DISMISSED.items():
        assert name and tokens and all(t.startswith("main:") or t in _KINDS for t in tokens), (ident, tokens)
        assert len(reason) > 20, (ident, reason)


def test_every_dismissed_token_is_owed_to_its_colliding_name():
    """A dismissal is only as wide as its collision: follow that one name inside its own file and every dismissed token must be gone."""
    graph = _ResolvingGraph(read_sources())
    ambiguous, console = _ambiguous(graph), _console_entries()
    for ident, (tokens, name, _why) in _DISMISSED.items():
        left = _tokens(graph, ident, ambiguous | {name}, console)
        assert not (left & tokens), f"{ident}: {sorted(left & tokens)} still reach it with {name!r} cut, so they are not (only) the collision"


def test_the_console_script_is_a_function_of_the_graph():
    graph = _ResolvingGraph(read_sources())
    for entry in _console_entries():
        assert entry in graph.funcs, f"pyproject [project.scripts] names {entry}, which the graph does not know"


def test_the_reach_finder_sees_a_chain_it_was_written_to_find():
    """Anti-vacuity on the real repo: ``heal_bulk_build`` was reachable from the console script (``main`` -> ``_serve`` -> ``init_db``) until this file's change
    converted it. Its caller chain is still there, so the finder must still report the entry."""
    graph = _ResolvingGraph(read_sources())
    ambiguous, console = _ambiguous(graph), _console_entries()
    tokens = _tokens(graph, "src/analytics/bulk_build.py::heal_bulk_build", ambiguous, console)
    assert "main:src/api/main.py::main" in tokens, tokens


_PLANT = {
    "src/work.py": "def target():\n    pass\n\ndef _worker():\n    target()\n\ndef start():\n    import threading\n    threading.Thread(target=_worker).start()\n",
}


def _planted(extra: dict[str, str]) -> set[str]:
    graph = _ResolvingGraph({**_PLANT, **extra})
    return _tokens(graph, "src/work.py::target", _ambiguous(graph), frozenset())


def test_a_worker_only_scope_has_no_main_thread_token():
    assert _planted({}) == set()


def test_a_script_an_async_def_and_a_module_level_call_are_found():
    assert "script" in _planted({"scripts/x.py": "from src.work import target\n\ndef go():\n    target()\n"})
    assert "event-loop" in _planted({"src/loop.py": "from src.work import target\n\nasync def handler():\n    target()\n"})
    assert "main:src/work.py::target" in _planted({"src/boot.py": "from src.work import target\ntarget()\n"})


def test_a_dunder_main_block_and_a_testing_harness_are_found():
    assert "main:src/work.py::target" in _planted({"src/tool.py": "from src.work import target\n\nif __name__ == '__main__':\n    target()\n"})
    assert "dev-tool" in _planted({"src/testing/soak.py": "from src.work import target\ntarget()\n"})


def test_a_common_name_is_followed_only_inside_its_own_file():
    plant = {"src/work.py": "def target():\n    pass\n\ndef update():\n    target()\n", "scripts/x.py": "d = {}\nd.update({})\n\ndef go():\n    d.update({})\n"}
    graph = _ResolvingGraph(plant)
    assert _tokens(graph, "src/work.py::target", _ambiguous(graph), frozenset()) == set()


def test_a_function_imported_under_another_name_is_followed():
    plant = {"src/boot.py": "from src.work import target as _t\n\nasync def handler():\n    _t()\n"}
    assert "event-loop" in _planted(plant)


def test_a_common_name_called_through_a_module_is_followed_across_files():
    """``start`` is a common method name, so the by-name graph cuts it at the file edge; an import names the one function it means."""
    plant = {
        "src/work.py": "def start():\n    pass\n",
        "src/boot.py": "from src import work\n\nasync def handler():\n    work.start()\n",
        "src/other.py": "import subprocess\n\ndef helper(p):\n    p.start()\n",
    }
    graph = _ResolvingGraph(plant)
    assert _tokens(graph, "src/work.py::start", _ambiguous(graph), frozenset()) == {"event-loop"}
    named = _ResolvingGraph({**plant, "src/boot.py": "from src.work import start as _go\n\nasync def handler():\n    _go()\n"})
    assert _tokens(named, "src/work.py::start", _ambiguous(named), frozenset()) == {"event-loop"}


def test_an_atexit_and_a_signal_handler_are_entries_of_their_own():
    plant = {
        "src/boot.py": "import atexit\nimport signal\nfrom src.work import target\n\ndef _bye():\n    target()\n\ndef install():\n    atexit.register(_bye)\n",
        "src/sig.py": "import signal\nfrom src.work import target\n\ndef _stop(signum, frame):\n    target()\n\ndef install():\n    signal.signal(signal.SIGTERM, _stop)\n",
    }
    assert {"atexit", "signal-handler"} <= _planted(plant)


def test_an_unrelated_call_of_the_same_name_is_not_followed():
    plant = {"src/work.py": "def start():\n    pass\n", "src/other.py": "async def handler(p):\n    p.start()\n"}
    graph = _ResolvingGraph(plant)
    assert _tokens(graph, "src/work.py::start", _ambiguous(graph), frozenset()) == set()
