"""S06-03 S1 + S3: the per-edition Wikipedia coverage report, on a temp lane.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The spine is what the report must never do: invent a number for an edition that never ran,
score or bar a share, count a located address that no extractor produced, or lose the last
known edition total when the siteinfo read fails.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.versioned.models import VersionedChange, VersionedEntity, VersionedGap, VersionedRevision
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki.counters import lane_counters
from src.wiki.coverage import TWELVE, edition_coverage
from src.wiki.lane_models import WikiWalkCursor, WikiWarmEdition

T0 = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    try:
        with lane_session("wiki") as s:
            yield s
    finally:
        dispose_all()


def _row(rep, edition):
    return next(r for r in rep["editions"] if r["edition"] == edition)


def _hot(s, edition, ext, text):
    e = VersionedEntity(external_id=ext, language=edition)
    s.add(e)
    s.flush()
    s.add(
        VersionedRevision(
            entity_id=e.id,
            revision_ref="1",
            content_hash="h",
            content=text,
            byte_size=len(text or ""),
        )
    )


def test_fresh_lane_lists_twelve_editions_as_no_run_yet(lane):
    rep = edition_coverage(lane, now=T0)
    assert rep["measured"] is False and rep["reason"] == "lane-never-run"
    assert [r["edition"] for r in rep["editions"]][:12] == list(TWELVE)
    assert len(TWELVE) == 12
    for r in rep["editions"]:
        assert r["has_run"] is False and r["reason"] == "no-run-yet"
        assert r["pages_seen"] is None and r["pages_seen_share"] is None


def test_share_is_two_counts_and_may_pass_100(lane):
    lane.add(
        WikiWalkCursor(
            edition="en", pages_seen=150, edition_articles=100, started_at=T0, updated_at=T0
        )
    )
    lane.commit()
    r = _row(edition_coverage(lane, now=T0), "en")
    assert r["pages_seen"] == 150 and r["edition_articles"] == 100
    assert r["pages_seen_share"] == pytest.approx(1.5)
    assert "score" not in r and "bar" not in r


def test_full_text_bounds_count_hot_and_warm_and_ignore_textless(lane):
    lane.add(WikiWalkCursor(edition="fr", pages_seen=10, edition_articles=100, started_at=T0, updated_at=T0))
    _hot(lane, "fr", "A", "texte")
    _hot(lane, "fr", "B", None)  # a revision with no stored text is not full text
    lane.add(WikiWarmEdition(edition="fr", pages_with_text=3, promoted=1, updated_at=T0))
    lane.commit()
    ft = _row(edition_coverage(lane, now=T0), "fr")["full_text"]
    assert ft["hot_pages_with_text"] == 1 and ft["warm_pages_with_text"] == 3 and ft["warm_promoted"] == 1
    assert ft["share_lower_bound"] == pytest.approx(0.3)  # max(HOT, WARM) / pages seen
    assert ft["share_upper_bound"] == pytest.approx(0.4)  # HOT + WARM / pages seen


def test_warm_never_run_is_unknown_not_zero(lane):
    lane.add(WikiWalkCursor(edition="it", pages_seen=10, edition_articles=100, started_at=T0, updated_at=T0))
    lane.commit()
    ft = _row(edition_coverage(lane, now=T0), "it")["full_text"]
    assert ft["warm_pages_with_text"] is None and ft["warm_promoted"] is None
    assert ft["share_upper_bound"] is None


def test_the_walks_last_refusal_is_named_as_what_it_is_not_as_a_failed_total(lane):
    lane.add(
        WikiWalkCursor(
            edition="de", pages_seen=10, edition_articles=2000, started_at=T0, updated_at=T0,
            last_error="service-busy", last_error_at=T0,
        )
    )
    lane.commit()
    r = _row(edition_coverage(lane, now=T0), "de")
    assert r["edition_articles"] == 2000
    note = r["edition_articles_read"]
    assert note["last_refusal"] == "service-busy" and "failed" not in note


def test_totals_name_editions_without_a_total_and_gap_only_editions_count_as_run(lane):
    lane.add(VersionedGap(feed="stream:pt", detected_at=T0, reason="restart", from_time=T0, to_time=T0))
    lane.commit()
    rep = edition_coverage(lane, now=T0)
    assert _row(rep, "pt")["has_run"] is True
    assert rep["totals"]["editions_without_total"] == len(rep["editions"])
    member = edition_coverage(lane, now=T0, newest_gaps=False)
    assert _row(member, "pt")["gaps"]["total"] == 1 == member["totals"]["gaps"]


def test_last_event_and_gap_history(lane):
    lane.add(
        VersionedChange(
            change_ref="1",
            feed="stream:es",
            change_kind="edit",
            occurred_at=T0,
            recorded_at=T0 + timedelta(minutes=5),
        )
    )
    lane.add(
        VersionedGap(
            feed="stream:es",
            detected_at=T0,
            reason="restart",
            from_time=T0,
            to_time=T0 + timedelta(hours=1),
        )
    )
    lane.commit()
    r = _row(edition_coverage(lane, now=T0 + timedelta(days=1)), "es")
    assert r["has_run"] is True
    assert r["last_event_recorded_at"].startswith("2026-03-11T12:05")
    assert r["gaps"]["total"] == 1 and r["gaps"]["by_reason"] == {"restart": 1}
    assert r["gaps"]["newest"][0]["closed"] is False
    assert "percent" not in str(r["gaps"])


def test_located_counters_are_absent_with_their_reason_never_zero(lane):
    loc = edition_coverage(lane, now=T0)["located"]
    assert loc["measured"] is False and loc["reason"] == "address-extractor-not-built"
    assert loc["per_edition"] is None and loc["per_press_lane"] is None


def test_rides_the_lane_counters_member_and_reads_back(lane):
    lane.add(
        WikiWalkCursor(
            edition="ja", pages_seen=5, edition_articles=50, started_at=T0, updated_at=T0
        )
    )
    lane.commit()
    import json

    member = json.loads(json.dumps(lane_counters(lane, now=T0, window_days=7)))
    assert _row(member["coverage"], "ja")["pages_seen"] == 5
    assert member["coverage"]["measured"] is True and "coverage" not in member["unmeasured"]


def test_member_carries_gap_counts_only_and_compact_unrun_rows(lane):
    lane.add(VersionedChange(change_ref="1", feed="stream:es", change_kind="edit", occurred_at=T0, recorded_at=T0))
    lane.add(VersionedGap(feed="stream:es", detected_at=T0, reason="restart", from_time=T0, to_time=T0))
    lane.commit()
    member = edition_coverage(lane, now=T0, newest_gaps=False)
    es = _row(member, "es")
    assert es["gaps"] == {"total": 1, "by_reason": {"restart": 1}}
    assert _row(member, "en") == {"edition": "en", "has_run": False, "reason": "no-run-yet"}
    assert "newest" in _row(edition_coverage(lane, now=T0), "es")["gaps"]
