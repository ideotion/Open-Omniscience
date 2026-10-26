"""The governor's closed windows travel in the diagnostics (R181: a slow-network zip is what answers the cross-pass question).

The log has one row per 1.5 s tick; a window record rides the one tick that closed a window. The newest ticks a diagnostics copy
keeps hold one window or none, so ``window_history`` reads the whole log for them, and the copies pay for the rows with ticks."""

import json

from src.monitoring import collect_perf as cp

_TICK = {"ts": "2026-10-17T22:52:30.053+00:00", "pass_id": "2026-10-17T22:48:26+00:00", "permits": 4, "permits_next": 5,
         "articles_stored": 417, "download_rate_kbps": 3726.5}
_WINDOW = {"signal": "articles/min", "rate": 104.0, "prev_rate": None, "articles": 417, "sources": 139, "elapsed_s": 240.6,
           "collector_kbps": 2138.5, "ticks": 154, "writer_saturated_share": 0.32, "cpu_saturated_share": 0.0, "decision": "hill-up"}


def _log(tmp_path, monkeypatch, lines):
    path = tmp_path / "collect_perf.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(cp, "_log_path", lambda: path)


def _row(**kw):
    return json.dumps({**_TICK, **kw}, separators=(",", ":"))


def test_window_history_reads_only_the_rows_that_closed_a_window_oldest_first_with_the_permits_beside_the_decision(tmp_path, monkeypatch):
    lines = [_row(), _row(permits=5, gov_window={**_WINDOW, "decision": "hill-up", "rate": 104.0}), _row(),
             _row(permits=5, permits_next=5, gov_window={**_WINDOW, "decision": "hold", "rate": 108.0, "prev_rate": 104.0})]
    _log(tmp_path, monkeypatch, lines)
    h = cp.window_history()
    got = h["windows"]
    assert [w["decision"] for w in got] == ["hill-up", "hold"]
    assert got[1]["permits"] == 5 and got[1]["permits_next"] == 5 and got[1]["rate"] == 108.0 and got[1]["prev_rate"] == 104.0
    assert got[0]["pass_id"] == _TICK["pass_id"] and got[0]["articles_stored"] == 417 and got[0]["signal"] == "articles/min"
    # the tick's instantaneous rate is named as the closing tick's, beside the window's own mean
    assert got[0]["closing_tick_kbps"] == 3726.5 and got[0]["collector_kbps"] == 2138.5 and "download_rate_kbps" not in got[0]
    assert (h["held"], h["kept"], h["partial"], h["reason"]) == (2, 2, False, None)
    newest = cp.window_history(limit=1)
    assert newest["windows"] == got[-1:] and (newest["held"], newest["kept"], newest["partial"]) == (2, 1, True)
    assert cp.window_history(limit=0)["windows"] == []


def test_window_history_skips_a_damaged_row_and_says_which_empty_it_is(tmp_path, monkeypatch):
    bad = b'\xff\xfe "gov_window" torn\n'
    path = tmp_path / "collect_perf.jsonl"
    path.write_bytes(b'{"gov_window": {"decision": "hold"\n' + json.dumps(_TICK | {"gov_window": "not a dict"}).encode() + b"\n"
                     + b'["gov_window"]\n' + bad + json.dumps(_TICK | {"gov_window": _WINDOW}).encode() + b"\n")
    monkeypatch.setattr(cp, "_log_path", lambda: path)
    h = cp.window_history()
    # one bad line, whatever it is, costs only itself: not the history, and the count of what was skipped is stated
    assert [w["decision"] for w in h["windows"]] == ["hill-up"] and h["skipped_rows"] == 4 and h["partial"] is False
    _log(tmp_path, monkeypatch, [_row(), _row()])
    h = cp.window_history()
    assert h["windows"] == [] and h["held"] == 0 and "no window closed" in h["reason"]
    monkeypatch.setattr(cp, "_log_path", lambda: tmp_path / "absent.jsonl")
    h = cp.window_history()
    # no log is not "no windows": unknown is null with its reason
    assert h["windows"] is None and h["held"] is None and "no collection-performance log" in h["reason"]


