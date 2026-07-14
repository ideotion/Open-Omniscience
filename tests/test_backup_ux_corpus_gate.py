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

_ROOT = Path(__file__).resolve().parent.parent
_APP_JS = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
_STREAM = (_ROOT / "src" / "backup" / "stream_backup.py").read_text(encoding="utf-8")


def _fn_body(src: str, start_marker: str) -> str:
    """The text of a top-level IIFE function from its declaration to the next `\\n    function `
    / `\\n    async function ` sibling — enough to scope assertions to one function."""
    i = src.index(start_marker)
    rest = src[i + len(start_marker):]
    ends = [rest.find("\n    function "), rest.find("\n    async function ")]
    ends = [e for e in ends if e != -1]
    return rest[: min(ends)] if ends else rest


def test_ux_run_gates_the_folder_phase_on_a_confirmed_corpus_backup():
    run = _fn_body(_APP_JS, "async function _uxRun(")
    # the load-bearing gate: the folder/blob phase is unreachable unless the volumes job is a
    # completed `backup` (state done + mode backup) of this dest.
    assert 's1.state !== "done"' in run and 's1.mode !== "backup"' in run, "the corpus-confirm gate is missing"
    # and the gate is BEFORE the folder start, so a failed confirm aborts into the catch
    # ("Backup failed") and never starts the blob phase / prints success.
    assert run.index('s1.state !== "done"') < run.index("/api/backup/folder/start"), (
        "the confirm gate must precede folder/start"
    )


def test_ux_start_then_poll_re_throws_an_unrelated_masked_job():
    poll = _fn_body(_APP_JS, "async function _uxStartThenPoll(")
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
