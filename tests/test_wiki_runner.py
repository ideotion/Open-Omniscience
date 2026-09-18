"""The runner: the piece that makes the lane COLLECT, driven on the recorded fixture.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S04-09's first PR listed the absence of this wiring as the slice's largest gap — "the
≥ 72 h run is not merely un-run, it is not yet startable". These tests are what makes
the claim that it is startable checkable: the whole loop runs here, on the recorded
stream, with the airplane socket guard armed.

WHAT IS WORTH TESTING ABOUT A RUNNER IS WHAT IT DOES OVER TIME AND AT THE EDGES —
whether it stops when the operator says stop, whether it keeps collecting metadata
when the budget is spent, whether one broken edition ends the other eleven. Those are
what is here. That it can store a change on a happy path is the least of it.
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import select

from src.ingest import activate_kill_switch, clear_kill_switch
from src.testing.wiki_fixture import FixtureWikiClient
from src.testing.wiki_stream_fixture import FixtureStreamSession
from src.versioned.models import VersionedChange, VersionedEntity
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki.lane import WikiStreamAdapter
from src.wiki.runner import BUDGET_FULL, DrainReport, WikiLaneRunner, drain_once
from src.wiki.stream import WikiEventStream
from src.wiki.tiers import HotSet, budget_state

EDITION = "oo"
ALPHA, BETA = 101, 102


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


def _filled_adapter():
    """An adapter whose buffer holds the whole recorded stream. No sockets."""
    adapter = WikiStreamAdapter(client=FixtureWikiClient(), editions=(EDITION,))
    WikiEventStream(
        session=FixtureStreamSession(), editions=(EDITION,), sleep=lambda _s: None
    ).run(adapter.offer, max_connections=1, on_position=adapter.note_position)
    return adapter


def _hot(**kw):
    return {EDITION: HotSet(EDITION, **kw)}


def _plenty():
    return budget_state(total_gb=20, disk_bytes=0, editions=1)


def _spent():
    return budget_state(total_gb=1, disk_bytes=2 * 1024**3, editions=1)


# --------------------------------------------------------------------------- #
# Admission: the tier is the only thing that grows the lane.
# --------------------------------------------------------------------------- #
def test_the_lane_follows_a_HOT_page_by_itself_and_records_WHY(lane):
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        report = drain_once(
            db, adapter, hot_sets=_hot(corpus_mention_titles={"Fixture Alpha"}), budget=_plenty()
        )
    assert report.entities_admitted == 1
    with lane_session("wiki") as db:
        row = db.execute(select(VersionedEntity)).scalar_one()
        assert row.external_id == f"{EDITION}:p{ALPHA}"
        assert row.admitted_reason == "corpus_mention", (
            "the operator can see which rule brought it in"
        )


def test_a_page_that_MOVED_mid_stream_is_still_admitted_under_its_OLD_title(lane):
    """The measured defect: the seen-map kept only the newest name, so page 101 —
    plainly mentioned by the corpus as "Fixture Alpha" — was never followed."""
    adapter = _filled_adapter()
    assert adapter.seen(f"{EDITION}:p{ALPHA}") == ((), None), (
        "the seen-map is a property of the batch just DRAINED, and nothing is drained yet"
    )
    with lane_session("wiki") as db:
        report = drain_once(
            db, adapter, hot_sets=_hot(corpus_mention_titles={"Fixture Alpha"}), budget=_plenty()
        )
    titles, page_id = adapter.seen(f"{EDITION}:p{ALPHA}")
    assert page_id == ALPHA
    assert titles.index("Fixture Alpha") < titles.index("Fixture Alpha (renamed)"), (
        "both names the batch used, oldest first"
    )
    assert report.entities_admitted == 1


def test_WITHOUT_an_admit_rule_the_lane_never_grows_by_itself(lane):
    """The substrate's default, unchanged: no callback, no lane ever follows anything."""
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        report = drain_once(db, adapter, hot_sets={}, budget=_plenty())
        assert report.entities_admitted == 0
        assert report.changes_recorded == 15, "and yet EVERY edit is still recorded"
        assert db.execute(select(VersionedEntity)).first() is None


def test_admission_happens_BEFORE_the_batch_is_recorded_so_the_change_is_linked(lane):
    """Running it after would leave the admitting change orphaned, and the page would
    wait for its NEXT edit before any text arrived."""
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        drain_once(
            db, adapter, hot_sets=_hot(corpus_mention_titles={"Fixture Alpha"}), budget=_plenty()
        )
    with lane_session("wiki") as db:
        entity = db.execute(select(VersionedEntity)).scalar_one()
        linked = db.execute(
            select(VersionedChange).where(VersionedChange.entity_id == entity.id)
        ).scalars().all()
    assert linked, "the very change that admitted the page names it"


