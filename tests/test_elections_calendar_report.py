"""Per-country tier report + snapshot conversion: fixtures only, refusals pinned."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.civic.calendar_report import (
    STATES,
    country_tier_report,
    layer,
    snapshot_to_event,
    snapshot_to_events,
)

TODAY = date(2026, 11, 7)
ROWS = json.loads(
    (Path(__file__).parent / "fixtures" / "election_snapshot_fixture.json").read_text("utf-8")
)


def _all_keys(obj):
    """Every key at every depth, so a score nested in a row or an entry is caught too."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_keys(v)


def _by_qid():
    events, refused = snapshot_to_events(ROWS, TODAY)
    return {e["source_qid"]: e for e in events}, {r["qid"]: r["reason"] for r in refused}


def test_day_precision_with_official_source_is_the_only_schedule():
    ev, _ = _by_qid()
    assert ev["Q1"]["confirmed"] is True and ev["Q1"]["day"] == 10


def test_day_without_official_source_degrades_to_a_labelled_window():
    ev, _ = _by_qid()
    q2 = ev["Q2"]
    assert q2["day"] is None and q2["confirmed"] is False
    assert q2["inferred"] is True and "no official source" in q2["inferred_reason"]


def test_range_in_one_month_is_a_window_and_labelled_inferred():
    ev, _ = _by_qid()
    assert ev["Q3"]["month"] == 7 and ev["Q3"]["day"] is None and ev["Q3"]["inferred"]


def test_year_and_month_precision_never_gain_a_day():
    ev, _ = _by_qid()
    assert ev["Q4"]["day"] is None and ev["Q4"]["month"] is None and ev["Q4"]["window_year"] == 2031
    assert ev["Q5"]["day"] is None and ev["Q5"]["month"] == 3


def test_no_date_is_null_with_a_reason_not_a_guess():
    ev, _ = _by_qid()
    q6 = ev["Q6"]
    assert q6["month"] is None and q6["day"] is None and "window_year" not in q6
    assert q6["date_reason"]


def test_past_and_malformed_rows_are_refused_with_a_reason():
    _, refused = _by_qid()
    assert "past" in refused["Q7"]
    assert "alpha-2" in refused["Q8"]


def test_report_states_every_floor_country_exactly_once_with_a_reason_when_absent():
    events, _ = snapshot_to_events(ROWS, TODAY)
    floor = {"fr", "de", "es", "pt", "it", "jp", "id", "zz"}
    rep = country_tier_report(events, floor, TODAY)
    assert [r["cc"] for r in rep["countries"]] == sorted(floor)
    assert sum(rep["counts"].values()) == len(floor)
    assert set(rep["counts"]) == set(STATES)
    by = {r["cc"]: r for r in rep["countries"]}
    assert by["fr"]["state"] == "scheduled" and by["de"]["state"] == "window"
    assert by["jp"]["state"] == "dateless" and by["jp"]["reason"]
    assert by["id"]["state"] == "missing" and by["id"]["reason"]
    assert all(r["state"] in STATES for r in rep["countries"])
    assert not any("score" in k.lower() for k in _all_keys(rep))


def test_projected_passed_is_reported_apart_and_never_rolled_forward():
    ev = {
        "calendar": "elections",
        "country": "ZZ",
        "title": "t",
        "interval_years": 4,
        "last_held": "2020-01-01",
        "recurrence_rule_source": "constitution art. 1",
    }
    rep = country_tier_report([ev], {"zz"}, TODAY)
    assert rep["countries"][0]["state"] == "projected_passed"
    ev2 = dict(ev, last_held="2025-01-01")
    assert (
        country_tier_report([ev2], {"zz"}, TODAY)["countries"][0]["state"] == "projected_upcoming"
    )


def test_layering_shadows_with_a_record_and_never_silently_drops():
    events, _ = snapshot_to_events(ROWS, TODAY)
    curated = [
        {
            "calendar": "elections",
            "country": "FR",
            "title": "France — Presidential election 2027",
            "month": 4,
        }
    ]
    merged, shadowed = layer(curated, events)
    assert shadowed == [
        {
            "qid": "Q1",
            "country": "FR",
            "shadowed_by": "France — Presidential election 2027",
            "reason": "same country, no office named, month 4",
        }
    ]
    assert len(merged) == len(events)  # 1 curated + (N-1) kept
    assert merged[0] is curated[0]


def test_a_past_range_is_refused_like_a_past_point():
    row = {"qid": "Q9", "country": "id", "office": "P", "start": "2019-04-01", "end": "2019-04-30"}
    ev, why = snapshot_to_event_pair(row)
    assert ev is None and "past" in why


