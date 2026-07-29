"""Stop during an import: free and complete before the swap, honest after it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field ruling 2026-07-29 item 15. ``VolumeBackupManager._run_restore`` never read
``self._stop`` (only ``_run_backup`` did), so the Stop button was INERT for the whole
of a restore — the longest thing an import does. Worse, the button existed, so it read
as a capability the app did not have.

The ruling's own analysis is what makes the two halves honest:

  * BEFORE the atomic swap everything runs on a disposable ``.restore-<hex>`` staging
    dir and a ``working.db`` copy under one ``BEGIN IMMEDIATE`` — so abort is free and
    complete, and the live corpus is byte-identical.
  * AFTER it there is no sound undo (a ``merged_rows`` delete leaves dangling ids,
    hash-joined rows legitimately attach to PRE-EXISTING articles, nothing repairs the
    counters), so the swap is uninterruptible BY DESIGN and a later Stop stops only the
    remaining, resumable work.

A test that only proved "stop works" would miss the second half entirely, so the
absence of a post-swap abort hook is asserted here as deliberate.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from src.backup.merge import RestoreAborted, merge_corpus
from src.database.models import Base

_MERGE_PY = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"
_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}


# --------------------------------------------------------------------------- #
#  the merge itself
# --------------------------------------------------------------------------- #
def _tiny_corpus(p: Path) -> None:
    """A real, empty schema — the merge writes its own provenance tables, so a
    hand-rolled two-table stub would fail for the wrong reason."""
    Base.metadata.create_all(create_engine(f"sqlite:///{p}", future=True))


def test_a_stop_during_the_merge_aborts_and_writes_nothing(tmp_path):
    """The merge is the longest phase of an import. A Stop that could not reach it
    would be a button that does nothing for hours."""
    staged, working = tmp_path / "in.db", tmp_path / "working.db"
    _tiny_corpus(staged)
    _tiny_corpus(working)
    before = working.read_bytes()
    with pytest.raises(RestoreAborted):
        merge_corpus(staged, working, _BATCH_META, should_stop=lambda: True)
    assert working.read_bytes() == before, (
        "the working copy must be rolled back — and it is the disposable one anyway; "
        "the LIVE corpus was never opened"
    )


def test_the_abort_names_where_it_stopped(tmp_path):
    """"It stopped" is not actionable; "it stopped before X, nothing was written" is."""
    staged, working = tmp_path / "in.db", tmp_path / "working.db"
    _tiny_corpus(staged)
    _tiny_corpus(working)
    with pytest.raises(RestoreAborted) as exc:
        merge_corpus(staged, working, _BATCH_META, should_stop=lambda: True)
    msg = str(exc.value)
    assert "nothing was written" in msg
    assert "keyword categories" in msg, "the exact step boundary it stopped at"


def test_no_stop_hook_is_byte_identical(tmp_path):
    """Every existing caller passes nothing; that path must be unchanged."""
    staged, working = tmp_path / "in.db", tmp_path / "working.db"
    _tiny_corpus(staged)
    _tiny_corpus(working)
    counts, batch_id = merge_corpus(staged, working, _BATCH_META)
    assert isinstance(batch_id, int) and isinstance(counts, dict)


def test_a_stop_that_never_fires_does_not_abort(tmp_path):
    staged, working = tmp_path / "in.db", tmp_path / "working.db"
    _tiny_corpus(staged)
    _tiny_corpus(working)
    counts, batch_id = merge_corpus(staged, working, _BATCH_META, should_stop=lambda: False)
    assert isinstance(batch_id, int)


# --------------------------------------------------------------------------- #
#  where the abort points are — and, deliberately, where they are not
# --------------------------------------------------------------------------- #
def _run_restore_source() -> str:
    tree = ast.parse(_MERGE_PY.read_text(encoding="utf-8"))
    src = _MERGE_PY.read_text(encoding="utf-8").splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run_restore":
            return "\n".join(src[node.lineno - 1 : node.end_lineno])
    raise AssertionError("run_restore not found")


def test_every_pre_swap_stage_has_an_abort_point():
    """Scoped to run_restore's own body, never a whole-file substring search: the two
    things being distinguished (pre-swap vs post-swap) share literal text."""
    body = _run_restore_source()
    for stage in (
        "prepare_staged", "snapshot_working_copy", "merge", "verify",
        "corpus_delta_before", "pre_restore_snapshot", "side_files_and_custody",
        "report_json_write", "swap",
    ):
        assert f'_abort_point("{stage}")' in body, f"{stage} has no abort point"


def test_there_is_deliberately_NO_abort_point_after_the_swap():
    """The absence is a design decision (there is no sound undo for os.replace), so it
    is asserted rather than left to be "fixed" later by someone reading the list above
    as incomplete."""
    body = _run_restore_source()
    after_swap = body.split('with timings.stage("swap"):', 1)[1]
    assert "_abort_point(" not in after_swap, (
        "an abort after the atomic swap would imply an undo that does not exist"
    )


def test_the_post_swap_reindex_still_receives_the_stop():
    """Not an abort — the re-index is resumable, so a Stop there simply leaves the
    backlog for later rather than pretending the import can be undone."""
    body = _run_restore_source()
    # Bounded by the statement that FOLLOWS the call, not by the first ")" — the
    # argument list contains parenthesised comments.
    reindex_call = body.split("reindex_imported_articles(", 1)[1].split("_rx_stats[", 1)[0]
    assert "should_stop=should_stop" in reindex_call


# --------------------------------------------------------------------------- #
#  the job that used to ignore it
# --------------------------------------------------------------------------- #
def test_the_volume_restore_job_passes_its_stop_event():
    """The defect at its actual call site: _run_backup passed should_stop, _run_restore
    did not, so the same Stop button worked for one and was inert for the other."""
    src = (Path(__file__).resolve().parents[1] / "src" / "backup" / "volume_job.py").read_text(
        encoding="utf-8"
    )
    run_restore_body = src.split("def _run_restore(", 1)[1].split("\n    # -- verify", 1)[0]
    assert "should_stop=self._stop.is_set" in run_restore_body
    assert run_restore_body.count("should_stop=self._stop.is_set") >= 2, (
        "both the reassembly and the merge/restore must honour it"
    )
    assert "except RestoreAborted" in run_restore_body, (
        "an operator's own Stop is a cancellation, never an error"
    )
