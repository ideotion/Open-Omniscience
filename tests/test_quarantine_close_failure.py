"""A session that fails to close after a quarantine run finished its work (row 177).

The worker closes its session in a ``finally`` after writing the run's final state. A close that raised
there turned a finished run into ``error`` -- resumable, and shown to the user as failed -- and wrote back
the state file the finished run had just cleared. The close failure is now logged and the run stays done.
"""

from __future__ import annotations

import logging

from src.analytics import quarantine_job as qj


def _work(session, **kw):
    return {"scanned": 3, "quarantined": 1, "already_quarantined": 0, "newly_written": 0,
            "by_reason": {"x": 1}, "last_id": 9, "done": True, "write": False}


class _StuckSession:
    def close(self) -> None:
        raise RuntimeError("the connection could not be returned")


def _finished_run(tmp_path, session_cls):
    mgr = qj.QuarantineJobManager(state_path=tmp_path / "q.json")
    mgr._state, mgr._cursor, mgr._total, mgr._done = "paused", 5, 20, 5
    mgr._tally = {"scanned": 5}
    mgr._work_fn = _work
    mgr._session_factory = session_cls
    mgr.resume()
    assert mgr._thread is not None
    mgr._thread.join(30)
    return mgr


def test_a_close_failure_after_the_work_leaves_the_run_done(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="src.analytics.quarantine_job"):
        mgr = _finished_run(tmp_path, _StuckSession)
    st = mgr.status()
    assert st["state"] == "done", st
    assert st["tally"]["scanned"] == 8
    assert not (tmp_path / "q.json").exists(), "a finished run's state file stays cleared"
    assert any("did not close" in r.getMessage() for r in caplog.records), "the close failure is logged"
    try:
        mgr.resume()
    except RuntimeError:
        pass
    else:
        raise AssertionError("a finished run must not be resumable")


def test_a_failing_batch_is_still_reported_as_the_error_not_the_close(tmp_path):
    def broken(session, **kw):
        raise ValueError("batch failed")

    mgr = qj.QuarantineJobManager(state_path=tmp_path / "q.json")
    mgr._state, mgr._cursor, mgr._total, mgr._done = "paused", 5, 20, 5
    mgr._work_fn = broken
    mgr._session_factory = _StuckSession
    mgr.resume()
    assert mgr._thread is not None
    mgr._thread.join(30)
    assert mgr.status()["state"] == "error"
    err = str(mgr.status()["error"])
    assert "batch failed" in err, err
    assert "could not be returned" not in err, "the close failure never replaces the batch's error"
