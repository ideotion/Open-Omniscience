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
    from src.reporting.evidence import load_or_create_signing_key, public_key_hex

    staged = _staged_from(staging, member_name)
    staged.origin_fingerprint = public_key_hex(load_or_create_signing_key())  # a backup THIS installation signed (R800)
    report = merge_side_files(staged)

    ann = report["annotations"]
    assert ann["errors"] == [], f"restore reported errors: {ann['errors']}"
    assert ann["imported_authors"] == 1
    assert "trust_withheld" not in ann
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
    withheld = report["annotations"]["trust_withheld"]
    assert withheld["count"] == 1 and withheld["offered"] is False and withheld["signer"] is None
    assert authors[0]["trust_withheld_by"] is None and store.withheld_trust() == []  # no offer for an unverified backup


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


# --------------------------------------------------------------------------- #
#  R800 / row 339: trust decisions from another installation's backup need a click
# --------------------------------------------------------------------------- #
OTHER_KEY = "ab" * 32


def _member_from_another_install(monkeypatch, tmp_path, name: str = "Alice", *, trusted: bool = True):
    dir_a = tmp_path / f"a-{name}"
    monkeypatch.setenv("OO_DATA_DIR", str(dir_a))
    store.import_bundle(_make_signed_bundle(name), trusted=trusted)
    record_file = next((dir_a / "annotations" / "imported").glob("*.json"))
    staging = tmp_path / f"staging-{name}"
    member_name = f"annotations/imported/{record_file.name}"
    dest = staging / member_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(record_file, dest)
    staged = _staged_from(staging, member_name)
    staged.origin_fingerprint = OTHER_KEY
    return staged


def test_another_installations_trust_decisions_are_withheld_and_named(monkeypatch, tmp_path):
    staged = _member_from_another_install(monkeypatch, tmp_path)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    from src.backup.merge import merge_side_files

    ann = merge_side_files(staged)["annotations"]
    assert ann["imported_authors"] == 1 and ann["errors"] == []  # the rest imports as before
    withheld = ann["trust_withheld"]
    assert withheld["count"] == 1 and withheld["signer"] == OTHER_KEY and withheld["offered"] is True
    assert "a key this installation did not make" in withheld["reason"]
    author = store.list_authors()[0]
    assert author["trusted"] is False and author["trust_withheld_by"] == OTHER_KEY
    assert store.withheld_trust() == [{"signer": OTHER_KEY, "count": 1, "authors": [
        {"author_id": author["author_id"], "author_name": "Alice"}]}]


def test_one_click_applies_them_and_a_stale_count_changes_nothing(monkeypatch, tmp_path):
    from src.backup.merge import merge_side_files

    staged_a = _member_from_another_install(monkeypatch, tmp_path, "Alice")
    staged_b = _member_from_another_install(monkeypatch, tmp_path, "Bob")
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    merge_side_files(staged_a)
    merge_side_files(staged_b)
    with pytest.raises(ValueError, match="now 2, not 1"):
        store.settle_withheld_trust(OTHER_KEY, apply=True, expected_count=1)  # the person was shown one
    assert all(a["trusted"] is False for a in store.list_authors())
    assert store.settle_withheld_trust(OTHER_KEY.upper(), apply=True, expected_count=2) == 2
    assert all(a["trusted"] is True and a["trust_withheld_by"] is None for a in store.list_authors())
    assert store.withheld_trust() == []


def test_no_leaves_them_untrusted_and_the_question_gone(monkeypatch, tmp_path):
    staged = _member_from_another_install(monkeypatch, tmp_path)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    from src.backup.merge import merge_side_files

    merge_side_files(staged)
    assert store.settle_withheld_trust(OTHER_KEY, apply=False, expected_count=1) == 1
    author = store.list_authors()[0]
    assert author["trusted"] is False and author["trust_withheld_by"] is None


def test_an_existing_local_decision_is_never_touched_from_another_key(monkeypatch, tmp_path):
    staged = _member_from_another_install(monkeypatch, tmp_path)
    dir_b = tmp_path / "b"
    monkeypatch.setenv("OO_DATA_DIR", str(dir_b))
    member = next((staged.staging_dir / "annotations" / "imported").glob("*.json"))
    local = dir_b / "annotations" / "imported" / member.name  # this installation already holds this author, untrusted
    local.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(member, local)
    rec = json.loads(local.read_text("utf-8"))
    rec["trusted"] = False
    local.write_text(json.dumps(rec), encoding="utf-8")
    from src.backup.merge import merge_side_files

    ann = merge_side_files(staged)["annotations"]
    assert ann["kept_local"] == 1 and "trust_withheld" not in ann
    assert json.loads(local.read_text("utf-8"))["trusted"] is False and store.withheld_trust() == []


def test_a_crafted_marker_in_the_backup_is_dropped(monkeypatch, tmp_path):
    """Only this module writes the marker: a record that brings its own (naming any key) loses it."""
    staged = _member_from_another_install(monkeypatch, tmp_path, trusted=False)
    member = next((staged.staging_dir / "annotations" / "imported").glob("*.json"))
    rec = json.loads(member.read_text("utf-8"))
    rec[store.TRUST_WITHHELD] = {"signer": "cd" * 32}
    member.write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    from src.backup.merge import merge_side_files

    ann = merge_side_files(staged)["annotations"]
    assert "trust_withheld" not in ann  # the record said untrusted: nothing was withheld
    assert store.withheld_trust() == [] and store.list_authors()[0]["trust_withheld_by"] is None


