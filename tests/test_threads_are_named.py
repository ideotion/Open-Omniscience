"""Every thread ``src/`` starts carries a name (audit 0.5.0, the standing lesson "an unnamed thread is a ``Thread-N`` nobody can attribute").

An anonymous thread cannot be matched by the GET side-effect walk's allowances (``tests/test_get_routes_side_effects.py``), is filed under
``(other)`` by ``src/database/open_stats.py:thread_family`` and reads as ``Thread-7`` in a diagnostics thread list. Finding F4 (the rollup
canary's interrupt timer, fixed in #1556) and the boot sequence's slow-step watchdog (#1573) were both found one at a time; this scan makes the
inventory permanent. A ``threading.Thread(...)`` / ``threading.Timer(...)`` (or the bare ``Thread`` / ``Timer`` imported from it) in ``src/`` is
named when it passes ``name=<something that is not None>``, OR when it is bound to a variable and the SAME function later assigns that
variable's ``.name`` (the shape ``columnar.serve_canary`` uses, because ``threading.Timer`` has no ``name`` argument). The second form is
read from the code, not listed: delete that assignment and the scan fails.

Stated limits: a thread made by a class that subclasses ``threading.Thread`` is not seen (``src/`` has none today, and the first one fails the
last test here), a pool's workers are named by the pool (``ThreadPoolExecutor-N`` is a family ``thread_family`` already knows, and the three
pools in ``src/`` pass no ``thread_name_prefix``), and a thread socketserver starts per request is not constructed in ``src/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_KINDS = frozenset({"Thread", "Timer"})


def _is_thread_call(node: ast.Call) -> bool:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id in _KINDS
    return isinstance(fn, ast.Attribute) and fn.attr in _KINDS and isinstance(fn.value, ast.Name) and fn.value.id == "threading"


def _has_name_argument(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg == "name":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    return False


def _unnamed_threads(source: str, filename: str) -> list[str]:
    """``file:line kind`` for every Thread / Timer constructor that is neither given a name nor bound to a variable whose ``.name`` is assigned."""
    tree = ast.parse(source)
    found: list[str] = []

    def scan_scope(scope: ast.AST) -> None:
        # the variables whose .name this scope assigns, and the constructors bound to a variable
        named_vars: set[str] = set()
        bound: dict[int, str] = {}
        nodes = list(_walk_scope(scope))
        for n in nodes:
            if isinstance(n, ast.Assign):
                for target in n.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "name" and isinstance(target.value, ast.Name):
                        named_vars.add(target.value.id)
                if isinstance(n.value, ast.Call) and _is_thread_call(n.value):
                    for target in n.targets:
                        if isinstance(target, ast.Name):
                            bound[id(n.value)] = target.id
        for n in nodes:
            if isinstance(n, ast.Call) and _is_thread_call(n) and not _has_name_argument(n) and bound.get(id(n)) not in named_vars:
                kind = n.func.id if isinstance(n.func, ast.Name) else n.func.attr
                found.append(f"{filename}:{n.lineno} {kind}")

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Module):
            scan_scope(node)
    return sorted(set(found))


def _walk_scope(scope: ast.AST):
    """The nodes of one function (or the module body) without descending into a nested function, which is its own scope."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
            stack.extend(ast.iter_child_nodes(n))


def _scan_src() -> list[str]:
    out: list[str] = []
    for f in sorted((_ROOT / "src").rglob("*.py")):
        rel = f.relative_to(_ROOT)
        if "static" in rel.parts:
            continue
        out += _unnamed_threads(f.read_text(encoding="utf-8"), rel.as_posix())
    return out


def _constructors_in_src() -> int:
    total = 0
    for f in sorted((_ROOT / "src").rglob("*.py")):
        if "static" in f.relative_to(_ROOT).parts:
            continue
        total += sum(1 for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))) if isinstance(n, ast.Call) and _is_thread_call(n))
    return total


def test_every_thread_src_starts_carries_a_name():
    unnamed = _scan_src()
    assert not unnamed, (
        "a thread with no name is a Thread-N nobody can attribute (the GET walk, open_stats.thread_family and diagnostics all read names). "
        "Pass name='oo-<purpose>' (threading.Timer has no name argument: assign timer.name before start()). " + str(unnamed)
    )


def test_the_scan_sees_the_constructors_and_both_naming_shapes():
    """Liveness, so a green scan is not a blind one."""
    assert _constructors_in_src() >= 40, "the scan stopped finding Thread / Timer constructors in src/"
    kwarg = "import threading\ndef f():\n    threading.Thread(target=g, name='oo-x').start()\n"
    assigned = "import threading\ndef f():\n    t = threading.Timer(1, g)\n    t.name = 'oo-x'\n    t.start()\n"
    assert _unnamed_threads(kwarg, "a.py") == [] and _unnamed_threads(assigned, "a.py") == []
    bare = "import threading\ndef f():\n    threading.Thread(target=g, daemon=True).start()\n"
    timer = "from threading import Timer\ndef f():\n    Timer(1, g).start()\n"
    none_name = "import threading\ndef f():\n    threading.Thread(target=g, name=None).start()\n"
    assert _unnamed_threads(bare, "b.py") == ["b.py:3 Thread"]
    assert _unnamed_threads(timer, "c.py") == ["c.py:3 Timer"]
    assert _unnamed_threads(none_name, "d.py") == ["d.py:3 Thread"]
    # a name assigned in ANOTHER function, or to a different variable, does not name this thread
    other_fn = "import threading\ndef f():\n    t = threading.Timer(1, g)\n    t.start()\ndef h(t):\n    t.name = 'x'\n"
    other_var = "import threading\ndef f():\n    t = threading.Timer(1, g)\n    u = object()\n    u.name = 'x'\n    t.start()\n"
    assert _unnamed_threads(other_fn, "e.py") == ["e.py:3 Timer"] and _unnamed_threads(other_var, "f.py") == ["f.py:3 Timer"]


def test_the_canary_timer_is_compliant_by_its_assignment_not_by_a_list():
    """``columnar.serve_canary`` names its Timer by ``timer.name = ...`` after construction: the scan must read that, and must fail without it."""
    path = _ROOT / "src" / "analytics" / "columnar.py"
    source = path.read_text(encoding="utf-8")
    assert _unnamed_threads(source, "columnar.py") == []
    assert 'timer.name = "rollup-canary-timer"' in source
    stripped = source.replace('timer.name = "rollup-canary-timer"', "pass")
    assert any(" Timer" in line for line in _unnamed_threads(stripped, "columnar.py")), "removing the assignment must make the scan fail"


def test_no_class_subclasses_thread():
    """A subclass's threads are invisible to the constructor scan; the first one must be read and either named or taught to the scan."""
    subclasses = []
    for f in sorted((_ROOT / "src").rglob("*.py")):
        if "static" in f.relative_to(_ROOT).parts:
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ClassDef):
                for base in n.bases:
                    if (isinstance(base, ast.Attribute) and base.attr == "Thread") or (isinstance(base, ast.Name) and base.id == "Thread"):
                        subclasses.append(f"{f.relative_to(_ROOT).as_posix()}:{n.lineno} {n.name}")
    assert not subclasses, subclasses
