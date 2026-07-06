"""
Regression: imported-annotation authors must survive an additive restore.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The bug (wave-3): a signed annotation bundle is imported once, which writes a
VERIFIED imported-author RECORD (manifest + signature stripped, only the verified
content + a verify_reason provenance note kept). A backup collects that record file.
On restore, ``merge_side_files`` re-passed the record to ``store.import_bundle``,
which correctly rejects a bundle-less record as malformed -> every imported author
silently failed to restore (the error was swallowed into ann['errors']).

The fix adopts the already-verified record directly (re-verification is impossible;
the artifact's own signature vouches for the payload; local always wins). These tests
prove the author IS restored and no errors are reported, and that the public
untrusted-bundle verifier ``import_bundle`` is unchanged (still rejects the record).
"""

from __future__ import annotations

import json
import shutil

import pytest

from src.annotations import bundle as bundle_mod
from src.annotations import store
from src.backup.artifact import StagedArtifact


def _make_signed_bundle(author_name: str) -> dict:
    annotations = [
        bundle_mod.Annotation(target="cnn.com", kind="ownership", value="owned by Example Corp"),
        bundle_mod.Annotation(target="foo.test", kind="leaning", value="lean-left"),
    ]
    signer = bundle_mod.annotation_signer()
    return bundle_mod.build_signed_bundle(author_name, annotations, signer)


def _staged_from(staging_dir, member_name: str) -> StagedArtifact:
    return StagedArtifact(
        kind="oo-backup-2",
        staging_dir=staging_dir,
        corpus_path=staging_dir / "corpus.db",
        custody_path=None,
        manifest={"app_version": "0.1.0"},
        signature_state="verified",
        origin_fingerprint="deadbeef" * 8,
        members=[{"name": member_name, "role": "annotations"}],
    )


def test_imported_author_survives_restore(monkeypatch, tmp_path):
    """signed bundle -> import (creates record) -> collect as backup member ->
    merge_side_files over a FRESH data dir -> the author IS restored, no errors."""
    # --- data dir A: author imports a signed bundle (writes the record) --------
    dir_a = tmp_path / "a"
    monkeypatch.setenv("OO_DATA_DIR", str(dir_a))
    bundle = _make_signed_bundle("Alice")
    summary = store.import_bundle(bundle, trusted=True)
    assert summary["annotations"] == 2
    imported = list((dir_a / "annotations" / "imported").glob("*.json"))
    assert len(imported) == 1, "import_bundle should write exactly one author record"
    record_file = imported[0]

    # --- collect the record as a backup member (name == data-dir-relative path) -
    staging = tmp_path / "staging"
    member_name = f"annotations/imported/{record_file.name}"
    dest = staging / member_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(record_file, dest)

    # --- data dir B: a FRESH machine restores the backup additively ------------
    dir_b = tmp_path / "b"
    monkeypatch.setenv("OO_DATA_DIR", str(dir_b))
    assert store.list_authors() == [], "fresh data dir has no imported authors"

    from src.backup.merge import merge_side_files

    report = merge_side_files(_staged_from(staging, member_name))

    ann = report["annotations"]
    assert ann["errors"] == [], f"restore reported errors: {ann['errors']}"
    assert ann["imported_authors"] == 1
    # The author is genuinely present and aggregatable on the fresh machine.
    authors = store.list_authors()
    assert len(authors) == 1
    assert authors[0]["author_name"] == "Alice"
    assert authors[0]["annotations"] == 2
    assert authors[0]["trusted"] is True  # the record's own trust decision is preserved
    agg = store.aggregate_for_target("cnn.com")
    assert agg["total_assertions"] == 1


def test_restore_keeps_local_author_record(monkeypatch, tmp_path):
    """Additive + local-wins: an existing local record is never overwritten."""
    dir_a = tmp_path / "a"
    monkeypatch.setenv("OO_DATA_DIR", str(dir_a))
    store.import_bundle(_make_signed_bundle("Alice"), trusted=True)
    record_file = next((dir_a / "annotations" / "imported").glob("*.json"))

    staging = tmp_path / "staging"
    member_name = f"annotations/imported/{record_file.name}"
    dest = staging / member_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(record_file, dest)

    # Same data dir A already holds this author -> the member is kept-local.
    from src.backup.merge import merge_side_files

    report = merge_side_files(_staged_from(staging, member_name))
    ann = report["annotations"]
    assert ann["errors"] == []
    assert ann["imported_authors"] == 0
    assert ann["kept_local"] == 1


def test_unverified_artifact_adopts_untrusted(monkeypatch, tmp_path):
    """An allow-unverified restore must NOT auto-trust an incoming author, even if the
    record claims trusted:true -- a crafted record can't escalate its own trust."""
    dir_a = tmp_path / "a"
    monkeypatch.setenv("OO_DATA_DIR", str(dir_a))
    store.import_bundle(_make_signed_bundle("Mallory"), trusted=True)  # record says trusted
    record_file = next((dir_a / "annotations" / "imported").glob("*.json"))

    staging = tmp_path / "staging"
    member_name = f"annotations/imported/{record_file.name}"
    dest = staging / member_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(record_file, dest)

    dir_b = tmp_path / "b"
    monkeypatch.setenv("OO_DATA_DIR", str(dir_b))
    from src.backup.merge import merge_side_files

    staged = _staged_from(staging, member_name)
    staged.signature_state = "unsigned"  # the allow-unverified restore posture
    report = merge_side_files(staged)
    assert report["annotations"]["imported_authors"] == 1
    authors = store.list_authors()
    assert authors[0]["trusted"] is False  # never auto-trusted from an unverified artifact


def test_adopt_rejects_path_traversal_author_id(monkeypatch, tmp_path):
    """A crafted author_id with path separators / traversal cannot write outside
    imported/ (CWE-22): adopt refuses it and merge_side_files reports the error."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.annotations.store import STORE_VERSION, adopt_imported_record

    for evil in ("../../../../escape_pwned", "../mine", "a/b", "..", "with space", ""):
        with pytest.raises(ValueError):
            adopt_imported_record({"version": STORE_VERSION, "author_id": evil, "annotations": []})

    # end-to-end: a backup member carrying a traversal author_id is reported, not written.
    staging = tmp_path / "staging"
    member = "annotations/imported/innocuous.json"
    dest = staging / member
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({
            "version": STORE_VERSION, "author_id": "../../../../pwned_via_merge",
            "author_name": "attacker",
            "annotations": [{"target": "cnn.com", "kind": "note", "value": "x"}],
        }),
        encoding="utf-8",
    )
    from src.backup.merge import merge_side_files

    report = merge_side_files(_staged_from(staging, member))
    assert report["annotations"]["errors"], "a traversal author_id must be reported, not adopted"
    assert report["annotations"]["imported_authors"] == 0


def test_adopt_imported_record_rejects_a_bundleless_record(monkeypatch, tmp_path):
    """A raw signed BUNDLE (not a record) is refused by adopt (structural check),
    just as a RECORD is refused by import_bundle -- neither path is weakened."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    bundle = _make_signed_bundle("Alice")  # a signed bundle, NOT an imported record
    with pytest.raises(ValueError):
        store.adopt_imported_record(bundle)
    # And the public untrusted-bundle verifier still rejects a record (unchanged).
    store.import_bundle(bundle, trusted=True)
    record = json.loads(
        next((tmp_path / "annotations" / "imported").glob("*.json")).read_text(encoding="utf-8")
    )
    with pytest.raises(ValueError):
        store.import_bundle(record)  # the exact malformed-input path the bug hit