def test_a_manual_trust_toggle_settles_the_question(monkeypatch, tmp_path):
    staged = _member_from_another_install(monkeypatch, tmp_path)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    from src.backup.merge import merge_side_files

    merge_side_files(staged)
    aid = store.list_authors()[0]["author_id"]
    assert store.set_trusted(aid, True)
    assert store.withheld_trust() == []


def test_the_endpoint_refuses_a_key_that_is_not_one(monkeypatch, tmp_path):
    from fastapi import HTTPException

    from src.api import annotations as api

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    for body in ({"signer": "zz", "count": 1, "authors": []}, {"signer": OTHER_KEY, "count": -1, "authors": []}):
        with pytest.raises(HTTPException) as refused:
            api.settle_withheld_trust(api.WithheldTrustDecision(**body))
        assert refused.value.status_code == 400
    with pytest.raises(HTTPException) as stale:
        api.settle_withheld_trust(api.WithheldTrustDecision(signer=OTHER_KEY, count=3, apply=True, authors=[]))
    assert stale.value.status_code == 409


@pytest.mark.parametrize("spelling", ["annotations/./imported/{f}", "annotations//imported/{f}", "./annotations/imported/{f}"])
def test_another_spelling_of_an_imported_record_still_passes_the_gate(monkeypatch, tmp_path, spelling):
    """Security read of row 339: the staging join drops "." segments and doubled "/", so routing on the name's
    spelling sent these past adopt_imported_record and wrote their trust flag as it came."""
    staged = _member_from_another_install(monkeypatch, tmp_path)
    real = staged.members[0]["name"]
    staged.members[0]["name"] = spelling.format(f=real.rsplit("/", 1)[1])
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    from src.backup.merge import merge_side_files

    ann = merge_side_files(staged)["annotations"]
    assert ann["imported_authors"] == 1 and ann.get("restored_mine") is None
    assert ann["trust_withheld"]["count"] == 1
    (author,) = store.list_authors()
    assert author["trusted"] is False and author["trust_withheld_by"] == OTHER_KEY


@pytest.mark.parametrize("name", ["keys/evidence_ed25519.pem", "state.json", "annotations", "annotations/notes.txt", "annotations/other.json",
     "annotations/imported/deeper/x.json"])
def test_an_annotations_member_outside_annotations_json_is_refused(monkeypatch, tmp_path, name):
    staging = tmp_path / "staging"
    (staging / name).parent.mkdir(parents=True, exist_ok=True)
    if name == "annotations":
        (staging / name).mkdir(exist_ok=True)
        (staging / name / "x").write_text("x")
    else:
        (staging / name).write_text("{}")
    staged = _staged_from(staging, name)
    base = tmp_path / "b"
    monkeypatch.setenv("OO_DATA_DIR", str(base))
    from src.backup.merge import merge_side_files

    ann = merge_side_files(staged)["annotations"]
    assert len(ann["errors"]) == 1 and "refused" in ann["errors"][0]
    assert not (base / name).exists()


def test_a_swap_that_keeps_the_count_changes_nothing(monkeypatch, tmp_path):
    """Security read of row 339: the click names the authors it showed, so one record removed and another from the
    same key added between the look and the click (count unchanged) applies nothing."""
    from src.backup.merge import merge_side_files

    staged_a = _member_from_another_install(monkeypatch, tmp_path, "Alice")
    staged_b = _member_from_another_install(monkeypatch, tmp_path, "Bob")
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    merge_side_files(staged_a)
    shown = [a["author_id"] for a in store.withheld_trust()[0]["authors"]]
    alice = store.list_authors()[0]["author_id"]
    assert store.remove_author(alice)
    merge_side_files(staged_b)  # Bob arrives from the same key: still one withheld decision
    with pytest.raises(ValueError, match="no longer the ones shown"):
        store.settle_withheld_trust(OTHER_KEY, apply=True, expected_count=1, expected_authors=shown)
    assert all(a["trusted"] is False for a in store.list_authors())
    bob = [a["author_id"] for a in store.withheld_trust()[0]["authors"]]
    assert store.settle_withheld_trust(OTHER_KEY, apply=True, expected_count=1, expected_authors=bob) == 1


def test_the_endpoint_passes_the_authors_it_was_shown(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import annotations as api_mod
    from src.backup.merge import merge_side_files

    staged = _member_from_another_install(monkeypatch, tmp_path)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    merge_side_files(staged)
    app = FastAPI()
    app.include_router(api_mod.router)
    c = TestClient(app)
    body = {"signer": OTHER_KEY, "count": 1, "apply": True, "authors": ["0" * 32]}
    assert c.post("/api/annotations/withheld-trust", json=body).status_code == 409
    body["authors"] = [store.list_authors()[0]["author_id"]]
    r = c.post("/api/annotations/withheld-trust", json=body)
    assert r.status_code == 200 and r.json()["applied"] == 1
