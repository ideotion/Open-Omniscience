"""The ``allpages`` walk (Q701 = c; S05-06's S2 + S3): driven on the fixture, mostly at its edges.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The brief's negative-space lens is the spine of this file: "an edition answering fewer than
50 titles, a missing continuation token, a page deleted mid-walk, a budget already spent --
each a recorded gap, never a 0 or a retry storm". Then the three things a walk must never do
whatever the network says: advance its bookmark on an answer it could not read, fall back
to another transport when the chosen one is refused, and turn a walked page into a page the
lane follows.
"""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path

import pytest
import requests
from sqlalchemy import select

from src.ingest import activate_kill_switch, clear_kill_switch
from src.testing.wiki_fixture import FixtureWikiClient
from src.versioned.models import VersionedEntity
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import mediawiki as mw
from src.wiki import walk as W
from src.wiki.lane_models import WikiWalkCursor, WikiWalkPage, WikiWalkSample
from src.wiki.tiers import budget_state

EDITION = "oo"


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    try:
        yield
    finally:
        dispose_all()


def _session():
    return lane_session("wiki")


def _plenty():
    return budget_state(total_gb=20, disk_bytes=0, editions=1)


def _spent():
    return budget_state(total_gb=1, disk_bytes=2 * 1024**3, editions=1)


