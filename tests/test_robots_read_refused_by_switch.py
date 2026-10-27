"""
A robots.txt read refused by the kill switch is not an answer about the host (R297).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``EthicalFetcher._get_robots`` caught every ``FetchError`` and ``requests`` error from its robots read as
"cannot safely determine robots -> fail closed", and cached that verdict (``cause: unreachable``, an hour,
persisted to the sidecar). The switch's own refusal is a ``FetchFailed``, so a Stop pressed between
``fetch()``'s first switch check and the robots read of a host whose verdict was not cached was filed as the
HOST's failure; a switch engaging while the robots request was in flight arrives the same way (the socket
guard's ``AirplaneModeError`` is wrapped in a ``requests`` error). Measured before the fix with the real
fetcher, the law tracker and one Stop: zero requests, ``RobotsUnavailable ... (unreachable)``, the document
stamped as checked, and the next pass (switch clear, fresh fetcher) stamped it again from the sidecar without
asking the host (R293, delta read 2, L2).

Two entry points, both pinned: the refusal at ``_guarded_redirect_get`` (Stop pressed before the read), and a
switch engaging while the request is in flight. What stays: a real unreachable host and a real 403 are still
cached with their cause, and a robots answer that WAS received is cached even if Stop is pressed right after.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument
from src.ingest import (
    EthicalFetcher,
    FetchFailed,
    RobotsUnavailable,
    activate_kill_switch,
    clear_kill_switch,
)
from src.ingest.airplane import AirplaneModeError
from src.law.track import track_document

_HOST = "https://gazette.example"
_SENTENCE = "network kill switch is active"


class _Resp:
    def __init__(self, status: int, text: str = ""):
        self.status_code, self.text, self.content = status, text, text.encode()
        self.headers, self.url = {"Content-Type": "text/plain"}, f"{_HOST}/robots.txt"


@pytest.fixture(autouse=True)
def _switch_clear(monkeypatch):
    monkeypatch.setenv("OO_ROBOTS_CACHE_PERSIST", "1")  # the sidecar is where the one-hour verdict survives a restart
    clear_kill_switch()
    yield
    clear_kill_switch()


def _fetcher(tmp_path):
    """A REAL ``EthicalFetcher`` (real session, so the switch's own refusal in ``_guarded_redirect_get`` is live)."""
    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, robots_cache_path=tmp_path / "robots.json")
    f._guard_target = lambda host: None  # type: ignore[method-assign]  # no DNS in a test
    return f


def _sidecar(tmp_path) -> dict:
    path = tmp_path / "robots.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _nothing_cached(f, tmp_path) -> None:
    assert f._robots == {} and f._robots_fails == {} and f._robots_cause == {}
    assert _sidecar(tmp_path) == {}, "a refusal by the switch must not reach the persisted verdicts"


# --------------------------------------------------------------------------- #
#  Entry point 1: Stop pressed before the robots read
# --------------------------------------------------------------------------- #
def test_a_robots_read_refused_by_the_switch_is_raised_as_the_refusal_and_not_cached(tmp_path):
    f = _fetcher(tmp_path)
    activate_kill_switch()
    with pytest.raises(FetchFailed) as exc:
        f._get_robots(_HOST, urlparse(f"{_HOST}/act1"))
    assert str(exc.value).startswith(_SENTENCE)
    _nothing_cached(f, tmp_path)


def test_stop_pressed_while_a_fetch_waits_for_its_host_is_not_filed_as_robots_unreachable(tmp_path):
    """The window of the finding: past ``fetch()``'s own switch check, then the host lock, then the robots read."""
    f = _fetcher(tmp_path)
    real_lock = f._host_lock

    @contextmanager
    def stop_pressed_while_waiting(netloc):
        with real_lock(netloc):
            activate_kill_switch()
            yield

    f._host_lock = stop_pressed_while_waiting  # type: ignore[method-assign]
    with pytest.raises(FetchFailed) as exc:
        f.fetch(f"{_HOST}/act1", require_html=False)
    assert not isinstance(exc.value, RobotsUnavailable), "the host's robots.txt was never asked"
    assert str(exc.value).startswith(_SENTENCE)
    _nothing_cached(f, tmp_path)

    # The consequence: once the switch clears the SAME fetcher asks the host again, instead of serving a cached
    # "unreachable" for an hour.
    clear_kill_switch()
    f._host_lock = real_lock  # type: ignore[method-assign]
    asked: list[str] = []

    def answers(url, **_kw):
        asked.append(url)
        return _Resp(404), url  # no robots.txt: everything allowed

    f._guarded_redirect_get = answers  # type: ignore[method-assign]
    f._http_get = lambda url, extra_headers=None, proxies=None: (_PageResp(), url)  # type: ignore[method-assign]
    f.fetch(f"{_HOST}/act1", require_html=False)
    assert f"{_HOST}/robots.txt" in asked, "robots.txt must be asked again after the refusal"


