"""The boot sequence's row for a step says why the step ended as it did.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-10-16, a running install: the rollup step read "declined" after 921 s and the row said nothing else; the reason
was in another report's block and a later, unrelated check had overwritten it. The row now carries the decline's own
codes and numbers, and a step that raised carries the exception's CLASS only.
"""

from __future__ import annotations

import pytest

from src.analytics import rollup_serve
from src.api import boot_sequence as bs


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    keep = {k: rollup_serve._STATE[k] for k in ("last_skip", "stopped", "last_decline")}
    rollup_serve._STATE.update(last_skip=None, stopped=None, last_decline=None)
    bs._reset()
    monkeypatch.setattr(rollup_serve, "serve_enabled", lambda: True)
    yield
    rollup_serve._STATE.update(keep)
    bs._reset()


def _row():
    return {r["step"]: r for r in bs.snapshot()["steps"]}["rollup"]


def test_a_declined_rollup_row_carries_the_stop_it_was_declined_for(monkeypatch):
    monkeypatch.setattr(rollup_serve, "build_now_and_wait", lambda: "declined")
    rollup_serve._STATE["last_decline"] = {
        "kind": "stopped", "source": "build", "reason": "duckdb-limit", "stage": "aggregate", "at": 1.0,
        "duckdb_limit_mb": 1005.0, "error": "Out of Memory Error: engine words", "repeats": 0,
    }
    rollup_serve._STATE["last_skip"] = {"reason": "exclusive-hold"}  # the later, unrelated check that hid it
    bs._timed("rollup", bs._rollup_first_build, holds="the re-index")
    row = _row()
    assert row["state"] == "declined"
    assert row["detail"]["reason"] == "duckdb-limit" and row["detail"]["stage"] == "aggregate"
    assert row["detail"]["duckdb_limit_mb"] == 1005.0 and row["detail"]["source"] == "build"
    assert "error" not in row["detail"], "an engine's own text is not a boot row"


def test_a_boot_build_declined_by_the_moment_is_not_named_for_an_older_sticky_reason(monkeypatch):
    monkeypatch.setattr(rollup_serve, "build_now_and_wait", lambda: "declined")
    rollup_serve._STATE["last_decline"] = {"kind": "skipped", "source": "memory", "reason": "mem-low", "at": 1.0}
    rollup_serve._STATE["last_skip"] = {"reason": "exclusive-hold", "source": "exclusive", "at": 2.0}
    bs._timed("rollup", bs._rollup_first_build, holds="the restore")
    d = _row()["detail"]
    assert d["reason"] == "exclusive-hold" and d["source"] == "exclusive"


def test_a_decline_with_no_sticky_record_falls_back_to_what_declined_last(monkeypatch):
    monkeypatch.setattr(rollup_serve, "build_now_and_wait", lambda: "declined")
    rollup_serve._STATE["last_skip"] = {"reason": "boot_order", "at": 2.0}
    bs._timed("rollup", bs._rollup_first_build, holds="x")
    assert _row()["detail"]["reason"] == "boot_order"


def test_a_decline_nobody_recorded_says_so_rather_than_nothing(monkeypatch):
    monkeypatch.setattr(rollup_serve, "build_now_and_wait", lambda: "declined")
    bs._timed("rollup", bs._rollup_first_build, holds="x")
    assert _row()["detail"]["reason"] == "unknown"


def test_a_restored_stop_is_named_as_one_in_the_row(monkeypatch):
    monkeypatch.setattr(rollup_serve, "build_now_and_wait", lambda: "declined")
    rollup_serve._STATE["last_decline"] = {"kind": "skipped", "source": "stopped", "reason": "duckdb-limit", "restored": True}
    bs._timed("rollup", bs._rollup_first_build, holds="x")
    assert _row()["detail"]["restored"] is True


def test_a_step_that_raised_shows_the_class_and_not_the_message(monkeypatch):
    def boom():
        raise OSError("/home/someone/secret-corpus.db is unreadable")

    bs._timed("rollup", boom, holds="x")
    row = _row()
    assert row["state"] == "failed" and row["detail"] == {"error": "OSError"}
    assert "secret" not in repr(bs.snapshot())


def test_a_step_that_finishes_has_no_detail_and_a_rerun_clears_an_old_one(monkeypatch):
    monkeypatch.setattr(rollup_serve, "build_now_and_wait", lambda: "declined")
    bs._timed("rollup", bs._rollup_first_build, holds="x")
    assert _row()["detail"] is not None
    monkeypatch.setattr(rollup_serve, "build_now_and_wait", lambda: "built")
    bs._timed("rollup", bs._rollup_first_build, holds="x")
    row = _row()
    assert row["state"] == "done" and row["detail"] is None
