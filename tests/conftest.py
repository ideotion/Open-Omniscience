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

import os
import tempfile

_ISOLATED = tempfile.mkdtemp(prefix="oo-tests-")
os.environ.setdefault("OO_DATA_DIR", _ISOLATED)
# Never autostart the background scraper thread during tests.
os.environ.setdefault("OO_NO_SCHEDULER", "1")
