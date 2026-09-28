"""Q707's WARM tier (S05-06's S1): driven on the fixture, mostly at its edges.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WARM is "every other changed page (full text, indexed lazily under the daily budget)"
(Q707 = a), holding "latest + previous" (Q710 🔒 = a). The spine of this file is what it
must never do, whatever the network or the stream says: keep a third text, fetch a page
that became HOT, take the budget share HOT is left, drop a deleted page's text (Q713), ask
the same unreadable page in every window, storm a refusing edition with retries, go direct
when the chosen transport is refused (Q722 = b), or turn a changed page into a page the
lane follows.
"""

from __future__ import annotations

import json
import re
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests
from sqlalchemy import select, text

from src.ingest import activate_kill_switch, clear_kill_switch
from src.testing.wiki_fixture import FixtureWikiClient
from src.versioned.models import VersionedChange, VersionedEntity
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import mediawiki as mw
from src.wiki import walk as W
from src.wiki import warm as M
from src.wiki.lane_models import WikiWarmEdition, WikiWarmPage, WikiWarmScan
from src.wiki.tiers import budget_state

EDITION = "oo"
T0 = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)


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


def _at_share():
    total = 20 * 1024**3
    return budget_state(total_gb=20, disk_bytes=int(total * M.WARM_BUDGET_SHARE), editions=1)


def _spent():
    return budget_state(total_gb=1, disk_bytes=2 * 1024**3, editions=1)


