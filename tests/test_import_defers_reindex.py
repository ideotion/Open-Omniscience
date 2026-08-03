"""The import no longer blocks on the re-index.

Implements the standing 2026-07-29 ruling 1/2 ("defer the re-index off the blocking
import path -- YES"; "the re-index is AUTONOMOUS + VISIBLE"), forced by the 2026-08-03
field run: all eighteen stages -- verify, reassemble, merge, SWAP -- finished in
118.6 s with the corpus committed and safe, and the post-swap re-index then ran 3.02
hours to 41% before the operator killed it. The import a user waited three and a half
hours for had been complete on disk after two minutes.

Nothing here makes the re-index faster. It stops being the IMPORT's problem.

THE HONESTY COST, which is what most of these tests are about: "import finished" no
longer means "fully indexed". Deferring silently would trade a visible three-hour wait
for an invisible incomplete corpus, which is strictly worse -- so the report says so
and carries the real pending count.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest


def test_deferral_is_the_default_and_is_revertible(monkeypatch):
    from src.backup import volume_job

    monkeypatch.delenv("OO_IMPORT_DEFER_REINDEX", raising=False)
    assert volume_job._defer_reindex() is True, "the ruling says defer; that is the default"
    monkeypatch.setenv("OO_IMPORT_DEFER_REINDEX", "0")
    assert volume_job._defer_reindex() is False, "the old blocking behaviour stays reachable"


def test_the_restore_plan_drops_the_reindex_stage_when_deferred():
    """The user-visible "phase N of M" must not count a phase this restore will never
    run. ``restore_stage_plan`` already supported the flag; the import now uses it."""
    from src.backup.merge import restore_stage_plan

    with_rx = restore_stage_plan(commit=True, reindex_imported=True)
    without = restore_stage_plan(commit=True, reindex_imported=False)
    assert "reindex" in with_rx
    assert "reindex" not in without
    assert len(without) == len(with_rx) - 1, "exactly one stage leaves the plan"


def test_the_import_passes_the_flag_through_consistently():
    """The plan and the call must agree. If the plan said one thing and run_restore
    did another, every phase index after the divergence would be wrong -- the exact
    silent-miscount the plan is computed rather than hardcoded to avoid."""
    import inspect

    from src.backup import volume_job

    src = inspect.getsource(volume_job.VolumeBackupManager._run_restore)

    # SCOPED to the run_restore CALL. The plan line a few lines above contains the very
    # same expression, so a whole-method substring search passes even when the call
    # itself is reverted to a hardcoded True -- verified by mutation, and exactly the
    # recorded trap that a substring assertion is only as strong as that string's
    # uniqueness within what it searches.
    def _args(after: str) -> str:
        """The argument text of the call opened by ``after``, paren-balanced.

        Splitting on the first ``)`` truncates at ``_defer_reindex()``'s OWN closing
        paren and yields a slice that can never contain what is being asserted -- it
        failed against correct code. Balance instead.
        """
        i = src.index(after) + len(after)
        depth, j = 1, i
        while depth:
            depth += {"(": 1, ")": -1}.get(src[j], 0)
            j += 1
        return src[i : j - 1]

    call = _args("report = run_restore(")
    assert "reindex_imported=not _defer_reindex()" in call, (
        "run_restore must be told the same thing the phase plan was, or every phase "
        "index after the divergence is silently wrong"
    )
    plan = _args("_restore_plan = restore_stage_plan(")
    assert "reindex_imported=not _defer_reindex()" in plan


def test_the_report_states_the_deferral_and_the_pending_count(monkeypatch):
    """The load-bearing honesty test. A corpus that is imported but not yet indexed is
    INCOMPLETE, and the report must say so with a real number -- otherwise deferring
    hides what waiting at least made visible."""
    from src.backup import volume_job

    monkeypatch.setattr(
        "src.backup.merge.reindex_backlog",
        lambda: {"available": True, "articles_pending": 12778, "batches": []},
    )
    monkeypatch.setattr(
        "src.api.backup_v2._REINDEX_RESUME_JOB",
        type("J", (), {"start": staticmethod(lambda **_k: {"state": "running"})})(),
    )
    report: dict = {}
    volume_job._hand_off_reindex(report)

    rx = report["reindex_deferred"]
    assert rx["deferred"] is True
    assert rx["articles_pending"] == 12778, "the real backlog, not a guess"
    assert rx["started"] is True
    assert "analytics" in rx["why"], "it must say WHAT is incomplete, not merely that something is"


def test_an_unreadable_backlog_is_not_reported_as_zero_pending(monkeypatch):
    """"could not read the backlog" and "nothing pending" must never look alike --
    reporting the first as the second is fabricated reassurance about missing data."""
    from src.backup import volume_job

    monkeypatch.setattr(
        "src.backup.merge.reindex_backlog",
        lambda: {"available": False, "reason": "database is locked"},
    )
    monkeypatch.setattr(
        "src.api.backup_v2._REINDEX_RESUME_JOB",
        type("J", (), {"start": staticmethod(lambda **_k: {})})(),
    )
    report: dict = {}
    volume_job._hand_off_reindex(report)

    rx = report["reindex_deferred"]
    assert rx["articles_pending"] is None, "an unreadable count must NOT be 0"
    assert rx["pending_unreadable_reason"] == "database is locked"


def test_a_drain_that_cannot_start_still_records_the_backlog(monkeypatch):
    """In an import QUEUE a drain is often already running, so start() legitimately
    refuses. The work must be DEFERRED, never lost: the backlog is recorded and the
    job stays startable, so a refusal costs latency and nothing else."""
    from src.backup import volume_job

    monkeypatch.setattr(
        "src.backup.merge.reindex_backlog",
        lambda: {"available": True, "articles_pending": 500, "batches": []},
    )

    def _busy(**_kw):
        raise RuntimeError("a reindex-resume job is already running")

    monkeypatch.setattr(
        "src.api.backup_v2._REINDEX_RESUME_JOB",
        type("J", (), {"start": staticmethod(_busy)})(),
    )
    report: dict = {}
    volume_job._hand_off_reindex(report)

    rx = report["reindex_deferred"]
    assert rx["started"] is False
    assert "already running" in rx["start_detail"]
    assert rx["articles_pending"] == 500, "the backlog is still recorded and still visible"


def test_the_epilogue_never_fails_a_committed_import(monkeypatch):
    """The import is COMMITTED by the time this runs. An epilogue that raised would
    turn a successful import into a reported failure over a bookkeeping read."""
    from src.backup import volume_job

    def _boom():
        raise OSError("disk gone")

    monkeypatch.setattr("src.backup.merge.reindex_backlog", _boom)
    monkeypatch.setattr(
        "src.api.backup_v2._REINDEX_RESUME_JOB",
        type("J", (), {"start": staticmethod(lambda **_k: {})})(),
    )
    report: dict = {}
    volume_job._hand_off_reindex(report)  # must not raise
    assert report["reindex_deferred"]["articles_pending"] is None


def test_the_drain_job_it_hands_off_to_actually_exists():
    """The hand-off names a job by string. If that job were renamed or removed, the
    import would defer work to nothing and say it had started it."""
    from src.api.backup_v2 import _REINDEX_RESUME_JOB

    assert _REINDEX_RESUME_JOB.kind == "reindex-resume"
    assert _REINDEX_RESUME_JOB.cancellable, "a multi-hour background drain must be stoppable"


@pytest.mark.parametrize("stage", ["keyword_counter_reconcile", "quarantine_scan"])
def test_the_stages_after_the_reindex_do_not_depend_on_it(stage):
    """Deferring is only safe because run_restore already anticipated the flag: the
    counter reconcile is deliberately UNCONDITIONAL (the drift comes from the MERGE),
    and the quarantine scan works off the batch's merged_rows ids, not off keywords.
    Pinned so a future edit cannot quietly move either INSIDE the reindex branch."""
    import inspect

    from src.backup import merge

    src = inspect.getsource(merge.run_restore)
    body = src.split("if reindex_imported:", 1)[1]
    # The stage must appear at the function's own indentation (8 spaces), i.e. OUTSIDE
    # the `if reindex_imported:` block rather than nested within it.
    assert f'\n        with timings.stage("{stage}")' in body, (
        f"{stage} must run whether or not the re-index did"
    )


def test_the_deferral_is_VISIBLE_in_the_import_summary():
    """The ruling says the re-index is "AUTONOMOUS + VISIBLE". Autonomous shipped with
    the hand-off; visible is this.

    Without it, deferring would trade a visible three-hour wait for an INVISIBLE
    incomplete corpus -- the report would be honest and nobody would read it. The
    summary states it, with the real count, and says an unreadable backlog is
    unreadable rather than showing 0.
    """
    from pathlib import Path

    app = Path("src/static/app.js").read_text(encoding="utf-8")
    fn = app.split("function _renderImportSummary", 1)[1].split("\n    function ", 1)[0]

    assert "reindex_deferred" in fn, "the summary must read the report's own deferral block"
    assert "indexingLine" in fn and "+ indexingLine +" in fn, "…and actually render it"
    assert "card-caveat" in fn, "it is a caveat about corpus completeness, styled as one"
    # The unreadable branch must exist and must NOT fall through to a zero.
    assert "could not be read" in fn, (
        "'could not read the backlog' and 'nothing pending' must not look alike"
    )


def test_both_visible_strings_ship_in_every_locale():
    """A caveat that only exists in English is not a caveat for most of the app's
    users. Every consent/caveat string ships x12."""
    import json
    from pathlib import Path

    needed = [
        "Indexing continues in the background. The number still to index could not be read.",
        "Indexing continues in the background: {n} article(s) still to index. Until it "
        "finishes they carry no keywords and are absent from analytics.",
    ]
    files = sorted(Path("src/static/locales").glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {len(files)}"
    for lf in files:
        data = json.loads(lf.read_text(encoding="utf-8"))
        for key in needed:
            assert key in data, f"{lf.name} is missing: {key[:50]}…"
