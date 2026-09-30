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

from datetime import timedelta

import pytest
from sqlalchemy import select

from src.testing.wiki_fixture import FixtureWikiClient
from src.testing.wiki_stream_fixture import FixtureStreamSession
from src.versioned import pipeline as pipeline_mod
from src.versioned.models import VersionedChange, VersionedEntity, _utcnow
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


def _patched_feeds(monkeypatch, names):
    order: list[tuple[str, int]] = []

    class Feeds:
        def feeds(self):
            return list(names)

    def fake_run_feed_once(lane, adapter, feed, **kw):
        order.append((feed, kw["catch_up"]))
        from src.versioned.pipeline import PassResult

        return PassResult(feed=feed)

    monkeypatch.setattr(runner_mod, "run_feed_once", fake_run_feed_once)
    monkeypatch.setattr(runner_mod, "make_admit", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "record_size_sample", lambda *a, **k: False)
    return Feeds(), order


def test_the_starting_feed_ROTATES_so_the_last_one_is_not_always_the_same(monkeypatch):
    feeds, order = _patched_feeds(monkeypatch, ["stream:a", "stream:b", "stream:c"])
    for turn in range(4):
        order.clear()
        drain_once(object(), feeds, hot_sets={}, budget=_plenty(), rotate=turn)
        assert sorted(f for f, _ in order) == ["stream:a", "stream:b", "stream:c"], "every feed, once"
        assert order[0][0] == ["stream:a", "stream:b", "stream:c"][turn % 3]


def test_the_backlog_is_read_only_when_the_fetching_is_bounded(monkeypatch):
    feeds, order = _patched_feeds(monkeypatch, ["stream:a"])
    drain_once(object(), feeds, hot_sets={}, budget=_plenty(), text_seconds=20.0)
    drain_once(object(), feeds, hot_sets={}, budget=_plenty(), text_seconds=None)
    assert order == [("stream:a", runner_mod.CATCH_UP_LIMIT), ("stream:a", 0)]


def test_a_text_the_bound_DEFERRED_is_fetched_by_the_NEXT_drain(lane):
    """The bound costs a page its text for a drain, never for good: nothing else would come
    back for a page admitted on its first edit, whose baseline the bound deferred."""
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        first = drain_once(db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=0.0)
    assert _stored(first) == 0 and first.text_deferred >= 1
    with lane_session("wiki") as db:
        second = drain_once(db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=3600.0)
    assert second.changes_recorded == 0, "the buffer was already drained"
    assert _stored(second) >= 1, "the catch-up fetched what the first drain had to leave"
    with lane_session("wiki") as db:
        third = drain_once(db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=3600.0)
    assert _stored(third) == 0 and third.text_deferred == 0, "and once fetched it is not asked again"


def test_a_text_the_BUDGET_refused_is_withheld_not_relabelled_deferred(lane):
    adapter = _filled_adapter()
    spent = budget_state(total_gb=1, disk_bytes=2 * 1024**3, editions=1)
    assert spent.exhausted
    with lane_session("wiki") as db:
        report = drain_once(db, adapter, hot_sets=_hot(), budget=spent, text_seconds=0.0)
    assert report.text_deferred == 0, "the storage budget's refusal keeps its own name"
    assert _stored(report) == 0


class _Tier:
    def __init__(self, log, name, on=True):
        self.log, self.name, self.on = log, name, on

    def is_on(self):
        return self.on

    def warm_for(self, seconds, **_kw):
        self.log.append((self.name, round(seconds, 6)))
        return _Report()

    walk_for = index_for = warm_for


class _Report:
    def as_dict(self):
        return {}


def _idle_runner(log, *, walk_on):
    clock = {"t": 0.0}
    runner = WikiLaneRunner(
        adapter=_filled_adapter(),
        stream=None,
        lane_session=lambda: lane_session("wiki"),
        state_of=lambda: "running",
        hot_sets=_hot,
        budget=_plenty,
        warm=_Tier(log, "warm"),
        walker=_Tier(log, "walk", on=walk_on),
        sleep=lambda _s: None,
        monotonic=lambda: clock["t"],
    )
    return runner


def test_WARM_leaves_the_walk_its_reserve_while_the_walk_is_on():
    log: list = []
    _idle_runner(log, walk_on=True).idle(100.0)
    assert log[0] == ("warm", 100.0 * (1.0 - runner_mod.WALK_RESERVE))
    assert log[1][0] == "walk" and log[1][1] > 0