class Clock:
    """A monotonic clock a test moves by hand."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Now:
    """The wall clock a test moves by hand."""

    def __init__(self, at: datetime = T0) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def _fetcher(client, *, editions=(EDITION,), batch=50, budget=None, clock=None, now=None,
             scan_limit=M.SCAN_LIMIT, enabled=True):
    return M.WarmFetcher(
        client=client,
        editions=editions,
        lane_session=_session,
        budget=budget or _plenty,
        enabled=enabled if callable(enabled) else (lambda: enabled),
        batch=batch,
        scan_limit=scan_limit,
        monotonic=clock or Clock(),
        now=now or Now(),
    )


_REFS = iter(range(1, 1_000_000))


def _change(page_id, revid=None, kind="edit", *, at=T0, edition=EDITION, entity_id=None,
            external_id=None):
    """One row as the drain writes it: the page id form, and ``{wiki}:r{revid}`` when the
    change carries a revision (a log event gets another ref, which is never a revision)."""
    ref = f"{edition}:r{revid}" if revid else f"{edition}:log{next(_REFS)}"
    with _session() as db:
        db.add(
            VersionedChange(
                entity_id=entity_id,
                external_id=external_id if external_id is not None else f"{edition}:p{page_id}",
                change_ref=ref,
                feed="stream",
                change_kind=kind,
                recorded_at=at,
            )
        )


def _follow(page_id, edition=EDITION):
    """Make the page HOT the way the drain does: an entity row for it."""
    with _session() as db:
        entity = VersionedEntity(external_id=f"{edition}:p{page_id}", title=f"P{page_id}")
        db.add(entity)
        db.flush()
        return entity.id


def _rows(edition=EDITION):
    with _session() as db:
        return {
            r.page_id: {c.name: getattr(r, c.name) for c in r.__table__.columns}
            for r in db.execute(select(WikiWarmPage).where(WikiWarmPage.edition == edition)).scalars()
        }


def _counts(edition=EDITION):
    with _session() as db:
        row = db.get(WikiWarmEdition, edition)
        return None if row is None else {c.name: getattr(row, c.name) for c in row.__table__.columns}


# --------------------------------------------------------------------------- #
# The request, the parser and the pause: pure, no lane.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ref, revid",
    [
        ("oo:r1011", 1011),
        ("en:r7", 7),
        ("oo:r0", None),          # the drain's own measured trap: 0 is not a revision
        ("oo:log12", None),       # a log event's ref
        ("oo:r12x", None),
        ("r12", None),            # no edition
        ("", None),
        (None, None),
    ],
)
def test_only_the_lane_s_OWN_revision_refs_name_a_revision(ref, revid):
    assert M.revid_of(ref) == revid


def test_WARM_asks_for_the_NEWEST_text_of_up_to_50_pages_BY_ID():
    params = mw.build_warm_texts_params([101, 102])
    assert params["pageids"] == "101|102", "by id: a title may have moved since the change"
    assert params["prop"] == "revisions|info" and params["rvslots"] == "main"
    assert params["rvprop"] == "ids|timestamp|content"
    assert "rvlimit" not in params, "without rvlimit, several pages answer each one's newest"
    assert params["formatversion"] == 2


@pytest.mark.parametrize("ids", [[], list(range(1, 52))])
def test_a_WARM_batch_of_none_or_over_50_is_REFUSED_never_clamped(ids):
    with pytest.raises(ValueError):
        mw.build_warm_texts_params(ids)


def _rev(revid, content="x", **slot):
    return {"revid": revid, "timestamp": "2026-03-10T12:00:00Z",
            "slots": {"main": {"content": content, **slot}}}


def test_the_parser_SETTLES_each_page_under_what_the_wiki_said():
    out = mw.parse_warm_texts(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {"pageid": 1, "ns": 0, "title": "A", "revisions": [_rev(11, "alpha")]},
                    {"pageid": 2, "missing": True},
                    {"pageid": 3, "ns": 4, "title": "Project:C", "revisions": [_rev(13)]},
                    {"pageid": 4, "ns": 0, "title": "D", "redirect": True, "revisions": [_rev(14)]},
                    {"pageid": 5, "ns": 0, "title": "E",
                     "revisions": [{"revid": 15, "slots": {"main": {"texthidden": True}}}]},
                    {"pageid": 6, "ns": 0, "title": "F", "revisions": [{"revid": 16, "texthidden": True}]},
                    {"title": "no id at all", "invalid": True},
                ]
            },
        }
    )
    pages = out["pages"]
    assert pages[1] == {"title": "A", "revid": 11, "timestamp": datetime(2026, 3, 10, 12, 0, tzinfo=UTC),
                        "text": "alpha"}
    assert pages[2] == {"missing": True}
    assert pages[3] == {"not_an_article": True, "title": "Project:C"}
    assert pages[4] == {"not_an_article": True, "title": "D"}, "a redirect is outside Q703's scope"
    assert pages[5] == pages[6] | {"title": "E", "revid": 15}
    assert pages[6] == {"text_hidden": True, "title": "F", "revid": 16}
    assert set(pages) == {1, 2, 3, 4, 5, 6}, "a page with no id has nothing to be keyed on"
    assert out["partial"] is False and out["error"] is None and out["malformed"] is None


def test_a_page_the_answer_left_BARE_is_not_settled_and_the_answer_says_it_is_partial():
    out = mw.parse_warm_texts(
        {
            "continue": {"rvcontinue": "12|123", "continue": "||"},
            "query": {"pages": [{"pageid": 1, "ns": 0, "title": "A", "revisions": [_rev(11)]},
                                {"pageid": 2, "ns": 0, "title": "B"}]},
        }
    )
    assert set(out["pages"]) == {1} and out["partial"] is True


def test_a_text_the_wiki_could_not_load_is_left_out_never_stored_as_empty():
    out = mw.parse_warm_texts(
        {"batchcomplete": True,
         "query": {"pages": [{"pageid": 1, "ns": 0, "title": "A",
                              "revisions": [{"revid": 11, "slots": {"main": {"textmissing": True}}}]}]}}
    )
    assert out["pages"] == {} and out["partial"] is False


@pytest.mark.parametrize(
    "payload, field, value",
    [
        ({"query": {"pages": []}}, "malformed", "neither-continue-nor-batchcomplete"),
        ({"batchcomplete": True, "query": {"pages": {"1": {"pageid": 1}}}}, "malformed", "pages-not-a-list"),
        ({"error": {"code": "maxlag", "info": "Waiting for a replica"}}, "error", "maxlag"),
        ("<html>", "malformed", "not-an-object"),
    ],
)
def test_an_answer_this_cannot_use_is_NAMED_never_read_as_empty(payload, field, value):
    out = mw.parse_warm_texts(payload)
    assert out[field] == value and out["pages"] == {}


def test_the_budget_pause_leaves_HOT_its_share_and_measures_before_it_refuses():
    assert M.budget_pause(_plenty()) is None
    assert M.budget_pause(_at_share()) == M.PAUSED_WARM_SHARE
    assert M.budget_pause(_spent()) == W.PAUSED_BUDGET
    unmeasured = budget_state(total_gb=20, disk_bytes=None, editions=1)
    assert M.budget_pause(unmeasured) is None, "nothing measured is not a spent budget"
    just_under = budget_state(total_gb=20, disk_bytes=int(20 * 1024**3 * M.WARM_BUDGET_SHARE) - 1,
                              editions=1)
    assert M.budget_pause(just_under) is None


def test_the_budget_token_is_the_DRAIN_S_token():
    """One word for one fact: the drain's withheld text and WARM's pause say the same."""
    from src.wiki.runner import BUDGET_FULL

    assert W.PAUSED_BUDGET == BUDGET_FULL and W.PAUSED_BUDGET in M.WARM_PAUSES
    assert M.PAUSED_WARM_SHARE in M.WARM_PAUSES and M.PAUSED_WARM_SHARE != W.PAUSED_BUDGET


@pytest.mark.parametrize(
    "kwargs, error",
    [({"editions": "oo"}, TypeError), ({"batch": 0}, ValueError), ({"batch": 51}, ValueError),
     ({"scan_limit": 0}, ValueError)],
)
def test_a_fetcher_built_WRONG_is_refused(kwargs, error):
    base = {"client": None, "editions": (EDITION,), "lane_session": _session, "budget": _plenty,
            "enabled": lambda: True}
    with pytest.raises(error):
        M.WarmFetcher(**{**base, **kwargs})


# --------------------------------------------------------------------------- #
# The switch: off means nothing at all, and off is the default.
# --------------------------------------------------------------------------- #
def test_the_switch_OFF_makes_no_request_and_writes_no_row_not_even_a_bookmark(lane):
    _change(101, 1011)
    client = FixtureWikiClient()
    fetcher = _fetcher(client, enabled=False)
    report = fetcher.warm_for(3600)
    assert client.calls == {} and (fetcher.state, fetcher.reason) == (M.STATE_OFF, None)
    assert (report.scanned, report.queued, report.requests) == (0, 0, 0)
    assert _rows() == {}, "off queued a page"
    with _session() as db:
        assert db.execute(select(WikiWarmScan)).first() is None, "off moved the bookmark"


def test_turning_the_switch_ON_later_reads_the_log_from_where_it_WAITED(lane):
    _change(101, 1011)
    on = {"v": False}
    client = FixtureWikiClient()
    fetcher = _fetcher(client, enabled=lambda: on["v"])
    fetcher.warm_for(3600)
    _change(102, 1007)
    on["v"] = True
    fetcher.warm_for(3600)
    assert {101, 102} <= set(_rows()), "a change recorded while WARM was off was skipped"
    assert fetcher.state != M.STATE_OFF


def test_a_switch_that_cannot_be_READ_is_an_off_switch(lane):
    def broken():
        raise OSError("settings file unreadable")

    _change(101, 1011)
    client = FixtureWikiClient()
    fetcher = _fetcher(client, enabled=broken)
    fetcher.warm_for(3600)
    assert client.calls == {} and fetcher.state == M.STATE_OFF


def test_the_switch_is_OFF_by_default_and_a_0_4_settings_file_loads_it_off(tmp_path, monkeypatch):
    """The walk's two ways a default flips without anyone choosing it (``R51``): the
    dataclass default, and a settings file saved BEFORE the switch existed."""
    from src.scheduler import settings as sset

    assert sset.SchedulerSettings().wiki_warm_enabled is False
    path = tmp_path / "scheduler_settings.json"
    monkeypatch.setattr(sset, "_settings_path", lambda: path)
    path.write_text(json.dumps({"wiki_lane_state": "running", "continuous": True}), "utf-8")
    assert sset.load_settings().wiki_warm_enabled is False
    assert sset.save_settings({"wiki_warm_enabled": True}).wiki_warm_enabled is True
    assert sset.load_settings().wiki_warm_enabled is True, "the operator's choice sticks"
    assert sset.load_settings().wiki_walk_enabled is False, "WARM's switch moved the walk's"


def test_the_config_API_declares_the_switch_or_the_save_never_reaches_the_settings():
    """The recorded settingUnreachable trap: ``model_dump(exclude_unset=True)`` drops an
    undeclared field, so a box that PUTs it would be saved by nobody."""
    from src.api.scheduler import SchedulerConfigUpdate

    assert SchedulerConfigUpdate(wiki_warm_enabled=True).model_dump(exclude_unset=True) == {
        "wiki_warm_enabled": True
    }


# --------------------------------------------------------------------------- #
# The queue: the lane's own change log, read forward from a bookmark.
# --------------------------------------------------------------------------- #
def test_the_queue_is_the_lane_s_OWN_change_log_minus_HOT_legacy_ids_and_other_editions(lane):
    hot = _follow(104)
    _change(101, 1011)
    _change(102, 1007)
    _change(104, 1009, entity_id=hot)                 # HOT's: the drain linked it
    _change(0, 55, external_id="oo:Fixture Epsilon")   # a legacy title-form id
    _change(5, 66, edition="xx")                        # an edition this lane does not run
    _change(0, 77, external_id="")                      # an event with nothing to point at
    scanned = _fetcher(FixtureWikiClient()).scan()
    assert scanned == {"scanned": 6, "queued": 2, "deleted": 0}
    rows = _rows()
    assert sorted(rows) == [101, 102]
    assert rows[101]["wanted_revid"] == 1011 and rows[101]["due_since"] is not None
    assert rows[101]["latest_text"] is None and rows[101]["title"] is None, "no title guessed"
    with _session() as db:
        assert db.get(WikiWarmScan, "changes").last_change_id == db.execute(
            select(VersionedChange.id).order_by(VersionedChange.id.desc())
        ).scalars().first()


def test_the_bookmark_means_a_second_scan_reads_ONLY_what_came_after_it(lane):
    fetcher = _fetcher(FixtureWikiClient())
    _change(101, 1011)
    assert fetcher.scan()["scanned"] == 1
    assert fetcher.scan() == {"scanned": 0, "queued": 0, "deleted": 0}
    _change(102, 1007)
    assert fetcher.scan() == {"scanned": 1, "queued": 1, "deleted": 0}


def test_one_scan_reads_at_most_its_LIMIT_and_the_rest_waits_for_the_next(lane):
    for pid, rev in ((101, 1011), (102, 1007), (105, 901)):
        _change(pid, rev)
    fetcher = _fetcher(FixtureWikiClient(), scan_limit=2)
    assert fetcher.scan()["scanned"] == 2
    assert sorted(_rows()) == [101, 102]
    assert fetcher.scan()["scanned"] == 1 and sorted(_rows()) == [101, 102, 105]


def test_ten_edits_while_a_page_waited_cost_ONE_fetch_of_where_the_page_is_now(lane):
    for rev in (1001, 1005, 1011):
        _change(101, rev)
    client = FixtureWikiClient()
    report = _fetcher(client).warm_for(3600)
    assert client.calls == {"fetch_warm_texts": 1}
    assert report.texts == 1 and _rows()[101]["latest_revid"] == 1011


def test_WARM_asks_for_the_pages_that_WAITED_LONGEST_first(lane):
    _change(105, 901, at=T0 + timedelta(minutes=2))
    _change(101, 1011, at=T0)
    _change(102, 1007, at=T0 + timedelta(minutes=1))

    class Recording(FixtureWikiClient):
        asked: list[list[int]] = []

        def fetch_warm_texts(self, wiki, pageids):
            Recording.asked.append(list(pageids))
            return super().fetch_warm_texts(wiki, pageids)

    _fetcher(Recording(), batch=2).warm_for(3600, max_requests=1)
    assert Recording.asked == [[101, 102]], "oldest first, and never more than the batch"


# --------------------------------------------------------------------------- #
# Fetching, on the fixture edition.
# --------------------------------------------------------------------------- #
def test_the_fixture_edition_is_warmed_with_ZERO_name_resolutions(lane, monkeypatch):
    """Q1018's bar: the socket guard installed, the kill switch clear, and a resolution
    counter on ``getaddrinfo`` -- a DNS lookup is egress too."""
    from src.ingest.airplane import install_airplane_socket_guard

    install_airplane_socket_guard()
    resolutions: list[tuple] = []
    real = socket.getaddrinfo
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: (resolutions.append(a), real(*a, **k))[1]
    )
    for pid, rev in ((101, 1011), (102, 1007), (103, 1008), (104, 1009), (105, 901)):
        _change(pid, rev)
    client = FixtureWikiClient()
    fetcher = _fetcher(client)
    report = fetcher.warm_for(3600)
    assert resolutions == []
    assert client.calls == {"fetch_warm_texts": 1}, "five pages, one request"
    assert (report.texts, report.deleted, report.requests) == (4, 1, 1)
    assert fetcher.state == M.STATE_CAUGHT_UP
    rows = _rows()
    assert rows[104]["title"] == "Fixture Delta" and rows[104]["latest_bytes"] > 30_000
    assert rows[103]["deleted_at"] is not None and rows[103]["latest_text"] is None
    assert all(r["due_since"] is None for r in rows.values())
    counts = _counts()
    assert (counts["pages_with_text"], counts["texts_fetched"], counts["requests"]) == (4, 4, 1)
    assert counts["response_bytes"] == report.response_bytes > 0


def test_WARM_NEVER_makes_a_changed_page_a_page_the_lane_follows(lane):
    for pid, rev in ((101, 1011), (102, 1007)):
        _change(pid, rev)
    _fetcher(FixtureWikiClient()).warm_for(3600)
    with _session() as db:
        assert db.execute(select(VersionedEntity)).first() is None


def test_the_texts_are_stored_COMPRESSED_and_read_back_VERBATIM(lane):
    _change(104, 1009)
    _fetcher(FixtureWikiClient()).warm_for(3600)
    with _session() as db:
        raw = db.execute(text("SELECT latest_text FROM wiki_warm_pages WHERE page_id = 104")).scalar_one()
    stored = _rows()[104]
    assert isinstance(raw, bytes) and len(raw) < stored["latest_bytes"], "compressed on disk"
    assert len(stored["latest_text"].encode("utf-8")) == stored["latest_bytes"]


class Scripted:
    """A client that answers WARM from a list: an exception, or a parsed answer."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked: list[tuple] = []

    def fetch_warm_texts(self, wiki, pageids):
        self.asked.append((wiki, list(pageids)))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return {"pages": {}, "partial": False, "error": None, "malformed": None,
                "response_bytes": 100, **answer}


