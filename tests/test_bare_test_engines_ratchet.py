"""Tests build their own SQLite engine through ``tests/_app_engine.py::app_sqlite_engine`` (rows 285 and 288).

A bare ``create_engine`` opens SQLite with its defaults: ``foreign_keys`` OFF, so a test can hold rows the app's store
refuses (a mention of an article that does not exist) and an ``ON DELETE CASCADE`` never fires. Measured 2026-11-21:
forcing foreign keys on for every test engine added 162 failures in 33 files, every one a seed row with no parent.

This is a ONE-WAY ceiling on the ``create_engine`` calls in test files that never attach the app's pragmas. It fails
when the count GROWS (a new test must use ``app_sqlite_engine``), and only the row 288 conversion batches lower
``_CEILING``. It deliberately has no twin failing when the ceiling sits above the count: a twin would make every
conversion PR edit this one number, and parallel PRs would conflict on it (Plan's ruling on row 285)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
#: ``create_engine`` calls in test files that never attach the app's pragmas, measured on 2026-11-21 (608 files).
_CEILING = 824
_MARK = re.compile(r"_sqlite_pragmas|app_sqlite_engine|foreign_keys")


def _engine_calls(text: str) -> int:
    count = 0
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            count += name == "create_engine"
    return count


def bare_engine_calls() -> dict[str, int]:
    found = {}
    for path in sorted(_TESTS.rglob("*.py")):
        if path.name == "_app_engine.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "create_engine" not in text or _MARK.search(text):
            continue
        calls = _engine_calls(text)
        if calls:
            found[path.relative_to(_TESTS).as_posix()] = calls
    return found


def test_no_new_test_builds_a_bare_sqlite_engine():
    total = sum(bare_engine_calls().values())
    assert total <= _CEILING, (
        f"{total} create_engine calls in test files without the app's pragmas, over the ceiling of {_CEILING}: "
        "build a test's own database with tests/_app_engine.py::app_sqlite_engine instead"
    )


def test_the_count_sees_each_form_of_the_call():
    # Fails if the counter goes blind
    assert _engine_calls("e = create_engine('sqlite://')\n") == 1
    assert _engine_calls("import sqlalchemy as sa\ne = sa.create_engine('sqlite://')\nf = sa.create_engine(u)\n") == 2
    assert _engine_calls("x = 'create_engine'\n") == 0
