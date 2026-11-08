"""
A Stop pressed and cleared again inside one request's flight is still a Stop (the engagement epoch, R327, ruled R614).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A recorder that decides after a request whether its failure was the target's reads the switch after the work
(R320). That is right while the switch is still engaged, and wrong when the operator pressed Stop and went back
online before the failure reached the caller: the switch then reads clear, and the operator's Stop was stored as
the target's failure. Measured with the production fetcher on ``*.example`` hosts
(``export-lane/law-switch-sweep-2026-10-27/REPORT.md``, scenarios S5 and S6): the host's robots.txt cached as
"unreachable" for an hour and written to the sidecar, and a tracked law document's check stamped, which keeps it
away for a day.

``activate_kill_switch()`` now counts itself. A recorder takes ``kill_switch_epoch()`` before its request and asks
``kill_switch_engaged_since()`` after it. This PR covers the two recorders R614 (3) names: the robots read in
``EthicalFetcher._get_robots`` and the law tracker's ``track_document``. Each case below drives the PRODUCTION
fetcher (``make_fetcher()``) with the airplane socket guard armed as boot arms it; a request is only ever really
made with the switch ENGAGED, so the guard refuses it before any socket call, and the hosts are ``*.example``
(RFC 2606, never resolvable). Every recorder is read against a control: an honest failure with no Stop, which must
be recorded exactly as before.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument
from src.ingest import (
    FetchFailed,
    RobotsUnavailable,
    activate_kill_switch,
    clear_kill_switch,
    kill_switch_active,
    kill_switch_engaged_since,
    kill_switch_epoch,
)
from src.ingest.fetch_verdict import KILL_SWITCH_REFUSAL
from src.law.track import track_document

_HOST_KEY = "https://gazette.example"
_URL = f"{_HOST_KEY}/act1"
_ROBOTS_OK = "User-agent: *\nAllow: /\n"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture(autouse=True)
def _offline_world(tmp_path, monkeypatch):
    """The switch clear, the guard armed as boot arms it (put back as found), and no proxy or fetch-mode setting."""
    from src.ingest import airplane

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_ROBOTS_CACHE_PERSIST", "1")  # the sidecar is where the one-hour verdict survives a restart
    monkeypatch.setenv("OO_FETCH_MIN_INTERVAL", "0")
    # A proxy would carry the request past the guard (the proxy is a different address) and turn its refusal into a
    # ProxyError; a user's machine has none.
    for var in (*_PROXY_VARS, "OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(airplane, "_airplane_armed", airplane._airplane_armed)  # restored at teardown
    assert airplane.install_airplane_socket_guard()
    clear_kill_switch()
    yield
    clear_kill_switch()


class _Stub:
    def __init__(self, url: str, status: int = 200, text: str = ""):
        self.status_code, self.text, self.content = status, text, text.encode()
        self.headers, self.url = {"Content-Type": "text/plain"}, url

    def close(self) -> None:
        pass


def _fetcher(tmp_path, *, robots, page):
    """The production fetcher, its session scripted per read kind; a list is one action per call, the last one repeats.

    ``ok`` a 200 (robots: allow all) · ``503`` a real host failure · ``down`` a real connection failure (no Stop) ·
    ``cut_clear`` Stop pressed while the request is in flight (the REAL guard refuses the connect and requests wraps
    its error), then cleared again before the failure reaches the caller.
    """
    from src.safety.fetcher import make_fetcher

    f = make_fetcher(retry_backoff_s=0, robots_cache_path=tmp_path / "robots.json")
    assert type(f.session).__name__ == "Session", type(f.session)  # a plain requests.Session: the real request path

    def guard(host, *_a, **_k):  # the real one starts with this check, then resolves the name (no lookups here)
        if kill_switch_active():
            raise FetchFailed(KILL_SWITCH_REFUSAL)

    f._guard_target = guard  # type: ignore[method-assign]
    scripts = {"robots": list(robots), "page": list(page)}
    real_get = f.session.get
    made: list[str] = []

    def get(url, **kw):
        kind = "robots" if url.endswith("/robots.txt") else "page"
        actions = scripts[kind]
        action = actions.pop(0) if len(actions) > 1 else actions[0]
        made.append(f"{kind}:{action}")
        if action == "ok":
            return _Stub(url, 200, _ROBOTS_OK)
        if action == "503":
            return _Stub(url, 503)
        if action == "down":
            raise requests.ConnectionError(f"connection refused by {url}")
        if action == "cut_clear":
            activate_kill_switch()
            assert kill_switch_active(), "a real request is only ever made with the switch engaged"
            try:
                return real_get(url, **kw)
            finally:
                clear_kill_switch()
        raise AssertionError(f"no action {action!r} for {url}")

    f.session.get = get  # type: ignore[method-assign]
    return f, made


def _sidecar(tmp_path) -> dict:
    path = tmp_path / "robots.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _db_and_doc():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    doc = LawDocument(
        jurisdiction="uk", title="Act", url=_URL, watched=True, last_status="unchanged",
        last_checked_at=datetime.now(UTC) - timedelta(days=3),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return db, doc


# --------------------------------------------------------------------------- #
#  The counter
# --------------------------------------------------------------------------- #
def test_the_epoch_counts_every_engagement_and_a_clear_does_not_undo_it():
    before = kill_switch_epoch()
    assert not kill_switch_engaged_since(before)
    activate_kill_switch()
    assert kill_switch_epoch() == before + 1
    clear_kill_switch()
    assert kill_switch_engaged_since(before), "engaged and cleared again since the capture: still a Stop"
    after = kill_switch_epoch()
    assert after == before + 1, "a clear is not an engagement"
    assert not kill_switch_engaged_since(after)
    activate_kill_switch()
    assert kill_switch_engaged_since(after), "engaged now"
    activate_kill_switch()  # engaging an engaged switch (the boot path does) still counts
    assert kill_switch_epoch() == before + 3
    # Engaged BEFORE the capture and still engaged: no new count, and it is still a Stop.
    during = kill_switch_epoch()
    assert kill_switch_engaged_since(during), "a switch engaged before the request and still engaged after it"


def test_concurrent_engagements_are_each_counted():
    """A lost count needs a thread switch inside the increment: standard CPython rarely makes one there, so this guards
    a free-threaded build more than it catches a removed lock today."""
    before = kill_switch_epoch()
    start = threading.Barrier(8)

    def press() -> None:
        start.wait()
        for _ in range(200):
            activate_kill_switch()

    threads = [threading.Thread(target=press, name=f"epoch-test-{i}") for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert kill_switch_epoch() == before + 8 * 200


# --------------------------------------------------------------------------- #
#  The robots read (S5): nothing cached, the refusal by name
# --------------------------------------------------------------------------- #
def test_a_stop_cleared_inside_the_robots_read_caches_nothing_and_is_the_refusal(tmp_path):
    f, made = _fetcher(tmp_path, robots=["cut_clear"], page=["ok"])
    with pytest.raises(FetchFailed) as exc:
        f.fetch(_URL, require_html=False)
    assert made == ["robots:cut_clear"], made
    assert not kill_switch_active(), "the switch was cleared again inside the flight"
    assert not isinstance(exc.value, RobotsUnavailable), "the host's robots.txt is not blamed for a Stop"
    assert str(exc.value) == KILL_SWITCH_REFUSAL
    assert f._robots == {} and f._robots_fails == {} and f._robots_cause == {}
    assert _sidecar(tmp_path) == {}, "a Stop must not reach the persisted verdicts"


def test_a_stop_pressed_before_the_robots_read_and_cleared_after_its_refusal_caches_nothing(tmp_path):
    """Engaged BEFORE the read's capture, so the count does not move; the read is refused by name; a clear lands before
    the read asks. Neither the switch nor the count says Stop then: the refusal's own sentence does."""
    f, made = _fetcher(tmp_path, robots=["ok"], page=["ok"])
    real = f._guarded_redirect_get

    def refused_then_cleared(url, **kw):
        try:
            return real(url, **kw)  # the switch is engaged: refused by name before the session is touched
        finally:
            clear_kill_switch()

    f._guarded_redirect_get = refused_then_cleared  # type: ignore[method-assign]
    activate_kill_switch()
    with pytest.raises(FetchFailed) as exc:
        f._get_robots(_HOST_KEY, urlparse(_URL))
    assert made == [], "no request was made"
    assert not kill_switch_active()
    assert str(exc.value) == KILL_SWITCH_REFUSAL
    assert f._robots == {} and f._robots_fails == {} and f._robots_cause == {}
    assert _sidecar(tmp_path) == {}


