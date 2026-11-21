"""Tests build their own SQLite engine through ``tests/_app_engine.py::app_sqlite_engine`` (rows 285 and 288).

A bare ``create_engine`` opens SQLite with its defaults: ``foreign_keys`` OFF, so a test can hold rows the app's store
refuses (a mention of an article that does not exist) and an ``ON DELETE CASCADE`` never fires. Measured 2026-11-21:
forcing foreign keys on for every test engine added 162 failures in 33 files, every one a seed row with no parent.

This is a ONE-WAY ceiling on the engine-building calls in tests/ (``create_engine`` and its kin) outside the helper. It fails
when the count GROWS (a new test must use ``app_sqlite_engine``), and only the row 288 conversion batches lower
``_CEILING``. It deliberately has no twin failing when the ceiling sits above the count: a twin would make every
conversion PR edit this one number, and parallel PRs would conflict on it (Plan's ruling on row 285)."""

from __future__ import annotations

import ast
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
#: Engine-building calls in tests/ outside the helper, measured on 2026-11-21. Counted per CALL, never per file: a file
#: that attaches the app's pragmas to one engine can still build others bare, and a per-file exemption would hide them.
_CEILING = 871  # in 636 files
#: The SQLAlchemy calls that build an engine.
_BUILDERS = frozenset({"create_engine", "create_async_engine", "engine_from_config"})


def _engine_calls(text: str) -> int:
    tree = ast.parse(text)
    names = set(_BUILDERS)
    for node in ast.walk(tree):  # ``from sqlalchemy import create_engine as ce`` makes ``ce(...)`` a builder too
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname for alias in node.names if alias.name in _BUILDERS and alias.asname}
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                count += func.id in names
            elif isinstance(func, ast.Attribute):
                count += func.attr in _BUILDERS
    return count


def bare_engine_calls() -> dict[str, int]:
    found = {}
    for path in sorted(_TESTS.rglob("*.py")):
        if path.name == "_app_engine.py":
            continue
        text = path.read_text(encoding="utf-8")
        if not any(name in text for name in _BUILDERS):
            continue
        calls = _engine_calls(text)
        if calls:
            found[path.relative_to(_TESTS).as_posix()] = calls
    return found


def test_no_new_test_builds_a_bare_sqlite_engine():
    total = sum(bare_engine_calls().values())
    assert total <= _CEILING, (
        f"{total} engine-building calls in tests/, over the ceiling of {_CEILING}: "
        "build a test's own database with tests/_app_engine.py::app_sqlite_engine instead"
    )


def test_the_count_sees_each_form_of_the_call():
    # Fails if the counter goes blind
    assert _engine_calls("e = create_engine('sqlite://')\n") == 1
    assert _engine_calls("import sqlalchemy as sa\ne = sa.create_engine('sqlite://')\nf = sa.create_engine(u)\n") == 2
    assert _engine_calls("from sqlalchemy import create_engine as ce\ne = ce('sqlite://')\n") == 1
    assert _engine_calls("e = create_async_engine(u)\nf = engine_from_config(c)\n") == 2
    assert _engine_calls("x = 'create_engine'\n# PRAGMA foreign_keys\n") == 0
    # One engine given the app's pragmas does not exempt the file's other engines
    assert _engine_calls("e = create_engine(a)\nevent.listen(e, 'connect', _sqlite_pragmas)\nf = create_engine(b)\n") == 2
