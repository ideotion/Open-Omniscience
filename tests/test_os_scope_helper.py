"""``tests/os_scope.py``: what the helper must do so that a test that uses it cannot leak a replaced ``os`` into the session (R351).

``hide_os`` once removed an attribute that ``scope_os`` had set with ``__dict__.pop``, bypassing ``monkeypatch``; the undo then raised
``AttributeError`` half-way and ``module.os`` stayed replaced for every later test (found in the read of the sweep PR: a platform without
``os.ST_RDONLY`` hits it in ``test_keyword_export_bounded``)."""

from __future__ import annotations

import ast
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tests.os_scope import hide_os, scope_os, scope_os_path

MISSING = "oo_a_name_this_platform_does_not_have"


def _module() -> Any:
    mod: Any = types.ModuleType("fake_module_under_test")
    mod.os = os
    return mod


def test_scoping_a_name_the_platform_lacks_and_then_hiding_it_undoes_cleanly():
    """Red before the fix: the undo raised ``AttributeError`` and ``mod.os`` stayed the scoped namespace."""
    mod, mp = _module(), pytest.MonkeyPatch()
    scope_os(mp, mod, **{MISSING: 1})
    assert getattr(mod.os, MISSING) == 1
    hide_os(mp, mod, MISSING)
    with pytest.raises(AttributeError):
        getattr(mod.os, MISSING)
    mp.undo()  # must not raise
    assert mod.os is os, "the real os was not put back"


def test_hiding_a_name_the_real_os_has_hides_it_for_this_module_only():
    mod, mp = _module(), pytest.MonkeyPatch()
    hide_os(mp, mod, "statvfs", "replace")
    assert not hasattr(mod.os, "statvfs") and not hasattr(mod.os, "replace")
    assert hasattr(os, "replace"), "hiding a name changed the real os"
    mp.undo()
    assert mod.os is os and hasattr(mod.os, "replace")


def test_scoping_the_same_module_twice_adds_to_one_namespace_and_the_undo_restores_everything():
    mod, mp = _module(), pytest.MonkeyPatch()
    real_replace, real_cpu = os.replace, os.cpu_count
    scope_os(mp, mod, replace=lambda a, b: "r")
    scope_os(mp, mod, cpu_count=lambda: 3)
    assert mod.os.replace(1, 2) == "r" and mod.os.cpu_count() == 3
    assert os.replace is real_replace and os.cpu_count is real_cpu, "the replacement reached the real os"
    mp.undo()
    assert mod.os is os


def test_a_name_hidden_and_then_scoped_again_is_visible_again():
    mod, mp = _module(), pytest.MonkeyPatch()
    hide_os(mp, mod, "statvfs")
    scope_os(mp, mod, statvfs=lambda p: "again")
    assert mod.os.statvfs("x") == "again"
    mp.undo()
    assert mod.os is os


def test_a_scoped_os_path_function_is_replaced_for_the_module_only_and_put_back_at_undo():
    mod, mp = _module(), pytest.MonkeyPatch()
    real_getsize = os.path.getsize
    scope_os_path(mp, mod, getsize=lambda _p: 7)
    scope_os(mp, mod, replace=lambda *_a: None)  # a second scope on the same module keeps the path namespace
    assert mod.os.path.getsize("anything") == 7
    assert mod.os.path.join("a", "b") == os.path.join("a", "b"), "an unreplaced os.path name must be the real one"
    assert os.path.getsize is real_getsize, "the process-wide os.path was touched"
    scope_os_path(mp, mod, exists=lambda _p: True)  # a second path scope adds to the first
    assert mod.os.path.getsize("anything") == 7 and mod.os.path.exists("nope")
    mp.undo()
    assert mod.os is os


# --------------------------------------------------------------------------- #
#  a name that is not an ``os`` attribute is a typo, not a fault injection
# --------------------------------------------------------------------------- #
# ``scope_os`` replaces with ``raising=False`` (a name the platform lacks, ``os.statvfs`` on Windows, must stay replaceable), so
# ``scope_os(monkeypatch, mod, replcae=f)`` creates an attribute nothing reads and the test passes without injecting anything.
# This reads every call site and checks the names against the ``os`` of the platform the suite runs on.
_TESTS = Path(__file__).resolve().parent
_HELPERS = {"scope_os": os, "scope_os_path": os.path, "hide_os": os}


def unknown_os_names(source: str) -> list[tuple[int, str, str]]:
    """``(line, helper, name)`` for every literal name given to a helper that is not an attribute of the module it replaces in."""
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        helper = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if helper not in _HELPERS:
            continue
        if helper == "hide_os":
            names = [a.value for a in node.args[2:] if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        else:
            names = [k.arg for k in node.keywords if k.arg]  # ``**{NAME: ...}`` has no literal name: not read
        found += [(node.lineno, helper, n) for n in names if not hasattr(_HELPERS[helper], n)]
    return found


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("scope_os(mp, mod, replace=f, fsync=g)", []),
        ("scope_os(mp, mod, replcae=f)", [(1, "scope_os", "replcae")]),
        ("scope_os_path(mp, mod, getsize=f)", []),
        ("scope_os_path(mp, mod, getsise=f)", [(1, "scope_os_path", "getsise")]),
        ('hide_os(mp, mod, "statvfs", "replace")', []),
        ('hide_os(mp, mod, "statvf")', [(1, "hide_os", "statvf")]),
        ('hide_os(mp, mod, NAME)', []),
        ("scope_os(mp, mod, **{NAME: 1})", []),
        ("tests.os_scope.scope_os(mp, mod, repalce=f)", [(1, "scope_os", "repalce")]),
    ],
)
def test_the_name_scanner_finds_a_misspelt_name_on_its_exact_line_and_nothing_else(source, expected):
    assert unknown_os_names(source) == expected


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="a name the suite replaces only to model a platform that lacks it (statvfs, ST_RDONLY) is absent from Windows' os, so the check "
    "is made where those names exist; the Linux and macOS runs cover every call site",
)
def test_every_name_a_test_gives_the_os_helpers_is_an_attribute_of_os():
    offenders: list[str] = []
    seen = dict.fromkeys(_HELPERS, 0)
    for path in sorted(_TESTS.rglob("*.py")):
        # not this file (its cases misspell names on purpose) and not the helper (``scope_os_path`` and ``hide_os`` call ``scope_os``
        # inside, so its count could never reach zero and the "read nothing" check below would prove nothing)
        if path.resolve() in {Path(__file__).resolve(), (_TESTS / "os_scope.py").resolve()} or "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if not any(h in source for h in _HELPERS):
            continue
        for line, helper, name in unknown_os_names(source):
            offenders.append(f"{path.relative_to(_TESTS).as_posix()}:{line} {helper}({name})")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                func = node.func
                helper = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if helper in seen:
                    seen[helper] += 1
    assert not offenders, f"these names are not attributes of os (a typo injects nothing and the test passes): {offenders}"
    assert all(seen.values()), f"the scan read no call of {[h for h, n in seen.items() if not n]}: the check proves nothing"
