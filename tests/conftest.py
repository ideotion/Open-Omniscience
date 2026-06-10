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

import importlib.util
import os
import tempfile

_ISOLATED = tempfile.mkdtemp(prefix="oo-tests-")
os.environ.setdefault("OO_DATA_DIR", _ISOLATED)
# Never autostart the background scraper thread during tests.
os.environ.setdefault("OO_NO_SCHEDULER", "1")

# --- Optional [analysis] extra (finding TEST-06) ----------------------------- #
# numpy/scipy/pandas/scikit-learn ship only with the [analysis] extra. The app
# boots fine without them (the analysis/commodity/keyword routers are simply not
# mounted -- see src/api/main.py:_ANALYSIS_AVAILABLE), so a core-only install
# (`pip install -e '.[dev]'`) MUST yield a green suite. These modules either
# import scipy/numpy at collection time (hard ImportError) or exercise endpoints
# that 404 without the routers; on a core-only install we skip collecting them
# rather than letting them error/fail. With the extra installed they all run.
ANALYSIS_AVAILABLE = all(
    importlib.util.find_spec(_m) is not None for _m in ("numpy", "scipy", "pandas")
)

if not ANALYSIS_AVAILABLE:
    collect_ignore = [
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


import pytest


@pytest.fixture(autouse=True)
def _clear_network_kill_switch():
    """The kill switch is process-global by design (a real kill switch); tests
    that hit /api/scheduler/stop would otherwise poison every later fetch test."""
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    yield
    clear_kill_switch()
