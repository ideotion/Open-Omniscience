"""
A Stop pressed and cleared again inside a request's flight records nothing, in the recorders R617's audit left after PR A (R617 "PR B",
the R614 epoch), and in the two R618 named: the custody OpenTimestamps fallback and the ring loader's candidate loop.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each recorder decided after a request, by the exception's TYPE or by reading the switch then (R320), and none read the engagement epoch
(R614), so a Stop the operator pressed and cleared again inside the request was filed as the target's behaviour:

* the Wikipedia walk and the WARM tier: a connect the Stop cut, a ``ConnectionError`` by type, written on the edition's bookmark and
  held back by the doubling wait (the walk's survives a restart), even with the switch still engaged;
* watched-page tracking (``update_page``): an enrichment fetch the Stop cut (categories, texts, diffs, ORES), failing open, committed
  as a revision with no text, diff or score and ``last_revid`` moved past it for good;
* the versioned lane's text fetch (``run_feed_once``): the page cooled down for five minutes and listed as an error;
* ORES scoring: reported as ``transport_error``;
* the wiki change stream: counted as a transport error, with a backoff;
* the markets pass and the import-all route (their ``except``), the price rules (``fetch_failed`` stamped on the rule, which Home
  reads as "needs attention", every remaining rule too when the switch stayed engaged), the field test (a cut step recorded done and
  never run again), the Wikidata items job (a miscount), and the OSM replication source (``unavailable`` instead of ``refused``);
* R618: the custody log writing a PERMANENT local-only proof in place of the OpenTimestamps one a Stop refused or cut, and the ring
  loader counting every candidate a Stop cut as an ``error`` (its loop had no switch check at all).

Where the production path runs, the airplane socket guard is armed as boot arms it and a real request is only ever made with the switch
ENGAGED, so the guard refuses it before any socket call; the proxy variables are cleared so nothing can route around it. The rest use the
recorder's own seam, because the recorder is what is under test. Every recorder is read against a control: the same failure with no
Stop, recorded as before. A loop whose epoch must be taken BEFORE its head check has a test where the Stop lands right after that check.
"""

from __future__ import annotations

import inspect
import logging
import pathlib
import sys
from contextlib import contextmanager

import pytest
import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Base, MarketExtractionRule, Source, WikiPage, WikiRevision
from src.ingest import FetchFailed, activate_kill_switch, clear_kill_switch, kill_switch_active
from src.ingest.fetch_verdict import KILL_SWITCH_REFUSAL
from src.safety.fetcher import GuardedSession, make_fetcher

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
#: A host's own reset, no Stop anywhere: the control's failure.
RESET = "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"
EDITION = "oo"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    """The switch clear, the guard armed as boot arms it (put back as found), and no proxy or fetch-mode setting."""
    from src.ingest import airplane

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
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


class _Session(GuardedSession):
    """The REAL guarded session (its own kill-switch check in ``request``) over the real ``requests`` transport, one scripted step per
    request: ``"cut"`` the operator presses Stop once the session's check has let the request go, so the REAL socket guard refuses the
    connect and requests wraps it in a ``ConnectionError``; then the switch is cleared again, unless ``keep`` (still engaged: R320's
    case) · ``"reset"`` a host's own reset, no Stop."""

    def __init__(self, script, *, keep: bool = False) -> None:
        super().__init__()
        self.script = list(script)
        self.keep = keep
        self.urls: list[str] = []

    def _send(self, method, url, *args, **kwargs):
        self.urls.append(url)
        step = self.script.pop(0)
        if step == "busy-across-a-stop":  # the host's own 503, with a Stop pressed and cleared while it was in flight
            _stop_and_clear()
            resp = requests.Response()
            resp.status_code, resp.url, resp._content = 503, url, b""
            return resp
        if step == "cut":
            activate_kill_switch()
            assert kill_switch_active(), "a real request is only ever made with the switch engaged"
            try:
                return super()._send(method, url, *args, **kwargs)
            finally:
                if not self.keep:
                    clear_kill_switch()
        assert step == "reset", step
        raise requests.exceptions.ConnectionError(RESET)


class _RefusedByNameThenCleared(GuardedSession):
    """The real session refusing BY NAME (``NetworkBlocked``, before any request), and the operator back online before the caller reads
    the failure."""

    def request(self, method, url, *args, **kwargs):
        assert kill_switch_active(), "premise: the switch is engaged when the session is asked"
        try:
            return super().request(method, url, *args, **kwargs)
        finally:
            clear_kill_switch()


def _stop_right_after_the_check(monkeypatch, function, loop_line, *, module=None, name="kill_switch_active"):
    """The check at the head of ``function``'s loop (the first ``if <name>():`` after ``loop_line``) reads clear, and the operator presses
    Stop the instant after it, before the request that check lets go: the case where an epoch taken AFTER the check would already hold the
    Stop and read the request's refusal as the target's failure once the switch is cleared again. ``module`` is where ``function`` looks
    the check up (``src.ingest`` for a function that imports it inside itself)."""
    import src.ingest as ingest_pkg

    module = module or ingest_pkg
    lines, first = inspect.getsourcelines(function)
    start = next(i for i, line in enumerate(lines) if line.strip() == loop_line)
    target = first + next(i for i in range(start, len(lines)) if lines[i].strip() == f"if {name}():")
    real = getattr(module, name)
    fired: list[int] = []

    def check() -> bool:
        engaged = real()
        caller = sys._getframe(1)
        if not fired and caller.f_code is function.__code__ and caller.f_lineno == target:
            fired.append(target)
            activate_kill_switch()
        return engaged

    monkeypatch.setattr(module, name, check)
    return fired


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def wiki_lane():
    from src.versioned.store import create_lane, dispose_all

    dispose_all()
    create_lane("wiki")
    try:
        yield
    finally:
        dispose_all()


