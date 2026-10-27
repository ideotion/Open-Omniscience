"""
Tests for the archive-backfill ride-along (src/ingest/archive_backfill.py,
2026-07-24 throughput brief, C15 / S-E slice 2).

In-memory SQLite + injected ingest_fn/discover_fn/state_path — no network, no
real fetcher, runs in CI. Covers the brief's own mandatory ⚠ negative-space
properties: the persisted cursor survives a "restart" (never re-fetches),
the per-pass budget is honoured (never fetches more than requested in one
call), a paywalled/thin page fails honestly (no circumvention — it is tallied
as a failure, never silently accepted as "stored"), and the queue/enqueue
mechanics (idempotent, bounded-per-tick, best-effort on a vanished source).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.archive_backfill import (
    advance_backfill,
    enqueue_source,
    load_state,
)
from src.ingest.pipeline import IngestOutcome, IngestResult


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


@pytest.fixture()
def source(db):
    s = Source(name="Example News", domain="example.com", enabled=True)
    db.add(s)
    db.commit()
    return s


@pytest.fixture(autouse=True)
def _clear_kill_switch_around():
    clear_kill_switch()
    yield
    clear_kill_switch()


def _urls(n, prefix="https://example.com/a"):
    return [f"{prefix}{i}" for i in range(n)]


def _discover(urls):
    def _fn(fetcher, source, *, full_history):
        return list(urls)

    return _fn


def _ingest_always(result: IngestResult):
    calls: list[str] = []

    def _fn(session, source, url, *, fetcher):
        calls.append(url)
        return IngestOutcome(url=url, result=result, article_id=None, detail=None)

    _fn.calls = calls  # type: ignore[attr-defined]
    return _fn


# --------------------------------------------------------------------------- #
# enqueue_source: idempotent, bounded, never a duplicate.
# --------------------------------------------------------------------------- #


def test_enqueue_is_idempotent(tmp_path):
    sp = tmp_path / "state.json"
    r1 = enqueue_source(7, state_path=sp)
    assert r1["enqueued"] is True
    r2 = enqueue_source(7, state_path=sp)
    assert r2["enqueued"] is False
    state = load_state(sp)
    assert len(state["queue"]) == 1


def test_enqueue_skips_an_already_done_source(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps({"done_sources": [7]}), "utf-8")
    r = enqueue_source(7, state_path=sp)
    assert r["enqueued"] is False
    assert "already backfilled" in r["reason"]


def test_enqueue_skips_the_currently_active_source(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps({"active": {"source_id": 7}}), "utf-8")
    r = enqueue_source(7, state_path=sp)
    assert r["enqueued"] is False


# --------------------------------------------------------------------------- #
# advance_backfill: the airplane-mode / off-switch skips.
# --------------------------------------------------------------------------- #


def test_zero_budget_is_disabled(db, tmp_path):
    out = advance_backfill(db, fetcher=None, per_pass=0, state_path=tmp_path / "s.json")
    assert out == {"enabled": False}


def test_airplane_mode_skips_honestly_never_an_error(db, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(1, state_path=sp)
    activate_kill_switch()
    try:
        out = advance_backfill(db, fetcher=None, per_pass=5, state_path=sp)
    finally:
        clear_kill_switch()
    assert out == {"enabled": True, "skipped": "airplane mode engaged"}
    # nothing was consumed from the queue while skipped
    state = load_state(sp)
    assert len(state["queue"]) == 1


def test_empty_queue_skips_honestly(db, tmp_path):
    out = advance_backfill(db, fetcher=None, per_pass=5, state_path=tmp_path / "s.json")
    assert out == {"enabled": True, "skipped": "queue is empty"}


# --------------------------------------------------------------------------- #
# The mandatory ⚠ property: the per-pass budget is honoured — never more than
# ``per_pass`` URLs fetched in one call, however large the source's history.
# --------------------------------------------------------------------------- #


def test_per_pass_budget_is_honoured(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)
    urls = _urls(37)
    discover = _discover(urls)
    ingest = _ingest_always(IngestResult.STORED)

    # Tick 1: enumeration only (its own bounded tick — never combined with a fetch).
    out1 = advance_backfill(
        db, fetcher=object(), per_pass=5, state_path=sp,
        ingest_fn=ingest, discover_fn=discover,
    )
    assert out1["enumerated"] is True
    assert out1["urls_found"] == 37
    assert ingest.calls == []  # no fetch happened on the enumeration tick

    # Tick 2: fetches exactly per_pass=5, never the whole 37-url backlog.
    out2 = advance_backfill(
        db, fetcher=object(), per_pass=5, state_path=sp,
        ingest_fn=ingest, discover_fn=discover,
    )
    assert out2["attempted"] == 5
    assert len(ingest.calls) == 5
    assert out2["done"] is False
    assert out2["cursor"] == 5


# --------------------------------------------------------------------------- #
# The mandatory ⚠ property: the cursor survives a "restart" — a paused
# backfill continues from where it left off, never re-fetching an already-
# attempted URL.
# --------------------------------------------------------------------------- #


def test_cursor_survives_a_restart_never_refetches(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)
    urls = _urls(12)
    discover = _discover(urls)
    ingest = _ingest_always(IngestResult.STORED)

    advance_backfill(db, fetcher=object(), per_pass=4, state_path=sp,
                      ingest_fn=ingest, discover_fn=discover)  # enumerate
    advance_backfill(db, fetcher=object(), per_pass=4, state_path=sp,
                      ingest_fn=ingest, discover_fn=discover)  # fetch 0..3
    assert ingest.calls == urls[0:4]

    # Simulate a process restart: a FRESH call, reading the SAME persisted
    # state file, must resume at the cursor rather than re-fetching urls[0:4].
    ingest2 = _ingest_always(IngestResult.STORED)
    out = advance_backfill(db, fetcher=object(), per_pass=4, state_path=sp,
                            ingest_fn=ingest2, discover_fn=discover)
    assert ingest2.calls == urls[4:8]
    assert out["cursor"] == 8

    # And a third "restart" finishes the remaining 4, marking done.
    ingest3 = _ingest_always(IngestResult.STORED)
    out3 = advance_backfill(db, fetcher=object(), per_pass=4, state_path=sp,
                             ingest_fn=ingest3, discover_fn=discover)
    assert ingest3.calls == urls[8:12]
    assert out3["done"] is True
    state = load_state(sp)
    assert state["active"] is None
    assert source.id in state["done_sources"]


# --------------------------------------------------------------------------- #
# The mandatory ⚠ property: a paywalled/thin page fails HONESTLY — it is
# tallied as a failure, never silently accepted as "stored" (no circumvention).
# --------------------------------------------------------------------------- #


def test_paywalled_url_is_tallied_honestly_never_fabricated_as_stored(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)
    urls = _urls(3)
    discover = _discover(urls)
    ingest = _ingest_always(IngestResult.EXTRACT_FAILED)  # a paywalled/thin page

    advance_backfill(db, fetcher=object(), per_pass=3, state_path=sp,
                      ingest_fn=ingest, discover_fn=discover)  # enumerate
    out = advance_backfill(db, fetcher=object(), per_pass=3, state_path=sp,
                            ingest_fn=ingest, discover_fn=discover)  # fetch
    assert out["tally"] == {IngestResult.EXTRACT_FAILED.value: 3}
    assert IngestResult.STORED.value not in out["tally"]


def test_a_url_raising_is_tallied_as_error_and_the_tick_continues(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)
    urls = _urls(3)
    discover = _discover(urls)

    def _raising_ingest(session, source, url, *, fetcher):
        raise RuntimeError("network hiccup")

    advance_backfill(db, fetcher=object(), per_pass=3, state_path=sp,
                      ingest_fn=_raising_ingest, discover_fn=discover)  # enumerate
    out = advance_backfill(db, fetcher=object(), per_pass=3, state_path=sp,
                            ingest_fn=_raising_ingest, discover_fn=discover)
    assert out["tally"] == {"error": 3}
    assert out["attempted"] == 3


def test_a_dirty_session_from_one_failed_url_does_not_cascade_to_the_next(db, source, tmp_path):
    """Regression for the 2026-07-25 (transversal audit 09) missing-rollback
    bug: a failure that leaves the session mid-transaction (a real failed
    flush -- not just any Python exception; store_fetched only catches
    IntegrityError itself, so e.g. an OperationalError from a concurrent
    writer propagates straight through) must not poison every REMAINING url
    in the same tick. Empirically confirmed the raw SQLAlchemy behaviour
    first: a query issued on a session with a pending-rollback transaction
    raises PendingRollbackError until session.rollback() is called."""
    from src.database.models import Article

    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)
    urls = _urls(2)
    discover = _discover(urls)
    calls: list[str] = []

    def _ingest(session, src_, url, *, fetcher):
        calls.append(url)
        if len(calls) == 1:
            session.add(Article(
                url=url, canonical_url=url, source_id=src_.id, title="t",
                content="c", hash="dup-hash",
            ))
            session.flush()
            session.add(Article(
                url=url + "-dup", canonical_url=url + "-dup", source_id=src_.id,
                title="t", content="c", hash="dup-hash",  # same hash -> IntegrityError
            ))
            session.flush()  # raises -- propagates straight out, uncaught here
            raise AssertionError("unreachable")  # pragma: no cover
        # If the fix's session.rollback() did NOT run after the first url's
        # failure, this raises PendingRollbackError instead of succeeding.
        n = session.query(Article).count()
        return IngestOutcome(url, IngestResult.STORED, article_id=n)

    advance_backfill(db, fetcher=object(), per_pass=2, state_path=sp,
                      ingest_fn=_ingest, discover_fn=discover)  # enumerate
    out = advance_backfill(db, fetcher=object(), per_pass=2, state_path=sp,
                            ingest_fn=_ingest, discover_fn=discover)
    assert out["tally"].get("error") == 1
    assert out["tally"].get(IngestResult.STORED.value) == 1
    assert out["attempted"] == 2


# --------------------------------------------------------------------------- #
# A source with no sitemap URLs is marked done immediately (never spins on an
# empty history); a vanished source is skipped, never crashing the ride-along.
# --------------------------------------------------------------------------- #


def test_empty_sitemap_marks_the_source_done_immediately(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)
    out = advance_backfill(db, fetcher=object(), per_pass=5, state_path=sp,
                            ingest_fn=_ingest_always(IngestResult.STORED),
                            discover_fn=_discover([]))
    assert out == {"enabled": True, "source_id": source.id, "urls_found": 0, "done": True}
    state = load_state(sp)
    assert source.id in state["done_sources"]
    assert state.get("active") in (None, {})


def test_a_vanished_queued_source_is_skipped_never_crashes(db, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(999999, state_path=sp)  # no such Source row
    out = advance_backfill(db, fetcher=object(), per_pass=5, state_path=sp)
    assert out["skipped"] == "source no longer exists"
    state = load_state(sp)
    assert state["queue"] == []


def test_enumeration_failure_does_not_abort_the_queue(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)

    def _raising_discover(fetcher, source, *, full_history):
        raise RuntimeError("sitemap fetch failed")

    out = advance_backfill(db, fetcher=object(), per_pass=5, state_path=sp,
                            discover_fn=_raising_discover)
    assert out["urls_found"] == 0
    assert out["done"] is True


# --------------------------------------------------------------------------- #
# full_history is an explicit, separate per-source consent — never implied by
# the default (bounded) auto-enqueue path.
# --------------------------------------------------------------------------- #


def test_full_history_flag_is_threaded_to_the_discover_call(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, full_history=True, state_path=sp)
    seen = {}

    def _discover_recording(fetcher, source, *, full_history):
        seen["full_history"] = full_history
        return _urls(2)

    advance_backfill(db, fetcher=object(), per_pass=5, state_path=sp,
                      discover_fn=_discover_recording)
    assert seen["full_history"] is True


def test_default_enqueue_is_bounded_not_full_history(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)  # full_history defaults False
    state = load_state(sp)
    assert state["queue"][0]["full_history"] is False


def test_a_sibling_feed_of_an_already_backfilled_outlet_is_not_backfilled_again(db, source, tmp_path):
    """Row J, D1: a sitemap is the site's. Two feeds of one domain read the same pages once, not twice."""
    twin = Source(name="Example News Arabic", domain="example.com", rss_url="https://example.com/ar.xml", enabled=True)
    other = Source(name="Other", domain="other.example", enabled=True)
    db.add_all([twin, other])
    db.commit()
    sp = tmp_path / "s.json"
    seen: list[int] = []

    def discover(fetcher, src, *, full_history):
        seen.append(src.id)
        return _urls(1)

    for sid in (source.id, twin.id, other.id):
        enqueue_source(sid, state_path=sp)
    for _ in range(8):
        advance_backfill(db, fetcher=object(), per_pass=5, state_path=sp,
                         ingest_fn=_ingest_always(IngestResult.STORED), discover_fn=discover)
    assert seen == [source.id, other.id]  # the sibling never enumerated a second time
    assert twin.id in load_state(sp)["done_sources"]


