"""No test replaces a function of the ``os`` module for the whole process (R351, after R344 and R350).

``monkeypatch.setattr(os, "replace", f)`` and ``monkeypatch.setattr(module.os, "replace", f)`` are the same call: ``module.os`` IS the ``os`` module,
so every thread and every caller, the test runner among them, is handed ``f``. pytest 9.2.0 began calling ``os.fstat`` at the end of each test phase
and a test that had replaced it that way went red on every head (R350). ``tests/os_scope.py`` (``scope_os``) binds the replacement to the one name
the module under test reads. This guard reads every test file's AST and fails on a replacement it finds anywhere else.

The allowlist is the only exception, each entry with its reason, and a stale entry (one that no longer matches a call) fails too, so it cannot rot.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PATCHERS = {"setattr", "delattr"}
_STRING_TARGET = re.compile(r"(^|\.)os\.[A-Za-z_]+$")

#: file -> why a process-wide replacement is the point of that test and not an accident
_DELIBERATE = {
    "test_backend_launch.py": "a GUARD that no process anywhere is signalled by a stop of a daemon the app did not spawn: the replacement records any os.kill, whoever calls it",
    "test_gpu_arbitration.py": "a GUARD that releasing the card signals no process anywhere: the replacement records any os.kill, whoever calls it",
    "test_session_hwm_light.py": "an OBSERVATION spy that passes through to the real os.open: it records every route into /proc the sampler could take, in any module it calls",
}


def _is_os(node: ast.AST) -> bool:
    """``os`` or ``<anything>.os``: the module itself, however a test reached it."""
    return (isinstance(node, ast.Name) and node.id == "os") or (isinstance(node, ast.Attribute) and node.attr == "os")


def process_wide_os_patches(source: str) -> list[int]:
    """Line numbers of calls that replace (or delete) a function of ``os`` itself."""
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        first = node.args[0]
        if name in _PATCHERS and _is_os(first):
            found.append(node.lineno)
        elif name in {"setattr", "patch"} and isinstance(first, ast.Constant) and isinstance(first.value, str) and _STRING_TARGET.search(first.value):
            found.append(node.lineno)  # monkeypatch.setattr("os.kill", f), mock.patch("pkg.mod.os.replace")
        elif name == "object" and _is_os(first):
            found.append(node.lineno)  # mock.patch.object(os, "replace", ...)
    return sorted(set(found))


def _test_files() -> list[Path]:
    return sorted(p for p in _TESTS.glob("test_*.py") if p.name != Path(__file__).name)


def test_no_test_replaces_an_os_function_for_the_whole_process_outside_the_allowlist():
    offenders = []
    for path in _test_files():
        if path.name in _DELIBERATE:
            continue
        lines = process_wide_os_patches(path.read_text(encoding="utf-8"))
        offenders += [f"{path.name}:{n}" for n in lines]
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
    ("line", "flagged"),
    [
        ('monkeypatch.setattr(os, "replace", f)', True),
        ('monkeypatch.setattr(mod.os, "fsync", f)', True),
        ('monkeypatch.setattr("os.kill", f)', True),
        ('mock.patch("src.x.os.replace", f)', True),
        ('mock.patch.object(os, "replace", f)', True),
        ('monkeypatch.delattr(os, "statvfs", raising=False)', True),
        ('scope_os(monkeypatch, mod, replace=f)', False),
        ('monkeypatch.setattr(mod, "os", namespace)', False),
        ('monkeypatch.setattr(builtins, "open", f)', False),
        ('monkeypatch.setattr(posixpath, "exists", f)', False),
    ],
)
def test_the_scanner_finds_each_shape_on_its_exact_line_and_nothing_else(line, flagged):
    assert process_wide_os_patches(f"import os\n\n{line}\n") == ([3] if flagged else [])