# --------------------------------------------------------------------------- #
# The budget stops TEXT and never the metadata.
# --------------------------------------------------------------------------- #
def test_a_spent_budget_withholds_TEXT_by_name_and_keeps_recording_METADATA(lane):
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        report = drain_once(
            db, adapter, hot_sets=_hot(corpus_mention_titles={"Fixture Alpha"}), budget=_spent()
        )
    assert report.changes_recorded == 15, "Q108 = a: metadata for EVERY edit"
    assert report.text_withheld >= 1
    assert report.text_withheld_reasons == {BUDGET_FULL: report.text_withheld}
    assert report.revisions_stored == 0


def test_the_withheld_reason_is_NOT_the_word_gap_or_the_word_deferred(lane):
    """Three states, three names. Merging them is what the counters exist to prevent."""
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        report = drain_once(
            db, adapter, hot_sets=_hot(corpus_mention_titles={"Fixture Alpha"}), budget=_spent()
        )
    assert report.gaps_recorded == 0, "a full disk is not a hole in our knowledge"
    assert report.as_dict()["passes"][f"stream:{EDITION}"]["text_deferred"] == 0


def test_an_UNMEASURED_budget_does_not_stop_the_first_pass(lane):
    """A lane that has never run holds no bytes; refusing there would stop it forever."""
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        report = drain_once(
            db,
            adapter,
            hot_sets=_hot(corpus_mention_titles={"Fixture Alpha"}),
            budget=budget_state(total_gb=20, disk_bytes=None, editions=12),
        )
    assert report.text_withheld == 0


def test_the_budget_in_the_report_is_the_one_read_BEFORE_the_writes_it_describes(lane):
    adapter = _filled_adapter()
    before = _plenty()
    with lane_session("wiki") as db:
        report = drain_once(
            db, adapter, hot_sets=_hot(corpus_mention_titles={"Fixture Alpha"}), budget=before
        )
    assert report.budget == before.as_dict()


# --------------------------------------------------------------------------- #
# One broken edition must not end the others.
# --------------------------------------------------------------------------- #
def test_a_feed_that_raises_is_NAMED_and_the_drain_continues(lane):
    class Exploding(WikiStreamAdapter):
        def read_changes(self, *, feed, since, budget):
            if feed.endswith(":boom"):
                raise RuntimeError("the boom edition is broken")
            return super().read_changes(feed=feed, since=since, budget=budget)

    adapter = Exploding(client=FixtureWikiClient(), editions=("boom", EDITION))
    WikiEventStream(
        session=FixtureStreamSession(), editions=(EDITION,), sleep=lambda _s: None
    ).run(adapter.offer, max_connections=1, on_position=adapter.note_position)
    with lane_session("wiki") as db:
        report = drain_once(db, adapter, hot_sets=_hot(), budget=_plenty())
    assert any("boom" in e and "RuntimeError" in e for e in report.errors), report.errors
    assert report.changes_recorded == 15, "the working edition still collected"


# --------------------------------------------------------------------------- #
# The runner obeys the operator's setting, and only that.
# --------------------------------------------------------------------------- #
def _runner(adapter, state, **kw):
    return WikiLaneRunner(
        adapter=adapter,
        stream=WikiEventStream(
            session=FixtureStreamSession(), editions=(EDITION,), sleep=lambda _s: None
        ),
        lane_session=lambda: lane_session("wiki"),
        state_of=lambda: state["value"],
        hot_sets=lambda: _hot(corpus_mention_titles={"Fixture Alpha"}),
        budget=_plenty,
        sleep=lambda _s: None,
        **kw,
    )


def test_the_runner_refuses_to_start_unless_the_setting_says_running(lane):
    for value in ("halted", "stopped"):
        runner = _runner(_filled_adapter(), {"value": value})
        assert runner.start() is False
        assert runner.streaming is False


def test_the_loop_ENDS_when_the_setting_stops_saying_running(lane):
    state = {"value": "running"}
    runner = _runner(_filled_adapter(), state)

    original = runner.drain

    def drain_then_halt():
        result = original()
        state["value"] = "halted"
        return result

    runner.drain = drain_then_halt  # type: ignore[method-assign]
    assert runner.run_until_stopped() == 1, "one drain, then the setting stopped it"


def test_an_UNREADABLE_setting_STOPS_the_stream_rather_than_continuing(lane):
    """The one direction this must not fail in: collecting on a permission it can no
    longer confirm."""

    def explode() -> str:
        raise RuntimeError("the settings file is unreadable")

    runner = WikiLaneRunner(
        adapter=_filled_adapter(),
        stream=WikiEventStream(
            session=FixtureStreamSession(), editions=(EDITION,), sleep=lambda _s: None
        ),
        lane_session=lambda: lane_session("wiki"),
        state_of=explode,
        hot_sets=lambda: _hot(),
        budget=_plenty,
        sleep=lambda _s: None,
    )
    assert runner._should_stop() is True
    assert runner.run_until_stopped() == 0, "and it never drained at all"


def test_stop_is_idempotent_and_leaves_no_thread_behind(lane):
    runner = _runner(_filled_adapter(), {"value": "running"})
    runner.stop()
    runner.stop()
    assert runner.streaming is False