def test_a_failed_enumeration_on_one_feed_leaves_its_sibling_its_own_attempt(db, source, tmp_path):
    """Row J, D1 (Opus read, finding 2): ``done_sources`` also holds a failed enumeration, so it must not stand for
    "the outlet's archive was backfilled": a transient error on one feed would otherwise mark its siblings done unread."""
    twin = Source(name="Example News Arabic", domain="example.com", rss_url="https://example.com/ar.xml", enabled=True)
    db.add(twin)
    db.commit()
    sp = tmp_path / "s.json"
    seen: list[int] = []

    def discover(fetcher, src, *, full_history):
        seen.append(src.id)
        if src.id == source.id:
            raise ConnectionError("transient")
        return _urls(2)

    for sid in (source.id, twin.id):
        enqueue_source(sid, state_path=sp)
    for _ in range(8):
        advance_backfill(db, fetcher=object(), per_pass=5, state_path=sp,
                         ingest_fn=_ingest_always(IngestResult.STORED), discover_fn=discover)
    assert seen == [source.id, twin.id]  # the sibling got its attempt
    assert load_state(sp)["completed_outlets"] == ["example.com"]  # and its run to the end is what marks the outlet


# --------------------------------------------------------------------------- #
# A Stop is the person's setting, not the site's (R325 item 1 sweep, D3). The tick's own check at its head
# covers only a Stop pressed before it: a Stop inside the enumeration (up to two robots reads and up to 5 sitemaps, 50 with
# the full history) or inside one URL's flight reaches the recorder as an ordinary failure, and was written down as one --
# an empty history (`done_sources`, which `enqueue_source` never re-queues) or a URL passed over for good. The tick says so
# the way every other recorder does (R296/R313): `skipped_offline: 1`, present ONLY when the switch held something back.
# --------------------------------------------------------------------------- #