def test_a_clear_waits_for_an_engagement_to_be_counted(monkeypatch):
    """The set and the count are one step as far as a clear is concerned: a clear can never land between them, where
    a reader would see the switch clear and the count unchanged (the read of R614's PR reproduced that window).

    Driven through the real ``activate_kill_switch()``: its ``set()`` is held open on one thread while
    ``clear_kill_switch()`` runs on another, and the clear must not finish before the engagement is counted."""
    from src import ingest

    entered, release = threading.Event(), threading.Event()

    class _HeldSet(threading.Event):
        def set(self) -> None:
            super().set()
            entered.set()
            release.wait(5)  # the engagement stays between its set and its count until the test lets it go

    monkeypatch.setattr(ingest, "_KILL", _HeldSet())
    before = kill_switch_epoch()
    engage = threading.Thread(target=activate_kill_switch, name="epoch-test-engage")
    engage.start()
    assert entered.wait(5), "activate_kill_switch never reached the switch's set()"
    cleared = threading.Event()
    clear = threading.Thread(target=lambda: (clear_kill_switch(), cleared.set()), name="epoch-test-clear")
    clear.start()
    try:
        assert not cleared.wait(0.2), "a clear went through between an engagement's set and its count"
        assert kill_switch_epoch() == before, "the count moved before the set returned"
    finally:
        release.set()
        engage.join(5)
        clear.join(5)
    assert cleared.is_set(), "the clear finished once the engagement was counted"
    assert kill_switch_epoch() == before + 1
    assert not kill_switch_active(), "the clear came after the engagement"
    assert kill_switch_engaged_since(before)


