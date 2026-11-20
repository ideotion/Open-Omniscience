"""A merge batch records the backup kind it was GIVEN, and "unknown" when none: never a guessed format (schema audit F7).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``merge_batches.artifact_kind`` is the operator's record of what they restored (``StagedArtifact.kind``). It used to fall
back to ``"oo-backup-2"`` in both the model default and ``merge_corpus``, so a batch whose caller named no kind read as an
``oo-backup-2`` restore, a format the writer left behind in 0.4 (R755, F7).
"""

from __future__ import annotations

import sqlite3

from src.backup.merge import merge_corpus
from src.database.models import MergeBatch
from tests.test_merge_keyword_dup_count import _META, _build


def _kinds(working) -> list[str]:
    con = sqlite3.connect(working)
    try:
        return [k for (k,) in con.execute("SELECT artifact_kind FROM merge_batches ORDER BY id")]
    finally:
        con.close()


def test_a_named_kind_is_recorded_as_given(tmp_path) -> None:
    working, staged = _build(tmp_path)
    merge_corpus(staged, working, {**_META, "artifact_kind": "oo-backup-3"})
    assert _kinds(working) == ["oo-backup-3"]


def test_no_kind_records_unknown_never_a_guessed_format(tmp_path) -> None:
    working, staged = _build(tmp_path)
    meta = {k: v for k, v in _META.items() if k != "artifact_kind"}
    merge_corpus(staged, working, meta)
    assert _kinds(working) == ["unknown"]


def test_the_model_default_is_not_a_format_either() -> None:
    default = MergeBatch.__table__.c.artifact_kind.default.arg
    assert default == "unknown"
    assert not str(default).startswith("oo-")
