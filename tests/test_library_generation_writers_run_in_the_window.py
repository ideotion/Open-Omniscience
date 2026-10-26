"""The writers of ``library_generation``'s state are reached only while a swap window is held (the WAL thread, 17 Oct 2026).

THE CLAIM IT KEEPS TRUE. ``library_generation`` writes four names (``_GENERATION``, ``_VALID``, ``_WINDOW_STAMP``, ``_DISK_CHANGED``) with no lock of
their own, because every write happens on the thread that holds the exclusive library window, and the window is held by one thread at a time. A
lock of their own guarded nothing else and had one effect: a plain lock whose ``with`` exit fails stays held and blocks every later section with
the window held (``test_swap_window_allocation_failures.py``). The argument stands only while no writer is reached from anywhere else.

WHAT IT CHECKS. It is an AST pin over ``src/`` (not ``scripts/``: the signal-leak probe sets the stamp by hand, outside any window, as the cleanup
of its own measurement), not a proof. It reads ``src/`` and fails:

* a call of a writer (``bump``, ``disk_changing``, ``_open_window``, ``_close_window``) that is not inside the BODY of a ``with <...>.swap_window(...)``
  block, or, in the module itself, not inside the part of ``swap_window`` that runs while this thread holds the window (after its ``_LOCK.exclusive``
  call, or in the cleanup behind ``held_here()``). A call from a function defined inside the block is a violation too: it may run later, on another
  thread. So is a call from a helper that the block's body calls: the pin cannot know the helper only runs inside a window, so the call goes into the
  block itself, or this pin and the argument above are re-read together;
* a writer that is REFERENCED and not called (``Thread(target=g.disk_changing)``, ``atexit.register(g.bump)``, ``f = g.disk_changing``): a reference
  can be run anywhere. Likewise ``getattr``/``setattr``/``hasattr``/``delattr`` given the name of a writer or of one of the four names as a string, and
  ``globals()`` in the module;
* a store to one of the four names from another module (an attribute store, in any form a store can take: plain, augmented, tuple, ``for`` or ``with``
  target), and in the module a ``global`` of them from anything that is not one of the writers (a method, an async function, a nested function);
* the module and the writers are found through every import form of ``src/``: ``from src.database import library_generation [as x]``, the relative
  forms (``from . import library_generation``, ``from ..database import library_generation``, ``from .library_generation import bump``), the bare
  ``import src.database.library_generation`` and its ``as`` form.

WHAT IT CANNOT SEE: a module reached by a computed name (``importlib.import_module(name)``) or a writer reached through an object that holds it. The
last tests in this file therefore also RUN the one placement that matters (the reset of the flag before the window is had) against the real source.
"""

from __future__ import annotations

import ast
import sys
import tempfile
import threading
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_MODULE = "src.database.library_generation"
_PACKAGE = ("src", "database")
_LEAF = "library_generation"
_MODULE_FILE = "database/library_generation.py"
_WRITERS = frozenset({"bump", "disk_changing", "_open_window", "_close_window"})
_FIELDS = frozenset({"_GENERATION", "_VALID", "_WINDOW_STAMP", "_DISK_CHANGED"})
#: The functions of the module that may assign the four names (``swap_window`` resets the flag; the rest are the writers).
_MAY_ASSIGN = _WRITERS | {"swap_window"}
_BY_NAME = frozenset({"getattr", "setattr", "delattr", "hasattr"})


