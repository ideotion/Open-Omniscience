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

from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.archive_backfill import (
    advance_backfill,
    enqueue_source,
    load_state,
)
from src.ingest.pipeline import IngestOutcome, IngestResult
from src.database.models import Base, Source


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