def _text(revid, body=None, title="A"):
    return {"title": title, "revid": revid, "timestamp": T0, "text": body or f"text of r{revid}"}


def _http(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status}", response=resp)


def test_Q710_a_THIRD_text_keeps_latest_and_previous_and_the_oldest_goes(lane):
    client = Scripted([{"pages": {1: _text(11)}}, {"pages": {1: _text(12)}}, {"pages": {1: _text(13)}}])
    fetcher = _fetcher(client)
    for rev in (11, 12, 13):
        _change(1, rev)
        fetcher.warm_for(3600)
    row = _rows()[1]
    assert (row["latest_revid"], row["latest_text"]) == (13, "text of r13")
    assert (row["previous_revid"], row["previous_text"]) == (12, "text of r12")
    assert row["previous_bytes"] == len("text of r12")
    counts = _counts()
    assert counts["texts_fetched"] == 3 and counts["pages_with_text"] == 1, "one page, three texts"


def test_an_answer_OLDER_than_the_text_held_changes_nothing(lane):
    client = Scripted([{"pages": {1: _text(12)}}, {"pages": {1: _text(11)}}])
    fetcher = _fetcher(client, now=Now(T0 + timedelta(hours=1)))
    _change(1, 12)
    fetcher.warm_for(3600)
    _change(1, 13)
    fetcher.warm_for(3600)
    row = _rows()[1]
    assert (row["latest_revid"], row["previous_revid"]) == (12, None), "never overwritten backwards"
    assert _counts()["texts_fetched"] == 1


