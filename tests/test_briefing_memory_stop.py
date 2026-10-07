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
        "article_count": 3, "stoplist": service._stoplist_fingerprint(), "cards": cards,
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
    on_disk = json.loads(path.read_text("utf-8"))
    assert [c["title"] for c in on_disk["cards"]] == ["a", "b"], (
        "the partial set replaced the cached feed on disk"
    )
    # Home reads the cache, not this return value: the marker must be in the file and reach the view.
    assert on_disk["kept_reason"] == "memory_short"
    assert service._present({**on_disk, "cards": []}, include_dismissed=False)["kept_reason"] == "memory_short"


def test_a_run_stopped_by_a_spent_budget_with_no_cards_keeps_the_feed_and_says_deadline(monkeypatch, tmp_path):
    """The other kept reason: only a diagnostic or a test reaches it (no production caller passes a
    deadline), so nothing else would notice it saying ``memory_short`` here (CHECK of #1284, A3)."""
    path = _cache(monkeypatch, tmp_path, [{"type": "x", "title": "a"}])
    monkeypatch.setattr(
        service, "run_all_bounded",
        lambda *a, **k: ([], {"truncated": True, "truncated_reason": "budget"}),
    )
    out = service.refresh_briefing(object())
    assert out["kept_reason"] == "deadline"
    assert json.loads(path.read_text("utf-8"))["kept_reason"] == "deadline"


@pytest.mark.parametrize(
    "garbage", ["", "Memory_Short", "memory_short ", " deadline", "<img src=x>", None, 0, 1, True, [], {}, ["deadline"]],
)
def test_the_view_drops_any_marker_that_is_not_one_of_the_two_known_reasons(garbage):
    """A hand-edited or damaged cache must not reach the API view: Home maps any value that is not
    ``memory_short`` to the time reason, so a stray string would read as a wrong cause (A14)."""
    on_disk = {"cards": [], "kept_reason": garbage, "incomplete_reason": garbage}
    view = service._present(on_disk, include_dismissed=False)
    assert "kept_reason" not in view and "incomplete_reason" not in view


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
    warmed: list[int] = []
    monkeypatch.setattr(ins, "warm_cache", lambda _s: warmed.append(1))
    out = service.refresh_briefing(object())
    assert [c["title"] for c in out["cards"]] == ["only-one"], (
        "with nothing cached, something must beat an empty Home"
    )
    # A short feed must not read as a complete one: the cache says so, and so does the view.
    assert out["incomplete_reason"] == "memory_short"
    assert json.loads(path.read_text("utf-8"))["incomplete_reason"] == "memory_short"
    assert service._present(out, include_dismissed=False)["incomplete_reason"] == "memory_short"
    assert warmed == [], "the warm-up ran straight after a stop for lack of memory"


def test_a_partial_run_stopped_by_a_spent_budget_is_not_widened_by_this_change(monkeypatch, tmp_path):
    """Only the empty case keeps the cache for a deadline truncation -- unchanged."""
    _cache(monkeypatch, tmp_path, [{"type": "x", "title": "a"}])
    monkeypatch.setattr(
        service, "run_all_bounded",
        lambda *a, **k: ([_Card("new")], {"truncated": True, "truncated_reason": "budget"}),
    )
    out = service.refresh_briefing(object())
    assert [c["title"] for c in out["cards"]] == ["new"]
    assert out["incomplete_reason"] == "deadline", "a partial set from a spent budget is marked too"


def test_a_refreshed_feed_records_the_shipped_stoplist_it_was_made_under(monkeypatch, tmp_path):
    _cache(monkeypatch, tmp_path, [{"type": "x", "title": "a"}])
    monkeypatch.setattr(service, "run_all_bounded", lambda *a, **k: ([_Card("new")], {"truncated": False}))
    out = service.refresh_briefing(object())
    assert out["stoplist"] == service._stoplist_fingerprint() and out["stoplist"]