class Clock:
    """A monotonic clock a test moves by hand."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _walker(client, *, editions=(EDITION,), batch=2, enabled=True, budget=None, clock=None,
            transport="direct"):
    return W.WikiWalker(
        client=client,
        editions=editions,
        lane_session=_session,
        budget=lambda: budget or _plenty(),
        enabled=lambda: enabled,
        transport=lambda: transport,
        batch=batch,
        monotonic=clock or Clock(),
    )


def _cursor(edition=EDITION):
    with _session() as db:
        row = db.get(WikiWalkCursor, edition)
        return None if row is None else {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _pages(edition=EDITION):
    with _session() as db:
        return {
            r.page_id: (r.title, r.qid, r.length_bytes, r.last_revid, r.pass_no)
            for r in db.execute(select(WikiWalkPage).where(WikiWalkPage.edition == edition)).scalars()
        }


# --------------------------------------------------------------------------- #
# The request and the parser: pure, no lane.
# --------------------------------------------------------------------------- #
def test_the_walk_asks_for_50_ARTICLES_without_redirects_and_nothing_else():
    params = mw.build_walk_params()
    assert params["generator"] == "allpages"
    assert params["gapnamespace"] == 0 and params["gapfilterredir"] == "nonredirects"
    assert params["gaplimit"] == mw.MAX_PAGES_PER_REQUEST == 50
    assert params["prop"] == "info|pageprops" and params["ppprop"] == "wikibase_item"
    assert params["formatversion"] == 2
    assert "rvprop" not in params and "revisions" not in params["prop"], "COLD is metadata only"


def test_the_continuation_goes_back_VERBATIM():
    cont = {"gapcontinue": "Zebra_(film)", "continue": "gapcontinue||"}
    params = mw.build_walk_params(cont)
    assert params["gapcontinue"] == "Zebra_(film)" and params["continue"] == "gapcontinue||"


@pytest.mark.parametrize("limit", [0, 51, 500])
def test_a_batch_outside_1_to_50_is_REFUSED_never_clamped(limit):
    with pytest.raises(ValueError, match="1 to 50"):
        mw.build_walk_params(limit=limit)


def _page(pid, title, **kw):
    return {"pageid": pid, "ns": 0, "title": title, "lastrevid": pid * 10, "length": pid * 3, **kw}


def test_an_answer_with_FEWER_than_50_pages_is_stored_as_it_is_never_padded():
    out = mw.parse_walk_batch(
        {"batchcomplete": True, "continue": {"gapcontinue": "C", "continue": "gapcontinue||"},
         "query": {"pages": [_page(1, "A"), _page(2, "B")]}}
    )
    assert [p["page_id"] for p in out["pages"]] == [1, 2]
    assert out["continue"] == {"gapcontinue": "C", "continue": "gapcontinue||"}
    assert out["complete"] is False and out["malformed"] is None


def test_NO_continuation_with_batchcomplete_is_the_end_of_the_pass():
    out = mw.parse_walk_batch({"batchcomplete": True, "query": {"pages": [_page(3, "Z")]}})
    assert out["complete"] is True and out["continue"] is None


def test_NO_continuation_and_NO_batchcomplete_is_MALFORMED_never_the_end():
    """A truncated body that happened to parse must not end a pass at the page it was cut at."""
    out = mw.parse_walk_batch({"query": {"pages": [_page(3, "Z")]}})
    assert out["complete"] is False
    assert out["malformed"] == "neither-continue-nor-batchcomplete"
    assert out["pages"] == [], "nothing from an unreadable answer is stored"


@pytest.mark.parametrize(
    "cont, why",
    [
        ({"action": "delete"}, "continuation-foreign-key"),
        ({"gapcontinue": ["A"]}, "continuation-foreign-value"),
        ([], "continuation-not-an-object"),
        ({}, "continuation-not-an-object"),
    ],
)
def test_a_continuation_that_would_REWRITE_the_question_is_refused(cont, why):
    out = mw.parse_walk_batch({"continue": cont, "query": {"pages": [_page(1, "A")]}})
    assert out["malformed"] == why and out["continue"] is None


def test_maxlag_comes_back_as_the_API_s_OWN_error_code():
    out = mw.parse_walk_batch({"error": {"code": "maxlag", "info": "Waiting for a database"}})
    assert out["error"] == "maxlag" and out["pages"] == [] and out["complete"] is False


def test_formatversion_1_s_page_MAP_is_malformed_not_silently_empty():
    out = mw.parse_walk_batch({"batchcomplete": "", "query": {"pages": {"1": _page(1, "A")}}})
    assert out["malformed"] == "pages-not-a-list"


def test_pages_the_walk_cannot_key_are_COUNTED_as_skipped_never_stored():
    out = mw.parse_walk_batch(
        {"batchcomplete": True, "query": {"pages": [
            {"ns": 0, "title": "Gone", "missing": True},
            _page(4, "Talk:X", ns=1),
            _page(5, "Alias", redirect=True),
            "not a page",
            _page(6, "Kept", pageprops={"wikibase_item": "Q42"}),
        ]}}
    )
    assert [p["page_id"] for p in out["pages"]] == [6]
    assert out["pages"][0]["qid"] == "Q42"
    assert out["skipped"] == 4


def test_the_edition_s_OWN_article_count_or_a_named_absence():
    assert mw.parse_statistics({"query": {"statistics": {"articles": 7, "pages": 30}}}) == {
        "articles": 7, "pages": 30,
    }
    assert mw.parse_statistics({"query": {"statistics": {"pages": 30}}}) == {
        "malformed": "no-article-count"
    }
    assert mw.parse_statistics({}) == {"malformed": "no-statistics"}


def test_the_budget_token_is_the_DRAIN_S_token():
    """One word for one fact: the drain's withheld text and the walk's pause say the same."""
    from src.wiki.runner import BUDGET_FULL

    assert W.PAUSED_BUDGET == BUDGET_FULL


# --------------------------------------------------------------------------- #
# The walk on the fixture edition.
# --------------------------------------------------------------------------- #
def test_the_fixture_edition_is_walked_to_the_end_with_ZERO_name_resolutions(lane, monkeypatch):
    """Q1018's bar for the walk: the socket guard installed, the kill switch clear, and a
    resolution counter on ``getaddrinfo`` -- a DNS lookup is egress too."""
    from src.ingest.airplane import install_airplane_socket_guard

    install_airplane_socket_guard()
    resolutions: list[tuple] = []
    real = socket.getaddrinfo
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: (resolutions.append(a), real(*a, **k))[1]
    )
    client = FixtureWikiClient()
    walker = _walker(client)
    report = walker.walk_for(3600)
    assert resolutions == []
    # The count first, then two batches of two over the four listed pages.
    assert client.calls == {"fetch_edition_statistics": 1, "fetch_walk_batch": 2}
    assert report.completed == [EDITION] and walker.state == W.STATE_COMPLETE
    pages = _pages()
    assert sorted(pages) == [101, 102, 104, 105], "the deleted page is not listed"
    assert all(qid is None for _t, qid, *_ in pages.values()), "no QID invented"
    cur = _cursor()
    assert cur["pages_seen"] == 4 and cur["edition_articles"] == 4
    assert cur["completed_at"] is not None and cur["continue_json"] is None
    assert cur["requests"] == 2 and cur["response_bytes"] > 0


def test_a_walked_page_NEVER_becomes_a_page_the_lane_follows(lane):
    """R40's premise: the walk ships before WARM only because it writes no entity row."""
    _walker(FixtureWikiClient()).walk_for(3600)
    with _session() as db:
        assert db.execute(select(VersionedEntity)).first() is None


