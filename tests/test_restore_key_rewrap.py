"""A restore places a carried key wrapped under THIS install's passphrase, and never over a key that is there (R448).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE TWO DEFECTS. (1) A backup carries the signing keys (``keys/``: the evidence key, the custody signer's two, the
annotation signer's two) as the install that wrote it wrapped them, under ITS passphrase. The restore placed the
bytes as they were, so on an install with another passphrase every export and backup failed on the evidence key
until someone moved the file aside. (2) The placement checked ``exists()`` and then ``os.replace``-d the carried
bytes into place: a key an export created between the two was overwritten, and the bundles already signed with it
lost their signer.

WHAT THE RESTORE DOES NOW (``merge._restore_key_members``). A key this install has is kept. A carried key is opened
with the passphrases the restore has (this install's, the source corpus's, the backup's) and written the way this
install writes its own, checked by reading it back before anything is written. One that none of them opens is not
written and is reported by name. The placement is ``keyfile.create_new``, which refuses to replace a file.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.backup import merge
from src.custody import signing
from tests.backup_helper import staged_artifact

SOURCE = "marker-source-passphrase-5d2e81"  # the passphrase of the install that wrote the backup
BACKUP = "marker-backup-passphrase-a03c47"  # the passphrase the backup itself is encrypted under
HERE = "marker-this-install-passphrase-c9b1"  # the passphrase this install holds
EVIDENCE = "keys/evidence_ed25519.pem"
CUSTODY_ED = "keys/custody_ed25519.pem"
CUSTODY_ML = "keys/custody_ml_dsa_65.key"

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")


class _FakeMldsa:
    """Stands in for the post-quantum backend, so the ML-DSA key file's restore is tested without the library."""

    PUBLIC_KEY_SIZE = 40

    @staticmethod
    def generate_keypair():
        return os.urandom(40), os.urandom(100)


@pytest.fixture(autouse=True)
def _nothing_held_unless_a_test_holds_one(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "live"))
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr(connect, "_passphrase", None)


def _hold(monkeypatch, passphrase: str) -> None:
    monkeypatch.setenv("OO_KEY_PASSPHRASE", passphrase)


def _seed(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )


