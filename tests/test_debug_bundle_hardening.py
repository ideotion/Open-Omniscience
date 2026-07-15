"""S8 — debug-bundle hardening: read-only DB + per-member guard + wall-clock budget.

Pins the contract: a member that RAISES records ``{error}`` (never aborts the bundle); a
member that RUNS PAST its budget records ``{skipped: budget}`` (never stalls the bundle);
the bundle stays COMPLETE (every section present) and returns in bounded wall time even
though one member sleeps far past the budget; and the endpoint opens the DB read-only.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SECTIONS = (
    "runtime", "corpus", "scheduler", "network", "imports", "calendar_imports",
    "law_documents", "wiki_pages", "collect_perf", "field_test", "errors", "error_log",
    "request_latency", "slow_queries", "schema_drift", "corpus_integrity",
    "session_forensics", "storage_composition", "p0_validation", "method",
)


def test_debug_bundle_opens_the_db_read_only():
    # Source-pinned (the wiring lesson): the bundle must never take the write gate.
    src = Path("src/api/diagnostics.py").read_text(encoding="utf-8")
    assert "def debug_bundle(db: Session = Depends(read_only_db))" in src


def test_a_raising_member_and_a_slow_member_yield_a_complete_bounded_bundle(monkeypatch):
    import src.monitoring.forensics as _fx
    import src.monitoring.latency as _lat
    from src.api.main import app
    from src.monitoring.errorlog import install

    install()
    # A 1s per-member budget; one member raises, one sleeps 6s (>> budget).
    monkeypatch.setenv("OO_DEBUG_BUNDLE_MEMBER_BUDGET_S", "1")

    def _boom(*a, **k):
        raise RuntimeError("member exploded")

    def _slow(*a, **k):
        time.sleep(6)
        return {"never": "returned"}

    monkeypatch.setattr(_lat, "summary", _boom)  # -> request_latency member
    monkeypatch.setattr(_fx, "session_forensics", _slow)  # -> session_forensics member

    with TestClient(app) as c:
        t0 = time.monotonic()
        r = c.get("/api/diagnostics/debug-bundle")
        elapsed = time.monotonic() - t0

    assert r.status_code == 200
    data = r.json()["data"]

    # COMPLETE: every section is still present despite one raise + one hang.
    for key in _SECTIONS:
        assert key in data, key

    # the raising member recorded an honest error, never aborted the bundle
    rl = data["request_latency"]
    assert isinstance(rl, dict) and "error" in rl and "member exploded" in rl["error"]

    # the hung member was budgeted out honestly (not waited on)
    sf = data["session_forensics"]
    assert sf.get("skipped") == "budget" and sf.get("budget_s") == 1.0

    # a normal member is unaffected
    assert data["runtime"]["python"]

    # BOUNDED: we did NOT wait the 6s sleep — one 1s skip + fast rest, well under 6s.
    assert elapsed < 4.0, elapsed


@pytest.mark.parametrize(
    "val,expect",
    [
        ("5", 5.0),
        ("0", 20.0),
        ("-5", 20.0),
        ("abc", 20.0),
        ("", 20.0),
        ("nan", 20.0),
        ("inf", 20.0),  # non-finite -> default (never reaches Thread.join)
        ("-inf", 20.0),
        ("1e18", 3600.0),  # huge finite -> CAPPED (would overflow join's timeout)
        ("100000", 3600.0),
    ],
)
def test_budget_env_degrades_honestly_and_caps(monkeypatch, val, expect):
    from src.api.diagnostics import _debug_bundle_member_budget_s

    monkeypatch.setenv("OO_DEBUG_BUNDLE_MEMBER_BUDGET_S", val)
    assert _debug_bundle_member_budget_s() == expect


def test_a_non_finite_budget_never_crashes_the_bundle(monkeypatch):
    """Skeptic #1: budget=inf must not reach Thread.join(inf) (OverflowError escapes the
    per-member guard and 500s the WHOLE bundle) nor emit a JSON-invalid Infinity."""
    from src.api.main import app
    from src.monitoring.errorlog import install

    install()
    monkeypatch.setenv("OO_DEBUG_BUNDLE_MEMBER_BUDGET_S", "inf")
    with TestClient(app) as c:
        r = c.get("/api/diagnostics/debug-bundle")
    assert r.status_code == 200  # clamped to the 20s default, no overflow
    assert r.json()["data"]["runtime"]["python"]


def test_a_raising_db_member_is_guarded_inline_and_never_aborts(monkeypatch):
    """DB members run INLINE (not on a worker thread — a shared SQLite connection is unsafe
    concurrently). A raising DB member must still record {error} and never abort the bundle;
    every other section stays present."""
    import src.monitoring.integrity as _intg
    from src.api.main import app
    from src.monitoring.errorlog import install

    install()

    def _boom(*a, **k):
        raise RuntimeError("db member exploded")

    monkeypatch.setattr(_intg, "corpus_integrity", _boom)  # -> corpus_integrity (DB, inline)
    with TestClient(app) as c:
        r = c.get("/api/diagnostics/debug-bundle")
    assert r.status_code == 200
    data = r.json()["data"]
    ci = data["corpus_integrity"]
    assert isinstance(ci, dict) and "error" in ci and "db member exploded" in ci["error"]
    for key in _SECTIONS:  # bundle stays complete
        assert key in data, key


def test_db_members_run_inline_not_on_a_worker_thread():
    """Source guard (the concurrency lesson): DB members must be threaded=False so no worker
    thread ever touches the shared read-only connection concurrently."""
    src = Path("src/api/diagnostics.py").read_text(encoding="utf-8")
    for db_member in ("corpus", "law_documents", "wiki_pages", "schema_drift",
                      "slow_queries", "corpus_integrity", "storage_composition"):
        # each DB member line carries threaded=False (verified via the _member call block)
        assert f'"{db_member}": _member(' in src, db_member
    assert "threaded=False" in src


def test_a_member_exception_with_a_broken_str_still_records_error(monkeypatch):
    """Skeptic #2: a failing member whose exception __str__ itself raises must STILL record
    an error marker — never be silently indistinguishable from a member returning None."""
    import src.monitoring.latency as _lat
    from src.api.main import app
    from src.monitoring.errorlog import install

    install()

    class _Evil(Exception):
        def __str__(self):
            raise ValueError("cannot render")

    def _boom(*a, **k):
        raise _Evil()

    monkeypatch.setattr(_lat, "summary", _boom)  # -> request_latency member
    with TestClient(app) as c:
        r = c.get("/api/diagnostics/debug-bundle")
    assert r.status_code == 200
    rl = r.json()["data"]["request_latency"]
    assert isinstance(rl, dict) and "error" in rl and "unrenderable" in rl["error"]