def test_a_restart_RESUMES_from_the_bookmark_and_re_asks_for_nothing(lane):
    first = FixtureWikiClient()
    _walker(first).walk_for(3600, max_requests=2)  # the count, then one batch
    assert first.calls == {"fetch_edition_statistics": 1, "fetch_walk_batch": 1}
    assert json.loads(_cursor()["continue_json"])["gapcontinue"] == "Fixture Delta"

    second = FixtureWikiClient()  # a new process: a new walker, a new client
    _walker(second).walk_for(3600)
    assert second.calls == {"fetch_walk_batch": 1}, "no second count, no repeated batch"
    assert sorted(_pages()) == [101, 102, 104, 105]
    assert _cursor()["pages_seen"] == 4, "each page counted once across the restart"


def test_the_walk_counts_what_it_measured_per_TRANSPORT(lane):
    _walker(FixtureWikiClient(), transport="proxy").walk_for(3600)
    with _session() as db:
        rows = [
            (r.transport, r.pages, r.requests, r.response_bytes)
            for r in db.execute(select(WikiWalkSample)).scalars()
        ]
    assert {t for t, *_ in rows} == {"proxy"}
    assert sum(p for _t, p, _r, _b in rows) == 4 and sum(r for _t, _p, r, _b in rows) == 2
    assert sum(b for *_x, b in rows) > 0


# --------------------------------------------------------------------------- #
# The refusals: named, recorded, and never a retry storm.
# --------------------------------------------------------------------------- #
def test_a_SPENT_budget_makes_no_request_and_says_why(lane):
    client = FixtureWikiClient()
    walker = _walker(client, budget=_spent())
    report = walker.walk_for(3600)
    assert client.calls == {}
    assert report.paused == W.PAUSED_BUDGET
    assert (walker.state, walker.reason) == (W.STATE_PAUSED, "storage_budget_spent")


def test_the_switch_OFF_makes_no_request(lane):
    client = FixtureWikiClient()
    walker = _walker(client, enabled=False)
    walker.walk_for(3600)
    assert client.calls == {} and walker.state == W.STATE_OFF
    assert _cursor() is None, "not even a bookmark row"


def test_the_switch_is_OFF_by_default_R51(tmp_path, monkeypatch):
    """R51 («Switch, off»): the walk runs only where the operator turns it on.

    Two ways the default could flip without anyone choosing it: the dataclass default, and
    a settings file saved BEFORE the switch existed (every 0.4 install has one), which
    must load it as off rather than as whatever a missing key happens to coerce to.
    """
    from src.scheduler import settings as sset

    assert sset.SchedulerSettings().wiki_walk_enabled is False
    path = tmp_path / "scheduler_settings.json"
    monkeypatch.setattr(sset, "_settings_path", lambda: path)
    path.write_text(json.dumps({"wiki_lane_state": "running", "continuous": True}), "utf-8")
    assert sset.load_settings().wiki_walk_enabled is False
    assert sset.save_settings({"wiki_walk_enabled": True}).wiki_walk_enabled is True
    assert sset.load_settings().wiki_walk_enabled is True, "the operator's choice sticks"


def test_airplane_mode_PAUSES_the_walk_by_name_and_moves_no_bookmark(lane):
    """A real client over the real guarded session: the refusal is the session's own."""
    from src.wiki.client import WikiClient

    activate_kill_switch()
    try:
        walker = _walker(WikiClient(min_interval_s=0.0))
        report = walker.walk_for(3600)
    finally:
        clear_kill_switch()
    assert report.paused == W.PAUSED_NETWORK_OFF
    assert (walker.state, walker.reason) == (W.STATE_PAUSED, "network_off")
    cur = _cursor()
    assert cur["consecutive_failures"] == 0 and cur["last_error"] is None, (
        "the operator's own switch is not the edition's fault"
    )
    assert cur["requests"] == 0 and cur["edition_articles_read_at"] is None


