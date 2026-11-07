"""The consented ONI fetch: kill switch first, a derived body bound, a loud refusal of the wrong file.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Fixtures are hand-built to mirror the published ``oni.ascii.txt`` shape; the build sandbox has no
route to the CPC host, so none of this is real CPC data and the live shape is an operator check.
"""

from __future__ import annotations

import pytest

from src.stats import fetch
from src.stats.fetch import ONI_URL, fetch_oni, oni_max_chars

GOOD = "SEAS YR   TOTAL ANOM\nDJF  1950 24.72 -1.53\nJFM  1950 25.17 -99.9\n"


class _Resp:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class _Getter:
    def __init__(self, resp: _Resp) -> None:
        self.resp = resp
        self.urls: list[str] = []

    def __call__(self, url: str) -> _Resp:
        self.urls.append(url)
        return self.resp


def _boom(url: str) -> _Resp:
    raise AssertionError(f"getter reached while it must not be: {url!r}")


def test_fetch_parses_stamps_the_vintage_and_keeps_the_gap(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    getter = _Getter(_Resp(GOOD))
    parsed = fetch_oni(get=getter, extracted_at="2026-11-07T00:00:00Z")
    assert getter.urls == [ONI_URL]
    assert parsed.rows_read == 2 and len(parsed.figures) == 4
    assert all(f.extracted_at == "2026-11-07T00:00:00Z" for f in parsed.figures)
    anom = {f.time_period: f.value for f in parsed.figures if f.series_id == "oni.anom"}
    assert anom == {"1950-DJF": -1.53, "1950-JFM": None}  # the sentinel is a gap, not -99.9


def test_the_kill_switch_refuses_before_any_request(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    with pytest.raises(RuntimeError, match="airplane mode"):
        fetch_oni(get=_boom)


def test_the_default_getter_is_never_reached_under_the_kill_switch(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    monkeypatch.setattr(fetch, "_default_getter", _boom)
    with pytest.raises(RuntimeError, match="airplane mode"):
        fetch_oni()


def test_an_html_error_page_is_a_failed_fetch_not_an_empty_series(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    with pytest.raises(ValueError, match="not the expected table"):
        fetch_oni(get=_Getter(_Resp("<html><body>Not Found</body></html>")))


def test_an_empty_body_is_not_a_successful_empty_fetch(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    with pytest.raises(ValueError, match="not the expected table"):
        fetch_oni(get=_Getter(_Resp("")))


def test_http_errors_propagate(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    with pytest.raises(RuntimeError, match="HTTP 404"):
        fetch_oni(get=_Getter(_Resp("", 404)))


def test_the_bound_is_derived_from_the_table_shape_and_grows_with_the_year() -> None:
    assert oni_max_chars(2027) - oni_max_chars(2026) == 12 * fetch.ONI_LINE_ALLOWANCE
    # A real table at today's size sits far under the bound; an absurd body does not.
    real = "SEAS YR   TOTAL ANOM\n" + "DJF  1950 24.72 -1.53\n" * (12 * 77)
    assert len(real) < oni_max_chars(2026) / 4


def test_a_body_over_the_derived_bound_is_refused_before_parsing(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    huge = GOOD + "x" * oni_max_chars()
    with pytest.raises(ValueError, match="allows"):
        fetch_oni(get=_Getter(_Resp(huge)))
