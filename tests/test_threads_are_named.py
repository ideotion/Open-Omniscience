"""Every thread ``src/`` starts carries a name (audit 0.5.0, the standing lesson "an unnamed thread is a ``Thread-N`` nobody can attribute").

An anonymous thread cannot be matched by the GET side-effect walk's allowances (``tests/test_get_routes_side_effects.py``), is filed under
``(other)`` by ``src/database/open_stats.py:thread_family`` and reads as ``Thread-7`` in a diagnostics thread list. Finding F4 (the rollup
canary's interrupt timer, fixed in #1556) and the boot sequence's slow-step watchdog (#1573) were both found one at a time; this scan makes the
inventory permanent. A ``threading.Thread(...)`` / ``threading.Timer(...)`` (or the bare ``Thread`` / ``Timer`` imported from it) in ``src/`` is
named when it passes ``name=<something that is not None>``, OR when it is bound to a variable and the SAME function later assigns that
variable's ``.name`` (the shape ``columnar.serve_canary`` uses, because ``threading.Timer`` has no ``name`` argument). The second form is
read from the code, not listed: delete that assignment and the scan fails.

The constructor is recognised through the module's own imports (``import threading``, ``import threading as _threading``,
``from threading import Thread as T``), so an alias is followed and a ``Timer`` from another module is not mistaken for one. A ``.name``
assignment counts only AFTER the constructor in the same function, and ``name=""`` counts as unnamed (it becomes ``Thread-N``). Shapes the scan
reads as unnamed although they are named (``self._t = Thread(...)`` then ``self._t.name = ...``, a tuple target, ``setName``, a positional
name) fail safe: red, to be rewritten into one of the two shapes above.

Stated limits (listed, not hidden): a thread made by a class that subclasses ``threading.Thread`` or ``Timer`` is not seen (``src/`` has none
today, and the first one fails ``test_no_class_subclasses_thread``); indirection (``functools.partial``) is unseen; the per-request threads
of the ``ThreadingHTTPServer`` that ``src/safety/data_volume.py`` serves on the pre-boot drive page are ``Thread-N (process_request_thread)`` and
``ProcessPoolExecutor``'s manager thread (``src/analytics/reindex_parallel.py``) is a ``Thread-N``, both started by the standard library; a
pool's workers are named by the pool and ``test_the_unprefixed_pools_are_exactly_the_listed_ones`` lists the two pools that pass no
``thread_name_prefix``. ``asyncio.to_thread``, ``run_in_executor``, ``ThreadPool`` and ``_thread.start_new_thread`` do not appear in ``src/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_KINDS = frozenset({"Thread", "Timer"})


def _threading_aliases(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    """(names bound to the ``threading`` module, local name -> ``Thread`` / ``Timer`` for ``from threading import ...``)."""
    modules: set[str] = set()
    members: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for alias in n.names:
                if alias.name == "threading":
                    modules.add(alias.asname or "threading")
        elif isinstance(n, ast.ImportFrom) and n.module == "threading":
            for alias in n.names:
                if alias.name in _KINDS:
                    members[alias.asname or alias.name] = alias.name
    return modules, members


def _thread_kind(node: ast.Call, modules: set[str], members: dict[str, str]) -> str | None:
    """``Thread`` / ``Timer`` when the call constructs one through this module's own ``threading`` imports, else None."""
    fn = node.func
    if isinstance(fn, ast.Name):
        return members.get(fn.id)
    if isinstance(fn, ast.Attribute) and fn.attr in _KINDS and isinstance(fn.value, ast.Name) and fn.value.id in modules:
        return fn.attr
    return None


def _has_name_argument(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg == "name":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value in (None, ""))
    return False


