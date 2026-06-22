"""The rolling error log carries honest, current-vs-stale session metadata.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

P0-5 (field test 2026-06-22): a 2026-06-22 debug bundle showed ONLY 2026-06-17
lock errors. The gate fix had already stopped them, but with no session boundary
in the log the maintainer read stale errors as live. ``install()`` now writes a
BOOT marker and ``summary()`` reports problems/lock-errors SINCE the latest boot,
so a clean current session is provably distinguishable from "logging is broken".
"""

from __future__ import annotations

import importlib
import logging

import src.monitoring.errorlog as errorlog


def _fresh(monkeypatch, tmp_path):
    """Point the log at a tmp file and reset module state for an isolated run."""
    monkeypatch.setattr(errorlog, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    errorlog._installed = False
    # Detach any handler a prior test/install left on the root logger.
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, errorlog._JsonlErrorHandler):
            root.removeHandler(h)


def test_install_writes_a_boot_marker(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    errorlog.install()
    recs = errorlog.recent_errors()
    assert any(r.get("level") == errorlog._BOOT_LEVEL for r in recs), "no session-start marker"
    s = errorlog.summary()
    assert s["last_session_started_at"] is not None
    assert s["problems_this_session"] == 0  # a fresh boot has no problems yet


def test_summary_counts_problems_since_the_latest_boot(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    # Simulate a PAST session that hit a lock, then a fresh boot with no problems.
    errorlog._append(
        {
            "at": "2026-06-17T10:00:00+00:00",
            "level": "ERROR",
            "logger": "src.ingest.pipeline",
            "message": "keyword indexing on ingest failed",
            "traceback_tail": "OperationalError: database is locked",
        }
    )
    errorlog.note_boot()  # the new session starts AFTER the stale error

    s = errorlog.summary()
    assert s["locked_errors_total"] == 1, "the stale lock error should still be visible"
    assert s["locked_errors_this_session"] == 0, "no lock error occurred THIS session"
    assert s["problems_this_session"] == 0, "the stale error must not read as live"
    assert s["last_at"] >= s["last_session_started_at"]


def test_summary_flags_a_lock_error_in_the_current_session(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    errorlog.note_boot()
    errorlog._append(
        {
            "at": "2026-06-22T12:00:00+00:00",
            "level": "ERROR",
            "logger": "src.ingest.pipeline",
            "message": "x",
            "traceback_tail": "OperationalError: database is locked",
        }
    )
    s = errorlog.summary()
    assert s["locked_errors_this_session"] == 1
    assert s["problems_this_session"] == 1


def test_empty_log_is_honest(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    s = errorlog.summary()
    assert s["records"] == 0
    assert s["problems_total"] == 0
    assert "note" in s


def test_module_imports_clean():
    importlib.reload(errorlog)  # no import-time side effects
