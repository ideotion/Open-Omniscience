"""The extraction lock in each collect-perf tick: ``extraction_lock``, and the keys the tick stopped repeating to pay for it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The summary line of a pass is written when the pass ENDS, so a pass that is killed (the lxml abort, an out-of-memory kill) or
hangs leaves ticks and no summary, and a hold that has not ended is in no counter. The live gauge in ``lock_stats`` reads both;
this puts its reading in every tick as the difference between two readings.

What each group of tests guards, and what fails without it:

* the arithmetic (``lock_tick_fields``): exact differences over the gauge's own clock, ``holder_age_s`` ABSENT (not null, not 0)
  when nobody holds the lock, ``null`` with a reason where a rate cannot be made (a zero would read as "the lock was idle");
* the wiring: the baseline is taken when the monitor starts so the first tick has a delta, each tick differences against the PREVIOUS
  tick (not the baseline), the injected reading and the real gauge both reach the log, an open hold shows in a tick that
  falls inside it;
* the failures: a gauge that cannot be read says so by exception CLASS only, the next tick has no earlier reading and says so,
  a failed baseline does the same, and no exception text reaches the log;
* the trims that pay for the block (A: two strings in ``process_budget``, B1: ``collector_kbps``, B2: ``mode``, B4: the tick's
  ``elapsed_s``): the removed fields equal the ones that stay, on the measured path that is the only path the app runs;
* the bytes: the widest block the code writes costs less than the least the trims save in a tick (raw serialised bytes; the
  DEFLATE figures are in the shipped row).
"""

from __future__ import annotations

import ast
import json
import math
import time
import types
from pathlib import Path

import pytest

import src.ingest.extract as extract_mod
from src.ingest import lock_stats
from src.ingest.extract import extract_article
from src.monitoring import collect_perf as cp
from src.scheduler import process_budget
from src.scheduler.bandwidth import BandwidthGovernor

_PAGE = "<p>" + "x" * 40 + "</p>"
_SECRET = "hunter2-correct-horse"


def _reading(now, occupied, waited, age=None, waiting=0):
    return {"now": now, "occupied_s": occupied, "waited_s": waited, "holder_age_s": age, "waiting": waiting}


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture(autouse=True)
def _fresh_gauge(monkeypatch):
    """An idle process-wide gauge for every test, left as found."""
    monkeypatch.setattr(lock_stats, "_waiters", {})
    monkeypatch.setattr(
        lock_stats, "_live", {"depth": 0, "since": None, "holder": None, "occupied_s": 0.0, "waited_s": 0.0}
    )
    lock_stats.reset()
    yield
    lock_stats.reset()


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(lock_stats, "now", fake)
    return fake


def _monitor(tmp_path, monkeypatch, *, lock_fn=None, rate_fn=lambda: 0.0, governor=None):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return cp.CollectionMonitor(
        governor=governor or BandwidthGovernor(mode="maximum", w_max=50),
        pass_id="2026-10-26T04:00:00+00:00",
        mode="rss",
        interval_s=3600.0,  # the loop's first wait: no tick fires on its own, the tests drive ``_tick``
        rate_fn=rate_fn,
        vitals_fn=lambda: {},
        writer_stats_fn=lambda: {},
        lock_fn=lock_fn,
    )


def _rows(tmp_path) -> list[dict]:
    return [json.loads(ln) for ln in (tmp_path / "collect_perf.jsonl").read_text(encoding="utf-8").splitlines()]


def _ticks(tmp_path) -> list[dict]:
    return [r for r in _rows(tmp_path) if r.get("kind") != "summary"]


class _Readings:
    """A lock_fn that hands out a fixed sequence of readings (or raises the item that is an exception)."""

    def __init__(self, *items):
        self.items = list(items)

    def __call__(self):
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


# --------------------------------------------------------------------------
# the arithmetic
# --------------------------------------------------------------------------
def test_the_block_is_the_difference_of_two_readings_over_the_gauges_own_clock():
    prev = _reading(10.0, 2.0, 1.0)
    cur = _reading(11.5, 2.63, 3.5, age=0.34, waiting=2)
    assert cp.lock_tick_fields(prev, cur) == {"held_frac": 0.42, "wait_rate": 1.67, "holder_age_s": 0.3}


