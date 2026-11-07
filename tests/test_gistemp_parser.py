"""The NASA GISS GISTEMP v4 parser and fetch — and the negative space.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FIXTURES ARE HAND-BUILT to mirror the published ``GLB.Ts+dSST.csv`` shape. They are NOT real
GISS data: this session had no route to data.giss.nasa.gov, so the format is documented, not
verified live, and the operator's first real fetch is what confirms it. Each positive claim
has its refusal twin (the #590 lesson: attack the negative space).
"""

from __future__ import annotations

import pytest

import src.stats.fetch as fetch
from src.stats.gistemp import (
    AGENCY,
    BASE_PERIOD,
    SERIES_ANNUAL_DN,
    SERIES_ANNUAL_JD,
    SERIES_MONTHLY,
    parse_gistemp,
)

VINTAGE = "2026-11-07T00:00:00Z"
HEADER = "Year,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec,J-D,D-N,DJF,MAM,JJA,SON"
GOOD = f"""Land-Ocean: Global Means

{HEADER}
1880,-.18,-.24,-.09,-.17,-.10,-.22,-.20,-.09,-.16,-.22,-.20,-.17,-.17,***,***,-.14,-.17,-.19
1881,-.19,-.14,.03,.05,.06,-.18,.01,-.03,-.15,-.21,-.18,-.07,-.09,-.10,-.19,-.03,-.07,-.18
2026,1.20,1.31,1.28,***,***,***,***,***,***,***,***,***,***,***,1.25,***,***,***
"""


def _of(res, series):
    return [f for f in res.figures if f.series_id == series]


def test_monthly_and_annual_series_with_stated_baseline():
    res = parse_gistemp(GOOD, extracted_at=VINTAGE)
    assert res.rows_read == 3 and not res.refused
    m = _of(res, SERIES_MONTHLY)
    assert len(m) == 36
    first = m[0]
    assert (first.time_period, first.value, first.unit) == ("1880-01", -0.18, "degC")
    assert first.agency == AGENCY and first.ref_area == "GLB"
    assert first.base_year == BASE_PERIOD == "1951-1980"
    assert first.extracted_at == VINTAGE
    assert {f.value for f in _of(res, SERIES_ANNUAL_JD) if f.time_period == "1880"} == {-0.17}


def test_stars_are_gaps_not_values_and_rows_are_kept():
    res = parse_gistemp(GOOD, extracted_at=VINTAGE)
    dn_1880 = [f for f in _of(res, SERIES_ANNUAL_DN) if f.time_period == "1880"]
    assert dn_1880[0].value is None
    cur = [f for f in _of(res, SERIES_MONTHLY) if f.time_period.startswith("2026-")]
    assert len(cur) == 12 and sum(f.value is None for f in cur) == 9
    assert all(f.value != 0 for f in cur if f.value is not None)


def test_seasonal_columns_are_stated_not_emitted():
    res = parse_gistemp(GOOD, extracted_at=VINTAGE)
    assert res.skipped_columns == ("DJF", "MAM", "JJA", "SON")
    assert {f.series_id for f in res.figures} == {SERIES_MONTHLY, SERIES_ANNUAL_JD, SERIES_ANNUAL_DN}


def test_same_bytes_same_figures_new_stamp_is_new_vintage():
    a = parse_gistemp(GOOD, extracted_at=VINTAGE)
    b = parse_gistemp(GOOD, extracted_at=VINTAGE)
    c = parse_gistemp(GOOD, extracted_at="2026-12-01T00:00:00Z")
    assert a.figures == b.figures
    assert [f.value for f in a.figures] == [f.value for f in c.figures]
    assert a.figures != c.figures


@pytest.mark.parametrize("region", ["NH", "SH"])
def test_hemisphere_files_carry_their_region(region):
    res = parse_gistemp(GOOD, region=region, extracted_at=VINTAGE)
    assert {f.ref_area for f in res.figures} == {region}