def _tick(db, sp, *, discover=None, ingest=None, fetcher=None):
    return advance_backfill(db, fetcher=fetcher if fetcher is not None else object(), per_pass=5, state_path=sp,
                            ingest_fn=ingest or _ingest_always(IngestResult.STORED),
                            discover_fn=discover or _discover(_urls(3)))


def _active_after_enumeration(db, source, sp, urls=3):
    enqueue_source(source.id, state_path=sp)
    _tick(db, sp, discover=_discover(_urls(urls)))
    assert load_state(sp)["active"]["cursor"] == 0


def test_a_stop_inside_the_enumeration_is_not_recorded_as_an_empty_history(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)

    def cut(fetcher, src, *, full_history):
        activate_kill_switch()  # Stop pressed after the tick's own check, before the sitemaps answered
        return []

    out = _tick(db, sp, discover=cut)
    assert out == {"enabled": True, "source_id": source.id, "skipped_offline": 1}
    state = load_state(sp)
    assert state["queue"] == [{"source_id": source.id, "full_history": False}], "the entry is still at the head of the queue"
    assert source.id not in state.get("done_sources", [])
    clear_kill_switch()
    # the Stop cleared, the next tick enumerates again and the source gets its backfill
    out = _tick(db, sp, discover=_discover(_urls(2)))
    assert out["urls_found"] == 2 and load_state(sp)["active"]["source_id"] == source.id
    assert "skipped_offline" not in out