def _dotted(node: ast.AST) -> str | None:
    """``a.b.c`` for a chain of attributes ending in a name, else ``None``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _absolute(node: ast.ImportFrom, package: tuple[str, ...]) -> str | None:
    """The absolute module a ``from ... import`` names, given the package of the file it is in (``None`` when it climbs out of ``src``)."""
    if node.level == 0:
        return node.module
    base = package[: len(package) - (node.level - 1)]
    if not base:
        return None
    return ".".join([*base, *([node.module] if node.module else [])])


def _aliases(tree: ast.AST, package: tuple[str, ...]) -> tuple[set[str], dict[str, str], set[str], list[int]]:
    """What this file calls the module (dotted expressions), its writers (alias -> real name) and its ``swap_window``, at any scope; and the
    lines of any ``from <the module> import *`` (which hides what is bound)."""
    modules: set[str] = set()
    writers: dict[str, str] = {}
    windows: set[str] = set()
    stars: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            where = _absolute(node, package)
            if where == ".".join(_PACKAGE):
                modules.update(a.asname or a.name for a in node.names if a.name == _LEAF)
            elif where == _MODULE:
                for a in node.names:
                    if a.name == "*":
                        stars.append(node.lineno)
                    elif a.name in _WRITERS:
                        writers[a.asname or a.name] = a.name
                    elif a.name == "swap_window":
                        windows.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == _MODULE:
                    modules.add(a.asname or _MODULE)  # a bare import is used as the full dotted name
    return modules, writers, windows, stars


def _window_nodes(fn: ast.FunctionDef) -> set[int] | None:
    """The ids of the nodes of ``swap_window`` that run while this thread HOLDS the window: everything in the outer ``try`` after its
    ``_LOCK.exclusive(...)`` statement, and the cleanup in the outer ``finally`` that sits behind the ``held_here()`` check. ``None`` when the
    function no longer has the shape this reads (one outer ``try``, one such statement in it): the pin then says so and asks for a re-read."""
    outers = [s for s in fn.body if isinstance(s, ast.Try)]
    if len(outers) != 1:
        return None
    outer = outers[0]
    takes = [
        i
        for i, s in enumerate(outer.body)
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and _dotted(s.value.func) == "_LOCK.exclusive"
    ]
    if len(takes) != 1:
        return None
    held: set[int] = set()
    for s in outer.body[takes[0] + 1 :]:
        held.update(id(n) for n in ast.walk(s))
    for s in outer.finalbody:
        if isinstance(s, ast.Try):
            for inner in s.body:
                if isinstance(inner, ast.If) and any(isinstance(n, ast.Call) and _dotted(n.func) == "_LOCK.held_here" for n in ast.walk(inner.test)):
                    for st in inner.body:
                        held.update(id(n) for n in ast.walk(st))
    return held


def _violations(source_text: str, *, is_the_module: bool = False, package: tuple[str, ...] = ("src",)) -> tuple[list[str], list[str]]:
    """(what reaches a writer or one of the four names from outside a window, the writers called at all)."""
    if not is_the_module and _LEAF not in source_text:
        return [], []  # every way to name the module needs the import, and the import names it
    tree = ast.parse(source_text)
    modules, writers, windows, stars = _aliases(tree, package)
    parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    swap = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "swap_window"), None) if is_the_module else None
    held = _window_nodes(swap) if swap is not None else None
    bad: list[str] = [f"line {n}: `from {_MODULE} import *` hides which writers are bound" for n in stars]
    called: list[str] = []
    if swap is not None and held is None:
        bad.append(
            f"line {swap.lineno}: swap_window no longer has the shape this pin reads (one outer try, one `_LOCK.exclusive(...)` statement in its body); "
            "re-read the argument at the top of this file and the pin together"
        )
        held = set()

    def writer_of(node: ast.AST) -> str | None:
        if is_the_module:
            return node.id if isinstance(node, ast.Name) and node.id in _WRITERS else None
        if isinstance(node, ast.Attribute) and node.attr in _WRITERS and _dotted(node.value) in modules:
            return node.attr
        if isinstance(node, ast.Name) and node.id in writers:
            return writers[node.id]
        return None

    def opens_a_window(node: ast.With) -> bool:
        for item in node.items:
            expr = item.context_expr
            if not isinstance(expr, ast.Call):
                continue
            func = expr.func
            if isinstance(func, ast.Attribute) and func.attr == "swap_window" and _dotted(func.value) in modules:
                return True
            if isinstance(func, ast.Name) and (func.id in windows or (is_the_module and func.id == "swap_window")):
                return True
        return False

    def inside_a_window(node: ast.AST) -> bool:
        child, parent = node, parents.get(id(node))
        while parent is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                # the module's own swap_window: only the part that runs while the window is held
                return bool(is_the_module and parent is swap and held is not None and id(node) in held)
            if isinstance(parent, ast.With) and child in parent.body and opens_a_window(parent):
                return True
            child, parent = parent, parents.get(id(parent))
        return False

    def enclosing_function(node: ast.AST) -> ast.AST | None:
        parent = parents.get(id(node))
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            parent = parents.get(id(parent))
        return parent

    for node in ast.walk(tree):
        if (name := writer_of(node)) is not None and isinstance(getattr(node, "ctx", ast.Load()), ast.Load):
            parent = parents.get(id(node))
            if isinstance(parent, ast.Call) and parent.func is node:
                called.append(name)
                if not inside_a_window(parent):
                    bad.append(f"line {node.lineno}: {name}() is called outside a swap window")
            else:
                bad.append(f"line {node.lineno}: {name} is referenced without being called (a reference can be run anywhere)")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _BY_NAME and len(node.args) >= 2:
                arg = node.args[1]
                if isinstance(arg, ast.Constant) and arg.value in (_WRITERS | _FIELDS):
                    bad.append(f"line {node.lineno}: {func.id}(..., {arg.value!r}) reaches a writer or a field by its name")
            if is_the_module and isinstance(func, ast.Name) and func.id == "globals":
                bad.append(f"line {node.lineno}: globals() in the module can write the four names without naming them")
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if not is_the_module and node.attr in _FIELDS and _dotted(node.value) in modules:
                bad.append(f"line {node.lineno}: {_dotted(node)} is stored outside the module's writers")
        elif is_the_module and isinstance(node, ast.Global) and _FIELDS.intersection(node.names):
            fn = enclosing_function(node)
            if not (isinstance(fn, ast.FunctionDef) and fn in tree.body and fn.name in _MAY_ASSIGN):
                where = getattr(fn, "name", "the module")
                bad.append(f"line {node.lineno}: {where} assigns {sorted(_FIELDS.intersection(node.names))} but is not one of the writers")
        elif is_the_module and swap is not None and isinstance(node, ast.Name) and node.id in _FIELDS and isinstance(node.ctx, (ast.Store, ast.Del)):
            # ``swap_window`` resets the flag: that is a write, and it must be made while the window is held
            if enclosing_function(node) is swap and id(node) not in (held or set()):
                bad.append(f"line {node.lineno}: swap_window stores {node.id} before it holds the window (or after it let go)")
    return bad, called


def test_every_call_of_a_writer_in_src_is_made_inside_a_swap_window():
    problems: list[str] = []
    called: set[tuple[str, str]] = set()
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        package = ("src", *path.relative_to(_SRC).parent.parts)
        bad, names = _violations(path.read_text(encoding="utf-8"), is_the_module=(rel == _MODULE_FILE), package=package)
        problems += [f"src/{rel} {b}" for b in bad]
        called.update((rel, n) for n in names)
    assert problems == [], problems
    # anti-vacuity: the pin saw the swap's own calls and the two callers that change the disk
    assert {(_MODULE_FILE, "bump"), (_MODULE_FILE, "_open_window"), (_MODULE_FILE, "_close_window")} <= called, sorted(called)
    assert {("backup/merge.py", "disk_changing"), ("database/encrypt_tool.py", "disk_changing")} <= called, sorted(called)


_ELSEWHERE = "from src.database import library_generation as g\n"
_DIAG = ("src", "api", "diagnostics")


@pytest.mark.parametrize(
    ("source", "package", "expected"),
    [
        (_ELSEWHERE + "def f():\n    g.disk_changing()\n", ("src",), 1),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(p):\n        g.disk_changing()\n", ("src",), 0),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(p):\n        pass\n    g.disk_changing()\n", ("src",), 1),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(p):\n        def later():\n            g.disk_changing()\n", ("src",), 1),
        (_ELSEWHERE + "def f(p, other):\n    with other.lock(p):\n        g.disk_changing()\n", ("src",), 1),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(g.disk_changing()):\n        pass\n", ("src",), 1),
        (_ELSEWHERE + "def f(p):\n    with open(p) as fh, g.swap_window(p):\n        g.disk_changing()\n", ("src",), 0),
        ("from src.database.library_generation import disk_changing as dc\ndef f():\n    dc()\n", ("src",), 1),
        ("from src.database.library_generation import disk_changing as dc, swap_window as sw\ndef f(p):\n    with sw(p):\n        dc()\n", ("src",), 0),
        ("import src.database.library_generation as g\ndef f():\n    g.bump()\n", ("src",), 1),
        (_ELSEWHERE + "def f():\n    g._VALID = frozenset()\n", ("src",), 1),
        (_ELSEWHERE + "def f():\n    g._WINDOW_STAMP = None\n", ("src",), 1),
        ("class Other:\n    def disk_changing(self):\n        pass\ndef f(o):\n    o.disk_changing()\n", ("src",), 0),
        # a writer REFERENCED and not called, inside a window too: a reference runs anywhere
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(p):\n        threading.Thread(target=g.disk_changing).start()\n", ("src",), 1),
        (_ELSEWHERE + "atexit.register(g.bump)\n", ("src",), 1),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(p):\n        dc = g.disk_changing\n        dc()\n", ("src",), 1),
        (_ELSEWHERE + "def f(p):\n    with g.swap_window(p):\n        getattr(g, 'disk_changing')()\n", ("src",), 1),
        (_ELSEWHERE + "def f():\n    setattr(g, '_VALID', frozenset())\n", ("src",), 1),
        # the import forms of src/
        ("from . import library_generation as g\ndef f():\n    g.bump()\n", ("src", "database"), 1),
        ("from .library_generation import bump\ndef f():\n    bump()\n", ("src", "database"), 1),
        ("from ..database import library_generation\ndef f():\n    library_generation.bump()\n", ("src", "api"), 1),
        ("from ..database import library_generation as g\ndef f(p):\n    with g.swap_window(p):\n        g.disk_changing()\n", ("src", "api"), 0),
        ("from .. import library_generation as g\ndef f():\n    g.bump()\n", _DIAG, 0),  # src.api.library_generation: another module
        ("from ...database import library_generation as g\ndef f():\n    g.bump()\n", _DIAG, 1),
        ("import src.database.library_generation\ndef f():\n    src.database.library_generation.bump()\n", ("src",), 1),
        ("import src.database.library_generation\ndef f(p):\n    with src.database.library_generation.swap_window(p):\n        src.database.library_generation.disk_changing()\n", ("src",), 0),
        ("from src.database.library_generation import *\n", ("src",), 1),
        # stores in every form a store takes
        (_ELSEWHERE + "def f():\n    g._VALID, g._WINDOW_STAMP = frozenset(), None\n", ("src",), 2),
        (_ELSEWHERE + "def f():\n    g._GENERATION += 1\n", ("src",), 1),
        (_ELSEWHERE + "def f():\n    for g._GENERATION in range(3):\n        pass\n", ("src",), 1),
        (_ELSEWHERE + "def f(x):\n    with x as g._VALID:\n        pass\n", ("src",), 1),
        (_ELSEWHERE + "def f():\n    return g._VALID\n", ("src",), 0),  # a read is not a write
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
        "thread_target_in_a_window",
        "atexit_register",
        "reference_in_a_variable",
        "getattr_by_name",
        "setattr_by_name",
        "relative_from_dot_import_module",
        "relative_from_dot_module_import_writer",
        "relative_dotdot_with_module_name",
        "relative_dotdot_inside_a_window",
        "relative_dotdot_from_another_package_is_another_module",
        "relative_dotdotdot",
        "bare_import_outside",
        "bare_import_inside",
        "star_import",
        "tuple_store",
        "augmented_store",
        "for_target_store",
        "with_target_store",
        "a_read_is_not_a_write",
    ],
)
def test_the_pin_tells_a_use_inside_a_window_from_one_outside(source, package, expected):
    bad, _ = _violations(source, package=package)
    assert len(bad) == expected, bad


#: A swap_window with the shape of the real one, to put a writer in or out of the part that holds the window.
_SWAP = (
    "def swap_window(source):\n"
    "    global _DISK_CHANGED\n"
    "    me = 1\n"
    "    try:\n"
    "{before}"
    "        _LOCK.exclusive(timeout)\n"
    "{after}"
    "    finally:\n"
    "        try:\n"
    "            if not before and _LOCK.held_here():\n"
    "                _close_window(swapped=swapped)\n"
    "{cleanup}"
    "        finally:\n"
    "            _LOCK.release_if_held_here(me)\n"
    "{last}"
)


def _swap(*, before: str = "", after: str = "", cleanup: str = "", last: str = "") -> str:
    return _SWAP.format(before=before, after=after, cleanup=cleanup, last=last) + "def bump():\n    global _GENERATION\n    _GENERATION += 1\n"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"after": "        _DISK_CHANGED = False\n        bump()\n        _open_window()\n"}, 0),
        ({"before": "        _DISK_CHANGED = False\n"}, 1),
        ({"before": "        bump()\n"}, 1),
        ({"before": "        _open_window()\n"}, 1),
        ({"after": "        _DISK_CHANGED = False\n", "cleanup": "                bump()\n"}, 0),
        ({"last": "    _close_window(swapped=True)\n"}, 1),
        ({"cleanup": "            _close_window(swapped=True)\n"}, 1),  # in the inner try, but outside the held_here() check
    ],
    ids=[
        "after_the_window_is_had",
        "flag_reset_before_the_window_is_had",
        "bump_before_the_window_is_had",
        "open_window_before_the_window_is_had",
        "cleanup_behind_held_here",
        "after_the_function",
        "in_the_finally_but_outside_held_here",
    ],
)
def test_inside_swap_window_only_the_part_that_holds_the_window_may_write(kwargs, expected):
    bad, _ = _violations(_swap(**kwargs), is_the_module=True)
    assert len(bad) == expected, bad


def test_inside_the_module_only_swap_window_calls_the_writers_and_only_the_writers_assign():
    ok = _swap(after="        _DISK_CHANGED = False\n        bump()\n")
    assert _violations(ok, is_the_module=True)[0] == []
    outside = _swap() + "def connecting():\n    bump()\n"
    assert len(_violations(outside, is_the_module=True)[0]) == 1
    assigns = _swap() + "def connecting():\n    global _VALID\n    _VALID = frozenset()\n"
    assert len(_violations(assigns, is_the_module=True)[0]) == 1
    nested = _swap() + "def helper(source):\n    def later():\n        bump()\n"
    assert len(_violations(nested, is_the_module=True)[0]) == 1
    nested_in_swap = _swap(after="        def later():\n            bump()\n")
    assert len(_violations(nested_in_swap, is_the_module=True)[0]) == 1


@pytest.mark.parametrize(
    "extra",
    [
        "class _Lock:\n    def reset(self):\n        global _VALID\n        _VALID = frozenset()\n",
        "async def later():\n    global _WINDOW_STAMP\n    _WINDOW_STAMP = None\n",
        "def connecting():\n    def inner():\n        global _GENERATION\n        _GENERATION = 0\n    inner()\n",
        "def connecting():\n    globals()['_VALID'] = frozenset()\n",
        "def connecting():\n    return bump\n",
        "def connecting():\n    setattr(sys.modules[__name__], '_VALID', frozenset())\n",
    ],
    ids=["method", "async_function", "nested_function", "globals_call", "writer_referenced", "setattr_by_name"],
)
def test_inside_the_module_a_write_from_anything_but_a_writer_is_seen(extra):
    assert len(_violations(_swap() + extra, is_the_module=True)[0]) == 1


def test_a_swap_window_that_changed_shape_is_said_so_and_not_read_as_clean():
    assert len(_violations("def swap_window(source):\n    pass\n", is_the_module=True)[0]) == 1
    two = "def swap_window(source):\n    try:\n        pass\n    finally:\n        pass\n    try:\n        pass\n    finally:\n        pass\n"
    assert len(_violations(two, is_the_module=True)[0]) == 1


# --- the real source, moved one line at a time ------------------------------------------------------------------------------------------------
_REAL = (_SRC / _MODULE_FILE).read_text(encoding="utf-8")
_TAKE = "        _LOCK.exclusive(timeout)\n"
_RESET = "        _DISK_CHANGED = False\n"
#: (what the real source has, what it becomes). Each puts one writer, or the reset of the flag, where the window is not held.
_MUTANTS = {
    "the_flag_reset_above_the_window": (_TAKE + "        earlier = _VALID\n" + _RESET, _RESET + _TAKE + "        earlier = _VALID\n"),
    "bump_above_the_window": (_TAKE, "        bump()\n" + _TAKE),
    "open_window_above_the_window": (_TAKE, "        _open_window()\n" + _TAKE),
    "close_after_the_release": (
        "            if not before:\n                _LOCK.release_if_held_here(me)",
        "            if not before:\n                _LOCK.release_if_held_here(me)\n                _close_window(swapped=swapped, earlier=earlier)",
    ),
}


def test_the_real_module_is_clean_and_each_move_of_a_writer_out_of_the_window_is_seen():
    assert _violations(_REAL, is_the_module=True)[0] == []
    for name, (old, new) in _MUTANTS.items():
        assert _REAL.count(old) == 1, f"{name}: the module no longer reads as this test expects; re-read the pin with the change"
        bad, _ = _violations(_REAL.replace(old, new), is_the_module=True)
        assert len(bad) == 1, (name, bad)


# --- and the one that matters, run -------------------------------------------------------------------------------------------------------------


def _load_copy(text: str, name: str, monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """An isolated copy of the module's source, so a test can run a changed one without touching the process-wide state of the real one."""
    mod = types.ModuleType(name)
    mod.__file__ = f"<{name}>"
    monkeypatch.setitem(sys.modules, name, mod)
    exec(compile(text, mod.__file__, "exec"), mod.__dict__)  # noqa: S102 - the repository's own module, read from the tree
    return mod


