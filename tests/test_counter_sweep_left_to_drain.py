"""Row 422 P6: a committing import whose re-index is deferred leaves its counter sweep to the drain.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The per-item ``keyword_counter_reconcile`` stage ran a whole-corpus sweep (capped at 30 s) on every queue item, and the
deferred drain's closing sweep (``finish_deferral``: restart, no budget) then reconciled every counter again. Measured
on the row 422 bench: 30.2 of 212 s. The commit now leaves it to the drain, under Plan's four conditions:

(a) only from a caller that starts the drain after the import (the flag, set from ``defer_reindex()`` beside
    ``hand_off_reindex``, which now starts the drain for the sweep even with no article pending);
(b) the R22 marker is opened and COMMITTED before the skip, and a process killed before the closing sweep leaves it open;
    the next start finds it and starts the drain for the sweep alone (``main._resume_counter_sweep_at_boot``);
(c) every surface reading the counters through ``counter_envelope`` says ``estimated`` while it is open;
(d) measured before and after on the row 422 bench (the PR body).
"""

from __future__ import annotations

import inspect
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _marker_closed_before_and_after():
    _close_marker()
    yield
    _close_marker()


def _close_marker() -> None:
    from src.analytics.counter_deferral import close_deferral
    from src.database.session import session_scope

    try:
        with session_scope() as s:
            close_deferral(s)
    except Exception:  # noqa: BLE001 - a store not created yet has no marker to close
        pass


def _marker_open() -> bool:
    from src.analytics.counter_deferral import is_deferral_open
    from src.database.session import session_scope

    with session_scope() as s:
        return is_deferral_open(s)


def _basis() -> str:
    from src.analytics.store import counter_envelope
    from src.database.session import session_scope

    with session_scope() as s:
        return counter_envelope(s).to_dict()["basis"]


def _commit(monkeypatch, *, left: bool) -> tuple[dict, list[int]]:
    from src.analytics import store
    from src.backup.artifact import cleanup_staging, read_artifact, write_backup_v2
    from src.backup.merge import run_restore

    calls: list[int] = []
    real = store.reconcile_keyword_counters

    def _spy(session, **kw):
        calls.append(1)
        return real(session, **kw)

    monkeypatch.setattr(store, "reconcile_keyword_counters", _spy)
    dest = Path(os.environ["OO_DATA_DIR"]).parent / f"p6-{os.getpid()}-{left}.oobak"
    dest.unlink(missing_ok=True)
    write_backup_v2(dest)
    staged = read_artifact(dest.read_bytes(), None, None)
    try:
        report = run_restore(staged, commit=True, reindex_imported=False, counters_left_to_drain=left)
    finally:
        cleanup_staging(staged)
        dest.unlink(missing_ok=True)
    return report, calls


def test_a_commit_that_leaves_the_sweep_opens_the_marker_first_and_skips_it(client, monkeypatch):
    report, calls = _commit(monkeypatch, left=True)
    assert report["committed"] is True
    kc = report["keyword_counters"]
    assert kc["left_to_drain"] is True and kc["reconciled"] is False and kc["estimated_since"]
    assert not calls, "the sweep is the drain's: the commit must not run it as well"
    assert _marker_open(), "the R22 marker is what keeps the counters honest until the drain's sweep"
    assert _basis() == "estimated"
    assert report["timings"]["stages"]["keyword_counter_reconcile"] >= 0, "still a named, timed stage"


def test_without_the_flag_the_sweep_runs_exactly_as_before(client, monkeypatch):
    report, calls = _commit(monkeypatch, left=False)
    assert report["committed"] is True
    assert calls == [1]
    assert "left_to_drain" not in report["keyword_counters"]
    assert not _marker_open()


def test_a_marker_that_cannot_be_opened_means_the_sweep_runs_here(client, monkeypatch):
    from src.analytics import counter_deferral

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(counter_deferral, "open_deferral", _boom)
    report, calls = _commit(monkeypatch, left=True)
    assert report["committed"] is True
    assert calls == [1], "no marker, no skip: an unmarked skip would read exact over unreconciled counters"
    assert "left_to_drain" not in report["keyword_counters"]


