"""The monitoring records and log lines that took an exception's words carry no held passphrase (sink sweep, PR 2).

Each case fails the way an engine does when it quotes what it was handed, with the unlocked session's passphrase in the
text, and reads back what the code wrote: the returned record and every log record (message and attached traceback). The
source-level guard is ``tests/test_no_raw_exc_info.py``; these pin the behaviour of the converted sites.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from src.monitoring import activity_ledger, ai_diagnostics, preflight, secret_scrub

_PW = "corpus'key\"two\\y"


def _boom(*_a, **_k):
    raise RuntimeError(f"driver said: {_PW} and {_PW.replace(chr(39), chr(39) * 2)}")


@pytest.fixture(autouse=True)
def _held_passphrase(monkeypatch):
    monkeypatch.setattr("src.database.connect._passphrase", _PW)


def _written(caplog) -> str:
    return caplog.text + "\n".join(
        str(getattr(r, secret_scrub.TRACEBACK_ATTRIBUTE, "")) for r in caplog.records
    )


def test_debug_failure_line_is_scrubbed_and_carries_no_exc_info(monkeypatch, caplog):
    monkeypatch.setattr(activity_ledger, "build_entry", _boom)
    with caplog.at_level(logging.DEBUG):
        assert activity_ledger.record("x") is None
    assert caplog.records and all(r.exc_info is None for r in caplog.records)
    assert _PW not in _written(caplog)
    assert "RuntimeError" in caplog.text


def test_debug_failure_is_not_built_when_debug_is_off(monkeypatch, caplog):
    """A disabled level costs nothing: the traceback is not made for a line nobody will read."""
    monkeypatch.setattr(activity_ledger, "build_entry", _boom)
    with caplog.at_level(logging.ERROR):
        assert activity_ledger.record("x") is None
    assert not caplog.records


def test_section_error_record_is_scrubbed():
    out = ai_diagnostics._safe(_boom)
    assert (
        out["section_ok"] is False
        and _PW not in out["error"]
        and "RuntimeError" not in out["error"]
        or _PW not in out["error"]
    )


def test_preflight_robots_error_is_scrubbed():
    fetcher = SimpleNamespace(_guard_target=_boom)
    rec = preflight._check_one(fetcher, SimpleNamespace(id=1, domain="example.org"))
    assert rec["robots_error"] and _PW not in rec["robots_error"]
    assert not any(_PW in str(v) for v in rec.values())
