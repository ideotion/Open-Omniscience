"""PRH-23 — the first-run preflight is a task-manager-visible job, not inline work.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Both halves ran inline on the collect-pass thread. Together they are up to 50 source
checks plus one robots read per feed host plus a per-provider sample -- many minutes
over Tor on a first launch, during which the task manager could show only the coarse
"background" phase. The app was working; it looked stalled.

These pin the four things that make the move honest rather than cosmetic:
the runner really stopped doing it inline; the job declines instead of racing an
exclusive operation; a cancelled half writes NO log (so the next pass retries the whole
set rather than the preflight being silently marked done); and progress is real.
"""

from __future__ import annotations

import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


@pytest.fixture(autouse=True)
def _isolated_preflight_logs(tmp_path, monkeypatch):
    """Both halves key "has this run" off a file in data_dir(), which conftest shares
    across the session -- so without this a preflight test would be decided by whichever
    earlier test happened to write one."""
    from src.monitoring import feed_preflight, preflight

    monkeypatch.setattr(preflight, "_log_path", lambda: tmp_path / "source_preflight.jsonl")
    monkeypatch.setattr(feed_preflight, "_log_path", lambda: tmp_path / "feed_preflight.jsonl")
    return tmp_path


@pytest.fixture()
def _schema():
    """The conftest store is a real (plaintext) file with no schema until something
    creates it; init_db() is the app's own path, so these tests exercise the real one."""
    from src.database.session import init_db

    init_db()


def test_the_runner_no_longer_runs_the_preflight_inline():
    """The pass tail kicks the job; it does not call the preflight functions itself.

    A source guard, because the alternative -- asserting on a live pass -- would need a
    real network run. The two literals it forbids are the exact calls that were there.
    """
    runner = (_SRC / "scheduler" / "runner.py").read_text(encoding="utf-8")
    assert "preflight_job.kick(fetcher)" in runner, (
        "the pass tail must kick the visible job (PRH-23)"
    )
    assert "preflight_sources(session, fetcher)" not in runner, (
        "the source preflight is running INLINE on the pass thread again -- that is the "
        "shape PRH-23 removed: minutes of Tor fetches with no name and no progress."
    )
    assert "run_feed_preflight(fetcher)" not in runner, (
        "the feed preflight is running INLINE on the pass thread again"
    )


def test_the_job_is_registered_so_api_jobs_can_enumerate_it():
    """Registered at import, like every other background job -- no shadow state."""
    from src.jobs.background import get_job
    from src.monitoring import preflight_job

    job = get_job(preflight_job.JOB_KIND)
    assert job is not None, "the job is not in the registry -- /api/jobs cannot show it"
    assert job.cancellable, "both halves check ctx.stopping, so Cancel must be offered"
    assert job.is_writer, "the source half writes SourceMetadata -- it must arbitrate"


def test_the_kick_declines_while_an_exclusive_operation_holds_the_machine(monkeypatch):
    """Gate the ENTRY POINT, not just the loop (the 2026-07-24 lesson).

    A pass already in flight when a restore/import/bundle claims the machine runs on
    into its tail, so this kick can fire under the hold. Declining costs nothing: the
    log is what marks the preflight done, and a declined kick writes none.
    """
    from src.monitoring import preflight_job

    started: list[object] = []
    monkeypatch.setattr(preflight_job, "pending", lambda: True)
    monkeypatch.setattr(
        preflight_job.PREFLIGHT_JOB, "start", lambda **kw: started.append(kw) or {"state": "running"}
    )
    monkeypatch.setattr("src.scheduler.runner.exclusive_window_open", lambda: True)

    assert preflight_job.kick(fetcher=object()) is None
    assert started == [], "the job started while an exclusive operation held the machine"

    # Negative twin: with NO hold it must actually start -- a guard that refuses always
    # would pass the assertion above while disabling the feature outright.
    monkeypatch.setattr("src.scheduler.runner.exclusive_window_open", lambda: False)
    assert preflight_job.kick(fetcher=object()) == {"state": "running"}
    assert len(started) == 1


def test_the_kick_does_nothing_once_both_halves_have_run(_isolated_preflight_logs):
    """Once-only, unchanged: the gate is still the log's existence."""
    from src.monitoring import preflight_job

    assert preflight_job.pending() is True
    (_isolated_preflight_logs / "source_preflight.jsonl").write_text("{}\n", encoding="utf-8")
    (_isolated_preflight_logs / "feed_preflight.jsonl").write_text("{}\n", encoding="utf-8")
    assert preflight_job.pending() is False
    assert preflight_job.kick(fetcher=object()) is None


def test_a_cancelled_source_preflight_writes_no_log_and_reports_incomplete(
    _isolated_preflight_logs, _schema, monkeypatch
):
    """NEGATIVE SPACE: a stopped run must not look like a finished one.

    ``has_run_before()`` reads the log. If a run cancelled after 3 of 50 sources wrote
    its log, the preflight would be marked done with 47 sources never checked and
    nothing would ever go back for them -- a gap published as a success. So a stopped
    run writes NOTHING and says ``complete: False``.
    """
    from src.database.models import Source
    from src.database.session import session_scope
    from src.monitoring import preflight

    monkeypatch.setattr(
        preflight,
        "_check_one",
        lambda fetcher, src: {"domain": src.domain, "verdict": "ok", "robots_allowed": True},
    )

    with session_scope() as db:
        for i in range(4):
            db.add(Source(name=f"pf{i}", domain=f"pf{i}-prh23.example", enabled=True))
        db.commit()

        seen: list[tuple[int, int, str]] = []
        out = preflight.preflight_sources(
            db,
            fetcher=object(),
            progress=lambda d, t, dom: seen.append((d, t, dom)),
            # stop once two have been checked
            should_stop=lambda: len(seen) >= 2,
        )
        db.rollback()

    assert out["complete"] is False
    assert out["checked"] == 2, f"expected to stop after 2, got {out['checked']}"
    assert not (_isolated_preflight_logs / "source_preflight.jsonl").exists(), (
        "a cancelled preflight wrote its log -- has_run_before() would now say it is "
        "done and the unchecked sources would never be revisited"
    )
    from src.monitoring.preflight import has_run_before

    assert has_run_before() is False, "the next pass must retry the whole set"
    assert seen and seen[0][1] >= 4, "progress must report a real total, not 0"


def test_an_uncancelled_source_preflight_still_logs_and_completes(
    _isolated_preflight_logs, _schema, monkeypatch
):
    """The positive twin: the fix must not turn a working preflight into a refusal."""
    from src.database.models import Source
    from src.database.session import session_scope
    from src.monitoring import preflight

    monkeypatch.setattr(
        preflight,
        "_check_one",
        lambda fetcher, src: {"domain": src.domain, "verdict": "ok", "robots_allowed": True},
    )
    with session_scope() as db:
        for i in range(3):
            db.add(Source(name=f"pfok{i}", domain=f"pfok{i}-prh23.example", enabled=True))
        db.commit()
        seen: list[tuple[int, int, str]] = []
        out = preflight.preflight_sources(
            db, fetcher=object(), progress=lambda d, t, dom: seen.append((d, t, dom))
        )
        db.commit()

    assert out["complete"] is True
    assert out["checked"] >= 3
    assert (_isolated_preflight_logs / "source_preflight.jsonl").exists()
    from src.monitoring.preflight import has_run_before

    assert has_run_before() is True
    assert [d for d, _t, _dom in seen] == list(range(1, len(seen) + 1)), (
        "progress must count up one per source"
    )
