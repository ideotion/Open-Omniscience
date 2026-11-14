"""Does a test's injected fault ever fire? The fault-reach audit (OPEN_QUEUE item 30, R412).

A test that installs a fault stub (a function that raises, a ``(_ for _ in ()).throw(exc)`` lambda, a ``Mock`` whose ``side_effect`` is an
exception) proves nothing unless the code under test reaches that stub. Three tests passed with the code mutated for exactly that reason
(fixed in #1636 and #1640). This module finds them mechanically, in two halves:

* STATIC (``analyse``): for one test file, which stubs each test installs and on which lines they raise. A stub is a ``def`` (or a
  method of a class) containing a ``raise``, or a lambda containing a ``.throw(``, that a test hands over as a VALUE (an argument, a
  keyword, a dict or list element, the right-hand side of an assignment), never one it calls itself. Names resolve by scope: a ``def``
  nested in the test first, then a module-level one, so a local name that merely collides with a module stub does not count. A stub whose
  every ``raise`` is ``AssertionError`` or ``NotImplementedError``, or that calls ``pytest.fail``, is a GUARD: the right number of calls
  is zero, and it is never reported.
* RUNTIME (the pytest plugin, ``-p tests.fault_reach``): ``sys.monitoring`` LINE events record which of those raise lines ran during
  which test. Nothing is rewritten: the old hand-run audit instrumented the test files in place, and a crash between instrument and
  restore left an instrumented file in the checkout. Every other line disables itself on its first event, so the cost is about one
  callback per line of the suite. ``Mock`` and ``AsyncMock`` with an exception ``side_effect`` are tracked by wrapping their call
  path: the site is the first test-file frame that created the mock or set the side effect.

A test is FLAGGED when it ran (its call phase executed), installed at least one non-guard device, and none of them fired in any of its
runs (parametrized cases fold onto their function). ``scripts/fault_reach_audit.py`` runs it, compares against the reviewed baseline
``tests/fault_reach_baseline.txt`` and writes the report; the weekly ``.github/workflows/fault-reach.yml`` runs that. It never gates a PR.

Stated limits: stubs installed by a FIXTURE rather than the test body are not attributed (the test does not name them); a stub reached
only from a thread that outlives its test is attributed to whichever test runs next; ``side_effect`` given as an iterable of exceptions is
not tracked.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

GUARD_EXCEPTIONS = frozenset({"AssertionError", "NotImplementedError"})
TESTS_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
#  Static half
# --------------------------------------------------------------------------- #
@dataclass
class Stub:
    """One fault device: where it raises, and with what."""

    name: str
    lines: frozenset[int]  # every line a raise (or a .throw call) of it spans
    exceptions: frozenset[str]
    calls_fail: bool = False

    @property
    def guard(self) -> bool:
        return self.calls_fail or (bool(self.exceptions) and self.exceptions <= GUARD_EXCEPTIONS)


@dataclass
class FileStubs:
    """For one test file: test qualname -> the stubs its body installs."""

    path: str
    installs: dict[str, list[Stub]] = field(default_factory=dict)

    def target_lines(self) -> set[int]:
        return {ln for stubs in self.installs.values() for s in stubs for ln in s.lines}


def _exc_name(node: ast.expr | None) -> str:
    e = node
    if isinstance(e, ast.Call):
        e = e.func
    if isinstance(e, ast.Attribute):
        return e.attr
    if isinstance(e, ast.Name):
        return e.id
    return "?"


def _own_nodes(fn: ast.AST):
    """Every node of ``fn``'s body, not descending into nested defs, lambdas or classes."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(n))


def _is_throw(n: ast.AST) -> bool:
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "throw" and isinstance(n.func.value, ast.GeneratorExp)


def _stub_of(fn: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, name: str) -> Stub | None:
    lines: set[int] = set()
    excs: set[str] = set()
    fail = False
    for n in _own_nodes(fn) if not isinstance(fn, ast.Lambda) else ast.walk(fn.body):
        if isinstance(n, ast.Raise) and n.exc is not None:
            lines.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
            excs.add(_exc_name(n.exc))
        elif _is_throw(n):
            lines.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
            excs.add(_exc_name(n.args[0]) if n.args else "?")
        elif isinstance(n, ast.Call) and _exc_name(n.func) == "fail" and isinstance(n.func, ast.Attribute):
            fail = True
            lines.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    if not lines:
        return None
    if isinstance(fn, ast.Lambda):
        lines.add(fn.lineno)  # a lambda shows up at run time as a code object starting here (no LINE event fires inside a one-line lambda)
    return Stub(name, frozenset(lines), frozenset(excs), fail)


def _value_names(fn: ast.AST) -> tuple[set[str], set[str]]:
    """Names a test body hands over as a value, and names it calls (an instance of a stub class is installed by calling the class)."""
    called_ids: set[int] = set()
    called: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            called_ids.add(id(n.func))
            called.add(n.func.id)
    values = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and id(n) not in called_ids:
            values.add(n.id)
    return values, called