def test_a_real_unreachable_robots_read_is_still_cached_for_an_hour(tmp_path):
    """The control: the same read failing with no Stop is the host's failure, as before."""
    f, made = _fetcher(tmp_path, robots=["down"], page=["ok"])
    with pytest.raises(RobotsUnavailable) as exc:
        f.fetch(_URL, require_html=False)
    assert made == ["robots:down"], made
    assert exc.value.cause == "unreachable"
    assert f._robots_fails[_HOST_KEY] == 1
    assert _sidecar(tmp_path)[_HOST_KEY]["cause"] == "unreachable"


def test_a_real_server_error_on_robots_is_still_cached(tmp_path):
    f, _made = _fetcher(tmp_path, robots=["503"], page=["ok"])
    with pytest.raises(RobotsUnavailable) as exc:
        f.fetch(_URL, require_html=False)
    assert exc.value.cause == "server_error"
    assert _sidecar(tmp_path)[_HOST_KEY]["cause"] == "server_error"


# --------------------------------------------------------------------------- #
#  The law tracker: no check stamped for a request a Stop cut short (S5 and S6)
# --------------------------------------------------------------------------- #
def test_a_stop_cleared_inside_the_robots_read_does_not_stamp_the_law_check(tmp_path):
    db, doc = _db_and_doc()
    before = doc.last_checked_at
    f, made = _fetcher(tmp_path, robots=["cut_clear"], page=["ok"])
    out = track_document(db, f, doc)
    db.refresh(doc)
    assert made == ["robots:cut_clear"], made
    assert out["status"] == "error" and out.get("offline") is True, out
    assert doc.last_checked_at == before, "the check was cut short by a Stop: it is not stamped"
    assert "robots" not in (doc.last_status or "").lower(), doc.last_status
    assert _sidecar(tmp_path) == {}


def test_a_stop_cleared_inside_the_page_read_does_not_stamp_the_law_check(tmp_path):
    db, doc = _db_and_doc()
    before = doc.last_checked_at
    f, made = _fetcher(tmp_path, robots=["ok"], page=["cut_clear"])
    out = track_document(db, f, doc)
    db.refresh(doc)
    assert made[0] == "robots:ok" and made[1:] and set(made[1:]) == {"page:cut_clear"}, made
    assert not kill_switch_active()
    assert out["status"] == "error", out
    assert doc.last_checked_at == before, "the check was cut short by a Stop: it is not stamped"
    # The robots answer was received before the Stop, so it is a real answer and stays cached.
    assert _sidecar(tmp_path)[_HOST_KEY]["kind"] == "parsed"


def test_a_real_failure_of_the_page_still_stamps_the_law_check(tmp_path):
    """The control: a 503 with no Stop is the document's failure, and the stamp is the back-off, as before."""
    db, doc = _db_and_doc()
    before = doc.last_checked_at
    f, _made = _fetcher(tmp_path, robots=["ok"], page=["503"])
    out = track_document(db, f, doc)
    db.refresh(doc)
    assert out["status"] == "error" and "offline" not in out, out
    assert doc.last_checked_at > before, "a real failed request is a check that happened"


class _RaisesOSError:
    """A fetcher double for the tracker's last branch: an error that is not a FetchError (the guard's own OSError)."""

    def __init__(self, *, stop: bool):
        self.stop = stop

    def fetch(self, url, **_kw):
        if self.stop:
            activate_kill_switch()
            clear_kill_switch()
        raise OSError("connection reset")


@pytest.mark.parametrize(("stop", "stamped"), [(True, False), (False, True)])
def test_an_error_that_is_not_a_fetch_error_follows_the_epoch_too(stop, stamped):
    db, doc = _db_and_doc()
    before = doc.last_checked_at
    out = track_document(db, _RaisesOSError(stop=stop), doc)
    db.refresh(doc)
    assert out["status"] == "error", out
    assert (doc.last_checked_at > before) is stamped, (stop, doc.last_checked_at, before)
