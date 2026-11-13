"""R666 (OPEN_QUEUE item 32): ONE briefing producer can no longer hold the write-ahead log's read mark for hours.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT. Home's refresh ran ``run_all_bounded(deadline=None)``: the budget was checked only BETWEEN producers and no producer
ran under a ``statement_deadline``, so one producer could read for as long as it liked. An RC2 bundle (28 Oct 2026) showed the
briefing thread as the oldest reader for 5,720 s while the log grew to 80.8 GB; a reader pins the checkpoint, so the disk fills.

What these tests pin: each producer on Home's refresh runs under its own bound; one stopped by it (or that ran past it anyway)
is named and its cards are left out; the loop goes on; the stopped reader RELEASES the log so a checkpoint completes afterwards
(the point of the fix, proven on a real WAL-mode file); the log latch stops the loop between producers; Home says which kinds
of card are missing and keeps saying it while the shown feed lacks them; a stopped producer runs last on the next refresh.
"""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import src.api.insights as ins
from src.briefing import registry, service
from src.briefing.card import Card
from src.database import maintenance as M


def _card(name: str) -> Card:
    return Card(
        type=name, key=name, title=name, summary="s", bucket="investigate", n=1,
        method="m", caveat="c",
    )


def _set_registry(monkeypatch, entries):
    monkeypatch.setattr(registry, "_REGISTRY", list(entries))
    monkeypatch.setattr(registry, "_disabled_names", lambda: set())


# --------------------------------------------------------------------------- the bound, in the loop
def test_the_bound_is_two_checkpoint_cycles():
    assert registry.PRODUCER_DEADLINE_CYCLES == 2
    assert registry.PRODUCER_DEADLINE_S == 2 * registry._SLOW_PRODUCER_S == 600.0


def test_a_producer_stopped_by_its_deadline_is_named_and_the_loop_goes_on(monkeypatch):
    ran: list[str] = []

    def _ok(name):
        def _p(_s):
            ran.append(name)
            return [_card(name)]
        return _p

    def _slow(_s):
        ran.append("slow")
        raise M.StatementTimeout("statement exceeded the 600s deadline and was aborted")

    _set_registry(monkeypatch, [("a", _ok("a")), ("slow", _slow), ("b", _ok("b"))])
    cards, stats = registry.run_all_bounded(object(), producer_deadline_s=600.0)
    assert ran == ["a", "slow", "b"]
    assert [c.type for c in cards] == ["a", "b"]
    assert [p["name"] for p in stats["stopped_producers"]] == ["slow"]
    assert stats["truncated"] is False


def test_a_producer_that_ran_past_its_bound_without_raising_is_stopped_too(monkeypatch):
    """A one-opcode statement or a producer that swallowed the timeout is not interruptible: it is still named, and the cards
    only a run past the bound could make are left out."""
    def _overran(_s):
        time.sleep(0.15)
        return [_card("overran")]

    _set_registry(monkeypatch, [("overran", _overran), ("b", lambda _s: [_card("b")])])
    cards, stats = registry.run_all_bounded(object(), producer_deadline_s=0.05)
    assert [c.type for c in cards] == ["b"]
    assert [p["name"] for p in stats["stopped_producers"]] == ["overran"]


def test_no_bound_and_no_stopped_list_unless_the_caller_asks(monkeypatch):
    def _slow(_s):
        time.sleep(0.05)
        return [_card("slow")]

    _set_registry(monkeypatch, [("slow", _slow)])
    cards, stats = registry.run_all_bounded(object())
    assert [c.type for c in cards] == ["slow"]
    assert "stopped_producers" not in stats


def test_a_memory_stop_inside_a_producer_stops_the_pass_as_memory_short(monkeypatch):
    ran: list[str] = []

    def _short(_s):
        ran.append("short")
        raise M.MemoryShort("memory stop")

    _set_registry(monkeypatch, [("short", _short), ("b", lambda _s: ran.append("b") or [])])
    _cards, stats = registry.run_all_bounded(object(), producer_deadline_s=600.0, memory_stop=True)
    assert ran == ["short"]
    assert stats["truncated_reason"] == "memory_short"
    assert "stopped_producers" not in stats


