"""NSIDC Sea Ice Index daily extent parser and fetcher, on hand-made fixtures (no network)."""

from __future__ import annotations

import pytest

from src.stats import fetch as fetch_mod
from src.stats.nsidc import NSIDC_AS_OF, parse_nsidc

HEADER = (
    "Year, Month, Day,     Extent,    Missing, Source Data\n"
    "YYYY,    MM,  DD, 10^6 sq km, 10^6 sq km, Source data product web site: http://nsidc.org/data/nsidc-0081.html\n"
)
GOOD = HEADER + (
    "1978,  10,  26,    10.231,      0.000, ['ftp://a/x.bin']\n"
    "1978,  10,  28,    10.420,      0.000, ['ftp://a/y.bin', 'ftp://a/z.bin']\n"
    "2024,   1,   5, -9999,   0.500, ['ftp://a/w.bin']\n"
)


def test_parses_rows_with_provenance_and_gap():
    p = parse_nsidc(GOOD, region="N", extracted_at="2026-11-07T00:00:00Z")
    assert p.rows_read == 3 and p.refused_total == 0 and not p.looks_unrecognised
    f = p.figures
    assert [x.time_period for x in f] == ["1978-10-26", "1978-10-28", "2024-01-05"]
    assert f[0].value == pytest.approx(10.231) and f[0].unit == "Mkm2"
    assert f[2].value is None  # -9999 is a gap, not a number
    assert all(x.ref_area == "N" and x.extracted_at == "2026-11-07T00:00:00Z" for x in f)
    assert p.rows_with_missing_area == 1
    assert not p.all_gap


def test_source_column_with_commas_does_not_break_the_row():
    p = parse_nsidc(GOOD, region="S", extracted_at="t")
    assert p.rows_read == 3 and p.figures[0].ref_area == "S"


@pytest.mark.parametrize(
    "row,reason",
    [
        ("2000, 1, 1, , 0, x", "non-numeric"),
        ("2000, 1, 1, nan, 0, x", "non-numeric"),
        ("2000, 1, 1, inf, 0, x", "non-numeric"),
        ("2000, 1, 1, 1e3, 0, x", "non-numeric"),
        ("2000, 1, 1, -3.0, 0, x", "negative"),
        ("2000, 1, 1, -0.000, 0, x", "negative"),
        ("2000, 1, 1, 999, 0, x", "bound"),
        ("2000, 2, 30, 5.0, 0, x", "calendar"),
        ("1900, 1, 1, 5.0, 0, x", "range"),
        ("2000, 1, 1, 5.0", "fields"),
        ("2000, a, 1, 5.0, 0, x", "integer"),
    ],
)
def test_bad_rows_are_refused_and_counted(row, reason):
    p = parse_nsidc(HEADER + row + "\n2001, 1, 1, 5.0, 0, x\n", extracted_at="t")
    assert p.rows_read == 1 and p.refused_total == 1
    assert reason in p.refused[0]["reason"]


def test_duplicate_date_refused():
    p = parse_nsidc(GOOD + "1978, 10, 26, 11.0, 0, x\n", extracted_at="t")
    assert p.refused_total == 1 and p.refused[0]["reason"] == "duplicate date"
    assert p.figures[0].value == pytest.approx(10.231)  # first one wins, no overwrite


def test_html_and_empty_bodies_are_unrecognised():
    for body in ("<html><body>404</body></html>", "", HEADER):
        assert parse_nsidc(body, extracted_at="t").looks_unrecognised


def test_all_gap_flag():
    p = parse_nsidc(HEADER + "2000, 1, 1, -9999, 0, x\n", extracted_at="t")
    assert p.all_gap and p.figures[0].value is None


def test_region_validated():
    with pytest.raises(ValueError):
        parse_nsidc(GOOD, region="X", extracted_at="t")
    with pytest.raises(ValueError):
        fetch_mod.nsidc_url("X")


def test_urls_and_derived_bound():
    assert fetch_mod.nsidc_url("N").endswith("/north/daily/data/N_seaice_extent_daily_v3.0.csv")
    assert fetch_mod.nsidc_url("S").endswith("/south/daily/data/S_seaice_extent_daily_v3.0.csv")
    from datetime import date

    assert fetch_mod.nsidc_max_chars(date(2030, 1, 1)) > fetch_mod.nsidc_max_chars(date(2026, 1, 1))


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_fetch_uses_getter_and_parses():
    urls = []

    def get(url):
        urls.append(url)
        return _Resp(GOOD)

    p = fetch_mod.fetch_nsidc("N", get=get, extracted_at="t")
    assert p.rows_read == 3 and urls == [fetch_mod.nsidc_url("N")]


