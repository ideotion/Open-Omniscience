"""R163: the loops of the OSM CLIs (scripts/osm_ingest.py, scripts/osm_reference_run.py) keep their back-edge inside the ``try`` whose ``finally`` they
rely on. CPython 3.13 leaves a loop whose body ends in a bare ``if`` outside the exception table of the ``try`` around it, so an interrupt delivered there
would skip the cleanup (src/utils/interrupts.py; tests/test_gates_survive_an_interrupt.py, ``_uncovered_loop_heads``). The body of each loop is unchanged;
only its last statement is written as a guard clause."""

from __future__ import annotations

import pytest

from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads

_ROWS = (
    ("src/osm/ingest.py", "ingest_country", {"for obj in extract.scan(border.bbox, locations):"}),
    ("src/osm/reference_run.py", "_run", {"for spec in specs:"}),
)


@pytest.mark.parametrize(("relpath", "funcname", "heads"), _ROWS, ids=[f"{r.rsplit('/', 1)[-1]}::{f}" for r, f, _h in _ROWS])
def test_the_osm_cli_loop_keeps_its_back_edge_inside_the_try(relpath, funcname, heads):
    left = _uncovered_loop_heads(relpath, funcname) & heads
    assert not left, f"{relpath}::{funcname}: a loop's back-edge is outside the try that covers its head: {sorted(left)}"