def test_the_log_latch_stops_the_loop_between_producers(monkeypatch):
    ran: list[str] = []
    pinned = {"now": False}

    def _p(name):
        def _f(_s):
            ran.append(name)
            if name == "a":
                pinned["now"] = True
            return []
        return _f

    _set_registry(monkeypatch, [("a", _p("a")), ("b", _p("b"))])
    monkeypatch.setattr(registry, "_log_pin_in_force", lambda: pinned["now"])
    _cards, stats = registry.run_all_bounded(object(), log_pin_stop=True)
    assert ran == ["a"]
    assert stats["truncated_reason"] == "wal_pinned"
    # And not asked unless the caller wants it.
    ran.clear()
    pinned["now"] = False
    _cards, stats = registry.run_all_bounded(object())
    assert ran == ["a", "b"] and stats["truncated"] is False


def test_run_last_changes_the_order_but_not_the_cards(monkeypatch):
    ran: list[str] = []

    def _p(name):
        def _f(_s):
            ran.append(name)
            return [_card(name)]
        return _f

    _set_registry(monkeypatch, [(n, _p(n)) for n in ("a", "b", "c")])
    cards, _stats = registry.run_all_bounded(object(), run_last=frozenset({"a"}))
    assert ran == ["b", "c", "a"]
    assert [c.type for c in cards] == ["a", "b", "c"], "cards keep registration order (the dedup belt keeps the same one)"


def test_an_enclosing_deadline_is_not_shadowed_by_the_per_producer_one(monkeypatch):
    """Under a diagnostics member's deadline the per-producer bound is not armed: the enclosing one bounds the loop, and a
    producer stopped by IT must not be reported as stopped by its own bound."""
    armed: list[float] = []
    real = M.statement_deadline

    def _spy(session, seconds=None):
        armed.append(seconds)
        return real(session, seconds=seconds)

    monkeypatch.setattr(M, "statement_deadline", _spy)

    class _S:
        info = {M._DEADLINE_KEY: time.monotonic() + 300}

    _set_registry(monkeypatch, [("a", lambda _s: [])])
    registry.run_all_bounded(_S(), producer_deadline_s=600.0)
    assert armed == []
    _S.info = {}
    registry.run_all_bounded(_S(), producer_deadline_s=600.0)
    assert armed == [600.0]


# --------------------------------------------------------------------------- the point: the log can be checkpointed again
def _wal_engine(path):
    eng = sa.create_engine(f"sqlite:///{path}")
    with eng.begin() as c:
        c.exec_driver_sql("PRAGMA journal_mode=WAL")
        c.exec_driver_sql("CREATE TABLE t (x INTEGER)")
        c.exec_driver_sql("INSERT INTO t VALUES (1)")
    return eng


def test_a_stopped_producer_releases_its_reader_and_the_log_checkpoints(monkeypatch, tmp_path):
    """Red without the bound: the producer's read would run for as long as the recursive count takes (far beyond this test),
    pinning every frame written meanwhile. With it, the read is interrupted at the bound, the transaction ends, and a TRUNCATE
    checkpoint taken right after completes with nothing busy and nothing left in the log."""
    db = tmp_path / "pin.db"
    eng = _wal_engine(db)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(M, "_read_memory_floor_mb", lambda: None)
    during: dict = {}

    def _writer_while_pinned():
        time.sleep(0.4)
        w = sqlite3.connect(db, timeout=5)
        w.execute("INSERT INTO t SELECT x + 1 FROM t")
        w.commit()
        during["ckpt"] = w.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        w.close()

    def _runaway(session):
        threading.Thread(target=_writer_while_pinned, daemon=True).start()
        # Reads t first, so the statement holds a read mark for as long as it runs: the shape of a long producer read.
        session.execute(sa.text(
            "WITH RECURSIVE c(i) AS (SELECT (SELECT max(x) FROM t) UNION ALL SELECT i + 1 FROM c) "
            "SELECT count(*) FROM c WHERE i < 0"
        )).all()
        return [_card("runaway")]

    _set_registry(monkeypatch, [("runaway", _runaway)])
    with Session() as s:
        started = time.monotonic()
        cards, stats = registry.run_all_bounded(s, producer_deadline_s=1.5)
        took = time.monotonic() - started
    assert took < 30, f"the producer was not stopped ({took:.1f} s)"
    assert cards == []
    assert [p["name"] for p in stats["stopped_producers"]] == ["runaway"]
    # While the producer read, the frames written after its snapshot could not all be checkpointed: the pin was real.
    _busy, log, done = during["ckpt"]
    assert log > 0 and done < log, during
    # After the stop: nothing holds the log back.
    c = sqlite3.connect(db, timeout=5)
    busy, log, done = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    c.close()
    eng.dispose()
    assert busy == 0 and log == 0 and done == 0, (busy, log, done)


