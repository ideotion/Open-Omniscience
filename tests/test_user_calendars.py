"""User-uploaded .ics calendars (Item E, 2026-06-15): add a calendar by uploading a
local .ics (NO network), removable and reversible. Reuses the import dedup + the
per-machine imports store, so events join the agenda like any imported feed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.events import feeds as F

ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nUID:u1\r\nDTSTART;VALUE=DATE:20260714\r\nSUMMARY:Bastille Day\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:u2\r\nDTSTART:20261225T000000Z\r\nSUMMARY:Christmas\\, Day\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def test_import_ics_text_adds_user_family():
    r = F.import_ics_text("My Holidays", ICS)
    assert r["family"] == "user-my-holidays" and r["added"] == 2 and r["events_in_file"] == 2
    ev = F.imported_agenda(family="user-my-holidays")
    assert {e["title"] for e in ev} == {"Bastille Day", "Christmas, Day"}
    users = F.list_user_feeds()
    assert any(f["key"] == "user-my-holidays" and f["events"] == 2 for f in users)


def test_import_ics_idempotent_dedup():
    F.import_ics_text("Cal", ICS)
    r2 = F.import_ics_text("Cal", ICS)
    assert r2["added"] == 0 and r2["family_total"] == 2


def test_remove_user_feed_is_reversible():
    F.import_ics_text("Temp", ICS)
    out = F.remove_user_feed("user-temp")
    assert out["removed"] == "user-temp" and out["events"] == 2
    assert F.list_user_feeds() == []
    F.import_ics_text("Temp", ICS)            # re-import restores it
    assert len(F.list_user_feeds()) == 1


def test_remove_refuses_non_user_family():
    with pytest.raises(KeyError):
        F.remove_user_feed("holidays-fr")     # a bundled family is never deletable here


def test_import_ics_rejects_oversize():
    big = "BEGIN:VCALENDAR\r\n" + ("X" * (5 * 1024 * 1024 + 10))
    with pytest.raises(ValueError):
        F.import_ics_text("Big", big)


def test_blank_name_defaults():
    r = F.import_ics_text("", ICS)
    assert r["family"] == "user-calendar" and r["name"] == "My calendar"


class _UrlResult:
    def __init__(self, content):
        self.content = content


class _UrlFetcher:
    def __init__(self, payload):
        self.payload = payload
        self.url = None

    def fetch(self, url, *, require_html=True):
        self.url = url
        return _UrlResult(self.payload)


def test_import_ics_url_normalizes_webcal_and_imports():
    f = _UrlFetcher(ICS)
    r = F.import_ics_url(f, "webcal://example.org/cal.ics", "Web Cal")
    assert f.url == "https://example.org/cal.ics"   # webcal:// -> https://
    assert r["added"] == 2 and r["family"] == "user-web-cal"
    assert any(x["key"] == "user-web-cal" for x in F.list_user_feeds())


def test_import_ics_url_rejects_non_http_without_fetching():
    class _Never:
        def fetch(self, url, **k):
            raise AssertionError("must never fetch a non-http(s) scheme")

    with pytest.raises(ValueError):
        F.import_ics_url(_Never(), "ftp://x/y.ics", "X")