def test_holder_age_is_absent_not_null_and_not_zero_when_nobody_holds_the_lock():
    out = cp.lock_tick_fields(_reading(0.0, 0.0, 0.0), _reading(1.5, 0.75, 0.0))
    assert out == {"held_frac": 0.5, "wait_rate": 0.0}
    assert "holder_age_s" not in out, "an absent key says 'no hold open'; a 0 would say one had just begun"


def test_a_hold_that_has_just_begun_is_a_zero_age_not_an_absent_one():
    """``holder_age_s`` 0.0 is a hold that began at the instant of the reading; the key is absent only when nobody holds the lock."""
    out = cp.lock_tick_fields(_reading(0.0, 0.0, 0.0), _reading(1.5, 0.0, 0.0, age=0.0))
    assert out == {"held_frac": 0.0, "wait_rate": 0.0, "holder_age_s": 0.0}


@pytest.mark.parametrize("prev,cur_now", [(None, 5.0), (_reading(5.0, 0.0, 0.0), 5.0), (_reading(9.0, 0.0, 0.0), 5.0)])
def test_an_open_hold_is_reported_on_the_paths_that_have_no_rates(prev, cur_now):
    """The 85 s page is exactly the case where the baseline or the previous reading may be missing: the age of the open hold
    needs no earlier reading and must not be lost with the rates."""
    out = cp.lock_tick_fields(prev, _reading(cur_now, 85.0, 3.0, age=85.04))
    assert out["held_frac"] is None and out["wait_rate"] is None and out["reason"]
    assert out["holder_age_s"] == 85.0


def test_an_idle_interval_is_zero_and_a_fully_held_one_is_one():
    assert cp.lock_tick_fields(_reading(0.0, 5.0, 2.0), _reading(1.5, 5.0, 2.0)) == {"held_frac": 0.0, "wait_rate": 0.0}
    full = cp.lock_tick_fields(_reading(0.0, 5.0, 0.0), _reading(1.5, 6.5, 6.0, age=40.04))
    assert full == {"held_frac": 1.0, "wait_rate": 4.0, "holder_age_s": 40.0}


def test_no_earlier_reading_is_null_with_a_reason_never_a_zero():
    out = cp.lock_tick_fields(None, _reading(1.5, 0.75, 0.0))
    assert out == {"held_frac": None, "wait_rate": None, "reason": "no earlier reading"}


@pytest.mark.parametrize("later", [10.0, 9.0, math.nan])
def test_an_interval_with_no_length_is_null_with_a_reason_never_a_division(later):
    out = cp.lock_tick_fields(_reading(10.0, 1.0, 1.0), _reading(later, 2.0, 2.0))
    assert out == {"held_frac": None, "wait_rate": None, "reason": "no time between readings"}


def test_a_difference_is_written_as_it_is_not_clamped_into_range():
    """The gauge's totals only grow and its lock is exclusive; a value outside 0 to 1 would mean an assumption broke, and clamping
    it would hide that (the module says so)."""
    out = cp.lock_tick_fields(_reading(0.0, 0.0, 0.0), _reading(1.0, 2.5, 0.0))
    assert out["held_frac"] == 2.5


def test_every_value_is_a_number_or_null_or_a_fixed_sentence():
    for out in (
        cp.lock_tick_fields(_reading(0.0, 0.0, 0.0), _reading(1.5, 0.3, 0.2, age=0.1)),
        cp.lock_tick_fields(None, _reading(1.5, 0.3, 0.2)),
        cp.lock_tick_fields(_reading(1.5, 0.0, 0.0), _reading(1.5, 0.3, 0.2)),
    ):
        assert set(out) <= {"held_frac", "wait_rate", "holder_age_s", "reason"}
        for k, v in out.items():
            assert (isinstance(v, float) and k != "reason") or v is None or (k == "reason" and isinstance(v, str)), (k, v)


