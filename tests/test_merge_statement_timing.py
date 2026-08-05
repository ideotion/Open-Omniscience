"""A merge step names WHICH of its statements is slow, not just that it is running.

The 2026-08-04 field import spent 50,708 s inside merge step 3 and was killed
without finishing. ``_step_watch``'s tick proved the step was executing -- a real
gain over the sixteen hours of unchanging "2/19" before it -- but step 3 runs six
statements, and a step-level tick cannot say which one. So a 14 h step still left
nothing to act on.

SQLite's trace callback fires once per statement START, so statement N ends when
N+1 begins. These tests pin that the timing is ATTRIBUTED to the right statement,
that the last statement in a step is reported at all, and that a statement in
flight is announced BEFORE it finishes -- the last one because the run that
motivated this was killed mid-statement and never reached any exit path.
"""

from __future__ import annotations

import sqlite3
import time

from src.backup.merge import _step_watch, _stmt_label


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    con.executemany("INSERT INTO t VALUES (?, ?)", [(i, "x" * 40) for i in range(500)])
    return con


def _collect():
    ended: list[tuple[str, float]] = []
    began: list[str] = []

    def cb(step, name, label, seconds, begin):  # noqa: ANN001
        (began.append(label) if begin else ended.append((label, seconds)))

    return cb, began, ended


def test_label_is_short_and_whitespace_collapsed() -> None:
    assert _stmt_label("SELECT\n   a,\tb\n FROM t") == "SELECT a, b FROM t"
    assert len(_stmt_label("SELECT " + "x" * 500)) <= 120


def test_every_statement_in_the_step_is_reported() -> None:
    con = _con()
    cb, began, ended = _collect()
    with _step_watch(con, 3, 19, "articles", None, None, cb):
        con.execute("SELECT COUNT(*) FROM t").fetchone()
        con.execute("SELECT SUM(a) FROM t").fetchone()
    labels = [lbl for lbl, _ in ended]
    assert "SELECT COUNT(*) FROM t" in labels
    # The LAST statement has no successor to end it; the context manager's exit
    # must close it out or the slowest statement in a step could vanish.
    assert "SELECT SUM(a) FROM t" in labels
    assert began  # a statement in flight is announced before it completes


def test_time_is_attributed_to_the_statement_that_actually_spent_it() -> None:
    """The whole point: a slow statement beside fast ones must be the one named.

    Without attribution this is just a step timer with extra steps.
    """
    con = _con()
    con.create_function("slow", 0, lambda: time.sleep(0.25) or 1)
    cb, _began, ended = _collect()
    with _step_watch(con, 3, 19, "articles", None, None, cb):
        con.execute("SELECT COUNT(*) FROM t").fetchone()
        con.execute("SELECT slow()").fetchone()
        con.execute("SELECT MAX(a) FROM t").fetchone()

    by_label = {lbl: sec for lbl, sec in ended}
    slow = by_label["SELECT slow()"]
    assert slow >= 0.2, by_label
    for lbl, sec in by_label.items():
        if lbl != "SELECT slow()":
            assert sec < slow, f"{lbl} ({sec}s) should be faster than the slow one"


def test_a_statement_interrupted_by_stop_is_still_named() -> None:
    """A stop lands INSIDE a statement -- that statement is the one worth naming."""
    con = _con()
    con.execute("CREATE TABLE big (a)")
    con.executemany("INSERT INTO big VALUES (?)", [(i,) for i in range(4000)])
    cb, _began, ended = _collect()
    from src.backup.merge import MergeStepStopped

    try:
        with _step_watch(con, 3, 19, "articles", lambda: True, None, cb):
            con.execute("SELECT COUNT(*) FROM big a, big b").fetchone()
    except MergeStepStopped:
        pass
    assert any("big" in lbl for lbl, _ in ended), ended


def test_a_raising_callback_never_breaks_the_step() -> None:
    """Reporting is report-only, in this direction too."""
    con = _con()

    def boom(*_a, **_k):
        raise RuntimeError("reporting exploded")

    with _step_watch(con, 3, 19, "articles", None, None, boom):
        assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 500


def test_the_step_still_works_without_a_statement_callback() -> None:
    """stmt_cb is optional: existing callers pass six args and must be unaffected."""
    con = _con()
    with _step_watch(con, 3, 19, "articles", None, None):
        assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 500


def test_the_trace_hook_is_removed_when_the_step_ends() -> None:
    """A left-behind trace callback would report every later statement as this step."""
    con = _con()
    cb, _began, ended = _collect()
    with _step_watch(con, 3, 19, "articles", None, None, cb):
        con.execute("SELECT COUNT(*) FROM t").fetchone()
    n_after_step = len(ended)
    con.execute("SELECT COUNT(*) FROM t").fetchone()
    assert len(ended) == n_after_step
