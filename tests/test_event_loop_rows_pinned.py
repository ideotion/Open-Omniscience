"""The event-loop-exempt loop is exempt only while the event loop is the one place it runs on the main thread (R165, R163).

``tests/test_gates_survive_an_interrupt.py::_event_loop_loops`` exempts a loop because uvicorn takes SIGINT and SIGTERM, so no KeyboardInterrupt is
raised on the event loop (``tests/test_event_loop_signal_exemption.py`` pins that). That reason covers a loop ONLY while no other main thread reaches it:
a script's main would have no uvicorn above it. This file pins the remaining row to the call sites that make it event-loop-only.

``vitals_history.start`` is called from one place, ``session_history.start_liveness`` (imported as ``_vitals_start``), reached by ``record_boot`` and
``forensics.record_session_start``, which only the lifespan calls. The by-name graph of ``tests/test_worker_only_callers_pinned.py`` cannot follow the name
``start`` (hundreds of callers), so the last hop is pinned by the import and the calls instead.

Three rows left this list when they were read for it (2026-10-17): ``DamageRegistry.incident_after_last_check`` and ``DamageRegistry.notes`` were
converted (tests/test_r163_cli_loops.py keeps them converted), and ``storage_events.record`` was found NOT to be event-loop-only: besides the lifespan it is
called by the write gate's hold bookkeeping (``writer._note_hold_end`` and ``_note_long_hold``, which run on whichever thread held the gate, a CLI's main
thread included) and by the storage guard, so its two loops are owed the R163 conversion by the lane that owns the file (``r163-cli/wal``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.test_worker_only_callers_pinned import Graph, read_sources

_SRC = Path(__file__).resolve().parents[1] / "src"
_ENTRY = "src/monitoring/session_history.py::start_liveness"
_THE_ONLY_CALLER_ON_THE_MAIN_THREAD = "src/api/main.py::lifespan (async def) calls src/monitoring/forensics.py::record_session_start"

# (file, function) -> the lane owed the conversion, and why the event-loop reason does not cover it
_OWED_CONVERSION = {
    ("monitoring/storage_events.py", "record"): "WAL (r163-cli/wal): also called by writer._note_hold_end / _note_long_hold and the storage guard, on any thread",
}


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return read_sources()


def test_vitals_history_start_is_reached_on_the_main_thread_only_by_the_lifespan(sources):
    nodes, _workers, main, open_ends = Graph(sources).closure(_ENTRY)
    assert main == [_THE_ONLY_CALLER_ON_THE_MAIN_THREAD], f"another main-thread entry reaches vitals_history.start; it is no longer event-loop-only: {main}"
    assert not open_ends
    assert nodes == sorted(
        [_ENTRY, "src/monitoring/session_history.py::record_boot", "src/monitoring/forensics.py::record_session_start"]
    ), f"the functions between the lifespan and vitals_history.start changed: read them, then edit this pin: {nodes}"


def test_the_only_use_of_vitals_history_start_is_the_one_the_chain_assumes(sources):
    imports, dotted = [], []
    for rel, text in sources.items():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom) and node.module == "src.monitoring.vitals_history":
                imports += [f"{rel}: as {a.asname or a.name}" for a in node.names if a.name == "start"]
            if isinstance(node, ast.Call) and ast.unparse(node.func) in ("vitals_history.start", "vh.start"):
                dotted.append(f"{rel}:{node.lineno}")
    assert imports == ["src/monitoring/session_history.py: as _vitals_start"], f"vitals_history.start is imported somewhere new: {imports}"
    assert not dotted, f"vitals_history.start is called by its module name somewhere new: {dotted}"
    calls = Graph(sources).calls["_vitals_start"]
    assert calls == {_ENTRY}, f"_vitals_start is called from somewhere other than start_liveness: {sorted(calls)}"


@pytest.mark.parametrize(("rel", "name"), sorted(_OWED_CONVERSION))
def test_each_owed_conversion_names_a_real_function(rel, name):
    tree = ast.parse((_SRC / rel).read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.FunctionDef) and n.name == name for n in ast.walk(tree)), f"{rel}::{name} is gone: delete the owed entry"
