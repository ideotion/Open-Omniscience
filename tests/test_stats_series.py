"""
Offline tests for the StatFigure → honest chart-series adapter (``src/stats/series.py``).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure-data tests — they build :class:`StatFigure` fixtures directly and assert the Group N
honesty rules the adapter bakes into its output shape: comparability segmentation (a unit /
base-year / SA-NSA change starts a new, unjoined segment), a published gap kept in place
(never interpolated), unparseable periods surfaced (never positioned at a guessed x), the
latest vintage winning on a duplicate, and NO score. They import only the pure modules, so
they run in the bare sandbox and in CI alike.
"""

from __future__ import annotations

import re

from src.stats.sdmx import StatFigure
from src.stats.series import _parse_period, to_chart_series

_SCORE_RE = re.compile(r"score|credibility|reliability|quality|trust", re.IGNORECASE)


def _fig(
    *,
    period: str,
    value: float | None = 1.0,
    ref_area: str = "FR",
    series_id: str = "X",
    unit: str | None = None,
    base_year: str | None = None,
    adjustment: str | None = None,
    extracted_at: str = "2026-06-25T00:00:00Z",
    agency: str = "eurostat",
    methodology_ref: str | None = None,
) -> StatFigure:
    return StatFigure(
        agency=agency,
        series_id=series_id,
        ref_area=ref_area,
        time_period=period,
        value=value,
        unit=unit,
        methodology_ref=methodology_ref,
        adjustment=adjustment,
        base_year=base_year,
        extracted_at=extracted_at,
    )


# --------------------------------------------------------------------------- #
# Period parsing.
# --------------------------------------------------------------------------- #
def test_parse_period_granularities_and_ordering() -> None:
    assert _parse_period("2020") == (2020.0, "annual")
    assert _parse_period("2020-Q1") == (2020.0, "quarter")
    assert _parse_period("2020-Q3")[0] == 2020.5
    assert _parse_period("2020-03")[0] == 2020 + 2 / 12.0
    assert _parse_period("2020M03")[1] == "month"
    assert _parse_period("2020-S2")[0] == 2020.5
    assert _parse_period("2020-W27")[1] == "week"
    # A day is placed at its day-of-year fraction (start of period convention).
    t, gran = _parse_period("2020-07-02")
    assert gran == "day"
    assert t is not None
    assert 2020.4 < t < 2020.6
    # Earlier-in-year sorts before later-in-year across granularities.
    q1 = _parse_period("2020-Q1")[0]
    q4 = _parse_period("2020-Q4")[0]
    assert q1 is not None
    assert q4 is not None
    assert q1 < q4 < 2021.0


def test_parse_period_unparseable_and_impossible() -> None:
    assert _parse_period("not-a-date") == (None, "unknown")
    assert _parse_period("") == (None, "unknown")
    assert _parse_period("2020-13")[0] is None  # month 13 is impossible
    assert _parse_period("2020-02-30")[0] is None  # impossible day


# --------------------------------------------------------------------------- #
# The series adapter.
# --------------------------------------------------------------------------- #
def test_simple_annual_series_one_segment_ordered() -> None:
    figs = [_fig(period="2021", value=12.0), _fig(period="2019", value=10.0),
            _fig(period="2020", value=11.0)]
    out = to_chart_series(figs)
    assert out["n_segments"] == 1
    seg = out["segments"][0]
    # Time-ordered regardless of input order.
    assert [p["period"] for p in seg["points"]] == ["2019", "2020", "2021"]
    assert [p["value"] for p in seg["points"]] == [10.0, 11.0, 12.0]
    assert out["granularity"] == "annual"
    assert out["unparseable_periods"] == []


def test_gap_value_is_kept_in_place_never_dropped() -> None:
    figs = [_fig(period="2019", value=10.0), _fig(period="2020", value=None),
            _fig(period="2021", value=12.0)]
    out = to_chart_series(figs)
    # One comparable segment; the middle value stays None (a gap, not dropped, not zeroed).
    assert out["n_segments"] == 1
    assert out["n_points"] == 3
    assert [p["value"] for p in out["segments"][0]["points"]] == [10.0, None, 12.0]