def test_unknown_region_is_a_programming_error():
    with pytest.raises(ValueError):
        parse_gistemp(GOOD, region="ARC", extracted_at=VINTAGE)


# ------------------------------------------------------------------ the negative space


@pytest.mark.parametrize(
    "body",
    [
        "<html><body>404 Not Found</body></html>",
        "Year,Jan\n1880,1",
        "",
        HEADER + "\n",
        "Land-Ocean: Global Means\n",
        "SEAS YR TOTAL ANOM\nDJF 1950 24.72 -1.53",
    ],
)
def test_a_wrong_file_is_unrecognised_or_empty_never_a_series(body):
    res = parse_gistemp(body, extracted_at=VINTAGE)
    assert res.figures == []
    assert res.looks_unrecognised


def test_a_missing_header_refuses_the_rows():
    res = parse_gistemp("1880,-.18,-.24,-.09,-.17,-.10,-.22,-.20,-.09,-.16,-.22,-.20,-.17,-.17,***,***,-.14,-.17,-.19", extracted_at=VINTAGE)
    assert res.figures == [] and res.looks_unrecognised


def test_refused_rows_are_counted_and_do_not_poison_good_ones():
    bad = GOOD + "\n18xx,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18\n1900,1,2,3\n1901,a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r\n9999,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0\n"
    res = parse_gistemp(bad, extracted_at=VINTAGE)
    assert res.rows_read == 3
    reasons = sorted(r["reason"] for r in res.refused)
    assert reasons == ["expected 19 fields", "non-numeric value", "year is not an integer", "year out of range"]
    assert not res.looks_unrecognised


def test_a_repeated_header_is_not_a_data_row_and_not_a_refusal():
    res = parse_gistemp(GOOD + HEADER + "\n", extracted_at=VINTAGE)
    assert res.rows_read == 3 and not res.refused


def test_a_literal_zero_is_a_value_not_a_gap():
    row = "1950," + ",".join(["0.00"] * 14) + ",***,***,***,***"
    res = parse_gistemp(f"{HEADER}\n{row}\n", extracted_at=VINTAGE)
    assert all(f.value == 0.0 for f in res.figures)


# -------------------------------------------------------------------------------- fetch


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_url_shape_and_region_check():
    assert fetch.gistemp_url("NH") == "https://data.giss.nasa.gov/gistemp/tabledata_v4/NH.Ts+dSST.csv"
    with pytest.raises(ValueError):
        fetch.gistemp_url("../etc")


def test_fetch_delegates_and_stamps_the_vintage():
    seen = []
    res = fetch.fetch_gistemp("GLB", get=lambda u: seen.append(u) or _Resp(GOOD), extracted_at=VINTAGE)
    assert seen == [fetch.gistemp_url("GLB")]
    assert res.rows_read == 3 and res.figures[0].extracted_at == VINTAGE


def test_fetch_of_an_error_page_raises_rather_than_returning_empty():
    with pytest.raises(ValueError):
        fetch.fetch_gistemp(get=lambda u: _Resp("<html>oops</html>"), extracted_at=VINTAGE)


def test_http_error_propagates():
    with pytest.raises(RuntimeError):
        fetch.fetch_gistemp(get=lambda u: _Resp("", 503), extracted_at=VINTAGE)


def test_kill_switch_refuses_before_any_getter_runs(monkeypatch):
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    called = []
    with pytest.raises(RuntimeError):
        fetch.fetch_gistemp(get=lambda u: called.append(u) or _Resp(GOOD))
    assert called == []


_Z = ",".join(["0"] * 17)


@pytest.mark.parametrize(
    "row",
    [
        "1950,nan," + ",".join(["0"] * 16),
        "1950,inf," + ",".join(["0"] * 16),
        "1950,-Infinity," + ",".join(["0"] * 16),
        "1950,1e9," + ",".join(["0"] * 16),
        "1950,1_0," + ",".join(["0"] * 16),
        "1950," + ",".join(["0"] * 14) + ",<html>,abc,def,ghi",
        "1950," + ",".join(["0"] * 17) + ",-",
        "1950" + "," * 18,
        "1950,0,,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0",
    ],
)
def test_non_measurements_and_malformed_cells_refuse_the_row(row):
    res = parse_gistemp(f"{HEADER}\n{row}\n", extracted_at=VINTAGE)
    assert res.figures == [] and res.rows_read == 0 and res.looks_unrecognised


