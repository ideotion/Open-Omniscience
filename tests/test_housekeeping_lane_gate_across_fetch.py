"""The housekeeping lane's crawl step does not carry the single-writer gate into the next outlet's network work.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics 9931cffe (build a38defa27, 2026-10-28): ``oo-housekeeping-lane`` held the write gate for 2,933 s, 2,666 s of it BETWEEN
statements, and the stack at the end of the hold was ``safety.fetcher:send <- ingest.airplane:_guarded_getaddrinfo``.

The cause, read on main: ``_lane_step_crawl`` finishes each outlet with a bulk ``UPDATE`` of its sibling feeds' ``last_crawled_at``. A bulk
statement takes the gate at once and sets the session's gate flag, and nothing committed after it, so the NEXT outlet's sitemap discovery and
page walk ran with the gate held. The fetcher the lane hands its steps (``wrap_fetcher``) hands a session's connection back before a fetch
only when the session has not written, so it declined, by design: "a kind that leaves the session DIRTY across its own fetch loop is correctly
DECLINED" (``run_housekeeping_lane``). The comment named the limit; this is the kind it was about.

Pinned here: at every network call of the crawl step the session holds no gate, whatever outlet came before it.
"""

from __future__ import annotations

import pytest

from src.catalog.qualification import STATUS_QUALIFIED
from src.database.models import Base, Source, SourceMetadata
from src.database.session import SessionLocal, engine
from src.database.writer import _SESSION_FLAG
from src.ingest.sitemap import SitemapDiscoveryReport
from src.scheduler.runner import _lane_step_crawl
from src.scheduler.settings import SchedulerSettings

_DOMAINS = ("gate-across-fetch-a.example", "gate-across-fetch-b.example", "gate-across-fetch-c.example")


@pytest.fixture()
def session():
    Base.metadata.create_all(engine)
    s = SessionLocal()
    for d in _DOMAINS:
        s.add(Source(name=d, domain=d, rss_url=None, enabled=True, status=STATUS_QUALIFIED))
    s.commit()
    try:
        yield s
    finally:
        s.rollback()
        ids = [i for (i,) in s.query(Source.id).filter(Source.domain.in_(_DOMAINS))]
        s.query(SourceMetadata).filter(SourceMetadata.source_id.in_(ids)).delete(synchronize_session=False)
        s.query(Source).filter(Source.domain.in_(_DOMAINS)).delete(synchronize_session=False)
        s.commit()
        s.close()


class _Report:
    pages_fetched = 1


def _run_step(session, monkeypatch):
    """The crawl step with the network replaced by recorders: at each call the session's gate flag is read."""
    held: list[tuple[str, str, bool]] = []

    def discover(fetcher, host, *, max_urls=0, **kw):
        held.append(("discover", host, bool(session.info.get(_SESSION_FLAG))))
        return SitemapDiscoveryReport(source_host=host)

    def crawl(session_, source, *, fetcher, config, start_url=None):
        held.append(("crawl", source.domain, bool(session.info.get(_SESSION_FLAG))))
        return _Report()

    monkeypatch.setattr("src.ingest.sitemap.discover_sitemap_urls", discover)
    monkeypatch.setattr("src.ingest.crawl.crawl_source", crawl)
    out = _lane_step_crawl(session, object(), SchedulerSettings(crawl_per_pass=3))
    return held, out


def test_the_crawl_step_holds_no_gate_at_any_network_call(session, monkeypatch):
    held, out = _run_step(session, monkeypatch)
    assert out["sources_crawled"] == 3, "the step did not reach every outlet, so the premise of this test did not hold"
    assert len(held) == 6 and {kind for kind, _, _ in held} == {"discover", "crawl"}
    assert [h for h in held if h[2]] == [], f"the single-writer gate was held across a network call: {held}"


def test_each_outlets_crawl_is_stamped_and_committed_before_the_next_outlet(session, monkeypatch):
    """The commit that ends the gate window is the stamp's own: an outlet that was crawled keeps its ``last_crawled_at`` after a rollback."""
    held, out = _run_step(session, monkeypatch)
    session.rollback()
    stamped = session.query(Source).filter(Source.domain.in_(_DOMAINS), Source.last_crawled_at.isnot(None)).count()
    assert stamped == 3


def test_an_outlet_that_fails_after_writing_leaves_no_gate_for_the_next_outlet(session, monkeypatch):
    """The failure path of the same defect: an outlet that wrote (a bulk statement takes the gate) and then raised was swallowed with its
    write still open, so the next outlet fetched with the gate held."""
    held: list[tuple[str, bool]] = []

    def discover(fetcher, host, *, max_urls=0, **kw):
        held.append((host, bool(session.info.get(_SESSION_FLAG))))
        if host == _DOMAINS[0]:
            session.query(Source).filter(Source.domain == host).update({Source.enabled: True}, synchronize_session=False)
            assert session.info.get(_SESSION_FLAG), "the premise: the bulk write took the gate"
            raise RuntimeError("the outlet failed after writing")
        return SitemapDiscoveryReport(source_host=host)

    monkeypatch.setattr("src.ingest.sitemap.discover_sitemap_urls", discover)
    monkeypatch.setattr("src.ingest.crawl.crawl_source", lambda *a, **k: _Report())
    out = _lane_step_crawl(session, object(), SchedulerSettings(crawl_per_pass=3))
    assert out["sources_crawled"] == 2
    assert [h for h in held if h[0] != _DOMAINS[0] and h[1]] == [], f"the gate was carried into a later outlet: {held}"


