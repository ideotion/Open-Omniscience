"""No module in ``src`` or ``scripts`` defines the same top-level function or class twice.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A second ``def name`` at module level silently replaces the first for every caller in the module, the calls written for the first
included, and nothing says so: ruff's F811 stays quiet when the first definition was used before the second appears, which is the usual
case (a helper is written, called, and a later change defines another by the same name). ``src/monitoring/forensics.py`` carried
``_seconds_between`` twice, one answering a float of seconds and one a whole number of seconds that is ``None`` for a reversed order; the later
one won for the whole module, and ``test_time_into_the_pass_is_unknown_not_zero_when_a_timestamp_cannot_be_read`` failed with ``1 == 1.5`` on
``main`` and in every pull request cut from it. Each definition came from a different pull request that was green on its own tree.

This reads every ``*.py`` under ``src`` and ``scripts`` and FAILS on a name defined twice DIRECTLY in a module body. It does not read:
a definition under an ``if`` or ``try`` (the platform and optional-import shapes), a ``@typing.overload`` stub, a ``@x.setter`` /
``@x.register`` second definition, a method (a class body is its own scope; ruff covers it with F811 because a method is rarely called
between two definitions), or a name in two different modules. Tests are not scanned: a pytest module that repeats a test name loses the
first test silently, which ruff reports as F811 on its own because a test is never called in between.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCANNED = ("src", "scripts")

#: Decorators that make a second definition of the same name the intended shape: ``typing.overload`` stubs and the
#: ``functools.singledispatch`` / property ``.register`` / ``.setter`` / ``.getter`` / ``.deleter`` family.
_REPEAT_OK = {"overload", "register", "setter", "getter", "deleter"}


def _decorator_word(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _repeated(source: str) -> list[tuple[str, int, int]]:
    """``(name, first line, second line)`` for each name defined twice directly in the module body."""
    first: dict[str, int] = {}
    found: list[tuple[str, int, int]] = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if any(_decorator_word(d) in _REPEAT_OK for d in node.decorator_list):
            continue
        if node.name in first:
            found.append((node.name, first[node.name], node.lineno))
        first[node.name] = node.lineno
    return found


def _modules() -> list[Path]:
    return sorted(p for top in _SCANNED for p in (_ROOT / top).rglob("*.py"))


def test_no_module_defines_a_top_level_name_twice():
    bad = []
    for path in _modules():
        for name, one, two in _repeated(path.read_text(encoding="utf-8")):
            bad.append(f"{path.relative_to(_ROOT)}: {name} defined at line {one} and again at line {two}")
    assert not bad, "the later definition replaces the earlier for the whole module:\n" + "\n".join(bad)


def test_the_scan_reads_the_tree_and_flags_a_duplicate():
    assert len(_modules()) > 100, "the scan found almost no modules: the roots moved"
    two = "def f(a):\n    return 1\n\n\ndef g():\n    return f(1)\n\n\ndef f(a, b):\n    return 2\n"
    assert _repeated(two) == [("f", 1, 9)]
    cls = "class C:\n    pass\n\n\nclass C:\n    pass\n"
    assert _repeated(cls) == [("C", 1, 5)]
    # A repeated name the module means: a platform split, an overload stub, a property pair.
    fine = (
        "import sys\n"
        "if sys.platform == 'win32':\n    def h():\n        return 1\nelse:\n    def h():\n        return 2\n"
        "from typing import overload\n"
        "@overload\ndef k(a: int) -> int: ...\n"
        "@overload\ndef k(a: str) -> str: ...\n"
        "def k(a):\n    return a\n"
    )
    assert _repeated(fine) == []
    # A repeat of the same name is flagged even when the first one is called in between, the case ruff's F811 does not report.
    used = "def f():\n    return 1\n\n\nx = f()\n\n\ndef f():\n    return 2\n"
    assert _repeated(used) == [("f", 1, 8)]