def _what_stays_valid_when_a_swap_waits_behind_one_that_changed_the_disk(lg: types.ModuleType) -> tuple[frozenset[int], int]:
    """Swap A changes the disk (``disk_changing``) and its replace fails, so the source is still there. Swap B starts while A holds the window and
    waits for it. (The valid set at A's close, A's generation.) The connections from before A must NOT be valid again: the files under them had
    their log names removed."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "live.db"
        source.write_text("x", encoding="utf-8")
        reached = threading.Event()
        seen: dict[str, object] = {}
        take, give = lg._LOCK.exclusive, lg._LOCK.release_if_held_here

        def take_noted(timeout: float) -> None:
            if threading.current_thread().name == "swap-b":
                reached.set()  # B is at the window; whatever it did before this line has been done
            return take(timeout)

        def give_noted(me: int) -> None:
            if threading.current_thread().name == "swap-a" and "valid" not in seen:
                seen["valid"], seen["generation"] = lg._VALID, lg._GENERATION  # A's cleanup has just run
            return give(me)

        lg._LOCK.exclusive, lg._LOCK.release_if_held_here = take_noted, give_noted  # type: ignore[method-assign]

        def swap_b() -> None:
            try:
                with lg.swap_window(source, timeout=10):
                    pass
            except BaseException as exc:  # noqa: BLE001 - handed to the test
                seen["b"] = repr(exc)

        def swap_a() -> None:
            with lg.swap_window(source, timeout=10):
                lg.disk_changing()
                threading.Thread(target=swap_b, name="swap-b", daemon=True).start()
                assert reached.wait(10), "swap B never got as far as asking for the window"

        a = threading.Thread(target=swap_a, name="swap-a")
        a.start()
        a.join(30)
        assert not a.is_alive() and "valid" in seen, seen
        return seen["valid"], seen["generation"]  # type: ignore[return-value]


def test_a_swap_that_waits_for_the_window_does_not_touch_the_flag_of_the_one_that_holds_it(monkeypatch):
    lg = _load_copy(_REAL, "_lg_real_copy", monkeypatch)
    valid, generation = _what_stays_valid_when_a_swap_waits_behind_one_that_changed_the_disk(lg)
    assert valid == frozenset({generation}), (sorted(valid), generation)


def test_the_same_run_sees_the_flag_reset_moved_above_the_window(monkeypatch):
    """Red without the order in ``swap_window``: with the reset above ``_LOCK.exclusive`` a swap that is only WAITING resets the flag of the swap that
    holds the window, and that one's cleanup gives the connections from before its disk change their validity back."""
    old, new = _MUTANTS["the_flag_reset_above_the_window"]
    assert _REAL.count(old) == 1
    lg = _load_copy(_REAL.replace(old, new), "_lg_mutant_copy", monkeypatch)
    valid, generation = _what_stays_valid_when_a_swap_waits_behind_one_that_changed_the_disk(lg)
    assert valid != frozenset({generation}) and generation - 1 in valid, (sorted(valid), generation)