def _wiki_client(session):
    from src.wiki.client import WikiClient

    return WikiClient(session=session, min_interval_s=0.0)


# --------------------------------------------------------------------------- #
#  1.6 The Wikipedia walk (the production client over the real guarded session)
# --------------------------------------------------------------------------- #
def _walker(session):
    from src.versioned.store import lane_session
    from src.wiki import walk as W
    from src.wiki.tiers import budget_state

    walker = W.WikiWalker(
        client=_wiki_client(session), editions=(EDITION,), lane_session=lambda: lane_session("wiki"),
        budget=lambda: budget_state(total_gb=20, disk_bytes=0, editions=1), enabled=lambda: True,
        transport=lambda: "direct", batch=2, monotonic=lambda: 1000.0,
    )
    with lane_session("wiki") as lane:
        walker._cursor_row(lane, EDITION)
    return walker


def _walk_cursor() -> dict:
    from src.versioned.store import lane_session
    from src.wiki.lane_models import WikiWalkCursor

    with lane_session("wiki") as lane:
        row = lane.get(WikiWalkCursor, EDITION)
        return {"failures": row.consecutive_failures, "last_error": row.last_error, "at": row.last_error_at}


def _walk_request(walker, which):
    state = {"pass_no": 1, "continue": None, "complete": False, "has_count": which == "batch", "failures": 0}
    return (walker._read_batch if which == "batch" else walker._read_count)(EDITION, state)


@pytest.mark.parametrize("which", ["count", "batch"])
@pytest.mark.parametrize("keep", [False, True], ids=["cleared", "still-engaged"])
def test_walk_a_connect_a_stop_cut_is_the_switchs_pause_and_nothing_is_written_on_the_edition(wiki_lane, which, keep):
    from src.wiki import walk as W

    walker = _walker(_Session(["cut"], keep=keep))
    out = _walk_request(walker, which)
    assert out == {"refused": W.PAUSED_NETWORK_OFF}, out
    assert _walk_cursor() == {"failures": 0, "last_error": None, "at": None}, "the Stop was written on the edition's bookmark"
    assert walker._not_before == {}, "the edition is held back for a Stop"


@pytest.mark.parametrize("which", ["count", "batch"])
def test_walk_an_http_answer_sharing_its_window_with_a_stop_is_still_the_hosts(wiki_lane, which):
    """Only the connection is reclaimed: a status line is an answer the host gave, and a Stop cannot produce one."""
    from src.wiki import walk as W

    walker = _walker(_Session(["busy-across-a-stop"]))
    assert _walk_request(walker, which) == {"refused": W.WAIT_SERVICE_BUSY}
    assert _walk_cursor()["last_error"] == W.WAIT_SERVICE_BUSY


@pytest.mark.parametrize("which", ["count", "batch"])
def test_walk_a_hosts_reset_with_no_stop_is_still_the_editions_wait_the_control(wiki_lane, which):
    from src.wiki import walk as W

    walker = _walker(_Session(["reset"]))
    assert _walk_request(walker, which) == {"refused": W.WAIT_CONNECTION}
    cursor = _walk_cursor()
    assert cursor["failures"] == 1 and cursor["last_error"] == W.WAIT_CONNECTION and cursor["at"] is not None
    assert EDITION in walker._not_before


# --------------------------------------------------------------------------- #
#  1.7 The WARM tier
# --------------------------------------------------------------------------- #
def _warm(session):
    from tests import test_wiki_warm as WT

    WT._change(101, 1011)
    return WT._fetcher(_wiki_client(session))


@pytest.mark.parametrize("keep", [False, True], ids=["cleared", "still-engaged"])
def test_warm_a_text_fetch_a_stop_cut_pauses_warm_and_holds_no_edition_to_blame(wiki_lane, keep):
    from src.wiki import walk as W

    fetcher = _warm(_Session(["cut"], keep=keep))
    report = fetcher.warm_for(3600)
    assert report.paused == W.PAUSED_NETWORK_OFF and report.refusals == {W.PAUSED_NETWORK_OFF: 1}, report
    assert fetcher.status()["waiting"] == {} and fetcher._failures == {}, "the edition waits out a backoff for a Stop"


def test_warm_a_hosts_reset_with_no_stop_is_still_the_editions_wait_the_control(wiki_lane):
    from src.wiki import walk as W

    fetcher = _warm(_Session(["reset"]))
    report = fetcher.warm_for(3600)
    assert report.paused is None and report.refusals == {W.WAIT_CONNECTION: 1}
    assert fetcher.status()["waiting"] == {EDITION: W.WAIT_CONNECTION}