def test_a_completed_run_carries_no_stop_marker(monkeypatch, tmp_path):
    path = _cache(monkeypatch, tmp_path, [{"type": "x", "title": "a"}])
    stale = json.loads(path.read_text("utf-8"))
    path.write_text(json.dumps({**stale, "kept_reason": "memory_short", "incomplete_reason": "deadline"}), "utf-8")
    monkeypatch.setattr(service, "run_all_bounded", lambda *a, **k: ([_Card("new")], {"truncated": False}))
    out = service.refresh_briefing(object())
    assert "incomplete_reason" not in out and "kept_reason" not in out
    view = service._present(json.loads(path.read_text("utf-8")), include_dismissed=False)
    assert "incomplete_reason" not in view and "kept_reason" not in view


def test_a_refresh_that_lands_during_a_kept_run_is_not_marked_as_the_previous_feed(monkeypatch, tmp_path):
    """The guard needs the feed that was on disk when the run STARTED: two reads taken after the
    run cannot see a complete refresh that landed while it ran (the coordinator's check, S5)."""
    path = _cache(monkeypatch, tmp_path, [{"type": "x", "title": "old"}])

    def _run(*a, **k):
        # a concurrent refresh finishes while this one runs: a newer, complete, unmarked feed
        path.write_text(json.dumps({
            "version": service.CACHE_VERSION, "generated_at": "2026-02-02T00:00:00+00:00",
            "article_count": 3, "cards": [{"type": "x", "title": "fresh"}],
        }), encoding="utf-8")
        return [], {"truncated": True, "truncated_reason": "memory_short"}

    monkeypatch.setattr(service, "run_all_bounded", _run)
    out = service.refresh_briefing(object())
    assert out["kept_reason"] == "memory_short", "this call still reports that it kept the cache"
    on_disk = json.loads(path.read_text("utf-8"))
    assert "kept_reason" not in on_disk, "a fresh complete feed was marked as the previous one"
    assert [c["title"] for c in on_disk["cards"]] == ["fresh"]


# ---------------------------------------------------------- a marker is repaired without a click
@pytest.fixture
def poll(monkeypatch, tmp_path, memory):
    """``poll(marker)`` is one Home poll over a cache carrying ``marker``; it returns how many
    background refreshes that poll started."""
    path = _cache(monkeypatch, tmp_path, [{"type": "x", "title": "a", "id": "a", "bucket": "lead"}])
    memory(4096.0)
    monkeypatch.setitem(service._marker_retry, "at", None)
    # no scheduler of an earlier test, with a lock still held, may decide these polls
    monkeypatch.setattr("src.scheduler.runner._scheduler", None)
    monkeypatch.setattr(
        service, "run_all_bounded",
        lambda *a, **k: ([], {"truncated": True, "truncated_reason": "memory_short"}),
    )
    started: list[int] = []
    monkeypatch.setattr(service, "_ensure_background_refresh", lambda: started.append(1))

    def _poll(marker: dict | None = None) -> int:
        on_disk = json.loads(path.read_text("utf-8"))
        for key in ("kept_reason", "incomplete_reason"):
            on_disk.pop(key, None)
        path.write_text(json.dumps({**on_disk, **(marker or {})}), encoding="utf-8")
        before = len(started)
        service.get_briefing(object(), background=True)
        return len(started) - before

    return _poll


@pytest.mark.parametrize("marker", [{"kept_reason": "memory_short"}, {"incomplete_reason": "deadline"}])
def test_a_stop_marker_starts_one_repair_once_memory_is_back(poll, marker):
    assert poll(marker) == 1, "a feed that says it stopped early stayed that way until someone pressed Refresh"


def test_a_feed_without_a_marker_is_not_refreshed(poll):
    assert poll(None) == 0


def test_the_repair_waits_while_memory_is_still_short(poll, memory):
    memory(100.0)
    assert poll({"kept_reason": "memory_short"}) == 0
    memory(4096.0)
    assert poll({"kept_reason": "memory_short"}) == 1, "the wait for memory must not use up the attempt"


def test_the_repair_needs_a_margin_of_headroom_not_a_megabyte_over_the_floor(poll, memory):
    """A refresh started a hair above the floor only stops again at its first producer boundary."""
    marker = {"kept_reason": "memory_short"}
    memory(257.0, 256.0)
    assert poll(marker) == 0
    memory(512.0, 256.0)
    assert poll(marker) == 0, "exactly floor plus margin is not yet above it"
    memory(513.0, 256.0)
    assert poll(marker) == 1


