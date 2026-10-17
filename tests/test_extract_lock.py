"""One extraction at a time, process-wide -- and the three ways that guarantee quietly stops being true.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

libxml2 aborted the collector (SIGABRT, no Python traceback) inside ``lxml.html.document_fromstring``
under a pool of ~50 workers: one boot in seven, 2026-10-14. The cause is NOT established
(``docs/ledger/OPEN_QUEUE.md``, "THE lxml SIGABRT"), so ``src/ingest/extract.py`` makes concurrent use
of libxml2 by the app's article extraction impossible, whatever the fault was: ``_LXML_LOCK`` around the whole
``extract_article`` call tree. A lock is only as good as its coverage, and coverage is what a later
change breaks without any test failing, so this file pins three things:

  1. the lock actually serialises -- the primary path AND the two-call fallback, and it is released
     when the extraction raises (a leaked lock would stop every collect worker, silently);
  2. the trees are released INSIDE the lock, not after it: on a return (the result holds text only, so
     the trees die with the call's last local -- a refactor that returned the ``Document`` and converted
     it outside the lock would free libxml2 memory concurrently again) and on a raise (an exception's
     traceback keeps the frames, and their locals, alive until the caller drops it);
  3. nothing else in ``src/`` can reach libxml2 -- no other module imports lxml or trafilatura, no
     ``BeautifulSoup`` is built without the explicit pure-Python ``html.parser``, no ``read_html`` --
     and inside ``extract.py`` only the two locked functions call trafilatura, only under the lock.

Each test fails when the thing it guards goes: a lock removed, a lock leaked, a tree released late, a new
import, a new helper that calls trafilatura on its own. The walks run on fixture sources as well as on the
tree, so the guard itself is checked to see what it claims to see.

WHAT THE WALKS DO NOT SEE, said so: a dynamic import whose module name is computed, a call deferred out
of the ``with`` block (a lambda or a thread target created under the lock and run after it), and a
rebinding of the lock name to something that does not lock (the runtime tests catch that one). Nor do they
see a third-party library that reaches libxml2 by itself: feedparser asks for the libxml2 SAX driver first
(``feedparser.api.PREFERRED_XML_PARSERS == ["drv_libxml2"]``) and uses it wherever the libxml2 Python
bindings import (a system or distro Python; a pip venv has no ``drv_libxml2``), in every collector worker and
outside the lock. So "nothing else in ``src/`` can reach libxml2" is a statement about the app's own imports.

A regression must FAIL here, not hang the run: the autouse fixture below turns a lock a previous test
left held (a deadlocked or leaked holder) into a failure of the next test within a second.
"""

from __future__ import annotations

import ast
import threading
import time
import traceback
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


@pytest.fixture(autouse=True)
def _the_lock_is_free_at_the_start_of_every_test():
    """Fail fast when a previous test left the lock held.

    A plain ``Lock`` regression deadlocks the nesting test's thread INSIDE the lock; the next test that
    extracts on the main thread would then wait for ever (no pytest-timeout here, and the CI job has no
    time limit short of GitHub's). Asking for the lock with a short timeout turns that into a failure
    that names the cause. Any thread other than the holder may take a free lock, so this thread asks.
    """
    got = extract_mod._LXML_LOCK.acquire(timeout=1)
    assert got, "the extraction lock is still held by a thread an earlier test left behind (a deadlock or a leak)"
    extract_mod._LXML_LOCK.release()
    yield


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
    # Checked BEFORE nesting: with a plain Lock the nested call below would deadlock its thread inside the lock for good.
    assert type(extract_mod._LXML_LOCK) is type(threading.RLock()), (
        f"_LXML_LOCK is a {type(extract_mod._LXML_LOCK).__name__}, not an RLock: a nested extraction would deadlock"
    )
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
    asker.join(timeout=2)
    waited_for_the_lock = asker.is_alive()  # read BEFORE the slow extraction is let go: afterwards the asker could finish
    release.set()
    worker.join(timeout=10)
    asker.join(timeout=10)
    assert not waited_for_the_lock, "a blank page waited for the lock"
    assert answers == [None, None]


# --------------------------------------------------------------------------- #
# 2. the trees are released while the lock is still held
# --------------------------------------------------------------------------- #


class _Tree:
    """Stands in for an lxml tree: records whether the extraction lock was held when it was released."""

    owned_at_release: list[bool] = []

    def __del__(self) -> None:
        # ``_is_owned`` exists on an RLock; a lock of another type records None, which the assertion below names.
        is_owned = getattr(extract_mod._LXML_LOCK, "_is_owned", None)
        _Tree.owned_at_release.append(is_owned() if is_owned else None)


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
        # ``type(...) is str``: an lxml smart string IS a str, and keeps its tree alive through ``getparent()``.
        assert type(getattr(result, name)) in (str, type(None)), f"ExtractedDoc.{name} is not plain text"


