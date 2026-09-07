"""
Slice 0 (DATA-SAFETY) — the unified "large data" backup must never report success unless the
corpus (volumes) phase PROVABLY completed as a backup of THIS destination.

Regression: a lost/masked `/v2/volumes/start` response could adopt an UNRELATED live volume job
(a Verify, a restore, or a backup to a different drive — all share one manager + one /status),
see its "done", skip the corpus for the chosen drive, then copy the blobs and print
"Backup complete." (field 2026-07-14).

The full DOM harness (stub api(), drive _uxRun) needs jsdom + exposing the monolithic-IIFE
functions and a browser click-through — owed per fork-3. These are the source-level invariants
that pin the fix's STRUCTURE (no crypto/browser), plus the backend "done ⇒ corpus present"
contract the fix relies on.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path
from tests.js_source_helper import app_js, function_body as _slice

_ROOT = Path(__file__).resolve().parent.parent
_APP_JS = app_js()
_STREAM = (_ROOT / "src" / "backup" / "stream_backup.py").read_text(encoding="utf-8")


def _fn_body(src: str, name: str) -> str:
    """One function's body, brace-matched. Shared slicer."""
    return _slice(src, name)


def test_ux_run_gates_the_folder_phase_on_a_confirmed_corpus_backup():
    run = _fn_body(_APP_JS, "_uxRun")
    # the load-bearing gate: the folder/blob phase is unreachable unless the volumes job is a
    # completed `backup` (state done + mode backup) of this dest.
    assert 's1.state !== "done"' in run and 's1.mode !== "backup"' in run, "the corpus-confirm gate is missing"
    # and the gate is BEFORE the folder start, so a failed confirm aborts into the catch
    # ("Backup failed") and never starts the blob phase / prints success.
    assert run.index('s1.state !== "done"') < run.index("/api/backup/folder/start"), (
        "the confirm gate must precede folder/start"
    )


def test_carrying_the_large_files_inside_the_artifact_replaces_the_folder_phase():
    """S6.2, and the half that would be a real defect if it were wrong: when they ride
    INSIDE the artifact, the folder phase must not ALSO copy them next to it -- that would
    double the bytes on the drive to deliver the same files, silently."""
    run = _fn_body(_APP_JS, "_uxRun")
    assert "include_blobs: blobs" in run, "the categories must reach the volumes job"
    assert "if (blobs.length && !inside) {" in run, "the folder phase must be skipped"
    # It only applies when a corpus is actually being written: with no artifact there is
    # nothing to carry them in, so the request must be the one that shipped.
    assert "wantCorpus && blobs.length" in run


def test_the_inside_choice_is_disabled_rather_than_ignored():
    """A tickbox whose state the run ignores is worse than one that is disabled: the
    dialog would be showing a choice that does not exist. Asserted on the sync helper,
    which is the only thing that decides it."""
    sync = _fn_body(_APP_JS, "_uxSyncInside")
    assert "inside.disabled = !usable" in sync
    assert "if (!usable) inside.checked = false" in sync, (
        "a disabled box must also be unticked, or a later re-enable restores a choice "
        "the operator never made"
    )
    assert "corpus.checked" in sync and '"models", "maps", "wiki"' in sync


def test_ux_start_then_poll_re_throws_an_unrelated_masked_job():
    poll = _fn_body(_APP_JS, "_uxStartThenPoll")
    # a 409 masked-start must only be adopted when the live job is OURS (mode/dest match) — an
    # unrelated Verify/restore/other-dest job re-throws instead of being reported as our backup.
    assert "expect" in poll and "st.mode !== expect.mode" in poll, "the mode-match re-throw is missing"
    assert "_uxSamePath" in _APP_JS, "the path-equality helper the gate uses is missing"


def test_stream_backup_always_emits_the_corpus_member():
    # the invariant the frontend fix relies on: a volumes job that reaches state:"done" genuinely
    # wrote the corpus, because write_stream_backup unconditionally emits the role="corpus" member.
    assert '_emit_member(st, MemberFile(src.member_name, "corpus", src.path))' in _STREAM, (
        "the unconditional corpus-member emission was moved/removed — the done⇒corpus invariant broke"
    )


def test_ux_show_last_completed_export_summary_restores_the_resume_control():
    """Audit finding 2026-07-17 (M8): a reopened Export dialog on a PAUSED background job
    printed "Backup paused. Resume to continue..." as plain status text, but never restored
    the two things a click on Resume actually needs: _uxPhase (which endpoint a resume must
    target) and the real #ux-pause button (default display:none) unhidden + relabelled into
    resume mode. So the reopened dialog claimed a paused job existed but offered no control
    to act on it. Fix: reuse _uxShowPaused — the SAME helper _uxRun already calls on a
    mid-run pause — and track which status endpoint (volumes vs folder) produced the shown
    paused state so _uxPhase targets the right one."""
    fn = _fn_body(_APP_JS, "_uxShowLastCompletedExportSummary")
    assert "_uxShowPaused(prog, bar, pauseBtn, t)" in fn, (
        "a paused reopen must reuse the same _uxShowPaused helper _uxRun uses mid-run"
    )
    assert "_uxPhase = phase" in fn, (
        "a paused reopen must restore _uxPhase so a Resume click targets the right endpoint"
    )
    # phase is tracked per endpoint so folder (which runs after volumes in a full export)
    # wins when BOTH are paused — matching the existing docstring: "the more recent state".
    assert 'phase = "volumes"' in fn and 'phase = "folder"' in fn


def test_ux_show_paused_is_the_single_source_of_the_resume_button_state():
    """The helper the M8 fix reuses must actually do the unhide+relabel — pin its contract
    so a future refactor of _uxShowPaused can't silently regress the reopen fix above."""
    fn = _fn_body(_APP_JS, "_uxShowPaused")
    assert 'pauseBtn.style.display = ""' in fn
    assert 'pauseBtn.dataset.mode = "resume"' in fn