# --------------------------------------------------------------------------
# the wiring
# --------------------------------------------------------------------------
def test_the_first_tick_differences_against_the_pass_start_and_each_later_tick_against_the_one_before(tmp_path, monkeypatch):
    fn = _Readings(
        _reading(100.0, 10.0, 4.0),  # start(): the baseline
        _reading(101.5, 10.75, 4.0, age=0.5),  # tick 1
        _reading(103.0, 11.5, 6.25),  # tick 2: against tick 1, not against the baseline
    )
    mon = _monitor(tmp_path, monkeypatch, lock_fn=fn)
    mon.start()
    try:
        mon._tick()
        mon._tick()
    finally:
        mon.stop()
    t1, t2 = _ticks(tmp_path)
    assert t1["extraction_lock"] == {"held_frac": 0.5, "wait_rate": 0.0, "holder_age_s": 0.5}
    assert t2["extraction_lock"] == {"held_frac": 0.5, "wait_rate": 1.5}, "(11.5-10.75)/1.5 and (6.25-4.0)/1.5"
    assert fn.items == [], "one reading per tick and one at the start: no more, no fewer"


def test_the_block_sits_between_the_writer_gate_and_the_cpu_fields(tmp_path, monkeypatch):
    mon = _monitor(tmp_path, monkeypatch, lock_fn=_Readings(_reading(0.0, 0.0, 0.0), _reading(1.5, 0.0, 0.0)))
    mon.start()
    try:
        mon._tick()
    finally:
        mon.stop()
    keys = list(_ticks(tmp_path)[0])
    assert keys.index("writer_gate") + 1 == keys.index("extraction_lock") == keys.index("cpu_sys_pct") - 1


def test_the_real_gauge_reaches_the_log_and_an_open_hold_shows_in_a_tick_inside_it(tmp_path, monkeypatch, clock):
    mon = _monitor(tmp_path, monkeypatch)  # the default lock_fn: lock_stats.live_reading
    mon.start()
    seen: list[dict] = []

    def body(html, *, url=None):
        clock.t += 1.0
        mon._tick()  # a tick that falls inside the hold: the hold has not ended, so no counter has it
        seen.append(dict(_ticks(tmp_path)[-1]["extraction_lock"]))
        clock.t += 0.5
        return extract_mod.ExtractedDoc("t", "x" * 300, None, None, None, None)

    monkeypatch.setattr(extract_mod, "_extract_locked", body)
    try:
        extract_article(_PAGE)
        clock.t += 1.5
        mon._tick()
    finally:
        mon.stop()
    inside = seen[0]
    # 1.0 s of the 1.0 s since the start was held, and the holder is 1.0 s old
    assert inside == {"held_frac": 1.0, "wait_rate": 0.0, "holder_age_s": 1.0}
    after = _ticks(tmp_path)[-1]["extraction_lock"]
    # since the tick inside: 0.5 s more held of 2.0 s, nobody holds it now
    assert after == {"held_frac": 0.25, "wait_rate": 0.0}


def test_the_real_gauge_default_is_the_modules_live_reading(tmp_path, monkeypatch):
    mon = _monitor(tmp_path, monkeypatch)
    assert set(mon._lock_reading()) == {"now", "occupied_s", "waited_s", "holder_age_s", "waiting"}


# --------------------------------------------------------------------------
# the failures
# --------------------------------------------------------------------------
def test_a_gauge_that_cannot_be_read_says_so_by_class_and_the_next_tick_says_it_has_nothing_to_compare(tmp_path, monkeypatch):
    fn = _Readings(
        _reading(0.0, 0.0, 0.0),
        RuntimeError(f"the passphrase is {_SECRET}"),
        _reading(3.0, 1.5, 0.0),
        _reading(4.5, 1.5, 0.0),
    )
    mon = _monitor(tmp_path, monkeypatch, lock_fn=fn)
    mon.start()
    try:
        mon._tick()
        mon._tick()
        mon._tick()
    finally:
        mon.stop()
    t1, t2, t3 = _ticks(tmp_path)
    assert t1["extraction_lock"] == {"unavailable": "RuntimeError"}
    assert t2["extraction_lock"] == {"held_frac": None, "wait_rate": None, "reason": "no earlier reading"}
    assert t3["extraction_lock"] == {"held_frac": 0.0, "wait_rate": 0.0}
    assert _SECRET not in (tmp_path / "collect_perf.jsonl").read_text(encoding="utf-8"), "the class, never the words"