def _unnamed_threads(source: str, filename: str) -> list[str]:
    """``file:line kind`` for every Thread / Timer constructor that is neither given a name nor bound to a variable whose ``.name`` the same
    function assigns on a LATER line."""
    tree = ast.parse(source)
    modules, members = _threading_aliases(tree)
    found: list[str] = []

    def scan_scope(scope: ast.AST) -> None:
        name_lines: dict[str, list[int]] = {}  # variable -> lines at which this scope assigns its .name
        bound: dict[int, str] = {}  # id(constructor call) -> the variable it is bound to
        nodes = list(_walk_scope(scope))
        for n in nodes:
            if isinstance(n, ast.Assign | ast.AnnAssign):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for target in targets:
                    if isinstance(target, ast.Attribute) and target.attr == "name" and isinstance(target.value, ast.Name):
                        name_lines.setdefault(target.value.id, []).append(n.lineno)
                value = n.value
                if isinstance(value, ast.Call) and _thread_kind(value, modules, members):
                    for target in targets:
                        if isinstance(target, ast.Name):
                            bound[id(value)] = target.id
        for n in nodes:
            if not isinstance(n, ast.Call):
                continue
            kind = _thread_kind(n, modules, members)
            if kind is None or _has_name_argument(n):
                continue
            var = bound.get(id(n))
            if var is not None and any(line > n.lineno for line in name_lines.get(var, [])):
                continue
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
        tree = ast.parse(f.read_text(encoding="utf-8"))
        modules, members = _threading_aliases(tree)
        total += sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call) and _thread_kind(n, modules, members))
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
    aliased = "import threading as _t\ndef f():\n    _t.Thread(target=g).start()\n"
    from_alias = "from threading import Thread as T\ndef f():\n    T(target=g).start()\n"
    foreign = "from timeit import Timer\ndef f():\n    Timer('x').timeit()\n"
    assert _unnamed_threads(aliased, "g.py") == ["g.py:3 Thread"] and _unnamed_threads(from_alias, "h.py") == ["h.py:3 Thread"]
    assert _unnamed_threads(foreign, "i.py") == []  # not threading's Timer
    # a name assigned BEFORE the constructor, or an empty name, does not name this thread
    before = "import threading\ndef f(t):\n    t.name = 'x'\n    t = threading.Timer(1, g)\n    t.start()\n"
    empty = "import threading\ndef f():\n    threading.Thread(target=g, name='').start()\n"
    assert _unnamed_threads(before, "j.py") == ["j.py:4 Timer"] and _unnamed_threads(empty, "k.py") == ["k.py:3 Thread"]
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
    line = next(i for i, text in enumerate(source.splitlines(), 1) if "threading.Timer(" in text)
    assert _unnamed_threads(stripped, "columnar.py") == [f"columnar.py:{line} Timer"], "removing the assignment must make the scan fail on the Timer"


def test_no_class_subclasses_thread():
    """A subclass's threads are invisible to the constructor scan; the first one must be read and either named or taught to the scan."""
    subclasses = []
    for f in sorted((_ROOT / "src").rglob("*.py")):
        if "static" in f.relative_to(_ROOT).parts:
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ClassDef):
                for base in n.bases:
                    if (isinstance(base, ast.Attribute) and base.attr in _KINDS) or (isinstance(base, ast.Name) and base.id in _KINDS):
                        subclasses.append(f"{f.relative_to(_ROOT).as_posix()}:{n.lineno} {n.name}")
    assert not subclasses, subclasses


# The pools whose workers read as ThreadPoolExecutor-N: a family open_stats.thread_family knows, so not anonymous, but nameless as to purpose.
# Their owners may add thread_name_prefix="oo-<purpose>" and delete the line here; a new unprefixed pool fails until it is read.
_UNPREFIXED_POOLS = {"src/ingest/segmented_download.py", "src/llm/concurrency.py"}


def test_the_unprefixed_pools_are_exactly_the_listed_ones():
    found: set[str] = set()
    for f in sorted((_ROOT / "src").rglob("*.py")):
        rel = f.relative_to(_ROOT)
        if "static" in rel.parts:
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call) or "ThreadPoolExecutor" not in (getattr(n.func, "id", None), getattr(n.func, "attr", None)):
                continue
            if not any(k.arg == "thread_name_prefix" for k in n.keywords):
                found.add(rel.as_posix())
    assert found == _UNPREFIXED_POOLS, (sorted(found - _UNPREFIXED_POOLS), sorted(_UNPREFIXED_POOLS - found))
