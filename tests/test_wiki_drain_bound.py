"""A drain may not starve the tiers behind it, and its progress is in the status.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

MEASURED ON A REAL RUN (2026-09-30, the 72 h soak's first hours): the stream was live and the
walk was switched on, yet ``drains`` read 0, ``last_drain`` null, and the walk, WARM and the
search index all ``not_started`` with no request made. The index, WARM and the walk run in
the idle time AFTER a drain, and a drain fetched one polite request per touched page with no
bound of its own, so a stream resumed behind a backlog kept the drain busy and the three tiers
waiting behind it. The drain now has a time bound for FETCHING texts, shared out between the
feeds; what it did not reach is counted as deferred, never dropped silently. And the status
says where the drain is, so "drains: 0" can be told apart: stuck in the hot-set read,
fetching, failing, or not yet started.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.testing.wiki_fixture import FixtureWikiClient
from src.testing.wiki_stream_fixture import FixtureStreamSession
from src.versioned.models import VersionedChange
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import runner as runner_mod
from src.wiki.lane import WikiStreamAdapter
from src.wiki.runner import DRAIN_TEXT_SECONDS, DrainReport, WikiLaneRunner, drain_once
from src.wiki.stream import WikiEventStream
from src.wiki.tiers import HotSet, budget_state

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


def _filled_adapter():
    adapter = WikiStreamAdapter(client=FixtureWikiClient(), editions=(EDITION,))
    WikiEventStream(
        session=FixtureStreamSession(), editions=(EDITION,), sleep=lambda _s: None
    ).run(adapter.offer, max_connections=1, on_position=adapter.note_position)
    return adapter


def _hot():
    return {EDITION: HotSet(EDITION, corpus_mention_titles={"Fixture Alpha"})}


def _plenty():
    return budget_state(total_gb=20, disk_bytes=0, editions=1)


def _stored(report: DrainReport) -> int:
    p = report.passes[f"stream:{EDITION}"]
    return int(p.get("baselines_captured", 0)) + int(p.get("revisions_stored", 0))


def test_the_default_bound_is_a_real_number_not_unbounded():
    assert 0 < DRAIN_TEXT_SECONDS <= 120


def test_a_drain_with_no_time_left_RECORDS_every_change_and_DEFERS_every_text(lane):
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        report = drain_once(
            db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=0.0
        )
        recorded = len(db.execute(select(VersionedChange)).scalars().all())
    assert report.changes_recorded == 15, "metadata is never traded for time"
    assert recorded == 15
    assert report.text_deferred >= 1, "the texts it did not reach are COUNTED, not dropped"
    assert _stored(report) == 0, "and none was fetched once the bound had passed"
    assert report.as_dict()["text_deferred"] == report.text_deferred


def test_an_unbounded_drain_still_fetches_the_text_as_before(lane):
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        report = drain_once(
            db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=None
        )
    assert report.text_deferred == 0
    assert _stored(report) >= 1, "the HOT page's text arrives when nothing bounds the drain"


def test_a_generous_bound_fetches_everything_too(lane):
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        report = drain_once(
            db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=3600.0
        )
    assert report.text_deferred == 0 and _stored(report) >= 1


def test_the_feeds_SHARE_the_bound_so_a_busy_first_edition_cannot_spend_it_all(monkeypatch):
    """Each feed gets an equal share of what is LEFT; a feed that uses its whole share
    leaves the next its own, instead of the first taking everything."""
    clock = {"t": 0.0}
    seen: list[float] = []

    class Feeds:
        def feeds(self):
            return ["stream:a", "stream:b", "stream:c"]

    def fake_run_feed_once(lane, adapter, feed, **kw):
        deadline = kw["fetch_deadline"]
        seen.append(round(deadline - clock["t"], 6))
        clock["t"] = deadline  # this feed spends its whole share
        from src.versioned.pipeline import PassResult

        return PassResult(feed=feed)

    monkeypatch.setattr(runner_mod, "run_feed_once", fake_run_feed_once)
    monkeypatch.setattr(runner_mod, "make_admit", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "record_size_sample", lambda *a, **k: False)
    drain_once(
        object(), Feeds(), hot_sets={}, budget=_plenty(), text_seconds=12.0,
        monotonic=lambda: clock["t"],
    )
    assert seen == [4.0, 4.0, 4.0], seen


def test_the_drain_reports_WHERE_it_is_and_clears_when_it_ends(lane):
    state = {"value": "running"}
    stages: list[tuple[str, str | None]] = []
    holder: dict[str, WikiLaneRunner] = {}

    def hot_sets():
        stages.append((holder["r"].drain_status()["stage"], None))
        return _hot()

    runner = WikiLaneRunner(
        adapter=_filled_adapter(),
        stream=WikiEventStream(
            session=FixtureStreamSession(), editions=(EDITION,), sleep=lambda _s: None
        ),
        lane_session=lambda: lane_session("wiki"),
        state_of=lambda: state["value"],
        hot_sets=hot_sets,
        budget=_plenty,
        sleep=lambda _s: None,
    )
    holder["r"] = runner
    before = runner.drain_status()
    assert before["stage"] == "idle" and before["running_for_s"] is None
    assert before["since_last_drain_s"] is None, "no drain yet is an absence, never 0"
    runner.drain()
    assert stages == [("hot-sets", None)], "a slow hot-set read is visible AS a hot-set read"
    after = runner.drain_status()
    assert after["stage"] == "idle" and after["feed"] is None
    assert after["running_for_s"] is None
    assert after["since_last_drain_s"] is not None
    assert runner.drains == 1


def test_a_failed_drain_leaves_the_stage_idle_and_the_reason_in_the_status(lane):
    state = {"value": "running"}

    def boom():
        raise RuntimeError("the keyword read timed out")

    runner = WikiLaneRunner(
        adapter=_filled_adapter(),
        stream=WikiEventStream(
            session=FixtureStreamSession(), editions=(EDITION,), sleep=lambda _s: None
        ),
        lane_session=lambda: lane_session("wiki"),
        state_of=lambda: state["value"],
        hot_sets=boom,
        budget=_plenty,
        sleep=lambda _s: None,
    )
    runner.run_until_stopped()
    status = runner.drain_status()
    assert status["stage"] == "idle", "a failure must not leave the lane claiming to be mid-drain"
    assert status["consecutive_failures"] == runner_mod.MAX_CONSECUTIVE_FAILURES
    assert "keyword read timed out" in (status["last_error"] or "")
    assert status["stopped"] is True


def test_the_service_status_carries_the_drain_block(lane):
    from src.wiki import service

    assert service.lane_service_status()["drain"] is None, "no runner: an absence"