def test_protected_mode_with_NO_proxy_WAITS_and_never_goes_direct(lane, monkeypatch):
    """Q722 = b: the walk follows the transport the operator chose, Tor included, and a
    missing proxy is a wait -- never a quiet fall back to the clear internet."""
    from src.ingest.airplane import install_airplane_socket_guard
    from src.safety.fetcher import NO_PROXY_REFUSAL, GuardedSession
    from src.wiki.client import WikiClient

    install_airplane_socket_guard()
    resolutions: list[tuple] = []
    real = socket.getaddrinfo
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: (resolutions.append(a), real(*a, **k))[1]
    )
    session = GuardedSession()
    session.transport_refusal = NO_PROXY_REFUSAL
    walker = _walker(WikiClient(session=session, min_interval_s=0.0))
    report = walker.walk_for(3600)
    assert report.paused == W.PAUSED_TRANSPORT_UNAVAILABLE
    assert walker.reason == "transport_unavailable"
    assert resolutions == [], "refused before a single name was resolved"
    assert _cursor()["requests"] == 0


class Scripted:
    """A client that answers from a list: an exception, a parsed batch, or a count."""

    def __init__(self, answers, *, counts=None):
        self.answers = list(answers)
        self.counts = counts or {"articles": 10}
        self.asked: list[tuple] = []

    def fetch_edition_statistics(self, wiki):
        self.asked.append(("count", wiki))
        return dict(self.counts)

    def fetch_walk_batch(self, wiki, *, continue_params=None, limit=50):
        self.asked.append(("batch", wiki, json.dumps(continue_params, sort_keys=True)))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return {"response_bytes": 100, **answer}


def _http(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status}", response=resp)


def _batch(pages, cont=None, complete=False, props_complete=True):
    return {"pages": pages, "continue": cont, "complete": complete,
            "props_complete": props_complete, "error": None, "malformed": None, "skipped": 0}


def _p(pid, title, qid=None):
    return {"page_id": pid, "title": title, "qid": qid, "length_bytes": 10, "last_revid": pid}


@pytest.mark.parametrize(
    "answer, token",
    [
        (_http(503), W.WAIT_SERVICE_BUSY),
        (_http(429), W.WAIT_SERVICE_BUSY),
        (_http(403), W.WAIT_REFUSED),
        (requests.ConnectionError("proxy did not answer"), W.WAIT_CONNECTION),
        (requests.Timeout("slow"), W.WAIT_CONNECTION),
        (ValueError("not JSON"), W.WAIT_MALFORMED),
        # requests' own decode error is BOTH a ValueError and an OSError: still the body's fault.
        (requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0), W.WAIT_MALFORMED),
        # ...while a ValueError that is the TRANSPORT's (a SOCKS proxy with no SOCKS support
        # installed) is not an unreadable answer: nothing was answered.
        (requests.exceptions.InvalidSchema("Missing dependencies for SOCKS support."), W.WAIT_CONNECTION),
        ({"pages": [], "error": "maxlag"}, W.WAIT_SERVICE_BUSY),
        ({"pages": [], "error": "badcontinue"}, W.WAIT_REFUSED),
        ({"pages": [], "malformed": "neither-continue-nor-batchcomplete"}, W.WAIT_MALFORMED),
    ],
)
def test_an_edition_s_refusal_is_WRITTEN_on_its_bookmark_and_the_bookmark_does_not_move(
    lane, answer, token
):
    clock = Clock()
    client = Scripted([_batch([_p(1, "A")], cont={"gapcontinue": "B"}), answer])
    walker = _walker(client, clock=clock)
    walker.walk_for(3600)
    cur = _cursor()
    assert cur["last_error"] == token and cur["consecutive_failures"] == 1
    assert json.loads(cur["continue_json"]) == {"gapcontinue": "B"}, "the bookmark held"
    assert cur["pages_seen"] == 1 and cur["requests"] == 1
    assert walker.state == W.STATE_WAITING