def test_a_page_that_became_HOT_is_not_asked_again_and_KEEPS_its_earlier_texts(lane):
    client = Scripted([{"pages": {1: _text(11), 2: _text(21, title="B")}}, {"pages": {2: _text(22, title="B")}}])
    fetcher = _fetcher(client)
    _change(1, 11)
    _change(2, 21)
    fetcher.warm_for(3600)
    assert _counts()["pages_with_text"] == 2
    _follow(1)                          # the operator's corpus now mentions page 1
    _change(1, 12)
    _change(2, 22)
    report = fetcher.warm_for(3600)
    assert client.asked[-1] == (EDITION, [2]), "page 1 is HOT's now and is not asked for"
    assert report.promoted == 1
    row = _rows()[1]
    assert row["promoted_at"] is not None and row["due_since"] is None
    assert row["latest_text"] == "text of r11", (
        "the text from before the page was followed is its only local copy, and stays"
    )
    counts = _counts()
    assert (counts["promoted"], counts["pages_with_text"]) == (1, 2)
    _change(1, 13)                      # a later change the drain did not link yet
    fetcher.warm_for(3600)
    assert _counts()["promoted"] == 1 and _rows()[1]["due_since"] is None, "promoted once, never re-queued"


def test_a_page_whose_ONLY_due_pages_turned_HOT_makes_no_request_at_all(lane):
    client = Scripted([])
    _change(1, 11)
    fetcher = _fetcher(client)
    fetcher.scan()
    _follow(1)
    report = fetcher.warm_for(3600)
    assert client.asked == [] and report.promoted == 1
    assert _rows()[1]["promoted_at"] is not None and _rows()[1]["latest_text"] is None


def test_a_DELETION_stops_the_asking_and_KEEPS_the_text_Q713(lane):
    client = Scripted([{"pages": {1: _text(11)}}])
    fetcher = _fetcher(client)
    _change(1, 11)
    fetcher.warm_for(3600)
    _change(1, None, kind="delete")
    report = fetcher.warm_for(3600)
    assert report.deleted == 1 and len(client.asked) == 1, "nothing asked for a deleted page"
    row = _rows()[1]
    assert row["deleted_at"] is not None and row["due_since"] is None
    assert row["latest_text"] == "text of r11", "a deleted page keeps its last text"
    assert _counts()["pages_with_text"] == 1


def test_a_page_the_WIKI_says_is_missing_is_marked_deleted_and_keeps_its_text(lane):
    client = Scripted([{"pages": {1: _text(11)}}, {"pages": {1: {"missing": True}}}])
    fetcher = _fetcher(client)
    _change(1, 11)
    fetcher.warm_for(3600)
    _change(1, 12)
    fetcher.warm_for(3600)
    row = _rows()[1]
    assert row["deleted_at"] is not None and row["latest_text"] == "text of r11"


def test_a_page_RE_CREATED_after_its_deletion_is_asked_for_again(lane):
    client = Scripted([{"pages": {1: _text(11)}}, {"pages": {1: _text(30)}}])
    fetcher = _fetcher(client)
    _change(1, 11)
    fetcher.warm_for(3600)
    _change(1, None, kind="delete")
    _change(1, 30, kind="create")
    fetcher.warm_for(3600)
    row = _rows()[1]
    assert row["deleted_at"] is None and row["latest_revid"] == 30
    assert row["previous_revid"] == 11, "the text from before the deletion is the previous one"


@pytest.mark.parametrize(
    "answer, reason",
    [({"not_an_article": True, "title": "Project:A"}, M.NO_TEXT_NOT_AN_ARTICLE),
     ({"text_hidden": True, "title": "A", "revid": 11}, M.NO_TEXT_HIDDEN)],
)
def test_a_page_with_NO_text_to_give_is_recorded_under_why_never_counted_as_a_text(lane, answer, reason):
    client = Scripted([{"pages": {1: answer}}])
    fetcher = _fetcher(client)
    _change(1, 11)
    report = fetcher.warm_for(3600)
    assert report.no_text == {reason: 1} and report.texts == 0
    row = _rows()[1]
    assert row["no_text_reason"] == reason and row["due_since"] is None and row["latest_text"] is None
    assert _counts()["pages_with_text"] == 0 and _counts()["texts_fetched"] == 0


def test_an_UNREADABLE_page_in_a_complete_answer_is_recorded_and_not_asked_again_until_it_changes(lane):
    """Otherwise it would sit at the head of the queue and be asked in every window, forever."""
    client = Scripted([{"pages": {}}, {"pages": {1: _text(12)}}])
    fetcher = _fetcher(client)
    _change(1, 11)
    report = fetcher.warm_for(3600)
    assert report.no_text == {M.NO_TEXT_UNREADABLE: 1}
    assert _rows()[1]["no_text_reason"] == M.NO_TEXT_UNREADABLE and _rows()[1]["due_since"] is None
    fetcher.warm_for(3600)
    assert len(client.asked) == 1 and fetcher.state == M.STATE_CAUGHT_UP
    _change(1, 12)
    fetcher.warm_for(3600)
    assert len(client.asked) == 2 and _rows()[1]["no_text_reason"] is None
    assert _rows()[1]["latest_revid"] == 12


