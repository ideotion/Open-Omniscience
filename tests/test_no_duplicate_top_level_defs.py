"""No module in ``src``, ``scripts`` or ``tests`` defines the same function or class name twice in one scope.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A second ``def name`` in the same scope silently replaces the first for every caller, the calls written for the first included, and nothing
says so. ``src/monitoring/forensics.py`` carried ``_seconds_between`` twice, one answering a float of seconds and one a whole number of seconds
that is ``None`` for a reversed order; the later one won for the whole module, and
``test_time_into_the_pass_is_unknown_not_zero_when_a_timestamp_cannot_be_read`` failed with ``1 == 1.5`` on ``main`` and in every pull request cut
from it. Each definition came from a different pull request that was green on its own tree.

WHY RUFF DID NOT SAY SO (measured with ruff 0.16.9; an independent read found it, the first version of this note had the cause wrong): F811
("redefinition of unused name") ignores every name that matches ``lint.dummy-variable-rgx``, whose default is ``^(_+|(_+[a-zA-Z0-9_]*[a-zA-Z0-9]+?))$``,
that is every name with a leading underscore: every module-private helper and every private method. The same file with the underscore removed from
``_seconds_between`` is reported (``Redefinition of unused 'seconds_between' from line 665``). A call inside a function body does NOT make the first
definition "used" for F811 (ruff resolves those after the module body, so they bind to the later definition); only a use at import time does, in the
module body. Tightening the regex for the whole repository is not the alternative: it takes the blocking ruff lane from 0 findings to 130.

This reads every ``*.py`` under ``src``, ``scripts`` and ``tests`` and FAILS on a name defined twice directly in a module body and, for every class,
twice directly in its body. READ NOT: a definition under an ``if`` / ``try`` / ``with`` (the platform and optional-import shapes), a name rebound by an
assignment or an import, the name ``_`` (the throwaway of route handlers), a name in two different modules or classes, and these repeats, which are
the intended shape: ``@typing.overload`` stubs (module level and class level), and in a class body the property pair (``@x.setter`` / ``.getter`` /
``.deleter``) and ``@x.register``. At module level ``register`` is NOT exempt: ``@singledispatch def f`` followed by ``@f.register(int) def f``
replaces the dispatcher with the int branch (measured), and ``@atexit.register def _cleanup`` followed by a plain ``def _cleanup`` is the bug. A
stub that follows a plain definition of its name is a repeat as well. Hidden folders and ``build`` / ``dist`` / virtual-environment folders are not
read, so a local environment under ``scripts/`` does not turn the gate red where CI's clean checkout is green.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCANNED = ("src", "scripts", "tests")

#: Folders that hold someone else's code or generated files, wherever they sit under a scanned root.
_NOT_OURS = {"build", "dist", "venv", "site-packages", "node_modules", "__pycache__"}

#: Decorators whose last word makes a repeated name the intended shape in a MODULE body: only ``typing.overload`` stubs.
_MODULE_REPEAT_OK = {"overload"}
#: ... and in a CLASS body: stubs, the property pair and ``register``.
_CLASS_REPEAT_OK = {"overload", "setter", "getter", "deleter", "register"}

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _decorator_word(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _repeats_in(body: list[ast.stmt], repeat_ok: set[str], scope: str) -> list[tuple[str, int, int]]:
    """``(scope name, first line, second line)`` for each name defined twice directly in ``body``.

    ``@overload`` stubs are the intended shape only BEFORE the implementation (stubs, then the plain definition): a stub that follows the plain
    definition of its name is a repeat, because the stub then replaces it. The other words in ``repeat_ok`` (a class body's property pair and
    ``register``) are a repeat of nothing when they follow a definition of the name."""
    first: dict[str, int] = {}
    state: dict[str, str] = {}  # "stubs": only overload stubs so far; "real": a definition that is not a stub
    found: list[tuple[str, int, int]] = []
    for node in body:
        if not isinstance(node, _DEFS) or node.name == "_":
            continue
        words = {_decorator_word(d) for d in node.decorator_list}
        stub = "overload" in words and "overload" in repeat_ok
        free = bool(words & (repeat_ok - {"overload"}))
        before = state.get(node.name)
        if before is None:
            first[node.name] = node.lineno
            state[node.name] = "stubs" if stub else "real"
        elif stub:
            if before == "real":
                found.append((f"{scope}{node.name}", first[node.name], node.lineno))
        elif before == "stubs":
            state[node.name] = "real"  # the implementation that follows its stubs
        elif not free:
            found.append((f"{scope}{node.name}", first[node.name], node.lineno))
    return found


def _repeated(source: str | bytes, filename: str = "<source>") -> list[tuple[str, int, int]]:
    """Every name defined twice in one scope of ``source``: in the module body, and in the body of each class (nested ones too)."""
    tree = ast.parse(source, filename=filename)
    found = _repeats_in(tree.body, _MODULE_REPEAT_OK, "")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            found.extend(_repeats_in(node.body, _CLASS_REPEAT_OK, f"{node.name}."))
    return found


def _modules(root: str, anchor: Path = _ROOT) -> list[Path]:
    base = anchor / root
    return sorted(
        p
        for p in base.rglob("*.py")
        if not any(part.startswith(".") or part in _NOT_OURS for part in p.relative_to(base).parts)
    )


@pytest.mark.parametrize("root", _SCANNED)
def test_no_module_defines_a_name_twice_in_one_scope(root):
    bad = []
    for path in _modules(root):
        for name, one, two in _repeated(path.read_bytes(), str(path.relative_to(_ROOT))):
            bad.append(f"{path.relative_to(_ROOT)}: {name} defined at line {one} and again at line {two}")
    assert not bad, "the later definition replaces the earlier one:\n" + "\n".join(bad)


def test_the_scan_reads_each_root_and_flags_a_duplicate():
    for root, at_least in (("src", 100), ("scripts", 5), ("tests", 100)):
        assert len(_modules(root)) >= at_least, f"the scan found almost no modules under {root}/: the root moved"
    two = "def f(a):\n    return 1\n\n\ndef g():\n    return f(1)\n\n\ndef f(a, b):\n    return 2\n"
    assert _repeated(two) == [("f", 1, 9)]
    cls = "class C:\n    pass\n\n\nclass C:\n    pass\n"
    assert _repeated(cls) == [("C", 1, 5)]


def test_a_private_name_is_read_as_well_as_a_public_one():
    # The shape that happened: ``_helper`` called from a function body between two definitions. ruff's F811 ignores it (every leading-underscore name).
    called = "def _h(a):\n    return 1\n\n\ndef caller():\n    return _h(1)\n\n\ndef _h(a, b):\n    return 2\n"
    assert _repeated(called) == [("_h", 1, 9)]
    used_at_import = "def f():\n    return 1\n\n\nx = f()\n\n\ndef f():\n    return 2\n"
    assert _repeated(used_at_import) == [("f", 1, 8)]


def test_a_method_defined_twice_is_read_and_a_property_pair_is_not():
    private = "class C:\n    def _m(self):\n        return 1\n\n    def _m(self):\n        return 2\n"
    assert _repeated(private) == [("C._m", 2, 5)]
    nested = "class A:\n    class B:\n        def m(self):\n            pass\n\n        def m(self):\n            pass\n"
    assert _repeated(nested) == [("B.m", 3, 6)]
    prop = (
        "class C:\n"
        "    @property\n    def v(self):\n        return 1\n\n"
        "    @v.setter\n    def v(self, value):\n        pass\n\n"
        "    @v.deleter\n    def v(self):\n        pass\n"
    )
    assert _repeated(prop) == []


def test_a_repeat_the_module_means_is_not_flagged_and_one_it_does_not_is():
    platform = (
        "import sys\nif sys.platform == 'win32':\n    def h():\n        return 1\nelse:\n    def h():\n        return 2\n"
    )
    assert _repeated(platform) == []
    stubs = (
        "from typing import overload\n"
        "@overload\ndef k(a: int) -> int: ...\n"
        "@overload\ndef k(a: str) -> str: ...\n"
        "def k(a):\n    return a\n"
    )
    assert _repeated(stubs) == []
    assert _repeated("def _():\n    pass\n\n\ndef _():\n    pass\n") == []
    # A stub after the plain definition, a plain one after a ``register`` and a ``register`` at module level are repeats: the later wins at run time.
    stub_after = "from typing import overload\ndef k(a):\n    return a\n@overload\ndef k(a: int) -> int: ...\n"
    assert _repeated(stub_after) == [("k", 2, 5)]
    register_then_plain = "import atexit\n@atexit.register\ndef _cleanup():\n    pass\n\n\ndef _cleanup():\n    pass\n"
    assert _repeated(register_then_plain) == [("_cleanup", 3, 7)]
    dispatcher = "from functools import singledispatch\n@singledispatch\ndef f(x):\n    return 1\n@f.register(int)\ndef f(x):\n    return 2\n"
    assert _repeated(dispatcher) == [("f", 3, 6)]


def test_a_file_that_does_not_parse_is_named_and_a_bom_or_an_encoding_cookie_is_read():
    with pytest.raises(SyntaxError) as raised:
        _repeated(b"def (:\n", "some/where.py")
    assert raised.value.filename == "some/where.py"
    assert _repeated("\ufeffdef f():\n    pass\n".encode()) == []
    assert _repeated("# -*- coding: latin-1 -*-\ndef f():\n    return 'é'\n".encode("latin-1")) == []


def test_a_virtual_environment_or_build_folder_under_a_root_is_not_read(tmp_path):
    for name in (".venv/lib/site-packages/pkg", "build/lib", "scripts_ok"):
        folder = tmp_path / "scripts" / name
        folder.mkdir(parents=True)
        (folder / "m.py").write_text("def f():\n    pass\n\n\ndef f():\n    pass\n", encoding="utf-8")
    assert [p.relative_to(tmp_path).as_posix() for p in _modules("scripts", tmp_path)] == ["scripts/scripts_ok/m.py"]