def _pub(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _plain_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _wrapped(key: Ed25519PrivateKey, passphrase: str) -> bytes:
    """Built from the custody wrap directly, not through the code under test."""
    return signing._wrap(_seed(key), passphrase.encode())


def _opens_with(path: Path, passphrase: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(signing._unwrap(path.read_bytes(), passphrase.encode()))


def _stage(tmp_path: Path, members: dict[str, bytes], *given: str):
    """A real ``StagedArtifact`` carrying ``members`` (role ``keys``) and the passphrases the restore was given."""
    staging = tmp_path / "staging"
    for name, body in members.items():
        p = staging / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    live = tmp_path / "live"
    live.mkdir(exist_ok=True)
    staged = staged_artifact(staging, members=[{"name": n, "role": "keys"} for n in members])
    staged.key_passphrases = tuple(given)
    return staged, live


def test_a_key_wrapped_under_the_source_install_is_placed_wrapped_under_this_one(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    key = Ed25519PrivateKey.generate()
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(key, SOURCE)}, SOURCE, BACKUP)
    out = merge.merge_side_files(staged)["keys"]
    assert out["restored"] == [EVIDENCE] and out["resealed"] == [EVIDENCE], out
    assert out["not_placed"] == [] and out["kept_local"] == []
    placed = live / EVIDENCE
    assert _pub(_opens_with(placed, HERE)) == _pub(key), "the SAME key, now opened by this install's passphrase"
    with pytest.raises(Exception):  # noqa: B017 - the GCM tag check: the source's passphrase no longer opens it
        _opens_with(placed, SOURCE)


def test_the_backup_passphrase_opens_a_key_the_corpus_passphrase_does_not(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    key = Ed25519PrivateKey.generate()
    staged, live = _stage(tmp_path, {CUSTODY_ED: _wrapped(key, BACKUP)}, SOURCE, BACKUP)
    out = merge.merge_side_files(staged)["keys"]
    assert out["resealed"] == [CUSTODY_ED], out
    assert _pub(_opens_with(live / CUSTODY_ED, HERE)) == _pub(key)


def test_a_key_already_wrapped_under_this_install_is_placed_as_carried(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    raw = _wrapped(Ed25519PrivateKey.generate(), HERE)
    staged, live = _stage(tmp_path, {EVIDENCE: raw}, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    assert out["restored"] == [EVIDENCE] and out["resealed"] == [], out
    assert (live / EVIDENCE).read_bytes() == raw


def test_a_key_none_of_the_passphrases_opens_is_not_written_and_is_named(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    raw = _wrapped(Ed25519PrivateKey.generate(), "a-passphrase-nobody-gave-the-restore")
    staged, live = _stage(tmp_path, {EVIDENCE: raw}, SOURCE, BACKUP)
    report = merge.merge_side_files(staged)
    out = report["keys"]
    assert out["restored"] == [] and [e["name"] for e in out["not_placed"]] == [EVIDENCE], out
    assert "not written" in out["not_placed"][0]["reason"]
    assert not (live / EVIDENCE).exists(), "a key this install cannot open blocked every export: it is not placed"
    assert not (live / "keys" / ".pending").exists()
    text = json.dumps(report, default=str)
    for secret in (SOURCE, BACKUP, HERE):
        assert secret not in text


def test_the_key_this_install_has_is_kept_byte_for_byte(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), SOURCE)}, SOURCE)
    mine = _wrapped(Ed25519PrivateKey.generate(), HERE)
    (live / "keys").mkdir()
    (live / EVIDENCE).write_bytes(mine)
    out = merge.merge_side_files(staged)["keys"]
    assert out["kept_local"] == [EVIDENCE] and out["restored"] == [], out
    assert (live / EVIDENCE).read_bytes() == mine


def test_a_key_made_while_the_restore_ran_is_never_overwritten(tmp_path, monkeypatch):
    """The race: the key is absent when the restore looks and present when it places. It used to be replaced."""
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), SOURCE)}, SOURCE)
    theirs = _wrapped(Ed25519PrivateKey.generate(), HERE)
    real = merge._reseal_key

    def an_export_makes_its_key_meanwhile(kind, local, raw, candidates, held):
        out = real(kind, local, raw, candidates, held)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(theirs)
        return out

    monkeypatch.setattr(merge, "_reseal_key", an_export_makes_its_key_meanwhile)
    out = merge.merge_side_files(staged)["keys"]
    assert (live / EVIDENCE).read_bytes() == theirs, "the key an export made in between is the one that stays"
    assert out["kept_local"] == [EVIDENCE] and out["restored"] == [], out
    assert not (live / "keys" / ".pending").exists()


def test_a_sealed_copy_that_does_not_read_back_as_the_same_key_is_not_written(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), SOURCE)}, SOURCE)
    other = Ed25519PrivateKey.generate()
    real_seal = signing.seal_ed25519_key
    monkeypatch.setattr(signing, "seal_ed25519_key", lambda _key, passphrase: real_seal(other, passphrase))
    out = merge.merge_side_files(staged)["keys"]
    assert [e["name"] for e in out["not_placed"]] == [EVIDENCE], out
    assert "did not read back as the same key" in out["not_placed"][0]["reason"]
    assert not (live / EVIDENCE).exists()


def test_a_plaintext_key_is_wrapped_as_it_is_placed(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    key = Ed25519PrivateKey.generate()
    staged, live = _stage(tmp_path, {EVIDENCE: _plain_pem(key)}, BACKUP)
    out = merge.merge_side_files(staged)["keys"]
    assert out["resealed"] == [EVIDENCE], out
    assert b"-----BEGIN" not in (live / EVIDENCE).read_bytes()
    assert _pub(_opens_with(live / EVIDENCE, HERE)) == _pub(key)


@posix_only
def test_an_install_that_holds_no_passphrase_gets_the_plaintext_key_it_writes_itself(tmp_path):
    key = Ed25519PrivateKey.generate()
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(key, BACKUP)}, BACKUP)
    out = merge.merge_side_files(staged)["keys"]
    assert out["resealed"] == [EVIDENCE], out
    placed = live / EVIDENCE
    loaded = serialization.load_pem_private_key(placed.read_bytes(), password=None)
    assert isinstance(loaded, Ed25519PrivateKey) and _pub(loaded) == _pub(key)
    assert stat.S_IMODE(placed.stat().st_mode) == 0o600