class _PageResp:
    status_code = 200
    headers = {"Content-Type": "text/html"}
    content = b"<html><body>x</body></html>"
    text = "<html><body>x</body></html>"

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------- #
#  Entry point 2: the switch engages while the robots request is in flight
# --------------------------------------------------------------------------- #
def test_a_switch_engaging_mid_request_is_the_refusal_not_an_unreachable_host(tmp_path):
    """The socket guard's ``AirplaneModeError`` (an OSError) reaches ``_get_robots`` wrapped in a requests error."""
    f = _fetcher(tmp_path)

    def cut_off(url, **_kw):
        activate_kill_switch()  # Stop pressed after the request began
        raise requests.ConnectionError(AirplaneModeError("blocked"))

    f._guarded_redirect_get = cut_off  # type: ignore[method-assign]
    with pytest.raises(FetchFailed) as exc:
        f._get_robots(_HOST, urlparse(f"{_HOST}/act1"))
    assert str(exc.value).startswith(_SENTENCE)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__, "the request error's words (host, URL) are not chained into the refusal"
    _nothing_cached(f, tmp_path)


def test_a_failure_that_is_not_the_refusal_is_raised_as_it_is_when_the_switch_is_set(tmp_path):
    """Under a set switch a ``FetchError`` is re-raised unchanged, whatever its words (a redirect loop, a lookup the
    airplane layer refused): it is not relabelled with the refusal sentence, and it is not cached either."""
    f = _fetcher(tmp_path)
    original = FetchFailed(f"too many redirects for {_HOST}/robots.txt")

    def loops(url, **_kw):
        activate_kill_switch()
        raise original

    f._guarded_redirect_get = loops  # type: ignore[method-assign]
    with pytest.raises(FetchFailed) as exc:
        f._get_robots(_HOST, urlparse(f"{_HOST}/act1"))
    assert exc.value is original
    _nothing_cached(f, tmp_path)


def test_a_switch_engaging_mid_fetch_through_fetch_is_not_robots_unavailable(tmp_path):
    f = _fetcher(tmp_path)

    def cut_off(url, **_kw):
        activate_kill_switch()
        raise requests.ConnectionError("connection reset")

    f._guarded_redirect_get = cut_off  # type: ignore[method-assign]
    with pytest.raises(FetchFailed) as exc:
        f.fetch(f"{_HOST}/act1", require_html=False)
    assert not isinstance(exc.value, RobotsUnavailable)
    _nothing_cached(f, tmp_path)