def test_a_failed_baseline_gives_the_first_tick_no_earlier_reading_and_the_pass_runs(tmp_path, monkeypatch):
    fn = _Readings(OSError(_SECRET), _reading(1.5, 0.0, 0.0), _reading(3.0, 0.75, 0.0))
    mon = _monitor(tmp_path, monkeypatch, lock_fn=fn)
    mon.start()
    try:
        mon._tick()
        mon._tick()
    finally:
        mon.stop()
    t1, t2 = _ticks(tmp_path)
    assert t1["extraction_lock"] == {"held_frac": None, "wait_rate": None, "reason": "no earlier reading"}
    assert t2["extraction_lock"] == {"held_frac": 0.5, "wait_rate": 0.0}
    assert _SECRET not in (tmp_path / "collect_perf.jsonl").read_text(encoding="utf-8")


def test_a_failed_baseline_still_shows_a_hold_that_is_open_at_the_first_tick(tmp_path, monkeypatch):
    fn = _Readings(OSError(_SECRET), _reading(1.5, 1.5, 0.0, age=85.0))
    mon = _monitor(tmp_path, monkeypatch, lock_fn=fn)
    mon.start()
    try:
        mon._tick()
    finally:
        mon.stop()
    assert _ticks(tmp_path)[0]["extraction_lock"] == {
        "held_frac": None, "wait_rate": None, "reason": "no earlier reading", "holder_age_s": 85.0,
    }


def test_a_reading_that_is_not_a_reading_is_unavailable_and_never_breaks_the_tick(tmp_path, monkeypatch):
    mon = _monitor(tmp_path, monkeypatch, lock_fn=_Readings(_reading(0.0, 0.0, 0.0), {"now": 1.5}))
    mon.start()
    try:
        mon._tick()
    finally:
        mon.stop()
    assert _ticks(tmp_path)[0]["extraction_lock"] == {"unavailable": "KeyError"}


# --------------------------------------------------------------------------
# the words
# --------------------------------------------------------------------------
def test_the_meaning_is_defined_in_the_module_and_is_not_written_into_the_log(tmp_path, monkeypatch):
    """The sentence in ``lock_stats.LIVE_METHOD`` is unique text: written once on a pass summary it cost +228 to +236 B in every
    slim diagnostics copy taken after a pass, once deflated (the tick block's shipped row has the measurement), which is more than the block and
    the trims net. So the tick's field names say what they hold and the words live in the code and the ledger, not in the log; a
    change that carries them in a summary, a tick or the block the scheduler copies into every run report fails here."""
    mon = _monitor(tmp_path, monkeypatch, lock_fn=_Readings(_reading(0.0, 0.0, 0.0), _reading(1.5, 0.0, 0.0)))
    mon.start()
    try:
        mon._tick()
    finally:
        summary = mon.stop(result={"articles_stored": 3, "sources_processed": 2, "pages_fetched": 5})
    log = (tmp_path / "collect_perf.jsonl").read_text(encoding="utf-8")
    assert "held_frac = share" not in log and "mean queue length" not in log
    assert not any("tick_method" in k for k in summary), "no key of the summary carries the sentence"
    assert "method" not in _ticks(tmp_path)[0]["extraction_lock"]
    assert "method" not in summary["extraction_lock"] or summary["extraction_lock"]["method"] == lock_stats.METHOD
    for name in ("held_frac", "wait_rate", "holder_age_s"):
        assert name in lock_stats.LIVE_METHOD, f"the sentence must define {name}"