def test_a_stop_followed_by_an_enumeration_that_raised_is_not_recorded_as_an_empty_history(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)

    def cut_and_raise(fetcher, src, *, full_history):
        activate_kill_switch()
        raise ConnectionError("airplane mode is engaged")

    out = _tick(db, sp, discover=cut_and_raise)
    assert out["skipped_offline"] == 1
    state = load_state(sp)
    assert len(state["queue"]) == 1 and source.id not in state.get("done_sources", [])


def test_a_part_read_enumeration_under_a_stop_is_not_walked_as_the_whole_archive(db, source, tmp_path):
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)

    def cut_after_two(fetcher, src, *, full_history):
        urls = _urls(2)  # the first sitemap answered, the rest were refused
        activate_kill_switch()
        return urls

    out = _tick(db, sp, discover=cut_after_two)
    assert out["skipped_offline"] == 1 and "urls_found" not in out
    state = load_state(sp)
    assert not state.get("active") and len(state["queue"]) == 1


def test_an_honest_empty_enumeration_is_still_recorded_as_done(db, source, tmp_path):
    """The control for the new key: with the switch never engaged an empty answer IS the site's, ends the source's backfill and
    says nothing about the switch (the strict form of the same case is ``test_empty_sitemap_marks_the_source_done_immediately``)."""
    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)
    out = _tick(db, sp, discover=_discover([]))
    assert out["done"] is True and source.id in load_state(sp)["done_sources"] and "skipped_offline" not in out


