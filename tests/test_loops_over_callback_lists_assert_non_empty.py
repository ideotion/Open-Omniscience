"""A test that asserts over a list only a callback fills must first assert the list is not empty (parent sweep R385, after R376 and #1615).

``test_the_tick_reports_elapsed_seconds_and_never_a_fraction`` read ``seen: list = []``, handed ``lambda *a: seen.append(a)`` to the code under
test, and then ``for call in seen: assert ...``. The code reports once per ``_STEP_WATCH_INTERVAL_S`` (2 s) and the statement took milliseconds, so
the callback never ran, ``seen`` stayed ``[]``, and every assertion in the loop passed over nothing. A mutant that changed what the tick sends
would have survived. A loop over an empty list is green whatever the code does, so a list that only a callback fills proves nothing until the
test says it is not empty.

This guard reads the AST of every file under tests/ and fails on exactly that shape: a collection created empty in the test, mutated ONLY inside
a nested ``def`` or ``lambda`` (the callback), iterated by a ``for`` whose body asserts, with no assertion elsewhere in the test that mentions
the collection as a whole (``assert seen``, ``assert len(seen) == 3``, ``assert seen == [...]``, ``assert x in seen``). A mention that only
iterates it inside a generator (``assert all(... for c in seen)``) is as empty-proof as the loop and does not count. A collection the test fills
itself (a ``for`` that appends, a ``+=`` at the test's own level) is not this shape and is not flagged.

A bound method handed over as the callback (``run(seen.append)``) counts as a callback fill. Stated limits, none of which has an instance in
tests/ today (checked): a test that is itself ``async def``; iteration through a slice or an attribute (``seen[1:]``, ``self.calls``); a
container created by tuple unpacking (``a, b = [], []``) or held in a dict; a whole-mention that proves nothing about size
(``assert seen is not None``) clears the guard; a collection handed to a helper that asserts over it is flagged (the strict side).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_MUTATORS = {"append", "extend", "insert", "add", "update", "setdefault", "appendleft", "put", "put_nowait"}
_VIEWS = {"items", "values", "keys"}
_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _own_nodes(fn: ast.FunctionDef):
    """Every node of the test that is not inside a nested def or lambda (the test's own statements)."""
    stack: list[ast.AST] = list(fn.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _NESTED + (ast.ClassDef,)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _callback_nodes(fn: ast.FunctionDef):
    """Every node inside a nested def or lambda of the test, at any depth."""
    for node in _own_nodes(fn):
        if isinstance(node, _NESTED):
            yield from ast.walk(node)


def _is_empty_collection(value: ast.AST | None) -> bool:
    if isinstance(value, ast.List):
        return not value.elts
    if isinstance(value, ast.Dict):
        return not value.keys
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {"list", "dict", "set", "deque"}:
        return not value.args and not value.keywords
    return False


def _target(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and _is_empty_collection(node.value):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and _is_empty_collection(node.value):
        return node.target.id
    return None


def _mutates(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _MUTATORS:
        return isinstance(node.func.value, ast.Name) and node.func.value.id == name
    if isinstance(node, ast.AugAssign):
        return isinstance(node.target, ast.Name) and node.target.id == name
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == name for t in targets)
    return False


def _bound_mutator_names(nodes: list[ast.AST]) -> set[str]:
    """Names whose mutator is mentioned at the test's own level (``run(seen.append)``): the callback IS the method.

    A direct call (``seen.append(1)``) is also a mention; the caller treats that as the test filling it itself, which wins."""
    return {n.value.id for n in nodes if isinstance(n, ast.Attribute) and n.attr in _MUTATORS and isinstance(n.value, ast.Name)}


def _iterated_name(loop: ast.For) -> str | None:
    it = loop.iter
    if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id in {"enumerate", "sorted", "reversed", "list", "tuple"} and it.args:
        it = it.args[0]  # for i, x in enumerate(seen)
    if isinstance(it, ast.Name):
        return it.id
    if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and it.func.attr in _VIEWS and isinstance(it.func.value, ast.Name):
        return it.func.value.id
    return None


def _mentioned_as_a_whole(test: ast.AST, name: str) -> bool:
    """``name`` appears in an assertion other than as the thing a comprehension walks (which is empty-proof)."""
    walked = {id(g.iter) for g in ast.walk(test) if isinstance(g, ast.comprehension)}
    for node in ast.walk(test):
        if isinstance(node, ast.Name) and node.id == name and id(node) not in walked:
            return True
    return False


def empty_proof_loops(source: str) -> list[tuple[int, str]]:
    """``(line of the for, collection name)`` for each loop that asserts over a callback-filled collection nothing says is non-empty."""
    found: list[tuple[int, str]] = []
    for fn in ast.walk(ast.parse(source)):
        if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_")):
            continue
        own = list(_own_nodes(fn))
        callbacks = list(_callback_nodes(fn))
        names = {n for n in map(_target, own) if n}
        handed_over = _bound_mutator_names(own)
        for name in sorted(names):
            fills_itself = any(_mutates(n, name) for n in own)
            if fills_itself or not (name in handed_over or any(_mutates(n, name) for n in callbacks)):
                continue  # the test fills it itself, or nothing fills it: not a callback-filled collection
            for loop in (n for n in own if isinstance(n, ast.For) and _iterated_name(n) == name):
                if not any(isinstance(n, ast.Assert) for n in ast.walk(loop)):
                    continue
                inside = {id(n) for n in ast.walk(loop)}
                outside = [n for n in own if isinstance(n, ast.Assert) and id(n) not in inside]
                if not any(_mentioned_as_a_whole(a.test, name) for a in outside):
                    found.append((loop.lineno, name))
    return sorted(set(found))


def _test_files() -> list[Path]:
    return sorted(p for p in _TESTS.rglob("*.py") if p.resolve() != Path(__file__).resolve() and "__pycache__" not in p.parts)


def test_no_test_asserts_over_a_list_only_a_callback_fills_without_saying_it_is_not_empty():
    offenders = []
    for path in _test_files():
        offenders += [f"{path.relative_to(_TESTS).as_posix()}:{line} loops over {name}" for line, name in empty_proof_loops(path.read_text(encoding="utf-8"))]
    assert not offenders, (
        "each of these loops asserts over a collection that only a callback fills; if the callback is never reached the loop checks nothing. "
        f"Assert the collection is not empty before the loop (assert {{name}}, or its length): {offenders}"
    )


_FILLED_BY_A_CALLBACK = """
def test_a():
    seen = []
    run(lambda *a: seen.append(a))
    for call in seen:
        assert call
"""


@pytest.mark.parametrize(
    ("source", "found"),
    [
        # the shape: created empty, filled only by a callback, looped over with an assertion, nothing says it is not empty
        (_FILLED_BY_A_CALLBACK, [(5, "seen")]),
        ("def test_a():\n    seen: list[tuple] = []\n    def cb(*a):\n        seen.append(a)\n    run(cb)\n    for call in seen:\n        assert call\n", [(6, "seen")]),
        ("def test_a():\n    seen = list()\n    run(lambda *a: seen.extend(a))\n    for call in seen:\n        assert call\n", [(4, "seen")]),
        ("def test_a():\n    seen = {}\n    def cb(k, v):\n        seen[k] = v\n    run(cb)\n    for k, v in seen.items():\n        assert v\n", [(6, "seen")]),
        ("def test_a():\n    seen = []\n    def cb(x):\n        seen.append(x)\n    run(cb)\n    for x in seen:\n        assert x\n    for y in seen:\n        assert y\n", [(6, "seen"), (8, "seen")]),
        # the callback is the bound method itself, a deque, a wrapped iteration
        ("def test_a():\n    seen = []\n    run(seen.append)\n    for call in seen:\n        assert call\n", [(4, "seen")]),
        ("def test_a():\n    seen = deque()\n    run(lambda *a: seen.appendleft(a))\n    for call in seen:\n        assert call\n", [(4, "seen")]),
        ("def test_a():\n    seen = []\n    run(lambda *a: seen.append(a))\n    for i, call in enumerate(seen):\n        assert call\n", [(4, "seen")]),
        ("def test_a():\n    seen = []\n    run(lambda *a: seen.append(a))\n    for call in sorted(seen):\n        assert call\n", [(4, "seen")]),
        # calling the method at the test's own level is the test filling it itself, whatever else hands it over
        ("def test_a():\n    seen = []\n    seen.append(1)\n    run(seen.append)\n    for call in seen:\n        assert call\n", []),
        # a mention that only walks it inside a generator is as empty-proof as the loop
        ("def test_a():\n    seen = []\n    run(lambda *a: seen.append(a))\n    assert all(c for c in seen)\n    for call in seen:\n        assert call\n", [(5, "seen")]),
        # filled by a callback and also asserted non-empty: fine, whichever way it is said
        (_FILLED_BY_A_CALLBACK.replace("    for call", "    assert seen\n    for call"), []),
        (_FILLED_BY_A_CALLBACK.replace("    for call", "    assert len(seen) == 2\n    for call"), []),
        (_FILLED_BY_A_CALLBACK.replace("    for call", "    assert seen == [(1,)]\n    for call"), []),
        (_FILLED_BY_A_CALLBACK.replace("    for call", "    assert (1,) in seen\n    for call"), []),
        (_FILLED_BY_A_CALLBACK.replace("        assert call\n", "        assert call\n    assert seen\n"), []),
        # the test fills it itself, so it is not a callback's list
        ("def test_a():\n    seen = []\n    for i in range(3):\n        seen.append(i)\n    for x in seen:\n        assert x >= 0\n", []),
        ("def test_a():\n    seen = []\n    seen += [1]\n    run(lambda: seen.append(2))\n    for x in seen:\n        assert x\n", []),
        # nothing fills it, or the loop asserts nothing, or it is not created empty
        ("def test_a():\n    seen = []\n    for x in seen:\n        assert x\n", []),
        ("def test_a():\n    seen = []\n    run(lambda *a: seen.append(a))\n    for call in seen:\n        use(call)\n", []),
        ("def test_a():\n    seen = [1]\n    run(lambda *a: seen.append(a))\n    for call in seen:\n        assert call\n", []),
        # not a test
        ("def helper():\n    seen = []\n    run(lambda *a: seen.append(a))\n    for call in seen:\n        assert call\n", []),
        # a generator inside the loop body, or an unrelated name, is not the loop
        ("def test_a():\n    seen = []\n    other = [1]\n    run(lambda *a: seen.append(a))\n    for x in other:\n        assert x\n", []),
    ],
)
def test_the_scanner_finds_each_shape_on_its_exact_line_and_nothing_else(source, found):
    assert empty_proof_loops(source) == found


def test_the_scan_covers_every_python_file_under_tests_including_subdirectories():
    scanned = {p.relative_to(_TESTS).as_posix() for p in _test_files()}
    assert {"conftest.py", "os_scope.py"} <= scanned, scanned
    assert any("/" in name for name in scanned), "no file under a tests/ subdirectory is scanned"
    assert Path(__file__).name not in scanned