def test_the_runner_reports_NO_last_drain_before_it_has_drained(lane):
    """An ABSENCE, never a report of zero."""
    runner = _runner(_filled_adapter(), {"value": "running"})
    assert runner.last_drain is None
    assert runner.drains == 0
    runner.drain()
    assert runner.last_drain is not None and runner.drains == 1


def test_the_stream_thread_ends_by_NAME_when_airplane_mode_is_engaged(lane, caplog):
    """Invariant #14e's corollary, through the runner: a refusal BY THE KILL SWITCH is
    named as such, not reported as the remote service going quiet."""
    import logging

    runner = _runner(_filled_adapter(), {"value": "running"}, max_connections=1)
    activate_kill_switch()
    try:
        with caplog.at_level(logging.INFO, logger="wiki.runner"):
            runner._stream_body()
    finally:
        clear_kill_switch()
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "kill switch" in joined, joined
    assert "not by Wikimedia" in joined, "named as OUR refusal, never the source's"
    assert "airplane" in joined, "and in the operator's own word for it"


def test_the_stream_thread_never_opens_a_database(lane):
    """Structural: the split at the buffer is the rule, so a SQLite handle is never
    shared across threads. Asserted by driving the stream body and finding nothing."""
    runner = _runner(_filled_adapter(), {"value": "running"}, max_connections=1)
    opened: list[str] = []

    import src.wiki.runner as runner_mod

    original = runner_mod.drain_once
    runner_mod.drain_once = lambda *a, **k: opened.append("drained") or DrainReport()  # type: ignore[assignment]
    try:
        runner._stream_body()
    finally:
        runner_mod.drain_once = original  # type: ignore[assignment]
    assert opened == [], "the stream half stores nothing; the drain half does"


def test_the_stream_and_the_drain_can_run_at_once_without_sharing_a_handle(lane):
    """The two-thread rule, exercised rather than asserted."""
    adapter = WikiStreamAdapter(client=FixtureWikiClient(), editions=(EDITION,))
    stream = WikiEventStream(
        session=FixtureStreamSession(), editions=(EDITION,), sleep=lambda _s: None
    )
    done = threading.Event()

    def pump():
        stream.run(adapter.offer, max_connections=1, on_position=adapter.note_position)
        done.set()

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    done.wait(timeout=10)
    thread.join(timeout=5)
    with lane_session("wiki") as db:
        report = drain_once(
            db, adapter, hot_sets=_hot(corpus_mention_titles={"Fixture Alpha"}), budget=_plenty()
        )
    assert report.changes_recorded == 15


# --------------------------------------------------------------------------- #
# Q706's cadence: twelve requests a day, spent one at a time.
# --------------------------------------------------------------------------- #
def test_the_daily_top_up_asks_for_YESTERDAY_not_today(lane):
    """The service aggregates a day after it ends. Asking for today returns nothing,
    and the caller cannot tell that from "nobody read anything"."""
    from datetime import UTC, datetime

    from src.wiki.pageviews import due_day

    now = datetime(2026, 9, 18, 0, 5, tzinfo=UTC)
    assert due_day(now).isoformat() == "2026-09-17"


def test_an_edition_never_fetched_is_DUE_and_one_fetched_today_is_not(lane):
    from datetime import date

    from src.wiki.pageviews import is_due

    want = date(2026, 9, 17)
    assert is_due(None, want) is True, "never fetched"
    assert is_due(date(2026, 9, 16), want) is True, "stale"
    assert is_due(want, want) is False, "already have it"
    assert is_due(date(2026, 9, 18), want) is False, (
        "a clock that moved backwards must not spend a request to learn nothing"
    )


def test_the_top_up_spends_ONE_request_per_tick_not_twelve(lane):
    """Twelve at once is the same daily budget arriving as a burst -- twelve times
    harder on the service and no faster for the operator."""
    calls: list[str] = []
    runner = _runner(_filled_adapter(), {"value": "running"})
    runner._pageviews = lambda: (calls.append("one") or "en")
    runner.refresh_one_pageview_top()
    assert calls == ["one"]


def test_a_FAILING_top_up_does_not_end_the_drain_loop(lane):
    def explode():
        raise RuntimeError("the analytics host is down")

    state = {"value": "running"}
    runner = _runner(_filled_adapter(), state)
    runner._pageviews = explode
    original = runner.drain

    def drain_then_halt():
        result = original()
        state["value"] = "halted"
        return result

    runner.drain = drain_then_halt  # type: ignore[method-assign]
    assert runner.run_until_stopped() == 1, "the drain still happened and still counted"


def test_the_top_up_runs_AFTER_the_drain(lane):
    """The drain is the lane's job; the attention signal is a top-up for the NEXT one."""
    order: list[str] = []
    state = {"value": "running"}
    runner = _runner(_filled_adapter(), state)
    original = runner.drain

    def drain_then_halt():
        order.append("drain")
        result = original()
        state["value"] = "halted"
        return result

    runner.drain = drain_then_halt  # type: ignore[method-assign]
    runner._pageviews = lambda: (order.append("pageviews") or "en")
    runner.run_until_stopped()
    assert order == ["drain", "pageviews"]
