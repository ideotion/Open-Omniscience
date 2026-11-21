"""Row 257 and R774: why an edition's article total is absent, or that one read earlier is no longer refreshed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The total is the walk's ``meta=siteinfo`` read. The bookmark keeps only the LAST refusal, so a batch refusal after a refused count read
would have taken its place; the count read's refusal is now recorded under its own history metric and read back by the coverage report.
R774: nothing but the opt-in walk reads a total, so a walk switched off says so, and a total read earlier is shown with its read date
as no longer refreshed. Never an empty or zero total that could read as a measurement.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import requests

from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import walk as W
from src.wiki.coverage import TOTAL_STATES, _total_state, edition_coverage
from src.wiki.lane_models import WikiLaneHour, WikiWalkCursor
from src.wiki.tiers import budget_state

EDITION = "oo"
T0 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    try:
        yield
    finally:
        dispose_all()


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _http(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status}", response=resp)


class Scripted:
    """Counts and batches answered from two lists: an exception or an answer."""

    def __init__(self, counts, batches=()):
        self.counts = list(counts)
        self.batches = list(batches)

    def fetch_edition_statistics(self, wiki):
        answer = self.counts.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def fetch_walk_batch(self, wiki, *, continue_params=None, limit=50):
        answer = self.batches.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return {"response_bytes": 100, **answer}


def _walker(client, clock):
    return W.WikiWalker(
        client=client, editions=(EDITION,), lane_session=lambda: lane_session("wiki"),
        budget=lambda: budget_state(total_gb=20, disk_bytes=0, editions=1),
        enabled=lambda: True, transport=lambda: "direct", batch=2, monotonic=clock,
    )


def _row(walk_enabled=True, walk_pause=None):
    with lane_session("wiki") as s:
        rep = edition_coverage(s, walk_enabled=walk_enabled, walk_pause=walk_pause)
    return next(r for r in rep["editions"] if r["edition"] == EDITION)


def test_a_refused_count_read_is_recorded_under_its_OWN_metric_and_named_by_the_report(lane):
    clock = Clock()
    walker = _walker(Scripted([_http(403)]), clock)
    walker.walk_for(3600, max_requests=1)
    with lane_session("wiki") as s:
        kinds = {(r.metric, r.kind) for r in s.query(WikiLaneHour).all()}
    assert (W.COUNT_READ_METRIC, W.WAIT_REFUSED) in kinds and ("walk", W.WAIT_REFUSED) in kinds
    note = _row()["edition_articles_read"]
    assert note["state"] == "not_read_refused" and note["reason"] == W.WAIT_REFUSED and note["at"]


def test_a_LATER_batch_refusal_never_overwrites_the_count_read_s_own_failure(lane):
    """The bookmark's last_error moves to the batch's token; the total's reason stays the count read's."""
    clock = Clock()
    walker = _walker(Scripted([_http(403)]), clock)
    walker.walk_for(3600, max_requests=1)
    with lane_session("wiki") as s:  # what a later batch refusal writes on the bookmark
        row = s.get(WikiWalkCursor, EDITION)
        row.last_error, row.last_error_at = W.WAIT_SERVICE_BUSY, T0
        s.commit()
    note = _row()["edition_articles_read"]
    assert note["last_refusal"] == W.WAIT_SERVICE_BUSY, "the bookmark's own last refusal is still given as what it is"
    assert (note["state"], note["reason"]) == ("not_read_refused", W.WAIT_REFUSED)


def test_a_count_read_that_later_SUCCEEDS_is_read_and_its_old_refusal_is_not_shown(lane):
    clock = Clock()
    walker = _walker(Scripted([_http(503), {"articles": 1234}], [{"pages": [], "continue": None, "complete": True,
                                                                     "props_complete": True, "error": None,
                                                                     "malformed": None, "skipped": 0}]), clock)
    walker.walk_for(3600, max_requests=1)
    clock.t += 3600 * 2
    walker.walk_for(3600, max_requests=1)
    r = _row()
    assert r["edition_articles"] == 1234
    assert r["edition_articles_read"]["state"] == "read" and r["edition_articles_read"]["reason"] is None


def test_airplane_mode_is_NAMED_and_writes_nothing_against_the_edition(lane):
    from src.ingest import activate_kill_switch, clear_kill_switch
    from src.wiki.client import WikiClient

    activate_kill_switch()
    try:
        walker = _walker(WikiClient(min_interval_s=0.0), Clock())
        walker.walk_for(3600)
    finally:
        clear_kill_switch()
    with lane_session("wiki") as s:
        assert not s.query(WikiLaneHour).filter(WikiLaneHour.metric == W.COUNT_READ_METRIC).count()
    note = _row(walk_pause=walker.reason)["edition_articles_read"]
    assert (note["state"], note["reason"]) == ("not_read_paused", W.PAUSED_NETWORK_OFF)


def test_an_answer_with_NO_count_is_said_as_such_never_as_not_read_yet(lane):
    walker = _walker(Scripted([{"malformed": "no-statistics"}], [{"pages": [], "continue": None, "complete": True,
                                                                  "props_complete": True, "error": None,
                                                                  "malformed": None, "skipped": 0}]), Clock())
    walker.walk_for(3600, max_requests=1)
    assert _row()["edition_articles_read"]["state"] == "answer_unreadable"


def test_R774_walk_OFF_never_read_and_read_earlier_no_longer_refreshed(lane):
    with lane_session("wiki") as s:
        s.add(WikiWalkCursor(edition=EDITION, pages_seen=10, started_at=T0, updated_at=T0))
        s.add(WikiWalkCursor(edition="de", pages_seen=5, edition_articles=900, edition_articles_read_at=T0,
                             started_at=T0, updated_at=T0))
        s.commit()
        rep = edition_coverage(s, walk_enabled=False)
    by = {r["edition"]: r for r in rep["editions"]}
    assert by[EDITION]["edition_articles"] is None, "no zero for a total that was never read"
    assert by[EDITION]["edition_articles_read"]["state"] == "not_read_walk_off"
    stale = by["de"]["edition_articles_read"]
    assert by["de"]["edition_articles"] == 900 and stale["state"] == "stale_walk_off" and stale["at"].startswith("2026-11-20")


def test_an_UNREAD_switch_is_neither_on_nor_off():
    assert _total_state(total=None, read_at=None, refusal=None, walk_enabled=None, walk_pause=None)["state"] == "unknown"
    # A total in hand is still shown as read; only its freshness depends on the switch.
    assert _total_state(total=5, read_at=T0, refusal=None, walk_enabled=None, walk_pause=None)["state"] == "read"


def test_every_state_the_report_can_give_is_one_the_surface_knows():
    import re
    from pathlib import Path

    js = Path("src/static/app-living.js").read_text(encoding="utf-8")
    body = js[js.index("function livingTotalWhy("):js.index("function livingWalkSwitchFact(")]
    named = set(re.findall(r'"([a-z_]+)"', body))
    # "read" and "not_read_yet" say nothing beyond the figure itself, on purpose.
    assert set(TOTAL_STATES) - {"read", "not_read_yet"} <= named


def test_the_living_overview_hands_the_walk_s_switch_and_pause_to_the_coverage_report(lane, monkeypatch):
    from src.api import living

    seen = {}

    def fake(lane_, **kw):
        seen.update(kw)
        return {"measured": False, "reason": "lane-never-run"}

    monkeypatch.setattr("src.wiki.coverage.edition_coverage", fake)
    living._wiki_coverage({"enabled": True, "state": "paused", "reason": W.PAUSED_TRANSPORT_UNAVAILABLE})
    assert seen == {"newest_gaps": False, "walk_enabled": True, "walk_pause": W.PAUSED_TRANSPORT_UNAVAILABLE,
                    "walk_running": True}
    living._wiki_coverage({"enabled": False, "state": "off", "reason": W.PAUSED_NETWORK_OFF})
    assert seen["walk_enabled"] is False and seen["walk_pause"] is None, "a reason without a pause is not a pause"
    living._wiki_coverage({"enabled": True, "state": "not_running", "reason": None})
    assert seen["walk_running"] is False and seen["walk_pause"] is None


def test_an_answer_with_no_count_stays_SAID_after_the_walk_is_switched_off():
    """It WAS read: "the page walk is off" would send the operator to a switch that would not bring a total back."""
    st = _total_state(total=None, read_at=T0, refusal=None, walk_enabled=False, walk_pause=None)
    assert st["state"] == "answer_unreadable" and st["at"].startswith("2026-11-20")


def test_a_walk_switched_ON_with_no_walker_running_says_so_never_nothing():
    st = _total_state(total=None, read_at=None, refusal=None, walk_enabled=True, walk_pause=None, walk_running=False)
    assert st["state"] == "not_read_not_running"
    # Unknown here (the diagnostics bundle): no claim either way.
    st = _total_state(total=None, read_at=None, refusal=None, walk_enabled=True, walk_pause=None, walk_running=None)
    assert st["state"] == "not_read_yet"


def test_the_disclosures_name_the_count_read():
    from pathlib import Path

    sec = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    assert "meta=siteinfo&siprop=statistics" in sec and "src/wiki/mediawiki.py:build_statistics_params" in sec
    html = Path("src/static/index.html").read_text(encoding="utf-8")
    assert "plus one request per edition for its article count" in html
    en = json.loads(Path("src/static/locales/en.json").read_text(encoding="utf-8"))
    assert "total not read: the page walk is off" in en