# --------------------------------------------------------------------------- #
#  1.8 Watched-page tracking (each enrichment sub-fetch cut through the real client)
# --------------------------------------------------------------------------- #
class _TrackClient:
    """Scripted page answers; the one sub-fetch named ``real`` goes through a REAL WikiClient over ``session``, where the Stop lands."""

    def __init__(self, *, real: str | None = None, session=None, baseline: bool = False) -> None:
        self.real, self.wiki = real, _wiki_client(session) if session is not None else None
        self.baseline = baseline

    def _maybe(self, name, answer, *args):
        return getattr(self.wiki, name)(*args) if self.real == name else answer

    def fetch_current_text(self, wiki, title):
        return {"revid": 100, "text": "baseline", "pageid": 5} if self.baseline else {"revid": 101, "text": "now"}

    def fetch_categories(self, wiki, title):
        return self._maybe("fetch_categories", ["Cities"], wiki, title)

    def fetch_revisions(self, wiki, title, *, limit=20, older_than=None):
        return [{"revid": 101, "parent_revid": 100, "size": 120, "editor": "x", "comment": "c"}]

    def fetch_revision_texts(self, wiki, revids):
        return self._maybe("fetch_revision_texts", {101: "text 101"}, wiki, revids)

    def fetch_compare(self, wiki, a, b):
        return self._maybe("fetch_compare", {"added": "a", "removed": "", "added_bytes": 1, "removed_bytes": 0}, wiki, a, b)


def _watched(db, *, baseline=True):
    from src.wiki.track import ensure_page

    page = ensure_page(db, EDITION, "Berlin")
    if baseline:
        page.baseline_revid = page.last_revid = 100
        db.commit()
    return page.id


def _page(db, page_id):
    db.expire_all()
    return db.get(WikiPage, page_id)


@pytest.mark.parametrize("sub", ["fetch_revision_texts", "fetch_compare"])
@pytest.mark.parametrize("keep", [False, True], ids=["cleared", "still-engaged"])
def test_track_a_sub_fetch_a_stop_cut_stores_no_revision_and_keeps_the_old_revid(db, sub, keep):
    from src.wiki.track import track_watched

    pid = _watched(db)
    out = track_watched(db, _TrackClient(real=sub, session=_Session(["cut"], keep=keep)))
    assert out == {"pages": 0, "new_revisions": 0, "flagged": 0, "skipped_offline": 1}, out
    page = _page(db, pid)
    assert db.query(WikiRevision).count() == 0, "a revision with no text or diff was stored for a Stop"
    assert page.last_revid == 100 and page.last_checked_at is None, "the page moved past the revision the Stop cut"


def test_track_an_ores_score_a_stop_cut_fails_open_and_still_stores_nothing(db):
    """ORES fails OPEN (it returns ``{}``), so no exception ever reached ``update_page``: only the epoch can see the Stop."""
    from src.wiki.ores import OresClient
    from src.wiki.track import track_watched

    pid = _watched(db)
    ores = OresClient(session=_Session(["cut"]))
    out = track_watched(db, _TrackClient(), ores_client=ores)
    assert ores.last_outcome == "refused_offline"
    assert out.get("skipped_offline") == 1 and db.query(WikiRevision).count() == 0, out
    assert _page(db, pid).last_revid == 100


def test_track_a_baseline_whose_categories_a_stop_cut_is_not_stored(db):
    from src.wiki.track import track_watched

    pid = _watched(db, baseline=False)
    out = track_watched(db, _TrackClient(real="fetch_categories", session=_Session(["cut"]), baseline=True))
    assert out.get("skipped_offline") == 1, out
    page = _page(db, pid)
    assert page.baseline_revid is None and page.last_checked_at is None, "a baseline the Stop cut short was stored"


def test_track_a_diff_a_host_reset_with_no_stop_is_stored_without_it_as_before_the_control(db):
    from src.wiki.track import track_watched

    pid = _watched(db)
    out = track_watched(db, _TrackClient(real="fetch_compare", session=_Session(["reset"])))
    assert out == {"pages": 1, "new_revisions": 1, "flagged": out["flagged"]}, out
    rev = db.query(WikiRevision).one()
    assert rev.revid == 101 and rev.diff is None and rev.full_text == "text 101"
    assert _page(db, pid).last_revid == 101


# --------------------------------------------------------------------------- #
#  1.9 The versioned lane's text fetch (the adapter is the seam; the recorder is the pass)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def versioned_lane(wiki_lane):
    from src.versioned import pipeline, store
    from src.versioned.adapters import external_id_for
    from tests.test_versioned_lane import WATCHED

    with store.lane_session("wiki") as session:
        for title in WATCHED:
            pipeline.ensure_entity(session, external_id_for(EDITION, title), title=title, language=EDITION)


def _versioned_pass(monkeypatch, fetch):
    from src.testing.wiki_fixture import FixtureWikiClient
    from src.versioned import pipeline, store
    from src.versioned.adapters import WikiLaneAdapter
    from tests.test_versioned_lane import FEED

    asked: list[str] = []

    def fetch_version(self, external_id):
        asked.append(external_id)
        return fetch(external_id)

    monkeypatch.setattr(WikiLaneAdapter, "fetch_version", fetch_version)
    attempts: dict[int, float] = {}
    adapter = WikiLaneAdapter(client=FixtureWikiClient(max_recentchanges=50), editions=(EDITION,))
    with store.lane_session("wiki") as lane:
        result = pipeline.run_feed_once(lane, adapter, FEED, attempts=attempts)
    return result, attempts, asked


