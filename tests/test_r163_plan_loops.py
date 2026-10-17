"""R163: the loops the restore CLI (src/monitoring/release_run_fresh_restore.py) and ``open-omniscience migrate-countries`` reach on the main thread keep their
back-edge inside the ``try`` whose cleanup they rely on. CPython 3.13 leaves a ``while <cond>:`` loop, and a ``for`` loop whose body ends in a bare ``if``,
outside the exception table of the ``try`` around it, so an interrupt delivered there would skip the cleanup (the rollback of an open transaction, the close
of a connection): src/utils/interrupts.py; tests/test_gates_survive_an_interrupt.py, ``_uncovered_loop_heads``. Each body is unchanged; only the loop's
condition or its last statement is written in the covered form."""

from __future__ import annotations

import pytest

from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads

_ROWS = (
    ("src/backup/country_migration.py", "migrate", {"for cp in plan.columns:", "if should_stop is not None and should_stop():", "for key, orig in original.items():"}),
    ("src/backup/merge.py", "merge_corpus", {"for i, (name, fn) in enumerate(steps, 1):"}),
    ("src/backup/merge.py", "merge_custody", {"for chain_id, sql, params in sources:", "dest.executemany("}),
)


@pytest.mark.parametrize(("relpath", "funcname", "heads"), _ROWS, ids=[f"{r.rsplit('/', 1)[-1]}::{f}" for r, f, _h in _ROWS])
def test_the_restore_and_migration_loops_keep_their_back_edge_inside_the_try(relpath, funcname, heads):
    left = _uncovered_loop_heads(relpath, funcname) & heads
    assert not left, f"{relpath}::{funcname}: a loop's back-edge is outside the try that covers its head: {sorted(left)}"
