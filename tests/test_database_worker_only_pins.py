"""The "worker-only" rows of tests/test_database_loop_heads_are_classified.py are pinned to the callers that make them worker-only (audit 0.5.0 A-012, R245).

tests/test_worker_only_callers_pinned.py does this for the allowlist of tests/test_gates_survive_an_interrupt.py: it rebuilds from the source the callers of
a function, transitively, and fails on a main-thread entry. It covers two of the ten rows of the loop-heads table. The review of that table found two rows wrong
(``active_leases`` reached from ``release_run_fresh_restore``, a module that runs ``main()`` on its main thread), which is what a pin catches and a grep
read once does not. This file pins the other eight with the same ``Graph`` (imported, never edited) and requires, for each:

  1. NO main-thread entry among the functions that reach it: an ``async def``, a module under ``scripts/`` or a call at a module's top level;
  2. a worker boundary on the way in (a thread start, a ``BackgroundJob``, a sync route) or a hand-read entry in :data:`_VALUE_ENTRIES`;
  3. EXACTLY the set of functions in :data:`_PINNED`: a new caller is not necessarily wrong, but it has to be read, and the edit is the review.

TWO THINGS THE SHARED CLOSURE CANNOT DO, handled here. It follows a public name across the whole repo, so ``run`` (``repair.run`` shares its name with every
``subprocess.run``) pulled in 5,700 functions and 5,900 "main-thread entries" that are not callers: :data:`_LOCAL_ONLY` names are followed only inside their
own file. And a function reached only as a VALUE (``_timed("verify-database", _verify_database)``, a registry of producers) has no caller to find: each such
entry is listed in :data:`_VALUE_ENTRIES` with the line that starts it, and a test checks the line is still there.

What this is NOT: the call graph is read by NAME, nothing is imported or run, and a call made through ``getattr``, a stored callable or a decorator is not seen.
Whether a thread has signal handlers is not read from the code either; the premise is R162/R163/R165 (only the main thread is sent a ``KeyboardInterrupt``)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.test_worker_only_callers_pinned import _ALIASES, _SPAWNERS, Graph, read_sources  # noqa: F401 - _SPAWNERS: Graph's own constant, named for the reader

_ROOT = Path(__file__).resolve().parents[1]

#: Names followed only inside their own file, because the same name is also a standard-library or unrelated call all over the repo.
_LOCAL_ONLY = frozenset({"run"})

#: id -> why it has no caller the scan can see, and the check that the line which starts it is still there (see :func:`_value_entry_starts`).
_VALUE_ENTRIES: dict[str, str] = {
    "src/api/boot_sequence.py::_verify_database": "a step handed to _timed(...) by boot_sequence.run, which main.py starts on the daemon thread oo-boot-sequence",
    "src/api/main.py::_run_startup_upkeep._warm_insights_cache": "handed to boot_sequence.run as its warm-up callback, on the daemon thread oo-boot-sequence",
    "src/briefing/producers.py::emotion_profile_card": "a producer registered with the briefing service and called by _refresh_briefing, on a request thread or a job thread",
    "src/briefing/producers.py::framing_split": "a producer registered with the briefing service (as above)",
    "src/briefing/producers.py::ip_litigation_pulse": "a producer registered with the briefing service (as above)",
    "src/briefing/producers.py::lonely_signal": "a producer registered with the briefing service (as above)",
    "src/briefing/producers.py::manufactured_emergence": "a producer registered with the briefing service (as above)",
    "src/briefing/producers.py::on_the_horizon": "a producer registered with the briefing service (as above)",
    "src/briefing/producers.py::rising_now": "a producer registered with the briefing service (as above)",
    "src/bulletin/sections.py::_rising": "a section of the bulletin builder's table, run where the bulletin is built",
}

#: row (file::scope, as the loop-heads table names it) -> every function that can reach it by name, in this file's reading.
_PINNED: dict[str, tuple[str, ...]] = {
    "src/database/fts_reindex.py::SearchReindexJobManager._park": (
        "src/database/fts_reindex.py::SearchReindexJobManager._park",
        "src/database/fts_reindex.py::SearchReindexJobManager._run",
    ),
    "src/database/fts_reindex.py::SearchReindexJobManager._run": (
        "src/database/fts_reindex.py::SearchReindexJobManager._run",
    ),
    "src/database/query.py::grouped_counts": (
        "src/analytics/emergence.py::find_manufactured_emergence",
        "src/analytics/emergence.py::find_manufactured_emergence._article_counts",
        "src/analytics/queries.py::trending",
        "src/analytics/queries.py::trending._counts",
        "src/analytics/queries.py::trending_windows",
        "src/analytics/readmodel.py::trending",
        "src/analytics/readmodel.py::trending_windows",
        "src/api/insights.py::warm_cache",
        "src/api/main.py::_run_startup_upkeep._warm_insights_cache",
        "src/briefing/producers.py::emotion_profile_card",
        "src/briefing/producers.py::framing_split",
        "src/briefing/producers.py::ip_litigation_pulse",
        "src/briefing/producers.py::lonely_signal",
        "src/briefing/producers.py::manufactured_emergence",
        "src/briefing/producers.py::on_the_horizon",
        "src/briefing/producers.py::rising_now",
        "src/briefing/service.py::_bg_refresh",
        "src/briefing/service.py::_refresh_briefing",
        "src/briefing/service.py::get_briefing",
        "src/briefing/service.py::refresh_briefing",
        "src/bulletin/facts.py::rising_concepts",
        "src/bulletin/sections.py::_rising",
        "src/database/query.py::grouped_counts",
        "src/database/query.py::windowed_group_counts",
        "src/monitoring/benchmark.py::_build_cases",
        "src/monitoring/benchmark.py::run_benchmark",
        "src/scheduler/runner.py::BackgroundScheduler._refresh_briefing_async._run",
    ),
    "src/database/repair.py::_disk_unread_pages": (
        "src/database/repair.py::_copy_and_swap",
        "src/database/repair.py::_disk_unread_pages",
        "src/database/repair.py::_finish",
        "src/database/repair.py::_kept_facts",
        "src/database/repair.py::_repair",
        "src/database/repair.py::_resume",
        "src/database/repair.py::_worker",
        "src/database/repair.py::run",
    ),
    "src/database/repair.py::_swap": (
        "src/database/repair.py::_copy_and_swap",
        "src/database/repair.py::_repair",
        "src/database/repair.py::_resume",
        "src/database/repair.py::_swap",
        "src/database/repair.py::_worker",
        "src/database/repair.py::run",
    ),
    "src/database/verify.py::_recheck_main": (
        "src/database/verify.py::_recheck_main",
    ),
    "src/database/verify.py::_reread_main": (
        "src/database/verify.py::_reread_main",
    ),
    "src/database/verify.py::inspect_file": (
        "src/api/boot_sequence.py::_verify_database",
        "src/database/repair.py::_copy_and_swap",
        "src/database/repair.py::_repair",
        "src/database/repair.py::_worker",
        "src/database/repair.py::run",
        "src/database/salvage.py::check_copy",
        "src/database/verify.py::_recheck_main",
        "src/database/verify.py::_reread_main",
        "src/database/verify.py::_run_plan",
        "src/database/verify.py::inspect_confirmed",
        "src/database/verify.py::inspect_file",
        "src/database/verify.py::run_armed",
    ),
}


class _LocalGraph(Graph):
    """:class:`Graph` with one more rule in its closure: a name in ``local_only`` is followed only inside the file that defines the node."""

    def closure_local(self, entry: str, local_only: frozenset[str]) -> tuple[list[str], list[str], list[str], list[str]]:
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
            local = own.startswith("_") or own in local_only
            for starter, how in self.starts.get(own, ()):
                if local and starter.split("::")[0] != rel:
                    continue
                workers.add(f"{node} started by {how} in {starter}")
                has_way_in.add(node)
            for used_as in {own, _ALIASES.get(node, own)}:
                local_name = used_as.startswith("_") or used_as in local_only
                if not local_name:
                    for f in self.module_calls.get(used_as, ()):
                        main.add(f"{node} called at the top level of {f}")
                        has_way_in.add(node)
                for caller in self.calls.get(used_as, ()):
                    cfile = caller.split("::")[0]
                    if local_name and cfile != rel:
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
        return sorted(nodes), sorted(workers), sorted(main), sorted(n for n in nodes if n not in has_way_in)


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return read_sources()


@pytest.fixture(scope="module")
def graph(sources) -> _LocalGraph:
    return _LocalGraph(sources)


@pytest.mark.parametrize("entry", sorted(_PINNED))
def test_no_main_thread_entry_reaches_a_pinned_worker_only_row(graph, entry):
    nodes, workers, main, open_ends = graph.closure_local(entry, _LOCAL_ONLY)
    assert not main, "a main-thread entry now reaches a row the loop-heads table calls worker-only: convert the loop instead (R163):\n  " + "\n  ".join(main)
    assert workers or open_ends, f"{entry}: nothing shows a worker boundary, and no hand-read entry stands in for one"
    unread = sorted(set(open_ends) - set(_VALUE_ENTRIES))
    assert not unread, f"these have no caller and no thread start the scan can see; read how each is reached, then list it in _VALUE_ENTRIES: {unread}"
    assert tuple(nodes) == tuple(sorted(_PINNED[entry])), (
        f"the functions that can reach {entry} changed; read the new caller, then edit _PINNED:\n  now: {nodes}\n  pinned: {sorted(_PINNED[entry])}"
    )


def test_every_worker_only_row_is_pinned_here_or_in_the_older_test():
    import tests.test_database_loop_heads_are_classified as table
    from tests.test_worker_only_callers_pinned import _PINNED as older

    rows = {f"{rel}::{name}" for (rel, name) in table._CLASS_C}
    unpinned = sorted(rows - set(_PINNED) - set(older))
    assert not unpinned, f"worker-only rows with no pin in either file: {unpinned}"
    stale = sorted(set(_PINNED) - rows)
    assert not stale, f"pins whose row is not in the loop-heads table any more: {stale}"


def _calls_with_target(text: str, spawner: str, target: str) -> bool:
    """Whether ``text`` calls ``spawner(...)`` with ``target`` (a name or a dotted attribute) among its arguments."""
    for node in ast.walk(ast.parse(text)):
        called = getattr(node.func, "id", None) or getattr(node.func, "attr", None) if isinstance(node, ast.Call) else None
        if called == spawner and any(ast.unparse(a) == target for a in [*node.args, *(k.value for k in node.keywords)]):
            return True
    return False


def test_the_hand_read_entries_are_still_started_as_described(sources):
    """Each value entry's start is a line in the source; pin it, so reading it once is not the only evidence."""
    assert _calls_with_target(sources["src/api/main.py"], "Thread", "boot_sequence.run"), "main.py no longer starts boot_sequence.run as a thread's target"
    boot = sources["src/api/boot_sequence.py"]
    assert '"verify-database", _verify_database' in boot, "the boot step that runs the check is no longer registered by name: re-read how it is run"
    assert "oo-boot-sequence" in sources["src/api/main.py"], "the boot sequence is no longer started on the thread named oo-boot-sequence"
    assert "_warm_insights_cache" in sources["src/api/main.py"]
    producers = sources["src/briefing/producers.py"]
    for name in ("emotion_profile_card", "framing_split", "ip_litigation_pulse", "lonely_signal", "manufactured_emergence", "on_the_horizon", "rising_now"):
        assert f"def {name}(" in producers