def test_a_PARTIAL_answer_keeps_the_pages_it_did_not_reach_at_the_HEAD_of_the_queue(lane):
    client = Scripted([{"pages": {1: _text(11)}, "partial": True}, {"pages": {2: _text(21, title="B")}}])
    fetcher = _fetcher(client)
    _change(1, 11)
    _change(2, 21)
    first = fetcher.warm_for(3600, max_requests=1)
    assert first.unanswered == 1 and first.texts == 1
    due = _rows()[2]["due_since"]
    assert due is not None and due.replace(tzinfo=UTC) == T0, "its place kept, not sent to the back"
    fetcher.warm_for(3600)
    assert client.asked[1] == (EDITION, [2]) and _rows()[2]["latest_revid"] == 21


def test_a_partial_answer_that_settled_NOTHING_is_a_named_WAIT_not_a_loop(lane):
    clock = Clock()
    client = Scripted([{"pages": {}, "partial": True}])
    fetcher = _fetcher(client, clock=clock)
    _change(1, 11)
    fetcher.warm_for(3600)
    assert fetcher.last_refusal == {EDITION: W.WAIT_MALFORMED}
    assert fetcher.state == M.STATE_WAITING and len(client.asked) == 1
    fetcher.warm_for(3600)
    assert len(client.asked) == 1, "nothing asked while the wait runs"


def test_an_OLDER_answer_inside_the_lag_grace_goes_to_the_BACK_and_past_it_is_accepted(lane):
    """A replica behind the stream answers an older revision: asked again later. Past the
    grace, the revision the stream named is taken to be gone (a revision deletion)."""
    now = Now(T0 + timedelta(minutes=1))
    client = Scripted([{"pages": {1: _text(1005)}}, {"pages": {1: _text(1005)}}])
    fetcher = _fetcher(client, now=now)
    _change(1, 1011, at=T0)
    fetcher.warm_for(3600)
    row = _rows()[1]
    assert row["latest_revid"] == 1005, "the older text is still the newest this machine has"
    assert row["due_since"].replace(tzinfo=UTC) == now.at, "to the back of the queue"
    assert len(client.asked) == 1, "asked once in the window, never in a loop inside it"
    assert fetcher.state == M.STATE_FETCHING, "not caught up while a page still waits"
    now.at = T0 + M.LAG_GRACE + timedelta(minutes=1)
    fetcher.warm_for(3600)
    assert _rows()[1]["due_since"] is None and len(client.asked) == 2


# --------------------------------------------------------------------------- #
# Stops: the budget, the operator's switches, and the source's refusals.
# --------------------------------------------------------------------------- #
def test_WARM_takes_the_budget_up_to_its_SHARE_then_stops_and_SAYS_so(lane):
    """S1's acceptance: WARM ingests up to the budget and stops, saying so -- here at its
    share, which leaves the rest of the budget to HOT."""
    budget = {"now": _plenty()}
    client = FixtureWikiClient()
    fetcher = _fetcher(client, budget=lambda: budget["now"])
    _change(101, 1011)
    assert fetcher.warm_for(3600).texts == 1
    budget["now"] = _at_share()
    _change(102, 1007)
    report = fetcher.warm_for(3600)
    assert report.paused == M.PAUSED_WARM_SHARE and report.requests == 0
    assert (fetcher.state, fetcher.reason) == (M.STATE_PAUSED, M.PAUSED_WARM_SHARE)
    assert client.calls == {"fetch_warm_texts": 1}
    assert _rows().get(102) is None, "not even queued: the scan waits with the fetch"
    budget["now"] = _plenty()                  # the operator raised the budget
    fetcher.warm_for(3600)
    assert _rows()[102]["latest_revid"] == 1007


def test_a_SPENT_budget_pauses_WARM_under_the_drain_s_own_word(lane):
    client = Scripted([])
    fetcher = _fetcher(client, budget=_spent)
    _change(1, 11)
    report = fetcher.warm_for(3600)
    assert report.paused == W.PAUSED_BUDGET and client.asked == []
    assert (fetcher.state, fetcher.reason) == (M.STATE_PAUSED, "storage_budget_spent")


def test_airplane_mode_PAUSES_WARM_by_name_and_holds_no_edition_to_blame(lane):
    """A real client over the real guarded session: the refusal is the session's own."""
    from src.wiki.client import WikiClient

    _change(101, 1011)
    activate_kill_switch()
    try:
        fetcher = _fetcher(WikiClient(min_interval_s=0.0))
        report = fetcher.warm_for(3600)
    finally:
        clear_kill_switch()
    assert report.paused == W.PAUSED_NETWORK_OFF
    assert (fetcher.state, fetcher.reason) == (M.STATE_PAUSED, "network_off")
    assert fetcher.status()["waiting"] == {}, "the operator's own switch is not the edition's fault"
    assert _rows()[101]["due_since"] is not None, "still waiting for its text"
    assert _counts() is None, "no request answered, so nothing counted"


def test_protected_mode_with_NO_proxy_WAITS_and_never_goes_direct(lane, monkeypatch):
    """Q722 = b: WARM follows the transport the operator chose, Tor included, and a missing
    proxy is a wait -- never a quiet fall back to the clear internet."""
    from src.ingest.airplane import install_airplane_socket_guard
    from src.safety.fetcher import NO_PROXY_REFUSAL, GuardedSession
    from src.wiki.client import WikiClient

    install_airplane_socket_guard()
    resolutions: list[tuple] = []
    real = socket.getaddrinfo
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: (resolutions.append(a), real(*a, **k))[1]
    )
    _change(101, 1011)
    session = GuardedSession()
    session.transport_refusal = NO_PROXY_REFUSAL
    fetcher = _fetcher(WikiClient(session=session, min_interval_s=0.0))
    report = fetcher.warm_for(3600)
    assert report.paused == W.PAUSED_TRANSPORT_UNAVAILABLE
    assert fetcher.reason == "transport_unavailable"
    assert resolutions == [], "refused before a single name was resolved"