def _always_raises(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return bool(body) and isinstance(body[0], ast.Raise) and body[0].exc is not None


def _scope_stubs(body: list[ast.stmt]) -> dict[str, list[Stub]]:
    """Stubs defined directly in a body: defs that raise, classes whose methods raise, names bound to a throwing lambda."""
    out: dict[str, list[Stub]] = {}
    for st in body:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            s = _stub_of(st, st.name)
            if s:
                out.setdefault(st.name, []).append(s)
        elif isinstance(st, ast.ClassDef) and not st.name.startswith("Test"):
            # a fake class is a fault device only through a method whose body IS a raise (after any docstring): a fake whose raise
            # waits on an argument, a flag the test sets or a fallback after the answers it knows is behaviour, and a test that
            # never asks for it injects nothing
            for m in st.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and _always_raises(m):
                    s = _stub_of(m, f"{st.name}.{m.name}")
                    if s:
                        out.setdefault(st.name, []).append(s)
        elif isinstance(st, ast.Assign) and isinstance(st.value, ast.Lambda):
            s = _stub_of(st.value, "lambda")
            if s:
                for t in st.targets:
                    if isinstance(t, ast.Name):
                        out.setdefault(t.id, []).append(Stub(t.id, s.lines, s.exceptions, s.calls_fail))
    return out


def _nested_scope(fn: ast.AST) -> dict[str, list[Stub]]:
    """Stubs defined anywhere inside a test function (its own defs, classes and lambda assignments, at any depth)."""
    out: dict[str, list[Stub]] = {}
    for n in ast.walk(fn):
        if n is fn:
            continue
        body = getattr(n, "body", None)
        if isinstance(body, list):
            for k, v in _scope_stubs(body).items():
                out.setdefault(k, []).extend(v)
    for k, v in _scope_stubs(fn.body).items():  # type: ignore[attr-defined]
        out.setdefault(k, []).extend(v)
    return out


def _tests(tree: ast.Module):
    for st in tree.body:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)) and st.name.startswith("test"):
            yield st.name, st
        elif isinstance(st, ast.ClassDef) and st.name.startswith("Test"):
            for m in st.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test"):
                    yield f"{st.name}::{m.name}", m


def analyse_source(source: str, path: str = "<test>") -> FileStubs:
    tree = ast.parse(source)
    module = _scope_stubs(tree.body)
    result = FileStubs(path)
    for qual, fn in _tests(tree):
        local = _nested_scope(fn)
        values, called = _value_names(fn)
        stubs: list[Stub] = []
        for name in sorted((values | called) - {fn.name}):
            found = local.get(name) or module.get(name) or []
            if name not in values:  # only called: counts for a stub class (its instance is the device), never for a function it calls itself
                found = [s for s in found if "." in s.name]
            stubs.extend(found)
        # a throwing lambda written inline as a value inside the test body
        for n in ast.walk(fn):
            if isinstance(n, ast.Lambda):
                s = _stub_of(n, f"lambda@{n.lineno}")
                if s and not any(s.lines <= x.lines for x in stubs):
                    stubs.append(s)
        if stubs:
            result.installs[qual] = stubs
    return result


def analyse(path: Path) -> FileStubs:
    return analyse_source(path.read_text(encoding="utf-8"), str(path))


# --------------------------------------------------------------------------- #
#  Runtime half: the pytest plugin
# --------------------------------------------------------------------------- #
_TOOL_NAME = "oo-fault-reach"