def test_the_trees_of_a_raising_extraction_are_freed_inside_the_lock_and_the_traceback_still_names_the_frames(monkeypatch):
    """The exception carries its traceback, the traceback keeps each frame's locals (``bare_extraction``'s trees) alive.

    Without ``_release_frames`` they are freed when the CALLER drops the exception, after the lock was given up -- a worker's
    ``except`` clause in runner.py -- while another worker may be inside a parse. Both calls raise here (the primary, then the
    fallback), which is the only way an exception escapes ``extract_article``; the fallback's exception carries the primary's
    as ``__context__``.
    """
    _Tree.owned_at_release = []

    def primary(*_a, **_kw):
        tree = _Tree()  # noqa: F841 - a frame local, the way ``bare_extraction`` holds its tree
        raise RuntimeError("primary")

    def fallback(*_a, **_kw):
        tree = _Tree()  # noqa: F841
        raise ValueError("fallback")

    monkeypatch.setattr(trafilatura, "bare_extraction", primary)
    monkeypatch.setattr(trafilatura, "extract", fallback)
    with pytest.raises(ValueError, match="fallback") as caught:
        extract_article(_HTML, url="https://example.org/a")
    # still inside ``pytest.raises``' hold of the exception: only the clearing can have freed the trees by now
    assert _Tree.owned_at_release == [True, True], (
        f"the trees of a raising extraction were not freed while the lock was held -- saw {_Tree.owned_at_release}"
    )
    frames = [f.name for f in traceback.extract_tb(caught.value.__traceback__)]
    assert "fallback" in frames and "extract_article" in frames, f"the traceback lost its frames: {frames}"
    context = caught.value.__context__
    assert isinstance(context, RuntimeError) and "primary" in [f.name for f in traceback.extract_tb(context.__traceback__)]


def test_a_tree_held_by_an_attribute_errors_object_is_freed_inside_the_lock_and_the_message_is_kept(monkeypatch):
    """Clearing frames is not enough: since Python 3.10 an ``AttributeError`` holds the object whose lookup failed (``obj``), and on an
    lxml element that is the element and so its whole document. trafilatura, htmldate and justext do their work on elements, so one such
    error in the primary and one in the fallback would leave both trees alive until the caller drops the exception, after the lock."""
    _Tree.owned_at_release = []

    def primary(*_a, **_kw):
        tree = _Tree()
        tree.no_such_attribute  # noqa: B018 - the interpreter raises AttributeError with obj=tree

    def fallback(*_a, **_kw):
        tree = _Tree()
        tree.another_missing_attribute  # noqa: B018

    monkeypatch.setattr(trafilatura, "bare_extraction", primary)
    monkeypatch.setattr(trafilatura, "extract", fallback)
    with pytest.raises(AttributeError) as caught:
        extract_article(_HTML, url="https://example.org/a")
    assert _Tree.owned_at_release == [True, True], (
        f"a tree held by an AttributeError was not freed while the lock was held -- saw {_Tree.owned_at_release}"
    )
    # what a log shows is kept: the message, the frames, and the chain
    text = "".join(traceback.format_exception(caught.value))
    assert "another_missing_attribute" in text and "no_such_attribute" in text and "in fallback" in text and "in primary" in text, text
    assert caught.value.name == "another_missing_attribute"


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
    # reset_caches() clears LRU caches and calls gc.collect(); it parses nothing. It runs at the pass boundary and in the
    # low-memory pause loop (runner.py), which can overlap a run-now pass, the housekeeping lane or the API; the memory guard's
    # in-pass release is release_residents (gc.collect, malloc_trim), not reset_caches. OPEN_QUEUE "THE lxml SIGABRT" lists both.
    "src/scheduler/hygiene.py": frozenset({"trafilatura.meta"}),
    # The diagnostics bundle's machine block reads etree.LIBXML_VERSION, LIBXML_COMPILED_VERSION and LIBXSLT_VERSION (module constants)
    # so a crash report names the libxml2 the process ran. It parses nothing and builds no tree; the module (the native-libraries
    # reader of the diagnostics follow-on) is not in the tree before that bundle, and an entry for a file that is absent allows nothing.
    # The allowance is the ``etree`` module (``from lxml import etree``, ``from lxml.etree import X`` or ``import lxml.etree as etree``), by
    # name: ``from lxml import html`` and a bare ``import lxml.etree`` (which binds the whole ``lxml``) are refused there. The walk
    # reads imports, not calls, so a parse call on ``etree`` in that file would not be seen here; the file is read by hand when it changes.
    "src/monitoring/native_libs.py": frozenset({"lxml.etree"}),
}


