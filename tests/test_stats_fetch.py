"""
Offline tests for the official-statistics LIVE FETCH layer (``src/stats/fetch.py``).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Network-FREE: the getter is always injected (a fake response object) or the kill
switch is monkeypatched, so no real socket is ever opened. They assert URL shape +
encoding, that the fetch DELEGATES to the merged parser (honesty rules carry through:
a published gap → ``value=None``, ``extracted_at`` preserved), and the binding safety
property — the kill switch refuses BEFORE any getter runs (no socket attempted while
airplane mode is engaged), on both the injected and the default-getter paths.
"""

from __future__ import annotations

import pytest

import src.stats.fetch as fetch
from src.stats.fetch import (
    EUROSTAT_API_BASE,
    WORLDBANK_API_BASE,
    eurostat_url,
    fetch_eurostat,
    fetch_worldbank,
    worldbank_url,
)


# --------------------------------------------------------------------------- #
# Fake response + getters (no network).
# --------------------------------------------------------------------------- #
class _FakeResponse:
    """A minimal requests-like response: ``.json()`` / ``.raise_for_status()``."""

    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:  # 200 → no-op
        return None


class _RecordingGetter:
    """A getter that records the URLs it was called with and returns a fixed response."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str) -> _FakeResponse:
        self.urls.append(url)
        return _FakeResponse(self.payload)


def _exploding_getter(url: str) -> _FakeResponse:
    """A getter that MUST NEVER be called (proves no socket is attempted)."""
    raise AssertionError(f"getter was called while it must not be: {url!r}")


# --------------------------------------------------------------------------- #
# Fixtures (reuse the parser-test shapes).
# --------------------------------------------------------------------------- #
def _worldbank_payload() -> list:
    page_meta = {"page": 1, "pages": 1, "per_page": 1000, "total": 2}
    observations = [
        {
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
            "country": {"id": "FR", "value": "France"},
            "countryiso3code": "FRA",
            "date": "2021",
            "value": 2957879759277.0,
        },
        {
            # A PUBLISHED GAP — the cell exists but the value is null.
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
            "country": {"id": "FR", "value": "France"},
            "countryiso3code": "FRA",
            "date": "2020",
            "value": None,
        },
    ]
    return [page_meta, observations]


def _sdmx_payload() -> dict:
    return {
        "data": {
            "structure": {
                "dimensions": {
                    "series": [
                        {"id": "geo", "values": [{"id": "EA19", "name": "Euro area"}]},
                        {"id": "indicator",
                         "values": [{"id": "PRC_HICP", "name": "HICP"}]},
                    ],
                    "observation": [{"id": "time", "values": [{"id": "2022-03"}]}],
                },
            },
            "dataSets": [{"series": {"0:0": {"observations": {"0": [109.4]}}}}],
        }
    }


# --------------------------------------------------------------------------- #
# URL builders.
# --------------------------------------------------------------------------- #
def test_worldbank_url_shape_and_encoding() -> None:
    url = worldbank_url("NY.GDP.MKTP.CD", "FR")
    assert url == (
        f"{WORLDBANK_API_BASE}/country/FR/indicator/NY.GDP.MKTP.CD"
        "?format=json&per_page=1000"
    )
    # Defaults: country "all", per_page tunable.
    assert worldbank_url("SP.POP.TOTL") == (
        f"{WORLDBANK_API_BASE}/country/all/indicator/SP.POP.TOTL"
        "?format=json&per_page=1000"
    )
    assert "per_page=50" in worldbank_url("SP.POP.TOTL", per_page=50)


def test_worldbank_url_encodes_path_segments() -> None:
    # A '/' in an id must be percent-encoded into the path segment, not split it.
    url = worldbank_url("A/B", "C D")
    assert "/indicator/A%2FB?" in url
    assert "/country/C%20D/" in url


def test_worldbank_url_rejects_empty_indicator() -> None:
    with pytest.raises(ValueError):
        worldbank_url("")
    with pytest.raises(ValueError):
        worldbank_url("   ")


def test_eurostat_url_shape_and_params() -> None:
    assert eurostat_url("PRC_HICP_MIDX") == (
        f"{EUROSTAT_API_BASE}/PRC_HICP_MIDX?format=JSON"
    )
    # Extra params are appended, urlencoded and SORTED (deterministic).
    url = eurostat_url("nama_10_gdp", {"unit": "CP_MEUR", "geo": "FR"})
    assert url == (
        f"{EUROSTAT_API_BASE}/nama_10_gdp?format=JSON&geo=FR&unit=CP_MEUR"
    )


def test_eurostat_url_rejects_empty_dataset() -> None:
    with pytest.raises(ValueError):
        eurostat_url("")
    with pytest.raises(ValueError):
        eurostat_url("  ")


# --------------------------------------------------------------------------- #
# fetch_worldbank — delegates to the parser, honesty rules carry through.
# --------------------------------------------------------------------------- #
def test_fetch_worldbank_parses_two_figures_with_gap(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    getter = _RecordingGetter(_worldbank_payload())
    figs = fetch_worldbank(
        "NY.GDP.MKTP.CD", "FR", get=getter, extracted_at="2026-06-16T12:00:00Z"
    )
    assert len(figs) == 2
    first, gap = figs
    assert first.agency == "worldbank"
    assert first.series_id == "NY.GDP.MKTP.CD"
    assert first.ref_area == "FRA"
    assert first.value == 2957879759277.0
    assert first.extracted_at == "2026-06-16T12:00:00Z"  # caller vintage preserved
    # The published gap survives delegation: value None, never dropped/zeroed.
    assert gap.value is None
    assert gap.time_period == "2020"
    # The getter was called once with the built URL.
    assert getter.urls == [worldbank_url("NY.GDP.MKTP.CD", "FR")]


# --------------------------------------------------------------------------- #
# fetch_eurostat — delegates to the SDMX parser.
# --------------------------------------------------------------------------- #
def test_fetch_eurostat_parses_sdmx_message(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    getter = _RecordingGetter(_sdmx_payload())
    figs = fetch_eurostat(
        "PRC_HICP_MIDX", get=getter, extracted_at="2026-06-16T12:00:00Z"
    )
    assert len(figs) == 1
    fig = figs[0]
    assert fig.agency == "eurostat"
    assert fig.ref_area == "EA19"
    assert fig.series_id == "PRC_HICP"
    assert fig.time_period == "2022-03"
    assert fig.value == 109.4
    assert fig.extracted_at == "2026-06-16T12:00:00Z"
    assert getter.urls == [eurostat_url("PRC_HICP_MIDX")]


def test_fetch_eurostat_agency_override(monkeypatch) -> None:
    # The same SDMX path serves other producers under their own agency code.
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    getter = _RecordingGetter(_sdmx_payload())
    figs = fetch_eurostat("DATASET", get=getter, agency="imf",
                          extracted_at="2026-06-16T12:00:00Z")
    assert figs and all(f.agency == "imf" for f in figs)


# --------------------------------------------------------------------------- #
# KILL SWITCH: refuse BEFORE any socket (the binding safety property).
# --------------------------------------------------------------------------- #
def test_fetch_worldbank_refuses_when_kill_switch_on_injected(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    with pytest.raises(RuntimeError, match="airplane mode"):
        # The exploding getter proves the getter is NEVER reached before the guard.
        fetch_worldbank("NY.GDP.MKTP.CD", get=_exploding_getter)


def test_fetch_eurostat_refuses_when_kill_switch_on_injected(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    with pytest.raises(RuntimeError, match="airplane mode"):
        fetch_eurostat("PRC_HICP_MIDX", get=_exploding_getter)


def test_default_getter_path_refuses_when_kill_switch_on(monkeypatch) -> None:
    # With get=None and the kill switch ON, the up-front guard still refuses — proving
    # the default path attempts NO network. We additionally fail loudly if the default
    # getter is ever reached (it would try to build a real guarded session / socket).
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    monkeypatch.setattr(
        fetch,
        "_default_getter",
        lambda url: (_ for _ in ()).throw(
            AssertionError("default getter reached while kill switch is on")
        ),
    )
    with pytest.raises(RuntimeError, match="airplane mode"):
        fetch_worldbank("NY.GDP.MKTP.CD")
    with pytest.raises(RuntimeError, match="airplane mode"):
        fetch_eurostat("PRC_HICP_MIDX")
