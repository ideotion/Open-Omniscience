"""
Offline tests for the OWID CSV fetch path of ``src/stats/fetch.py`` (Group N).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Network-FREE: the getter is always injected (a fake TEXT response) or the kill switch is
monkeypatched, so no real socket is ever opened. They assert the OWID grapher URL shape,
the single-metric value-column AUTO-DETECTION (and the loud failure when several data
columns are present), that the fetch DELEGATES to the merged ``parse_csv`` (honesty rules
carry through: a blank cell → ``value=None``, ``extracted_at`` preserved, ``Code`` used for
``ref_area``), and the binding safety property — the kill switch refuses BEFORE any getter
runs (no socket attempted while airplane mode is engaged), on the injected AND default paths.

Imports ``src.stats.fetch`` (the guarded factory pulls in cryptography), so this runs in CI,
not the bare sandbox; the URL + auto-detect + delegation ALGORITHM is also proven by a
standalone repro using the stdlib-only ``parse_csv``.
"""

from __future__ import annotations

import pytest

import src.stats.fetch as fetch
from src.stats.fetch import (
    OWID_GRAPHER_BASE,
    fetch_owid,
    owid_grapher_url,
)

_OWID_CSV = (
    "Entity,Code,Year,co2_per_capita\n"
    "France,FRA,2020,4.24\n"
    "Germany,DEU,2020,7.69\n"
    "France,FRA,2021,\n"  # a published gap — blank cell, kept as None
)


class _TextResponse:
    """A minimal requests-like response carrying ``.text`` (OWID CSV is text, not JSON)."""

    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


class _RecordingGetter:
    def __init__(self, text: str) -> None:
        self.text = text
        self.urls: list[str] = []

    def __call__(self, url: str) -> _TextResponse:
        self.urls.append(url)
        return _TextResponse(self.text)


def _exploding_getter(url: str) -> _TextResponse:
    raise AssertionError(f"getter was called while it must not be: {url!r}")


# --------------------------------------------------------------------------- #
# URL builder.
# --------------------------------------------------------------------------- #
def test_owid_grapher_url_shape_and_encoding() -> None:
    assert owid_grapher_url("co2-emissions-per-capita") == (
        f"{OWID_GRAPHER_BASE}/co2-emissions-per-capita.csv"
        "?v=1&csvType=full&useColumnShortNames=true"
    )
    # A space (defensive) is percent-encoded into the single path segment.
    assert "/odd%20slug.csv?" in owid_grapher_url("odd slug")


def test_owid_grapher_url_rejects_empty_slug() -> None:
    with pytest.raises(ValueError):
        owid_grapher_url("")
    with pytest.raises(ValueError):
        owid_grapher_url("   ")