# --------------------------------------------------------------------------
# the trims that pay for the block
# --------------------------------------------------------------------------
def test_a_tick_no_longer_repeats_what_the_same_sample_already_carries(tmp_path, monkeypatch):
    mon = _monitor(tmp_path, monkeypatch, lock_fn=_Readings(_reading(0.0, 0.0, 0.0), _reading(1.5, 0.0, 0.0)))
    mon.start()
    try:
        mon._tick()
    finally:
        mon.stop()
    row = _ticks(tmp_path)[0]
    assert "elapsed_s" not in row, "forensics derives the time into the pass from ts and pass_id (tests/test_session_forensics.py)"
    assert not {"collector_kbps", "mode"} & set(row["process_budget"])
    assert "download_rate_kbps" in row and "rate_mode" in row, "the two values the removed copies equalled stay in the sample"
    assert {"budget_kbps", "process_kbps", "downloads_measured", "over_budget", "partial", "method"} <= set(row["process_budget"])


def test_the_governor_is_still_fed_the_whole_process_figure_from_the_untrimmed_budget(tmp_path, monkeypatch):
    gov = BandwidthGovernor(mode="maximum", w_max=50)
    fed: list[float] = []
    real = gov.observe

    def spy(process_kbps, **kw):
        fed.append(process_kbps)
        return real(process_kbps, **kw)

    monkeypatch.setattr(gov, "observe", spy)
    mon = _monitor(tmp_path, monkeypatch, governor=gov, rate_fn=lambda: 321.5,
                   lock_fn=_Readings(_reading(0.0, 0.0, 0.0), _reading(1.5, 0.0, 0.0)))
    mon.start()
    try:
        mon._tick()
    finally:
        mon.stop()
    assert fed == [_ticks(tmp_path)[0]["process_budget"]["process_kbps"]] and fed[0] >= 321.5


@pytest.mark.parametrize("downloads", [
    {"measured": False, "idle": True, "unmeasured": [], "reason": "no download is running"},
    {"measured": True, "idle": False, "bytes_per_s": 250_000.0, "unmeasured": ["wiki-dump:xx"]},
])
@pytest.mark.parametrize("mode", ["maximum", "target"])
def test_the_tick_budget_is_exactly_compose_minus_the_two_keys_that_equal_a_sample_field(tmp_path, monkeypatch, mode, downloads):
    """Every other key of ``compose``'s answer (the panel reads ``downloads_kbps``, ``over_budget``, ``partial``; ``budget_reason`` and
    ``downloads_reason`` are the app's words) is in the tick unchanged: a key added to ``_TICK_BUDGET_DUPLICATES`` fails here."""
    import src.ingest.download_rate as dr

    monkeypatch.setattr(dr, "process_download_rate", lambda: dict(downloads))
    gov = BandwidthGovernor(mode=mode, w_max=50)
    mon = _monitor(tmp_path, monkeypatch, governor=gov, rate_fn=lambda: 321.5,
                   lock_fn=_Readings(_reading(0.0, 0.0, 0.0), _reading(1.5, 0.0, 0.0)))
    mon.start()
    try:
        mon._tick()
    finally:
        mon.stop()
    full = process_budget.compose(gov, 321.5, download_rate=dict(downloads))
    assert set(full) - set(_ticks(tmp_path)[0]["process_budget"]) == {"collector_kbps", "mode"}
    assert _ticks(tmp_path)[0]["process_budget"] == {k: v for k, v in full.items() if k not in ("collector_kbps", "mode")}


def test_the_app_builds_its_monitor_without_a_rate_fn_which_is_what_makes_the_removed_budget_fields_free():
    """B1 is free on the MEASURED path only (``_measure_rate`` rounds and floors the figure that ``compose`` would round and floor).
    An injected ``rate_fn`` would put an unrounded figure in ``download_rate_kbps`` and a rounded one in ``collector_kbps``; the
    app never passes one, and this fails if ``runner.py`` ever does."""
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src" / "scheduler" / "runner.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "CollectionMonitor"]
    assert calls, "the runner no longer builds a CollectionMonitor by name: update this pin"
    for call in calls:
        assert "rate_fn" not in {k.arg for k in call.keywords}


