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
    got = cp.window_history()
    assert [w["decision"] for w in got] == ["hill-up", "hold"]
    assert got[1]["permits"] == 5 and got[1]["permits_next"] == 5 and got[1]["rate"] == 108.0 and got[1]["prev_rate"] == 104.0
    assert got[0]["pass_id"] == _TICK["pass_id"] and got[0]["articles_stored"] == 417 and got[0]["signal"] == "articles/min"
    assert cp.window_history(limit=1) == got[-1:] and cp.window_history(limit=0) == []


def test_window_history_skips_a_damaged_row_and_says_nothing_for_a_missing_or_window_free_log(tmp_path, monkeypatch):
    _log(tmp_path, monkeypatch, ['{"gov_window": {"decision": "hold"', _row(gov_window="not a dict"), _row(gov_window=_WINDOW)])
    assert [w["decision"] for w in cp.window_history()] == ["hill-up"]
    _log(tmp_path, monkeypatch, [_row(), _row()])
    assert cp.window_history() == []
    monkeypatch.setattr(cp, "_log_path", lambda: tmp_path / "absent.jsonl")
    assert cp.window_history() == []


def test_the_window_rows_cost_no_more_bytes_than_the_ticks_each_copy_gave_up():
    """The budget is the serialised bytes of the largest shape, not a count: a window row at its widest (every number at its
    longest) against a tick row at the least a real one measured (1,650 B: the Lenovo bundle's 330 KB over 200 ticks)."""
    from src.api import diagnostics as d

    widest = {**_TICK, **_WINDOW, "permits": 50, "permits_next": 50, "articles_stored": 99999999, "download_rate_kbps": 99999.9,
              "rate": 9999.9, "prev_rate": 9999.9, "articles": 99999, "sources": 99999, "elapsed_s": 3599.9,
              "collector_kbps": 99999.9, "ticks": 99999, "writer_saturated_share": 0.99, "cpu_saturated_share": 0.99,
              "decision": "saturated-at-floor"}
    assert set(widest) == set(cp._WINDOW_ROW_TICK_KEYS) | set(_WINDOW)
    row = len(json.dumps(widest, separators=(",", ":"))) + 1
    tick = 1650
    assert d._DEBUG_BUNDLE_SLIM_PERF_WINDOWS * row <= (20 - d._DEBUG_BUNDLE_SLIM_PERF_TICKS) * tick
    assert d._DEBUG_BUNDLE_PERF_WINDOWS * row <= (200 - d._DEBUG_BUNDLE_PERF_TICKS) * tick
    # and the log can hold no more windows than the whole copy asks for: 240 s is 160 ticks of 1.5 s, in 5,000 rows
    assert d._DEBUG_BUNDLE_PERF_WINDOWS >= cp._CAP_LINES // 160
