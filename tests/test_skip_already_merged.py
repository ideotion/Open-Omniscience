"""Refusing to re-merge an artifact this corpus already merged.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field logs 2026-07-31: 18 imports, 12.5 h of wall clock, 29,636 new articles --
and 8 of those imports added ZERO. The largest spent 2.96 h merging 700,503
duplicate articles and left corpus_delta.before byte-identical to .after. The
cost is paid in staging and merging BEFORE anything reveals the artifact was
already imported, so the question has to be asked from the container manifest,
which is one small JSON read.

The dangerous direction here is a FALSE SKIP -- silently not importing something
that was never actually merged. So these pin the negatives at least as hard as
the positive: an unknown digest, an unreadable manifest, a non-matching digest,
and a batch that never committed must all still do the work.
"""

from __future__ import annotations

import json

import pytest

from src.backup import merge as m

_DIGEST = "a" * 64
_OTHER = "b" * 64


def _write_manifest(tmp_path, **fields):
    d = tmp_path / "backup"
    d.mkdir(exist_ok=True)
    (d / "volumes.json").write_text(json.dumps(fields), encoding="utf-8")
    return d


# --------------------------------------------------------------------------- #
#  artifact_source_digest: reading the identity of the BYTES, cheaply
# --------------------------------------------------------------------------- #
def test_reads_the_whole_archive_digest_from_the_manifest(tmp_path):
    d = _write_manifest(tmp_path, kind="oo-volumes-2", plaintext_sha256=_DIGEST, volumes=[])
    assert m.artifact_source_digest(d) == _DIGEST


def test_a_manifest_without_a_digest_is_an_unknown_not_an_error(tmp_path):
    d = _write_manifest(tmp_path, kind="oo-volumes-2", volumes=[])
    assert m.artifact_source_digest(d) is None


def test_an_unreadable_folder_is_an_unknown_not_an_exception(tmp_path):
    assert m.artifact_source_digest(tmp_path / "does-not-exist") is None


def test_a_malformed_digest_is_refused(tmp_path):
    """A truncated or non-hex value must not become an identity -- matching on a
    degenerate key is how a skip starts refusing imports it never performed."""
    for bad in ("", "abc", _DIGEST[:63], 12345, None, ["a" * 64]):
        d = _write_manifest(tmp_path, kind="oo-volumes-2", plaintext_sha256=bad)
        assert m.artifact_source_digest(d) is None, f"accepted {bad!r}"


# --------------------------------------------------------------------------- #
#  find_completed_import: only a COMMITTED batch counts
# --------------------------------------------------------------------------- #
def _seed_batch(session, *, digest, status):
    from sqlalchemy import text

    session.execute(
        text(
            "INSERT INTO merge_batches (imported_at, artifact_kind, origin_fingerprint,"
            " source_digest, status) VALUES ('2026-07-31T00:00:00', 'oo-backup-2',"
            " 'unsigned', :d, :s)"
        ),
        {"d": digest, "s": status},
    )
    session.commit()


@pytest.fixture()
def session(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.maintenance import ensure_merge_batch_source_digest
    from src.database.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'x.db'}")
    Base.metadata.create_all(engine)
    ensure_merge_batch_source_digest(engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    import contextlib

    @contextlib.contextmanager
    def _scope():
        yield s

    monkeypatch.setattr("src.database.session.session_scope", _scope)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_a_committed_batch_is_found(session):
    _seed_batch(session, digest=_DIGEST, status="merged")
    hit = m.find_completed_import(_DIGEST)
    assert hit is not None and hit["status"] == "merged"


def test_a_reindexed_batch_also_counts_as_done(session):
    """'reindexed' differs from 'merged' only in whether the POST-swap re-index
    finished. Re-importing would not advance that -- the re-index is its own
    resumable job -- so both mean 'these bytes are already in'."""
    _seed_batch(session, digest=_DIGEST, status="reindexed")
    assert m.find_completed_import(_DIGEST) is not None


def test_a_batch_that_never_committed_is_not_a_match(session):
    """A 'previewed' or 'failed' batch means the merge did NOT land. Treating it
    as done would silently skip an import that never happened -- the one failure
    mode of this feature that costs data rather than time."""
    for status in ("previewed", "failed"):
        session.execute(
            __import__("sqlalchemy").text("DELETE FROM merge_batches")
        )
        session.commit()
        _seed_batch(session, digest=_DIGEST, status=status)
        assert m.find_completed_import(_DIGEST) is None, status


def test_a_different_artifact_is_not_a_match(session):
    _seed_batch(session, digest=_OTHER, status="merged")
    assert m.find_completed_import(_DIGEST) is None


def test_an_unknown_digest_never_matches(session):
    """Batches merged before this column existed carry NULL. NULL must never match
    -- including when the CALLER also has no digest, which is the case that would
    otherwise pair 'I don't know what this is' with 'I don't know what that was'
    and call them equal."""
    _seed_batch(session, digest=None, status="merged")
    assert m.find_completed_import(None) is None
    assert m.find_completed_import("") is None
    assert m.find_completed_import(_DIGEST) is None


def test_an_unreadable_store_does_not_veto_an_import(session, monkeypatch):
    """A store we cannot query is an unknown, so the import proceeds. Refusing on a
    read error would turn a transient DB problem into a silently skipped import."""
    import contextlib

    @contextlib.contextmanager
    def _boom():
        raise RuntimeError("simulated: store unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr("src.database.session.session_scope", _boom)
    assert m.find_completed_import(_DIGEST) is None


# --------------------------------------------------------------------------- #
#  the wiring: the digest reaches the row, and the skip is not silent
# --------------------------------------------------------------------------- #
def test_run_restore_accepts_and_forwards_a_source_digest():
    """The digest is read by the CALLER (which has the folder) and threaded in, so
    the recording happens inside the merge transaction -- present only if the merge
    committed."""
    import inspect

    assert "source_digest" in inspect.signature(m.run_restore).parameters
    src = inspect.getsource(m.run_restore)
    assert '"source_digest": source_digest' in src, "the digest never reaches batch meta"


def test_the_merge_insert_writes_the_digest_in_its_own_transaction():
    import inspect

    src = inspect.getsource(m.merge_corpus)
    assert "source_digest" in src
    assert 'batch_meta.get("source_digest")' in src


def test_the_skip_names_what_it_matched_and_is_forceable():
    """An import that quietly does nothing is indistinguishable from one that
    failed, so the skip must say which batch and when -- and force must exist."""
    import inspect

    from src.backup import volume_job

    src = inspect.getsource(volume_job.VolumeBackupManager._run_restore)
    assert "artifact_source_digest" in src and "find_completed_import" in src
    assert "already-merged" in src
    assert "merged_as_batch" in src and "merged_at" in src
    assert "self._force" in src, "the skip must be overridable"
    # The check must precede the expensive work, or it saves nothing. Anchored to
    # the CALL sites, not the names: both appear in the import block first, so
    # comparing bare names would compare two imports and pass regardless.
    assert src.index("find_completed_import(") < src.index("read_volume_backup(")
    assert "force" in inspect.signature(volume_job.VolumeBackupManager.start_restore).parameters
