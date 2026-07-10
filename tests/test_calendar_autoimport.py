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
    # The whole directory is due on a fresh machine — the robots-dead default hosts
    # (google/webcal/cantonbecker/floern) are filtered out of load_families entirely.
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


def test_robots_dead_default_hosts_are_filtered_from_the_directory():
    """B7 / field finding E: the robots-dead default hosts (the dead Google "second
    source" beside every WPH feed, webcal.guru, cantonbecker, floern) are filtered OUT
    of the loaded directory entirely, so they can never be listed, previewed, or
    auto-imported — an honest single-provider default set. (Field test 2026-06-22 first
    just SKIPPED them in the round-robin; now they are gone from load_families.)"""
    from urllib.parse import urlparse

    # The dead hosts are NOT in the loaded directory.
    listed_hosts = {
        urlparse(fd["url"]).netloc
        for fam in F.load_families()
        for fd in fam["feeds"]
    }
    assert not (listed_hosts & F._DEAD_DEFAULT_HOSTS), (
        f"a robots-dead host leaked into the directory: {listed_hosts & F._DEAD_DEFAULT_HOSTS}"
    )

    # And the auto-import round-robin never fetches one (trivially, since none is listed).
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
    assert not (fetched_hosts & F._DEAD_DEFAULT_HOSTS)
    # The working WorldPublicHoliday host IS reached.
    assert "worldpublicholiday.com" in fetched_hosts