class _Recorder:
    def __init__(self) -> None:
        self.current: str | None = None  # the running test's nodeid
        self.targets: dict[str, set[int]] = {}  # absolute test file path -> raise lines
        self.hits: set[tuple[str, str, int]] = set()  # (nodeid, file, line)
        self.ran: set[str] = set()  # nodeids whose call phase ran and did not skip
        self.mock_sites: dict[tuple[str, str, int], set[str]] = {}  # (nodeid, file, line) -> exception names set there
        self.mock_hits: set[tuple[str, str, int]] = set()
        self.lock = threading.Lock()
        self.tool: int | None = None

    # ---- sys.monitoring ------------------------------------------------- #
    def start(self) -> None:
        mon = sys.monitoring
        for tool in (3, 4):
            if mon.get_tool(tool) is None:
                mon.use_tool_id(tool, _TOOL_NAME)
                self.tool = tool
                break
        if self.tool is None:  # pragma: no cover - two other tools hold both free ids
            raise RuntimeError("fault-reach: no free sys.monitoring tool id (3 and 4 are taken)")
        disable = mon.DISABLE

        def on_line(code, line):
            lines = self.targets.get(code.co_filename)
            if lines is None or line not in lines:
                return disable
            cur = self.current
            if cur is not None:
                self.hits.add((cur, code.co_filename, line))
            return None

        def on_start(code, offset):
            # a one-line lambda runs without a single LINE event of its own (measured on 3.13), so a throwing lambda is seen entering
            if code.co_name != "<lambda>":
                return disable
            lines = self.targets.get(code.co_filename)
            if lines is None or code.co_firstlineno not in lines:
                return disable
            cur = self.current
            if cur is not None:
                self.hits.add((cur, code.co_filename, code.co_firstlineno))
            return None

        mon.register_callback(self.tool, mon.events.LINE, on_line)
        mon.register_callback(self.tool, mon.events.PY_START, on_start)
        mon.set_events(self.tool, mon.events.LINE | mon.events.PY_START)

    def stop(self) -> None:
        if self.tool is not None:
            mon = sys.monitoring
            mon.set_events(self.tool, 0)
            mon.register_callback(self.tool, mon.events.LINE, None)
            mon.register_callback(self.tool, mon.events.PY_START, None)
            mon.free_tool_id(self.tool)
            self.tool = None

    # ---- Mock side effects ---------------------------------------------- #
    def _test_frame_site(self) -> tuple[str, int] | None:
        roots = tuple(r for r in (str(TESTS_DIR), os.environ.get("FAULT_REACH_EXTRA_ROOT")) if r)
        f = sys._getframe(2)
        while f is not None:
            fn = f.f_code.co_filename
            if fn.startswith(roots) and fn != __file__:
                return fn, f.f_lineno
            f = f.f_back
        return None

    def note_side_effect(self, mock, value) -> None:
        from unittest.mock import _is_exception  # type: ignore[attr-defined]

        if not _is_exception(value) or self.current is None:
            return
        site = self._test_frame_site()
        if site is None:
            return
        exc = value.__name__ if isinstance(value, type) else type(value).__name__
        key = (self.current, site[0], site[1])
        mock.__dict__["_oo_fault_site"] = key
        with self.lock:
            self.mock_sites.setdefault(key, set()).add(exc)

    def note_mock_raise(self, mock) -> None:
        key = mock.__dict__.get("_oo_fault_site")
        if key is not None and self.current is not None:
            self.mock_hits.add(key)

    def patch_mock(self) -> None:
        import unittest.mock as um

        rec = self
        prop = um.NonCallableMock.side_effect
        real_init = um.NonCallableMock.__init__

        def init(self, *a, **k):
            real_init(self, *a, **k)
            rec.note_side_effect(self, self.__dict__.get("_mock_side_effect"))

        def set_side_effect(self, value):
            prop.fset(self, value)
            rec.note_side_effect(self, value)

        um.NonCallableMock.__init__ = init
        um.NonCallableMock.side_effect = property(prop.fget, set_side_effect)

        def wrap_sync(real):
            def run(self, /, *a, **k):
                try:
                    return real(self, *a, **k)
                except BaseException as e:
                    if um._is_exception(self.side_effect) and (e is self.side_effect or type(e) is self.side_effect):  # type: ignore[attr-defined]
                        rec.note_mock_raise(self)
                    raise

            return run

        def wrap_async(real):
            async def run(self, /, *a, **k):
                try:
                    return await real(self, *a, **k)
                except BaseException as e:
                    if um._is_exception(self.side_effect) and (e is self.side_effect or type(e) is self.side_effect):  # type: ignore[attr-defined]
                        rec.note_mock_raise(self)
                    raise

            return run

        um.CallableMixin._execute_mock_call = wrap_sync(um.CallableMixin._execute_mock_call)
        um.AsyncMockMixin._execute_mock_call = wrap_async(um.AsyncMockMixin._execute_mock_call)

    # ---- output ----------------------------------------------------------- #
    def dump(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "hits": sorted(self.hits),
            "ran": sorted(self.ran),
            "mock_sites": [[*k, sorted(v)] for k, v in sorted(self.mock_sites.items())],
            "mock_hits": sorted(self.mock_hits),
        }
        name = f"reach-{os.getpid()}.json"
        tmp = out_dir / (name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, out_dir / name)


_REC: _Recorder | None = None


def pytest_configure(config) -> None:
    global _REC
    out = os.environ.get("FAULT_REACH_DIR")
    if not out:
        return
    _REC = _Recorder()
    _REC.patch_mock()
    _REC.start()


def pytest_collection_modifyitems(session, config, items) -> None:
    if _REC is None:
        return
    seen: set[str] = set()
    for item in items:
        p = str(Path(str(item.fspath)).resolve())
        if p in seen:
            continue
        seen.add(p)
        try:
            lines = analyse(Path(p)).target_lines()
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        if lines:
            _REC.targets[p] = lines
    sys.monitoring.restart_events()  # lines in these files that fired during collection were disabled before their targets were known


def pytest_runtest_setup(item) -> None:
    if _REC is not None:
        _REC.current = item.nodeid


def pytest_runtest_call(item) -> None:
    if _REC is not None:
        _REC.current = item.nodeid


def pytest_runtest_logreport(report) -> None:
    """A test RAN when its call phase finished without skipping: a ``pytest.skip`` inside the body never reached its fault either."""
    if _REC is not None and report.when == "call" and not report.skipped:
        _REC.ran.add(report.nodeid)


def pytest_runtest_teardown(item, nextitem) -> None:
    if _REC is not None:
        _REC.current = item.nodeid


def pytest_sessionfinish(session, exitstatus) -> None:
    if _REC is None:
        return
    _REC.stop()
    _REC.dump(Path(os.environ["FAULT_REACH_DIR"]))