@pytest.mark.parametrize("keep", [False, True], ids=["cleared", "still-engaged"])
def test_versioned_a_text_fetch_a_stop_cut_is_not_cooled_down_or_an_error(versioned_lane, monkeypatch, keep):
    def cut(external_id):
        activate_kill_switch()
        if not keep:
            clear_kill_switch()
        raise requests.exceptions.ConnectionError(RESET)

    result, attempts, asked = _versioned_pass(monkeypatch, cut)
    assert len(asked) == 1, "the pass went on fetching through a Stop"
    assert attempts == {}, "the page is held back BACKLOG_COOLDOWN_S for a Stop"
    assert result.errors == [], result.errors


def test_versioned_a_genuine_fetch_failure_is_cooled_down_and_listed_as_before_the_control(versioned_lane, monkeypatch):
    def reset(external_id):
        raise requests.exceptions.ConnectionError(RESET)

    result, attempts, asked = _versioned_pass(monkeypatch, reset)
    assert len(asked) == 3 and len(attempts) == 3
    assert len(result.errors) == 3 and all(e.endswith(": ConnectionError") for e in result.errors)


# --------------------------------------------------------------------------- #
#  1.10 ORES
# --------------------------------------------------------------------------- #
def test_ores_a_request_a_stop_cut_and_cleared_is_named_as_the_switch(db):
    from src.wiki.ores import OresClient

    client = OresClient(session=_Session(["cut"]))
    assert client.score(EDITION, [1]) == {} and not kill_switch_active()
    assert client.last_outcome == "refused_offline", client.last_outcome


def test_ores_a_refusal_by_name_is_the_switchs_after_the_switch_is_cleared():
    from src.wiki.ores import OresClient

    client = OresClient(session=_RefusedByNameThenCleared())
    activate_kill_switch()
    assert client.score(EDITION, [1]) == {} and not kill_switch_active()
    assert client.last_outcome == "refused_offline", client.last_outcome


def test_ores_a_hosts_reset_with_no_stop_is_a_transport_error_the_control():
    from src.wiki.ores import OresClient

    client = OresClient(session=_Session(["reset"]))
    assert client.score(EDITION, [1]) == {}
    assert client.last_outcome == "transport_error"


# --------------------------------------------------------------------------- #
#  1.11 The wiki change stream
# --------------------------------------------------------------------------- #
def _stream(session):
    from src.wiki.stream import WikiEventStream

    return WikiEventStream(session=session, editions=(EDITION,), url="https://stream.example/v2/stream/recentchange", sleep=lambda _s: None)


def test_stream_a_connect_a_stop_cut_and_cleared_is_not_a_transport_error():
    stream = _stream(_Session(["cut"]))
    counters = stream.run(lambda _c: None, max_connections=1)
    assert counters.connections == 1 and counters.transport_errors == 0 and counters.consecutive_failures == 0, counters
    assert counters.last_failure is None


def test_stream_a_connect_a_stop_cut_while_still_engaged_ends_as_the_refusal_uncounted():
    from src.wiki.stream import StreamStopped

    stream = _stream(_Session(["cut"], keep=True))
    with pytest.raises(StreamStopped, match="kill switch"):
        stream.run(lambda _c: None, max_connections=2)
    assert stream.counters.transport_errors == 0 and stream.counters.connections == 1


def test_stream_a_stop_pressed_just_after_the_loop_check_and_cleared_after_the_refusal_is_a_stop():
    stream = _stream(_RefusedByNameThenCleared())
    real = stream._refuse_if_offline
    fired: list[str] = []

    def check(doing):
        real(doing)
        if not fired and doing.startswith("opening"):
            fired.append(doing)
            activate_kill_switch()  # right after the loop's own check let the connection go

    stream._refuse_if_offline = check  # type: ignore[method-assign]
    counters = stream.run(lambda _c: None, max_connections=1)
    assert fired, "premise: the Stop landed right after the loop's check"
    assert counters.transport_errors == 0, "a connection the Stop refused was counted as a transport fault"


def test_stream_a_hosts_reset_with_no_stop_is_counted_the_control():
    counters = _stream(_Session(["reset"])).run(lambda _c: None, max_connections=1)
    assert counters.transport_errors == 1 and counters.last_failure == "ConnectionError"


# --------------------------------------------------------------------------- #
#  1.13 / 1.14 The markets pass and the import-all route (their except; the seam is ``import_feed``)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def one_feed(monkeypatch):
    from tests.test_markets_stop_in_flight import _feeds

    feeds = _feeds(2)
    monkeypatch.setattr("src.markets.feed_catalog.load_feeds", lambda path=None: feeds)
    monkeypatch.setattr("src.markets.feed_catalog.load_index_feeds", lambda path=None: [])
    monkeypatch.setattr("src.markets.feed_catalog.feeds_for_category", lambda category=None: feeds)
    return feeds