def test_a_duplicate_year_is_refused_not_emitted_twice():
    r1 = "1950," + ",".join(["1"] * 18)
    r2 = "1950," + ",".join(["2"] * 18)
    res = parse_gistemp(f"{HEADER}\n{r1}\n{r2}\n", extracted_at=VINTAGE)
    assert res.rows_read == 1 and [r["reason"] for r in res.refused] == ["duplicate year"]
    assert {f.value for f in res.figures} == {1.0}


@pytest.mark.parametrize("body", ["", HEADER + "\n"])
def test_fetch_of_an_empty_or_header_only_body_raises(body):
    with pytest.raises(ValueError):
        fetch.fetch_gistemp(get=lambda u: _Resp(body), extracted_at=VINTAGE)


@pytest.mark.parametrize(
    "row",
    [
        "1950," + "9" * 400 + "," + ",".join(["0"] * 17),
        "1950,99999," + ",".join(["0"] * 16),
        "1950,٠.٥," + ",".join(["0"] * 16),
        "1950,０.５," + ",".join(["0"] * 16),
        "١٩٩٠," + ",".join(["0"] * 18),
        "19_90," + ",".join(["0"] * 18),
        "01990," + ",".join(["0"] * 18),
        "2199," + ",".join(["0"] * 18),
    ],
)
def test_hostile_numbers_and_years_are_refused(row):
    res = parse_gistemp(f"{HEADER}\n{row}\n", extracted_at=VINTAGE)
    assert res.figures == [] and res.looks_unrecognised


def test_the_refusal_list_is_capped_but_the_count_is_exact():
    from src.stats.gistemp import MAX_REFUSALS_KEPT

    good = "1950," + ",".join(["0"] * 18)
    body = f"{HEADER}\n{good}\n" + "junk\n" * 5000
    res = parse_gistemp(body, extracted_at=VINTAGE)
    assert res.refused_total == 5000 and len(res.refused) == MAX_REFUSALS_KEPT
    assert res.rows_read == 1 and not res.looks_unrecognised


def test_fetch_refuses_an_oversized_body():
    with pytest.raises(ValueError):
        fetch.fetch_gistemp(get=lambda u: _Resp("x" * (fetch.gistemp_max_chars() + 1)), extracted_at=VINTAGE)


def test_the_body_bound_grows_with_the_data_and_fits_the_real_table():
    assert fetch.gistemp_max_chars(2027) - fetch.gistemp_max_chars(2026) == fetch.GISTEMP_LINE_ALLOWANCE
    assert fetch.gistemp_max_chars(2026) > 147 * 125  # a ~125-char row for every year to date fits


def test_an_all_gap_table_is_a_success_marked_all_gap():
    row = "1950," + ",".join(["***"] * 18)
    res = parse_gistemp(f"{HEADER}\n{row}\n", extracted_at=VINTAGE)
    assert res.rows_read == 1 and res.all_gap and not res.looks_unrecognised
    assert res.summary()["all_gap"] is True
    assert parse_gistemp(GOOD, extracted_at=VINTAGE).all_gap is False


def test_the_summary_says_when_refusals_are_only_a_sample():
    good = "1950," + ",".join(["0"] * 18)
    res = parse_gistemp(f"{HEADER}\n{good}\n" + "junk\n" * 500, extracted_at=VINTAGE)
    s = res.summary()
    assert s["refused_total"] == 500 and s["refused_is_sample"] is True and len(s["refused_sample"]) == 100
    assert parse_gistemp(GOOD, extracted_at=VINTAGE).summary()["refused_is_sample"] is False