def test_a_refusal_is_NEVER_a_retry_storm(lane):
    """Refused, then asked again only after the doubling wait -- one minute, then two."""
    clock = Clock()
    client = Scripted([_http(503), _http(503), _batch([_p(1, "A")], complete=True)])
    walker = _walker(client, clock=clock)
    walker.walk_for(3600)
    assert [a[0] for a in client.asked] == ["count", "batch"]
    walker.walk_for(3600)
    assert len(client.asked) == 2, "nothing asked while the wait runs"
    clock.t += W.BACKOFF_FIRST_S
    walker.walk_for(3600)
    assert len(client.asked) == 3 and _cursor()["consecutive_failures"] == 2
    clock.t += W.BACKOFF_FIRST_S  # the second wait is TWO minutes
    walker.walk_for(3600)
    assert len(client.asked) == 3
    clock.t += W.BACKOFF_FIRST_S
    walker.walk_for(3600)
    assert _cursor()["completed_at"] is not None and _cursor()["consecutive_failures"] == 0
    assert W.backoff_seconds(40) == W.BACKOFF_MAX_S, "capped at an hour"


def test_an_UNKNOWN_fault_is_raised_not_dressed_up_as_a_network_refusal(lane):
    client = Scripted([KeyError("a bug")])
    with pytest.raises(KeyError):
        _walker(client).walk_for(3600)


def test_a_QID_the_API_did_not_answer_YET_is_kept_and_only_a_complete_batch_clears_it(lane):
    client = Scripted([
        _batch([_p(1, "A", "Q1")], cont={"gapcontinue": "A2", "continue": "||"}),
        _batch([_p(1, "A")], cont={"gapcontinue": "B"}, props_complete=False),
    ])
    _walker(client).walk_for(3600, max_requests=3)
    assert _pages()[1][1] == "Q1", "props still arriving: the QID is not gone"
    client.answers.append(_batch([_p(1, "A")], complete=True))
    _walker(client).walk_for(3600)
    assert _pages()[1][1] is None, "a complete batch without one clears it"
    assert _cursor()["pages_seen"] == 1, "one page, however often it was listed"


def test_a_page_DELETED_mid_walk_keeps_its_row_and_one_deleted_ahead_is_simply_not_listed(lane):
    """The brief's "a page deleted mid-walk": behind the bookmark, its row stays exactly as
    the walk saw it (the walk never learns of the deletion and never claims one); ahead of
    the bookmark, the edition just does not list it -- no gap, no refusal, no error."""
    client = Scripted([
        _batch([_p(1, "A", "Q1"), _p(2, "B")], cont={"gapcontinue": "C"}),
        # Upstream, between the two requests: "A" (walked) and "C" (not yet) are deleted.
        _batch([_p(4, "D")], complete=True),
    ])
    walker = _walker(client)
    walker.walk_for(3600)
    pages = _pages()
    assert sorted(pages) == [1, 2, 4], "the page deleted ahead of the bookmark was never listed"
    assert pages[1] == ("A", "Q1", 10, 1, 1), "the page deleted behind the bookmark kept its row as seen"
    cur = _cursor()
    assert cur["pages_seen"] == 3 and cur["completed_at"] is not None
    assert cur["consecutive_failures"] == 0 and cur["last_error"] is None, "a deletion is not a refusal"
    assert walker.state == W.STATE_COMPLETE
    assert not hasattr(WikiWalkPage, "deleted_at"), "the walk has no way to claim a deletion"


def test_editions_are_walked_ROUND_ROBIN_one_batch_each(lane):
    class Two(Scripted):
        def fetch_walk_batch(self, wiki, *, continue_params=None, limit=50):
            self.asked.append(("batch", wiki, None))
            return {"response_bytes": 1, **_batch([_p(len(self.asked), wiki)], cont={"gapcontinue": "x"})}

    client = Two([])
    _walker(client, editions=("aa", "bb")).walk_for(3600, max_requests=6)
    assert [a[1] for a in client.asked] == ["aa", "bb", "aa", "bb", "aa", "bb"]


def test_an_edition_whose_count_is_UNREADABLE_is_still_walked_of_an_unknown_total(lane):
    client = Scripted([_batch([_p(1, "A")], complete=True)], counts={"malformed": "no-statistics"})
    _walker(client).walk_for(3600)
    cur = _cursor()
    assert cur["edition_articles"] is None and cur["edition_articles_read_at"] is not None
    assert cur["completed_at"] is not None