def _import_feed_raising(monkeypatch, *, stop: str | None):
    calls: list[str] = []

    def _raises(session, **kw):
        calls.append(kw["symbol"])
        if stop == "clear":
            _stop_and_clear()
        elif stop == "by-name":
            assert kill_switch_active(), "premise: the Stop is engaged when the feed is asked for"
            clear_kill_switch()  # back online before the failure reaches the loop
        raise RuntimeError("store error")

    monkeypatch.setattr("src.markets.csv_feeds.import_feed", _raises)
    return calls


def test_markets_pass_a_feed_raising_across_a_stop_and_clear_is_no_failure(one_feed, monkeypatch, caplog):
    from src.markets import pipeline
    from tests.test_markets_stop_in_flight import TODAY, _Fetcher, _sess

    calls = _import_feed_raising(monkeypatch, stop="clear")
    with caplog.at_level(logging.WARNING):
        tally = pipeline.import_due_feeds(_sess(), fetcher=_Fetcher(), now=TODAY)
    assert calls == ["S1"] and tally == {"checked": 0, "imported": 0, "fresh": 0, "failed": 0}, tally
    assert "market feed f1 raised during a Stop" in caplog.text


def test_markets_pass_a_stop_pressed_just_after_the_loop_check_is_no_failure(one_feed, monkeypatch):
    from src.markets import pipeline
    from tests.test_markets_stop_in_flight import TODAY, _Fetcher, _sess

    _import_feed_raising(monkeypatch, stop="by-name")
    fired = _stop_right_after_the_check(
        monkeypatch, pipeline.import_due_feeds, "for feed in (*load_feeds(), *load_index_feeds()):", module=pipeline,
    )
    tally = pipeline.import_due_feeds(_sess(), fetcher=_Fetcher(), now=TODAY)
    assert fired, "premise: the Stop landed right after the loop's check"
    assert tally["failed"] == 0 and tally["checked"] == 0, tally


def test_markets_pass_a_feed_raising_with_no_stop_is_a_failure_the_control(one_feed, monkeypatch):
    from src.markets import pipeline
    from tests.test_markets_stop_in_flight import TODAY, _Fetcher, _sess

    calls = _import_feed_raising(monkeypatch, stop=None)
    tally = pipeline.import_due_feeds(_sess(), fetcher=_Fetcher(), now=TODAY)
    assert calls == ["S1", "S2"] and tally == {"checked": 2, "imported": 0, "fresh": 0, "failed": 2}, tally


def _route(monkeypatch):
    from src.api import markets
    from tests.test_markets_stop_in_flight import _Fetcher, _sess

    monkeypatch.setattr(markets, "following_fetcher", lambda *a, **k: _Fetcher())
    return markets, _sess()


def test_markets_route_a_feed_raising_across_a_stop_and_clear_is_not_an_error_row(one_feed, monkeypatch):
    markets, s = _route(monkeypatch)
    _import_feed_raising(monkeypatch, stop="clear")
    out = markets.import_all_feeds(db=s)
    assert out["failed"] == 0 and out["results"] == [] and out["skipped_offline"] == 2, out


def test_markets_route_a_stop_pressed_just_after_the_loop_check_is_not_an_error_row(one_feed, monkeypatch):
    markets, s = _route(monkeypatch)
    _import_feed_raising(monkeypatch, stop="by-name")
    fired = _stop_right_after_the_check(monkeypatch, markets.import_all_feeds, "for i, feed in enumerate(todo):")
    out = markets.import_all_feeds(db=s)
    assert fired, "premise: the Stop landed right after the loop's check"
    assert out["failed"] == 0 and out["results"] == [] and out["skipped_offline"] == 2, out


def test_markets_route_a_feed_raising_with_no_stop_is_an_error_row_the_control(one_feed, monkeypatch):
    markets, s = _route(monkeypatch)
    _import_feed_raising(monkeypatch, stop=None)
    out = markets.import_all_feeds(db=s)
    assert out["failed"] == 2 and [r["status"] for r in out["results"]] == ["error", "error"]
    assert "skipped_offline" not in out


# --------------------------------------------------------------------------- #
#  1.15 The price rules (the production fetcher)
# --------------------------------------------------------------------------- #
RULE_HOST = "prices.example"


class _Stub:
    def __init__(self, url, status=200, body=b"", headers=None):
        self.status_code, self.url, self._body = status, url, body
        self.headers = {"Content-Type": "text/html", **(headers or {})}
        self.content, self.text, self.encoding = body, body.decode("utf-8", "replace"), "utf-8"

    def iter_content(self, chunk_size=16384):
        yield self._body

    def close(self):
        pass


def _rule_fetcher(tmp_path, *, page: str):
    """The production fetcher over a scripted ``session.get``: robots allow all; the rule's page is ``"cut"`` (Stop pressed while it is
    in flight, the REAL guard refuses the connect, then cleared), ``"keep"`` (the same, still engaged) or ``"reset"`` (a host's own reset)."""
    f = make_fetcher(retry_backoff_s=0, max_retries=0, robots_cache_path=pathlib.Path(tmp_path) / "robots.json")
    assert type(f.session).__name__ == "Session", type(f.session)

    def guard(host, *_a, **_k):  # the first line of ``_guard_target``: no lookup is ever made
        if kill_switch_active():
            raise FetchFailed(KILL_SWITCH_REFUSAL)

    f._guard_target = guard  # type: ignore[method-assign]
    real_get = f.session.get

    def get(url, **kw):
        if kill_switch_active():
            return real_get(url, **kw)
        if url.endswith("/robots.txt"):
            return _Stub(url, 200, b"User-agent: *\nAllow: /\n", {"Content-Type": "text/plain"})
        if page in ("cut", "keep"):
            activate_kill_switch()
            try:
                return real_get(url, **kw)
            finally:
                if page == "cut":
                    clear_kill_switch()
        raise requests.exceptions.ConnectionError(RESET)

    f.session.get = get  # type: ignore[method-assign]
    return f


