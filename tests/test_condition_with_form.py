"""A ``threading.Condition`` is never entered with ``with``: take the plain lock under it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``Condition.__enter__`` and ``__exit__`` are Python frames, and CPython delivers a signal at the start of a Python frame and after a call
returns. A KeyboardInterrupt landing after the inner lock is taken but before ``__enter__`` returns, or at the start of ``__exit__`` before it
releases, leaves the lock taken for ever; every other thread then blocks on it until the process restarts. Measured with real SIGALRM
interrupts on CPython 3.13 (``/mnt/project-files/fix-source-qualification/probes/sigprobe4.py``): ``with condition:`` left the lock held in 15,174
of 43,142 interrupts in a tight loop; ``with raw_rlock:`` (a C lock's ``__enter__``/``__exit__`` run inside one bytecode) left 0 of 40,151, and
the same with ``notify_all`` in the body 0 of 46,483 (ruling R144). The pattern is ``self._lock = threading.RLock()`` and
``self._cond = threading.Condition(self._lock)``, then ``with self._lock:`` with ``wait`` / ``notify`` on the Condition.

This reads ``src`` and FAILS on a ``with`` whose context is a name assigned from ``Condition(...)``. Two modules still use the form and are pinned
by their count of sites, so a NEW site there fails too and a conversion makes the count drop to zero (the test then asks for the entry to go).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"

#: Modules that still enter a Condition with ``with``, each with its number of sites and why it is not converted yet.
_STILL_WITH_CONDITION: dict[str, tuple[int, str]] = {
    "database/writer.py": (9, "the single-writer gate: R144 converted the settings hold and three small gates; this one is on the hot path of every write and goes in its own PR"),
    "monitoring/storage_events.py": (2, "the storage-event journal's wait for a change; the same sweep as the writer gate"),
}


def _is_condition(func: ast.expr) -> bool:
    return (isinstance(func, ast.Attribute) and func.attr == "Condition") or (isinstance(func, ast.Name) and func.id == "Condition")


def _condition_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call) and _is_condition(node.value.func):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                names.add(ast.unparse(target))
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


def test_no_module_enters_a_condition_with_with_except_the_two_pinned_ones():
    seen: dict[str, int] = {}
    for path in sorted(_SRC.rglob("*.py")):
        sites = _with_sites(path.read_text(encoding="utf-8"))
        if sites:
            seen[path.relative_to(_SRC).as_posix()] = len(sites)
    expected = {name: count for name, (count, _) in _STILL_WITH_CONDITION.items()}
    assert seen == expected, (
        "a `with <Condition>` form is back (or one of the pinned modules changed its count). Take the plain lock instead: "
        "`self._lock = threading.RLock()`, `self._cond = threading.Condition(self._lock)`, `with self._lock:`. "
        f"found {seen}, pinned {expected}"
    )
    assert all(why.strip() for _, why in _STILL_WITH_CONDITION.values())


@pytest.mark.parametrize(
    "path",
    ["config/kv_store.py", "database/pool_reserve.py", "database/library_generation.py", "scheduler/bandwidth.py"],
)
def test_the_converted_modules_build_the_condition_on_a_plain_lock_and_enter_the_lock(path):
    """Non-vacuity: each converted module still has a Condition, built on an explicit RLock, and enters the lock itself."""
    source = (_SRC / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert _condition_names(tree), f"{path} no longer builds a Condition: this pin has nothing to read"
    assert "threading.RLock()" in source
    built_on_a_lock = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _is_condition(n.func) and len(n.args) == 1
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
    ],
)
def test_the_reader_leaves_the_plain_lock_form_alone(snippet):
    assert _with_sites(snippet) == [], snippet