# --------------------------------------------------------------------------- #
# The counters artifact, the runner and the schema.
# --------------------------------------------------------------------------- #
def test_the_counters_artifact_carries_the_walk_or_an_ABSENCE(lane):
    from src.wiki.counters import lane_counters

    with _session() as db:
        before = lane_counters(db)["walk"]
    assert before == {"measured": False, "reason": "walk-never-run"}, "absent, never zeros"
    _walker(FixtureWikiClient(), transport="pool").walk_for(3600)
    with _session() as db:
        after = lane_counters(db)["walk"]
    assert after["measured"] is True and after["pages_seen"] == 4
    [row] = after["editions"]
    assert (row["edition"], row["pages_seen"], row["edition_articles"]) == (EDITION, 4, 4)
    assert after["complete"] == [EDITION]
    assert after["throughput"]["by_transport"]["pool"]["pages"] == 4
    assert "can pass" in after["caveat"], "the denominator's caveat travels with it"


def test_the_runner_WALKS_in_the_idle_time_and_a_broken_walk_never_ends_the_lane(lane):
    from src.wiki.runner import WikiLaneRunner

    slept: list[float] = []

    class Broken:
        def walk_for(self, seconds, *, should_stop):
            raise RuntimeError("a walk bug")

        def status(self):
            return {"state": "walking"}

    runner = WikiLaneRunner(
        adapter=None, stream=None, lane_session=_session, state_of=lambda: "running",
        hot_sets=dict, budget=_plenty, walker=Broken(), sleep=slept.append,
        monotonic=lambda: 0.0, drain_interval_s=30.0,
    )
    runner.idle(30.0)
    assert sum(slept) == 30.0, "the interval is still slept when the walk fails"
    assert runner.last_walk == {"error": "RuntimeError"}

    walker = _walker(FixtureWikiClient())
    runner = WikiLaneRunner(
        adapter=None, stream=None, lane_session=_session, state_of=lambda: "running",
        hot_sets=dict, budget=_plenty, walker=walker, sleep=slept.append,
        monotonic=lambda: 0.0, drain_interval_s=30.0,
    )
    runner.idle(30.0)
    assert runner.last_walk["completed"] == [EDITION]
    assert runner.walk_status()["state"] == W.STATE_COMPLETE


def test_the_walk_tables_land_in_wiki_db_and_NOT_in_another_lane(tmp_path, monkeypatch):
    from sqlalchemy import inspect

    from src.versioned import store

    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        store.create_lane("wiki")
        store.create_lane("law")
        wiki = set(inspect(store.lane_engine("wiki")).get_table_names())
        law = set(inspect(store.lane_engine("law")).get_table_names())
    finally:
        store.dispose_all()
    walk = {"wiki_walk_pages", "wiki_walk_cursors", "wiki_walk_samples"}
    assert walk <= wiki and walk.isdisjoint(law)


def test_a_0_4_lane_file_GAINS_the_walk_tables_when_this_build_opens_it(tmp_path, monkeypatch):
    """A wiki.db an earlier build wrote has no walk tables; ``create_lane`` adds them and
    keeps every row it had."""
    from sqlalchemy import inspect, text

    from src.versioned import store

    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        store.create_lane("wiki")
        eng = store.lane_engine("wiki")
        with eng.begin() as conn:
            for name in ("wiki_walk_pages", "wiki_walk_cursors", "wiki_walk_samples"):
                conn.execute(text(f'DROP TABLE "{name}"'))
        assert "wiki_walk_cursors" not in inspect(eng).get_table_names()
        store.create_lane("wiki")
        assert "wiki_walk_cursors" in inspect(store.lane_engine("wiki")).get_table_names()
    finally:
        store.dispose_all()


def test_the_page_table_is_WITHOUT_ROWID_so_the_key_is_not_stored_twice():
    assert WikiWalkPage.__table__.dialect_options["sqlite"]["with_rowid"] is False


# --------------------------------------------------------------------------- #
# The task manager's row, and the walk's words in all twelve languages.
# --------------------------------------------------------------------------- #
_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12
    return out


def _js_table(name: str) -> dict[str, str]:
    """A ``const NAME = {...}`` string table from app-living.js, brace-matched by the shared
    helper rather than sliced by hand (``tests/test_source_slicing_discipline.py``)."""
    from tests.js_source_helper import object_literal, read_static

    body = object_literal(read_static("app-living.js"), name)
    return dict(re.findall(r'(\w+):\s*"([^"]*)"', body))