def test_the_restored_evidence_key_signs_on_this_install(tmp_path, monkeypatch):
    """The defect as an operator met it: after the restore, the evidence key loads under this install's passphrase."""
    from src.reporting import evidence as ev

    _hold(monkeypatch, HERE)
    key = Ed25519PrivateKey.generate()
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(key, SOURCE)}, SOURCE)
    merge.merge_side_files(staged)
    assert ev.public_key_hex(ev.load_or_create_signing_key(live / EVIDENCE)) == _pub(key).hex()


def test_an_mldsa_key_is_resealed_as_the_same_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    _hold(monkeypatch, HERE)
    pk, sk = _FakeMldsa.generate_keypair()
    staged, live = _stage(tmp_path, {CUSTODY_ML: signing.seal_mldsa_key(pk, sk, SOURCE.encode())}, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    assert out["resealed"] == [CUSTODY_ML], out
    raw = (live / CUSTODY_ML).read_bytes()
    assert signing.parse_mldsa_key(live / CUSTODY_ML, raw, HERE.encode()) == (pk, sk, "wrapped")


def test_an_mldsa_key_is_not_placed_where_the_library_cannot_read_it(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {CUSTODY_ML: os.urandom(200)}, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    assert [e["name"] for e in out["not_placed"]] == [CUSTODY_ML], out
    assert "post-quantum" in out["not_placed"][0]["reason"]
    assert not (live / CUSTODY_ML).exists()


def test_a_file_that_is_not_a_key_this_app_writes_is_carried_and_said_so(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {"keys/notes.txt": b"something an operator kept here"}, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    assert out["restored"] == ["keys/notes.txt"] and out["carried_unread"] == ["keys/notes.txt"], out
    assert (live / "keys" / "notes.txt").read_bytes() == b"something an operator kept here"


def test_a_member_name_outside_the_keys_folder_is_refused(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {"keys/deeper/notes.txt": b"x"}, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    assert [e["name"] for e in out["not_placed"]] == ["keys/deeper/notes.txt"], out
    assert not (live / "keys" / "deeper").exists()


def test_the_passphrases_never_show_in_the_staged_artifact_repr(tmp_path):
    staged, _live = _stage(tmp_path, {}, SOURCE, BACKUP)
    assert SOURCE not in repr(staged) and BACKUP not in repr(staged)


def test_the_readers_hand_the_restore_the_passphrases_they_were_given():
    from src.backup.artifact import key_passphrases_for

    assert key_passphrases_for(SOURCE, BACKUP) == (SOURCE, BACKUP)
    assert key_passphrases_for(None, BACKUP) == (BACKUP,)
    assert key_passphrases_for(BACKUP, BACKUP) == (BACKUP,)
    assert key_passphrases_for(None, None) == ()


def test_a_backup_written_on_another_install_restores_a_key_that_signs_here(tmp_path, monkeypatch):
    """End to end through the real writer and reader: the evidence key made by the export on install A (holding
    SOURCE) comes back on install B (holding HERE) under B's passphrase, opened with the corpus passphrase given."""
    from src.backup.export_folder import allocate_export_folder
    from src.backup.stream_backup import CorpusSource, _no_freeze, read_stream_backup, write_stream_backup
    from src.reporting import evidence as ev
    from tests.test_evidence_key_wrap import _corpus

    a = tmp_path / "install-a"
    monkeypatch.setenv("OO_DATA_DIR", str(a))
    _hold(monkeypatch, SOURCE)
    dest = allocate_export_folder(tmp_path / "drive")
    src = CorpusSource(path=_corpus(tmp_path), member_name="corpus.db", encrypted=False, freeze=_no_freeze)
    summary = write_stream_backup(dest, BACKUP, corpus_source=src, volume_size=128 * 1024)
    signer = summary["envelope"]["public_key"]

    b = tmp_path / "install-b"
    b.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(b))
    _hold(monkeypatch, HERE)
    staged = read_stream_backup(dest, BACKUP, b / "staging-root", corpus_passphrase=SOURCE)
    assert staged.key_passphrases == (SOURCE, BACKUP)
    out = merge.merge_side_files(staged)["keys"]
    assert EVIDENCE in out["resealed"], out
    assert ev.public_key_hex(ev.load_or_create_signing_key(b / EVIDENCE)) == signer