def test_the_headroom_margin_is_capped_so_a_high_floor_does_not_switch_the_repair_off(poll, memory):
    marker = {"kept_reason": "memory_short"}
    memory(2048.0 + 512.0, 2048.0)
    assert poll(marker) == 0, "exactly floor plus the cap is not yet above it"
    memory(2048.0 + 513.0, 2048.0)
    assert poll(marker) == 1


def test_the_repair_never_overlaps_the_schedulers_whole_corpus_work(poll, monkeypatch):
    from src.scheduler import runner

    class _Busy:
        def whole_corpus_work_running(self):
            return busy[0]

    busy = [True]
    monkeypatch.setattr(runner, "_scheduler", _Busy())
    marker = {"kept_reason": "memory_short"}
    assert poll(marker) == 0
    busy[0] = False
    assert poll(marker) == 1


def test_the_scheduler_reports_its_whole_corpus_work_from_its_two_locks():
    from src.scheduler.runner import BackgroundScheduler
    from src.scheduler.settings import SchedulerSettings

    sched = BackgroundScheduler(settings_provider=lambda: SchedulerSettings())
    assert sched.whole_corpus_work_running() is False
    with sched._briefing_bg_lock:
        assert sched.whole_corpus_work_running() is True
    with sched._heavy_tail_lock:
        assert sched.whole_corpus_work_running() is True
    assert sched.whole_corpus_work_running() is False


def test_a_marker_that_keeps_coming_back_waits_from_when_the_last_refresh_finished(poll, monkeypatch):
    """What the pause protects: a refresh that keeps ending early, or one that takes minutes,
    being re-run back to back. The wait starts when a refresh FINISHES, not when it began."""
    marker = {"kept_reason": "memory_short"}
    clock = [1000.0]
    monkeypatch.setattr(service, "_monotonic", lambda: clock[0])
    assert poll(marker) == 1, "nothing has run in this process yet: the first poll repairs at once"
    # that refresh runs for a long time and ends early, re-marking the feed
    clock[0] += 5000.0
    service.refresh_briefing(object())  # a stopped run (the module's stub below) records its finish time
    clock[0] += service._MARKER_RETRY_S - 1
    assert poll(marker) == 0
    clock[0] += 1
    assert poll(marker) == 1, "exactly the retry interval after the finish is allowed"


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
    key = ins._bind_key(s, ins.trending_windows_key(
        country=None, kind=None, limit=ins.WARM_TRENDING_HOME[0], series_top=ins.WARM_TRENDING_HOME[1]))
    assert ins._read_cache.get(key) is None, "an aborted read must leave nothing in the cache"


def test_warming_gets_a_longer_time_budget_than_a_request_but_keeps_the_memory_stop(monkeypatch):
    monkeypatch.delenv("OO_WARM_DEADLINE_S", raising=False)
    monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", "60")
    assert ins._warm_deadline_seconds() == 300.0
    monkeypatch.setenv("OO_WARM_DEADLINE_S", "90")
    assert ins._warm_deadline_seconds() == 90.0
    monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", "0")
    assert ins._warm_deadline_seconds() is None, "a disabled deadline stays disabled"


@pytest.mark.parametrize("value", ["0", "-5", "nan", "inf", "abc", ""])
def test_a_warm_deadline_that_would_disarm_the_stop_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", "60")
    monkeypatch.setenv("OO_WARM_DEADLINE_S", value)
    assert ins._warm_deadline_seconds() == 300.0


def test_a_disabled_endpoint_deadline_leaves_the_warm_deadline_disabled(monkeypatch):
    monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", "0")
    monkeypatch.setenv("OO_WARM_DEADLINE_S", "90")
    assert ins._warm_deadline_seconds() is None


def test_a_huge_warm_deadline_is_honoured_not_capped(monkeypatch):
    """There is no ceiling by design (no fixed caps): the operator asked to wait."""
    monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", "60")
    monkeypatch.setenv("OO_WARM_DEADLINE_S", "1e12")
    assert ins._warm_deadline_seconds() == 1e12
