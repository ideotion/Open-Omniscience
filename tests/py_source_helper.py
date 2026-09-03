"""Resolve a CALL to a NAME in Python source, the way the interpreter would.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A guard that finds a call is not a guard that resolves the name. ``foo()`` can
appear in a scope where nothing binds ``foo``, and the guard passes while the
call raises ``NameError`` the moment its path is taken -- which is exactly what
shipped once here: PR-10's first cut asserted that ``invalidate_header_cache()``
appeared as an ``ast.Call`` and missed that the enclosing function had no import
for it. Only ruff's F821 caught that.

:func:`assert_calls_resolve` does what the guard should have done: for every call
to ``name``, walk the scopes the interpreter would search -- the call's own
function, each enclosing function, and the module -- and require one of them to
bind it. A class body counts only when the call sits DIRECTLY in it, because
class-level names are not visible to functions nested inside.

Extracted from tests/test_poll_storm.py rather than copied into a second file:
two implementations of one check is how one of them is strengthened and the other
quietly is not (the shape of the very defect S3.2 fixed in src/api/library.py).
"""

from __future__ import annotations

import ast
import pathlib


def binds_here(scope: ast.AST, name: str) -> bool:
    """Is ``name`` bound in THIS scope's own body -- an import, an assignment, a
    ``def``, a parameter, a ``global`` -- without descending into nested scopes,
    which have their own?"""
    args = getattr(scope, "args", None)
    if args is not None:
        for a in (
            list(args.posonlyargs)
            + list(args.args)
            + list(args.kwonlyargs)
            + [args.vararg, args.kwarg]
        ):
            if a is not None and a.arg == name:
                return True

    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
            continue  # a different scope
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[0]) == name:
                    return True
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id == name:
                return True
        elif isinstance(node, ast.Global) and name in node.names:
            return True
        stack.extend(ast.iter_child_nodes(node))
    return False


def visible_scopes(tree: ast.Module, call: ast.AST) -> list[ast.AST]:
    """The scopes ``call`` can see a name from, innermost first."""
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    scopes: list[ast.AST] = []
    node: ast.AST | None = parent.get(call)
    first = True
    while node is not None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            scopes.append(node)
        elif isinstance(node, ast.ClassDef):
            if first:
                scopes.append(node)
        elif isinstance(node, ast.Module):
            scopes.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            first = False
        node = parent.get(node)
    return scopes


def call_sites(tree: ast.Module, name: str) -> list[ast.Call]:
    """Every ``name(...)`` call in ``tree`` (bare name calls, not attributes)."""
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
    ]


def assert_calls_resolve(path: str | pathlib.Path, name: str, *, at_least: int = 1) -> list[int]:
    """Assert ``name`` is CALLED in ``path`` and that every call can resolve it.

    Returns the line numbers of the calls, so a caller can assert more about
    where they are. ``at_least`` guards the vacuous direction: a file with no
    calls at all would otherwise satisfy "every call resolves" for free.
    """
    p = pathlib.Path(path)
    tree = ast.parse(p.read_text(encoding="utf-8"))
    sites = call_sites(tree, name)
    assert len(sites) >= at_least, (
        f"{p}: expected at least {at_least} call(s) to {name}(), found {len(sites)}"
    )
    for call in sites:
        scopes = visible_scopes(tree, call)
        assert any(binds_here(s, name) for s in scopes), (
            f"{p}:{call.lineno} calls {name}() but no enclosing scope binds that "
            f"name -- the call raises NameError when the path is taken"
        )
    return [c.lineno for c in sites]
