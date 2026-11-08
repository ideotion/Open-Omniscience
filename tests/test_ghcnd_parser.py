"""GHCN-Daily parser and fetch: hand-made fixtures (the sandbox cannot reach the host)."""

from __future__ import annotations

import pytest

from src.ingest.fetch_verdict import NETWORK_REFUSED
from src.stats import fetch, ghcnd

STN = "USC00011084"
AT = "2026-11-07T00:00:00Z"


def _line(element: str, year: int, month: int, days: dict[int, tuple[int, str, str, str]], station: str = STN) -> str:
    """One 269-character line; days not given are -9999 with blank flags."""
    out = f"{station}{year:04d}{month:02d}{element}"
    for d in range(1, 32):
        v, m, q, s = days.get(d, (-9999, " ", " ", " "))
        out += f"{v:5d}{m}{q}{s}"
    assert len(out) == ghcnd.LINE_LENGTH
    return out


def _parse(*lines: str, station: str = STN) -> ghcnd.GhcndParse:
    return ghcnd.parse_ghcnd_dly("\n".join(lines) + "\n", station=station, extracted_at=AT)


def test_units_and_dates():
    p = _parse(
        _line("TMAX", 2020, 1, {1: (-25, " ", " ", "S"), 2: (305, " ", " ", "S")}),
        _line("PRCP", 2020, 1, {1: (125, " ", " ", "S")}),
        _line("SNWD", 2020, 1, {1: (40, " ", " ", "S")}),
    )
    got = {(f.series_id, f.time_period): (f.value, f.unit) for f in p.figures if f.value is not None}
    assert got[("ghcnd.TMAX", "2020-01-01")] == (-2.5, "degC")
    assert got[("ghcnd.TMAX", "2020-01-02")] == (30.5, "degC")
    assert got[("ghcnd.PRCP", "2020-01-01")] == (12.5, "mm")
    assert got[("ghcnd.SNWD", "2020-01-01")] == (40.0, "mm")
    assert all(f.ref_area == STN and f.extracted_at == AT and f.base_year is None for f in p.figures)


def test_missing_is_a_gap_not_zero_and_nonexistent_days_are_absent():
    p = _parse(_line("TMAX", 2021, 2, {1: (10, " ", " ", "S")}))
    assert len(p.figures) == 28  # February 2021: no 29th-31st
    assert p.figures[0].value == 1.0
    assert all(f.value is None for f in p.figures[1:])
    assert p.missing_days == 27


def test_quality_flagged_value_becomes_a_gap_with_its_reason_counted():
    p = _parse(_line("TMAX", 2020, 7, {1: (999, " ", "G", "S"), 2: (250, " ", " ", "S")}))
    assert p.figures[0].value is None
    assert p.figures[1].value == 25.0
    assert p.quality_flagged == {"G": 1}
    assert p.flagged == [{"station": STN, "date": "2020-07-01", "element": "TMAX", "qflag": "G"}]
    assert p.summary()["quality_flagged_total"] == 1


def test_trace_precipitation_is_zero_and_counted():
    p = _parse(_line("PRCP", 2020, 3, {5: (0, "T", " ", "S")}))
    assert p.figures[4].value == 0.0
    assert p.trace_days == 1


def test_other_elements_are_named_not_silent():
    p = _parse(_line("WT01", 2020, 1, {1: (1, " ", " ", "S")}), _line("TMIN", 2020, 1, {1: (0, " ", " ", "S")}))
    assert p.skipped_elements == {"WT01": 1}
    assert {f.series_id for f in p.figures} == {"ghcnd.TMIN"}


@pytest.mark.parametrize(
    "bad",
    [
        _line("TMAX", 2020, 1, {1: (1, " ", " ", " ")}, station="USC00099999"),  # other station
        _line("TMAX", 2020, 4, {31: (1, " ", " ", " ")}),  # a value on April 31
        _line("PRCP", 2020, 1, {1: (-5, " ", " ", " ")}),  # negative precipitation
        _line("TMAX", 2020, 1, {1: (5000, " ", " ", " ")}),  # 500 degC
        "short line",
        "<html>404</html>",
    ],
)
def test_bad_lines_are_refused_and_counted(bad):
    p = _parse(bad)
    assert p.refused_total == 1 and not p.figures
    assert p.looks_unrecognised


