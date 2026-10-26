"""R205: the comprehensions inside a ``with``/``try``-``finally`` whose cleanup an interrupt must not skip are functions of their own.

CPython 3.13 inlines a comprehension into its function, and the back-edge of its filter-skip then sits between the exception-table entries
of the construct around it, so a ``KeyboardInterrupt`` delivered there leaves the frame without running the ``finally`` or the lock's
release (measured on a minimal case: 12,283 of 12,491 interrupts skipped the ``finally``). In a frame of its own there is no handler to
skip. The body of each comprehension is unchanged. The four sites are the Tier A items with a plausible chain to boot or a CLI in
/mnt/project-files/audit-0.5.0/inputs/comprehensions-in-try-report.md (reachability there is by bare function name, depth 4: a hint, not a
proof). The check reads the compiled code with the helper of tests/test_gates_survive_an_interrupt.py (imported, that file is not edited)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads

_SITES = (
    ("src/database/source_identity.py", "upgrade_sources_to_composite_key", "finally that turns foreign-key enforcement back on"),
    ("src/database/damage.py", "confirmed_damage", "with self._lock"),
    ("src/versioned/store.py", "lane_engine", "with _lock"),
    ("src/versioned/store.py", "dispose_lane", "with _lock"),  # reached by encrypt_tool.encrypt_all through an aliased import
)


@pytest.mark.parametrize(("relpath", "funcname", "protects"), _SITES, ids=[f"{r.rsplit('/', 1)[-1]}::{f}" for r, f, _p in _SITES])
def test_no_comprehension_leaves_its_back_edge_outside_the_construct_that_cleans_up(relpath, funcname, protects):
    # the function is matched by name, so a rename must fail here rather than leave the check looking at nothing
    source = (Path(__file__).resolve().parents[1] / relpath).read_text(encoding="utf-8")
    assert f"def {funcname}(" in source, f"{relpath}: {funcname} is gone; update this test"
    left = _uncovered_loop_heads(relpath, funcname)
    assert not left, f"{relpath}::{funcname}: a comprehension's back-edge is outside the construct ({protects}): {sorted(left)}"
