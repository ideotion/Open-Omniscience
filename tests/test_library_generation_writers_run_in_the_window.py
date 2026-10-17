"""Every call of a writer of ``library_generation``'s state, in ``src/``, is made inside a swap window (the WAL thread, 17 Oct 2026).

THE CLAIM IT KEEPS TRUE. ``library_generation`` writes four names (``_GENERATION``, ``_VALID``, ``_WINDOW_STAMP``, ``_DISK_CHANGED``) with no lock of
their own, because every write happens on the thread that holds the exclusive library window, and the window is held by one thread at a time. A
lock of their own guarded nothing else and had one effect: a plain lock whose ``with`` exit fails stays held and blocks every later section with
the window held (``test_swap_window_allocation_failures.py``). The argument stands only while no writer is called from anywhere else, so this test
reads the source of ``src/`` and fails a call that is not inside ``swap_window`` (in the module itself) or inside the BODY of a
``with <...>.swap_window(...)`` block (everywhere else: the restore, the repair and the encrypt call ``disk_changing`` there). A call made from a
helper that the window's body calls, or from a function defined inside the block, is a violation too: the pin cannot know that the helper only
runs inside a window, so the call goes into the block itself, or this pin and the argument above are re-read together.
It also fails a store to one of the four names from outside the writers, in the module or through an alias of it from any other module of ``src/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_MODULE = "src.database.library_generation"
_MODULE_FILE = "database/library_generation.py"
_WRITERS = frozenset({"bump", "disk_changing", "_open_window", "_close_window"})
_FIELDS = frozenset({"_GENERATION", "_VALID", "_WINDOW_STAMP", "_DISK_CHANGED"})
#: The functions of the module that may assign the four names (``swap_window`` resets the flag; the rest are the writers).
_MAY_ASSIGN = _WRITERS | {"swap_window"}


def _aliases(tree: ast.AST) -> tuple[set[str], dict[str, str], set[str]]:
    """Names this module binds to ``library_generation``, to its writers (alias -> real name), and to its ``swap_window``, at any scope."""
    modules: set[str] = set()
    writers: dict[str, str] = {}
    windows: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.database":
            modules.update(a.asname or a.name for a in node.names if a.name == "library_generation")
        elif isinstance(node, ast.Import):
            modules.update(a.asname for a in node.names if a.name == _MODULE and a.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == _MODULE:
            for a in node.names:
                if a.name in _WRITERS:
                    writers[a.asname or a.name] = a.name
                elif a.name == "swap_window":
                    windows.add(a.asname or a.name)
    return modules, writers, windows


def _violations(source_text: str, *, is_the_module: bool = False) -> tuple[list[str], list[str]]:
    """(calls of a writer that are not inside a window or stores to the four names from outside the writers, the writers called at all)."""
    tree = ast.parse(source_text)
    modules, writers, windows = _aliases(tree)
    parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    def writer_called(call: ast.Call) -> str | None:
        func = call.func
        if is_the_module:
            return func.id if isinstance(func, ast.Name) and func.id in _WRITERS else None
        if isinstance(func, ast.Attribute) and func.attr in _WRITERS and isinstance(func.value, ast.Name) and func.value.id in modules:
            return func.attr
        if isinstance(func, ast.Name) and writers.get(func.id) in _WRITERS:
            return writers[func.id]
        return None

    def opens_a_window(node: ast.With) -> bool:
        for item in node.items:
            expr = item.context_expr
            if not isinstance(expr, ast.Call):
                continue
            func = expr.func
            if isinstance(func, ast.Attribute) and func.attr == "swap_window" and isinstance(func.value, ast.Name) and func.value.id in modules:
                return True
            if isinstance(func, ast.Name) and (func.id in windows or (is_the_module and func.id == "swap_window")):
                return True
        return False

    def inside_a_window(node: ast.AST) -> bool:
        child, parent = node, parents.get(id(node))
        while parent is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return is_the_module and isinstance(parent, ast.FunctionDef) and parent.name == "swap_window" and parent in tree.body
            if isinstance(parent, ast.With) and child in parent.body and opens_a_window(parent):
                return True
            child, parent = parent, parents.get(id(parent))
        return False

    bad: list[str] = []
    called: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (name := writer_called(node)):
            called.append(name)
            if not inside_a_window(node):
                bad.append(f"line {node.lineno}: {name}() is called outside a swap window")
        elif not is_the_module and isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and t.attr in _FIELDS and isinstance(t.value, ast.Name) and t.value.id in modules:
                    bad.append(f"line {node.lineno}: {t.value.id}.{t.attr} is stored outside the module's writers")
    if is_the_module:
        for fn in tree.body:
            if isinstance(fn, ast.FunctionDef) and fn.name not in _MAY_ASSIGN:
                for g in ast.walk(fn):
                    if isinstance(g, ast.Global) and _FIELDS.intersection(g.names):
                        bad.append(f"line {g.lineno}: {fn.name}() assigns {sorted(_FIELDS.intersection(g.names))} but is not one of the writers")
    return bad, called


def test_every_call_of_a_writer_in_src_is_made_inside_a_swap_window():
    problems: list[str] = []
    called: set[tuple[str, str]] = set()
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        bad, names = _violations(path.read_text(encoding="utf-8"), is_the_module=(rel == _MODULE_FILE))
        problems += [f"src/{rel} {b}" for b in bad]
        called.update((rel, n) for n in names)
    assert problems == [], problems
    # anti-vacuity: the pin saw the swap's own calls and the two callers that change the disk
    assert {(_MODULE_FILE, "bump"), (_MODULE_FILE, "_open_window"), (_MODULE_FILE, "_close_window")} <= called, sorted(called)
    assert {("backup/merge.py", "disk_changing"), ("database/encrypt_tool.py", "disk_changing")} <= called, sorted(called)


_ELSEWHERE = "from src.database import library_generation as g\n"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (_ELSEWHERE + "def f():\n    g.disk_changing()\n", 1),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(p):\n        g.disk_changing()\n", 0),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(p):\n        pass\n    g.disk_changing()\n", 1),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(p):\n        def later():\n            g.disk_changing()\n", 1),
        (_ELSEWHERE + "def f(p, other):\n    with other.lock(p):\n        g.disk_changing()\n", 1),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(g.disk_changing()):\n        pass\n", 1),
        (_ELSEWHERE + "def f(p):\n    with open(p) as fh, g.swap_window(p):\n        g.disk_changing()\n", 0),
        ("from src.database.library_generation import disk_changing as dc\ndef f():\n    dc()\n", 1),
        ("from src.database.library_generation import disk_changing as dc, swap_window as sw\ndef f(p):\n    with sw(p):\n        dc()\n", 0),
        ("import src.database.library_generation as g\ndef f():\n    g.bump()\n", 1),
        (_ELSEWHERE + "def f():\n    g._VALID = frozenset()\n", 1),
        (_ELSEWHERE + "def f():\n    g._WINDOW_STAMP = None\n", 1),
        ("class Other:\n    def disk_changing(self):\n        pass\ndef f(o):\n    o.disk_changing()\n", 0),
    ],
    ids=[
        "call_outside",
        "call_in_the_body",
        "call_after_the_block",
        "call_in_a_function_defined_in_the_block",
        "call_in_another_with",
        "call_in_the_items",
        "call_in_a_second_item_window",
        "from_import_outside",
        "from_import_inside",
        "bump_through_import_as",
        "store_valid",
        "store_stamp",
        "unrelated_method_of_the_same_name",
    ],
)
def test_the_pin_tells_a_call_inside_a_window_from_one_outside(source, expected):
    bad, _ = _violations(source)
    assert len(bad) == expected, bad


def test_inside_the_module_only_swap_window_calls_the_writers_and_only_the_writers_assign():
    ok = (
        "def bump():\n    global _GENERATION, _VALID\n    _GENERATION += 1\n"
        "def swap_window(source):\n    global _DISK_CHANGED\n    _DISK_CHANGED = False\n    bump()\n    _open_window()\n    _close_window(swapped=True)\n"
    )
    assert _violations(ok, is_the_module=True)[0] == []
    outside = "def swap_window(source):\n    pass\ndef connecting():\n    bump()\n"
    assert len(_violations(outside, is_the_module=True)[0]) == 1
    assigns = "def connecting():\n    global _VALID\n    _VALID = frozenset()\n"
    assert len(_violations(assigns, is_the_module=True)[0]) == 1
    nested = "def swap_window(source):\n    def later():\n        bump()\n"
    assert len(_violations(nested, is_the_module=True)[0]) == 1