def _rules(db, n=2):
    src = Source(name=RULE_HOST, domain=RULE_HOST, enabled=True)
    db.add(src)
    db.flush()
    rows = [MarketExtractionRule(source_id=src.id, symbol=f"X{i}", url=f"https://{RULE_HOST}/p{i}", selector=".price") for i in range(n)]
    db.add_all(rows)
    db.commit()
    return rows


def _stamps(db):
    db.expire_all()
    return [(r.last_run_at, r.last_status) for r in db.execute(select(MarketExtractionRule).order_by(MarketExtractionRule.id)).scalars()]


@pytest.mark.parametrize("page", ["cut", "keep"], ids=["cleared", "still-engaged"])
def test_rule_a_page_a_stop_cut_is_skipped_offline_and_stamps_nothing(db, tmp_path, page):
    from src.markets.pipeline import run_rule

    rule = _rules(db, 1)[0]
    out = run_rule(db, rule, fetcher=_rule_fetcher(tmp_path, page=page))
    db.commit()  # the next commit on the shared session is what persisted a stamp
    assert out.status == "skipped_offline", out
    assert _stamps(db) == [(None, None)], "a Stop was stamped on the rule (Home reads it as a price feed needing attention)"


def test_rules_a_stop_ends_the_batch_and_no_later_rule_is_stamped(db, tmp_path):
    """R320's case: the switch stays engaged, and every later rule used to be stamped ``fetch_failed: network kill switch is active``."""
    from src.markets.pipeline import run_rules

    rules = _rules(db, 3)
    out = run_rules(db, rules, fetcher=_rule_fetcher(tmp_path, page="keep"))
    db.commit()
    assert out["tally"] == {"skipped_offline": 1}, out["tally"]
    assert _stamps(db) == [(None, None)] * 3


def test_rules_a_stop_pressed_just_after_the_loop_check_and_cleared_after_the_refusal_is_a_stop(db, tmp_path, monkeypatch):
    from src.markets import pipeline

    rules = _rules(db, 1)
    f = _rule_fetcher(tmp_path, page="reset")
    real_fetch = f.fetch

    def fetch(url, **kw):
        assert kill_switch_active(), "premise: the Stop is engaged when the page is asked for"
        try:
            return real_fetch(url, **kw)  # refused by name, before any request
        finally:
            clear_kill_switch()  # back online before the rule reads the failure

    f.fetch = fetch  # type: ignore[method-assign]
    fired = _stop_right_after_the_check(monkeypatch, pipeline.run_rules, "for rule in rules:", module=pipeline)
    out = pipeline.run_rules(db, rules, fetcher=f)
    db.commit()
    assert fired, "premise: the Stop landed right after the loop's check"
    assert out["tally"] == {"skipped_offline": 1}, out["tally"]
    assert _stamps(db) == [(None, None)]


def test_rule_a_hosts_reset_with_no_stop_is_still_fetch_failed_the_control(db, tmp_path):
    from src.markets.pipeline import run_rules

    rules = _rules(db, 2)
    out = run_rules(db, rules, fetcher=_rule_fetcher(tmp_path, page="reset"))
    db.commit()
    assert out["tally"] == {"fetch_failed": 2}
    assert all(at is not None and status.startswith("fetch_failed: ") for at, status in _stamps(db))


# --------------------------------------------------------------------------- #
#  1.16 The field test (its step recorder is what is under test)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("keep", [False, True], ids=["cleared", "still-engaged"])
def test_field_test_a_step_a_stop_cut_is_not_done_and_runs_again(keep):
    from src.monitoring import field_test as FT

    def step():
        activate_kill_switch()
        if not keep:
            clear_kill_switch()
        return {"imported": 3, "failed": 37}

    FT._run_step("markets_import_all", step)
    assert not FT._step_done("markets_import_all"), "a step the Stop cut was recorded done: it would never run again"
    rec = FT.recent_results()[-1]
    assert rec["ok"] is False and "kill switch" in rec["stopped"] and rec["result"] == {"imported": 3, "failed": 37}


def test_field_test_a_step_with_no_stop_is_done_as_before_the_control():
    from src.monitoring import field_test as FT

    FT._run_step("markets_import_all", lambda: {"imported": 3, "failed": 1})
    assert FT._step_done("markets_import_all") and "stopped" not in FT.recent_results()[-1]


# --------------------------------------------------------------------------- #
#  1.17 The Wikidata items job (its own getter over the real guarded session)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def factory():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)

    @contextmanager
    def _f():
        s = Sess()
        try:
            yield s
        finally:
            s.close()

    yield _f
    eng.dispose()