def test_a_url_cut_by_a_stop_in_flight_is_not_passed_over(db, source, tmp_path):
    sp = tmp_path / "s.json"
    _active_after_enumeration(db, source, sp)

    def cut(session, src, url, *, fetcher):
        activate_kill_switch()
        return IngestOutcome(url=url, result=IngestResult.FETCH_FAILED, article_id=None, detail="request error")

    out = _tick(db, sp, ingest=cut)
    assert out["attempted"] == 0 and out["cursor"] == 0 and out["tally"] == {} and out["skipped_offline"] == 1
    active = load_state(sp)["active"]
    assert active["cursor"] == 0 and active["tally"] == {}, "the cursor stays on the cut URL"
    clear_kill_switch()
    served = _ingest_always(IngestResult.STORED)
    out = _tick(db, sp, ingest=served)
    assert served.calls[0] == _urls(3)[0], "the next tick asks for the cut URL again"
    assert "skipped_offline" not in out


def test_a_url_that_raised_under_a_stop_is_not_passed_over_either(db, source, tmp_path):
    sp = tmp_path / "s.json"
    _active_after_enumeration(db, source, sp)

    def cut(session, src, url, *, fetcher):
        activate_kill_switch()
        raise OSError("airplane mode is engaged: refusing a network connection")

    out = _tick(db, sp, ingest=cut)
    assert out["attempted"] == 0 and out["tally"] == {} and out["skipped_offline"] == 1
    assert load_state(sp)["active"]["cursor"] == 0


def test_a_url_that_finished_before_the_stop_keeps_its_place(db, source, tmp_path):
    sp = tmp_path / "s.json"
    _active_after_enumeration(db, source, sp)

    def stored_then_stop(session, src, url, *, fetcher):
        activate_kill_switch()  # Stop pressed just after this URL was stored
        return IngestOutcome(url=url, result=IngestResult.STORED, article_id=None, detail=None)

    out = _tick(db, sp, ingest=stored_then_stop)
    assert out["attempted"] == 1 and out["cursor"] == 1 and out["tally"] == {"stored": 1}
    assert out["skipped_offline"] == 1, "the two URLs after it were held back by the switch, and the tick says so"