def test_the_current_month_and_year_have_not_passed():
    month = {
        "qid": "Q10",
        "country": "id",
        "office": "P",
        "point_in_time": "2026-11-01",
        "precision": "month",
    }
    year = {
        "qid": "Q11",
        "country": "id",
        "office": "P",
        "point_in_time": "2026-01-01",
        "precision": "year",
    }
    assert snapshot_to_event_pair(month)[0] is not None
    assert snapshot_to_event_pair(year)[0] is not None


def test_a_dropped_day_does_not_survive_in_date_basis():
    ev, _ = _by_qid()
    assert "2029-09-01" not in ev["Q2"]["date_basis"]


def snapshot_to_event_pair(row):
    return snapshot_to_event(row, TODAY)


# ------------------------------------------------------------------ 0.6.1 follow-ups of #1773


def _curated(**kw):
    base = {"calendar": "elections", "title": "Curated", "confirmed": False, "day": None}
    base.update(kw)
    return base


def test_an_office_less_curated_entry_no_longer_shadows_every_row_of_its_country():
    events, _ = snapshot_to_events(ROWS, TODAY)
    # Germany: a curated window in a different month from the Bundestag row (September 2029)
    merged, shadowed = layer([_curated(country="DEU", month=3)], events, TODAY)
    assert shadowed == [] and len(merged) == len(events) + 1
    # a dateless curated entry shadows nothing either: it cannot show it is the same election
    _, shadowed = layer([_curated(country="DEU")], events, TODAY)
    assert shadowed == []


def test_a_stated_year_must_overlap_and_an_office_must_agree():
    events, _ = snapshot_to_events(ROWS, TODAY)
    _, shadowed = layer([_curated(country="DE", window_year=2029)], events, TODAY)
    assert [s["qid"] for s in shadowed] == ["Q2"] and "year 2029" in shadowed[0]["reason"]
    _, shadowed = layer([_curated(country="DE", window_year=2030)], events, TODAY)
    assert shadowed == []
    _, shadowed = layer([_curated(country="DE", window_year=2029, office="President")], events, TODAY)
    assert shadowed == []
    _, shadowed = layer([_curated(country="DE", window_year=2029, office="bundestag")], events, TODAY)
    assert [s["qid"] for s in shadowed] == ["Q2"]


def test_an_undated_snapshot_row_is_kept_not_shadowed():
    events, _ = snapshot_to_events(ROWS, TODAY)
    _, shadowed = layer([_curated(country="JPN", month=7, window_year=2028)], events, TODAY)
    assert shadowed == []  # Q6 (Japan) carries no date, so nothing shows it is the curated election


def test_alpha3_and_alpha2_meet_in_the_report_and_in_layering():
    events = [_curated(country="FRA", title="France 2027", month=4)]
    rep = country_tier_report(events, {"fr", "DEU"}, TODAY)
    by = {r["cc"]: r for r in rep["countries"]}
    assert set(by) == {"fr", "de"}
    assert by["fr"]["state"] == "window" and by["de"]["state"] == "missing"


def test_wikidata_timestamps_with_a_time_part_are_read():
    base = {"qid": "Q50", "country": "fr", "office": "President", "official_url": "https://example.org/"}
    ev, _ = snapshot_to_event(dict(base, point_in_time="+2027-04-10T00:00:00Z", precision="day"), TODAY)
    assert (ev["month"], ev["day"], ev["window_year"]) == (4, 10, 2027) and ev["confirmed"]
    ev, _ = snapshot_to_event(dict(base, point_in_time="+2027-05-00T00:00:00Z", precision="month"), TODAY)
    assert (ev["month"], ev["window_year"]) == (5, 2027)
    ev, _ = snapshot_to_event(dict(base, point_in_time="+2031-00-00T00:00:00Z", precision="year"), TODAY)
    assert ev["window_year"] == 2031 and ev["month"] is None
    ev, _ = snapshot_to_event(
        dict(base, start="2027-07-01T00:00:00Z", end="+2027-07-31T00:00:00Z", official_url=""), TODAY
    )
    assert ev["month"] == 7 and ev["inferred"]


def test_a_zero_day_under_day_precision_stays_unreadable():
    row = {"qid": "Q51", "country": "fr", "office": "P", "point_in_time": "+2027-04-00T00:00:00Z", "precision": "day"}
    ev, _ = snapshot_to_event(row, TODAY)
    assert ev["day"] is None and ev["date_reason"] == "row states no usable date"