@pytest.mark.parametrize("mode", ["maximum", "target"])
def test_the_removed_budget_fields_equal_the_fields_that_stay_on_the_measured_path(monkeypatch, mode):
    """B1 and B2 are free only while ``compose``'s ``collector_kbps`` is the tick's ``download_rate_kbps`` and its ``mode`` is the
    sample's ``rate_mode``. On the path the app runs (no injected ``rate_fn``) the rate is rounded to 0.1 and floored at 0 by
    ``_measure_rate`` before ``compose`` sees it; this pins that for a rate with a long tail, an idle tick and a counter that went
    backwards, so a change to either side fails here and not in a log."""
    gov = BandwidthGovernor(mode=mode, w_max=50)
    mon = cp.CollectionMonitor(governor=gov, pass_id="p", mode="rss", vitals_fn=lambda: {}, writer_stats_fn=lambda: {})
    totals = iter([123457, 123457, 400])  # bytes_total: a rate with a long tail, idle, then a counter that went backwards
    clock = iter([1.3333, 2.8333, 4.1])
    # the module's own handle on the clock, not the process-wide ``time`` (the gauge and pytest read that one)
    monkeypatch.setattr(cp, "time", types.SimpleNamespace(monotonic=lambda: next(clock), time=time.time))
    monkeypatch.setattr(mon, "_bytes_total", lambda: next(totals))
    mon._prev_bytes, mon._prev_mono = 0, 0.0
    rates = []
    for _ in range(3):
        rate = mon._measure_rate()
        rates.append(rate)
        budget = process_budget.compose(gov, rate)
        assert budget["collector_kbps"] == rate
        assert budget["mode"] == gov.mode
    assert rates[0] > 0 and rates[0] != round(123457 * 8 / 1000.0 / 1.3333, 6), "the first rate has a tail the rounding cut"
    assert rates[1] == 0.0 and rates[2] == 0.0, "an idle tick and a backwards counter both read 0.0, never negative"


# --------------------------------------------------------------------------
# the bytes
# --------------------------------------------------------------------------
def _removed_per_tick_at_least() -> int:
    """The fewest bytes of a tick row the trims remove, in the state that removes least (target mode: its ``mode`` value is
    the shorter, and the maximum-mode sentence is not in the row): the three keys at their narrowest and the shorter METHOD."""
    # ``"key":value,`` is the object's two braces out and one comma in
    keys = sum(
        len(json.dumps({k: v}, separators=(",", ":"))) - 1
        for k, v in (("elapsed_s", 0.0), ("collector_kbps", 0.0), ("mode", "target"))
    )
    old_method_chars = 185  # the sentence before trim A, measured on main 2fb9a4701; the new one is read from the module
    return keys + (old_method_chars - len(process_budget.METHOD))


def _block_bytes(block: dict) -> int:
    """``"extraction_lock":{...},`` as the log row writes it."""
    return len(json.dumps({"extraction_lock": block}, separators=(",", ":"))) - 2 + 1


def test_the_widest_numeric_block_costs_less_than_the_least_the_trims_save_in_a_tick():
    """Raw serialised bytes of a tick row, which is the budget the diagnostics copies are cut to (DEFLATE is in the shipped row,
    where it was measured on real written logs). The widths are what the code can write: ``held_frac`` at two decimals, a wait rate
    to 999.99 (a queue of a thousand threads is not a width worth a day's log), a holder age to 99999.9 s (a day and a half held)."""
    widest = {"held_frac": 0.42, "wait_rate": 999.99, "holder_age_s": 99999.9}
    assert _block_bytes(widest) == 79
    assert _block_bytes(widest) <= _removed_per_tick_at_least() == 107


def test_the_blocks_a_broken_gauge_writes_every_tick_fit_in_the_same_saving():
    for block in (
        {"held_frac": None, "wait_rate": None, "reason": "no earlier reading"},
        {"held_frac": None, "wait_rate": None, "reason": "no time between readings"},
        {"unavailable": "UnicodeDecodeError"},
    ):
        assert _block_bytes(block) <= _removed_per_tick_at_least(), block
