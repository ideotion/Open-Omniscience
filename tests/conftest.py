"""
Global test isolation (audit finding F-004).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src.database.session`` computes ``DATA_DIR`` / ``DATABASE_URL`` from ``OO_DATA_DIR``
at *import* time, and the engine is a module singleton. pytest imports this conftest
before any test module imports ``src.*``, so setting ``OO_DATA_DIR`` here — to an
ephemeral directory — binds every on-disk artifact (SQLite DB, keys, caches, custody
log) under that throwaway dir instead of the working-tree ``data/``. This keeps the
suite hermetic (no repository pollution) and order-independent.

``setdefault`` is used so an explicit ``OO_DATA_DIR`` (CI, or an operator running a
specific scenario) still wins, and per-test ``monkeypatch.setenv`` continues to override
for the JSON-file state that is read at runtime.
"""

from __future__ import annotations

import atexit
import importlib.util
import os
import shutil
import tempfile

_ISOLATED = tempfile.mkdtemp(prefix="oo-tests-")
# Audit finding 2026-07-17: this directory backs SQLite DBs, keys, caches, and
# custody logs for the WHOLE test session and was never cleaned up -- every pytest
# invocation left a fresh oo-tests-* directory behind (accumulating in the OS temp
# dir across CI runs / local dev). atexit fires at interpreter shutdown regardless
# of which pytest hooks ran, so this cleans up even if the suite is interrupted.
# ignore_errors=True: a stray open handle (e.g. a not-yet-closed sqlite3 connection
# at shutdown) must never turn cleanup into a crash on the way out.
atexit.register(shutil.rmtree, _ISOLATED, ignore_errors=True)
os.environ.setdefault("OO_DATA_DIR", _ISOLATED)
# Never autostart the background scraper thread during tests.
os.environ.setdefault("OO_NO_SCHEDULER", "1")
# Never auto-seed the ~3,200-source production catalog during tests. The seed moved
# into run_deferred_startup on 2026-06-18, so it now fires on EVERY TestClient-context
# lifespan -- slow, non-hermetic, and its auto-increment Source ids collide with tests
# that pin ids (e.g. the convergence endpoint test). Tests that need the catalog call
# the seeder directly; one that wants the lifespan seed can still set OO_AUTOSEED=1.
os.environ.setdefault("OO_AUTOSEED", "0")
# The suite runs on an EXPLICIT plaintext store (the ruled opt-out); the
# SQLCipher paths are exercised by tests/test_sqlcipher.py with their own
# passphrases and data dirs.
os.environ.setdefault("OO_DB_PLAINTEXT", "1")

# --- Optional-extra test isolation (findings TEST-06 + OO-D15-005) ----------- #
# The analysis/nlp extras (numpy/scipy/pandas/scikit-learn/statsmodels/networkx/
# vaderSentiment/spaCy) are optional. The app boots fine without them (the
# analysis/commodity/keyword routers are simply not mounted -- see the optional
# try/except in src/api/_wiring.py:wire()), so a core-only install
# (`pip install -e '.[dev]'`) MUST yield a green suite. Two failure modes:
#   (1) a test module imports an extra at COLLECTION time -> hard ImportError;
#   (2) a test exercises an analysis router that isn't mounted -> 404 failures.
# We skip-collect the affected modules rather than letting them error/fail.
#
# (1) is now handled GENERICALLY: any test_*.py that directly imports a MISSING
#     extra is auto-ignored, so a future statsmodels/sklearn/networkx/spaCy test
#     needs no manual list edit. The prior probe checked only numpy/scipy/pandas
#     against a hand-maintained list, so such a test would have hard-errored.
# (2) keeps an explicit list, since a router-404 is a runtime failure no import
#     scanner can see.
_EXTRA_MODULES = (
    "numpy",
    "scipy",
    "pandas",
    "sklearn",
    "statsmodels",
    "networkx",
    "spacy",
    "vaderSentiment",
)
_MISSING_EXTRAS = {_m for _m in _EXTRA_MODULES if importlib.util.find_spec(_m) is None}
# The analysis routers need the numpy/scipy/pandas core of the [analysis] extra.
ANALYSIS_AVAILABLE = not ({"numpy", "scipy", "pandas"} & _MISSING_EXTRAS)

