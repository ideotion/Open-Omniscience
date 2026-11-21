"""R772(a) (row 245): the Wikipedia stream and ORES scoring are bound to the transport they were approved under.

A change of the transport (protected mode switched on or off, another proxy, settings that cannot be read) stops them with a
named reason. It is not a transport failure: no backoff, no reconnect over the new transport. The lane stays HELD until the
operator turns it on again through the stream button, which shows the held reason and the transport now in force; going online,
Start, Run-now and a settings write do not lift it. A tracking batch (and the ORES scores inside it) stops at the change too.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import requests

from src.safety import transport_watch as tw

_ROOT = Path(__file__).resolve().parents[1]
_PROXY = "socks5h://127.0.0.1:9050"


def _settings(monkeypatch, **kw):
    import src.safety.settings as settings

    st = settings.SafetySettings(**kw)
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    return st


def _protect(monkeypatch):
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    tw.bump()


@pytest.fixture(autouse=True)
def _fast_recheck(monkeypatch):
    monkeypatch.setattr(tw, "RECHECK_S", 0.0)


class _Adapter(requests.adapters.BaseAdapter):
    """Answers every request with a small body and counts what was SENT. No socket."""

    def __init__(self) -> None:
        super().__init__()
        self.sent = 0

    def send(self, request, *args, **kwargs):  # type: ignore[override]
        self.sent += 1
        resp = requests.Response()
        resp.status_code = 200
        resp.raw = io.BytesIO(b"{}")
        resp.url = request.url
        resp.request = request
        return resp

    def close(self):
        return None


# --------------------------------------------------------------------------- the shared session answers to the caller's run


def test_a_shared_session_rebuilt_under_the_new_transport_still_answers_to_the_callers_run(monkeypatch):
    """The lane's threads and a click share ``session/wiki``. A session built AFTER the switch is clean on its own watch; the lane's
    run was approved direct, so a request it makes through that new session is refused before anything is sent."""
    from src.safety.fetcher import _session_for
    from src.safety.settings import SafetySettings

    _settings(monkeypatch)
    lane = tw.for_launch(tw.mode_now())
    _protect(monkeypatch)
    s = _session_for(SafetySettings(fetch_mode="protected", http_proxy=_PROXY))  # built outside the run, under the new transport
    adapter = _Adapter()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    with tw.run(lane), pytest.raises(tw.TransportStopped) as exc:
        s.get("https://stream.example.org/v2/stream/recentchange")
    assert exc.value.reason == "protected"
    assert adapter.sent == 0, "nothing goes out over the new transport for a run approved over the old one"


def test_outside_any_run_the_session_only_answers_to_its_own_watch(monkeypatch):
    from src.safety.fetcher import GuardedSession

    s = GuardedSession()
    assert s._watches() == ()
    own = tw.TransportWatch(transport=tw.DIRECT)
    s.transport_watch = own
    assert s._watches() == (own,)
    with tw.run(own):
        assert s._watches() == (own,), "the same watch is asked once"
    other = tw.TransportWatch(transport=tw.DIRECT)
    with tw.run(other):
        assert s._watches() == (own, other)


# --------------------------------------------------------------------------- the stream: a stop, never a fault


class _RaisingSession:
    def __init__(self, exc):
        self.exc, self.calls, self.headers = exc, 0, {}

    def get(self, *_a, **_kw):
        self.calls += 1
        raise self.exc


def test_the_stream_does_not_retry_a_transport_change(monkeypatch):
    from src.wiki.stream import WikiEventStream

    session = _RaisingSession(tw.TransportStopped("protected"))
    slept: list[float] = []
    stream = WikiEventStream(session=session, editions=("oo",), sleep=slept.append)
    with pytest.raises(tw.TransportStopped):
        stream.run(lambda _c: None, max_connections=5)
    assert session.calls == 1, "no reconnect"
    assert slept == [], "no backoff"
    assert stream.counters.transport_errors == 0 and stream.counters.consecutive_failures == 0, "not counted as a fault"


def test_the_stream_stops_at_the_next_event_after_the_change(monkeypatch):
    from src.testing.wiki_stream_fixture import FixtureStreamSession
    from src.wiki.stream import WikiEventStream

    _settings(monkeypatch)
    run = tw.for_launch(tw.mode_now())
    seen: list = []

    def on_change(change):
        seen.append(change)
        if len(seen) == 2:
            _protect(monkeypatch)

    stream = WikiEventStream(session=FixtureStreamSession(), editions=("oo",), sleep=lambda _s: None)
    with tw.run(run), pytest.raises(tw.TransportStopped):
        stream.run(on_change, max_connections=1)
    assert len(seen) == 2, "no event is acted on after the change"


# --------------------------------------------------------------------------- the runner holds


def _runner(monkeypatch, *, held: list, max_connections=1):
    from src.testing.wiki_fixture import FixtureWikiClient
    from src.testing.wiki_stream_fixture import FixtureStreamSession
    from src.wiki.lane import WikiStreamAdapter
    from src.wiki.runner import WikiLaneRunner
    from src.wiki.stream import WikiEventStream
    from src.wiki.tiers import budget_state

    _settings(monkeypatch)
    return WikiLaneRunner(
        adapter=WikiStreamAdapter(client=FixtureWikiClient(), editions=("oo",)),
        stream=WikiEventStream(session=FixtureStreamSession(), editions=("oo",), sleep=lambda _s: None),
        lane_session=lambda: None,
        state_of=lambda: "running",
        hot_sets=lambda: {},
        budget=lambda: budget_state(total_gb=20, disk_bytes=0, editions=1),
        sleep=lambda _s: None,
        max_connections=max_connections,
        transport_watch=tw.for_launch(tw.mode_now()),
        on_hold=held.append,
    )


@pytest.mark.parametrize(
    ("change", "held_by"),
    [("protected", "protected"), ("unreadable", "settings")],
)
def test_a_transport_change_holds_the_runner_by_name_and_nothing_revives_it(monkeypatch, change, held_by):
    import threading

    held: list = []
    runner = _runner(monkeypatch, held=held, max_connections=None)
    ended = threading.Thread(target=lambda: None)
    ended.start()
    ended.join()
    runner._thread = ended  # a stream that ended: what revive_stream would start again but for the hold
    assert runner._should_stop() is False
    if change == "protected":
        _protect(monkeypatch)
    else:
        import src.safety.settings as settings

        monkeypatch.setattr(settings, "load_settings", lambda: (_ for _ in ()).throw(RuntimeError("locked")))
    assert runner._stream_should_stop() is True, "seen at the next event, never behind the state cache"
    assert runner.held_by == held_by and held == [held_by]
    runner._stop.clear()  # only the hold is left to refuse: the guard under test, not the stop flag
    assert runner.start() is False, "a held runner does not start"
    assert runner.revive_stream() is False, "and the drain loop's revive does not revive it"
    assert runner.run_until_stopped(max_drains=3) == 0, "no drain runs on a held lane"


def test_the_stream_thread_that_meets_the_change_holds_the_lane(monkeypatch):
    held: list = []
    runner = _runner(monkeypatch, held=held)
    _protect(monkeypatch)
    runner._stream_body()
    assert runner.held_by == "protected" and held == ["protected"]


def test_a_stop_raised_inside_the_stream_holds_the_lane_too(monkeypatch):
    held: list = []
    runner = _runner(monkeypatch, held=held)

    def raising_run(*_a, **_kw):
        raise tw.TransportStopped("proxy")

    monkeypatch.setattr(runner._stream, "run", raising_run)
    runner._stream_body()
    assert runner.held_by == "proxy" and held == ["proxy"]
    assert runner.last_stream_end == "TransportStopped"


# --------------------------------------------------------------------------- the service: only the operator's click lifts it


@pytest.fixture
def _service(monkeypatch):
    import src.wiki.service as service

    monkeypatch.setattr(service, "_state_of", lambda: "running")
    monkeypatch.setattr(service, "_APPROVED", None)
    monkeypatch.setattr(service, "_RUNNER", None)
    monkeypatch.setattr(service, "_DRAIN_THREAD", None)
    service.clear_hold()
    yield service
    service.clear_hold()


def test_going_online_start_and_a_settings_write_do_not_lift_the_hold(monkeypatch, _service):
    built: list = []
    monkeypatch.setattr(_service, "_build", lambda approved=None: built.append(approved))
    holder = object()
    monkeypatch.setattr(_service, "_RUNNER", holder)
    _service._note_hold(holder, "protected")
    monkeypatch.setattr(_service, "_RUNNER", None)
    assert _service.lane_hold()["held_by"] == "protected"
    assert _service.start_wiki_lane() is False
    assert built == [], "no runner was built while held"


def test_a_runner_that_held_itself_before_its_record_landed_is_held_not_rebuilt(monkeypatch, _service):
    """The race both security reads found: the runner is held and stopped, the service has no record yet, and a Start lands."""
    built: list = []
    monkeypatch.setattr(_service, "_build", lambda *a: built.append(a))

    class _Held:
        held_by = "protected"
        streaming = False
        stopped = True

    monkeypatch.setattr(_service, "_RUNNER", _Held())
    assert _service.start_wiki_lane() is False
    assert built == [] and _service.lane_hold()["held_by"] == "protected"


def test_a_lane_started_again_after_the_transport_changed_while_it_was_off_is_held(monkeypatch, _service):
    """Stopped by airplane mode or paused, then protected mode switched: going online is not a click that showed the new transport."""
    built: list = []
    monkeypatch.setattr(_service, "_build", lambda *a: built.append(a))
    _settings(monkeypatch)
    monkeypatch.setattr(_service, "_APPROVED", tw.mode_now())
    _protect(monkeypatch)
    assert _service.start_wiki_lane() is False
    assert built == [] and _service.lane_hold()["held_by"] == "protected"


def test_a_resume_that_starts_nothing_keeps_the_hold(monkeypatch, _service):
    monkeypatch.setattr(_service, "start_wiki_lane", lambda **_kw: False)
    holder = object()
    monkeypatch.setattr(_service, "_RUNNER", holder)
    _service._note_hold(holder, "proxy")
    monkeypatch.setattr(_service, "_RUNNER", None)
    assert _service.resume_held_lane("direct") is False
    assert _service.lane_hold()["held_by"] == "proxy", "a later Start cannot start it over a transport nobody was shown"


def test_a_hold_from_a_runner_that_is_no_longer_current_is_ignored(_service):
    _service._note_hold(object(), "protected")
    assert _service.lane_hold() is None


def test_the_resume_click_starts_a_new_lane_over_the_transport_it_was_shown(monkeypatch, _service):
    approved: list = []

    class _R:
        streaming = False
        stopped = False
        held_by = None

        def start(self):
            return True

        def run_until_stopped(self):
            return 0

    monkeypatch.setattr(_service, "_build", lambda approved_=None: approved.append(approved_) or _R())
    holder = object()
    monkeypatch.setattr(_service, "_RUNNER", holder)
    _service._note_hold(holder, "protected")
    monkeypatch.setattr(_service, "_RUNNER", None)
    assert _service.resume_held_lane("protected:abc") is True
    assert _service.lane_hold() is None
    assert approved == ["protected:abc"], "the new lane is approved under the transport the click was shown"


# --------------------------------------------------------------------------- the status and the resume endpoint


def test_the_status_names_the_hold_and_the_transport_a_click_would_use(monkeypatch, _service):
    from src.api.scheduler import _wiki_lane_block, _wiki_lane_reason

    _protect(monkeypatch)
    holder = object()
    monkeypatch.setattr(_service, "_RUNNER", holder)
    _service._note_hold(holder, "protected")
    monkeypatch.setattr(_service, "_RUNNER", None)
    block = _wiki_lane_block()
    assert block["held_by"] == "protected"
    assert block["resume_transport"] == "proxy"
    assert block["resume_token"] == tw.display_token()
    assert _PROXY not in repr(block) and "9050" not in repr(block), "never the proxy address"
    assert _wiki_lane_reason("running", False, held=True) == "transport-held"
    from src.ingest import activate_kill_switch, clear_kill_switch

    activate_kill_switch()
    try:
        assert _wiki_lane_reason("running", False, held=True) == "transport-held", "going online would not lift it"
    finally:
        clear_kill_switch()


def test_the_resume_endpoint_refuses_without_the_token_of_the_transport_now_in_force(monkeypatch, _service, tmp_path):
    from fastapi import HTTPException

    from src.api import scheduler as api
    from src.ingest import clear_kill_switch

    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    clear_kill_switch()
    saved: list = []
    monkeypatch.setattr(api, "save_settings", lambda fields, **_kw: saved.append(fields))
    monkeypatch.setattr(api, "_wiki_lane_block", lambda: {})
    _settings(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        api.resume_wiki_lane(api.WikiLaneResumeBody(transport=tw.display_token()))
    assert exc.value.status_code == 409, "nothing is held"

    holder = object()
    monkeypatch.setattr(_service, "_RUNNER", holder)
    _service._note_hold(holder, "protected")
    monkeypatch.setattr(_service, "_RUNNER", None)
    token_direct = tw.display_token()
    _protect(monkeypatch)
    for body in (None, api.WikiLaneResumeBody(transport=""), api.WikiLaneResumeBody(transport=token_direct)):
        with pytest.raises(HTTPException) as exc:
            api.resume_wiki_lane(body)
        assert exc.value.status_code == 409 and exc.value.detail == api.WIKI_TRANSPORT_CHANGED
    assert saved == [] and _service.lane_hold() is not None

    out = api.resume_wiki_lane(api.WikiLaneResumeBody(transport=tw.display_token()))
    assert out["resumed"] is True
    assert saved == [{"wiki_lane_state": "running"}], "the click turns the lane on again"
    assert _service.lane_hold() is None


def test_the_resume_endpoint_refuses_in_airplane_mode(monkeypatch, _service):
    from fastapi import HTTPException

    from src.api import scheduler as api
    from src.ingest import activate_kill_switch, clear_kill_switch

    _settings(monkeypatch)
    holder = object()
    monkeypatch.setattr(_service, "_RUNNER", holder)
    _service._note_hold(holder, "protected")
    monkeypatch.setattr(_service, "_RUNNER", None)
    activate_kill_switch()
    try:
        with pytest.raises(HTTPException) as exc:
            api.resume_wiki_lane(api.WikiLaneResumeBody(transport=tw.display_token()))
        assert exc.value.status_code == 409 and "Airplane mode" in str(exc.value.detail)
    finally:
        clear_kill_switch()
    assert _service.lane_hold() is not None


# --------------------------------------------------------------------------- tracking and ORES


def test_ores_names_a_transport_change_and_does_not_fail_open():
    from src.wiki.ores import OUTCOMES, OresClient

    client = OresClient(session=_RaisingSession(tw.TransportStopped("proxy")))
    with pytest.raises(tw.TransportStopped):
        client.score("enwiki", [1])
    assert client.last_outcome == "transport_changed" and client.last_outcome in OUTCOMES


def test_a_tracking_batch_stops_at_the_change_and_says_so(monkeypatch):
    import src.wiki.track as track

    _settings(monkeypatch)
    asked: list = []

    def fake_update(session, client, page, **_kw):
        asked.append(page)
        if len(asked) == 2:
            _protect(monkeypatch)
            raise tw.TransportStopped("protected")
        return {"new": 0, "flagged": 0}

    class _Q:
        def filter_by(self, **_kw):
            return self

        def order_by(self, *_a):
            return self

    class _S:
        def query(self, *_a):
            return _Q()

        def rollback(self):
            return None

    monkeypatch.setattr(track, "update_page", fake_update)
    import src.database.query as q

    monkeypatch.setattr(q, "capped", lambda _query, _n: type("C", (), {"all": lambda self: ["a", "b", "c", "d"]})())
    out = track.track_watched(_S(), object())
    assert asked == ["a", "b"], "the rest of the pages are not asked over the new transport"
    assert out["stopped_by"] == "protected" and out["pages"] == 1


def test_a_page_whose_window_saw_the_change_is_not_stored(monkeypatch):
    from src.wiki.track import _refuse_if_stopped

    rolled: list = []

    class _S:
        def rollback(self):
            rolled.append(1)

    from src.ingest import kill_switch_epoch

    _settings(monkeypatch)
    run = tw.for_launch(tw.mode_now())
    with tw.run(run):
        _refuse_if_stopped(_S(), kill_switch_epoch())  # nothing changed: stored
        _protect(monkeypatch)
        with pytest.raises(tw.TransportStopped):
            _refuse_if_stopped(_S(), kill_switch_epoch())
    assert rolled == [1]


# --------------------------------------------------------------------------- the UI


def test_the_stream_button_resumes_a_held_lane_only_through_the_resume_route_after_naming_the_transport():
    src = (_ROOT / "src/static/app-sources.js").read_text(encoding="utf-8")
    start = src.index("async function resumeHeldWikiLane(")
    body = src[start : src.index("async function stopWikiLane(", start)]
    assert "/api/scheduler/wiki-lane/resume" in body
    assert "confirm(lines.why" in body and "lines.over" in body, "the reason and the transport are shown before the click"
    assert body.index("confirm(") < body.index("ensureOnline(") < body.index("/api/scheduler/wiki-lane/resume")
    assert "held.token" in body
    toggle = src[src.index("async function toggleWikiLane("):start]
    assert "if (_wikiLaneWhy && _wikiLaneWhy.held) { await resumeHeldWikiLane(); return; }" in toggle
    assert '"transport-held"' in src


def test_a_page_whose_text_fetch_met_the_change_is_rolled_back_not_stored_without_text(monkeypatch):
    """The enrichment fetches fail open; a transport change is not a missing enrichment: the page is not stored, ``last_revid`` stays."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, WikiRevision
    from src.wiki.track import ensure_page, track_watched

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    page = ensure_page(db, "en", "Berlin")
    page.watched = True
    page.baseline_revid = page.last_revid = 100
    db.commit()

    class _Client:
        def fetch_revisions(self, wiki, title, *, limit=20, older_than=None):
            return [{"revid": 101, "parentid": 100, "user": "x", "timestamp": "2026-11-21T00:00:00Z", "size": 10, "comment": ""}]

        def fetch_revision_texts(self, wiki, revids):
            raise tw.TransportStopped("protected")

        def fetch_compare(self, wiki, a, b):
            return {"added": "", "removed": "", "added_bytes": 0, "removed_bytes": 0}

    _settings(monkeypatch)
    out = track_watched(db, _Client())
    assert out["stopped_by"] == "protected" and out["pages"] == 0
    assert db.query(WikiRevision).count() == 0
    db.refresh(page)
    assert page.last_revid == 100
