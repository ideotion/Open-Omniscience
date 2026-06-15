"""Continuous calendar auto-import (Item E, ruled 2026-06-15 "auto-import
everything"): a BOUNDED, polite, round-robin batch per pass so every bundled feed
is eventually covered without hammering. Best-effort + idempotent + per-feed
backoff; the kill switch / robots / politeness ride the shared fetcher.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.events import feeds as F

ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nUID:x1\r\nDTSTART;VALUE=DATE:20260714\r\nSUMMARY:Bastille Day\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


@dataclass
class _Result:
    content: str


class _StubFetcher:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def fetch(self, url, *, require_html=True):
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return _Result(content=self.payload)


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def test_bounded_batch_and_roundrobin():
    f = _StubFetcher(ICS)
    r1 = F.auto_import_due_feeds(f, batch=3)
    assert r1["picked"] == 3 and r1["imported"] == 3
    assert r1["due"] >= 400          # the whole bundled directory is "due" on a fresh machine
    assert f.calls == 3              # bounded: exactly `batch` fetches, never all 500
    # A second pass skips the just-imported feeds (backoff) and covers DIFFERENT ones.
    r2 = F.auto_import_due_feeds(f, batch=3)
    assert r2["picked"] == 3 and r2["imported"] == 3
    assert r2["due"] == r1["due"] - 3   # three fewer feeds are now due
    assert f.calls == 6


def test_backoff_recently_imported_skipped():
    f = _StubFetcher(ICS)
    F.auto_import_due_feeds(f, batch=5)
    # Immediately re-running with a long interval imports the NEXT feeds, never repeats.
    before = f.calls
    F.auto_import_due_feeds(f, batch=5, min_interval_hours=12)
    assert f.calls == before + 5     # 5 new feeds, none of the first 5 retried


def test_failure_does_not_abort_batch_and_backs_off():
    f = _StubFetcher(RuntimeError("blocked"))
    r = F.auto_import_due_feeds(f, batch=4)
    assert r["picked"] == 4 and r["imported"] == 0 and r["failed"] == 4
    # the failed feeds were still timestamped, so they back off (not retried next pass)
    r2 = F.auto_import_due_feeds(f, batch=4, min_interval_hours=12)
    assert r2["picked"] == 4         # the NEXT four, not the same four