@pytest.mark.parametrize(
    "answer, token",
    [
        (_http(503), W.WAIT_SERVICE_BUSY),
        (_http(429), W.WAIT_SERVICE_BUSY),
        (_http(403), W.WAIT_REFUSED),
        (requests.ConnectionError("proxy did not answer"), W.WAIT_CONNECTION),
        (requests.Timeout("slow"), W.WAIT_CONNECTION),
        (ValueError("not JSON"), W.WAIT_MALFORMED),
        ({"error": "maxlag"}, W.WAIT_SERVICE_BUSY),
        ({"error": "badvalue"}, W.WAIT_REFUSED),
        ({"malformed": "neither-continue-nor-batchcomplete"}, W.WAIT_MALFORMED),
    ],
)
def test_an_edition_s_refusal_is_NAMED_and_its_pages_stay_due(lane, answer, token):
    client = Scripted([answer])
    fetcher = _fetcher(client)
    _change(1, 11)
    report = fetcher.warm_for(3600)
    assert report.refusals == {token: 1} and report.paused is None
    assert fetcher.last_refusal == {EDITION: token} and fetcher.state == M.STATE_WAITING
    assert fetcher.status()["waiting"] == {EDITION: token}
    assert _rows()[1]["due_since"] is not None and _rows()[1]["latest_text"] is None
    counts = _counts()
    assert counts is None or counts["requests"] == 0, "a refused request is not an answered one"


def test_a_refusal_is_NEVER_a_retry_storm(lane):
    """Refused, then asked again only after the doubling wait -- one minute, then two."""
    clock = Clock()
    client = Scripted([_http(503), _http(503), {"pages": {1: _text(11)}}])
    fetcher = _fetcher(client, clock=clock)
    _change(1, 11)
    fetcher.warm_for(3600)
    assert len(client.asked) == 1
    fetcher.warm_for(3600)
    assert len(client.asked) == 1, "nothing asked while the wait runs"
    clock.t += W.BACKOFF_FIRST_S
    fetcher.warm_for(3600)
    assert len(client.asked) == 2
    clock.t += W.BACKOFF_FIRST_S  # the second wait is TWO minutes
    fetcher.warm_for(3600)
    assert len(client.asked) == 2
    clock.t += W.BACKOFF_FIRST_S
    fetcher.warm_for(3600)
    assert _rows()[1]["latest_revid"] == 11 and fetcher.last_refusal == {}
    assert fetcher.state == M.STATE_CAUGHT_UP


def test_an_UNKNOWN_fault_is_raised_not_dressed_up_as_a_network_refusal(lane):
    _change(1, 11)
    with pytest.raises(KeyError):
        _fetcher(Scripted([KeyError("a bug")])).warm_for(3600)


def test_one_edition_s_refusal_never_stops_ANOTHER(lane):
    class TwoEditions:
        def __init__(self):
            self.asked: list[str] = []

        def fetch_warm_texts(self, wiki, pageids):
            self.asked.append(wiki)
            if wiki == "aa":
                raise _http(503)
            return {"pages": {p: _text(p * 10) for p in pageids}, "partial": False,
                    "error": None, "malformed": None, "response_bytes": 10}

    _change(1, 11, edition="aa")
    _change(2, 21, edition="bb")
    client = TwoEditions()
    fetcher = _fetcher(client, editions=("aa", "bb"))
    fetcher.warm_for(3600)
    assert client.asked == ["aa", "bb"], "round-robin, and a busy edition is asked once"
    assert _rows("bb")[2]["latest_revid"] == 20 and _rows("aa")[1]["latest_text"] is None
    assert fetcher.status()["waiting"] == {"aa": W.WAIT_SERVICE_BUSY}


def test_the_window_ends_at_its_DEADLINE_and_the_rest_waits_for_the_next(lane):
    clock = Clock()

    class Slow(FixtureWikiClient):
        def fetch_warm_texts(self, wiki, pageids):
            clock.t += 20.0
            return super().fetch_warm_texts(wiki, pageids)

    for pid, rev in ((101, 1011), (102, 1007), (104, 1009)):
        _change(pid, rev)
    client = Slow()
    report = _fetcher(client, batch=1, clock=clock).warm_for(30.0)
    assert report.requests == 2, "a request is never started past the deadline"
    assert sum(r["due_since"] is not None for r in _rows().values()) == 1


# --------------------------------------------------------------------------- #
# Where WARM runs, what it reports, and where its tables live.
# --------------------------------------------------------------------------- #
def test_the_runner_gives_WARM_the_idle_time_BEFORE_the_walk_and_a_broken_WARM_never_ends_the_lane(lane):
    from src.wiki.runner import WikiLaneRunner

    order: list[str] = []
    slept: list[float] = []

    class Broken:
        def warm_for(self, seconds, *, should_stop):
            order.append("warm")
            raise RuntimeError("a WARM bug")

        def status(self):
            return {"state": "fetching"}

    class Walker:
        def walk_for(self, seconds, *, should_stop):
            order.append("walk")
            return W.WindowReport()

        def status(self):
            return {"state": "off"}

    runner = WikiLaneRunner(
        adapter=None, stream=None, lane_session=_session, state_of=lambda: "running",
        hot_sets=dict, budget=_plenty, walker=Walker(), warm=Broken(), sleep=slept.append,
        monotonic=lambda: 0.0, drain_interval_s=30.0,
    )
    runner.idle(30.0)
    assert order == ["warm", "walk"], "HOT, then WARM, then COLD: Q707's own order"
    assert slept == [30.0], "the interval is still slept when WARM fails"
    assert runner.last_warm == {"error": "RuntimeError"}
    assert runner.warm_status()["last_window"] == {"error": "RuntimeError"}

    _change(101, 1011)
    fetcher = _fetcher(FixtureWikiClient())
    runner = WikiLaneRunner(
        adapter=None, stream=None, lane_session=_session, state_of=lambda: "running",
        hot_sets=dict, budget=_plenty, warm=fetcher, sleep=slept.append,
        monotonic=lambda: 0.0, drain_interval_s=30.0,
    )
    runner.idle(30.0)
    assert runner.last_warm["texts"] == 1
    assert runner.warm_status()["state"] == M.STATE_CAUGHT_UP


