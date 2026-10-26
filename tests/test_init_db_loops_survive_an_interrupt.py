"""Audit 0.5.0 (A-012, routing 11): the loops `init_db` runs on the MAIN thread, before `serve` has installed its signal handlers, end in no
bare `if`, so the back-edge of a `for` sits inside the exception-table entry of the `with engine.begin()` / `try` / `except BaseException`
around it (R161/R163; the same reading of the compiled code as tests/test_gates_survive_an_interrupt.py, whose helper this imports).

A `for` whose last statement is an `if` leaves its back-edge between two exception-table entries on CPython 3.13, so a `KeyboardInterrupt`
delivered there skips the cleanup: here the transaction's rollback in `install_source_outlet_id` (`except BaseException`) and the
engine transaction of every `ensure_*` column step. They take the guard-clause form (`if name in existing: continue`, then the body).

THE RATCHET IS DELIBERATELY NOT TREE-WIDE (the audit's own ruling for A-012): it covers only the functions `init_db` and the boot
self-heals call on the main thread, found by NAME PATTERN (every `ensure_*` of maintenance.py and source_identity.py, so a new column step is
held to it without anyone remembering to list it) plus the named functions below. Loops in worker-only or event-loop code (R162/R165) are out
of scope on purpose, and the helpers of tests/test_r205_comprehensions_under_cleanup.py cover the comprehensions."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads

_ROOT = Path(__file__).resolve().parents[1]

#: file -> predicate on a function name; every function it selects must have no loop head outside its construct.
_PATTERNS = {
    "src/database/maintenance.py": lambda n: n.startswith("ensure_") or n == "_add_missing_columns",
    "src/database/source_identity.py": lambda n: n.startswith("ensure_") or n in {"install_source_outlet_id", "upgrade_sources_to_composite_key"},
    # worker-only (R165) today; converted with the same helper so a CLI that reaches the registry later inherits it
    "src/database/damage.py": lambda n: n in {"repair_upsert", "settle_interrupted_repairs"},
}


def _selected() -> list[tuple[str, str]]:
    out = []
    for rel, pick in _PATTERNS.items():
        tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
        names = sorted({n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and pick(n.name)})
        out.extend((rel, n) for n in names)
    return out


def test_the_ratchet_selects_what_it_claims_to():
    # anti-vacuity: the 28 loops of maintenance.py's column steps are in it, and so are the named functions
    chosen = _selected()
    names = {n for _r, n in chosen}
    assert len([1 for r, _n in chosen if r.endswith("maintenance.py")]) >= 28, chosen
    assert {"install_source_outlet_id", "upgrade_sources_to_composite_key", "repair_upsert", "settle_interrupted_repairs", "ensure_feed_backoff_columns"} <= names


@pytest.mark.parametrize(("relpath", "funcname"), _selected(), ids=lambda v: v.rsplit("/", 1)[-1])
def test_no_loop_head_of_an_init_db_step_is_outside_the_construct_that_cleans_up(relpath, funcname):
    left = _uncovered_loop_heads(relpath, funcname)
    assert not left, f"{relpath}::{funcname}: a loop's back-edge is outside its with/try (give it the guard-clause form): {sorted(left)}"