# --------------------------------------------------------------------------- Home: the cache, the view, the next pass
@pytest.fixture
def home(monkeypatch, tmp_path):
    path = tmp_path / "briefing_cache.json"
    monkeypatch.setattr(service, "_cache_path", lambda: path)
    monkeypatch.setattr(service, "_article_count", lambda _s: 0)
    monkeypatch.setattr(service, "_stoplist_fingerprint", lambda: None)
    monkeypatch.setattr(ins, "warm_cache", lambda _s: {"warmed": []})
    monkeypatch.setattr(service, "dismissed_ids", lambda: set())
    monkeypatch.setattr(registry, "_disabled_names", lambda: set())
    return path


def test_home_asks_for_the_bound_and_the_latch(monkeypatch, home):
    seen = {}

    def _spy(*a, **k):
        seen.update(k)
        return [], {"truncated": False}

    monkeypatch.setattr(service, "run_all_bounded", _spy)
    service.refresh_briefing(object())
    assert seen["producer_deadline_s"] == registry.PRODUCER_DEADLINE_S
    assert seen["log_pin_stop"] is True


def test_home_names_the_missing_kinds_and_runs_them_last_next_time(monkeypatch, home):
    order: list[list[str]] = []

    def _spy(*a, **k):
        order.append(sorted(k.get("run_last") or []))
        return [_card("lonely_signal")], {
            "truncated": False,
            "stopped_producers": [{"name": "space_time_convergence", "seconds": 600.4}, {"name": "<b>x</b>", "seconds": 1}],
        }

    monkeypatch.setattr(service, "run_all_bounded", _spy)
    service.refresh_briefing(object())
    view = service.get_briefing(object())
    assert view["stopped_producers"] == ["Converging on one place"], "a name the catalog does not know is never echoed"
    assert view["producer_deadline_min"] == 10
    assert "incomplete_reason" not in view, "a producer stop must not start the ten-minute marker repair loop"
    assert service._marker_wants_refresh(service._read_cache()) is False
    service.refresh_briefing(object())
    assert order == [[], ["<b>x</b>", "space_time_convergence"]]


def test_the_line_stays_while_a_kept_feed_still_lacks_the_cards(monkeypatch, home):
    """The caveat lasts for as long as the SHOWN feed lacks the cards: a later refresh that keeps the previous feed (a memory
    or log stop) keeps its list too; a complete refresh replaces both."""
    results = [
        ([_card("a")], {"truncated": False, "stopped_producers": [{"name": "space_time_convergence", "seconds": 601}]}),
        ([], {"truncated": True, "truncated_reason": "wal_pinned"}),
        ([_card("a")], {"truncated": False}),
    ]
    monkeypatch.setattr(service, "run_all_bounded", lambda *a, **k: results.pop(0))
    service.refresh_briefing(object())
    service.refresh_briefing(object())
    view = service.get_briefing(object())
    assert view["kept_reason"] == "wal_pinned"
    assert view["stopped_producers"] == ["Converging on one place"]
    service.refresh_briefing(object())
    view = service.get_briefing(object())
    assert "stopped_producers" not in view and "kept_reason" not in view


def test_a_log_stop_with_no_previous_feed_writes_what_it_has_and_says_why(monkeypatch, home):
    monkeypatch.setattr(
        service, "run_all_bounded",
        lambda *a, **k: ([_card("a")], {"truncated": True, "truncated_reason": "wal_pinned"}),
    )
    warmed: list[int] = []
    monkeypatch.setattr(ins, "warm_cache", lambda _s: warmed.append(1))
    service.refresh_briefing(object())
    view = service.get_briefing(object())
    assert view["incomplete_reason"] == "wal_pinned"
    assert warmed == [], "no cache warm-up while the log is pinned: it reads more of the corpus"
