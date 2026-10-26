"""R163: the loops and comprehensions of the OSM CLIs (scripts/osm_ingest.py, scripts/osm_reference_run.py) keep their back-edge inside the ``try`` whose ``finally`` they
rely on. CPython 3.13 leaves a loop whose body ends in a bare ``if`` outside the exception table of the ``try`` around it, so an interrupt delivered there
would skip the cleanup (src/utils/interrupts.py; tests/test_gates_survive_an_interrupt.py, ``_uncovered_loop_heads``). The body of each loop is unchanged;
only its last statement is written as a guard clause. A comprehension is inlined into its caller on 3.13 and its filter-skip back-edge is
uncovered the same way (measured: 12,283 of 12,491 interrupts skipped the ``finally``), so the two inside these ``try`` bodies are functions of
their own. The comprehensions in ``_run``'s ``finally`` itself are not listed: an interrupt anywhere in a ``finally`` body skips the rest of it."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads

#: (file, function, loop heads that must still exist in the file, uncovered heads that are allowed). The comprehensions of ``_run``'s own
#: ``finally`` are the allowed ones: an interrupt anywhere in a ``finally`` body skips the rest of it, covered back-edge or not.
_ROWS = (
    ("src/osm/ingest.py", "ingest_country", {"for obj in extract.scan(border.bbox, locations):"}, set()),
    ("src/osm/reference_run.py", "_run", {"for spec in specs:"},
     {'done_ok = {p["name"] for p in report["phases"] if p.get("status") == "ok"}',
      "unfinished = [sp.name for sp in specs if sp.name not in done_ok]"}),
)


@pytest.mark.parametrize(("relpath", "funcname", "watched", "allowed"), _ROWS, ids=[f"{r.rsplit('/', 1)[-1]}::{f}" for r, f, _w, _a in _ROWS])
def test_no_loop_of_the_osm_cli_leaves_its_back_edge_outside_the_try(relpath, funcname, watched, allowed):
    # a watched head is matched by text, so a renamed function or an edited loop head must fail here rather than leave the test empty
    source = (Path(__file__).resolve().parents[1] / relpath).read_text(encoding="utf-8")
    missing = {h for h in watched if h not in source}
    assert not missing, f"{relpath}::{funcname}: the loop heads this test watches are gone from the file (update the test): {sorted(missing)}"
    left = _uncovered_loop_heads(relpath, funcname) - allowed
    assert not left, f"{relpath}::{funcname}: a loop's back-edge is outside the try that covers its head: {sorted(left)}"
