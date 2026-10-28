"""``os`` as ONE module sees it, with some functions replaced (R351, after R344/R350).

``monkeypatch.setattr(module.os, "replace", f)`` does not patch ``module``: ``module.os`` IS the ``os`` module, so the function is replaced for
every thread and every caller of the process, the test runner among them. pytest 9.2.0 began calling ``os.fstat`` at the end of each phase, and a
test that had replaced ``os.fstat`` process-wide went red on every head (R350). The cure is to replace the one name the module under test reads:
``scope_os(monkeypatch, module, replace=f)`` binds ``module.os`` to a namespace that answers the replaced functions itself and hands everything
else to the real ``os``, and ``monkeypatch`` puts the real module back at teardown.

Two consequences, both wanted. Code that reaches ``os`` any other way (a local ``import os`` inside a function, ``pathlib`` calling ``os.replace``
for ``Path.replace``) no longer sees the replacement, so a test that depended on that fails loudly instead of passing by accident. And a second
``scope_os`` on the same module adds to the first one's namespace instead of replacing it.
"""

from __future__ import annotations

import os
from types import ModuleType

import pytest


class _ScopedOs:
    """``os`` with some attributes replaced or hidden; every other name is the real ``os``'s."""

    def __init__(self) -> None:
        self._hidden: set[str] = set()

    def __getattr__(self, name):
        if name == "_hidden" or name in self._hidden:
            raise AttributeError(name)
        return getattr(os, name)


def scope_os(monkeypatch: pytest.MonkeyPatch, module: ModuleType, **replaced) -> _ScopedOs:
    """Replace ``os.<name>`` as ``module`` sees it, for the rest of the test. Returns the namespace bound to ``module.os``."""
    seen = module.os
    if not isinstance(seen, _ScopedOs):
        seen = _ScopedOs()
        monkeypatch.setattr(module, "os", seen)
    for name, fn in replaced.items():
        # ``raising=False``: a name the platform lacks (``os.statvfs`` on Windows) is still replaceable here, as the tests that need it did before
        monkeypatch.setattr(seen, name, fn, raising=False)
    seen._hidden.difference_update(replaced)
    return seen


def hide_os(monkeypatch: pytest.MonkeyPatch, module: ModuleType, *names: str) -> _ScopedOs:
    """Make ``os.<name>`` missing as ``module`` sees it (a platform without ``statvfs``), for the rest of the test."""
    seen = scope_os(monkeypatch, module)
    for name in names:
        seen.__dict__.pop(name, None)
        seen._hidden.add(name)
    return seen
