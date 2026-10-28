"""``tests/os_scope.py``: what the helper must do so that a test that uses it cannot leak a replaced ``os`` into the session (R351).

``hide_os`` once removed an attribute that ``scope_os`` had set with ``__dict__.pop``, bypassing ``monkeypatch``; the undo then raised
``AttributeError`` half-way and ``module.os`` stayed replaced for every later test (found in the read of the sweep PR: a platform without
``os.ST_RDONLY`` hits it in ``test_keyword_export_bounded``)."""

from __future__ import annotations

import os
import types
from typing import Any

import pytest

from tests.os_scope import hide_os, scope_os

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