def test_the_task_manager_shows_the_walk_only_while_it_walks_pauses_or_waits(lane, monkeypatch):
    import src.api.jobs as jobs
    import src.wiki.service as service

    monkeypatch.setattr(service, "lane_service_status", lambda: None)
    assert jobs._wiki_walk_jobs() == [], "no lane running here: no row"
    for state in ("off", "complete", "not_started"):
        monkeypatch.setattr(service, "lane_service_status", lambda s=state: {"walk": {"state": s}})
        assert jobs._wiki_walk_jobs() == [], state

    monkeypatch.setattr(
        service, "lane_service_status", lambda: {"walk": {"state": "paused", "reason": "network_off"}}
    )
    [row] = jobs._wiki_walk_jobs()
    assert (row["id"], row["kind"], row["state"]) == ("wiki-walk", "wiki-walk", "paused")
    assert row["progress"] is None and row["eta_seconds"] is None and row["actions"] == [], (
        "no bar against a total the walk can pass, no ETA, and nothing to click: the switch "
        "is in Settings"
    )
    assert row["label"] == "Wikipedia page walk", "a walk that never ran has no count to show"
    assert (row["detail"], row["detail_i18n"]) == ("Airplane mode is on.", "Airplane mode is on.")

    _walker(FixtureWikiClient()).walk_for(3600)
    monkeypatch.setattr(service, "lane_service_status", lambda: {"walk": {"state": "walking"}})
    [row] = jobs._wiki_walk_jobs()
    assert row["state"] == "running" and "detail" not in row
    assert row["label"] == "Wikipedia page walk — 4 pages seen"
    assert row["label_i18n"] == "Wikipedia page walk — {pages}"
    assert row["label_vars"] == {"pages": {"i18n": "{n} pages seen", "vars": {"n": 4}}}

    monkeypatch.setattr(service, "lane_service_status", lambda: {"walk": {"state": "waiting"}})
    [row] = jobs._wiki_walk_jobs()
    assert row["detail_i18n"] == jobs._WALK_ALL_WAITING


def test_the_walk_row_is_listed_and_is_not_a_database_writer():
    import src.api.jobs as jobs

    assert "wiki-walk" not in jobs._DB_WRITER_KINDS, (
        "the walk writes the lane's own file, never corpus.db: it takes no part in the "
        "single-writer ask"
    )
    assert "_wiki_walk_jobs()" in (_ROOT / "src" / "api" / "jobs.py").read_text(encoding="utf-8")


def test_one_cause_has_one_wording_in_the_task_manager_and_in_living_sources():
    import src.api.jobs as jobs

    living = _js_table("_LIVING_WALK_WHY")
    for token, line in jobs._WALK_WHY.items():
        assert living.get(token) == line, (token, line, living.get(token))
    assert set(living) == set(W.GLOBAL_PAUSES) | set(W.EDITION_WAITS), (
        "every token the walker can publish has a sentence, and no sentence names a token it cannot"
    )
    assert set(_js_table("_LIVING_WALK_STATE")) == set(W.WALK_STATES) | {"not_running"}


def _walk_keys() -> list[str]:
    import src.api.jobs as jobs

    keys = [
        "Wikipedia page walk", "Wikipedia page walk — {pages}", "{n} page seen", "{n} pages seen",
        jobs._WALK_ALL_WAITING, *jobs._WALK_WHY.values(),
    ]
    # Table-driven words: t(TABLE[token]) is invisible to the literal t("...") gate.
    for name in ("_LIVING_WALK_STATE", "_LIVING_WALK_WHY", "_LIVING_TRANSPORT"):
        keys += list(_js_table(name).values())
    return sorted(set(keys))


@pytest.mark.parametrize("key", _walk_keys())
def test_the_walk_s_table_driven_and_server_side_words_are_keyed_x12(key):
    want = sorted(re.findall(r"\{(\w+)\}", key))
    for code, d in _locales().items():
        assert key in d and d[key].strip(), f"{code}.json has no value for {key!r}"
        assert sorted(re.findall(r"\{(\w+)\}", d[key])) == want, f"{code}: {d[key]!r}"


def test_russian_and_arabic_count_frames_are_labels():
    """A two-form pair cannot carry Russian's or Arabic's plural forms, so the MANY frame is
    a label and a count (the house form: "страниц: {n}"), grammatical for every number."""
    loc = _locales()
    for code in ("ru", "ar"):
        for key in ("{n} pages seen", "{n} pages an hour"):
            assert re.search(r":\s*\{n\}", loc[code][key]), f"{code}: {key!r} = {loc[code][key]!r}"