def test_a_process_killed_after_the_skip_leaves_the_marker_and_the_next_start_sweeps(client, monkeypatch):
    """Condition (b) with a real kill: the marker is committed before the stage returns, so SIGKILL right after it
    leaves it open on disk; the next start reads it and starts the drain for the sweep alone, whose closing sweep then
    reconciles and closes it."""
    code = (
        "import os, signal\n"
        "from src.backup.merge import _leave_counters_to_drain\n"
        "assert _leave_counters_to_drain() is not None\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=dict(os.environ), capture_output=True, timeout=300, check=False
    )
    assert proc.returncode == -signal.SIGKILL, proc.stderr.decode(errors="replace")[-2000:]
    assert _marker_open(), "the kill came after the commit: the marker must survive it"
    assert _basis() == "estimated"

    from src.api import boot_sequence, main

    started: list[int] = []
    monkeypatch.setattr(
        "src.backup.volume_job.start_reindex_drain", lambda: (started.append(1), (True, None))[1]
    )
    monkeypatch.setitem(boot_sequence._STATE, "reindex_pending", None)
    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    monkeypatch.setenv("OO_REINDEX_AUTORESUME", "1")
    main._resume_counter_sweep_at_boot()
    assert boot_sequence._STATE["reindex_pending"] == 0, "the open marker alone asks for the drain"
    boot_sequence._start_reindex()
    assert started == [1], "with no article pending, the open marker alone must start the drain"

    from src.analytics.store import finish_deferral
    from src.database.session import session_scope

    with session_scope() as s:
        out = finish_deferral(s)
    assert out["complete"] is True and out["closed"] is True
    assert not _marker_open()


def test_with_nothing_owed_the_start_does_not_invent_a_drain(client, monkeypatch):
    from src.api import boot_sequence, main

    monkeypatch.setitem(boot_sequence._STATE, "reindex_pending", None)
    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    monkeypatch.setenv("OO_REINDEX_AUTORESUME", "1")
    main._resume_counter_sweep_at_boot()
    assert boot_sequence._STATE["reindex_pending"] is None


def test_the_boot_ask_keeps_the_opt_outs(client, monkeypatch):
    from src.api import boot_sequence, main
    from src.backup.merge import _leave_counters_to_drain

    assert _leave_counters_to_drain() is not None
    for env in ({"OO_NO_SCHEDULER": "1"}, {"OO_NO_SCHEDULER": "0", "OO_REINDEX_AUTORESUME": "0"}):
        monkeypatch.setitem(boot_sequence._STATE, "reindex_pending", None)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        main._resume_counter_sweep_at_boot()
        assert boot_sequence._STATE["reindex_pending"] is None, env


def test_the_hand_off_starts_the_drain_for_the_sweep_even_with_nothing_pending(monkeypatch):
    from src.backup import volume_job

    monkeypatch.setattr(
        "src.backup.merge.reindex_backlog", lambda: {"available": True, "articles_pending": 0, "batches": []}
    )
    monkeypatch.setattr("src.scheduler.runner.exclusive_window_open", lambda: False)
    started: list[int] = []
    monkeypatch.setattr(volume_job, "start_reindex_drain", lambda: (started.append(1), (True, None))[1])

    report: dict = {"keyword_counters": {"reconciled": False, "left_to_drain": True}}
    volume_job.hand_off_reindex(report)
    assert started == [1]
    assert report["reindex_deferred"]["started"] is True

    started.clear()
    report = {"keyword_counters": {"reconciled": True}}
    volume_job.hand_off_reindex(report)
    assert not started, "nothing pending and no sweep owed: nothing to start, as before"


def _call_args(fn, name: str = "report = run_restore(") -> str:
    src = inspect.getsource(fn)
    i = src.index(name) + len(name)
    depth, j = 1, i
    while depth:
        depth += {"(": 1, ")": -1}.get(src[j], 0)
        j += 1
    return src[i : j - 1]


def test_every_deferring_commit_path_passes_the_flag_from_the_same_switch():
    """Condition (a): the flag rides exactly the switch that makes the caller hand off to the drain."""
    from src.api import backup_v2
    from src.backup import volume_job

    for fn in (backup_v2.restore_legacy_path, volume_job.VolumeBackupManager._run_restore):
        call = _call_args(fn)
        assert "counters_left_to_drain=defer_reindex()" in call, fn.__qualname__
        assert "reindex_imported=not defer_reindex()" in call, fn.__qualname__


def _open_marker() -> None:
    from src.backup.merge import _leave_counters_to_drain

    assert _leave_counters_to_drain() is not None