# --------------------------------------------------------------------------- #
#  The consequence R293 cares about: the law document is not stamped, on this pass or the next
# --------------------------------------------------------------------------- #
def test_the_law_tracker_gives_the_time_back_and_the_next_pass_asks_the_host(tmp_path):
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    doc = LawDocument(
        jurisdiction="uk", title="Act", url=f"{_HOST}/act1", watched=True, last_status="unchanged",
        last_checked_at=datetime.now(UTC) - timedelta(days=3),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    before = doc.last_checked_at

    f = _fetcher(tmp_path)
    real_lock = f._host_lock

    @contextmanager
    def stop_pressed_while_waiting(netloc):
        with real_lock(netloc):
            activate_kill_switch()
            yield

    f._host_lock = stop_pressed_while_waiting  # type: ignore[method-assign]
    out = track_document(db, f, doc)
    db.refresh(doc)
    assert out["status"] == "error" and out["offline"] is True, "named as the switch's refusal, not the host's"
    assert doc.last_checked_at == before, "no request was made: no check happened"
    assert "robots" not in (doc.last_status or "").lower(), "the host's robots.txt is not blamed"

    # next pass: the switch is clear and a FRESH fetcher reads the same sidecar
    clear_kill_switch()
    f2 = _fetcher(tmp_path)
    asked: list[str] = []

    def answers(url, **_kw):
        asked.append(url)
        return _Resp(404), url

    f2._guarded_redirect_get = answers  # type: ignore[method-assign]
    f2._http_get = lambda url, extra_headers=None, proxies=None: (_PageResp(), url)  # type: ignore[method-assign]
    track_document(db, f2, doc)
    assert f"{_HOST}/robots.txt" in asked, "the sidecar must not carry a verdict no request produced"


# --------------------------------------------------------------------------- #
#  Controls: what must keep being cached
# --------------------------------------------------------------------------- #
def test_a_real_unreachable_host_is_still_cached_with_its_cause(tmp_path):
    f = _fetcher(tmp_path)

    def down(url, **_kw):
        raise requests.ConnectionError("connection refused")

    f._guarded_redirect_get = down  # type: ignore[method-assign]
    with pytest.raises(RobotsUnavailable) as exc:
        f._enforce_robots(f"{_HOST}/act1", _HOST, None)
    assert exc.value.cause == "unreachable"
    assert _HOST in f._robots and f._robots_fails[_HOST] == 1
    assert _sidecar(tmp_path)[_HOST]["cause"] == "unreachable"


def test_a_real_refusal_by_the_host_is_still_cached_with_its_cause(tmp_path):
    f = _fetcher(tmp_path)
    f._guarded_redirect_get = lambda url, **_kw: (_Resp(403), url)  # type: ignore[method-assign]
    with pytest.raises(RobotsUnavailable) as exc:
        f._enforce_robots(f"{_HOST}/act1", _HOST, None)
    assert exc.value.cause == "refused"
    assert _sidecar(tmp_path)[_HOST]["cause"] == "refused"


def test_a_robots_answer_that_was_received_is_cached_even_if_stop_is_pressed_right_after(tmp_path):
    f = _fetcher(tmp_path)

    def answer_then_stop(url, **_kw):
        resp = _Resp(200, "User-agent: *\nDisallow: /private\n")
        activate_kill_switch()  # Stop pressed after the host had answered: the answer is real
        return resp, url

    f._guarded_redirect_get = answer_then_stop  # type: ignore[method-assign]
    parser = f._get_robots(_HOST, urlparse(f"{_HOST}/act1"))
    assert parser is not None and not parser.can_fetch(f.user_agent, f"{_HOST}/private")
    assert _sidecar(tmp_path)[_HOST]["kind"] == "parsed"


def test_a_403_that_was_received_is_cached_as_refused_even_if_stop_is_pressed_right_after(tmp_path):
    """A 403 is an answer the host gave, so it never reaches the catch: it is cached with its cause like any answer."""
    f = _fetcher(tmp_path)

    def refuse_then_stop(url, **_kw):
        resp = _Resp(403)
        activate_kill_switch()
        return resp, url

    f._guarded_redirect_get = refuse_then_stop  # type: ignore[method-assign]
    assert f._get_robots(_HOST, urlparse(f"{_HOST}/act1")) is None
    assert f._robots_fails[_HOST] == 1
    assert _sidecar(tmp_path)[_HOST]["cause"] == "refused"


def test_a_real_failure_under_a_clear_switch_whose_text_names_it_is_still_a_host_failure(tmp_path):
    """The switch is CLEAR here, so even a FetchFailed whose words are the sentence is the host's problem as far as
    this guard is concerned: it decides by the switch, never by a text."""
    f = _fetcher(tmp_path)

    def says_so(url, **_kw):
        raise FetchFailed(f"HTTP 502 for {url} ({_SENTENCE})")

    f._guarded_redirect_get = says_so  # type: ignore[method-assign]
    with pytest.raises(RobotsUnavailable) as exc:
        f._enforce_robots(f"{_HOST}/act1", _HOST, None)
    assert exc.value.cause == "unreachable"
