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
time), and a ``scripts/`` function (Q's Graph already treats these as main-thread). An ``async def`` is the event loop (R165). Three kinds are LISTED, never
failed: ``script`` (a dev or operator tool; the process ends on the interrupt), ``event-loop`` (R165) and ``dev-tool`` (a harness under ``src/testing``). Anything
else is ``main:<entry>`` and fails.

WHAT THIS CANNOT DO, and the mark of it. The call graph is read by NAME (tests/test_worker_only_callers_pinned.py's Graph; nothing is imported or run). A call
through ``getattr``, a registry, a stored callable or a decorator is not seen. A name that is also a builtin or a common method (``update``, ``get``, ``run``,
``digest``) or is defined in three or more files is followed only inside its own file, because otherwise ``subprocess.run`` pulls in thousands of functions: that
UNDER-APPROXIMATES a real cross-file call through such a name. And two files that share a rarer name produce a path that is not a call: :data:`_DISMISSED` lists
those, each with the exact entries it dismisses, so a NEW entry through the same scope still fails. A forward reachability with every ambiguous name expanded was
read once by hand when this file was written (16 extra rows, all collisions: ``subprocess.run`` in ``_run_ephemeral``, ``core_guard.engage`` calling its own
``status``); it is not rerun here.

The reading is of CPython 3.13 bytecode, like its siblings."""

from __future__ import annotations

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
    "src/monitoring/forensics.py::_filesystem_type": (frozenset({"script", "event-loop"}), "the lifespan's data_dir_persistence (event loop, R165) and the migration evidence script"),
    "src/monitoring/secret_scrub.py::scrubbed_copy": (frozenset({"script"}), "the migration evidence and scale bench scripts (dev tools)"),
    "src/osm/history.py::ingest_history": (frozenset({"script"}), "scripts/osm_history_ingest.py, an operator tool that ingests one history file and exits"),
    "src/osm/pbf.py::_records": (frozenset({"script"}), "scripts/build_admin_boundaries.py reads a .pbf through the reader and exits"),
    "src/osm/places.py::build_search_index": (frozenset({"script"}), "scripts/osm_ingest.py, an operator tool that ingests one country and exits"),
    "src/osm/reader.py::available_memory_bytes": (frozenset({"script"}), "scripts/osm_ingest.py (as above)"),
    "src/osm/view.py::build_view_index": (frozenset({"script"}), "scripts/osm_ingest.py (as above)"),
    "src/wiki/dump_index.py::build_index": (frozenset({"script"}), "the collection bench script's stage timing (a dev tool)"),
    "src/wiki/dumpread.py::_read_stream_block": (frozenset({"script"}), "the collection bench script's stage timing (a dev tool)"),
    "src/wiki/dumpread.py::iter_pages": (frozenset({"script"}), "the collection bench script's stage timing (a dev tool)"),
}

#: scope -> (the entry tokens that reach it by NAME only, and what the name collision is). An entry NOT in the set still fails.
_DISMISSED: dict[str, tuple[frozenset[str], str]] = {
    "src/monitoring/storage_events.py::update": (
        frozenset({"main:src/monitoring/release_run_fresh_restore.py::main", "script"}),
        "storage_events.run_ended calls `fields.update(...)`, a dict method, which the name-based graph reads as a call of this module's own update()",
    ),
    "src/osm/pbf.py::_records": (
        frozenset({"main:src/api/main.py::main", "event-loop"}),
        "forensics.pages_state_before_open calls read_header of monitoring/page_reading.py; osm/pbf.py defines a read_header too, and the graph cannot tell them apart",
    ),
}


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
        elif "called at the top level of" in text:
            called, _, caller_file = text.partition(" called at the top level of ")
            out.add("dev-tool" if caller_file.startswith("src/testing/") else f"main:{called}")
        else:
            out.add(f"main:{text}")
    for node in nodes:
        if node in console:
            out.add(f"main:{node}")
    return {("dev-tool" if t.startswith("main:src/testing/") else t) for t in out}


def test_no_cleanup_covered_loop_outside_the_database_package_is_reachable_on_the_main_thread():
    graph = _LocalGraph(read_sources())
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
        dismissed = _DISMISSED.get(ident, (frozenset(), ""))[0]
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
    for ident, (tokens, _why) in _DISMISSED.items():
        if ident not in seen_scopes:
            problems.append(f"{ident}: dismissed but no longer a cleanup-covered loop head: delete the row")
        elif tokens - seen_dismissed[ident]:
            problems.append(f"{ident}: dismisses {sorted(tokens - seen_dismissed[ident])}, which no longer reach it: delete them from the row")
    assert not problems, "\n".join(problems)


def test_every_listed_row_has_a_reason_and_a_known_kind():
    for ident, (kinds, reason) in _LISTED.items():
        assert kinds and kinds <= {"script", "event-loop", "dev-tool"}, (ident, kinds)
        assert len(reason) > 20, (ident, reason)
    for ident, (tokens, reason) in _DISMISSED.items():
        assert tokens and all(t.startswith("main:") or t in {"script", "event-loop", "dev-tool"} for t in tokens), (ident, tokens)
        assert len(reason) > 20, (ident, reason)


def test_the_console_script_is_a_function_of_the_graph():
    graph = _LocalGraph(read_sources())
    for entry in _console_entries():
        assert entry in graph.funcs, f"pyproject [project.scripts] names {entry}, which the graph does not know"


def test_the_reach_finder_sees_a_chain_it_was_written_to_find():
    """Anti-vacuity on the real repo: ``heal_bulk_build`` was reachable from the console script (``main`` -> ``_serve`` -> ``init_db``) until this file's change
    converted it. Its caller chain is still there, so the finder must still report the entry."""
    graph = _LocalGraph(read_sources())
    ambiguous, console = _ambiguous(graph), _console_entries()
    tokens = _tokens(graph, "src/analytics/bulk_build.py::heal_bulk_build", ambiguous, console)
    assert "main:src/api/main.py::main" in tokens, tokens


_PLANT = {
    "src/work.py": "def target():\n    pass\n\ndef _worker():\n    target()\n\ndef start():\n    import threading\n    threading.Thread(target=_worker).start()\n",
}


def _planted(extra: dict[str, str]) -> set[str]:
    graph = _LocalGraph({**_PLANT, **extra})
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
    graph = _LocalGraph(plant)
    assert _tokens(graph, "src/work.py::target", _ambiguous(graph), frozenset()) == set()
