"""The USGS earthquake monthly-count parser and fetch, and the negative space.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FIXTURES ARE HAND-BUILT to mirror the documented FDSN ``format=csv`` shape. They are NOT real
USGS data: this session had no route to earthquake.usgs.gov, so the format is documented, not
verified live. Each positive claim has its refusal twin.
"""

from __future__ import annotations

import pytest

import src.stats.fetch as fetch
from src.stats.usgs_quakes import AGENCY, MIN_MAGNITUDE_FLOOR, parse_usgs_quakes, series_ids

VINTAGE = "2026-11-07T00:00:00Z"
HEADER = "time,latitude,longitude,depth,mag,magType,id,place,type,status"


def _row(t, mag, eid, kind="earthquake", status="reviewed", place='"Somewhere, Nowhere"'):
    return f"{t},1.0,2.0,10,{mag},mww,{eid},{place},{kind},{status}"


GOOD = "\n".join(
    [
        HEADER,
        _row("2026-01-03T01:02:03.500Z", "5.1", "a1"),
        _row("2026-01-20T01:02:03.000Z", "6.4", "a2", status="automatic"),
        _row("2026-01-21T00:00:00.000Z", "4.9", "a3"),  # under the 5.0 threshold
        _row("2026-01-22T00:00:00.000Z", "5.5", "a4", kind="quarry blast"),
        _row("2026-03-01T00:00:00.000Z", "5.0", "a5"),
        _row("2025-12-31T23:59:59.000Z", "7.0", "a6"),  # outside the window
    ]
)


def _parse(text=GOOD, **kw):
    args = {"start_month": "2026-01", "end_month": "2026-03", "min_magnitude": 5.0, "extracted_at": VINTAGE}
    args.update(kw)
    return parse_usgs_quakes(text, **args)


def _by(res, series):
    return {f.time_period: f.value for f in res.figures if f.series_id == series}


def test_monthly_counts_and_max_magnitude_with_the_trail():
    res = _parse()
    count_id, max_id = series_ids(5.0)
    assert _by(res, count_id) == {"2026-01": 2.0, "2026-02": 0.0, "2026-03": 1.0}
    assert _by(res, max_id) == {"2026-01": 6.4, "2026-02": None, "2026-03": 5.0}
    f = res.figures[0]
    assert (f.agency, f.ref_area, f.unit, f.extracted_at) == (AGENCY, "WORLD", "events", VINTAGE)
    assert f.agency != "us-usgs"  # never the minerals agency
    assert f.base_year is None and f.adjustment is None


def test_exclusions_are_stated_not_silent():
    res = _parse()
    assert res.excluded_non_earthquake == 1
    assert res.excluded_below_threshold == 1
    assert res.excluded_outside_window == 1
    assert res.counted == 3
    assert res.unreviewed == 1
    assert res.summary()["counted"] == 3


def test_the_month_in_progress_is_a_gap_not_a_small_number():
    res = _parse(start_month="2026-10", end_month="2026-11", text=HEADER + "\n" + _row("2026-11-02T00:00:00.000Z", "6.0", "b1"))
    count_id, max_id = series_ids(5.0)
    assert _by(res, count_id) == {"2026-10": 0.0, "2026-11": None}
    assert _by(res, max_id)["2026-11"] is None
    assert "2026-11" in res.partial_periods and "2026-10" not in res.partial_periods


def test_a_future_month_is_a_gap_with_its_own_reason():
    res = _parse(start_month="2026-12", end_month="2026-12", text=HEADER + "\n")
    assert res.partial_periods == {"2026-12": "month after the vintage"}


def test_below_the_completeness_floor_is_a_refusal():
    with pytest.raises(ValueError, match="completeness floor"):
        _parse(min_magnitude=MIN_MAGNITUDE_FLOOR - 0.1)


@pytest.mark.parametrize(
    "bad",
    [
        _row("not-a-time", "5.1", "x1"),
        _row("2026-01-03T01:02:03Z", "nan", "x2"),
        _row("2026-01-03T01:02:03Z", "inf", "x3"),
        _row("2026-01-03T01:02:03Z", "1e9", "x4"),
        _row("2026-01-03T01:02:03Z", "", "x5"),  # an earthquake of unknown size is not an event of size 0
        _row("2026-01-03T01:02:03Z", "5.1", ""),
        "short,row",
    ],
)
def test_malformed_rows_are_refused_counted_and_not_counted_as_events(bad):
    res = _parse(text=GOOD + "\n" + bad)
    assert res.refused_total == 1
    assert res.counted == 3  # the good rows are untouched
    assert _by(res, series_ids(5.0)[0])["2026-01"] == 2.0


def test_a_duplicate_event_id_is_refused_not_counted_twice():
    res = _parse(text=GOOD + "\n" + _row("2026-01-03T01:02:03.500Z", "5.1", "a1"))
    assert res.refused_total == 1 and res.refused[0]["reason"] == "duplicate event id"
    assert _by(res, series_ids(5.0)[0])["2026-01"] == 2.0


