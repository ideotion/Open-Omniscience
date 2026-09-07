"""Shared doubles for the backup/restore job tests.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS FILE EXISTS. Three test modules stubbed ``read_volume_backup`` with
``lambda *a, **k: object()``. That is not a weak double, it is one that cannot describe
any real value: every field the restore job reads off it raises ``AttributeError``, so
adding a field to :class:`~src.backup.artifact.StagedArtifact` reddens nine tests at
once in code that is correct. The one-line way out is a ``getattr(staged, "x", default)``
in the production path -- which reads as defensive and is a permanent hole, because every
real artifact HAS the field and the only caller that could lack it is a fixture.

So the double is the real dataclass, built once here. A field added to it can never be
missing from these tests again, and a test can no longer describe an artifact the engine
could not produce.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def staged_artifact(tmp_path: Any = None, **overrides: Any):
    """A minimal but REAL ``StagedArtifact`` for the restore doubles."""
    from src.backup.artifact import StagedArtifact

    base = Path(tmp_path) if tmp_path is not None else Path("/nonexistent-staging")
    fields: dict[str, Any] = {
        "kind": "oo-backup-2",
        "staging_dir": base,
        "corpus_path": base / "corpus.db",
        "custody_path": None,
        "manifest": {},
        "signature_state": "verified",
        "origin_fingerprint": "unsigned",
    }
    fields.update(overrides)
    return StagedArtifact(**fields)
