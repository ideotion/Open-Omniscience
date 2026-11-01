"""The title index's backfill is queued AFTER the heavy boot steps, never at unlock, and can be declined.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.api import boot_sequence as bs


@pytest.fixture()
def calls(monkeypatch):
    seen: list[str] = []
    import src.api.search_instant as si

    monkeypatch.setattr(si, "start_build_if_incomplete", lambda: seen.append("queued") or "started")
    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    monkeypatch.delenv("OO_TITLE_INDEX_AUTOBUILD", raising=False)
    return seen


def test_it_is_queued_by_the_reindex_step_even_when_no_backlog_is_pending(calls):
    bs._reset()
    with pytest.raises(bs._Skipped):  # no re-index pending: the step itself is skipped ...
        bs._start_reindex()
    assert calls == ["queued"]  # ... and the title index was queued regardless


def test_the_test_suite_and_the_opt_out_decline_it(calls, monkeypatch):
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    bs._queue_title_index()
    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    monkeypatch.setenv("OO_TITLE_INDEX_AUTOBUILD", "0")
    bs._queue_title_index()
    assert calls == []


def test_a_failure_to_queue_never_takes_the_step_down(monkeypatch):
    import src.api.search_instant as si

    def boom():
        raise RuntimeError("no thread")

    monkeypatch.setattr(si, "start_build_if_incomplete", boom)
    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    bs._queue_title_index()  # must not raise
