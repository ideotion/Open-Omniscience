"""
Calendar feed directory: catalog integrity, ICS parsing, family dedup, API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-supplied aggregation (2026-06-10): ~500 feeds bundled as CANDIDATES;
duplicates grouped into families (shown, never hidden); verify/import are
explicit operator actions; imported events dedup within a family by
(normalized title, date) while every source stays listed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.events import feeds as F

ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nUID:a1\r\nDTSTART;VALUE=DATE:20260714\r\n"
    "SUMMARY:Bastille Day\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:a2\r\nDTSTART:20261225T000000Z\r\n"
    "SUMMARY:Christmas\\, Day\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:bad\r\nSUMMARY:No date -> skipped\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


# --------------------------------------------------------------------------- #
#  Bundled catalog integrity
# --------------------------------------------------------------------------- #
def test_catalog_families_and_duplicates():
    fams = F.load_families()
    assert len(fams) >= 250, "the aggregated directory should be fully integrated"
    ids = [fd["id"] for fam in fams for fd in fam["feeds"]]
    assert len(ids) == len(set(ids)), "feed ids must be unique"
    # The duplication is the point: most country families carry BOTH providers.
    multi = [f for f in fams if len(f["feeds"]) > 1]
    assert len(multi) >= 200
    fr = next(f for f in fams if f["key"] == "holidays-fr")
    assert {fd["provider"] for fd in fr["feeds"]} == {"Google Calendar", "WorldPublicHoliday"}
    assert all(fd["url"].startswith(("http://", "https://")) for fam in fams for fd in fam["feeds"])


def test_directory_status_shape():
    status = F.directory_status()
    assert status["total_feeds"] >= 490
    assert status["catalog_as_of"] == "2026-06"
    assert any(d["name"] == "Nager.Date" for d in status["directory_only"])


# --------------------------------------------------------------------------- #
#  Tolerant ICS parsing (defensive: skip, never guess)
# --------------------------------------------------------------------------- #
def test_parse_ics_events_and_skips():
    events = F.parse_ics(ICS)
    assert [e["date"] for e in events] == ["2026-07-14", "2026-12-25"]
    assert events[1]["title"] == "Christmas, Day"  # RFC escaping unescaped
    assert all(e.get("uid") for e in events)


def test_parse_ics_rejects_non_calendar():
    assert F.parse_ics("<html>not a calendar</html>") == []
    assert F.parse_ics("") == []


# --------------------------------------------------------------------------- #
#  Verify + import via a stub fetcher (no network in tests, ever)
# --------------------------------------------------------------------------- #
@dataclass
class _Result:
    content: str


class _StubFetcher:
    def __init__(self, payload):
        self.payload = payload

    def fetch(self, url, *, require_html=True):
        if isinstance(self.payload, Exception):
            raise self.payload
        return _Result(content=self.payload)


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def test_verify_records_honest_verdicts():
    v = F.verify_feed(_StubFetcher(ICS), "google-hol-fr")
    assert v["status"] == "ok" and v["events"] == 2
    v2 = F.verify_feed(_StubFetcher("<html></html>"), "wph-hol-fr")
    assert v2["status"] == "not_ical"
    # WPH is year-pinned 2026: not stale today, so no false alarm.
    assert "stale_year" not in v2
    v3 = F.verify_feed(_StubFetcher(RuntimeError("boom")), "floern-launches")
    assert v3["status"] == "unreachable" and "boom" in v3["error"]
    assert set(F.load_verdicts()) == {"google-hol-fr", "wph-hol-fr", "floern-launches"}


def test_import_dedups_within_family_keeping_all_sources():
    r1 = F.import_feed(_StubFetcher(ICS), "google-hol-fr")
    assert r1["added"] == 2 and r1["family"] == "holidays-fr"
    # The second provider carries the same two events -> merged, both sources listed.
    r2 = F.import_feed(_StubFetcher(ICS), "wph-hol-fr")
    assert r2["added"] == 0 and r2["merged_into_existing"] == 2
    events = F.imported_agenda(family="holidays-fr")
    assert len(events) == 2
    assert all(set(e["sources"]) == {"google-hol-fr", "wph-hol-fr"} for e in events)
    # A different date for the "same" title stays a SEPARATE entry (disagreement shown).
    other = ICS.replace("20260714", "20260715")
    F.import_feed(_StubFetcher(other), "wph-hol-fr")
    titles = [(e["title"], e["date"]) for e in F.imported_agenda(family="holidays-fr")]
    assert ("Bastille Day", "2026-07-14") in titles and ("Bastille Day", "2026-07-15") in titles


def test_feed_api_shapes():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.get("/api/events/feeds")
        assert r.status_code == 200
        body = r.json()
        assert body["total_feeds"] >= 490
        assert any(f["duplicates"] for f in body["families"])
        assert c.post("/api/events/feeds/nope/verify").status_code == 404
        r2 = c.get("/api/events/imported")
        assert r2.status_code == 200 and "events" in r2.json()
