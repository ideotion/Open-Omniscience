"""A ``threading.Condition`` is never entered with ``with``: take the plain lock under it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``Condition.__enter__`` and ``__exit__`` are Python frames, and CPython delivers a signal at the start of a Python frame and after a call
returns. A KeyboardInterrupt landing after the inner lock is taken but before ``__enter__`` returns, or at the start of ``__exit__`` before it
releases, leaves the lock taken for ever; every other thread then blocks on it until the process restarts. Measured with real SIGALRM
interrupts on CPython 3.13 (``scripts/signal_leak_probe.py``): ``with condition:`` left the lock held in 15,174
of 43,142 interrupts in a tight loop; ``with raw_rlock:`` (a C lock's ``__enter__``/``__exit__`` run inside one bytecode) left 0 of 40,151, and
the same with ``notify_all`` in the body 0 of 46,483 (ruling R144). The pattern is ``self._lock = threading.RLock()`` and
``self._cond = threading.Condition(self._lock)``, then ``with self._lock:`` with ``wait`` / ``notify`` on the Condition.

THE GUARANTEE IS CPYTHON 3.13'S: there ``with x:`` compiles to ``BEFORE_WITH`` and the protected range starts right after it. On 3.14 it
compiles to ``LOAD_SPECIAL __enter__; CALL``, the signal check at the end of the call runs before the protected range, and the same probes left a
raw RLock held in about 80 % of interrupts (and ``with condition:`` in about 30 %), so nothing in this file's fix survives a Python bump unmeasured:
``test_the_with_statement_still_compiles_to_before_with`` fails on a Python that does not, and the next step is to re-run the probes before accepting it.

This reads ``src`` and FAILS on a ``with`` whose context is a name assigned from ``threading.Condition(...)`` (not ``asyncio.Condition``, which is a
different primitive). One module still uses the form (held behind the run-records PR) and is pinned by its count of sites, so a NEW site there fails, and a conversion makes
the failure say the entry should go.

NOT READ (none occurs in ``src`` today; each would need a person to see it): a Condition kept in a dict or list (``with self._conds[k]:``), made by a
factory (``_c = make()``), a subclass of ``threading.Condition``, entered by hand (``_c.__enter__()``) or through ``ExitStack.enter_context``,
reached as ``with other._cond:`` through another object or ``with getattr(self, "_cond"):``, and a name held by a second class that reuses the
spelling of a Condition's name (flagged: names are matched module-wide). Tests are not scanned.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"

#: Modules that still enter a Condition with ``with``, each with its number of sites and why it is not converted yet.
_STILL_WITH_CONDITION: dict[str, tuple[int, str]] = {
    "monitoring/storage_events.py": (2, "the storage-event journal's wait for a change; held behind the run-records PR (#1421), which edits the same lines"),
}


def _threading_spellings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """``(names bound to the threading module, names bound to threading.Condition)`` by this module's imports."""
    modules: set[str] = set()
    conditions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.asname or a.name for a in node.names if a.name == "threading"}
        elif isinstance(node, ast.ImportFrom) and node.module == "threading":
            conditions |= {a.asname or a.name for a in node.names if a.name == "Condition"}
    return modules, conditions


def _is_condition(func: ast.expr, spellings: tuple[set[str], set[str]]) -> bool:
    modules, conditions = spellings
    return (isinstance(func, ast.Attribute) and func.attr == "Condition" and isinstance(func.value, ast.Name) and func.value.id in modules) or (
        isinstance(func, ast.Name) and func.id in conditions
    )


def _condition_names(tree: ast.AST) -> set[str]:
    spellings = _threading_spellings(tree)
    names: set[str] = set()

    def is_one(value: ast.AST | None) -> bool:
        return isinstance(value, ast.Call) and _is_condition(value.func, spellings)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple) and len(target.elts) == len(node.value.elts):
                    names |= {ast.unparse(t) for t, v in zip(target.elts, node.value.elts, strict=True) if is_one(v)}  # `a, b = Condition(), 1`
                elif is_one(node.value):
                    names.add(ast.unparse(target))
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and is_one(node.value):
            names.add(ast.unparse(node.target))
    return names


def _with_sites(source: str) -> list[int]:
    """Line numbers of the ``with`` statements whose context is a name this module assigned from ``Condition(...)``."""
    tree = ast.parse(source)
    names = _condition_names(tree)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.With, ast.AsyncWith)) and any(ast.unparse(item.context_expr) in names for item in node.items)
    )


def _differences(seen: dict[str, int], expected: dict[str, int]) -> list[str]:
    """What is wrong between the sites found and the sites pinned, each in words that say what to do."""
    lines = [f"{name}: a `with <Condition>` form is back ({n} site(s)); take the plain lock instead" for name, n in seen.items() if name not in expected]
    for name, count in expected.items():
        if seen.get(name, 0) < count:
            lines.append(f"{name}: pinned at {count} site(s), now {seen.get(name, 0)}: converted, so lower the count (or drop the entry at 0)")
        elif seen[name] > count:
            lines.append(f"{name}: pinned at {count} site(s), now {seen[name]}: a NEW `with <Condition>` form; take the plain lock instead")
    return lines


