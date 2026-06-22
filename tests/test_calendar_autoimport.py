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
    # The whole FETCHABLE directory is due on a fresh machine — robots-disallowed
    # hosts (google-hol/webcal, ~254 feeds) are excluded from the auto round-robin.
    assert r1["due"] >= 200
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


def test_robots_disallowed_hosts_excluded_from_auto_import_but_stay_listed():
    """Field test 2026-06-22: ~238 robots-dead google-hol feeds sort BEFORE the working
    wph feeds, so the round-robin attempted dead feeds for many passes. The auto-import
    must skip the field-verified robots-disallowed hosts — but they STAY in the directory
    (the UI shows them with their honest verdict; the operator can still import manually)."""
    from urllib.parse import urlparse

    # The dead hosts are still LISTED (load_families is untouched).
    listed_hosts = {
        urlparse(fd["url"]).netloc
        for fam in F.load_families()
        for fd in fam["feeds"]
    }
    assert F._AUTO_IMPORT_SKIP_HOSTS <= listed_hosts  # they ARE in the catalog

    # But the auto-import round-robin never picks a feed on those hosts. Drain a LOT of
    # batches (more than enough to reach the working feeds) and assert no dead host fired.
    f = _StubFetcher(ICS)
    fetched_hosts: set[str] = set()
    real_fetch = f.fetch

    def _track(url, *, require_html=True):
        fetched_hosts.add(urlparse(url).netloc)
        return real_fetch(url, require_html=require_html)

    f.fetch = _track
    for _ in range(60):  # 60 * 8 = 480 picks — covers the whole fetchable directory
        F.auto_import_due_feeds(f, batch=8)
    assert fetched_hosts, "the auto-import should have fetched SOME feeds"
    assert not (fetched_hosts & F._AUTO_IMPORT_SKIP_HOSTS), (
        f"auto-import fetched a robots-disallowed host: {fetched_hosts & F._AUTO_IMPORT_SKIP_HOSTS}"
    )
    # The working WorldPublicHoliday host IS reached (not starved by the dead feeds).
    assert "worldpublicholiday.com" in fetched_hosts
