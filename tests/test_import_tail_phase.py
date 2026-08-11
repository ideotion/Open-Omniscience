"""The import run's tail: the work that happens after the last item says "Done".

FIELD REPORT 2026-08-11. An import's dialog read "1/1 imported · 1h 55m" with its only
item "Done · 1h 44m" and "Background collection is paused for this whole import"
underneath, while one core sat at 100% and a second import was refused. Nothing had
hung: after the last item the queue merges the search index (``_tune_after_run``, an
FTS5 ``'optimize'`` — single-threaded and index-scaled) inside the same exclusive
window, and the run is legitimately still running. What was missing was that anyone
could SEE it. Three surfaces are pinned here:

* the dialog header (behaviourally, in ``tests/import_tail_phase_node_test.js``);
* the task-manager row, which said "Importing" at 100% of items — a job claiming to be
  finished and to be working in the same breath;
* the re-index drain, which is the OTHER thing the operator asked about: it must yield
  to a new import rather than compete with it, and nothing must be lost when it does.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import inspect
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
#  the dialog header (node)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_import_tail_phase_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "import_tail_phase_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


# --------------------------------------------------------------------------- #
#  the task-manager row
# --------------------------------------------------------------------------- #
def _queue_status(**over) -> dict:
    base = {
        "state": "running",
        "items": [{"label": "backup-a", "state": "done"}],
        "current": None,
        "live": None,
        "items_done": 1,
        "items_total": 1,
        "stages_done": 1,
        "stages_total": 2,
    }
    base.update(over)
    return base


def _jobs_with(monkeypatch, status: dict) -> list[dict]:
    import src.backup.import_queue as q

    class _Fake:
        def status(self) -> dict:
            return status

    monkeypatch.setattr(q, "get_import_queue", lambda: _Fake())
    from src.api.jobs import _import_queue_jobs

    return _import_queue_jobs()


def test_the_row_names_the_tail_phase_instead_of_importing_at_100_percent(monkeypatch) -> None:
    """The reported wording. With every item done and the search-index merge running,
    the row said "Importing" beside 100% — the two halves contradicting each other."""
    jobs = _jobs_with(monkeypatch, _queue_status(live={"phase": "tuning"}))
    assert len(jobs) == 1
    assert jobs[0]["label"] == "Finishing the import"
    # THE BAR counts stages, so it cannot read full while a stage is left.
    prog = jobs[0]["progress"]
    assert prog["percent"] < 100.0, "a full bar beside a run still holding the machine"
    assert (prog["done"], prog["total"], prog["unit"]) == (1, 2, "stages")
    # The item count is a REAL measurement and stays beside it: one of one item IS
    # imported. It was never the wrong number, only the wrong thing to draw a bar from.
    assert (jobs[0]["items_done"], jobs[0]["items_total"]) == (1, 1)


def test_an_item_in_flight_is_still_named_by_that_item(monkeypatch) -> None:
    """The twin. The tail label must not swallow the case it was never about."""
    jobs = _jobs_with(
        monkeypatch,
        _queue_status(current={"label": "backup-a", "state": "running"}, items_done=0),
    )
    assert jobs[0]["label"] == "Importing backup-a"


def test_a_run_with_neither_an_item_nor_a_phase_keeps_the_plain_label(monkeypatch) -> None:
    """No phase published means nothing to name — claiming one would be fabricated."""
    jobs = _jobs_with(monkeypatch, _queue_status())
    assert jobs[0]["label"] == "Importing"


def test_the_nested_sub_job_shape_is_read_too(monkeypatch) -> None:
    """A mirrored sub-job status nests its phase under ``progress``; the run's own tail
    live is flat. One reader, both shapes — the same mismatch that made the phase
    invisible on the frontend."""
    jobs = _jobs_with(
        monkeypatch, _queue_status(live={"state": "running", "progress": {"phase": "tuning"}})
    )
    assert jobs[0]["label"] == "Finishing the import"


# --------------------------------------------------------------------------- #
#  the manager's own stage accounting
# --------------------------------------------------------------------------- #
def _queue(tmp_path):
    from src.backup.import_queue import ImportQueueManager

    return ImportQueueManager(state_path=tmp_path / "q.json")


def test_the_search_index_merge_is_counted_as_a_stage(tmp_path) -> None:
    """The denominator has to include the stage that is actually left, or the bar is
    full while the run still owns the machine."""
    mgr = _queue(tmp_path)
    mgr._items = [{"id": "0-corpus", "kind": "corpus", "state": "done", "started_at": 1.0,
                   "ended_at": 2.0, "label": "a", "path": "/x", "error": None, "summary": None}]
    st = mgr.status()
    assert (st["items_done"], st["items_total"]) == (1, 1), "the item count is unchanged"
    assert (st["stages_done"], st["stages_total"]) == (1, 2)
    assert st["stages_done"] < st["stages_total"]


def test_the_stage_completes_when_the_tuning_pass_is_over(tmp_path, monkeypatch) -> None:
    """It counts as done once the pass has RUN — what it achieved is `tuned`, reported
    separately, so a tuning that failed does not strand the run short of its own end."""
    mgr = _queue(tmp_path)
    mgr._items = [{"id": "0-corpus", "kind": "corpus", "state": "done", "started_at": 1.0,
                   "ended_at": 2.0, "label": "a", "path": "/x", "error": None, "summary": None}]

    def _boom(*_a, **_kw):
        raise RuntimeError("optimize failed")

    monkeypatch.setattr("src.database.fts.optimize_after_bulk", _boom)
    mgr._tune_after_run()
    st = mgr.status()
    assert st["stages_done"] == st["stages_total"] == 2
    assert st["tuned"] is None, "and it still reports honestly that it achieved nothing"


def test_a_stopped_run_never_reaches_its_own_end(tmp_path) -> None:
    """The twin. Stop skips the merge, so the stage never runs — and a stopped run
    reading 100% would be the same fabricated completeness pointing the other way."""
    mgr = _queue(tmp_path)
    mgr._items = [{"id": "0-corpus", "kind": "corpus", "state": "done", "started_at": 1.0,
                   "ended_at": 2.0, "label": "a", "path": "/x", "error": None, "summary": None}]
    mgr._stop.set()
    mgr._tune_after_run()
    st = mgr.status()
    assert st["stages_done"] == 1 < st["stages_total"] == 2


# --------------------------------------------------------------------------- #
#  the re-index drain yields to an import
# --------------------------------------------------------------------------- #
class _Ctx:
    """Stands in for JobContext. Pinned to the real class below: a hand-written double
    that has drifted produces the same green as correct code (recorded lesson)."""

    def __init__(self, stopping: bool = False) -> None:
        self._stopping = stopping
        self.progress: list[dict] = []

    @property
    def stopping(self) -> bool:
        return self._stopping

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        self.progress.append({"done": done, "total": total, "detail": detail})


def test_the_ctx_double_matches_the_real_job_context() -> None:
    from src.jobs.background import JobContext

    def shape(fn):
        # Names and KINDS, not the whole signature: the double carries no annotations
        # and never will, and an annotation drift is not what silently breaks a caller.
        return [(p.name, p.kind) for p in inspect.signature(fn).parameters.values()]

    assert shape(_Ctx.set_progress) == shape(JobContext.set_progress)
    assert isinstance(JobContext.stopping, property), "stopping must stay a property"


def _drive(monkeypatch, *, window_open: bool, stopping: bool = False) -> tuple[dict, list]:
    import src.api.backup_v2 as b2
    import src.backup.merge as merge

    calls: list[dict] = []

    monkeypatch.setattr(
        merge,
        "reindex_backlog",
        lambda: {"available": True, "articles_pending": 700_000,
                 "batches": [{"batch_id": 7, "articles": 700_000}]},
    )

    def _fake_reindex(batch_id, *, progress_cb=None, should_stop=None, **kw):
        calls.append({"batch_id": batch_id, "should_stop": should_stop})
        return {"reindexed": 700_000, "failed": 0}

    monkeypatch.setattr(merge, "reindex_imported_articles", _fake_reindex)
    monkeypatch.setattr(b2, "exclusive_window_open", lambda: window_open)

    ctx = _Ctx(stopping=stopping)
    return b2._reindex_resume_worker(ctx), calls


def test_the_drain_stands_down_when_an_import_holds_the_machine(monkeypatch) -> None:
    """An import claims all cores and an enlarged cache on the premise that it is alone.
    This drain is the one heavy writer that was never told."""
    out, calls = _drive(monkeypatch, window_open=True)
    assert calls == [], "no batch may start while an import owns the machine"
    assert out["stopped"] is True
    assert out["paused_for_import"] is True


def test_the_drain_runs_normally_when_nothing_holds_the_machine(monkeypatch) -> None:
    """The twin, and the one that matters most: an over-eager yield would leave the
    backlog permanently undrained, which is worse than the competition it prevents."""
    out, calls = _drive(monkeypatch, window_open=False)
    assert [c["batch_id"] for c in calls] == [7]
    assert out["stopped"] is False
    assert "paused_for_import" not in out
    assert out["articles_reindexed"] == 700_000


def test_a_cancel_and_a_yield_are_reported_apart(monkeypatch) -> None:
    """Both stop the drain; only one of them restarts itself. Reporting a cancel as a
    yield would promise the operator a resume nobody scheduled."""
    out, calls = _drive(monkeypatch, window_open=False, stopping=True)
    assert calls == []
    assert out["stopped"] is True
    assert out["paused_for_import"] is False


def test_the_yield_reaches_inside_a_batch_not_only_between_them(monkeypatch) -> None:
    """THE DISCRIMINATING ONE. A single import is a single batch of every article it
    merged, so a check that only ran BETWEEN batches would never fire on the one shape
    that matters. The predicate handed to reindex_imported_articles — polled inside its
    own loop, where the durable watermark makes an early return free — must see the
    window open the moment it does."""
    import src.api.backup_v2 as b2

    window = {"open": False}
    monkeypatch.setattr(b2, "exclusive_window_open", lambda: window["open"])

    _out, calls = _drive(monkeypatch, window_open=False)
    monkeypatch.setattr(b2, "exclusive_window_open", lambda: window["open"])
    should_stop = calls[0]["should_stop"]
    assert should_stop is not None, "the drain must hand the article loop a stop predicate"
    assert should_stop() is False, "and it must not stop while nothing holds the machine"

    window["open"] = True
    assert should_stop() is True, "an import opening mid-batch must reach the article loop"
