"""One extraction at a time, process-wide -- and the three ways that guarantee quietly stops being true.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

libxml2 aborted the collector (SIGABRT, no Python traceback) inside ``lxml.html.document_fromstring``
under a pool of ~50 workers: one boot in seven, 2026-10-14. The cause is NOT established
(``docs/ledger/OPEN_QUEUE.md``, "THE lxml SIGABRT"), so ``src/ingest/extract.py`` makes concurrent use
of libxml2 impossible from the app, whatever the fault was: ``_LXML_LOCK`` around the whole
``extract_article`` call tree. A lock is only as good as its coverage, and coverage is what a later
change breaks without any test failing, so this file pins three things:

  1. the lock actually serialises -- the primary path AND the two-call fallback, and it is released
     when the extraction raises (a leaked lock would stop every collect worker, silently);
  2. the trees are released INSIDE the lock, not after it (the result holds text only, so the trees die
     with the call's last local -- a refactor that returned the ``Document`` and converted it outside
     the lock would free libxml2 memory concurrently again);
  3. nothing else in ``src/`` can reach libxml2 -- no other module imports lxml or trafilatura, no
     ``BeautifulSoup`` is built without the explicit pure-Python ``html.parser``, no ``read_html`` --
     and inside ``extract.py`` only the two locked functions call trafilatura, only under the lock.

Each test fails when the thing it guards goes: a lock removed, a lock leaked, a tree released late, a new
import, a new helper that calls trafilatura on its own. The walks run on fixture sources as well as on the
tree, so the guard itself is checked to see what it claims to see.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest
import trafilatura
from trafilatura.settings import Document

import src.ingest.extract as extract_mod
from src.ingest.extract import ExtractedDoc, extract_article

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"

_HTML = "<html><body><p>" + "A sentence that is long enough to count as a body. " * 12 + "</p></body></html>"


def _document(text: str | None = None) -> Document:
    doc = Document()
    doc.text = text if text is not None else "A sentence that is long enough to count as a body. " * 12
    doc.title = "A title"
    return doc


class _Meter:
    """Counts how many callers are INSIDE a fake at once. ``peak`` > 1 means two extractions overlapped."""

    def __init__(self, hold_s: float = 0.02) -> None:
        self._guard = threading.Lock()
        self.hold_s = hold_s
        self.inside = 0
        self.peak = 0
        self.entries = 0

    def stay(self) -> None:
        with self._guard:
            self.inside += 1
            self.entries += 1
            self.peak = max(self.peak, self.inside)
        # The sleep releases the GIL: without a lock a second thread walks in while this one is "inside".
        time.sleep(self.hold_s)
        with self._guard:
            self.inside -= 1


def _run_threads(count: int, target) -> list:
    """Start ``count`` threads together (a barrier), return what each returned. A raise in a thread fails the test."""
    start = threading.Barrier(count)
    out: list = [None] * count
    errors: list[BaseException] = []

    def work(i: int) -> None:
        try:
            start.wait(timeout=10)
            out[i] = target(i)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the test thread below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a worker never finished (a deadlock?)"
    if errors:
        raise errors[0]
    return out


# --------------------------------------------------------------------------- #
# 1. the lock serialises, on both paths, and is released on a raise
# --------------------------------------------------------------------------- #


def test_two_threads_are_never_inside_the_primary_extraction_together(monkeypatch):
    meter = _Meter()

    def fake(*_a, **_kw):
        meter.stay()
        return _document()

    monkeypatch.setattr(trafilatura, "bare_extraction", fake)
    results = _run_threads(8, lambda i: extract_article(_HTML, url=f"https://example.org/{i}"))
    assert all(isinstance(r, ExtractedDoc) for r in results)
    assert meter.entries == 8
    assert meter.peak == 1, f"{meter.peak} extractions overlapped: the process-wide lock is not held"


def test_the_two_call_fallback_is_inside_the_same_lock(monkeypatch):
    meter = _Meter()

    def explodes(*_a, **_kw):
        meter.stay()
        raise RuntimeError("the metadata pass threw")

    def body(*_a, **_kw):
        meter.stay()
        return "A sentence that is long enough to count as a body. " * 12

    def metadata(*_a, **_kw):
        meter.stay()
        return _document()

    monkeypatch.setattr(trafilatura, "bare_extraction", explodes)
    monkeypatch.setattr(trafilatura, "extract", body)
    monkeypatch.setattr(trafilatura, "extract_metadata", metadata)
    results = _run_threads(6, lambda i: extract_article(_HTML, url=f"https://example.org/{i}"))
    assert all(isinstance(r, ExtractedDoc) for r in results), "the fallback no longer rescues the article"
    assert meter.entries == 18, "each article should pass through all three calls once"
    assert meter.peak == 1, f"{meter.peak} calls overlapped on the fallback path"


def test_the_lock_is_released_when_an_extraction_raises(monkeypatch):
    def explodes(*_a, **_kw):
        raise RuntimeError("primary")

    def explodes_again(*_a, **_kw):
        raise ValueError("fallback")

    monkeypatch.setattr(trafilatura, "bare_extraction", explodes)
    monkeypatch.setattr(trafilatura, "extract", explodes_again)
    with pytest.raises(ValueError, match="fallback"):
        extract_article(_HTML, url="https://example.org/a")

    # RLock: the test thread would re-acquire its own leaked lock, so ask from ANOTHER thread.
    taken: list[bool] = []

    def other() -> None:
        got = extract_mod._LXML_LOCK.acquire(timeout=2)
        taken.append(got)
        if got:
            extract_mod._LXML_LOCK.release()

    t = threading.Thread(target=other, daemon=True)
    t.start()
    t.join(timeout=5)
    assert taken == [True], "the lock is still held after an extraction raised: every collect worker would stall"


def test_the_lock_can_be_taken_again_by_the_thread_that_holds_it(monkeypatch):
    """RLock, not Lock: a caller that nests extraction must not deadlock itself (it would hang the pass, not fail)."""
    seen: list[ExtractedDoc | None] = []
    depth = {"n": 0}

    def nesting(*_a, **_kw):
        if depth["n"] == 0:
            depth["n"] = 1
            seen.append(extract_article(_HTML, url="https://example.org/inner"))
        return _document()

    monkeypatch.setattr(trafilatura, "bare_extraction", nesting)
    done: list[ExtractedDoc | None] = []
    t = threading.Thread(target=lambda: done.append(extract_article(_HTML, url="https://example.org/outer")), daemon=True)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive(), "a nested extraction deadlocked on its own lock"
    assert isinstance(done[0], ExtractedDoc) and isinstance(seen[0], ExtractedDoc)


def test_a_blank_page_is_refused_before_the_lock_is_asked_for(monkeypatch):
    """A page with nothing in it must not queue behind a slow extraction: the cheap refusals stay outside."""
    held = threading.Event()
    release = threading.Event()

    def slow(*_a, **_kw):
        held.set()
        assert release.wait(timeout=10)
        return _document()

    monkeypatch.setattr(trafilatura, "bare_extraction", slow)
    worker = threading.Thread(target=lambda: extract_article(_HTML, url="https://example.org/slow"), daemon=True)
    worker.start()
    assert held.wait(timeout=10), "the slow extraction never started"
    answers: list[ExtractedDoc | None] = []
    asker = threading.Thread(target=lambda: answers.extend([extract_article(""), extract_article("   \n ")]), daemon=True)
    asker.start()
    asker.join(timeout=5)
    release.set()
    worker.join(timeout=10)
    assert not asker.is_alive(), "a blank page waited for the lock"
    assert answers == [None, None]


# --------------------------------------------------------------------------- #
# 2. the trees are released while the lock is still held
# --------------------------------------------------------------------------- #


class _Tree:
    """Stands in for an lxml tree: records whether the extraction lock was held when it was released."""

    owned_at_release: list[bool] = []

    def __del__(self) -> None:
        _Tree.owned_at_release.append(extract_mod._LXML_LOCK._is_owned())  # type: ignore[attr-defined]


def test_the_trees_are_freed_inside_the_lock_and_the_result_holds_no_tree(monkeypatch):
    _Tree.owned_at_release = []

    def fake(*_a, **_kw):
        doc = _document()
        doc.body = _Tree()  # type: ignore[assignment]
        doc.commentsbody = _Tree()  # type: ignore[assignment]
        return doc

    monkeypatch.setattr(trafilatura, "bare_extraction", fake)
    result = extract_article(_HTML, url="https://example.org/a")
    assert isinstance(result, ExtractedDoc)
    assert _Tree.owned_at_release == [True, True], (
        "a tree was released after the lock was given up (or never released): libxml2 memory is freed "
        f"concurrently again -- saw {_Tree.owned_at_release}"
    )
    for name in ("title", "text", "language", "author", "canonical_url"):
        assert isinstance(getattr(result, name), (str, type(None))), f"ExtractedDoc.{name} holds a non-text value"


# --------------------------------------------------------------------------- #
# 3. nothing else in the app reaches libxml2
# --------------------------------------------------------------------------- #

#: Roots that bring libxml2 (or an lxml-backed parser) into the process. ``htmldate``/``justext``/``readability`` are
#: trafilatura's own parsers: they run only inside its call tree.
_LIBXML_ROOTS = frozenset({"lxml", "trafilatura", "htmldate", "justext", "readability", "lxml_html_clean"})

#: file -> the modules it may import from those roots, and why.
_ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    # THE module: every parse of the app's HTML happens in its call tree, under the lock.
    "src/ingest/extract.py": frozenset({"trafilatura", "trafilatura.settings"}),
    # reset_caches() clears LRU caches and calls gc.collect(); it parses nothing. It can run beside a pool (the memory guard
    # fires during a pass), which is why docs/ledger/OPEN_QUEUE.md "THE lxml SIGABRT" lists the collector as a limit, not as covered.
    "src/scheduler/hygiene.py": frozenset({"trafilatura.meta"}),
}


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _libxml_reach(source: str, path: str) -> list[str]:
    """Every way ``source`` (at repo-relative ``path``) can reach libxml2 outside the allowed places."""
    allowed = _ALLOWED_IMPORTS.get(path, frozenset())
    found: list[str] = []

    def check(module: str, line: int, how: str) -> None:
        if module.split(".")[0] in _LIBXML_ROOTS and module not in allowed:
            found.append(f"{path}:{line} {how} {module}")

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check(alias.name, node.lineno, "imports")
        elif isinstance(node, ast.ImportFrom):
            # ``from . import x`` has module None and level > 0: relative, never one of ours.
            check(node.module or "", node.lineno, "imports from")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func) or ""
            tail = name.rsplit(".", 1)[-1]
            if tail in {"import_module", "__import__"} and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    check(first.value, node.lineno, "imports dynamically")
            elif tail == "read_html":
                # pandas.read_html defaults to the lxml flavor.
                found.append(f"{path}:{node.lineno} calls read_html (lxml flavor by default)")
            elif tail == "BeautifulSoup":
                # With no explicit parser, bs4 uses the best one installed -- lxml, when it is there.
                features = node.args[1] if len(node.args) > 1 else next(
                    (kw.value for kw in node.keywords if kw.arg == "features"), None
                )
                if not (isinstance(features, ast.Constant) and features.value == "html.parser"):
                    found.append(f"{path}:{node.lineno} builds BeautifulSoup without the explicit html.parser")
    return found


def test_no_module_other_than_extract_reaches_libxml2():
    found: list[str] = []
    scanned = 0
    for file in sorted(_SRC.rglob("*.py")):
        rel = file.relative_to(_ROOT).as_posix()
        found += _libxml_reach(file.read_text(encoding="utf-8"), rel)
        scanned += 1
    assert scanned > 200, f"the walk saw only {scanned} files: it is not looking at src/"
    assert found == [], (
        "this code can reach libxml2 outside the extraction lock (src/ingest/extract.py:_LXML_LOCK):\n  "
        + "\n  ".join(found)
        + "\nRoute it through extract_article, or add it to _ALLOWED_IMPORTS with the reason it cannot run beside a pool."
    )


@pytest.mark.parametrize(
    ("source", "path", "expect"),
    [
        ("import lxml.html\n", "src/a.py", "imports lxml.html"),
        ("from lxml import etree\n", "src/a.py", "imports from lxml"),
        ("import trafilatura\n", "src/a.py", "imports trafilatura"),
        ("from htmldate import find_date\n", "src/a.py", "imports from htmldate"),
        ("from trafilatura.meta import reset_caches\n", "src/a.py", "imports from trafilatura.meta"),
        ("import importlib\nimportlib.import_module('lxml.html')\n", "src/a.py", "imports dynamically lxml.html"),
        ("__import__('justext')\n", "src/a.py", "imports dynamically justext"),
        ("import pandas as pd\npd.read_html(x)\n", "src/a.py", "calls read_html"),
        ("from bs4 import BeautifulSoup\nBeautifulSoup(x)\n", "src/a.py", "without the explicit html.parser"),
        ("from bs4 import BeautifulSoup\nBeautifulSoup(x, 'lxml')\n", "src/a.py", "without the explicit html.parser"),
        ("import bs4\nbs4.BeautifulSoup(x, features='lxml-xml')\n", "src/a.py", "without the explicit html.parser"),
        # The allowance is per file and per module: hygiene may import trafilatura.meta, not trafilatura.
        ("import trafilatura\n", "src/scheduler/hygiene.py", "imports trafilatura"),
        ("from trafilatura.settings import Document\n", "src/scheduler/hygiene.py", "imports from trafilatura.settings"),
    ],
)
def test_the_walk_sees_each_way_in(source, path, expect):
    found = _libxml_reach(source, path)
    assert len(found) == 1 and expect in found[0], found


@pytest.mark.parametrize(
    ("source", "path"),
    [
        ("from trafilatura.meta import reset_caches\n", "src/scheduler/hygiene.py"),
        ("import trafilatura\nfrom trafilatura.settings import Document\n", "src/ingest/extract.py"),
        ("from bs4 import BeautifulSoup\nBeautifulSoup(x, 'html.parser')\n", "src/a.py"),
        ("from bs4 import BeautifulSoup\nBeautifulSoup(x, features='html.parser')\n", "src/a.py"),
        ("import xml.etree.ElementTree as ET\n", "src/a.py"),
        ("from . import lxml_helpers\nfrom .trafilatura_x import y\n", "src/a.py"),
    ],
)
def test_the_walk_accepts_what_is_allowed(source, path):
    assert _libxml_reach(source, path) == []


# ---- inside extract.py: only the two locked functions call trafilatura, only under the lock ---- #

#: The functions that may call trafilatura, and from where each may be called.
_LOCKED_FUNCTIONS = {"_extract_locked", "_extract_resiliently"}


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _function_of(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return "<module>"


def _under_lock(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        if isinstance(node, ast.With) and any(_dotted(item.context_expr) == "_LXML_LOCK" for item in node.items):
            return True
    return False


def _lock_coverage(source: str) -> list[str]:
    """What is wrong with how ``extract.py`` calls trafilatura, as sentences. [] means every call is under the lock."""
    tree = ast.parse(source)
    parents = _parents(tree)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _LIBXML_ROOTS and (alias.name != "trafilatura" or alias.asname):
                    problems.append(f"line {node.lineno}: `import {alias.name}` must be plain `import trafilatura`")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in _LIBXML_ROOTS:
            names = {a.name for a in node.names}
            if node.module != "trafilatura.settings" or not names <= {"Document", "set_date_params"}:
                problems.append(f"line {node.lineno}: `from {node.module} import ...` hides which calls reach libxml2")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func) or ""
            where = _function_of(node, parents)
            if name.startswith("trafilatura.") and where not in _LOCKED_FUNCTIONS:
                problems.append(f"line {node.lineno}: {name}() is called from {where}, outside the locked functions")
            if name in _LOCKED_FUNCTIONS:
                if name == "_extract_locked" and not (where == "extract_article" and _under_lock(node, parents)):
                    problems.append(f"line {node.lineno}: _extract_locked() is called without `with _LXML_LOCK:`")
                if name == "_extract_resiliently" and where != "_extract_locked":
                    problems.append(f"line {node.lineno}: _extract_resiliently() is called from {where}, not from the locked body")
    return problems


def test_extract_py_calls_trafilatura_only_from_the_locked_functions():
    assert _lock_coverage((_SRC / "ingest" / "extract.py").read_text(encoding="utf-8")) == []


_LOCKED_SKELETON = """
import threading
import trafilatura
from trafilatura.settings import Document, set_date_params
_LXML_LOCK = threading.RLock()
def extract_article(html, *, url=None):
    with _LXML_LOCK:
        return _extract_locked(html, url=url)
