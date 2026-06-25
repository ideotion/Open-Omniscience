"""
Offline tests for the JSON-stat fetch path of ``src/stats/fetch.py`` (Group N).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Network-FREE: the getter is always injected (a fake JSON response) or the kill switch is
monkeypatched. They assert the caller-URL passthrough (we never fabricate a JSON-stat
endpoint — the caller supplies the documented query URL verbatim), that a non-http(s) URL
is rejected LOUDLY, that the fetch DELEGATES to the merged ``parse_jsonstat`` (honesty carries
through: a ``null`` cell → ``value=None``, ``extracted_at`` preserved, ``series_id`` pinned),
and the binding safety property — the kill switch refuses BEFORE any getter runs.

Imports ``src.stats.fetch`` (the guarded factory pulls in cryptography), so this runs in CI,
not the bare sandbox; the URL-guard + delegation algorithm is also proven by a standalone
repro using the stdlib-only ``parse_jsonstat``.
"""

from __future__ import annotations

import pytest

import src.stats.fetch as fetch
from src.stats.fetch import fetch_jsonstat

# A 2 (geo) x 2 (time) JSON-stat cube, row-major: idx = geo*2 + time.
_JSONSTAT = {
    "class": "dataset",
    "id": ["geo", "time"],
    "size": [2, 2],
    "dimension": {
        "geo": {"category": {"index": {"FR": 0, "DE": 1}, "label": {"FR": "France", "DE": "Germany"}}},
        "time": {"category": {"index": {"2020": 0, "2021": 1}}},
    },
    "value": [10.0, None, 20.0, 22.0],  # FR/2021 is a published gap (null)
}


class _JsonResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _RecordingGetter:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str) -> _JsonResponse:
        self.urls.append(url)
        return _JsonResponse(self.payload)


def _exploding_getter(url: str) -> _JsonResponse:
    raise AssertionError(f"getter was called while it must not be: {url!r}")


_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10_gdp?format=JSON"


def test_fetch_jsonstat_passes_the_caller_url_and_delegates(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    getter = _RecordingGetter(_JSONSTAT)
    figs = fetch_jsonstat(
        _URL, agency="eurostat", series_id="GDP", get=getter, extracted_at="2026-06-25T00:00:00Z"
    )
    assert len(figs) == 4
    cells = {(f.ref_area, f.time_period): f for f in figs}
    assert cells[("FR", "2020")].value == 10.0
    assert cells[("DE", "2021")].value == 22.0
    # The published gap (null) survives delegation: value None, never dropped/zeroed.
    assert cells[("FR", "2021")].value is None
    # series_id pinned + agency + vintage carried through.
    assert all(f.series_id == "GDP" and f.agency == "eurostat" for f in figs)
    assert all(f.extracted_at == "2026-06-25T00:00:00Z" for f in figs)
    # The caller's URL is used verbatim (no fabricated endpoint).
    assert getter.urls == [_URL]


def test_fetch_jsonstat_rejects_non_http_url(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    for bad in ("ftp://x/y", "file:///etc/passwd", "  ", "not-a-url"):
        with pytest.raises(ValueError, match="http"):
            fetch_jsonstat(bad, agency="x", get=_exploding_getter)


def test_fetch_jsonstat_refuses_when_kill_switch_on_injected(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    with pytest.raises(RuntimeError, match="airplane mode"):
        fetch_jsonstat(_URL, agency="eurostat", get=_exploding_getter)


def test_fetch_jsonstat_default_getter_refuses_when_kill_switch_on(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    monkeypatch.setattr(
        fetch,
        "_default_getter",
        lambda url: (_ for _ in ()).throw(
            AssertionError("default getter reached while kill switch is on")
        ),
    )
    with pytest.raises(RuntimeError, match="airplane mode"):
        fetch_jsonstat(_URL, agency="eurostat")
