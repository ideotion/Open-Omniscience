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
    errorlog._http_last.clear()  # reset the cross-test HTTP-error throttle state
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
    # The error's `at` must be AFTER the boot marker, which note_boot() stamps with
    # the REAL wall clock — so a hardcoded "12:00" was brittle (it passed only when
    # the suite ran before noon UTC; it flaked the macOS lane that ran at 13:27).
    # A far-future timestamp is unambiguously "this session" regardless of run time.
    errorlog._append(
        {
            "at": "2099-12-31T23:59:59+00:00",
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
    assert s["http_errors_total"] == 0
    assert s["http_status_breakdown"] == {}
    assert "note" in s


def test_http_error_is_recorded_and_counted(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    errorlog.note_boot()
    errorlog.note_http_error("POST", "/api/backup/v2/volumes/start", 404)
    errorlog.note_http_error("GET", "/api/something", 500)

    recs = errorlog.recent_errors()
    http = [r for r in recs if r.get("level") == errorlog._HTTP_LEVEL]
    assert len(http) == 2
    assert {r["status"] for r in http} == {404, 500}
    assert any("404" in r["message"] and "volumes/start" in r["message"] for r in http)

    s = errorlog.summary()
    assert s["http_errors_total"] == 2
    assert s["http_errors_this_session"] == 2
    assert s["http_status_breakdown"] == {"404": 1, "500": 1}
    # An error RESPONSE is not, by itself, an app fault: it must NOT inflate the
    # problem/lock counts the data-loss signal relies on.
    assert s["problems_total"] == 0
    assert s["problems_this_session"] == 0


def test_http_error_duplicates_are_throttled(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    # Identical (method, path, status) hammered by a poll loop collapses to one
    # record within the throttle window; a DIFFERENT status is still captured.
    for _ in range(50):
        errorlog.note_http_error("GET", "/api/scheduler/activity", 503)
    errorlog.note_http_error("GET", "/api/scheduler/activity", 500)

    http = [r for r in errorlog.recent_errors() if r.get("level") == errorlog._HTTP_LEVEL]
    assert len(http) == 2, "duplicate 503s should be throttled to one; the 500 is distinct"
    assert {r["status"] for r in http} == {503, 500}


def test_http_error_never_raises(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    # A broken append must be swallowed — diagnostics can never break the app.
    monkeypatch.setattr(errorlog, "_append", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
    errorlog.note_http_error("GET", "/api/x", 500)  # must not raise


def test_module_imports_clean():
    importlib.reload(errorlog)  # no import-time side effects


def test_htmldate_cache_clear_noise_is_filtered_out(monkeypatch, tmp_path):
    """S5 item 1 (field-feedback 2026-07-23): htmldate.meta.reset_caches() (reached
    via trafilatura's own reset_caches() at every pass boundary) logs an ERROR every
    time it hits an AttributeError on charset_normalizer's functions in the installed
    version pin — measured 85 of 93 "problems" on one field session. That ONE known
    message class from that ONE logger must be filtered out of the counters, without
    blanket-suppressing the logger (a genuinely different message from the same
    logger, e.g. an import failure, must still count)."""
    _fresh(monkeypatch, tmp_path)
    errorlog.install()
    noisy = logging.getLogger("htmldate.meta")
    for _ in range(85):
        noisy.error("impossible to clear cache for function: %s", "AttributeError('x')")
    # A genuinely different message from the SAME logger must still be captured —
    # this is a targeted filter, not a blanket suppression of htmldate.meta.
    noisy.error("impossible to import charset function name")

    recs = errorlog.recent_errors()
    problem_msgs = [r["message"] for r in recs if r.get("level") in errorlog._PROBLEM_LEVELS]
    assert not any("impossible to clear cache for function" in m for m in problem_msgs)
    assert any("impossible to import charset function name" in m for m in problem_msgs)

    s = errorlog.summary()
    assert s["problems_this_session"] == 1  # only the import-failure message counts


def test_htmldate_noise_filter_leaves_other_loggers_untouched(monkeypatch, tmp_path):
    """The filter matches on LOGGER NAME too — an unrelated logger emitting a
    similar-looking message must still be counted (never a bare message-substring
    match that could mask a real fault in our own code)."""
    _fresh(monkeypatch, tmp_path)
    errorlog.install()
    logging.getLogger("src.some.other.module").error(
        "impossible to clear cache for function: our own bug"
    )
    s = errorlog.summary()
    assert s["problems_this_session"] == 1
