"""
A Stop is never the target's failure in six more recorders, read through the engagement epoch (R617 PR A; R614, R320).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The R617 audit listed recorders outside R614's two PRs that file a failed request against its target. Most read the switch nowhere after
the request, so a Stop still engaged was recorded too (R320), and the rest read it only as it is now, so a Stop pressed and cleared again
inside the request was recorded (R614). Each now takes ``kill_switch_epoch()`` before its request (before its own head check where it has
one) and asks ``kill_switch_engaged_since`` after it:

* the stat subscriptions (``refresh_due``): the cut subscription, and every later one the up-front refusal reached, stamped ``error`` for
  ``interval_days`` (30 by default);
* the hazard snapshot (``auto_snapshot_due``) and its manual twin (``POST /api/signals/hazards/snapshot?refresh=1``): the snapshot
  REPLACED by the feeds that happened to answer, held for 6 h;
* the qualification pass (``run_qualification_pass``): the cut candidate, and every later one, judged, stamped or logged as having no
  evidence; the bulk job pauses on it instead of reading the empty pass as an empty backlog;
* world discovery (``run_world_discovery``): a country the Stop cut mid-way marked done for good, and the ``"airplane" in str(exc)``
  substring replaced by the epoch read;
* the wiki dump and OSM region downloads (``_download``, ``_pump``): the entry stored as ``error``, waiting for the operator;
* the market feeds (``import_feed`` through ``classify_failed_check(exc, since=)``): the cut attempt filed as the feed's own verdict.

Where the production fetcher or session runs, the airplane socket guard is armed as boot arms it and a real request is only ever made with
the switch ENGAGED, so the guard refuses it before any socket call; hosts are ``*.example`` (RFC 2606) and no proxy variable is set. Where
the recorder is what is under test, its own seam stands in for the network. Every recorder is read against a control: the same failure
with no Stop, recorded as before.
"""

from __future__ import annotations

import inspect
import json
import pathlib
import sys
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.ingest as ingest_pkg
from src.database.models import Base, Source, SourceQualificationAttempt
from src.ingest import FetchFailed, activate_kill_switch, clear_kill_switch, kill_switch_active
from src.ingest.fetch_verdict import KILL_SWITCH_REFUSAL, NETWORK_REFUSED
from src.safety.fetcher import NetworkBlocked, make_fetcher