def test_a_runner_built_without_WARM_reports_no_WARM(lane):
    from src.wiki.runner import WikiLaneRunner

    runner = WikiLaneRunner(
        adapter=None, stream=None, lane_session=_session, state_of=lambda: "running",
        hot_sets=dict, budget=_plenty, sleep=lambda s: None, monotonic=lambda: 0.0,
    )
    assert runner.warm_status() is None


def test_the_counters_artifact_carries_WARM_or_an_ABSENCE(lane):
    from src.wiki.counters import lane_counters

    with _session() as db:
        before = lane_counters(db)["warm"]
    assert before == {"measured": False, "reason": "warm-never-run"}, "absent, never zeros"
    for pid, rev in ((101, 1011), (102, 1007), (103, 1008)):
        _change(pid, rev)
    _fetcher(FixtureWikiClient()).warm_for(3600)
    _change(105, 901)
    _fetcher(FixtureWikiClient()).scan()
    with _session() as db:
        after = lane_counters(db)["warm"]
    assert after["measured"] is True
    [row] = after["editions"]
    assert (row["edition"], row["pages_with_text"], row["texts_fetched"], row["due"]) == (EDITION, 2, 2, 1)
    assert (after["requests"], after["due"]) == (1, 1)
    assert str(int(M.WARM_BUDGET_SHARE * 100)) in after["caveat"] and "proposed" in after["caveat"]
    assert after["method"]


def test_the_counters_say_a_lane_that_only_QUEUED_is_measured_with_nothing_fetched(lane):
    from src.wiki.warm import warm_coverage

    _change(101, 1011)
    _fetcher(FixtureWikiClient()).scan()
    with _session() as db:
        out = warm_coverage(db)
    assert out["measured"] is True and out["due"] == 1 and out["texts_fetched"] == 0


def test_the_WARM_tables_land_in_wiki_db_and_NOT_in_another_lane(tmp_path, monkeypatch):
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
    warm = {"wiki_warm_pages", "wiki_warm_editions", "wiki_warm_scan"}
    assert warm <= wiki and warm.isdisjoint(law)


def test_a_0_4_lane_file_GAINS_the_WARM_tables_when_this_build_opens_it(tmp_path, monkeypatch):
    from sqlalchemy import inspect

    from src.versioned import store

    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        store.create_lane("wiki")
        eng = store.lane_engine("wiki")
        with eng.begin() as conn:
            for name in ("wiki_warm_pages", "wiki_warm_editions", "wiki_warm_scan"):
                conn.execute(text(f'DROP TABLE "{name}"'))
        assert "wiki_warm_pages" not in inspect(eng).get_table_names()
        store.create_lane("wiki")
        names = set(inspect(store.lane_engine("wiki")).get_table_names())
        assert {"wiki_warm_pages", "wiki_warm_editions", "wiki_warm_scan"} <= names
    finally:
        store.dispose_all()


def test_the_service_status_carries_WARM_and_says_None_without_a_runner(monkeypatch):
    from src.wiki import service

    monkeypatch.setattr(service, "_RUNNER", None, raising=False)
    status = service.lane_service_status()
    assert "warm" in status and status["warm"] is None


def test_the_fixture_client_matches_the_REAL_client_s_signature():
    import inspect

    from src.wiki.client import WikiClient

    assert inspect.signature(FixtureWikiClient.fetch_warm_texts) == inspect.signature(
        WikiClient.fetch_warm_texts
    )


# --------------------------------------------------------------------------- #
# Living sources: WARM's block, and its words in all twelve languages.
# --------------------------------------------------------------------------- #
def test_living_sources_names_a_lane_that_never_ran_and_the_read_creates_nothing(tmp_path, monkeypatch):
    from src.api import living
    from src.versioned.store import lane_path

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setattr("src.wiki.service.lane_service_status", lambda: None)
    dispose_all()
    try:
        out = living._wiki_warm()
        assert (out["state"], out["measured"], out["reason_counts"]) == ("not_running", False, "lane-never-run")
        assert out["reason"] is None and out["waiting"] == {}
        assert out["share"] == M.WARM_BUDGET_SHARE
        assert not lane_path("wiki").exists(), "a GET made the lane file the drain should make"
    finally:
        dispose_all()


def test_living_sources_takes_WARM_s_STATE_from_the_process_and_its_COUNTS_from_the_rows(lane, monkeypatch):
    from src.api import living

    live = {"state": "paused", "reason": M.PAUSED_WARM_SHARE, "waiting": {EDITION: W.WAIT_SERVICE_BUSY}}
    monkeypatch.setattr("src.wiki.service.lane_service_status", lambda: {"warm": live})
    out = living._wiki_warm()
    assert (out["measured"], out["reason_counts"]) == (False, "warm-never-run"), "absent, never zeros"
    assert (out["state"], out["reason"]) == ("paused", M.PAUSED_WARM_SHARE)
    for pid, rev in ((101, 1011), (102, 1007)):
        _change(pid, rev)
    _fetcher(FixtureWikiClient()).warm_for(3600)
    out = living._wiki_warm()
    assert out["measured"] is True and out["pages_with_text"] == 2 and out["texts_fetched"] == 2
    assert out["reason"] == M.PAUSED_WARM_SHARE, "the counts must never overwrite the pause's reason"
    assert out["waiting"] == {EDITION: W.WAIT_SERVICE_BUSY}
    assert [e["edition"] for e in out["editions"]] == [EDITION]


@pytest.mark.parametrize(
    "enabled, live, want",
    [
        (True, {"state": "off"}, "not_started"),    # switched on since the last window
        (False, {"state": "off"}, "off"),
        (True, {"state": "fetching"}, "fetching"),
        (False, {"state": "fetching"}, "fetching"),  # the page draws Off from ``enabled``
        (None, {"state": "off"}, "off"),             # an unreadable switch moves nothing
        (True, None, "not_running"),
    ],
)
def test_a_state_the_OLD_setting_produced_is_not_shown_as_the_new_one(enabled, live, want):
    from src.api import living

    assert living._state_since_switch(enabled, live) == want


def test_living_sources_says_NOT_STARTED_right_after_the_switch_is_turned_on(lane, monkeypatch):
    from src.api import living

    monkeypatch.setattr("src.wiki.service.lane_service_status", lambda: {"warm": {"state": "off"}})
    monkeypatch.setattr(
        "src.scheduler.settings.load_settings", lambda: type("S", (), {"wiki_warm_enabled": True})()
    )
    out = living._wiki_warm()
    assert (out["enabled"], out["state"]) == (True, "not_started"), (
        "a ticked box beside «Off»: the fetcher's last window ran under the old setting"
    )