@pytest.mark.parametrize("body", ["", "<html><body>Bad Request</body></html>", "a,b,c\n1,2,3\n"])
def test_a_wrong_file_is_unrecognised_and_emits_no_series(body):
    res = _parse(text=body)
    assert res.looks_unrecognised and not res.figures


def test_columns_are_found_by_name_so_added_columns_do_not_break_it():
    text = "id,extra,type,mag,time\nz1,q,earthquake,5.2,2026-02-01T00:00:00Z\n"
    assert _by(_parse(text=text), series_ids(5.0)[0])["2026-02"] == 1.0


def test_a_header_only_body_in_a_complete_window_is_a_true_zero():
    assert set(_by(_parse(text=HEADER + "\n"), series_ids(5.0)[0]).values()) == {0.0}


def test_same_bytes_new_stamp_is_a_new_vintage():
    a, b = _parse(), _parse(extracted_at="2026-11-08T00:00:00Z")
    assert [f.value for f in a.figures] == [f.value for f in b.figures]
    assert {f.extracted_at for f in b.figures} == {"2026-11-08T00:00:00Z"}


def test_the_refusal_list_is_capped_but_the_count_is_exact():
    res = _parse(text=HEADER + "\n" + "\n".join(f"junk{i}" for i in range(500)))
    assert res.refused_total == 500 and len(res.refused) == 100 and res.refused_is_sample


@pytest.mark.parametrize("kw", [{"start_month": "2026-3"}, {"end_month": "2025-01"}, {"extracted_at": "yesterday"}])
def test_bad_arguments_are_programming_errors(kw):
    with pytest.raises(ValueError):
        _parse(**kw)


# -------------------------------------------------------------------------------- fetch


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _server(count="3", body=GOOD, seen=None):
    def get(url):
        if seen is not None:
            seen.append(url)
        return _Resp(count) if "/count?" in url else _Resp(body)

    return get


def test_urls_are_complete_months_utc_and_earthquakes_only():
    u = fetch.usgs_quakes_count_url("2026-01", "2026-03", 5.0)
    assert u.startswith("https://earthquake.usgs.gov/fdsnws/event/1/count?")
    assert "starttime=2026-01-01T00%3A00%3A00" in u and "endtime=2026-04-01T00%3A00%3A00" in u
    assert "eventtype=earthquake" in u and "minmagnitude=5" in u
    q = fetch.usgs_quakes_query_url("2026-12", "2026-12", 6.5)
    assert "endtime=2027-01-01" in q and "format=csv" in q and "orderby=time-asc" in q and "minmagnitude=6.5" in q


def test_fetch_counts_first_then_reads_and_stamps_the_vintage():
    seen: list[str] = []
    res = fetch.fetch_usgs_quakes("2026-01", "2026-03", get=_server(seen=seen), extracted_at=VINTAGE)
    assert "/count?" in seen[0] and "/query?" in seen[1] and len(seen) == 2
    assert res.declared_count == 3 and res.figures[0].extracted_at == VINTAGE


def test_kill_switch_refuses_before_any_getter_runs(monkeypatch):
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    called: list[str] = []
    with pytest.raises(RuntimeError, match="kill switch|airplane|offline|refus"):
        fetch.fetch_usgs_quakes("2026-01", "2026-03", get=_server(seen=called))
    assert called == []


def test_a_window_over_the_service_maximum_is_refused_not_truncated():
    seen: list[str] = []
    with pytest.raises(ValueError, match="shorter window"):
        fetch.fetch_usgs_quakes("1900-01", "2026-01", get=_server(count="20001", seen=seen))
    assert len(seen) == 1  # the events were never requested


@pytest.mark.parametrize("count", ["", "<html>", "-3", "3.5", "9999999999"])
def test_a_count_that_is_not_an_integer_is_refused(count):
    with pytest.raises(ValueError, match="plain integer"):
        fetch.fetch_usgs_quakes("2026-01", "2026-03", get=_server(count=count))


def test_the_body_bound_is_derived_from_the_declared_count():
    big = "x" * (3 * fetch.USGS_QUAKES_ROW_ALLOWANCE + fetch.USGS_QUAKES_HEADER_ALLOWANCE + 1)
    with pytest.raises(ValueError, match="allow"):
        fetch.fetch_usgs_quakes("2026-01", "2026-03", get=_server(body=big))
    # and a body that fits is not refused by size
    fetch.fetch_usgs_quakes("2026-01", "2026-03", get=_server(), extracted_at=VINTAGE)


def test_an_error_page_raises_rather_than_returning_an_empty_series():
    with pytest.raises(ValueError, match="not the expected catalogue"):
        fetch.fetch_usgs_quakes("2026-01", "2026-03", get=_server(count="0", body="<html>oops</html>"))


def test_http_error_propagates():
    with pytest.raises(RuntimeError):
        fetch.fetch_usgs_quakes("2026-01", "2026-03", get=lambda u: _Resp("", 503))