# (2) Router-dependent modules: green only with the analysis routers mounted.
_ROUTER_DEPENDENT = [
    "test_awareness.py",
    "test_commodity.py",
    "test_commodity_csv.py",
    "test_confidence_intervals.py",
    "test_statistical_tests.py",
    "test_analysis_api.py",
    "test_csv_feeds.py",
    "test_workflow_integration.py",
    "test_framing_keywords_api.py",
]

collect_ignore: list[str] = []
if not ANALYSIS_AVAILABLE:
    collect_ignore.extend(_ROUTER_DEPENDENT)
# (1) Generic import-error guard: ignore any test file that directly imports an
# extra we do not have installed.
if _MISSING_EXTRAS:
    import re as _re
    from pathlib import Path as _Path

    _extra_import = _re.compile(
        r"^\s*(?:import|from)\s+(" + "|".join(_re.escape(_m) for _m in _EXTRA_MODULES) + r")\b",
        _re.MULTILINE,
    )
    for _f in sorted(_Path(__file__).parent.glob("test_*.py")):
        try:
            _src = _f.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - unreadable file
            continue
        if (set(_extra_import.findall(_src)) & _MISSING_EXTRAS) and _f.name not in collect_ignore:
            collect_ignore.append(_f.name)


import pytest  # noqa: E402 - must follow the OO_DATA_DIR/plaintext env setup above


@pytest.fixture(autouse=True)
def _clear_network_kill_switch():
    """The kill switch is process-global by design (a real kill switch); tests
    that hit /api/scheduler/stop would otherwise poison every later fetch test."""
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    yield
    clear_kill_switch()


@pytest.fixture(autouse=True)
def _write_gate_not_leaked(request):
    """Guard against the gate-leak HANG class of bug: a test must never leave the
    single-writer gate held — the next writer would block forever (it once did,
    silently, until faulthandler pinned it). Recover the gate, then fail the
    offending test by name so a leak surfaces as a clear failure, never a hang.

    A LEGITIMATE background writer can still be mid-commit at teardown — notably the
    briefing-refresh DAEMON kicked by ``/api/briefing/refresh`` (non-blocking by design,
    #455), which writes on its own session after the request returns. That is NOT a leak,
    so when the gate is held we WAIT briefly for it to drain; a real leak (a session
    flushed but never committed/closed) never releases, so the bounded wait still surfaces
    it. The wait only runs on the rare teardown that overlaps a background write."""
    import time

    from src.database.writer import write_gate as _g

    yield
    if _g.stats()["held"]:
        deadline = time.monotonic() + 5.0
        while _g.stats()["held"] and time.monotonic() < deadline:
            time.sleep(0.02)
    if _g.stats()["held"]:
        _g._reset_for_tests()  # recover so the rest of the suite still runs
        raise AssertionError(
            f"{request.node.nodeid} left the single-writer write gate HELD "
            "(would hang the next writer): a session was flushed but never "
            "committed/rolled-back/closed. Use session_scope()/get_db, or close()."
        )


@pytest.fixture(autouse=True)
def _memory_guard_not_leaked():
    """The RSS memory guard (P0.3 E3) is a process-global latch; a test that
    legitimately trips it (e.g. a monitor tick fed low-memory vitals) must
    never leak a paused-low-memory state into the next test — the same
    order-dependent-pollution class as the write-gate guard above."""
    yield
    from src.scheduler.memguard import memory_guard

    memory_guard.reset(reason="test isolation")


@pytest.fixture(autouse=True)
def _isolated_robots_cache_path(tmp_path, monkeypatch):
    """A5 (2026-07-24 throughput brief, C4): EthicalFetcher now persists an
    in-TTL robots.txt verdict to a shared data_dir() sidecar BY DEFAULT (the
    point: make_fetcher() builds a brand-new instance every pass, so this is
    what stops every pass re-fetching robots.txt for every host). Left
    pointed at the real (session-isolated but still SHARED-across-tests)
    data_dir, two unrelated tests fetching the same domain (e.g.
    "example.com") would leak a robots decision from one into the other —
    the same order-dependent-pollution class the write-gate/memory-guard
    fixtures above guard against. Point the DEFAULT path at a fresh per-test
    tmp file so a test that never asks for this feature is unaffected; a
    test that explicitly passes its own ``robots_cache_path=`` (the
    persistence tests themselves, tests/test_robots_cache_persistence.py) is
    unaffected either way."""
    import src.ingest as _ingest_mod

    monkeypatch.setattr(_ingest_mod, "_robots_cache_path", lambda: tmp_path / "robots_cache.json")
