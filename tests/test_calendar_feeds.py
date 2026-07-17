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
def test_catalog_families_and_are_dead_host_free():
    from urllib.parse import urlparse

    fams = F.load_families()
    assert len(fams) >= 200, "the aggregated directory should be fully integrated"
    ids = [fd["id"] for fam in fams for fd in fam["feeds"]]
    assert len(ids) == len(set(ids)), "feed ids must be unique"
    # B7 / finding E: the robots-dead default hosts (Google's dead "second source",
    # webcal.guru, cantonbecker, floern) are filtered OUT of the loaded directory —
    # an honest single-provider default set, no fake corroboration.
    hosts = {urlparse(fd["url"]).netloc for fam in fams for fd in fam["feeds"]}
    assert not (hosts & F._DEAD_DEFAULT_HOSTS), f"a robots-dead host leaked into the directory: {hosts & F._DEAD_DEFAULT_HOSTS}"
    fr = next(f for f in fams if f["key"] == "holidays-fr")
    assert {fd["provider"] for fd in fr["feeds"]} == {"WorldPublicHoliday"}
    assert all(fd["url"].startswith(("http://", "https://")) for fam in fams for fd in fam["feeds"])


def test_directory_status_shape():
    status = F.directory_status()
    assert status["total_feeds"] >= 200  # ~242 working single-provider feeds after the dead-host filter
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
    # Fixtures use WORKING feeds (the dead google/floern feeds are filtered out now;
    # monkeyness-moons is retired as REDUNDANT vs the computed astronomy layer).
    v = F.verify_feed(_StubFetcher(ICS), "wph-hol-fr")
    assert v["status"] == "ok" and v["events"] == 2
    v2 = F.verify_feed(_StubFetcher("<html></html>"), "wph-hol-de")
    assert v2["status"] == "not_ical"
    v3 = F.verify_feed(_StubFetcher(RuntimeError("boom")), "ose-calendar")
    assert v3["status"] == "unreachable" and "boom" in v3["error"]
    assert set(F.load_verdicts()) == {"wph-hol-fr", "wph-hol-de", "ose-calendar"}


def test_verify_rejects_a_filtered_dead_feed():
    # A robots-dead default feed is no longer in the loaded directory -> not verifiable.
    assert F.feed_by_id("google-hol-fr") is None
    with pytest.raises(KeyError):
        F.verify_feed(_StubFetcher(ICS), "google-hol-fr")


def test_import_dedups_within_family_keeping_all_sources(monkeypatch):
    # After the dead-host filter no bundled family carries two providers, so drive the
    # cross-provider dedup logic with a two-feed fixture family (decoupled from the catalog).
    fam = {
        "key": "holidays-fr",
        "name": "France — public holidays",
        "kind": "holidays",
        "country": "FR",
        "feeds": [
            {"id": "wph-hol-fr", "provider": "WorldPublicHoliday", "url": "https://worldpublicholiday.com/x.ics"},
            {"id": "alt-hol-fr", "provider": "Alt", "url": "https://example.org/fr.ics"},
        ],
    }
    monkeypatch.setattr(F, "load_families", lambda: [fam])
    monkeypatch.setattr(F, "feed_by_id", lambda fid: next(((fam, fd) for fd in fam["feeds"] if fd["id"] == fid), None))

    r1 = F.import_feed(_StubFetcher(ICS), "wph-hol-fr")
    assert r1["added"] == 2 and r1["family"] == "holidays-fr"
    # The second provider carries the same two events -> merged, both sources listed.
    r2 = F.import_feed(_StubFetcher(ICS), "alt-hol-fr")
    assert r2["added"] == 0 and r2["merged_into_existing"] == 2
    events = F.imported_agenda(family="holidays-fr")
    assert len(events) == 2
    assert all(set(e["sources"]) == {"wph-hol-fr", "alt-hol-fr"} for e in events)
    # A different date for the "same" title stays a SEPARATE entry (disagreement shown).
    other = ICS.replace("20260714", "20260715")
    F.import_feed(_StubFetcher(other), "alt-hol-fr")
    titles = [(e["title"], e["date"]) for e in F.imported_agenda(family="holidays-fr")]
    assert ("Bastille Day", "2026-07-14") in titles and ("Bastille Day", "2026-07-15") in titles


def test_feed_api_shapes():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.get("/api/events/feeds")
        assert r.status_code == 200
        body = r.json()
        assert body["total_feeds"] >= 200  # ~242 working feeds after the dead-host filter
        # No family carries a duplicate provider now (the dead Google "second source" is gone).
        assert all(not f["duplicates"] for f in body["families"])
        assert c.post("/api/events/feeds/nope/verify").status_code == 404
        r2 = c.get("/api/events/imported")
        assert r2.status_code == 200 and "events" in r2.json()


def test_redundant_moons_feed_is_retired_and_its_ghosts_filtered():
    """Maintainer field report 2026-07-17 (three moon states on one day): the
    Moons-Seasons ICS duplicated the computed Meeus astronomy layer (method +
    accuracy stated in-app) with no stated method. Retired as REDUNDANT — out of
    the directory and the auto-import round-robin — and already-imported events
    attributed solely to it are filtered at read time (a mixed-source event just
    loses the retired id, never the event)."""
    ids = {f["id"] for fam in F.load_families() for f in fam["feeds"]}
    assert "monkeyness-moons" not in ids
    assert F.feed_by_id("monkeyness-moons") is None

    F._save_json("calendar_feed_imports.json", {
        "astral": {"name": "Astronomy", "events": {
            "fp1": {"title": "Full Moon", "date": "2024-07-21",
                    "sources": ["monkeyness-moons"]},
            "fp2": {"title": "March Equinox", "date": "2026-03-20",
                    "sources": ["monkeyness-moons", "ose-calendar"]},
        }},
    })
    evs = F.load_imports()["astral"]["events"]
    assert "fp1" not in evs, "a solely-retired-sourced ghost must not surface"
    assert evs["fp2"]["sources"] == ["ose-calendar"], "mixed-source keeps the live provider"