# --------------------------------------------------------------------------- #
# fetch_owid — auto-detect the value column, delegate to parse_csv.
# --------------------------------------------------------------------------- #
def test_fetch_owid_autodetects_value_column_and_delegates(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    getter = _RecordingGetter(_OWID_CSV)
    figs = fetch_owid(
        "co2-emissions-per-capita", get=getter, extracted_at="2026-06-25T00:00:00Z"
    )
    assert len(figs) == 3
    fr20, de20, fr21 = figs
    assert fr20.agency == "owid"
    assert fr20.series_id == "co2-emissions-per-capita"  # defaults to the slug
    assert fr20.ref_area == "FRA"  # the Code column, not the Entity name
    assert fr20.value == 4.24
    assert fr20.extracted_at == "2026-06-25T00:00:00Z"
    assert de20.ref_area == "DEU" and de20.value == 7.69
    # The blank cell is a published gap, kept as None (never fabricated to 0).
    assert fr21.value is None and fr21.time_period == "2021"
    assert getter.urls == [owid_grapher_url("co2-emissions-per-capita")]


def test_fetch_owid_explicit_value_col_and_unit(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    getter = _RecordingGetter(_OWID_CSV)
    figs = fetch_owid(
        "co2-emissions-per-capita",
        value_col="co2_per_capita",
        unit="t per person",
        series_id="co2pc",
        get=getter,
        extracted_at="2026-06-25T00:00:00Z",
    )
    assert figs[0].series_id == "co2pc"
    assert all(f.unit == "t per person" for f in figs)  # carried verbatim from the caller


def test_fetch_owid_raises_loudly_on_ambiguous_value_column(monkeypatch) -> None:
    # Two non-key columns and no value_col → the auto-detect refuses (never guesses).
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: False)
    getter = _RecordingGetter("Entity,Code,Year,a,b\nFrance,FRA,2020,1,2\n")
    with pytest.raises(ValueError, match="auto-detect"):
        fetch_owid("multi", get=getter)


# --------------------------------------------------------------------------- #
# KILL SWITCH: refuse BEFORE any socket.
# --------------------------------------------------------------------------- #
def test_fetch_owid_refuses_when_kill_switch_on_injected(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    with pytest.raises(RuntimeError, match="airplane mode"):
        fetch_owid("co2-emissions-per-capita", get=_exploding_getter)


def test_fetch_owid_default_getter_refuses_when_kill_switch_on(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    monkeypatch.setattr(
        fetch,
        "_default_getter",
        lambda url: (_ for _ in ()).throw(
            AssertionError("default getter reached while kill switch is on")
        ),
    )
    with pytest.raises(RuntimeError, match="airplane mode"):
        fetch_owid("co2-emissions-per-capita")


# --------------------------------------------------------------------------- #
# R496: the default getter STREAMS and refuses as soon as the bound is passed.
# --------------------------------------------------------------------------- #
class _FakeStreamResponse:
    status_code = 200
    encoding = "utf-8"

    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}
        self.read = 0
        self.closed = False

    def iter_content(self, chunk_size=0):
        for c in self._chunks:
            self.read += len(c)
            yield c

    def raise_for_status(self):
        return None

    def close(self):
        self.closed = True


def _session_returning(resp):
    class _S:
        def get(self, url, **kw):
            assert kw.get("stream") is True
            return resp

    return lambda **kw: _S()


def test_default_getter_refuses_mid_stream_once_past_the_bound(monkeypatch) -> None:
    resp = _FakeStreamResponse([b"x" * 10] * 1000)
    monkeypatch.setattr(fetch, "guarded_session", _session_returning(resp))
    with pytest.raises(fetch.BodyTooLarge):
        fetch._default_getter("https://example.test/a.csv", max_bytes=25)
    assert resp.read == 30  # stopped at the third chunk, not after the download
    assert resp.closed


def test_default_getter_refuses_on_declared_length_before_reading(monkeypatch) -> None:
    resp = _FakeStreamResponse([b"x"], headers={"Content-Length": "999999"})
    monkeypatch.setattr(fetch, "guarded_session", _session_returning(resp))
    with pytest.raises(fetch.BodyTooLarge):
        fetch._default_getter("https://example.test/a.csv", max_bytes=100)
    assert resp.read == 0 and resp.closed


def test_default_getter_returns_the_body_within_the_bound(monkeypatch) -> None:
    resp = _FakeStreamResponse([b"Entity,Code,Year,v\n", b"A,AAA,2000,1\n"])
    monkeypatch.setattr(fetch, "guarded_session", _session_returning(resp))
    got = fetch._default_getter("https://example.test/a.csv", max_bytes=1000)
    got.raise_for_status()
    assert got.text.startswith("Entity,Code") and got.status_code == 200


def test_owid_and_gistemp_bounds_are_derived_and_grow_with_the_year() -> None:
    assert fetch.owid_max_bytes(now_year=2027) > fetch.owid_max_bytes(now_year=2026)
    assert fetch.owid_max_bytes(first_year=-10000) > fetch.owid_max_bytes()