def test_the_local_rule_agrees_with_the_shared_closure_where_it_does_not_apply(graph):
    """Anti-drift: with no name made local the closure here is the older test's, on a pinned entry of that file."""
    entry = "src/database/article_indexes.py::_refresh_stats"
    assert graph.closure_local(entry, frozenset()) == graph.closure(entry)


_BASE = {
    "src/a.py": "def target():\n    pass\n\ndef run():\n    target()\n\ndef _worker():\n    run()\n\ndef start():\n    import threading\n    threading.Thread(target=_worker).start()\n",
}


def test_a_local_only_name_ignores_callers_in_other_files():
    other = {"src/b.py": "import subprocess\n\ndef helper():\n    subprocess.run(['x'])\n"}
    nodes, workers, main, _o = _LocalGraph({**_BASE, **other}).closure_local("src/a.py::target", frozenset({"run"}))
    assert nodes == ["src/a.py::_worker", "src/a.py::run", "src/a.py::target"] and workers and not main
    wide, _w, _m, _o2 = _LocalGraph({**_BASE, **other}).closure_local("src/a.py::target", frozenset())
    assert "src/b.py::helper" in wide, "the same name followed repo-wide pulls in an unrelated caller: that is what the local rule is for"


def test_a_script_that_calls_a_pinned_row_is_a_main_thread_entry():
    script = {"scripts/x.py": "from src.a import target\n\ndef go():\n    target()\n"}
    _n, _w, main, _o = _LocalGraph({**_BASE, **script}).closure_local("src/a.py::target", frozenset({"run"}))
    assert main and "scripts/x.py" in main[0]
