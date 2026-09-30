"""Diagnostics rank 4 (2026-09-30): the briefing and its cache warm-up stop when memory is short.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT. ``warm_cache`` computed the whole-corpus trending views OUTSIDE the statement
deadline and memory stop that every endpoint read runs under, and ``run_all_bounded`` (the
briefing's producer loop) had no memory condition at all -- both run at the tail of each
collection pass, which is when a small machine has the least memory left.

Memory is faked by patching the two readings the deadlined read itself uses
(``maintenance._available_mb`` / ``_read_memory_floor_mb``), so the tests exercise the
shipped comparison rather than a re-typed copy of it.
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import src.api.insights as ins
from src.briefing import registry, service
from src.database import maintenance as M
from src.utils.cache import SimpleCache


@pytest.fixture
def memory(monkeypatch):
    """Set the (available, floor) MB the stop sees; ``None`` for a reading that is absent."""
    def _set(avail, floor=256.0):
        monkeypatch.setattr(M, "_available_mb", lambda: avail)
        monkeypatch.setattr(M, "_read_memory_floor_mb", lambda: floor)
    return _set


def _producers(monkeypatch, n=5, *, on_run=None):
    ran: list[str] = []

    def _mk(name):
        def _p(_session):
            ran.append(name)
            if on_run:
                on_run(name)
            return []
        return _p

    monkeypatch.setattr(registry, "_REGISTRY", [(f"p{i}", _mk(f"p{i}")) for i in range(n)])
    return ran


# --------------------------------------------------------------------------- run_all_bounded
def test_the_producer_loop_does_not_start_a_producer_while_memory_is_short(monkeypatch, memory):
    ran = _producers(monkeypatch)
    memory(100.0)
    _cards, stats = registry.run_all_bounded(object(), memory_stop=True)
    assert ran == [], "a producer started with the machine at its memory floor"
    assert stats["truncated"] is True
    assert stats["truncated_reason"] == "memory_short"
    assert stats["producers_run"] == 0 and stats["producers_total"] == 5


def test_the_loop_stops_between_producers_when_memory_falls_mid_run(monkeypatch, memory):
    memory(4000.0)

    def _after_two(name):
        if name == "p1":
            memory(90.0)

    ran = _producers(monkeypatch, on_run=_after_two)
    _cards, stats = registry.run_all_bounded(object(), memory_stop=True)
    assert ran == ["p0", "p1"], ran
    assert stats["truncated_reason"] == "memory_short"
    assert stats["producers_run"] == 2


@pytest.mark.parametrize(
    "avail,floor",
    [
        (4000.0, 256.0),   # plenty
        (256.0001, 256.0),  # just above the line
        (None, 256.0),     # a machine that cannot report its memory is never "short"
        (100.0, None),     # the stop is off (OO_READ_MEMORY_STOP=0 or no guard)
    ],
)
def test_the_loop_runs_everything_when_memory_is_fine_or_unmeasurable(monkeypatch, memory, avail, floor):
    ran = _producers(monkeypatch)
    memory(avail, floor)
    _cards, stats = registry.run_all_bounded(object(), memory_stop=True)
    assert len(ran) == 5
    assert stats["truncated"] is False
    assert "truncated_reason" not in stats


def test_memory_is_not_watched_unless_the_caller_asks(monkeypatch, memory):
    """Bulletin, leads-quality and the card audit print their own words for a short run and
    know only a spent time budget, so they do not get a memory stop they would mislabel."""
    ran = _producers(monkeypatch)
    memory(100.0)
    _cards, stats = registry.run_all_bounded(object())
    assert len(ran) == 5 and stats["truncated"] is False


def test_the_home_refresh_asks_for_the_memory_stop(monkeypatch, tmp_path):
    seen = {}

    def _spy(*a, **k):
        seen.update(k)
        return [], {"truncated": False}

    monkeypatch.setattr(service, "run_all_bounded", _spy)
    monkeypatch.setattr(service, "_cache_path", lambda: tmp_path / "briefing_cache.json")
    monkeypatch.setattr(service, "_article_count", lambda _s: 0)
    monkeypatch.setattr(service, "evaluate_watches", lambda _s: None, raising=False)
    monkeypatch.setattr(ins, "warm_cache", lambda _s: {"warmed": []})
    service.refresh_briefing(object())
    assert seen.get("memory_stop") is True


def test_the_reason_names_a_spent_budget_too(monkeypatch, memory):
    ran = _producers(monkeypatch)
    memory(4000.0)
    _cards, stats = registry.run_all_bounded(object(), deadline=0.0, memory_stop=True)
    assert ran == [] and stats["truncated_reason"] == "budget"


# ---------------------------------------------------------------------------- refresh_briefing
def _cache(monkeypatch, tmp_path, cards):
    path = tmp_path / "briefing_cache.json"
    path.write_text(json.dumps({
        "version": service.CACHE_VERSION, "generated_at": "2026-01-01T00:00:00+00:00",
        "article_count": 3, "cards": cards,
    }), encoding="utf-8")
    monkeypatch.setattr(service, "_cache_path", lambda: path)
    monkeypatch.setattr(service, "_article_count", lambda _s: 3)
    monkeypatch.setattr(service, "evaluate_watches", lambda _s: None, raising=False)
    # the warm step is not under test here and must not run against a stub session
    monkeypatch.setattr(ins, "warm_cache", lambda _s: {"warmed": []})
    return path


class _Card:
    def __init__(self, title):
        self.title = title

    def to_dict(self):
        return {"type": "x", "key": self.title, "title": self.title, "id": self.title,
                "bucket": "lead", "rank": 0}


def test_a_memory_stopped_run_keeps_the_whole_cached_feed_even_when_partial(monkeypatch, tmp_path):
    path = _cache(monkeypatch, tmp_path, [{"type": "x", "title": "a"}, {"type": "x", "title": "b"}])
    monkeypatch.setattr(
        service, "run_all_bounded",
        lambda *a, **k: ([_Card("only-one")], {"truncated": True, "truncated_reason": "memory_short"}),
    )
    out = service.refresh_briefing(object())
    assert [c["title"] for c in out["cards"]] == ["a", "b"]
    assert out["kept_reason"] == "memory_short", "the caller must be able to tell nothing was refreshed"
    assert [c["title"] for c in json.loads(path.read_text("utf-8"))["cards"]] == ["a", "b"], (
        "the partial set replaced the cached feed on disk"
    )


def test_a_memory_stopped_run_with_no_cache_still_writes_what_it_has(monkeypatch, tmp_path):
    path = tmp_path / "briefing_cache.json"  # absent
    monkeypatch.setattr(service, "_cache_path", lambda: path)
    monkeypatch.setattr(service, "_article_count", lambda _s: 3)
    monkeypatch.setattr(service, "evaluate_watches", lambda _s: None, raising=False)
    monkeypatch.setattr(ins, "warm_cache", lambda _s: {"warmed": []})
    monkeypatch.setattr(
        service, "run_all_bounded",
        lambda *a, **k: ([_Card("only-one")], {"truncated": True, "truncated_reason": "memory_short"}),
    )
    out = service.refresh_briefing(object())
    assert [c["title"] for c in out["cards"]] == ["only-one"], (
        "with nothing cached, something must beat an empty Home"
    )


def test_a_partial_run_stopped_by_a_spent_budget_is_not_widened_by_this_change(monkeypatch, tmp_path):
    """Only the empty case keeps the cache for a deadline truncation -- unchanged."""
    _cache(monkeypatch, tmp_path, [{"type": "x", "title": "a"}])
    monkeypatch.setattr(
        service, "run_all_bounded",
        lambda *a, **k: ([_Card("new")], {"truncated": True, "truncated_reason": "budget"}),
    )
    out = service.refresh_briefing(object())
    assert [c["title"] for c in out["cards"]] == ["new"]


# ------------------------------------------------------------------------------- warm_cache
def _sqlite_session(tmp_path):
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'w.db'}",
                           connect_args={"check_same_thread": False})
    return sessionmaker(bind=eng)()


def test_warm_cache_computes_under_the_memory_stop_and_skips_when_short(monkeypatch, tmp_path, memory):
    """Short memory: no compute starts, nothing is cached, the pass tail carries on."""
    s = _sqlite_session(tmp_path)
    computed: list[str] = []
    monkeypatch.setattr(ins, "_CACHE_TTL_S", 300)
    monkeypatch.setattr(ins, "_read_cache", SimpleCache(max_size=16, default_ttl=300))
    monkeypatch.setattr(ins.rm, "trending_windows", lambda *a, **k: computed.append("tw") or {"x": 1})
    monkeypatch.setattr(ins.rm, "top_terms", lambda *a, **k: computed.append("top") or {"x": 1})
    memory(100.0)
    try:
        out = ins.warm_cache(s)
    finally:
        s.rollback()
        s.close()
    assert computed == [], f"a whole-corpus compute started while memory was short: {computed}"
    assert out["warmed"] == []


def test_warm_cache_still_warms_when_memory_is_fine(monkeypatch, tmp_path, memory):
    s = _sqlite_session(tmp_path)
    computed: list[str] = []
    monkeypatch.setattr(ins, "_CACHE_TTL_S", 300)
    monkeypatch.setattr(ins, "_read_cache", SimpleCache(max_size=16, default_ttl=300))
    monkeypatch.setattr(ins.rm, "trending_windows", lambda *a, **k: computed.append("tw") or {"x": 1})
    monkeypatch.setattr(ins.rm, "top_terms", lambda *a, **k: computed.append("top") or {"x": 1})
    memory(4000.0)
    try:
        out = ins.warm_cache(s)
    finally:
        s.rollback()
        s.close()
    assert computed.count("tw") == 2 and computed.count("top") == 1, computed
    assert len(out["warmed"]) == 3


def test_a_read_stopped_part_way_is_skipped_and_nothing_is_cached(monkeypatch, tmp_path, memory):
    """Memory fine at the start, short by the next progress tick: the abort is a
    StatementTimeout subclass and warm_cache must log it, cache nothing and carry on."""
    s = _sqlite_session(tmp_path)
    monkeypatch.setattr(ins, "_CACHE_TTL_S", 300)
    monkeypatch.setattr(ins, "_read_cache", SimpleCache(max_size=16, default_ttl=300))
    memory(4000.0)

    def _aborts(*a, **k):
        raise M.MemoryShort("stopped this read after 3s: the machine was nearly out of memory")

    monkeypatch.setattr(ins.rm, "trending_windows", _aborts)
    monkeypatch.setattr(ins.rm, "top_terms", lambda *a, **k: {"x": 1})
    try:
        out = ins.warm_cache(s)
    finally:
        s.rollback()
        s.close()
    assert len(out["warmed"]) == 1, "the spec that was not stopped must still be warmed"


def test_warming_gets_a_longer_time_budget_than_a_request_but_keeps_the_memory_stop(monkeypatch):
    monkeypatch.delenv("OO_WARM_DEADLINE_S", raising=False)
    monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", "60")
    assert ins._warm_deadline_seconds() == 300.0
    monkeypatch.setenv("OO_WARM_DEADLINE_S", "90")
    assert ins._warm_deadline_seconds() == 90.0
    monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", "0")
    assert ins._warm_deadline_seconds() is None, "a disabled deadline stays disabled"