def test_fetch_refuses_html_and_oversize():
    with pytest.raises(ValueError, match="not the expected"):
        fetch_mod.fetch_nsidc("N", get=lambda u: _Resp("<html>x</html>"), extracted_at="t")
    with pytest.raises(ValueError, match="over the"):
        fetch_mod.fetch_nsidc("N", get=lambda u: _Resp("x" * (fetch_mod.nsidc_max_chars() + 1)), extracted_at="t")


def test_kill_switch_refuses_before_any_request(monkeypatch):
    from src.ingest.fetch_verdict import NETWORK_REFUSED

    monkeypatch.setattr(fetch_mod, "kill_switch_active", lambda: True)
    called = []
    with pytest.raises(RuntimeError, match=NETWORK_REFUSED[:20]):
        fetch_mod.fetch_nsidc("N", get=lambda u: called.append(u), extracted_at="t")
    assert called == []


def test_as_of_is_stamped():
    assert NSIDC_AS_OF == "2026-11"


def test_the_session_is_pinned_to_its_own_host_and_directory_and_the_read_is_bounded(monkeypatch):
    built: dict = {}
    bounded: list[int] = []

    def factory(**kw):
        built.update(kw)
        return "session"

    monkeypatch.setattr(fetch_mod, "guarded_session", factory)
    monkeypatch.setattr(fetch_mod, "_bounded_get", lambda session, url, *, max_chars: bounded.append(max_chars))
    fetch_mod._nsidc_getter("u")
    assert built["allowed_hosts"] == fetch_mod.NSIDC_HOSTS == ("noaadata.apps.nsidc.org",)
    assert built["allowed_path_prefixes"] == fetch_mod.NSIDC_PATHS == ("/NOAA/G02135/",)
    assert bounded == [fetch_mod.nsidc_max_chars()]
    for region in ("N", "S"):
        assert fetch_mod.nsidc_url(region).startswith("https://noaadata.apps.nsidc.org/NOAA/G02135/")


def test_unknown_coverage_is_counted_apart_from_full_coverage():
    p = parse_nsidc(HEADER + "2000, 1, 1, 5.0, -9999, x\n2000, 1, 2, 5.0, 0.000, x\n", extracted_at="t")
    assert p.rows_read == 2 and p.rows_with_unknown_missing_area == 1 and p.rows_with_missing_area == 0


def test_a_changed_or_missing_units_row_reads_no_rows():
    names = "Year, Month, Day, Extent, Missing, Source Data\n"
    for body in (
        names + "2000, 1, 1, 5.0, 0, x\n",  # units row missing
        names + "YYYY, MM, DD, 10^3 sq km, 10^3 sq km, x\n2000, 1, 1, 5.0, 0, x\n",  # unit changed
        "Year, Month\n2000,1,1,5,0,x\n",
    ):
        p = parse_nsidc(body, extracted_at="t")
        assert p.rows_read == 0 and p.looks_unrecognised


def test_each_partly_observed_day_is_named():
    body = HEADER + "2000, 1, 1, 5.0, 0.000, x\n2000, 1, 2, 4.1, 2.500, x\n2000, 1, 3, 4.0, -9999, x\n"
    p = parse_nsidc(body, extracted_at="t")
    assert p.coverage_gaps == {"2000-01-02": 2.5, "2000-01-03": None}
    assert p.summary()["coverage_gaps"] == {"2000-01-02": 2.5, "2000-01-03": None}


def test_a_swapped_or_renamed_column_is_refused_not_read_as_extent():
    units = "YYYY, MM, DD, 10^6 sq km, 10^6 sq km, x\n"
    for names in (
        "Year, Month, Day, Missing, Extent, Source Data\n",
        "Year, Month, Day, Area, Missing, Source Data\n",
    ):
        p = parse_nsidc(names + units + "2000, 1, 1, 0.000, 10.2, x\n", extracted_at="t")
        assert p.rows_read == 0 and p.figures == [] and p.looks_unrecognised