#: What the rest of ``src/`` may take from ``src/ingest/extract.py``: the entry point and its result, never the locked helpers or the
#: ``trafilatura`` name the module holds (a call to those from another module would be an extraction outside the lock).
_EXTRACT_PATH = "src/ingest/extract.py"
_EXTRACT_PUBLIC = frozenset({"extract_article", "ExtractedDoc", "extensive_date_search_enabled"})


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
                root = alias.name.split(".")[0]
                if alias.asname is None and "." in alias.name and alias.name in allowed and root in _LIBXML_ROOTS and root not in allowed:
                    # ``import lxml.etree`` binds the name ``lxml``, the WHOLE package, so ``lxml.html`` is reachable through it (trafilatura
                    # has imported it by then): only ``import lxml.etree as etree`` or ``from lxml import etree`` bind just the submodule.
                    found.append(f"{path}:{node.lineno} imports {alias.name} without 'as' (it binds {root}, the whole package)")
                if alias.name == "src.ingest.extract" and path != _EXTRACT_PATH:
                    found.append(f"{path}:{node.lineno} imports src.ingest.extract whole (its locked helpers become reachable)")
        elif isinstance(node, ast.ImportFrom):
            # ``from . import x`` has module None and level > 0: relative, never one of ours.
            module = node.module or ""
            if node.level == 0 and "." not in module and module in _LIBXML_ROOTS and module not in allowed:
                # ``from lxml import html`` takes the SUBMODULE ``lxml.html``: judge each name, or an allowance for ``lxml.etree`` would
                # carry ``html`` (a parser) with it. A file allowed the whole package (extract.py: trafilatura) is not affected.
                for alias in node.names:
                    check(f"{module}.{alias.name}", node.lineno, "imports from")
            else:
                check(module, node.lineno, "imports from")
            if node.module == "bs4" and any(a.name == "BeautifulSoup" and a.asname for a in node.names):
                found.append(f"{path}:{node.lineno} imports BeautifulSoup under another name (the walk reads calls by name)")
            if path != _EXTRACT_PATH:
                names = {a.name for a in node.names}
                inside_ingest = node.level > 0 and path.startswith("src/ingest/")
                if node.module == "src.ingest.extract" or (inside_ingest and node.module == "extract"):
                    private = sorted(names - _EXTRACT_PUBLIC)
                    if private:
                        found.append(f"{path}:{node.lineno} takes {', '.join(private)} from src.ingest.extract (only {sorted(_EXTRACT_PUBLIC)} are public)")
                elif "extract" in names and (node.module == "src.ingest" or (inside_ingest and node.module is None)):
                    found.append(f"{path}:{node.lineno} imports the src.ingest.extract module whole (its locked helpers become reachable)")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func) or ""
            tail = name.rsplit(".", 1)[-1]
            if tail in {"import_module", "__import__"} and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    check(first.value, node.lineno, "imports dynamically")
            elif tail in {"read_html", "read_xml", "to_xml"}:
                # pandas reads and writes HTML and XML with lxml unless told otherwise.
                found.append(f"{path}:{node.lineno} calls {tail} (pandas: lxml by default)")
            elif tail == "BeautifulSoup":
                # With no explicit parser, bs4 uses the best one installed -- lxml, when it is there.
                features = node.args[1] if len(node.args) > 1 else next(
                    (kw.value for kw in node.keywords if kw.arg == "features"), None
                )
                if not (isinstance(features, ast.Constant) and features.value == "html.parser"):
                    found.append(f"{path}:{node.lineno} builds BeautifulSoup without the explicit html.parser")
                elif any(kw.arg == "builder" for kw in node.keywords):
                    found.append(f"{path}:{node.lineno} builds BeautifulSoup with its own builder")
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
        # the machine block's allowance is for the etree module's constants, not for a parser
        ("import lxml.html\n", "src/monitoring/native_libs.py", "imports lxml.html"),
        ("from lxml import html\nhtml.fromstring(x)\n", "src/monitoring/native_libs.py", "imports from lxml.html"),
        ("from lxml import html as h\n", "src/monitoring/native_libs.py", "imports from lxml.html"),
        ("import lxml\nlxml.etree.fromstring(x)\n", "src/monitoring/native_libs.py", "imports lxml"),
        ("from lxml import etree, html\n", "src/monitoring/native_libs.py", "imports from lxml.html"),
        # ``import a.b`` binds ``a``: the allowance for one submodule must not carry the package's others with it
        ("import lxml.etree\nlxml.html.fromstring(x)\n", "src/monitoring/native_libs.py", "imports lxml.etree without 'as'"),
        ("import trafilatura.meta\n", "src/scheduler/hygiene.py", "imports trafilatura.meta without 'as'"),
        ("import trafilatura\n", "src/a.py", "imports trafilatura"),
        ("from htmldate import find_date\n", "src/a.py", "imports from htmldate"),
        ("from trafilatura.meta import reset_caches\n", "src/a.py", "imports from trafilatura.meta"),
        ("import importlib\nimportlib.import_module('lxml.html')\n", "src/a.py", "imports dynamically lxml.html"),
        ("__import__('justext')\n", "src/a.py", "imports dynamically justext"),
        ("import pandas as pd\npd.read_html(x)\n", "src/a.py", "calls read_html"),
        ("import pandas as pd\npd.read_xml(x)\n", "src/a.py", "calls read_xml"),
        ("df.to_xml()\n", "src/a.py", "calls to_xml"),
        ("from bs4 import BeautifulSoup as Soup\n", "src/a.py", "under another name"),
        ("from bs4 import BeautifulSoup\nBeautifulSoup(x, 'html.parser', builder=b)\n", "src/a.py", "with its own builder"),
        ("from src.ingest.extract import _extract_resiliently\n", "src/a.py", "takes _extract_resiliently"),
        ("from src.ingest.extract import extract_article, _LXML_LOCK\n", "src/a.py", "takes _LXML_LOCK"),
        ("from .extract import trafilatura\n", "src/ingest/b.py", "takes trafilatura"),
        ("import src.ingest.extract as e\n", "src/a.py", "imports src.ingest.extract whole"),
        ("from src.ingest import extract\n", "src/a.py", "imports the src.ingest.extract module whole"),
        ("from . import extract\n", "src/ingest/b.py", "imports the src.ingest.extract module whole"),
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
        ("from lxml import etree\nprint(etree.LIBXML_VERSION)\n", "src/monitoring/native_libs.py"),
        ("from lxml.etree import LIBXML_VERSION\n", "src/monitoring/native_libs.py"),
        ("import lxml.etree as etree\nprint(etree.LIBXML_VERSION)\n", "src/monitoring/native_libs.py"),
        ("import trafilatura.settings\n", "src/ingest/extract.py"),
        ("import trafilatura\nfrom trafilatura.settings import Document\n", "src/ingest/extract.py"),
        ("from bs4 import BeautifulSoup\nBeautifulSoup(x, 'html.parser')\n", "src/a.py"),
        ("from bs4 import BeautifulSoup\nBeautifulSoup(x, features='html.parser')\n", "src/a.py"),
        ("import xml.etree.ElementTree as ET\n", "src/a.py"),
        ("from . import lxml_helpers\nfrom .trafilatura_x import y\n", "src/a.py"),
        ("from src.ingest.extract import extract_article, ExtractedDoc\n", "src/ingest/pipeline.py"),
        ("from .extract import extract_article\n", "src/ingest/b.py"),
        # another package's own module named extract is not ours
        ("from .extract import _private_thing\nfrom . import extract\n", "src/markets/run.py"),
        ("from src.ingest import extract_article\n", "src/a.py"),
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
        elif isinstance(node, ast.Name) and node.id == "trafilatura" and isinstance(node.ctx, ast.Load):
            # Any use of the name, not only a call: an alias (``_BARE = trafilatura.bare_extraction``), ``getattr(trafilatura, ...)``
            # and ``partial(trafilatura.extract)`` all reach the library without a ``trafilatura.x(...)`` call to see.
            where = _function_of(node, parents)
            if where not in _LOCKED_FUNCTIONS:
                problems.append(f"line {node.lineno}: trafilatura is used in {where}, outside the locked functions")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func) or ""
            where = _function_of(node, parents)
            if name == "Document":
                # Since trafilatura 2.1.0 every Document() builds two lxml documents (the very code of issue #840).
                problems.append(f"line {node.lineno}: Document() is built in {where}: it creates lxml trees; only trafilatura builds them")
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
         "trafilatura is used in metadata_only"),
        # a module-level call
        (lambda s: s + "WARM = trafilatura.extract('<p>x</p>')\n", "trafilatura is used in <module>"),
        # an alias, getattr and partial reach the library without a ``trafilatura.x(...)`` call
        (lambda s: s + "_BARE = trafilatura.bare_extraction\n", "trafilatura is used in <module>"),
        (lambda s: s + "def other2(h):\n    return getattr(trafilatura, 'extract')(h)\n", "trafilatura is used in other2"),
        (lambda s: s + "import functools\ndef other3():\n    return functools.partial(trafilatura.extract, favor_recall=True)\n", "trafilatura is used in other3"),
        # a Document built anywhere makes lxml trees
        (lambda s: s + "def blank():\n    return Document()\n", "Document() is built in blank"),
        (lambda s: s + "_EMPTY = Document()\n", "Document() is built in <module>"),
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