def test_WARM_keeps_the_whole_window_when_the_walk_is_off():
    log: list = []
    _idle_runner(log, walk_on=False).idle(100.0)
    assert log[0] == ("warm", 100.0)


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


def _deferred_lane():
    """A lane whose one HOT page has its change recorded and its text deferred."""
    adapter = _filled_adapter()
    with lane_session("wiki") as db:
        first = drain_once(db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=0.0)
    assert first.text_deferred >= 1
    return adapter


def _entity(db):
    return db.execute(select(VersionedEntity)).scalars().one()


def test_the_BACKLOG_is_not_counted_as_deferred_again_on_every_drain(lane):
    adapter = _deferred_lane()
    with lane_session("wiki") as db:
        _entity(db).last_checked_at = _utcnow() - timedelta(hours=1)
    with lane_session("wiki") as db:
        again = drain_once(db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=0.0)
    assert again.text_deferred == 0, "a page counted on the drain that left it is not counted twice"


def test_a_page_the_source_reported_GONE_is_not_asked_for_again(lane):
    _deferred_lane()
    with lane_session("wiki") as db:
        ent = _entity(db)
        ent.deleted_at = _utcnow()
        ent.last_checked_at = _utcnow() - timedelta(hours=1)
    with lane_session("wiki") as db:
        assert pipeline_mod._unfetched_entities(db, f"stream:{EDITION}", 10) == []


def test_an_UNWATCHED_page_is_not_in_the_backlog(lane):
    _deferred_lane()
    with lane_session("wiki") as db:
        ent = _entity(db)
        ent.watching = False
        ent.last_checked_at = None
    with lane_session("wiki") as db:
        assert pipeline_mod._unfetched_entities(db, f"stream:{EDITION}", 10) == []


def test_a_page_checked_a_moment_ago_waits_out_its_COOLDOWN(lane):
    _deferred_lane()
    feed = f"stream:{EDITION}"
    with lane_session("wiki") as db:
        _entity(db).last_checked_at = _utcnow()
    with lane_session("wiki") as db:
        assert pipeline_mod._unfetched_entities(db, feed, 10) == [], "inside the cooldown"
    with lane_session("wiki") as db:
        _entity(db).last_checked_at = _utcnow() - timedelta(seconds=pipeline_mod.BACKLOG_COOLDOWN_S + 5)
    with lane_session("wiki") as db:
        assert len(pipeline_mod._unfetched_entities(db, feed, 10)) == 1, "and back after it"


def test_a_FAILED_fetch_is_stamped_so_it_leaves_the_head_of_the_backlog(lane, monkeypatch):
    adapter = _deferred_lane()
    with lane_session("wiki") as db:
        _entity(db).last_checked_at = _utcnow() - timedelta(hours=1)

    def boom(_external_id):
        raise RuntimeError("the service said 429")

    monkeypatch.setattr(adapter, "fetch_version", boom)
    with lane_session("wiki") as db:
        report = drain_once(db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=3600.0)
    assert any("429" in e for p in report.passes.values() for e in p.get("errors", []))
    with lane_session("wiki") as db:
        assert pipeline_mod._unfetched_entities(db, f"stream:{EDITION}", 10) == []


def test_a_page_whose_STORE_raises_does_not_end_the_pass_or_poison_the_session(lane, monkeypatch):
    adapter = _deferred_lane()
    with lane_session("wiki") as db:
        _entity(db).last_checked_at = _utcnow() - timedelta(hours=1)

    def boom(*_a, **_k):
        raise RuntimeError("the corpus upsert failed")

    monkeypatch.setattr(pipeline_mod, "store_version", boom)
    with lane_session("wiki") as db:
        report = drain_once(db, adapter, hot_sets=_hot(), budget=_plenty(), text_seconds=3600.0)
        # the session is still usable for the rest of the drain and its commit
        assert db.execute(select(VersionedChange)).scalars().first() is not None
    errors = [e for p in report.passes.values() for e in p.get("errors", [])]
    assert any("store: RuntimeError" in e for e in errors), errors
    with lane_session("wiki") as db:
        assert pipeline_mod._unfetched_entities(db, f"stream:{EDITION}", 10) == [], (
            "stamped before the attempt, so it does not head the next pass"
        )
