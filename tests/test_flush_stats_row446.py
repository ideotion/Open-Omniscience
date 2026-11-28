"""Row 446: a collector flush reports where it held the single-writer gate, and the pass summary carries it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pinned here:

- the window's arithmetic: flushes, articles, the hold's total, mean and longest, and the seconds of each phase;
- a real batched flush records ONE entry whose gate phases (insert, index, links, commit) add up to its hold, beside the
  phases that run outside the gate;
- a flush that fails and is redone article by article records nothing;
- the collection monitor resets the window when a pass starts and writes it into the pass summary as ``collector_flush``.
"""

from __future__ import annotations

import pytest

from src.ingest import flush_stats
from tests.test_collect_extraction_outside_gate import _ingest


@pytest.fixture(autouse=True)
def _fresh_window():
    flush_stats.reset()
    yield
    flush_stats.reset()


def test_the_window_sums_flushes_and_keeps_the_longest_hold():
    flush_stats.record({"insert": 0.5, "index": 2.0, "links": 0.25, "commit": 1.0, "precompute": 3.0}, articles=8, hold_s=3.75)
    flush_stats.record({"insert": 0.1, "index": 0.4, "commit": 0.2, "unknown": 9.0}, articles=2, hold_s=0.7)
    snap = flush_stats.snapshot()
    assert snap["flushes"] == 2 and snap["articles"] == 10
    assert snap["hold_total_s"] == pytest.approx(4.45)
    assert snap["hold_mean_s"] == pytest.approx(2.225)
    assert snap["hold_max_s"] == pytest.approx(3.75) and snap["hold_max_articles"] == 8
    assert snap["phases_s"]["index"] == pytest.approx(2.4)
    assert snap["phases_s"]["precompute"] == pytest.approx(3.0)
    assert set(snap["phases_s"]) == set(flush_stats.PHASES), "an unknown phase name is ignored, never added"
    assert snap["method"] == flush_stats.METHOD


def test_an_empty_window_says_so_and_carries_no_mean():
    snap = flush_stats.snapshot()
    assert snap["flushes"] == 0 and "hold_mean_s" not in snap
    flush_stats.record({"commit": 1.0}, articles=1, hold_s=1.0)
    flush_stats.reset()
    assert flush_stats.snapshot()["flushes"] == 0


def test_a_batched_flush_records_its_gate_phases(monkeypatch):
    _dom, _src_id, tally = _ingest(monkeypatch, n=4, batch="4")
    assert tally["stored"] == 4
    snap = flush_stats.snapshot()
    assert snap["flushes"] == 1 and snap["articles"] == 4, snap
    ph = snap["phases_s"]
    inside = ph["insert"] + ph["index"] + ph["links"] + ph["commit"]
    # The hold is one interval; its four parts are read off the same clock, so they add up to it within rounding.
    assert inside == pytest.approx(snap["hold_total_s"], abs=0.005)
    assert ph["index"] > 0 and ph["commit"] > 0, "ANTI-VACUITY: the flush indexed and committed"
    assert ph["precompute"] > 0, "the extraction ran, outside the gate"


def test_a_failed_flush_redone_one_by_one_records_nothing(monkeypatch):
    from src.ingest import batch as batch_mod

    def boom(self, entries):  # noqa: ANN001, ANN202
        raise RuntimeError("the batched commit failed")

    monkeypatch.setattr(batch_mod.ArticleBatch, "_flush_batched", boom)
    _dom, _src_id, tally = _ingest(monkeypatch, n=3, batch="3")
    assert tally["stored"] == 3, "the redo path stored every article"
    assert flush_stats.snapshot()["flushes"] == 0


def test_the_pass_summary_carries_the_window(tmp_path, monkeypatch):
    import json

    from src.monitoring import collect_perf as cp
    from src.scheduler.bandwidth import BandwidthGovernor

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    flush_stats.record({"commit": 1.0}, articles=1, hold_s=1.0)  # before the pass: not this pass's
    mon = cp.CollectionMonitor(
        governor=BandwidthGovernor(mode="maximum", w_max=50), pass_id="row446", mode="rss", interval_s=3600.0,
        rate_fn=lambda: 0.0, vitals_fn=lambda: {}, writer_stats_fn=lambda: {},
    )
    mon.start()
    try:
        assert flush_stats.snapshot()["flushes"] == 0, "a pass starts a new window"
        flush_stats.record({"insert": 0.2, "index": 0.5, "commit": 0.3}, articles=8, hold_s=1.0)
        mon._tick()  # a summary is written only for a pass that ticked
    finally:
        summary = mon.stop()
    assert summary is not None
    block = summary["collector_flush"]
    assert block["flushes"] == 1 and block["articles"] == 8 and block["hold_mean_s"] == pytest.approx(1.0)
    rows = [json.loads(ln) for ln in (tmp_path / "collect_perf.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["kind"] == "summary" and rows[-1]["collector_flush"]["flushes"] == 1