def test_living_sources_says_not_running_when_the_lane_runs_WITHOUT_a_WARM_fetcher(lane, monkeypatch):
    from src.api import living

    monkeypatch.setattr("src.wiki.service.lane_service_status", lambda: {"warm": None, "walk": None})
    assert living._wiki_warm()["state"] == "not_running"


def test_the_overview_carries_WARM_before_the_walk_in_Q707_s_order(lane, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api import living
    from src.database.models import Base, LawDocument, LawRevision, WikiPage, WikiRevision

    monkeypatch.setattr("src.wiki.service.lane_service_status", lambda: None)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[t.__table__ for t in (WikiPage, WikiRevision, LawDocument, LawRevision)]
    )
    db = sessionmaker(bind=engine)()
    try:
        out = living.living_overview(db=db)
    finally:
        db.close()
        engine.dispose()
    wiki = out["sources"][0]
    assert list(wiki) == ["kind", "stream", "tracked", "warm", "walk", "storage"]
    assert wiki["warm"]["state"] == "not_running" and wiki["warm"]["measured"] is False
    assert "Other changed pages (WARM)" in out["method"]


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


def test_every_token_WARM_can_publish_has_a_sentence_and_one_cause_has_ONE_wording():
    why = _js_table("_LIVING_WARM_WHY")
    assert set(why) == set(M.WARM_PAUSES) | set(W.EDITION_WAITS), (
        "every token WARM can publish has a sentence, and no sentence names a token it cannot"
    )
    assert set(_js_table("_LIVING_WARM_STATE")) == set(M.WARM_STATES) | {"not_running"}
    walk = _js_table("_LIVING_WALK_WHY")
    for token, line in why.items():
        if token == W.PAUSED_TRANSPORT_UNAVAILABLE:
            # The one sentence that names its subject: the lane, not the walk.
            assert line.endswith("and the lane never goes direct."), line
        elif token in walk:
            assert line == walk[token], (token, line, walk[token])


def _warm_keys() -> list[str]:
    keys: list[str] = []
    # Table-driven words: t(TABLE[token]) is invisible to the literal t("...") gate.
    for name in ("_LIVING_WARM_STATE", "_LIVING_WARM_WHY"):
        keys += list(_js_table(name).values())
    return sorted(set(keys))


@pytest.mark.parametrize("key", _warm_keys())
def test_WARM_s_table_driven_words_are_keyed_x12(key):
    for code, d in _locales().items():
        assert key in d and d[key].strip(), f"{code}.json has no value for {key!r}"


def test_the_edition_row_s_count_frame_keeps_both_counts_and_is_a_LABEL_in_russian_and_arabic():
    key = "{n} with text · {m} to fetch"
    for code, d in _locales().items():
        assert sorted(re.findall(r"\{(\w+)\}", d[key])) == ["m", "n"], f"{code}: {d[key]!r}"
    for code in ("ru", "ar"):
        value = _locales()[code][key]
        assert re.search(r":\s*\{n\}", value) and re.search(r":\s*\{m\}", value), f"{code}: {value!r}"


# --------------------------------------------------------------------------- #
# The switch in Settings -> Wikipedia: a listener, the cost stated visibly, x12.
# --------------------------------------------------------------------------- #
def _warm_label_html() -> str:
    from tests.js_source_helper import read_static

    m = re.search(r'<label[^>]*>\s*<input type="checkbox" id="wiki-warm-enabled"[^>]*>.*?</label>',
                  read_static("index.html"), re.S)
    assert m, "the WARM switch is gone from Settings -> Wikipedia"
    return m.group(0)


def test_the_settings_box_states_the_cost_and_where_the_texts_go_VISIBLY():
    label = _warm_label_html()
    visible = re.sub(r"<[^>]+>", " ", label)
    assert f"{int(M.WARM_BUDGET_SHARE * 100)}% of its storage budget" in visible, (
        "the visible cost quotes a share that is not WARM_BUDGET_SHARE"
    )
    assert "not in your corpus" in visible, "where the texts go is only in the hover"
    assert "runs only while the stream runs" in visible
    assert not re.search(r"\son[a-z]+\s*=", label), "an inline handler on the WARM switch"


def test_the_box_is_bound_by_a_LISTENER_and_saves_the_declared_field():
    from tests.js_source_helper import function_source, read_static

    boot = read_static("app-boot.js")
    assert 'warm.addEventListener("change", () => saveWikiWarm(warm.checked))' in boot
    save = function_source(read_static("app-sources.js"), "saveWikiWarm")
    assert "wiki_warm_enabled: !!on" in save and '"/api/scheduler/config"' in save
    assert "box.checked = stored" in save, "the box must mirror what was STORED, not the click"
    assert "box.checked = !on" in save, "a failed save must put the box back"
    for name in ("saveWikiWarm", "saveWikiWalk"):
        assert "livingRefreshIfShown()" in function_source(read_static("app-sources.js"), name), (
            f"{name}: Living sources would keep showing the state from before the switch moved"
        )
    refresh = function_source(read_static("app-living.js"), "livingRefreshIfShown")
    assert "if (_livingOverview) loadLivingOverview();" in refresh, "a never-opened view must not fetch"


def _switch_keys() -> list[str]:
    label = _warm_label_html()
    keys = [re.sub(r"\s+", " ", k).strip() for k in re.findall(r">([^<>]+)<", label) if k.strip()]
    keys.append(re.search(r'title="([^"]+)"', label).group(1))
    keys += [
        "Fetching other changed pages is on. It starts with the live stream, when you are online.",
        "Fetching other changed pages is off. Texts already fetched are kept.",
        "The lane can fetch the newest text of every other page the stream reports changed, 50 pages a "
        "request. That fetching is off: switch it on in Settings → Wikipedia.",
    ]
    return sorted(set(keys))


def test_the_switch_s_words_are_the_ones_this_test_keys():
    assert len(_switch_keys()) == 6, _switch_keys()


@pytest.mark.parametrize("key", _switch_keys())
def test_the_switch_s_words_are_keyed_x12(key):
    for code, d in _locales().items():
        assert key in d and d[key].strip(), f"{code}.json has no value for {key!r}"