def test_base_year_change_starts_a_new_segment() -> None:
    figs = [
        _fig(period="2019", value=100.0, unit="Index", base_year="2010"),
        _fig(period="2020", value=50.0, unit="Index", base_year="2015"),
    ]
    out = to_chart_series(figs)
    # The 2010=100 run is NEVER joined to the 2015=100 run.
    assert out["n_segments"] == 2
    assert out["segments"][0]["base_year"] == "2010"
    assert out["segments"][1]["base_year"] == "2015"
    assert [len(s["points"]) for s in out["segments"]] == [1, 1]


def test_seasonal_adjustment_flip_segments_three_ways() -> None:
    figs = [
        _fig(period="2019", adjustment="SA"),
        _fig(period="2020", adjustment="NSA"),
        _fig(period="2021", adjustment="SA"),
    ]
    out = to_chart_series(figs)
    # SA → NSA → SA cannot be one line: three honestly-unjoined segments.
    assert out["n_segments"] == 3
    assert [s["adjustment"] for s in out["segments"]] == ["SA", "NSA", "SA"]


def test_unit_change_starts_a_new_segment() -> None:
    figs = [
        _fig(period="2019", unit="million euro"),
        _fig(period="2020", unit="million euro"),
        _fig(period="2021", unit="percent of GDP"),
    ]
    out = to_chart_series(figs)
    assert out["n_segments"] == 2
    assert [len(s["points"]) for s in out["segments"]] == [2, 1]
    assert out["segments"][1]["unit"] == "percent of GDP"


def test_unparseable_period_is_surfaced_not_placed() -> None:
    figs = [_fig(period="2020", value=1.0), _fig(period="provisional", value=2.0)]
    out = to_chart_series(figs)
    assert out["unparseable_periods"] == ["provisional"]
    # Only the placeable point made it into a segment (the unparseable one is NOT positioned).
    assert out["n_points"] == 1
    assert out["segments"][0]["points"][0]["period"] == "2020"


def test_latest_vintage_wins_on_a_duplicate() -> None:
    figs = [
        _fig(period="2020", value=10.0, extracted_at="2026-01-01T00:00:00Z"),
        _fig(period="2020", value=12.0, extracted_at="2026-06-01T00:00:00Z"),  # newer vintage
    ]
    out = to_chart_series(figs)
    assert out["duplicates_collapsed"] == 1
    assert out["n_points"] == 1
    assert out["segments"][0]["points"][0]["value"] == 12.0  # the fresher vintage


def test_filter_by_ref_area_and_series_id() -> None:
    figs = [
        _fig(period="2020", value=1.0, ref_area="FR", series_id="A"),
        _fig(period="2020", value=2.0, ref_area="DE", series_id="A"),
        _fig(period="2020", value=3.0, ref_area="FR", series_id="B"),
    ]
    out = to_chart_series(figs, ref_area="FR", series_id="A")
    assert out["n_points"] == 1
    assert out["segments"][0]["points"][0]["value"] == 1.0


def test_mixed_granularity_is_flagged() -> None:
    figs = [_fig(period="2019", value=1.0), _fig(period="2020-Q1", value=2.0)]
    out = to_chart_series(figs)
    assert out["granularity"] == "mixed"


def test_empty_input_is_honest() -> None:
    out = to_chart_series([])
    assert out["segments"] == []
    assert out["n_points"] == 0
    assert out["granularity"] == "none"
    assert out["unparseable_periods"] == []


def test_no_score_key_anywhere_in_the_output() -> None:
    figs = [
        _fig(period="2019", value=10.0, unit="Index", base_year="2010"),
        _fig(period="2020", value=50.0, unit="Index", base_year="2015"),
        _fig(period="bad", value=1.0),
    ]
    out = to_chart_series(figs)

    def _walk(obj: object) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert not _SCORE_RE.search(k), f"forbidden score-like key: {k!r}"
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(out)
