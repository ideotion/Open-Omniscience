"""A swap barrier that refuses is the ENGINE's refusal, never the operator's Stop.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Both pre-swap barriers -- the quiescence wait and the WAL checkpoint -- raised a bare
``RestoreAborted`` when another job still held the corpus. Its ONE handler labels the run
``cancelled``, journals ``stopped-by-operator`` and, in the same branch, CLEARS ``_error``.
So a refusal nobody asked for was reported as the operator's own cancellation, and because
the SPA rejects a cancelled state with ``s.error || view.text || state`` the one actionable
sentence -- "another job is still writing to your corpus (...)", naming the holder -- was
dropped on the way to the UI.

``merge.py`` carried the finding in a source comment and deferred it: "re-labelling belongs
to a slice that changes both, not to a file-lock fix". This is that slice.

Both directions are pinned. A refusal must name the engine AND keep its message; a genuine
operator Stop must still read as a cancellation -- a fix that relabelled every pre-swap
abort as an error would be its own dishonesty, and it is one edit away.
"""

from __future__ import annotations

import time

import pytest

from src.backup.volume_job import VolumeBackupManager
from tests.backup_helper import staged_artifact


def _wait(mgr: VolumeBackupManager, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = mgr.status()
        if st.get("state") not in ("running", "idle"):
            return st
        time.sleep(0.02)
    raise AssertionError(f"the job never settled: {mgr.status()}")


@pytest.fixture
def staged_restore(tmp_path, monkeypatch):
    """Drive the REAL ``_run_restore`` handler with a stubbed merge, so what is under
    test is the labelling, not the merge engine."""
    import src.backup.artifact as artifact_mod
    import src.backup.merge as merge_mod
    import src.scheduler.runner as sched_mod

    monkeypatch.setattr(sched_mod, "pause_for_exclusive_operation", lambda timeout=10.0: True)
    monkeypatch.setattr(sched_mod, "resume_after_exclusive_operation", lambda was_paused: None)
    monkeypatch.setattr(artifact_mod, "read_volume_backup", lambda *a, **k: staged_artifact())
    monkeypatch.setattr(artifact_mod, "cleanup_staging", lambda staged: None)

    src = tmp_path / "src"
    src.mkdir()

    def _drive(exc: BaseException) -> dict:
        def _raise(*a, **k):
            raise exc

        monkeypatch.setattr(merge_mod, "run_restore", _raise)
        mgr = VolumeBackupManager()
        mgr.start_restore(str(src), "pw")
        return _wait(mgr)

    return _drive


_HOLDER_MSG = (
    "another job is still writing to your corpus (reindex) after waiting 180s — "
    "nothing was written to your corpus."
)


def test_a_refusal_is_not_reported_as_the_operators_cancellation(staged_restore):
    from src.backup.merge import RestoreRefused

    st = staged_restore(RestoreRefused(_HOLDER_MSG))

    assert st["state"] != "cancelled", (
        "the operator cancelled nothing — reporting a barrier refusal as their own "
        "cancellation sends them looking for a job they never started"
    )
    assert st["state"] == "error"


def test_a_refusal_keeps_the_sentence_that_names_the_holder(staged_restore):
    """The message IS the remedy. The cancelled branch clears ``_error``, and the SPA
    falls back to a bare state string when it is empty."""
    from src.backup.merge import RestoreRefused

    st = staged_restore(RestoreRefused(_HOLDER_MSG))

    assert st.get("error"), "a refusal with no error text reaches the UI as a bare state"
    assert "another job is still writing" in st["error"]
    assert "reindex" in st["error"], "the holder's name is the actionable half"


def test_the_operators_own_stop_still_reads_as_a_cancellation(staged_restore):
    """NEGATIVE SPACE. A genuine pre-swap Stop is a normal outcome, never an error --
    relabelling it would trade one wrong actor for another."""
    from src.backup.merge import RestoreAborted

    st = staged_restore(RestoreAborted("stopped before 'swap' — nothing was written"))

    assert st["state"] == "cancelled"
    assert not st.get("error"), "an honoured Stop is not a failure to read"


def test_a_refusal_is_a_restore_aborted_so_every_existing_handler_stays_correct():
    """The subclassing is load-bearing, not taxonomy: the property every RestoreAborted
    handler relies on -- nothing applied, the live corpus byte-identical, the staging dir
    disposable -- is exactly as true for a refusal."""
    from src.backup.merge import RestoreAborted, RestoreRefused

    assert issubclass(RestoreRefused, RestoreAborted)


def test_the_refusal_is_caught_before_the_stop_branch():
    """Ordering, asserted rather than remembered: ``except RestoreAborted`` first would
    swallow every refusal into the cancellation branch and this whole fix would be inert
    while all four tests above still described the code correctly."""
    import inspect

    from src.backup.volume_job import VolumeBackupManager as M

    body = inspect.getsource(M._run_restore)
    assert body.index("except RestoreRefused") < body.index("except RestoreAborted")


def test_both_swap_barriers_raise_the_refusal_not_the_operators_stop():
    """THE WIRING, and it is not covered by the handler tests above.

    Those inject a ``RestoreRefused`` themselves, so reverting either barrier's raise to
    a bare ``RestoreAborted`` leaves all of them green -- a mutation that survived on the
    first matrix run. ``test_swap_barrier`` cannot see it either: its guard is about the
    FAMILY, and ``RestoreAborted`` is in the family.

    Scoped to the raises the swap stage's own barriers make -- between the quiescence
    call and the commit point -- and read from the PARSE TREE, so the comments at those
    sites (which necessarily name both classes) cannot satisfy it. ``_abort_point("swap")``
    sits in that span and is deliberately untouched: it is a call, and the Stop it raises
    inside really is the operator's.
    """
    import ast
    import inspect

    import src.backup.merge as merge

    tree = ast.parse(inspect.getsource(merge))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "run_restore"
    )

    def _line_of(needle: str) -> int:
        hits = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and needle in ast.unparse(n.func)
        ]
        assert len(hits) == 1, f"expected exactly one {needle} call in run_restore, got {hits}"
        return hits[0]

    start, end = _line_of("wait_for_quiescence"), _line_of("_replace_live_corpus")
    assert start < end

    barrier_raises = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Raise) and n.exc is not None and start < n.lineno < end
    ]
    assert len(barrier_raises) == 2, (
        "the swap stage has two barriers -- the quiescence wait and the WAL checkpoint; "
        f"found {len(barrier_raises)} raises between the wait and the commit point"
    )
    for node in barrier_raises:
        name = ast.unparse(node.exc.func if isinstance(node.exc, ast.Call) else node.exc)
        assert name == "RestoreRefused", (
            f"a swap barrier raises {name!r}: a refusal because ANOTHER job held the "
            "corpus must not be reported as the operator's own cancellation"
        )