def test_the_graph_and_ring_gap_surfaces_say_estimated_while_the_sweep_is_owed(client):
    """Condition (c): the user-visible readers of the maintained counters outside /top and /supergroups carry the
    envelope, so a deferred sweep reads ``estimated`` there too."""
    _open_marker()
    for url in ("/api/insights/graph?level=family", "/api/insights/graph?level=supergroup", "/api/insights/ring-gaps"):
        r = client.get(url)
        assert r.status_code == 200, (url, r.text[:300])
        assert (r.json().get("counts") or {}).get("basis") == "estimated", url
    windowed = client.get("/api/insights/graph?level=family&days=7").json()
    assert "counts" not in windowed, "a windowed graph reads the mentions, not the counters"


def test_a_warmed_top_carries_the_same_envelope(client):
    from src.api import insights
    from src.database.session import session_scope

    _open_marker()
    insights._read_cache.clear()
    with session_scope() as s:
        insights.warm_cache(s)
    body = client.get("/api/insights/top?group=true&limit=20").json()
    assert (body.get("counts") or {}).get("basis") == "estimated"


def test_the_card_audit_and_engine_report_state_the_counters_basis():
    from types import SimpleNamespace

    from src.analytics.engine_report import _counter_basis as engine_basis
    from src.briefing.card_audit import _keyword_facts
    from src.database.session import session_scope

    _open_marker()
    with session_scope() as s:
        assert engine_basis(s)["basis"] == "estimated"
        facts = _keyword_facts(s, SimpleNamespace(key="anything-not-a-keyword-p6"))
    assert facts["matched"] is False  # an unmatched key has no counters to disclose
    import inspect

    from src.briefing import card_audit

    assert '"counts": _counter_basis_once(session)' in inspect.getsource(card_audit._keyword_facts)


def test_an_unreadable_backlog_sweeps_in_the_import_instead_of_a_drain_that_would_stop_first(client, monkeypatch):
    from src.backup import volume_job

    _open_marker()
    monkeypatch.setattr("src.backup.merge.reindex_backlog", lambda: {"available": False, "reason": "locked"})
    monkeypatch.setattr("src.scheduler.runner.exclusive_window_open", lambda: False)
    started: list[int] = []
    monkeypatch.setattr(volume_job, "start_reindex_drain", lambda: (started.append(1), (True, None))[1])
    report: dict = {"keyword_counters": {"reconciled": False, "left_to_drain": True}}
    volume_job.hand_off_reindex(report)
    assert not started, "a drain that cannot read its backlog never reaches its closing sweep"
    assert report["keyword_counters"]["swept_in_import"] is True
    assert report["keyword_counters"]["reconciled"] is True
    assert not _marker_open()


def test_the_disclosure_readers_honour_a_deadline_and_never_fail_a_preview(client, monkeypatch):
    from src.analytics import engine_report, queries, store
    from src.briefing import card_audit
    from src.database.maintenance import StatementTimeout
    from src.database.session import session_scope

    def _deadline(*_a, **_k):
        raise StatementTimeout("deadline")

    monkeypatch.setattr(store, "counter_envelope", _deadline)
    with session_scope() as s:
        for fn in (queries._counter_basis, engine_report._counter_basis, card_audit._counter_basis):
            with pytest.raises(StatementTimeout):
                fn(s)

    def _boom(*_a, **_k):
        raise RuntimeError("locked")

    monkeypatch.setattr(store, "counter_envelope", _boom)
    r = client.get("/api/insights/ring-gaps")
    assert r.status_code == 200 and "counts" not in r.json()


def test_a_sweep_only_drain_at_boot_still_queues_the_builds_that_wait_for_a_reindex(monkeypatch):
    from src.api import boot_sequence

    queued: list[str] = []
    monkeypatch.setattr(boot_sequence, "_queue_title_index", lambda: None)
    monkeypatch.setattr(boot_sequence, "_queue_keyword_index_heal", lambda: queued.append("heal"))
    monkeypatch.setattr(boot_sequence, "_queue_day_counts", lambda: queued.append("day"))
    monkeypatch.setattr("src.backup.volume_job.start_reindex_drain", lambda: (True, None))
    monkeypatch.setitem(boot_sequence._STATE, "reindex_pending", 0)
    boot_sequence._start_reindex()
    assert sorted(queued) == ["day", "heal"]
    queued.clear()
    monkeypatch.setitem(boot_sequence._STATE, "reindex_pending", 5)
    boot_sequence._start_reindex()
    assert queued == [], "a real re-index still holds them back"


def test_the_triage_proposal_states_the_counters_basis():
    import inspect

    from src.ai_layer import triage_proposal

    assert '"counts": _counter_basis(session)' in inspect.getsource(triage_proposal.build_triage_proposal)