def _extract_locked(html, *, url=None):
    try:
        return trafilatura.bare_extraction(html)
    except Exception:
        return _extract_resiliently(html, url=url)
def _extract_resiliently(html, *, url=None):
    return trafilatura.extract(html)
"""


@pytest.mark.parametrize(
    ("change", "expect"),
    [
        # a lock taken but not around the call
        (lambda s: s.replace("    with _LXML_LOCK:\n        return _extract_locked", "    if True:\n        return _extract_locked"),
         "_extract_locked() is called without"),
        # the call moved out of the with
        (lambda s: s.replace("    with _LXML_LOCK:\n        return _extract_locked(html, url=url)", "    with _LXML_LOCK:\n        pass\n    return _extract_locked(html, url=url)"),
         "_extract_locked() is called without"),
        # a new helper that calls trafilatura on its own
        (lambda s: s + "def metadata_only(html):\n    return trafilatura.extract_metadata(html)\n",
         "called from metadata_only"),
        # a module-level call
        (lambda s: s + "WARM = trafilatura.extract('<p>x</p>')\n", "called from <module>"),
        # the fallback reached from somewhere else
        (lambda s: s + "def other(html):\n    return _extract_resiliently(html)\n", "_extract_resiliently() is called from other"),
        # an alias that would hide the calls from the walk
        (lambda s: s.replace("import trafilatura\n", "import trafilatura as tf\n"), "must be plain `import trafilatura`"),
        (lambda s: s + "from trafilatura import bare_extraction\n", "hides which calls reach libxml2"),
        (lambda s: s + "from trafilatura.settings import Extractor\n", "hides which calls reach libxml2"),
    ],
)
def test_the_coverage_walk_names_each_way_the_lock_stops_covering(change, expect):
    assert _lock_coverage(_LOCKED_SKELETON) == [], "the skeleton the cases mutate is itself rejected"
    problems = _lock_coverage(change(_LOCKED_SKELETON))
    assert problems, "the walk accepted a change that takes a call out from under the lock"
    assert any(expect in p for p in problems), problems