def test_no_module_enters_a_condition_with_with_except_the_pinned_ones():
    seen: dict[str, int] = {}
    for path in sorted(_SRC.rglob("*.py")):
        sites = _with_sites(path.read_text(encoding="utf-8"))
        if sites:
            seen[path.relative_to(_SRC).as_posix()] = len(sites)
    lines = _differences(seen, {name: count for name, (count, _) in _STILL_WITH_CONDITION.items()})
    assert not lines, (
        "\n".join(lines) + "\nThe pattern: `self._lock = threading.RLock()`, `self._cond = threading.Condition(self._lock)`, `with self._lock:`."
    )
    assert all(why.strip() for _, why in _STILL_WITH_CONDITION.values())


def test_the_with_statement_still_compiles_to_before_with():
    """The whole fix rests on this (see the module docstring): measured on CPython 3.13, where the protected range of a ``with`` starts
    right after ``BEFORE_WITH``. On a Python that compiles it otherwise (3.14: ``LOAD_SPECIAL`` then ``CALL``), re-run
    ``scripts/signal_leak_probe.py`` (``raw`` must leave 0 held) before accepting the bump."""
    import dis

    def f(lock):
        with lock:
            pass

    assert "BEFORE_WITH" in {i.opname for i in dis.get_instructions(f)}, (
        "this Python compiles `with lock:` without BEFORE_WITH: the raw-lock guarantee of R144 was measured only where it does"
    )


@pytest.mark.parametrize(
    "path",
    ["config/kv_store.py", "database/pool_reserve.py", "database/library_generation.py", "scheduler/bandwidth.py", "database/writer.py"],
)
def test_the_converted_modules_build_the_condition_on_a_plain_lock_and_enter_the_lock(path):
    """Non-vacuity: each converted module still has a Condition, built on an explicit RLock, and enters the lock itself."""
    source = (_SRC / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert _condition_names(tree), f"{path} no longer builds a Condition: this pin has nothing to read"
    assert "threading.RLock()" in source
    spellings = _threading_spellings(tree)
    built_on_a_lock = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _is_condition(n.func, spellings) and len(n.args) == 1
    ]
    assert built_on_a_lock, f"{path}: the Condition is not built on an explicit lock"
    entered = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.With) and any(ast.unparse(i.context_expr) in {"self._lock", "_hold_lock"} for i in n.items)
    ]
    assert len(entered) >= 4, f"{path}: the plain lock is entered {len(entered)} times"
    assert _with_sites(source) == []


@pytest.mark.parametrize(
    "snippet",
    [
        "import threading\nclass A:\n    def __init__(self):\n        self._cond = threading.Condition()\n    def f(self):\n        with self._cond:\n            pass",
        "import threading\n_c = threading.Condition()\ndef f():\n    with _c:\n        pass",
        "from threading import Condition\n_c = Condition()\ndef f():\n    with _c:\n        pass",
        "import threading as t\n_c = t.Condition(t.RLock())\ndef f():\n    with _c:\n        pass",
        "import threading\ndef f(lock):\n    cv = threading.Condition(lock)\n    with cv:\n        pass",
        "import threading\n_c = threading.Condition()\ndef f(other):\n    with other, _c:\n        pass",
        "import threading\n_c: threading.Condition = threading.Condition()\ndef f():\n    with _c:\n        pass",
        "import threading\n_c = threading.Condition()\nasync def f():\n    async with _c:\n        pass",
        "from threading import Condition as Cond\n_c = Cond()\ndef f():\n    with _c:\n        pass",
        "import threading\na, _c = 1, threading.Condition()\ndef f():\n    with _c:\n        pass",
        "import threading\ndef f():\n    if (cv := threading.Condition()):\n        with cv:\n            pass",
        "import threading\n_c = threading.Condition()\ndef f():\n    with (_c):\n        pass",
        "import threading\n_c = threading.Condition()\ndef f():\n    with _c as held:\n        pass",
    ],
)
def test_the_reader_finds_every_spelling_of_with_on_a_condition(snippet):
    assert _with_sites(snippet), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        "import threading\nclass A:\n    def __init__(self):\n        self._lock = threading.RLock()\n        self._cond = threading.Condition(self._lock)\n    def f(self):\n        with self._lock:\n            self._cond.wait(1)",
        "import threading\n_c = threading.Condition()\ndef f():\n    _c.acquire()\n    _c.release()",
        "import threading\ndef f(lock):\n    with lock:\n        pass",
        "import threading\n_c = threading.Condition()\ndef g(x):\n    with x:\n        _c.notify_all()",
        # asyncio.Condition is a different primitive (an async context manager with no signal hazard of this kind)
        "import asyncio\n_c = asyncio.Condition()\nasync def f():\n    async with _c:\n        pass",
        "from asyncio import Condition\n_c = Condition()\nasync def f():\n    async with _c:\n        pass",
    ],
)
def test_the_reader_leaves_the_plain_lock_form_alone(snippet):
    assert _with_sites(snippet) == [], snippet


@pytest.mark.parametrize(
    ("seen", "expected", "words"),
    [
        ({"a.py": 2}, {}, ["a.py", "is back"]),
        ({"a.py": 1}, {"a.py": 3}, ["converted", "lower the count"]),
        ({}, {"a.py": 3}, ["converted", "drop the entry at 0"]),
        ({"a.py": 4}, {"a.py": 3}, ["NEW"]),
    ],
)
def test_the_difference_says_what_to_do(seen, expected, words):
    text = "\n".join(_differences(seen, expected))
    assert all(w in text for w in words), text


def test_no_difference_when_the_sites_are_the_pinned_ones():
    assert _differences({"a.py": 3}, {"a.py": 3}) == []
