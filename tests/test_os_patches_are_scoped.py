"""No test replaces a function of the ``os`` module for the whole process (R351, after R344 and R350).

``monkeypatch.setattr(os, "replace", f)`` and ``monkeypatch.setattr(module.os, "replace", f)`` are the same call: ``module.os`` IS the ``os`` module,
so every thread and every caller, the test runner among them, is handed ``f``. pytest 9.2.0 began calling ``os.fstat`` at the end of each test phase
and a test that had replaced it that way went red on every head (R350). ``tests/os_scope.py`` (``scope_os``) binds the replacement to the one name
the module under test reads. This guard reads the AST of every Python file under tests/ and fails on a replacement it finds anywhere else.

The allowlist is the only exception, each entry with its reason, and a stale entry (one that no longer matches a call) fails too, so it cannot rot.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PATCHERS = {"setattr", "delattr"}
#: the modules that ARE ``os.path`` (``os.path`` is ``posixpath`` or ``ntpath``, which import ``genericpath``)
_PATH_MODULES = {"posixpath", "ntpath", "genericpath"}
_STRING_TARGET = re.compile(r"(^|\.)(os|posixpath|ntpath|genericpath)(\.path)?\.[A-Za-z_]+$|(^|\.)os\.path$")
_STRING_MODULE = re.compile(r"(^|\.)(os|os\.path|posixpath|ntpath|genericpath)$")

#: file (relative to tests/) -> why a process-wide replacement is the point of that test and not an accident
_DELIBERATE = {
    "test_backend_launch.py": "a GUARD that no process anywhere is signalled by a stop of a daemon the app did not spawn: the replacement records any os.kill, whoever calls it",
    "test_gpu_arbitration.py": "a GUARD that releasing the card signals no process anywhere: the replacement records any os.kill, whoever calls it",
    "torture_helper.py": "runs as a CHILD process (never inside pytest) that SIGKILLs itself at the swap boundary: the replacement is the whole child's, and nothing else runs in it",
    "test_session_hwm_light.py": "an OBSERVATION spy that passes through to the real os.open: it records every route into /proc the sampler could take, in any module it calls",
}


class _Names:
    """The names a file binds to ``os`` and to ``os.path`` (``import os as _os``, ``import os.path as osp``, ``from os import path as P``)."""

    def __init__(self, tree: ast.AST) -> None:
        self.os = {"os"}
        self.path = set(_PATH_MODULES)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "os" and a.asname:
                        self.os.add(a.asname)
                    elif a.asname and (a.name == "os.path" or a.name in _PATH_MODULES):
                        self.path.add(a.asname)
            elif isinstance(node, ast.ImportFrom) and node.module == "os":
                for a in node.names:
                    if a.name == "path":
                        self.path.add(a.asname or "path")

    def is_os(self, node: ast.AST) -> bool:
        """``os`` (or an alias) or ``<anything>.os``: the module itself, however a test reached it."""
        return (isinstance(node, ast.Name) and node.id in self.os) or (isinstance(node, ast.Attribute) and node.attr == "os")

    def is_path(self, node: ast.AST) -> bool:
        """``os.path`` however spelled: ``os.path``, ``<x>.os.path``, an alias of it, or ``posixpath``/``ntpath``/``genericpath``."""
        if isinstance(node, ast.Name):
            return node.id in self.path
        return isinstance(node, ast.Attribute) and (node.attr in _PATH_MODULES or (node.attr == "path" and self.is_os(node.value)))

    def is_process_module(self, node: ast.AST) -> bool:
        return self.is_os(node) or self.is_path(node)


def _argument(node: ast.Call, position: int, keyword: str) -> ast.AST | None:
    if len(node.args) > position:
        return node.args[position]
    return next((k.value for k in node.keywords if k.arg == keyword), None)


def _string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def process_wide_os_patches(source: str) -> list[int]:
    """Line numbers that replace (or delete) a function of ``os`` or ``os.path`` itself."""
    tree = ast.parse(source)
    names = _Names(tree)
    found: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            first = _argument(node, 0, "target")
            text = _string(first)
            if name in _PATCHERS and first is not None and names.is_process_module(first):
                found.append(node.lineno)
            elif name in {"setattr", "patch"} and text is not None and _STRING_TARGET.search(text):
                found.append(node.lineno)  # monkeypatch.setattr("os.kill", f), mock.patch("pkg.mod.os.path.getsize")
            elif name == "object" and first is not None and names.is_process_module(first):
                found.append(node.lineno)  # mock.patch.object(os, "replace", ...)
            elif name == "multiple" and first is not None and (names.is_process_module(first) or (text is not None and _STRING_MODULE.search(text))):
                found.append(node.lineno)  # mock.patch.multiple(os, replace=f), mock.patch.multiple("os", ...)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            if any(isinstance(t, ast.Attribute) and names.is_process_module(t.value) for t in targets):
                found.append(node.lineno)  # os.replace = f, os.path.getsize += f, del os.statvfs
    return sorted(set(found))


def _test_files() -> list[Path]:
    """Every Python file under tests/: a helper, a conftest or a ``scale/`` module patches the process as surely as a ``test_*.py`` does."""
    return sorted(p for p in _TESTS.rglob("*.py") if p.resolve() != Path(__file__).resolve() and "__pycache__" not in p.parts)


def _relative(path: Path) -> str:
    return path.relative_to(_TESTS).as_posix()


def test_no_test_replaces_an_os_function_for_the_whole_process_outside_the_allowlist():
    offenders = []
    for path in _test_files():
        if _relative(path) in _DELIBERATE:
            continue
        lines = process_wide_os_patches(path.read_text(encoding="utf-8"))
        offenders += [f"{_relative(path)}:{n}" for n in lines]
    assert not offenders, (
        "these replace an os function for every thread and caller, the test runner included; use tests.os_scope.scope_os(monkeypatch, <module under test>, "
        f"<name>=<replacement>) (R351): {offenders}"
    )


@pytest.mark.parametrize("name", sorted(_DELIBERATE))
def test_every_allowlisted_file_still_has_the_replacement_it_is_excused_for(name):
    assert process_wide_os_patches((_TESTS / name).read_text(encoding="utf-8")), (
        f"{name} no longer replaces an os function process-wide: remove its entry from _DELIBERATE"
    )


@pytest.mark.parametrize(
    ("source", "lines"),
    [
        # the shapes #1602 found
        ('import os\n\nmonkeypatch.setattr(os, "replace", f)\n', [3]),
        ('import os\n\nmonkeypatch.setattr(mod.os, "fsync", f)\n', [3]),
        ('import os\n\nmonkeypatch.setattr("os.kill", f)\n', [3]),
        ('import os\n\nmock.patch("src.x.os.replace", f)\n', [3]),
        ('import os\n\nmock.patch.object(os, "replace", f)\n', [3]),
        ('import os\n\nmonkeypatch.delattr(os, "statvfs", raising=False)\n', [3]),
        # the blind spots it listed: os.path and its modules
        ('import os\n\nmonkeypatch.setattr(os.path, "getsize", f)\n', [3]),
        ('import os\n\nmonkeypatch.setattr(mod.os.path, "exists", f)\n', [3]),
        ('import os\n\nmonkeypatch.setattr(posixpath, "exists", f)\n', [3]),
        ('import os\n\nmonkeypatch.setattr(ntpath, "exists", f)\n', [3]),
        ('import os\n\nmonkeypatch.setattr("os.path.getsize", f)\n', [3]),
        ('import os\n\nmonkeypatch.setattr("posixpath.exists", f)\n', [3]),
        ('import os\n\nmock.patch("pkg.mod.os.path.exists", f)\n', [3]),
        # aliases
        ('import os as _os\n\nmonkeypatch.setattr(_os, "replace", f)\n', [3]),
        ('import os.path as osp\n\nmonkeypatch.setattr(osp, "getsize", f)\n', [3]),
        ('from os import path as P\n\nmonkeypatch.setattr(P, "getsize", f)\n', [3]),
        ('from os import path\n\nmonkeypatch.setattr(path, "getsize", f)\n', [3]),
        ('import posixpath as pp\n\nmonkeypatch.setattr(pp, "exists", f)\n', [3]),
        # keyword forms
        ('import os\n\nmonkeypatch.setattr(target=os, name="replace", value=f)\n', [3]),
        ('import os\n\nmock.patch.object(target=os, attribute="replace")\n', [3]),
        # patch.multiple
        ('import os\n\nmock.patch.multiple(os, replace=f)\n', [3]),
        ('import os\n\nmock.patch.multiple("os", replace=f)\n', [3]),
        ('import os\n\nmock.patch.multiple("os.path", exists=f)\n', [3]),
        ('import os\n\nmock.patch.multiple(target=os.path, exists=f)\n', [3]),
        # assignment
        ('import os\n\nos.replace = f\n', [3]),
        ('import os\n\nmod.os.replace = f\n', [3]),
        ('import os\n\nos.path.getsize = f\n', [3]),
        ('import os\n\nos.replace: object = f\n', [3]),
        ('import os\n\nos.counter += 1\n', [3]),
        ('import os\n\ndel os.statvfs\n', [3]),
        # not a process-wide replacement
        ('import os\n\nscope_os(monkeypatch, mod, replace=f)\n', []),
        ('import os\n\nscope_os_path(monkeypatch, mod, getsize=f)\n', []),
        ('import os\n\nmonkeypatch.setattr(mod, "os", namespace)\n', []),
        ('import os\n\nmod.os = namespace\n', []),
        ('import os\n\nmonkeypatch.setattr(builtins, "open", f)\n', []),
        ('import os\n\nmonkeypatch.setattr(seen, "path", path)\n', []),
        ('import os\n\nmonkeypatch.setattr(os.environ, "X", "1")\n', []),
        ('import os\n\nmock.patch("pkg.mod.os", namespace)\n', []),
        ('import os\n\nvalue = os.path.join("a", "b")\n', []),
    ],
)
def test_the_scanner_finds_each_shape_on_its_exact_line_and_nothing_else(source, lines):
    assert process_wide_os_patches(source) == lines


def test_the_scan_covers_helpers_conftests_and_subdirectories_not_only_top_level_test_files():
    scanned = {_relative(p) for p in _test_files()}
    assert {"conftest.py", "os_scope.py", "torture_helper.py"} <= scanned, scanned
    assert any("/" in name for name in scanned), "no file under a tests/ subdirectory is scanned"
    assert Path(__file__).name not in scanned
