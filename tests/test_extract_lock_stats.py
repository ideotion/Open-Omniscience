"""What the extraction lock cost, per collection pass: the line that tells a long page from a stalled collector.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``extract_article`` runs one extraction at a time in the whole process and nothing times a long page out
(a 10 MiB nav-heavy page measured 85 s, ``docs/ledger/OPEN_QUEUE.md``, "THE lxml SIGABRT"). From outside, a
pass in which every worker waits behind one slow page looks like a stalled collector. ``src/ingest/
lock_stats.py`` counts the holds and waits, and the collection monitor writes them into the pass's summary
line in ``collect_perf.jsonl`` (``extraction_lock``), a file the debug bundle already carries.

The clock is a fake the tests drive, so every number below is exact and nothing sleeps. Each test fails when
the thing it guards goes: the statistic removed, its window never reset, a page's character count reported as
bytes, the longest hold paired with the wrong page, the record taken inside the lock, the URL written into it.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

import src.ingest.extract as extract_mod
from src.ingest import lock_stats
from src.ingest.extract import extract_article
from src.monitoring.collect_perf import CollectionMonitor, recent_samples
from src.scheduler.bandwidth import BandwidthGovernor

_PAGE = "<html><body><p>" + "A sentence that is long enough to count as a body. " * 12 + "</p></body></html>"


class _Clock:
    """A clock the test moves by hand. ``watch(name)`` returns an event set when that thread first reads it."""

    def __init__(self) -> None:
        self.t = 0.0
        self._watched: dict[str, threading.Event] = {}

    def watch(self, thread_name: str) -> threading.Event:
        self._watched[thread_name] = threading.Event()
        return self._watched[thread_name]

    def __call__(self) -> float:
        reading = self.t  # read BEFORE announcing, so the test cannot move the clock between the two
        event = self._watched.get(threading.current_thread().name)
        if event is not None:
            event.set()
        return reading


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(lock_stats, "now", fake)
    lock_stats.reset()
    yield fake
    lock_stats.reset()


def _hold_for(clock: _Clock, seconds_by_page: dict[int, float], monkeypatch) -> None:
    """Make the extraction itself take ``seconds_by_page[len(html)]`` seconds of the fake clock."""

    def fake(html, *, url=None):
        clock.t += seconds_by_page.get(len(html), 0.0)
        return extract_mod.ExtractedDoc(
            title="t", text="x" * 300, published_at=None, language=None, author=None, canonical_url=None
        )

    monkeypatch.setattr(extract_mod, "_extract_locked", fake)


def _page(chars: int) -> str:
    return "<p>" + "x" * chars + "</p>"


def test_one_extraction_is_counted_with_its_hold_and_its_page(clock, monkeypatch):
    page = _page(40)
    _hold_for(clock, {len(page): 2.5}, monkeypatch)
    assert extract_article(page) is not None
    snap = lock_stats.snapshot()
    assert snap["extractions"] == 1
    assert snap["hold_max_s"] == 2.5 and snap["hold_total_s"] == 2.5
    assert snap["wait_max_s"] == 0.0 and snap["wait_total_s"] == 0.0
    assert snap["hold_max_html_utf8_bytes"] == len(page.encode("utf-8"))
    assert "monotonic" in snap["method"]


def test_the_wait_is_the_time_between_asking_for_the_lock_and_getting_it(clock, monkeypatch):
    held = threading.Event()
    release = threading.Event()
    big, small = _page(300), _page(20)

    def fake(html, *, url=None):
        if threading.current_thread().name == "holder":
            held.set()
            assert release.wait(10)
        return extract_mod.ExtractedDoc("t", "x" * 300, None, None, None, None)

    monkeypatch.setattr(extract_mod, "_extract_locked", fake)
    asked = clock.watch("waiter")
    holder = threading.Thread(target=lambda: extract_article(big), name="holder", daemon=True)
    waiter = threading.Thread(target=lambda: extract_article(small), name="waiter", daemon=True)
    holder.start()
    assert held.wait(10)
    waiter.start()
    assert asked.wait(10), "the waiter never asked for the lock"
    clock.t = 5.0  # five seconds pass while the holder has the lock and the waiter is blocked on it
    release.set()
    holder.join(10)
    waiter.join(10)
    assert not holder.is_alive() and not waiter.is_alive()
    snap = lock_stats.snapshot()
    assert snap["extractions"] == 2
    assert snap["wait_max_s"] == 5.0 and snap["wait_total_s"] == 5.0
    assert snap["hold_max_s"] == 5.0 and snap["hold_total_s"] == 5.0
    assert snap["hold_max_html_utf8_bytes"] == len(big.encode("utf-8")), "the longest hold is the big page's"


def test_the_longest_hold_is_paired_with_its_own_page_not_the_latest_or_the_largest(clock, monkeypatch):
    first, longest, last = _page(100), _page(10), _page(500)  # the longest hold is the SMALLEST page
    _hold_for(clock, {len(first): 1.0, len(longest): 4.0, len(last): 2.0}, monkeypatch)
    for page in (first, longest, last):
        extract_article(page)
    snap = lock_stats.snapshot()
    assert snap["extractions"] == 3
    assert snap["hold_max_s"] == 4.0 and snap["hold_total_s"] == 7.0
    assert snap["hold_max_html_utf8_bytes"] == len(longest.encode("utf-8"))


def test_the_size_is_utf8_bytes_not_characters(clock, monkeypatch):
    page = "<p>" + "é" * 50 + "</p>"  # two bytes a letter
    _hold_for(clock, {len(page): 1.0}, monkeypatch)
    extract_article(page)
    size = lock_stats.snapshot()["hold_max_html_utf8_bytes"]
    assert size == len(page) + 50 and size != len(page)


def test_a_lone_surrogate_in_the_page_does_not_break_the_size(clock, monkeypatch):
    page = "<p>\ud800 " + "x" * 30 + "</p>"
    _hold_for(clock, {len(page): 1.0}, monkeypatch)
    assert extract_article(page) is not None
    assert lock_stats.snapshot()["hold_max_html_utf8_bytes"] > 0


def test_a_raising_extraction_is_counted_and_the_error_still_reaches_the_caller(clock, monkeypatch):
    def fake(html, *, url=None):
        clock.t += 3.0
        raise ValueError("the parser gave up")

    monkeypatch.setattr(extract_mod, "_extract_locked", fake)
    with pytest.raises(ValueError, match="the parser gave up"):
        extract_article(_page(40))
    snap = lock_stats.snapshot()
    assert snap["extractions"] == 1 and snap["hold_max_s"] == 3.0


def test_a_blank_page_never_asks_for_the_lock_so_it_is_not_counted(clock, monkeypatch):
    _hold_for(clock, {}, monkeypatch)
    for blank in ("", "   \n\t "):
        assert extract_article(blank) is None
    assert lock_stats.snapshot() == {"extractions": 0}


def test_an_empty_window_says_so_and_invents_no_maximum(clock):
    snap = lock_stats.snapshot()
    assert snap == {"extractions": 0}
    assert "hold_max_s" not in snap and "wait_max_s" not in snap


def test_reset_starts_a_new_window(clock, monkeypatch):
    page = _page(40)
    _hold_for(clock, {len(page): 9.0}, monkeypatch)
    extract_article(page)
    assert lock_stats.snapshot()["hold_max_s"] == 9.0
    lock_stats.reset()
    assert lock_stats.snapshot() == {"extractions": 0}
    _hold_for(clock, {len(page): 1.0}, monkeypatch)
    extract_article(page)
    assert lock_stats.snapshot()["hold_max_s"] == 1.0, "the earlier window's longest hold leaked into this one"


def test_the_record_holds_numbers_only_never_the_url_or_the_page(clock, monkeypatch):
    url = "https://example.test/story?X-Amz-Signature=abc123secret"
    page = "<p>" + "needle-in-the-page " * 5 + "</p>"
    _hold_for(clock, {len(page): 1.0}, monkeypatch)
    extract_article(page, url=url)
    snap = lock_stats.snapshot()
    text = json.dumps(snap)
    assert "abc123secret" not in text and "example.test" not in text and "needle" not in text
    assert {k: type(v) for k, v in snap.items() if k != "method"} == {
        "extractions": int,
        "wait_max_s": float,
        "wait_total_s": float,
        "hold_max_s": float,
        "hold_total_s": float,
        "hold_max_html_utf8_bytes": int,
    }


def test_the_statistic_is_taken_after_the_extraction_lock_is_given_up(clock, monkeypatch):
    seen: list[bool] = []
    real = lock_stats.record

    def spy(**kwargs):
        seen.append(extract_mod._LXML_LOCK._is_owned())
        return real(**kwargs)

    monkeypatch.setattr(lock_stats, "record", spy)
    page = _page(40)
    _hold_for(clock, {len(page): 1.0}, monkeypatch)
    extract_article(page)
    assert seen == [False], "the record was taken while the extraction lock was still held: it would lengthen every hold"


def test_a_broken_statistic_never_breaks_an_extraction(clock, monkeypatch):
    class _Broken:
        def __enter__(self):
            raise RuntimeError("the statistics lock is broken")

        def __exit__(self, *exc):
            return False

    page = _page(40)
    _hold_for(clock, {len(page): 1.0}, monkeypatch)
    with monkeypatch.context() as scoped:  # undone before the fixture's own teardown resets the window
        scoped.setattr(lock_stats, "_STATS_LOCK", _Broken())
        assert extract_article(page) is not None


def test_the_default_clock_is_a_real_one(monkeypatch):
    """The fake is for exactness; this proves the shipped ``now`` actually moves with time."""
    lock_stats.reset()

    def slow(html, *, url=None):
        time.sleep(0.05)
        return extract_mod.ExtractedDoc("t", "x" * 300, None, None, None, None)

    monkeypatch.setattr(extract_mod, "_extract_locked", slow)
    extract_article(_page(40))
    snap = lock_stats.snapshot()
    lock_stats.reset()
    assert snap["hold_max_s"] >= 0.04 and snap["extractions"] == 1


# --------------------------------------------------------------------------- #
# The pass: the monitor opens the window and writes the snapshot into its summary line.
# --------------------------------------------------------------------------- #


def _monitor():
    return CollectionMonitor(
        governor=BandwidthGovernor(mode="maximum", w_max=4),
        pass_id="lock-stats-pass",
        mode="press",
        rate_fn=lambda: 100.0,
        vitals_fn=lambda: {"cpu_sys_pct": 20.0, "cpu_proc_pct": 10.0, "mem_avail_mb": 4000.0, "rss_mb": 200.0},
        writer_stats_fn=lambda: {"waiters": 0, "total_wait_s": 0.0, "peak_waiters": 0},
    )


def test_the_pass_summary_carries_the_extraction_lock_block(clock, monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    page = _page(64)
    _hold_for(clock, {len(page): 85.0}, monkeypatch)
    mon = _monitor()
    mon.start()
    try:
        extract_article(page)
        mon._tick()
    finally:
        summary = mon.stop(result={"articles_stored": 1, "sources_processed": 1, "pages_fetched": 1})
    block = summary["extraction_lock"]
    assert block["extractions"] == 1
    assert block["hold_max_s"] == 85.0 and block["hold_max_html_utf8_bytes"] == len(page.encode("utf-8"))
    on_disk = [r for r in recent_samples() if r.get("kind") == "summary"]
    assert on_disk and on_disk[-1]["extraction_lock"] == block, "the block must reach collect_perf.jsonl, the file the bundle carries"


def test_the_window_opens_when_the_pass_starts_so_an_earlier_pass_does_not_leak(clock, monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    page = _page(64)
    _hold_for(clock, {len(page): 85.0}, monkeypatch)
    extract_article(page)  # before the pass: a previous pass's, or a manual add's
    mon = _monitor()
    mon.start()
    try:
        mon._tick()
    finally:
        summary = mon.stop(result=None)
    assert summary["extraction_lock"] == {"extractions": 0}


def test_a_pass_that_cannot_read_the_statistic_says_which_failure_not_a_zero(clock, monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))

    def boom():
        raise RuntimeError("secret words that must not reach the record")

    monkeypatch.setattr(lock_stats, "snapshot", boom)
    mon = _monitor()
    mon._tick()
    summary = mon._write_summary(None)
    assert summary["extraction_lock"] == {"unavailable": "RuntimeError"}
    assert "secret words" not in json.dumps(summary)
