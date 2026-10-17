"""The two ways a worker-only loop is reached through a TABLE are pinned to their callers (R162/R163, the two rows the reach tool called UNKNOWN).

``main_thread_reach.py`` could not follow a call through a value, so two loops stayed UNKNOWN until they were read by hand
(/mnt/project-files/fix-source-qualification/reach-on-stack-2026-10-17/UNKNOWN-RESOLVED.md):

  * ``database.query.grouped_counts`` (``result.close()`` in a ``finally``) and everything under the briefing PRODUCER TABLE are reached only through
    ``registry.run_all_bounded``. Its callers, all worker-only today: ``briefing.service._refresh_briefing``, ``bulletin.cards.cards_by_type`` (reached from
    ``cards.build``, imported only by ``bulletin.sections._cards``), ``analytics.leads_quality.leads_quality_report``, and ``registry.run_all``, which nothing
    calls outside the tests: the one OPEN DOOR.
  * ``storage_events.diagnostics_member`` is reached only through the slot table's string target, by ``diagnostics_slots.members()``, whose callers are in
    ``api/diagnostics/bundle.py``.

This test fails when the callers of a door change (read the new one, then edit :data:`_DOORS`), and, apart from that, whenever a MAIN-THREAD entry (an ``async
def``, a script, a top-level call) calls a door or one of the pinned callers: that would make the row REACHABLE, and the loop must then be converted (R163).
It uses the by-name graph of ``tests/test_worker_only_callers_pinned.py`` and has the same limits (calls through a stored callable, ``getattr`` or a
decorator are not seen); the call graph with receiver types is ``main_thread_reach.py``.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from tests.test_worker_only_callers_pinned import Graph, read_sources

# door (a public function name, as it is called) -> the functions that call it
_DOORS: dict[str, frozenset[str]] = {
    "run_all_bounded": frozenset(
        {
            "src/analytics/leads_quality.py::leads_quality_report",
            "src/briefing/registry.py::run_all",
            "src/briefing/service.py::_refresh_briefing",
            "src/bulletin/cards.py::cards_by_type",
        }
    ),
    "run_all": frozenset(),  # the open door: documented as a calling convention, called by no code in src/ or scripts/
    "members": frozenset(
        {
            "src/api/diagnostics/bundle.py::_all_diagnostics_members",
            "src/api/diagnostics/bundle.py::_diagnostics_coverage_report",
        }
    ),
}

# callers whose own way in is followed by name to the end (a private name stays inside its own file, so these chains are short and exact)
_FOLLOWED = (
    "src/briefing/service.py::_refresh_briefing",
    "src/analytics/leads_quality.py::leads_quality_report",
    "src/api/diagnostics/bundle.py::_all_diagnostics_members",
    "src/api/diagnostics/bundle.py::_diagnostics_coverage_report",
)

# ``cards.build`` is a common name, so its callers cannot be followed by name: the one file that imports it is pinned instead, and the function there
# that calls it is a section builder run from the bulletin routes (sync routes)
_CARDS_IMPORTERS = ("src/bulletin/sections.py",)


def _main_thread_callers(graph: Graph, door: str) -> list[str]:
    out = [f"{f} (top level) calls {door}" for f in sorted(graph.module_calls.get(door, ()))]
    for caller in sorted(graph.calls.get(door, ())):
        kind = graph._route_kind(caller)  # noqa: SLF001
        if kind and kind != "sync route":
            out.append(f"{caller} ({kind}) calls {door}")
        elif caller.startswith("scripts/"):
            out.append(f"{caller} (a script) calls {door}")
    return out


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return read_sources()


@pytest.fixture(scope="module")
def graph(sources) -> Graph:
    return Graph(sources)


@pytest.mark.parametrize("door", sorted(_DOORS))
def test_the_callers_of_a_door_are_the_pinned_ones(graph, door):
    now = frozenset(graph.calls.get(door, ()))
    assert now == _DOORS[door], f"the callers of {door} changed; read the new one (is it on a worker?), then edit _DOORS:\n  now: {sorted(now)}\n  pinned: {sorted(_DOORS[door])}"


@pytest.mark.parametrize("door", sorted(_DOORS))
def test_no_main_thread_entry_calls_a_door(graph, door):
    main = _main_thread_callers(graph, door)
    assert not main, "a main-thread entry now calls a door to a worker-only loop: the rows behind it become REACHABLE; convert the loops (R163):\n  " + "\n  ".join(main)


@pytest.mark.parametrize("entry", _FOLLOWED)
def test_no_main_thread_entry_reaches_a_pinned_caller(graph, entry):
    _nodes, workers, main, open_ends = graph.closure(entry)
    assert not main, "a main-thread entry now reaches a door's caller:\n  " + "\n  ".join(main)
    assert workers, f"{entry}: no worker boundary on any way in, so nothing shows it is worker-only"
    assert not open_ends, f"no caller and no thread start the scan can see: {open_ends}"


def test_cards_build_is_imported_only_where_it_was_read(sources):
    importers = sorted(rel for rel, text in sources.items() if "from src.bulletin.cards import" in text and rel != "src/bulletin/cards.py")
    assert importers == list(_CARDS_IMPORTERS), f"cards.build gained an importer; read how it is called (worker?), then edit _CARDS_IMPORTERS: {importers}"


def test_cards_by_type_is_called_only_by_build(graph):
    assert sorted(graph.calls.get("cards_by_type", ())) == ["src/bulletin/cards.py::build"]


# --- the same scan, on planted callers (red when a main-thread caller is added) --------------------------------------------------------------

_BASE: Mapping[str, str] = {
    "src/briefing/registry.py": "def run_all_bounded(session):\n    pass\n\ndef run_all(session):\n    return run_all_bounded(session)\n",
}


def _planted(extra: Mapping[str, str], door: str) -> list[str]:
    return _main_thread_callers(Graph({**_BASE, **extra}), door)


def test_a_script_calling_run_all_is_found():
    assert _planted({"scripts/x.py": "from src.briefing.registry import run_all\n\ndef main():\n    run_all(None)\n"}, "run_all")


def test_a_module_level_call_of_run_all_bounded_is_found():
    assert _planted({"src/x.py": "from src.briefing.registry import run_all_bounded\nrun_all_bounded(None)\n"}, "run_all_bounded")


def test_an_async_def_calling_members_is_found():
    assert _planted({"src/x.py": "async def handler(slots):\n    slots.members()\n"}, "members")


def test_a_sync_route_calling_a_door_is_not_a_main_thread_caller():
    assert not _planted({"src/x.py": "@router.get('/x')\ndef handler():\n    run_all(None)\n"}, "run_all")


def test_a_new_caller_changes_the_pinned_set():
    g = Graph({**_BASE, "src/x.py": "def helper():\n    run_all(None)\n"})
    assert frozenset(g.calls.get("run_all", ())) != _DOORS["run_all"]