#: The raw requests error of a Stop on the LAST request through an HTTP proxy: not our sentence at the start, so only the switch or the
#: epoch can say it was a Stop.
RAW_STOP = "('Connection aborted.', AirplaneModeError('airplane mode is engaged: refusing a network connection to a.example:443'))"
RESET = "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    """The switch clear, the guard armed as boot arms it (put back as found), and no proxy or fetch-mode setting."""
    from src.ingest import airplane

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_FETCH_MIN_INTERVAL", "0")
    monkeypatch.setenv("OO_FETCH_RETRY_BACKOFF", "0")
    for var in (*_PROXY_VARS, "OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(airplane, "_airplane_armed", airplane._airplane_armed)  # restored at teardown
    assert airplane.install_airplane_socket_guard()
    clear_kill_switch()
    yield
    clear_kill_switch()


def _stop_and_clear() -> None:
    """The operator presses Stop and goes back online again: the count moves, the switch reads clear."""
    activate_kill_switch()
    clear_kill_switch()


def _guard_refuses_a_connect(url: str = "https://a.example/x") -> None:
    """A real request made with the switch ENGAGED: the armed socket guard refuses it before any socket call, and requests wraps that
    refusal as it would a Stop landing inside a connect. Never reads proxy settings, so nothing is sent anywhere."""
    assert kill_switch_active(), "a real request is only ever made with the switch engaged"
    s = requests.Session()
    s.trust_env = False
    try:
        s.get(url, timeout=5)
    finally:
        s.close()
    raise AssertionError("the armed socket guard let a request through")  # pragma: no cover - the get above always raises


def _cut_and_clear(url: str = "https://a.example/x") -> None:
    """A Stop pressed while the request is in flight (the REAL guard refuses the connect), cleared before the failure reaches the caller."""
    activate_kill_switch()
    try:
        _guard_refuses_a_connect(url)
    finally:
        clear_kill_switch()


def _stop_right_after_the_check(monkeypatch, function, anchor_line):
    """The first ``if kill_switch_active():`` in ``function`` after ``anchor_line`` reads clear, and the operator presses Stop the instant
    after it, before the request that check lets go: the case where an epoch taken AFTER the check would already hold the Stop and read the
    request's refusal as the target's failure once the switch is cleared again. (R614's ``_stop_right_after_the_loop_check``, any anchor.)"""
    lines, first = inspect.getsourcelines(function)
    start = next(i for i, line in enumerate(lines) if line.strip() == anchor_line)
    target = first + next(i for i in range(start, len(lines)) if lines[i].strip() == "if kill_switch_active():")
    real = ingest_pkg.kill_switch_active
    fired: list[int] = []

    def check() -> bool:
        engaged = real()
        caller = sys._getframe(1)
        if not fired and caller.f_code is function.__code__ and caller.f_lineno == target:
            fired.append(target)
            activate_kill_switch()
        return engaged

    monkeypatch.setattr(ingest_pkg, "kill_switch_active", check)
    return fired


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


@pytest.fixture()
def scope(db):
    """A session factory that yields the SAME test session (never closes it)."""

    @contextmanager
    def _scope():
        yield db
        db.commit()

    return _scope


class _Stub:
    def __init__(self, url, status=200, body=b"", headers=None):
        self.status_code, self.url, self._body = status, url, body
        self.headers = {"Content-Type": "text/html", **(headers or {})}
        self.content, self.text, self.encoding = body, body.decode("utf-8", "replace"), "utf-8"

    def iter_content(self, chunk_size=16384):
        yield self._body

    def close(self):
        pass


def _fetcher(tmp_path, calls, *, bodies=None, cut_clear_on=None, raw_clear_on=None, down_on=None, retries=None):
    """The production fetcher over a scripted ``session.get`` (R614's test helper), every scripted fault firing ONCE, on the first URL
    ending with it: ``cut_clear_on`` Stop pressed while the request is in flight (the REAL guard refuses the connect and requests wraps
    its error), then cleared · ``raw_clear_on`` the same Stop on a last request, arriving as the raw proxy error with the switch already
    clear · ``down_on`` a host's own reset, no Stop. Otherwise robots allow all, ``bodies`` maps a URL to ``(content type, bytes)``, and
    anything else is a 503."""
    f = make_fetcher(
        retry_backoff_s=0, robots_cache_path=pathlib.Path(tmp_path) / "robots.json",
        **({"max_retries": retries} if retries is not None else {}),
    )
    assert type(f.session).__name__ == "Session", type(f.session)  # a plain requests.Session: the real request path

    def guard(host, *_a, **_k):  # the first line of ``_guard_target``: no lookup is ever made
        if kill_switch_active():
            raise FetchFailed(KILL_SWITCH_REFUSAL)

    f._guard_target = guard  # type: ignore[method-assign]
    real_get = f.session.get
    pending = {"cut": cut_clear_on, "raw": raw_clear_on, "down": down_on}

    def fires(kind: str, url: str) -> bool:
        if pending[kind] is not None and url.endswith(pending[kind]):
            pending[kind] = None
            return True
        return False

    def get(url, **kw):
        calls.append(url)
        if fires("raw", url):
            _stop_and_clear()
            raise requests.exceptions.ProxyError(RAW_STOP)
        if fires("down", url):
            raise requests.exceptions.ProxyError(RESET)
        if fires("cut", url):
            activate_kill_switch()
            assert kill_switch_active(), "a real request is only ever made with the switch engaged"
            try:
                return real_get(url, **kw)
            finally:
                clear_kill_switch()
        if kill_switch_active():
            return real_get(url, **kw)
        if url.endswith("/robots.txt"):
            return _Stub(url, 200, b"User-agent: *\nAllow: /\n", {"Content-Type": "text/plain"})
        if bodies and url in bodies:
            ctype, body = bodies[url]
            return _Stub(url, 200, body, {"Content-Type": ctype})
        return _Stub(url, 503)

    f.session.get = get  # type: ignore[method-assign]
    return f


# --------------------------------------------------------------------------- #
#  1. The stat subscriptions (``refresh_due``)
# --------------------------------------------------------------------------- #
def _subs(db, n=2):
    from src.stats import subscriptions as S

    for i in range(n):
        S.record_subscription(db, source="worldbank", indicator=f"IND{i}", country="FR")
    db.commit()
    return S


def _stamps(db):
    from src.database.models import StatSubscription

    db.expire_all()
    return {s.indicator: (s.last_fetched_at, s.last_status) for s in db.query(StatSubscription).all()}


def test_stats_a_stop_cleared_inside_a_subscriptions_request_stamps_nothing(db):
    S = _subs(db)
    asked: list[str] = []

    def get(url):
        asked.append(url)
        _cut_and_clear()

    out = S.refresh_due(db, get=get)
    assert not kill_switch_active()
    assert _stamps(db) == {"IND0": (None, None), "IND1": (None, None)}, "a cleared Stop stamped a subscription error for 30 days"
    assert out["errors"] == 0 and out["skipped_offline"] == 2 and len(asked) == 1, (out, asked)
    assert len(S.due_subscriptions(db)) == 2, "both stay due, so the next online pass asks them"


def test_stats_a_stop_still_engaged_stamps_neither_the_cut_subscription_nor_the_ones_after_it(db):
    """No read after the request at all before R617: the cut one AND every later one (refused up front by ``fetch_worldbank``) were stamped."""
    S = _subs(db)

    def get(url):
        activate_kill_switch()
        _guard_refuses_a_connect()

    out = S.refresh_due(db, get=get)
    assert kill_switch_active()
    assert _stamps(db) == {"IND0": (None, None), "IND1": (None, None)}, "a Stop still engaged was stamped as the subscriptions' error"
    assert out["errors"] == 0 and out["skipped_offline"] == 2, out


def test_stats_a_stop_pressed_just_after_the_subscription_check_is_a_stop(db, monkeypatch):
    """The epoch is taken before the check that lets the subscription's request go, so a Stop between the two is in its window."""
    from src.stats import fetch as statfetch

    S = _subs(db, n=1)
    real = statfetch.fetch_worldbank

    def refused(*a, **k):
        assert kill_switch_active(), "premise: the Stop is engaged when the subscription is asked"
        try:
            return real(*a, **k)  # refused by name, up front
        finally:
            clear_kill_switch()  # back online before the failure is classified

    monkeypatch.setattr(statfetch, "fetch_worldbank", refused)
    fired = _stop_right_after_the_check(monkeypatch, S.refresh_due, "for i, s in enumerate(due):")
    out = S.refresh_due(db, get=lambda url: pytest.fail("no request may be made"))
    assert fired, "premise: the Stop landed right after the loop's check"
    assert _stamps(db) == {"IND0": (None, None)} and out["errors"] == 0 and out["skipped_offline"] == 1, (out, _stamps(db))


def test_stats_a_genuine_failure_with_no_stop_is_stamped_the_control(db):
    S = _subs(db)

    def get(url):
        raise requests.exceptions.ConnectionError(RESET)

    out = S.refresh_due(db, get=get)
    stamps = _stamps(db)
    assert out["errors"] == 2 and out["skipped_offline"] == 0, out
    assert all(at is not None and status.startswith("error:") for at, status in stamps.values()), stamps


# --------------------------------------------------------------------------- #
#  2. The hazard snapshot (``auto_snapshot_due`` and the manual refresh route)
# --------------------------------------------------------------------------- #
_USGS = "https://usgs.example/quakes.geojson"
_GDACS = "https://gdacs.example/events.json"
_USGS_ONE = (
    b'{"features":[{"id":"us-test-1","properties":{"title":"M 5.0 - Testland","mag":5.0,'
    b'"place":"Testland","time":1700000000000,"url":"https://usgs.example/x"},'
    b'"geometry":{"type":"Point","coordinates":[10.0,20.0]}}]}'
)
_OLD = {"source": "usgs", "id": "us-old", "type": "earthquake", "severity": "major", "title": "the previous snapshot",
        "magnitude": 7.0, "lat": 1.0, "lon": 2.0, "place": "Oldplace", "time": "2026-01-01T00:00:00Z", "url": "https://usgs.example/old"}


@pytest.fixture()
def hazards(monkeypatch, tmp_path):
    """The two feeds on ``*.example`` hosts and a STALE previous snapshot, so the pass is due."""
    from datetime import UTC, datetime, timedelta

    from src.api import hazards as H
    from src.hazards import store

    monkeypatch.setattr(H, "_FEEDS", {"usgs": _USGS, "gdacs": _GDACS})
    path = tmp_path / "hazards_snapshot.json"
    monkeypatch.setattr(store, "_snapshot_path", lambda: path)
    store.save_snapshot([_OLD], now=datetime.now(UTC) - timedelta(days=1))
    before = path.read_text("utf-8")
    return SimpleNamespace(path=path, before=before, bodies={_USGS: ("application/json", _USGS_ONE)})


def _snap_ids(path):
    return [r["id"] for r in json.loads(path.read_text("utf-8"))["records"]]


def test_hazards_a_stop_cleared_inside_one_feed_keeps_the_previous_snapshot(hazards, tmp_path):
    from src.hazards import track

    res = track.auto_snapshot_due(_fetcher(tmp_path, [], bodies=hazards.bodies, cut_clear_on="/events.json", retries=0))
    assert not kill_switch_active()
    assert res == {"skipped_offline": True}, res
    assert hazards.path.read_text("utf-8") == hazards.before, f"a cleared Stop replaced the snapshot: {_snap_ids(hazards.path)}"


def test_hazards_a_stop_still_engaged_after_one_feed_answered_keeps_the_previous_snapshot(hazards, tmp_path):
    """No read after the relay before R617: USGS answered, the Stop then refused GDACS, and a snapshot without GDACS was saved."""
    from src.hazards import track

    class _StopAfterFirst:
        def __init__(self, inner):
            self.inner = inner

        def fetch(self, url, **kw):
            try:
                return self.inner.fetch(url, **kw)
            finally:
                activate_kill_switch()  # the Stop lands as the first feed's answer comes back, and stays

    res = track.auto_snapshot_due(_StopAfterFirst(_fetcher(tmp_path, [], bodies=hazards.bodies)))
    assert kill_switch_active()
    assert res == {"skipped_offline": True}, res
    assert hazards.path.read_text("utf-8") == hazards.before, f"a Stop saved a partial snapshot: {_snap_ids(hazards.path)}"


def test_hazards_a_stop_pressed_just_after_the_head_check_is_a_stop(hazards, tmp_path, monkeypatch):
    """The epoch is taken before the check that lets the relay go: refused by name, cleared, then the other feed answers online."""
    from src.api import hazards as H
    from src.hazards import track

    monkeypatch.setattr(H, "_FEEDS", {"gdacs": _GDACS, "usgs": _USGS})  # the refused feed first, the one that answers after it
    calls: list[str] = []
    inner = _fetcher(tmp_path, calls, bodies=hazards.bodies)

    class _ClearAfterFirstRefusal:
        def fetch(self, url, **kw):
            try:
                return inner.fetch(url, **kw)
            finally:
                clear_kill_switch()

    fired = _stop_right_after_the_check(monkeypatch, track.auto_snapshot_due, 'return {"skipped": "fresh", "age_hours": age}')
    res = track.auto_snapshot_due(_ClearAfterFirstRefusal())
    assert fired, "premise: the Stop landed right after the head check"
    assert _GDACS not in calls and _USGS in calls, "premise: the first feed was refused by name and the second asked online"
    assert res == {"skipped_offline": True}, res
    assert hazards.path.read_text("utf-8") == hazards.before


def test_hazards_a_feed_that_failed_with_no_stop_saves_what_answered_the_control(hazards, tmp_path):
    from src.hazards import track

    res = track.auto_snapshot_due(_fetcher(tmp_path, [], bodies=hazards.bodies, down_on="/events.json", retries=0))
    assert res["snapshotted"] == 1 and len(res["failures"]) == 1, res
    assert _snap_ids(hazards.path) == ["us-test-1"]


@pytest.mark.parametrize("cleared", [True, False], ids=["stop-cleared", "stop-engaged"])
def test_the_manual_refresh_does_not_replace_the_snapshot_with_the_feeds_a_stop_left(hazards, db, monkeypatch, cleared):
    from src.api import hazards as H
    from src.api.signals import signals_hazards_snapshot

    def relay(source="all", **_kw):
        (_stop_and_clear if cleared else activate_kill_switch)()
        return [{**_OLD, "id": "us-partial"}], ["gdacs: FetchFailed: request error"]

    monkeypatch.setattr(H, "fetch_hazards", relay)
    out = signals_hazards_snapshot(body=None, refresh=True, db=db)
    assert out["saved"] is False and out["failures"], out
    assert hazards.path.read_text("utf-8") == hazards.before, f"a Stop replaced the snapshot: {_snap_ids(hazards.path)}"


def test_the_manual_refresh_under_a_stop_still_saves_the_posted_records(hazards, db, monkeypatch):
    """As when every feed failed: the posted records are the person's own local write."""
    from src.api import hazards as H
    from src.api.signals import HazardSnapshotBody, signals_hazards_snapshot

    monkeypatch.setattr(H, "fetch_hazards", lambda source="all", **_kw: (_stop_and_clear(), ([{**_OLD, "id": "us-partial"}], ["gdacs: x"]))[1])
    out = signals_hazards_snapshot(body=HazardSnapshotBody(records=[{**_OLD, "id": "us-posted"}]), refresh=True, db=db)
    assert out["saved"] is True and _snap_ids(hazards.path) == ["us-posted"], out


def test_the_manual_refresh_with_no_stop_saves_what_answered_the_control(hazards, db, monkeypatch):
    from src.api import hazards as H
    from src.api.signals import signals_hazards_snapshot

    monkeypatch.setattr(H, "fetch_hazards", lambda source="all", **_kw: ([{**_OLD, "id": "us-partial"}], ["gdacs: reset"]))
    out = signals_hazards_snapshot(body=None, refresh=True, db=db)
    assert out["saved"] is True and _snap_ids(hazards.path) == ["us-partial"], out


# --------------------------------------------------------------------------- #
#  3. The qualification pass (``run_qualification_pass``) and the bulk job
# --------------------------------------------------------------------------- #
@pytest.fixture()
def q(monkeypatch):
    """The real qualification module on a machine above the memory floor, so the pass reaches its trial loop."""
    import src.config.machine_floor as mf
    from src.catalog import qualification as Q

    monkeypatch.delenv("OO_ALLOW_BIG_SCANS", raising=False)
    monkeypatch.setattr(Q, "scan_budget", lambda articles, **k: mf.scan_budget(
        articles, override=False, total_mb=16384.0, available_mb=8192.0))
    return Q


def _candidates(db, Q, domains=("a.example", "b.example")):
    from tests.test_source_qualification import (
        _add_candidate_with_articles,
        _seed_healthy_en_cohort,
    )

    _seed_healthy_en_cohort(db)
    out = [_add_candidate_with_articles(db, domain=d, status=Q.STATUS_UNQUALIFIED, pathology=False) for d in domains]
    db.commit()
    return out


def _judged(db, Q, cands):
    db.expire_all()
    ids = {c.id for c in cands}
    rows = {a.source_id for a in db.query(SourceQualificationAttempt).all() if a.source_id in ids}
    statuses = {db.get(Source, c.id).domain: db.get(Source, c.id).status for c in cands}
    return rows, statuses


@pytest.mark.parametrize("raises", [False, True], ids=["trial-returned", "trial-raised"])
def test_qualification_a_stop_cleared_inside_the_first_trial_judges_nothing(db, q, monkeypatch, raises):
    cands = _candidates(db, q)
    tried: list[str] = []

    def trial(session, source, fetcher, **_kw):
        tried.append(source.domain)
        _stop_and_clear()
        if raises:
            raise FetchFailed(f"request error for https://{source.domain}/feed: {RAW_STOP}")
        return {"skipped_offline": 1}  # what ``ingest_source`` hands back for a feed the Stop cut

    monkeypatch.setattr(q, "trial_fetch", trial)
    out = q.run_qualification_pass(db, fetcher=object(), per_pass=10)
    rows, statuses = _judged(db, q, cands)
    assert out["evaluated"] == 0 and out["skipped"] == "airplane mode engaged" and out["trial_fetch_errors"] == 0, out
    assert rows == set() and set(statuses.values()) == {q.STATUS_UNQUALIFIED}, (rows, statuses)
    assert tried == ["a.example"], "the candidates after the Stop were tried"


def test_qualification_a_stop_still_engaged_judges_neither_the_cut_candidate_nor_the_rest(db, q, monkeypatch):
    """No read inside or after the trial loop before R617: every candidate was judged on what the refused trials left."""
    cands = _candidates(db, q)

    def trial(session, source, fetcher, **_kw):
        if not kill_switch_active():
            activate_kill_switch()  # the Stop lands in the first trial, and stays
        raise FetchFailed(KILL_SWITCH_REFUSAL)

    monkeypatch.setattr(q, "trial_fetch", trial)
    out = q.run_qualification_pass(db, fetcher=object(), per_pass=10)
    rows, statuses = _judged(db, q, cands)
    assert out["evaluated"] == 0 and out["skipped"] == "airplane mode engaged", out
    assert rows == set() and set(statuses.values()) == {q.STATUS_UNQUALIFIED}, (rows, statuses)


def test_qualification_candidates_tried_before_the_stop_are_judged_and_the_cut_one_is_deferred(db, q, monkeypatch):
    cands = _candidates(db, q, ("a.example", "b.example", "c.example"))

    def trial(session, source, fetcher, **_kw):
        if source.domain == "b.example":
            _stop_and_clear()
        return {}

    monkeypatch.setattr(q, "trial_fetch", trial)
    out = q.run_qualification_pass(db, fetcher=object(), per_pass=10)
    rows, statuses = _judged(db, q, cands)
    assert out["evaluated"] == 1 and out["deferred"] == 2, out
    assert rows == {cands[0].id} and statuses == {
        "a.example": q.STATUS_QUALIFIED, "b.example": q.STATUS_UNQUALIFIED, "c.example": q.STATUS_UNQUALIFIED,
    }, statuses


def test_qualification_a_stop_landing_before_the_trial_loop_and_cleared_after_the_refusal_judges_nothing(db, q, monkeypatch):
    """The Stop lands after the caller's check (in the cohort plan or the selection queries) and is cleared once the first trial is
    refused by name: the trial loop's own check, after its window opens, defers the batch before any trial (the independent read)."""
    cands = _candidates(db, q)
    tried: list[str] = []

    def trial(session, source, fetcher, **_kw):
        tried.append(source.domain)
        assert kill_switch_active()
        clear_kill_switch()
        raise FetchFailed(KILL_SWITCH_REFUSAL)

    monkeypatch.setattr(q, "trial_fetch", trial)
    activate_kill_switch()
    out = q.run_qualification_pass(db, fetcher=object(), per_pass=10)
    rows, statuses = _judged(db, q, cands)
    assert tried == [], "a trial went out under the Stop"
    assert out["evaluated"] == 0 and out["skipped"] == "airplane mode engaged" and out["trial_fetch_errors"] == 0, out
    assert rows == set() and set(statuses.values()) == {q.STATUS_UNQUALIFIED}, (rows, statuses)


def test_qualification_a_stop_pressed_just_after_the_trial_loops_check_is_a_stop(db, q, monkeypatch):
    cands = _candidates(db, q)

    def trial(session, source, fetcher, **_kw):
        try:
            raise FetchFailed(KILL_SWITCH_REFUSAL)  # what the fetcher says with the switch engaged
        finally:
            clear_kill_switch()

    monkeypatch.setattr(q, "trial_fetch", trial)
    fired = _stop_right_after_the_check(monkeypatch, q.run_qualification_pass, "epoch = kill_switch_epoch()")
    out = q.run_qualification_pass(db, fetcher=object(), per_pass=10)
    rows, statuses = _judged(db, q, cands)
    assert fired, "premise: the Stop landed right after the trial loop's check"
    assert out["evaluated"] == 0 and out["skipped"] == "airplane mode engaged" and out["trial_fetch_errors"] == 0, out
    assert rows == set() and set(statuses.values()) == {q.STATUS_UNQUALIFIED}, (rows, statuses)


def test_qualification_through_the_production_fetcher_a_cut_feed_logs_no_no_evidence_attempt(db, q, tmp_path):
    """The real trial (``ingest_source``) over the production fetcher: it catches the cut feed GET and returns a tally, so only the
    epoch read after it can say the candidate was never asked. Before R617 it was logged as having no evidence (to the back of the queue)."""
    cand = Source(name="a.example", domain="a.example", rss_url="https://a.example/feed.xml", language="en", enabled=True,
                  status=q.STATUS_UNQUALIFIED)
    db.add(cand)
    db.commit()
    calls: list[str] = []
    out = q.run_qualification_pass(db, fetcher=_fetcher(tmp_path, calls, cut_clear_on="/feed.xml", retries=0), per_pass=5)
    assert not kill_switch_active() and "https://a.example/feed.xml" in calls, calls
    assert out["skipped"] == "airplane mode engaged", out
    assert db.query(SourceQualificationAttempt).filter_by(source_id=cand.id).count() == 0, "a cut feed was logged as no evidence"


def test_qualification_a_genuine_trial_failure_with_no_stop_is_judged_the_control(db, q, monkeypatch):
    cands = _candidates(db, q, ("a.example",))

    def trial(session, source, fetcher, **_kw):
        raise FetchFailed(f"request error for https://{source.domain}/feed: {RESET}")

    monkeypatch.setattr(q, "trial_fetch", trial)
    out = q.run_qualification_pass(db, fetcher=object(), per_pass=10)
    rows, statuses = _judged(db, q, cands)
    assert out["evaluated"] == 1 and out["trial_fetch_errors"] == 1 and "skipped" not in out, out
    assert rows == {cands[0].id} and statuses == {"a.example": q.STATUS_QUALIFIED}, statuses


class _Ctx:
    def __init__(self):
        self.progress: list[dict] = []
        self.stopping = False

    def set_progress(self, **kw):
        self.progress.append(kw)


def test_the_bulk_job_pauses_on_a_pass_a_cleared_stop_emptied_instead_of_calling_it_complete(db, q, scope, monkeypatch):
    from src.catalog.qualify_job import run_bulk_qualification

    _candidates(db, q)
    monkeypatch.setattr(q, "trial_fetch", lambda session, source, fetcher, **_kw: _stop_and_clear())
    out = run_bulk_qualification(_Ctx(), batch_size=10, fetcher=object(), session_factory=scope, sleep_s=0.0)
    assert not kill_switch_active()
    assert out["complete"] is False and "airplane mode engaged" in out.get("paused_reason", ""), out
    assert out["evaluated"] == 0 and db.query(SourceQualificationAttempt).count() == 0, out


# --------------------------------------------------------------------------- #
#  4. World discovery (``run_world_discovery``)
# --------------------------------------------------------------------------- #
def _payload(name, website):
    return {"results": {"bindings": [{"itemLabel": {"value": name}, "website": {"value": website}}]}}


def _discover(scope, tmp_path, run_query, countries=("ke", "ng")):
    from src.catalog.discover_job import load_state, run_world_discovery

    path = tmp_path / "wd.json"
    res = run_world_discovery(_Ctx(), countries=list(countries), run_query=run_query, session_factory=scope, state_path=path,
                              world_codes=list(countries), sleep_s=0)
    return res, load_state(path)


def _second_query(stop):
    """Every country's first query answers, its second one is cut by ``stop``; a query asked under an engaged switch is refused by name."""
    asked: list[str] = []

    def run_query(cc, type_qids):
        asked.append(cc)
        if kill_switch_active():
            raise RuntimeError(NETWORK_REFUSED)
        if asked.count(cc) == 2:
            stop()
            raise FetchFailed(f"request error for https://query.example/sparql: {RAW_STOP}")
        return _payload(f"Outlet {cc}-{asked.count(cc)}", f"https://outlet-{cc}-{asked.count(cc)}.example/")

    return run_query, asked


@pytest.mark.parametrize("stop", [_stop_and_clear, activate_kill_switch], ids=["stop-cleared", "stop-engaged"])
def test_discovery_a_stop_inside_a_country_does_not_mark_it_done(db, scope, tmp_path, stop):
    run_query, asked = _second_query(stop)
    res, state = _discover(scope, tmp_path, run_query)
    assert res["complete"] is False and "airplane" in res["paused_reason"], res
    assert state.get("done", []) == [] and res["errors"] == [], "a country the Stop cut was marked done with the cut query as its error"
    assert "ng" not in asked, "the job went on to the next country"
    # the sources the answered queries added are real rows, so they are counted
    added = db.query(Source).filter(Source.domain.like("outlet-ke-%")).count()
    assert added >= 1 and res["added_total"] == added, (res, added)


def test_discovery_a_country_a_stop_cut_counts_both_asks_once_resumed(db, scope, tmp_path):
    """The sources the cut ask added stay in the country's own count after the resumed ask completes it (the independent read)."""
    run_query, _asked = _second_query(_stop_and_clear)
    first, _ = _discover(scope, tmp_path, run_query, countries=("ke",))
    assert first["added_total"] >= 1, first
    n = [0]

    def answer(cc, type_qids):
        n[0] += 1
        return _payload(f"Outlet {cc}-r{n[0]}", f"https://outlet-{cc}-r{n[0]}.example/")

    res, state = _discover(scope, tmp_path, answer, countries=("ke",))
    added = db.query(Source).filter(Source.domain.like("outlet-ke-%")).count()
    assert state["done"] == ["ke"], state
    assert state["per_country"]["ke"] == added == res["added_total"] > first["added_total"], (state, res, added)


def test_discovery_a_stop_pressed_just_after_the_country_check_is_a_stop(db, scope, tmp_path, monkeypatch):
    from src.catalog import discover as D
    from src.catalog.discover_job import run_world_discovery

    real = D.discover_sources

    def refused(*a, **k):
        assert kill_switch_active(), "premise: the Stop is engaged when the country is asked"
        try:
            return real(*a, **k)  # refused by name, up front
        finally:
            clear_kill_switch()

    monkeypatch.setattr(D, "discover_sources", refused)
    fired = _stop_right_after_the_check(monkeypatch, run_world_discovery, "for cc in codes:")
    res, state = _discover(scope, tmp_path, lambda cc, q: _payload("x", f"https://x-{cc}.example/"))
    assert fired, "premise: the Stop landed right after the loop's check"
    assert "airplane" in res["paused_reason"] and res["errors"] == [] and state.get("done", []) == [], res


def test_discovery_host_words_that_mention_airplane_mode_are_the_countrys_error_not_a_pause(db, scope, tmp_path, monkeypatch):
    """The substring is gone: a failure is the switch's only when the switch says so (R298, R617)."""
    from src.catalog import discover as D

    def failing(*a, **k):
        raise RuntimeError("upstream said: airplane mode is engaged")

    monkeypatch.setattr(D, "discover_sources", failing)
    res, state = _discover(scope, tmp_path, lambda cc, q: {}, countries=("ke",))
    assert "airplane" not in (res.get("paused_reason") or ""), res
    assert res["errors"] and res["errors"][0].startswith("ke: "), res


def test_discovery_a_query_that_failed_with_no_stop_still_lets_the_country_be_done_the_control(db, scope, tmp_path):
    run_query, asked = _second_query(lambda: None)
    res, state = _discover(scope, tmp_path, run_query)
    assert res["complete"] is True and state["done"] == ["ke", "ng"], res
    assert len(res["errors"]) == 2, "each country's failed query rides in the state, as before"


# --------------------------------------------------------------------------- #
#  5. The wiki dump and OSM region downloads (``_download`` and ``_pump``)
# --------------------------------------------------------------------------- #
class _GatedResp:
    status_code = 200
    headers = {"Content-Length": "30"}

    def __init__(self, gate: threading.Event):
        self._gate = gate

    def raise_for_status(self):
        pass

    def iter_content(self, _chunk):
        for _ in range(3):
            self._gate.wait(5)
            yield b"0123456789"


def _wait_until(predicate, tries=250, delay=0.02):
    for _ in range(tries):
        if predicate():
            return True
        time.sleep(delay)
    return False


def _refused_by_the_guarded_session(headers):
    """The production download session, with the switch engaged: refused by name (``NetworkBlocked``) before any socket."""
    from src.wiki.dumps import _default_get

    assert kill_switch_active(), "a real request is only ever made with the switch engaged"
    return _default_get("https://dumps.example/x.bz2", headers)


_KINDS = {
    "dump": ("src.wiki.dumps", "DumpDownloadManager", ("en", "fr"), ("en:pages-articles", "fr:pages-articles"), ("enwiki", "frwiki")),
    "osm": ("src.geo.osm_downloads", "OsmDownloadManager", ("monaco", "andorra"), ("monaco", "andorra"), ("monaco", "andorra")),
}


def _manager(kind, tmp_path, http_get):
    import importlib

    mod_name, cls_name, *_ = _KINDS[kind]
    cls = getattr(importlib.import_module(mod_name), cls_name)
    return cls(base_dir=tmp_path / kind, http_get=http_get, max_concurrent=1)


def _entry(mgr, key):
    return next(e for e in mgr.list() if e["key"] == key)


def _join(mgr, key):
    t = mgr._threads.get(key)
    if t is not None:
        t.join(10)
        assert not t.is_alive()


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_downloads_a_stop_cleared_inside_the_connect_is_paused_not_error(tmp_path, kind):
    _m, _c, (code, _), (key, _), _ = _KINDS[kind]
    mgr = _manager(kind, tmp_path, lambda url, headers: _cut_and_clear())
    mgr.start(code)
    _join(mgr, key)
    e = _entry(mgr, key)
    assert not kill_switch_active()
    assert (e["status"], e.get("paused_by"), e.get("error")) == ("paused", "airplane", None), e


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_downloads_a_stop_landing_after_the_start_check_is_paused_not_error(tmp_path, monkeypatch, kind):
    """Refused by name in the worker, then cleared before the failure is read: the worker's window opened after the Stop, and only the
    class of the refusal (raised by the switch alone) can say it was a Stop."""
    import importlib

    mod_name, cls_name, (code, _), (key, _), _ = _KINDS[kind]
    cls = getattr(importlib.import_module(mod_name), cls_name)

    def get(url, headers):
        try:
            return _refused_by_the_guarded_session(headers)
        finally:
            clear_kill_switch()

    mgr = _manager(kind, tmp_path, get)
    fired = _stop_right_after_the_check(monkeypatch, cls.start, "from src.ingest import kill_switch_active")
    mgr.start(code)
    _join(mgr, key)
    assert fired, "premise: the Stop landed right after start()'s check"
    e = _entry(mgr, key)
    assert (e["status"], e.get("paused_by"), e.get("error")) == ("paused", "airplane", None), e


_THIRD = {"dump": ("de", "de:pages-articles"), "osm": ("liechtenstein", "liechtenstein")}


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_downloads_every_queued_entry_is_paused_not_launched_when_airplane_mode_pauses_the_worker(tmp_path, kind):
    """The worker airplane mode paused pumps the queue: EVERY queued entry is presented paused, not only as many as the freed slots (the
    one-slot queue of two behind it would otherwise leave the second "queued" with no worker, since going back online starts nothing),
    and no request is even attempted for any of them."""
    _m, _c, (first, second), (key1, key2), (tag1, _tag2) = _KINDS[kind]
    third, key3 = _THIRD[kind]
    gate = threading.Event()
    calls: list[str] = []

    def get(url, headers):
        calls.append(url)
        if tag1 in url:
            return _GatedResp(gate)
        return _refused_by_the_guarded_session(headers)

    mgr = _manager(kind, tmp_path, get)
    try:
        mgr.start(first)
        assert _wait_until(lambda: _entry(mgr, key1)["status"] == "downloading")
        assert mgr.start(second)["status"] == "queued"
        assert mgr.start(third)["status"] == "queued"
        activate_kill_switch()  # and it stays engaged
        gate.set()
        _join(mgr, key1)
        assert _wait_until(lambda: _entry(mgr, key2)["status"] != "queued")
        _join(mgr, key2)
        _join(mgr, key3)
    finally:
        gate.set()
    assert _entry(mgr, key1)["status"] == "paused"
    for key in (key2, key3):
        e = _entry(mgr, key)
        assert (e["status"], e.get("paused_by"), e.get("error")) == ("paused", "airplane", None), e
    assert mgr._order == [], "no entry is left queued with no worker to launch it"
    assert len(calls) == 1, f"a queued entry was launched into airplane mode: {calls}"


class _ChunkedResp:
    """Two chunks answered, then ``between`` runs (inside the transfer, after the chunk loop's check for the second chunk passed), then
    the read fails as a reset would."""

    status_code = 200
    headers = {"Content-Length": "30"}

    def __init__(self, between):
        self._between = between

    def raise_for_status(self):
        pass

    def iter_content(self, _chunk):
        yield b"0123456789"
        yield b"0123456789"
        self._between()
        raise requests.exceptions.ConnectionError(RESET)


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_downloads_a_transfer_that_fails_genuinely_after_a_cleared_stop_is_an_error(tmp_path, kind):
    """A Stop pressed and cleared while the first chunk was read, then a genuine reset two chunks later: the transfer's window is one
    chunk (the socket guard never cuts an open stream), so the reset is the transfer's own, an error, never "paused by airplane"."""
    _m, _c, (code, _), (key, _), _ = _KINDS[kind]
    stops: list[int] = []

    class _Resp(_ChunkedResp):
        def iter_content(self, _chunk):
            _stop_and_clear()  # before the first chunk lands: inside the connect's window
            stops.append(1)
            yield from super().iter_content(_chunk)

    mgr = _manager(kind, tmp_path, lambda url, headers: _Resp(lambda: None))
    mgr.start(code)
    _join(mgr, key)
    assert stops, "premise: the Stop was pressed and cleared inside the transfer"
    e = _entry(mgr, key)
    assert e["status"] == "error" and e["error"] and not e.get("paused_by"), e


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_downloads_a_chunk_read_a_stop_cut_and_cleared_is_paused_not_error(tmp_path, kind):
    """The other side of the one-chunk window: a Stop pressed and cleared inside a chunk's read that then fails is the Stop's."""
    _m, _c, (code, _), (key, _), _ = _KINDS[kind]
    mgr = _manager(kind, tmp_path, lambda url, headers: _ChunkedResp(_stop_and_clear))
    mgr.start(code)
    _join(mgr, key)
    e = _entry(mgr, key)
    assert not kill_switch_active()
    assert (e["status"], e.get("paused_by"), e.get("error")) == ("paused", "airplane", None), e


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_downloads_a_genuine_failure_with_no_stop_is_an_error_the_control(tmp_path, kind):
    _m, _c, (code, _), (key, _), _ = _KINDS[kind]

    def get(url, headers):
        raise requests.exceptions.ConnectionError(RESET)

    mgr = _manager(kind, tmp_path, get)
    mgr.start(code)
    _join(mgr, key)
    e = _entry(mgr, key)
    assert e["status"] == "error" and e["error"] and not e.get("paused_by"), e


def test_the_guarded_download_session_refuses_by_name_the_premise():
    activate_kill_switch()
    with pytest.raises(NetworkBlocked):
        _refused_by_the_guarded_session({})


# --------------------------------------------------------------------------- #
#  6. The market feeds (``import_feed`` and ``classify_failed_check(exc, since=)``)
# --------------------------------------------------------------------------- #
_CSV = "https://m.example/q.csv"


@pytest.fixture()
def slept(monkeypatch):
    from src.markets import csv_feeds as C

    calls: list[float] = []
    monkeypatch.setattr(C, "time", SimpleNamespace(sleep=calls.append))
    return calls


def _import(db, fetcher):
    from src.markets import csv_feeds as C

    return C.import_feed(db, url=_CSV, symbol="WTI", fetcher=fetcher)


@pytest.mark.parametrize("fault", ["raw_clear_on", "cut_clear_on"])
def test_markets_a_stop_cleared_inside_the_feed_request_is_offline_not_the_feeds_verdict(db, tmp_path, slept, fault):
    out = _import(db, _fetcher(tmp_path, [], retries=0, **{fault: "/q.csv"}))
    assert not kill_switch_active()
    assert (out.status, out.verdict, out.retryable, out.attempts) == ("fetch_failed", "offline", False, 1), out
    assert slept == [], "a Stop is not a transient fault to retry after a sleep"


def _two_attempts(tmp_path, second):
    """The feed's first attempt meets a host's reset (retried); ``second`` is what its second attempt's request does."""
    calls: list[str] = []
    f = _fetcher(tmp_path, calls, retries=0, down_on="/q.csv")
    real_get = f.session.get

    def get(url, **kw):
        if url == _CSV and calls.count(_CSV) == 1:  # the second attempt
            calls.append(url)
            second()
        return real_get(url, **kw)

    f.session.get = get  # type: ignore[method-assign]
    return f


def _raw_stop():
    _stop_and_clear()
    raise requests.exceptions.ProxyError(RAW_STOP)


def _reset():
    raise requests.exceptions.ProxyError(RESET)


def test_markets_a_stop_cleared_inside_the_retry_is_offline(db, tmp_path, slept):
    out = _import(db, _two_attempts(tmp_path, _raw_stop))
    assert out.attempts == 2 and slept == [1.5] and out.verdict == "offline", (out, slept)


def test_markets_each_attempt_is_judged_by_its_own_window(db, tmp_path, monkeypatch):
    """A Stop pressed and cleared during the wait BETWEEN the attempts is in neither window: the second attempt was asked online, and
    its reset is the host's."""
    from src.markets import csv_feeds as C

    monkeypatch.setattr(C, "time", SimpleNamespace(sleep=lambda s: _stop_and_clear()))
    out = _import(db, _two_attempts(tmp_path, _reset))
    assert out.attempts == 2 and out.verdict == "refused", out


def test_markets_a_genuine_reset_with_no_stop_is_the_feeds_verdict_the_control(db, tmp_path, slept):
    calls: list[str] = []
    f = _fetcher(tmp_path, calls, retries=0, down_on="/q.csv")
    out = _import(db, f)
    # the first attempt's reset is retried once after the sleep; the second meets the host's 503, its own answer
    assert out.status == "fetch_failed" and out.verdict == "http-error" and out.attempts == 2 and slept == [1.5], out


def test_classify_failed_check_reads_the_window_when_given_one_and_the_switch_otherwise():
    from src.ingest import kill_switch_epoch
    from src.markets.csv_feeds import classify_failed_check

    cut = FetchFailed(f"request error for {_CSV}: {RAW_STOP}")
    epoch = kill_switch_epoch()
    _stop_and_clear()
    assert classify_failed_check(cut, since=epoch)[0] == "offline"
    assert classify_failed_check(cut)[0] != "offline", "without a window it is the R320 read of the switch as it is now"
    assert classify_failed_check(cut, since=kill_switch_epoch())[0] != "offline", "a window that saw no Stop is the host's"
    status = FetchFailed(f"HTTP 503 for {_CSV}")
    assert classify_failed_check(status, since=epoch)[0] == "http-error", "a status line is the host's answer whatever the window saw"