def _items(factory, getter=None, n_batches=2):
    from src.analytics.ring_loader import RateGate
    from src.entities import items as IT
    from src.entities.wikidata_items import BATCH_MAX

    qids = [f"Q{i}" for i in range(1, BATCH_MAX * n_batches + 1)]
    return IT.fetch_items(qids, session_factory=factory, get=getter, gate=RateGate(min_interval_s=0.0, sleep=lambda _s: None))


def test_items_a_batch_a_stop_cut_and_cleared_is_the_switchs_and_stays_pending(factory, monkeypatch):
    session = _Session(["cut"])
    monkeypatch.setattr("src.safety.fetcher.guarded_session", lambda **_k: session)
    out = _items(factory)
    assert out["refused"] == 0 and out["stopped_by_airplane_mode"] is True and out["pending"] == out["requested"], out
    assert len(session.urls) == 1, "the job went on after the Stop"


def test_items_a_stop_pressed_just_after_the_loop_check_and_cleared_after_the_refusal_is_a_stop(factory, monkeypatch):
    from src.entities import items as IT

    def getter(url):
        try:
            return IT._default_getter(url)  # the real guarded session refuses by name
        finally:
            clear_kill_switch()

    fired = _stop_right_after_the_check(monkeypatch, IT.fetch_items, "for batch in todo:", module=IT, name="_kill_switch_active")
    out = _items(factory, getter)
    assert fired, "premise: the Stop landed right after the loop's check"
    assert out["refused"] == 0 and out["stopped_by_airplane_mode"] is True, out


def test_items_a_hosts_reset_with_no_stop_is_refused_as_before_the_control(factory, monkeypatch):
    from src.entities.wikidata_items import BATCH_MAX

    session = _Session(["reset", "reset"])
    monkeypatch.setattr("src.safety.fetcher.guarded_session", lambda **_k: session)
    out = _items(factory)
    assert out["refused"] == 2 * BATCH_MAX and out["stopped_by_airplane_mode"] is False, out


# --------------------------------------------------------------------------- #
#  1.18 The OSM replication source
# --------------------------------------------------------------------------- #
def test_osm_a_state_read_a_stop_cut_and_cleared_is_refused_not_unavailable():
    from src.osm import replication as R

    with pytest.raises(R.DiffRefused) as ei:
        R.GuardedDiffSource("europe", session_factory=lambda _u: _Session(["cut"])).fetch_state()
    assert str(ei.value) == R.KILL_SWITCH_TEXT and not kill_switch_active()


def test_osm_a_mirrors_reset_with_no_stop_is_unavailable_the_control():
    from src.osm import replication as R

    with pytest.raises(R.DiffUnavailable):
        R.GuardedDiffSource("europe", session_factory=lambda _u: _Session(["reset"])).fetch_state()


# --------------------------------------------------------------------------- #
#  R618 (a) The custody log's OpenTimestamps fallback (``ots_stamp`` is the seam: the library is not installed here)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def ots(monkeypatch):
    """OpenTimestamps as installed: the real ``ots_stamp``'s own kill-switch check runs before it builds anything."""
    import src.custody.timestamp as T

    monkeypatch.setattr(T, "OTS_AVAILABLE", True)
    return T


def _custody(tmp_path):
    from src.custody.log import CustodyLog
    from src.custody.signing import HybridSigner

    signer = HybridSigner(ed25519_path=tmp_path / "ed.pem", mldsa_path=tmp_path / "ml.key")
    return CustodyLog(db_path=str(tmp_path / "custody.db"), signer=signer, anchoring_mode="opentimestamps")


def _calendars_cut(monkeypatch, *, stop: bool):
    """The calendar submissions, the Stop pressed while they are in flight (every calendar refused) and cleared again."""
    import src.custody.log as L
    from src.custody.timestamp import TimestampUnavailable

    def ots_stamp(digest):
        if stop:
            _stop_and_clear()
        raise TimestampUnavailable("No OpenTimestamps calendar could be reached: https://a.example: ConnectionError")

    monkeypatch.setattr(L, "ots_stamp", ots_stamp)


def test_custody_a_submission_a_stop_cut_writes_no_local_proof_in_its_place(tmp_path, monkeypatch, ots):
    from src.custody.timestamp import TimestampUnavailable

    _calendars_cut(monkeypatch, stop=True)
    with _custody(tmp_path) as log:
        with pytest.raises(TimestampUnavailable, match="kill switch"):
            log.record("article:1", "h1", "ingest")
        assert log.all_entries() == [], "a permanent local-only proof was written for a Stop"


def test_custody_a_submission_refused_with_the_switch_still_engaged_writes_nothing_either(tmp_path, ots):
    """R320's case, through the REAL ``ots_stamp``: its own check refuses by name, and the fallback used to write a local proof."""
    from src.custody.timestamp import TimestampUnavailable

    activate_kill_switch()
    with _custody(tmp_path) as log:
        with pytest.raises(TimestampUnavailable, match="kill switch"):
            log.record("article:1", "h1", "ingest")
        assert log.all_entries() == []


def test_custody_the_log_route_names_the_switch_when_a_stop_refuses_the_entry(tmp_path, monkeypatch, ots):
    """The manual route answers the refusal in its own words (503), never a bare 500 that would point the operator elsewhere."""
    from fastapi import HTTPException

    import src.api.custody as C

    monkeypatch.setattr(C, "_log", lambda: _custody(tmp_path))
    activate_kill_switch()
    with pytest.raises(HTTPException) as caught:
        C.log_action(C.LogRequest(item_id="article:1", item_hash="h1", action="ingest"))
    assert caught.value.status_code == 503 and "kill switch" in str(caught.value.detail), caught.value.detail
    with _custody(tmp_path) as log:
        assert log.all_entries() == []


