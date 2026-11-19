"""Row 188: the driver-class caches a fake ``sqlcipher3`` can poison are all known to the suite's leak check.

``tests/conftest.py`` (``DRIVER_CLASS_CACHES``, checked after every test by ``pytest_runtest_teardown``) fails a test that leaves a fake
``sqlcipher3`` in ``sys.modules`` or a driver-class cache resolved while one was in. A cached function it does not list is not checked, so a
new one would bring the leak back unseen: every ``lru_cache``/``cache`` function in ``src`` that imports ``sqlcipher3`` must be listed.
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _cached_driver_functions() -> set[str]:
    found: set[str] = set()
    for path in sorted((REPO / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mod = ".".join(path.relative_to(REPO).with_suffix("").parts)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            decos = [ast.unparse(d) for d in node.decorator_list]
            if not any("lru_cache" in d or d in ("cache", "functools.cache") for d in decos):
                continue
            if "sqlcipher3" in ast.unparse(node):
                found.add(f"{mod}:{node.name}")
    return found


def test_every_cached_driver_class_function_is_checked_after_each_test():
    from tests.conftest import DRIVER_CLASS_CACHES

    found = _cached_driver_functions()
    assert "src.database.write:_db_operational_error_types" in found, "the scan finds the function row 188 was about"
    assert found == set(DRIVER_CLASS_CACHES), (sorted(found - set(DRIVER_CLASS_CACHES)), sorted(set(DRIVER_CLASS_CACHES) - found))


def test_the_check_finds_a_cache_resolved_under_a_fake_driver_and_clears_it(monkeypatch):
    """The check itself, run by hand: a fake sqlcipher3 without OperationalError in, the cache filled, the fake taken out (as a monkeypatch undo
    does): the cached answer lacks the real class, so the check names it and clears it, and the real driver error reads as locked again."""
    sqlcipher3 = pytest.importorskip("sqlcipher3")
    from src.database import write
    from tests.conftest import _driver_class_leaks

    write._db_operational_error_types.cache_clear()
    with monkeypatch.context() as m:
        fake = types.SimpleNamespace(IntegrityError=type("FakeIntegrityError", (Exception,), {}))
        m.setitem(sys.modules, "sqlcipher3", types.SimpleNamespace(dbapi2=fake))
        m.setitem(sys.modules, "sqlcipher3.dbapi2", fake)
        write._db_operational_error_types()
    assert write.is_locked_error(sqlcipher3.dbapi2.OperationalError("database is locked")) is False, "the premise: the poisoned cache"
    leaks = _driver_class_leaks()
    assert any("_db_operational_error_types" in x for x in leaks), leaks
    assert write.is_locked_error(sqlcipher3.dbapi2.OperationalError("database is locked")) is True
    assert _driver_class_leaks() == []


def test_the_check_takes_out_a_fake_left_in_sys_modules(monkeypatch):
    from tests.conftest import _driver_class_leaks

    monkeypatch.setitem(sys.modules, "sqlcipher3", types.SimpleNamespace())
    leaks = _driver_class_leaks()
    assert leaks and "not the driver" in leaks[0], leaks
    assert not isinstance(sys.modules.get("sqlcipher3"), types.SimpleNamespace), "and it is taken out"
