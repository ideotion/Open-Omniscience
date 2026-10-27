"""A Stop is never a market feed's outcome (R320; the market half of the R313 family, after PR 1570 fixed the preflight and feed verification).

``import_feed`` classified a failed fetch from the ERROR'S TEXT alone, and a refusal is recognised only by OUR sentence at the start (R298). A
Stop that lands during the request arrives as the raw requests error instead, and through an HTTP proxy as ``request error for <url>:
('Connection aborted.', AirplaneModeError(...))``: not our sentence, so the failure was filed as the FEED'S (``refused``, retryable), then
retried after a sleep, in airplane mode. The switch is now read after the failed check. These tests cut through the REAL requests/urllib3
wrapping, not a hand-typed string, and pin both directions: the same failure with the switch clear is still that feed's failure.
"""

from __future__ import annotations

import contextlib

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from urllib3.exceptions import ProtocolError

from src.database.models import Base
from src.ingest import (
    FetchFailed,
    RobotsDisallowed,
    activate_kill_switch,
    clear_kill_switch,
    kill_switch_active,
)
from src.ingest.airplane import AirplaneModeError
from src.markets import csv_feeds as C

_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO"
_REFUSAL = "airplane mode is engaged: refusing a network connection to 'fred.stlouisfed.org'. No packet leaves the machine while offline"


def _proxy_shape() -> str:
    """The text exactly as the fetcher reports a Stop that landed inside a proxied request."""
    err = requests.ConnectionError(
        ProtocolError("Connection aborted.", AirplaneModeError(_REFUSAL))
    )
    return f"request error for {_URL}: {err}"


class _Fetcher:
    def __init__(self, exc: Exception, *, engage: bool = False) -> None:
        self.exc, self.engage, self.calls = exc, engage, 0

    def fetch(self, url, **_kw):
        self.calls += 1
        if self.engage:
            activate_kill_switch()
        raise self.exc


@contextlib.contextmanager
def _switch(on: bool):
    (activate_kill_switch if on else clear_kill_switch)()
    try:
        yield
    finally:
        clear_kill_switch()


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


@pytest.fixture()
def slept(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr(C.time, "sleep", calls.append)
    return calls


def _import(session, fetcher):
    return C.import_feed(session, url=_URL, symbol="WTI", fetcher=fetcher)


def test_the_proxy_shape_is_not_our_sentence_so_the_classifier_alone_refuses_it():
    """The premise: the anchored match (R298) must keep refusing it, or the fix below is dead code."""
    text = _proxy_shape()
    assert text.startswith("request error for") and "AirplaneModeError" in text
    assert C.classify_fetch_failure(FetchFailed(text))[0] != "offline"


def test_a_stop_inside_a_proxied_request_is_offline_and_is_not_retried(session, slept):
    with _switch(True):
        f = _Fetcher(FetchFailed(_proxy_shape()))
        out = _import(session, f)
    assert (out.status, out.verdict, out.retryable, out.attempts) == (
        "fetch_failed",
        "offline",
        False,
        1,
    )
    assert "kill switch" in (out.verdict_note or "")
    assert f.calls == 1 and slept == [], (
        "no second attempt and no sleep: the person's own setting is not a transient fault"
    )


def test_a_stop_that_lands_during_the_request_is_offline_whatever_the_error_says(session, slept):
    f = _Fetcher(
        FetchFailed("HTTPSConnectionPool(host='x', port=443): Max retries exceeded"), engage=True
    )
    try:
        out = _import(session, f)
    finally:
        clear_kill_switch()
    assert out.verdict == "offline" and out.attempts == 1 and f.calls == 1 and slept == []


def test_the_same_failure_with_the_switch_clear_is_still_that_feeds_failure(session, slept):
    assert not kill_switch_active()
    f = _Fetcher(FetchFailed(_proxy_shape()))
    out = _import(session, f)
    assert out.verdict == "refused" and out.retryable is True
    assert out.attempts == 2 and f.calls == 2 and len(slept) == 1


def test_a_robots_disallow_read_before_the_stop_is_kept_as_the_hosts_answer(session, slept):
    with _switch(True):
        out = _import(session, _Fetcher(RobotsDisallowed("robots.txt disallows " + _URL)))
    assert out.verdict == "robots-disallowed"