def _step_that_writes(session, fetcher, settings):
    from src.database.models import Source as _Source

    session.query(_Source).filter(_Source.domain == _DOMAINS[0]).update({_Source.enabled: True}, synchronize_session=False)
    return {"wrote": True}


def test_the_lane_hands_the_next_kind_a_session_that_holds_no_gate(session, monkeypatch):
    from src.scheduler import runner

    seen: list[bool] = []

    def next_step(session_, fetcher, settings):
        seen.append(bool(session_.info.get(_SESSION_FLAG)))
        return {}

    monkeypatch.setattr(runner, "_lane_pending_kinds", lambda settings: ["markets", "calendar"])
    monkeypatch.setattr(runner, "_lane_kind_order", lambda kinds: list(kinds))
    monkeypatch.setattr(runner, "_LANE_STEPS", {"markets": _step_that_writes, "calendar": next_step})
    monkeypatch.setattr(runner, "_activity", lambda *a, **k: None)
    runner.run_housekeeping_lane(session, object(), SchedulerSettings())
    assert seen == [False], "the first kind's write was still open when the second kind started"


def test_a_step_runs_under_its_lane_label_and_the_label_is_given_back(session, monkeypatch):
    from src.database import pool_watch
    from src.scheduler import runner

    inside: list[object] = []

    def step(session_, fetcher, settings):
        session_.execute(__import__("sqlalchemy").text("select 1")).scalar()  # a checkout taken while the step runs
        inside.append(pool_watch.work_label())
        inside.append([r["endpoint"] for r in pool_watch.checked_out()])
        return {}

    monkeypatch.setattr(runner, "_lane_pending_kinds", lambda settings: ["crawl"])
    monkeypatch.setattr(runner, "_lane_kind_order", lambda kinds: list(kinds))
    monkeypatch.setattr(runner, "_LANE_STEPS", {"crawl": step})
    monkeypatch.setattr(runner, "_activity", lambda *a, **k: None)
    assert pool_watch.work_label() is None
    runner.run_housekeeping_lane(session, object(), SchedulerSettings())
    assert inside[0] == "lane:crawl"
    assert "lane:crawl" in inside[1], f"the connection the step took is not listed under its lane: {inside[1]}"
    assert pool_watch.work_label() is None, "the label outlived the step"


def test_a_label_without_a_method_or_scope_is_work_and_a_request_is_not():
    from src.database import pool_watch

    token = pool_watch.set_endpoint("lane:markets")
    try:
        assert pool_watch.work_label() == "lane:markets"
    finally:
        pool_watch.reset_endpoint(token)
    token = pool_watch.set_endpoint("GET UNMATCHED", method="GET", scope={})
    try:
        assert pool_watch.work_label() is None
    finally:
        pool_watch.reset_endpoint(token)


def test_a_long_hold_that_ends_names_the_work_it_was_doing(monkeypatch):
    """``gate_hold``'s closing record carried no route for a hold taken by a worker, so a 2,933 s hold in ``oo-housekeeping-lane`` could not
    be attributed to a step. It now carries the worker's own label."""
    from src.database import pool_watch, writer
    from src.monitoring import storage_events

    recorded: list[dict] = []
    monkeypatch.setattr(storage_events, "end", lambda *a, **k: False)
    monkeypatch.setattr(storage_events, "record", lambda kind, fields, **k: recorded.append({"kind": kind, **fields}))
    token = pool_watch.set_endpoint("lane:crawl")
    try:
        writer._note_hold_end("oo-housekeeping-lane", 2933.0, 1.0)
    finally:
        pool_watch.reset_endpoint(token)
    assert recorded and recorded[0]["kind"] == "gate_hold" and recorded[0]["route"] == "lane:crawl", recorded


def test_a_recorded_sitemap_is_committed_before_the_walk_fetches(session, monkeypatch):
    """``update_source_sitemap_url`` stages a ``SourceMetadata`` row; the walk that follows fetches page after page, so the row is committed
    first rather than riding to the first article the walk happens to store."""
    from types import SimpleNamespace

    from src.ingest.pipeline import IngestResult

    pending_at_ingest: list[int] = []

    def discover(fetcher, host, *, max_urls=0, **kw):
        return SitemapDiscoveryReport(source_host=host, root_sitemap_url=f"https://{host}/sitemap.xml", urls=[f"https://{host}/a"])

    def ingest(session_, source, url, *, fetcher):
        pending_at_ingest.append(len(session_.new) + len(session_.dirty))
        return SimpleNamespace(result=IngestResult.DUPLICATE)

    monkeypatch.setattr("src.ingest.sitemap.discover_sitemap_urls", discover)
    monkeypatch.setattr("src.ingest.pipeline.ingest_url", ingest)
    out = _lane_step_crawl(session, object(), SchedulerSettings(crawl_per_pass=1))
    assert out["sitemap_urls_ingested"] == 1, "the sitemap branch did not run, so the premise of this test did not hold"
    assert pending_at_ingest == [0], "the recorded sitemap was still staged when the walk fetched"
