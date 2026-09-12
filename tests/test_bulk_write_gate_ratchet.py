"""No bulk-ORM write may reach SQLite outside the single-writer gate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FOUND 2026-09-11 while fixing finding C8, and the hole is wider than the finding was.

``src/database/writer.py`` documents the gate as covering "EVERY write -- flush or bulk".
It does not. ``register_write_gate`` hangs off two SQLAlchemy events:

  * ``before_flush``   -- the ORM unit of work (``add`` + flush)
  * ``do_orm_execute`` -- ORM-issued DML (``Query.delete()``/``Query.update()``,
                          ``session.execute(insert()/update()/delete())``)

The LEGACY BULK operations -- ``bulk_update_mappings``, ``bulk_insert_mappings``,
``bulk_save_objects`` -- write through ``session_transaction.connection(...)`` directly
(``sqlalchemy.orm.bulk_persistence._bulk_update`` -> ``persistence._emit_update_statements``)
and fire NEITHER. They are invisible to both hooks, so they reach the file completely
outside the gate.

REPRODUCED, not reasoned about: two threads, one holding the gate and the SQLite write
lock past ``busy_timeout``, the other issuing a ``bulk_update_mappings``, raised a raw
``sqlite3.OperationalError: database is locked`` every run. That is exactly the
data-loss class the gate exists to prevent (field log 2026-06-13: metals fetched over
the network, then dropped on a locked write), and it is why the language auto-cleanup
step failed deterministically on every pass in the 2026-09-11 field bundle while its
correctly-gated siblings did not.

THIS IS A SOURCE-LEVEL RATCHET BECAUSE NO EVENT CAN CATCH IT. SQLAlchemy emits nothing
for these calls, so the gate cannot be extended to cover them from inside -- the same
reason the repo already guards socket-capable imports with a source-level ratchet rather
than a runtime hook. Every call site must take ``write_lock()`` explicitly, and this test
is what stops the next one being added without it.
"""

from __future__ import annotations

import ast
import pathlib

_BULK_CALLS = {"bulk_update_mappings", "bulk_insert_mappings", "bulk_save_objects"}

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def _bulk_calls_outside_write_lock(tree: ast.AST) -> list[tuple[str, int]]:
    """Every bulk-ORM call NOT lexically inside a `with write_lock():` block.

    Lexical containment is the honest test here: the gate is reentrant per thread, so a
    `write_lock()` anywhere up the enclosing `with` chain genuinely covers the call, and
    anything subtler (a gate taken in a caller two frames up) is exactly the kind of
    invisible coupling that let this hole exist in the first place -- it should be made
    visible at the call site, not inferred.
    """
    offenders: list[tuple[str, int]] = []

    class V(ast.NodeVisitor):
        def __init__(self) -> None:
            self.gate_depth = 0

        def _is_write_lock(self, item: ast.withitem) -> bool:
            call = item.context_expr
            if not isinstance(call, ast.Call):
                return False
            fn = call.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            return name == "write_lock"

        def visit_With(self, node: ast.With) -> None:
            gated = any(self._is_write_lock(i) for i in node.items)
            self.gate_depth += 1 if gated else 0
            for child in node.body:
                self.visit(child)
            self.gate_depth -= 1 if gated else 0

        visit_AsyncWith = visit_With  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in _BULK_CALLS and self.gate_depth == 0:
                offenders.append((fn.attr, node.lineno))
            self.generic_visit(node)

    V().visit(tree)
    return offenders


def test_no_bulk_orm_write_escapes_the_single_writer_gate():
    found: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails its own tests
            continue
        for call, line in _bulk_calls_outside_write_lock(tree):
            found.append(f"{path.relative_to(_SRC.parent.parent)}:{line}: {call}()")

    assert not found, (
        "bulk-ORM write(s) outside `with write_lock():` -- these fire neither "
        "before_flush nor do_orm_execute, so they reach SQLite with the single-writer "
        "gate NOT held, and collide with a concurrent writer as a raw "
        "'database is locked'. Wrap each in write_lock():\n  " + "\n  ".join(found)
    )


def test_the_ratchet_can_actually_see_an_offender():
    """A guard that cannot fail is not a guard -- prove it detects the shape it forbids,
    and that it correctly accepts the gated form."""
    bad = ast.parse(
        "def f(session, rows):\n"
        "    session.bulk_update_mappings(Keyword, rows)\n"
    )
    assert _bulk_calls_outside_write_lock(bad) == [("bulk_update_mappings", 2)]

    good = ast.parse(
        "def f(session, rows):\n"
        "    with write_lock():\n"
        "        session.bulk_update_mappings(Keyword, rows)\n"
    )
    assert _bulk_calls_outside_write_lock(good) == []

    # ...including when the gate is combined with another context manager on one line,
    # which is how run_discovery takes it.
    combined = ast.parse(
        "def f(session, rows):\n"
        "    with write_lock(), session.begin_nested():\n"
        "        session.bulk_save_objects(rows)\n"
    )
    assert _bulk_calls_outside_write_lock(combined) == []


def test_writer_docstring_does_not_overstate_its_coverage():
    """The claim that started this: writer.py said the gate covers "EVERY write -- flush
    or bulk". It did not, for three years of legacy bulk calls. A keystone mechanism that
    overstates its own coverage is worse than one that states a narrower truth, because
    every reader downstream trusts the docstring instead of checking."""
    writer = (_SRC / "database" / "writer.py").read_text(encoding="utf-8")
    assert "EVERY write — flush or bulk — serialises" not in writer, (
        "writer.py still claims blanket bulk coverage it does not have"
    )
    # ...and it must NAME the gap, so the next reader learns it from the module itself.
    assert "bulk_update_mappings" in writer, (
        "writer.py must name the legacy bulk operations its hooks cannot see"
    )