def test_duplicate_month_element_is_refused():
    line = _line("TMAX", 2020, 1, {1: (1, " ", " ", "S")})
    p = _parse(line, line)
    assert p.lines_read == 1 and p.refused_total == 1


def test_empty_body_is_unrecognised_and_bad_station_raises():
    assert _parse("").looks_unrecognised
    with pytest.raises(ValueError):
        ghcnd.parse_ghcnd_dly("", station="../etc/passwd", extracted_at=AT)


def test_all_gap_is_flagged():
    assert _parse(_line("TMAX", 2020, 1, {})).all_gap


def _station_row(sid, lat, lon, elev, state, name, gsn="", net="", wmo=""):
    return f"{sid:<11} {lat:8.4f} {lon:9.4f} {elev:6.1f} {state:<2} {name:<30} {gsn:<3} {net:<3} {wmo:<5}"


def test_station_list():
    text = "\n".join(
        [
            _station_row("USC00011084", 31.0583, -87.0547, 25.9, "AL", "BREWTON 3 SSE", net="HCN"),
            _station_row("ACW00011604", 17.1167, -61.7833, -999.9, "", "ST JOHNS COOLIDGE FLD", gsn="GSN", wmo="78861"),
            _station_row("XXXXXXXXXXX", 95.0, 0.0, 0.0, "", "BAD LAT"),
            "garbage",
        ]
    )
    p = ghcnd.parse_ghcnd_stations(text)
    assert [s.station_id for s in p.stations] == ["USC00011084", "ACW00011604"]
    a, b = p.stations
    assert (a.state, a.hcn_crn, a.gsn, a.wmo_id, a.elevation_m) == ("AL", "HCN", False, None, 25.9)
    assert (b.state, b.gsn, b.wmo_id, b.elevation_m) == (None, True, "78861", None)
    assert p.refused_total == 2


# --- fetch ---------------------------------------------------------------------------------------------


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_url_validates_station():
    assert fetch.ghcnd_url(STN).endswith("/ghcnd-all/USC00011084.dly")
    with pytest.raises(ValueError):
        fetch.ghcnd_url("../../x")


def test_bound_grows_with_the_calendar():
    assert fetch.ghcnd_max_chars(2027) > fetch.ghcnd_max_chars(2026)


def test_fetch_happy_path_and_refusals(monkeypatch):
    body = _line("TMAX", 2020, 1, {1: (10, " ", " ", "S")}) + "\n"
    calls = []
    got = fetch.fetch_ghcnd_station(STN, get=lambda u: calls.append(u) or _Resp(body), extracted_at=AT)
    assert calls == [fetch.ghcnd_url(STN)] and got.figures[0].value == 1.0
    with pytest.raises(ValueError, match="not the expected station file"):
        fetch.fetch_ghcnd_station(STN, get=lambda u: _Resp("<html>"), extracted_at=AT)
    with pytest.raises(ValueError, match="over the"):
        fetch.fetch_ghcnd_station(STN, get=lambda u: _Resp("x" * (fetch.ghcnd_max_chars() + 1)), extracted_at=AT)


def test_kill_switch_refuses_before_any_request(monkeypatch):
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)

    def boom(url):
        raise AssertionError("no request may be made")

    with pytest.raises(RuntimeError, match=NETWORK_REFUSED.split()[0]):
        fetch.fetch_ghcnd_station(STN, get=boom)


def test_the_default_getter_is_held_to_the_ghcn_directory(monkeypatch):
    seen = {}

    def fake_session(**kw):
        seen.update(kw)
        return object()

    monkeypatch.setattr(fetch, "guarded_session", fake_session)
    monkeypatch.setattr(fetch, "_bounded_get", lambda session, url, *, max_chars: (url, max_chars))
    url, max_chars = fetch._ghcnd_getter(fetch.ghcnd_url(STN))
    assert seen["allowed_hosts"] == ("www.ncei.noaa.gov",)
    assert all(fetch.ghcnd_url(STN).split("//", 1)[1].split("/", 1)[1].startswith(p.lstrip("/")) for p in seen["allowed_path_prefixes"])
    assert max_chars == fetch.ghcnd_max_chars()