def test_a_real_failure_with_the_switch_never_engaged_is_still_passed_over(db, source, tmp_path):
    """The control: a page that really failed is the page's, tallied and passed over (the backfill is best-effort)."""
    sp = tmp_path / "s.json"
    _active_after_enumeration(db, source, sp)
    out = _tick(db, sp, ingest=_ingest_always(IngestResult.FETCH_FAILED))
    assert out["attempted"] == 3 and out["cursor"] == 3 and out["tally"] == {"fetch_failed": 3} and out["done"] is True
    assert "skipped_offline" not in out


class _Resp:
    def __init__(self, status=200, body=b"", ctype="text/html"):
        self.status_code, self.headers, self.content = status, {"Content-Type": ctype}, body
        self.text, self.encoding = body.decode("utf-8", "replace"), "utf-8"

    def iter_content(self, chunk_size=16384):
        yield self.content

    def close(self):
        pass


def _real_fetcher(tmp_path, get, monkeypatch):
    """The PRODUCTION fetcher over a scripted session: the robots read with its kill-switch branch, the refusals at the head of
    ``declared_sitemaps()`` and ``fetch()`` and the robots cache run unchanged. ``_guard_target`` is replaced, and a cut in the
    first request never reaches the retry loop (measured: ``session.get`` is called once and nothing sleeps)."""
    from src.safety.fetcher import make_fetcher

    monkeypatch.setenv("OO_FETCH_MIN_INTERVAL", "0")
    f = make_fetcher(retry_backoff_s=0, robots_cache_path=tmp_path / "robots.json")
    f._guard_target = lambda *a, **k: None  # the host is never resolved; the switch check stays the first line of fetch()
    f.session.get = get
    return f


def test_a_stop_in_the_flight_of_the_REAL_enumeration_is_not_recorded_as_an_empty_history(db, source, tmp_path, monkeypatch):
    import requests

    def get(url, **_kw):
        activate_kill_switch()  # the Stop lands in the first request; the socket guard would cut it just so
        raise requests.exceptions.ConnectionError("Failed to establish a new connection: airplane mode is engaged")

    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)
    out = advance_backfill(db, _real_fetcher(tmp_path, get, monkeypatch), per_pass=5, state_path=sp)
    assert out == {"enabled": True, "source_id": source.id, "skipped_offline": 1}
    state = load_state(sp)
    assert len(state["queue"]) == 1 and source.id not in state.get("done_sources", [])


def test_an_honest_empty_enumeration_by_the_REAL_fetcher_is_still_done(db, source, tmp_path, monkeypatch):
    def get(url, **_kw):
        if url.endswith("/robots.txt"):
            return _Resp(200, b"User-agent: *\nAllow: /\n", "text/plain")
        return _Resp(404)  # no sitemap anywhere: the site's own answer

    sp = tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)
    out = advance_backfill(db, _real_fetcher(tmp_path, get, monkeypatch), per_pass=5, state_path=sp)
    assert out["done"] is True and source.id in load_state(sp)["done_sources"] and "skipped_offline" not in out


@pytest.mark.parametrize("cut_at", ["robots", "page"])
def test_a_url_cut_in_the_REAL_ingest_is_not_passed_over(db, source, tmp_path, monkeypatch, cut_at):
    """The URL case through ``ingest_url`` and the production fetcher: the Stop reaches the recorder as ``fetch_failed`` whether it
    cut the robots read or the page itself -- the outcome set ``{fetch_failed, error}`` the tick holds back on is an assumption
    about the fetcher, and this is what fails if the robots path ever raises ``RobotsUnavailable`` under the switch again."""
    import requests

    def get(url, **_kw):
        if (cut_at == "robots") == url.endswith("/robots.txt"):
            activate_kill_switch()
            raise requests.exceptions.ConnectionError("Failed to establish a new connection: airplane mode is engaged")
        return _Resp(200, b"User-agent: *\nAllow: /\n", "text/plain")

    sp = tmp_path / "s.json"
    _active_after_enumeration(db, source, sp)
    out = advance_backfill(db, _real_fetcher(tmp_path, get, monkeypatch), per_pass=5, state_path=sp)
    assert out["attempted"] == 0 and out["tally"] == {} and out["skipped_offline"] == 1
    assert load_state(sp)["active"]["cursor"] == 0