def test_custody_an_ingest_entry_a_stop_cut_is_owed_for_a_later_anchor_not_lost(db, tmp_path, monkeypatch, ots):
    """The ingest auto-log stays fail-open: the article is stored, and its entry is queued as owed (``src.custody.pending``), which the
    end of a later collection pass writes, marked late, with the anchor this mode asks for."""
    from src.custody import pending
    from src.custody.log import CustodyLog
    from src.custody.settings import CustodySettings
    from src.ingest.pipeline import _maybe_record_custody
    from tests.test_custody_batch import _stored

    monkeypatch.setattr(
        "src.custody.settings.load_settings", lambda: CustodySettings(auto_log_on_ingest=True, anchoring_mode="opentimestamps"),
    )
    _calendars_cut(monkeypatch, stop=True)
    art = _stored(db, 1)[0]
    _maybe_record_custody(art)
    assert [int(r["article_id"]) for r in pending.read_pending()] == [art.id], "the entry is neither written nor owed"
    with CustodyLog() as log:
        assert log.all_entries() == []


def test_custody_a_genuine_calendar_failure_still_falls_back_to_a_local_proof_the_control(tmp_path, monkeypatch, ots):
    _calendars_cut(monkeypatch, stop=False)
    with _custody(tmp_path) as log:
        entry = log.record("article:1", "h1", "ingest")
    assert entry.timestamp["kind"] == "local" and "requested but unavailable" in entry.timestamp["detail"]


def test_custody_opentimestamps_not_installed_under_a_stop_still_falls_back_as_before(tmp_path):
    """The switch is not why a submission that cannot be made failed: the local proof says the library is missing, as before."""
    activate_kill_switch()
    with _custody(tmp_path) as log:
        entry = log.record("article:1", "h1", "ingest")
    assert entry.timestamp["kind"] == "local" and "not installed" in entry.timestamp["detail"]


# --------------------------------------------------------------------------- #
#  R618 (b) The ring loader's candidate loop
# --------------------------------------------------------------------------- #
def _candidates(n=3):
    from src.analytics.ring_loader import Candidate

    return [Candidate(term=f"t{i}", normalized=f"t{i}", language="en", articles=1, mentions=1) for i in range(n)]


def _load(getter):
    from src.analytics.ring_loader import RateGate, load_rings_from_wikidata

    return load_rings_from_wikidata(_candidates(), get=getter, gate=RateGate(min_interval_s=0.0, sleep=lambda _s: None), write=False)


@pytest.mark.parametrize("keep", [False, True], ids=["cleared", "still-engaged"])
def test_rings_a_candidate_a_stop_cut_is_no_error_and_the_load_ends(keep):
    from src.analytics.ring_loader import SKIP_ERROR

    session = _Session(["cut"], keep=keep)
    asked: list[str] = []

    def getter(url):
        asked.append(url)
        return session.get(url, timeout=5).json()

    out = _load(getter)
    assert SKIP_ERROR not in out["skipped"], out["skipped"]
    assert out["stopped"] is True and len(asked) == 1, (out, asked)


def test_rings_a_stop_pressed_just_after_the_loop_check_and_cleared_after_the_refusal_is_a_stop(monkeypatch):
    from src.analytics import ring_loader as RL

    def getter(url):
        try:
            return RL._default_getter(url)  # the real guarded session refuses by name
        finally:
            clear_kill_switch()

    fired = _stop_right_after_the_check(monkeypatch, RL.load_rings_from_wikidata, "for i, cand in enumerate(candidates):")
    out = _load(getter)
    assert fired, "premise: the Stop landed right after the loop's check"
    assert out["skipped"] == {} and out["stopped"] is True, out


def test_rings_a_stop_between_two_candidates_asks_for_nothing_more():
    """R618's loop check: a Stop engaged before a candidate's requests ends the load there, and nothing more is asked."""
    from src.analytics.ring_loader import SKIP_NO_ITEM, RateGate, load_rings_from_wikidata

    looks = {"n": 0}

    def should_stop():
        looks["n"] += 1
        if looks["n"] == 2:
            activate_kill_switch()  # pressed between the first candidate and the second
        return False

    asked: list[str] = []
    out = load_rings_from_wikidata(
        _candidates(), get=lambda url: (asked.append(url), {"search": []})[1], should_stop=should_stop,
        gate=RateGate(min_interval_s=0.0, sleep=lambda _s: None), write=False,
    )
    assert len(asked) == 1, asked
    assert out["skipped"] == {SKIP_NO_ITEM: 1} and out["stopped"] is True, out


def test_rings_a_genuine_failure_with_no_stop_is_still_an_error_and_the_load_goes_on_the_control():
    from src.analytics.ring_loader import SKIP_ERROR

    session = _Session(["reset"] * 3)
    out = _load(lambda url: session.get(url, timeout=5).json())
    assert out["skipped"] == {SKIP_ERROR: 3} and out["stopped"] is False, out