def test_a_log_that_cannot_be_read_is_unknown_with_its_reason_not_an_empty_history(tmp_path, monkeypatch):
    (tmp_path / "dir.jsonl").mkdir()
    monkeypatch.setattr(cp, "_log_path", lambda: tmp_path / "dir.jsonl")
    h = cp.window_history()
    assert h["windows"] is None and "could not be read" in h["reason"]


def _real_window_and_tick(tmp_path, monkeypatch):
    """A window record from the governor's own ``_window_step`` and a tick row from ``CollectionMonitor._tick`` with no vitals at all
    (psutil is an optional extra, so every vitals field is None: the least a real row carries)."""
    from src.scheduler.bandwidth import BandwidthGovernor

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    gov = BandwidthGovernor(mode="maximum", w_max=50)
    mon = cp.CollectionMonitor(governor=gov, pass_id="2026-10-17T22:48:26+00:00", mode="rss", rate_fn=lambda: 0.0,
                               vitals_fn=lambda: {}, writer_stats_fn=lambda: {})
    mon._tick()
    line = cp._log_path().read_text(encoding="utf-8").splitlines()[-1]
    return gov, json.loads(line), len(line) + 1


#: The least a MAXIMUM-MODE tick row measured when the windows were paid for: the event-loop watchdog measuring, no vitals (Export's
#: re-measure of #1464: production ticks 1,653 B or more; a target-mode tick with no vitals 1,478 B, which only a log mixing both modes could
#: make the newest ticks given up, so that paper case is not covered). The tick this test builds, ``_real_window_and_tick``, has no
#: ``start()`` and so is not the least. A RECORDED constant, not the live tick: a later trim of the tick only makes the zip smaller than it
#: was when the trade was made, and a pin against the live tick would fail on that.
_LEAST_TICK_BYTES_AT_THE_TRADE = 1552


def test_the_window_rows_cost_no_more_bytes_than_the_ticks_each_copy_gave_up(tmp_path, monkeypatch):
    """The budget is the serialised bytes of the largest shape, not a count: a window row at its widest (every number at its longest,
    the shape taken from the governor's own record) plus the member's envelope, against the ticks each copy gave up at the least a real tick
    measured. Uncompressed ``debug-bundle.json`` bytes: the archive deflates it, which is not the claim."""
    from src.api import diagnostics as d
    from src.scheduler.bandwidth import BandwidthGovernor

    _gov, tick_row, _tick_bytes = _real_window_and_tick(tmp_path, monkeypatch)
    # the fixture's window carries exactly the keys the governor writes, so a new field cannot slip into every row unmeasured
    from tests.test_bandwidth_governor import _windows

    real = BandwidthGovernor(mode="maximum", w_max=50)
    _windows(real, [100.0])
    assert set(real.last_window) == set(_WINDOW)
    widest = {**{k: tick_row.get(k) for k in cp._WINDOW_ROW_TICK_KEYS}, "closing_tick_kbps": 99999.9, **_WINDOW,
              "permits": 50, "permits_next": 50, "articles_stored": 99999999, "rate": 9999.9, "prev_rate": 9999.9, "articles": 99999,
              "sources": 99999, "elapsed_s": 3599.9, "collector_kbps": 99999.9, "ticks": 99999, "writer_saturated_share": 0.99,
              "cpu_saturated_share": 0.99, "decision": "saturated-at-floor"}
    row = len(json.dumps(widest, separators=(",", ":"))) + 1
    envelope = len(json.dumps({"windows": [], "held": 99999, "kept": 99999, "partial": True, "reason": None, "skipped_rows": 99999}))
    # the two keys that carry the windows, which the feature adds beside the rows
    envelope += len('"collect_perf_windows":') + len('"collect_perf_newest_windows":11,')
    assert d._DEBUG_BUNDLE_SLIM_PERF_WINDOWS * row + envelope <= (
        d._DEBUG_BUNDLE_SLIM_PERF_TICKS_NO_WINDOWS - d._DEBUG_BUNDLE_SLIM_PERF_TICKS) * _LEAST_TICK_BYTES_AT_THE_TRADE
    assert d._DEBUG_BUNDLE_PERF_WINDOWS * row + envelope <= (
        d._DEBUG_BUNDLE_PERF_TICKS_NO_WINDOWS - d._DEBUG_BUNDLE_PERF_TICKS) * _LEAST_TICK_BYTES_AT_THE_TRADE
