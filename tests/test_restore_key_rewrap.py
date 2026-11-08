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
def test_an_install_that_holds_no_passphrase_gets_the_carried_key_still_encrypted_never_in_the_clear(tmp_path):
    """R613: the restore could open it with the backup's passphrase, and still writes nothing in the clear: the bytes are
    placed as carried, and the import report says how to unlock them."""
    from src.backup.import_reports import render_import_report_markdown

    key = Ed25519PrivateKey.generate()
    carried = _wrapped(key, BACKUP)
    staged, live = _stage(tmp_path, {EVIDENCE: carried}, BACKUP)
    keys = merge.merge_side_files(staged)["keys"]
    assert keys["still_encrypted"] == [EVIDENCE] and keys["resealed"] == [] and keys["restored"] == [EVIDENCE], keys
    placed = live / EVIDENCE
    assert placed.read_bytes() == carried, "placed exactly as carried"
    assert _pub(_opens_with(placed, BACKUP)) == _pub(key), "and it is the same key, under the backup's passphrase"
    assert stat.S_IMODE(placed.stat().st_mode) == 0o600
    md = render_import_report_markdown({"outcome": "ok", "side_files": {"keys": keys}})
    assert "## Signing keys still encrypted" in md
    assert "still encrypted with the backup's passphrase" in md and "set OO_KEY_PASSPHRASE to that passphrase and restart" in md
    assert f"- `{EVIDENCE}`" in md


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
    from src.backup.stream_backup import (
        CorpusSource,
        _no_freeze,
        read_stream_backup,
        write_stream_backup,
    )
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


# --------------------------------------------------------------------------- #
#  The independent read's findings (2026-11-08): pairs, parse failures, the
#  operator's report, and the claims that had no test of their own.
# --------------------------------------------------------------------------- #
def _unknown_algorithm_pem() -> bytes:
    """A PKCS8 PEM whose algorithm OID (1.2.3.4) the library does not know: it raises UnsupportedAlgorithm, not SigningError."""
    import base64

    der = bytes.fromhex("302e020100300506032a0304042204 20".replace(" ", "")) + os.urandom(32)
    return b"-----BEGIN PRIVATE KEY-----\n" + base64.encodebytes(der) + b"-----END PRIVATE KEY-----\n"


def test_a_plaintext_key_is_placed_when_nothing_is_held_or_given(tmp_path):
    raw = _plain_pem(Ed25519PrivateKey.generate())
    staged, live = _stage(tmp_path, {EVIDENCE: raw})
    out = merge.merge_side_files(staged)["keys"]
    assert out["restored"] == [EVIDENCE] and out["resealed"] == [], out
    assert (live / EVIDENCE).read_bytes() == raw and out["still_encrypted"] == []
    assert out["written_as"].startswith("as carried"), out["written_as"]


def test_a_passphrase_this_install_cannot_encode_writes_no_key(tmp_path, monkeypatch):
    """Nothing can be wrapped under it, so a key is not written at all: never written plaintext on an encrypted install."""
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", "lone-\ud800-surrogate")
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), BACKUP)}, BACKUP)
    out = merge.merge_side_files(staged)["keys"]
    assert [e["name"] for e in out["not_placed"]] == [EVIDENCE], out
    assert "not written" in out["not_placed"][0]["reason"]
    assert not (live / EVIDENCE).exists()


def test_the_live_database_passphrase_is_tried_when_another_one_is_held(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", "marker-live-db-passphrase-71e0")
    _hold(monkeypatch, HERE)  # OO_KEY_PASSPHRASE: the key passphrase this install holds
    key = Ed25519PrivateKey.generate()
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(key, "marker-live-db-passphrase-71e0")})
    out = merge.merge_side_files(staged)["keys"]
    assert out["resealed"] == [EVIDENCE], out
    assert _pub(_opens_with(live / EVIDENCE, HERE)) == _pub(key)


def test_an_mldsa_copy_that_does_not_read_back_as_the_same_pair_is_not_written(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    _hold(monkeypatch, HERE)
    pk, sk = _FakeMldsa.generate_keypair()
    staged, live = _stage(tmp_path, {CUSTODY_ML: signing.seal_mldsa_key(pk, sk, SOURCE.encode())}, SOURCE)
    real_seal = signing.seal_mldsa_key
    other_pk, other_sk = _FakeMldsa.generate_keypair()
    monkeypatch.setattr(signing, "seal_mldsa_key", lambda _pk, _sk, passphrase: real_seal(other_pk, other_sk, passphrase))
    out = merge.merge_side_files(staged)["keys"]
    assert [e["name"] for e in out["not_placed"]] == [CUSTODY_ML], out
    assert "did not read back as the same key" in out["not_placed"][0]["reason"]
    assert not (live / CUSTODY_ML).exists()


def test_a_key_file_the_library_cannot_parse_is_reported_and_the_import_goes_on(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {EVIDENCE: _unknown_algorithm_pem(), "keys/notes.txt": b"kept"}, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    assert [e["name"] for e in out["not_placed"]] == [EVIDENCE], out
    assert out["restored"] == ["keys/notes.txt"], "the step went on past the file it could not read"
    assert not (live / EVIDENCE).exists()


def test_a_write_failure_placing_a_key_fails_the_stage(tmp_path, monkeypatch):
    """An OSError other than "a file is there" is not a kept key: the import fails before the live corpus is touched."""
    from src.custody import keyfile

    _hold(monkeypatch, HERE)
    staged, _live = _stage(tmp_path, {EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), HERE)}, SOURCE)

    def disk_full(path, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(keyfile, "create_new", disk_full)
    with pytest.raises(OSError, match="No space left"):
        merge.merge_side_files(staged)


def test_a_keys_path_that_is_a_file_fails_the_stage_and_is_not_called_kept(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), HERE)}, SOURCE)
    (live / "keys").write_bytes(b"not a folder")
    with pytest.raises(OSError):
        merge.merge_side_files(staged)


def test_half_a_pair_is_never_grafted_onto_the_half_this_install_has(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    _hold(monkeypatch, HERE)
    pk, sk = _FakeMldsa.generate_keypair()
    carried = {
        CUSTODY_ED: _wrapped(Ed25519PrivateKey.generate(), SOURCE),
        CUSTODY_ML: signing.seal_mldsa_key(pk, sk, SOURCE.encode()),
    }
    staged, live = _stage(tmp_path, carried, SOURCE)
    mine = _wrapped(Ed25519PrivateKey.generate(), HERE)
    (live / "keys").mkdir()
    (live / CUSTODY_ED).write_bytes(mine)
    out = merge.merge_side_files(staged)["keys"]
    assert sorted(out["kept_local"]) == [CUSTODY_ED, CUSTODY_ML] and out["restored"] == [], out
    assert (live / CUSTODY_ED).read_bytes() == mine
    assert not (live / CUSTODY_ML).exists(), "the source's ML-DSA key would have signed beside this install's Ed25519 key"


def test_a_pair_is_placed_whole_or_not_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    _hold(monkeypatch, HERE)
    carried = {CUSTODY_ED: _wrapped(Ed25519PrivateKey.generate(), SOURCE), CUSTODY_ML: os.urandom(200)}
    staged, live = _stage(tmp_path, carried, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    reasons = {e["name"]: e["reason"] for e in out["not_placed"]}
    assert set(reasons) == {CUSTODY_ED, CUSTODY_ML}, out
    assert "post-quantum" in reasons[CUSTODY_ML] and "pair" in reasons[CUSTODY_ED]
    assert not (live / CUSTODY_ED).exists() and not (live / CUSTODY_ML).exists()


def test_a_pair_both_halves_of_which_open_is_placed_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    _hold(monkeypatch, HERE)
    ed = Ed25519PrivateKey.generate()
    pk, sk = _FakeMldsa.generate_keypair()
    carried = {CUSTODY_ED: _wrapped(ed, SOURCE), CUSTODY_ML: signing.seal_mldsa_key(pk, sk, SOURCE.encode())}
    staged, live = _stage(tmp_path, carried, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    assert sorted(out["resealed"]) == [CUSTODY_ED, CUSTODY_ML], out
    assert _pub(_opens_with(live / CUSTODY_ED, HERE)) == _pub(ed)
    assert signing.parse_mldsa_key(live / CUSTODY_ML, (live / CUSTODY_ML).read_bytes(), HERE.encode())[:2] == (pk, sk)


def test_the_import_report_names_a_key_that_was_not_restored():
    from src.backup.import_reports import render_import_report_markdown

    md = render_import_report_markdown(
        {"outcome": "ok", "side_files": {"keys": {"not_placed": [{"name": EVIDENCE, "reason": "a fixed reason"}]}}}
    )
    assert "## Signing keys not restored" in md
    assert f"`{EVIDENCE}`: a fixed reason" in md
    quiet = render_import_report_markdown({"outcome": "ok", "side_files": {"keys": {"not_placed": [], "restored": [EVIDENCE]}}})
    assert "Signing keys" not in quiet


def test_the_single_file_reader_hands_the_restore_its_backup_passphrase(tmp_path, monkeypatch):
    from src.backup.artifact import cleanup_staging, read_artifact, write_backup_v2
    from src.database.session import init_db

    _hold(monkeypatch, SOURCE)
    init_db()
    dest = tmp_path / "one.oobak"
    write_backup_v2(dest, passphrase=BACKUP)
    staged = read_artifact(dest.read_bytes(), BACKUP, staging_root=tmp_path)
    try:
        assert staged.key_passphrases == (BACKUP,)
    finally:
        cleanup_staging(staged)


def test_the_legacy_volume_reader_hands_the_restore_both_passphrases(tmp_path, monkeypatch):
    from src.backup.artifact import cleanup_staging, read_volume_backup, write_backup_v2
    from src.backup.volumes import write_volume_set
    from src.database.session import init_db

    init_db()
    inner = tmp_path / "inner.zip"
    write_backup_v2(inner)  # an oo-backup-2 zip, the payload a legacy oo-volumes-1 set carries
    vols = tmp_path / "vols"
    write_volume_set(inner, vols, BACKUP)
    staged = read_volume_backup(vols, BACKUP, tmp_path, corpus_passphrase=SOURCE)
    try:
        assert staged.key_passphrases == (SOURCE, BACKUP)
    finally:
        cleanup_staging(staged)


# --------------------------------------------------------------------------- #
#  The delta read's findings (2026-11-08).
# --------------------------------------------------------------------------- #
def test_without_the_post_quantum_library_a_wrapped_pair_is_still_restored_whole(tmp_path, monkeypatch):
    """The ML-DSA wrap is AES-GCM over the key bytes: it moves under this install's passphrase with no ML-DSA code."""
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    _hold(monkeypatch, HERE)
    ed = Ed25519PrivateKey.generate()
    ml = os.urandom(140)  # public + secret key bytes, as the signer stores them
    carried = {CUSTODY_ED: _wrapped(ed, SOURCE), CUSTODY_ML: signing.seal_mldsa_key(ml, b"", SOURCE.encode())}
    staged, live = _stage(tmp_path, carried, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    assert sorted(out["resealed"]) == [CUSTODY_ED, CUSTODY_ML] and out["not_placed"] == [], out
    assert _pub(_opens_with(live / CUSTODY_ED, HERE)) == _pub(ed)
    assert signing._unwrap((live / CUSTODY_ML).read_bytes(), HERE.encode()) == ml


def test_without_the_library_an_mldsa_key_already_wrapped_here_is_placed_as_carried(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    _hold(monkeypatch, HERE)
    raw = signing.seal_mldsa_key(os.urandom(140), b"", HERE.encode())
    staged, live = _stage(tmp_path, {CUSTODY_ML: raw}, SOURCE)
    out = merge.merge_side_files(staged)["keys"]
    assert out["restored"] == [CUSTODY_ML] and out["resealed"] == [], out
    assert (live / CUSTODY_ML).read_bytes() == raw


def test_without_the_library_and_nothing_held_a_wrapped_mldsa_key_is_placed_still_encrypted(tmp_path, monkeypatch):
    """R613 on the move without the post-quantum library: opened to know it is a key, never written in the clear."""
    from src.backup.import_reports import render_import_report_markdown

    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    ml = os.urandom(140)
    carried = signing.seal_mldsa_key(ml, b"", BACKUP.encode())
    staged, live = _stage(tmp_path, {CUSTODY_ML: carried}, BACKUP)
    keys = merge.merge_side_files(staged)["keys"]
    assert keys["still_encrypted"] == [CUSTODY_ML] and keys["resealed"] == [], keys
    assert (live / CUSTODY_ML).read_bytes() == carried
    md = render_import_report_markdown({"outcome": "ok", "side_files": {"keys": keys}})
    assert "## Signing keys still encrypted" in md and f"- `{CUSTODY_ML}`" in md
    assert "set OO_KEY_PASSPHRASE to that passphrase and restart" in md


def test_a_pair_whose_first_half_another_caller_made_meanwhile_is_not_completed(tmp_path, monkeypatch):
    """The restore sees the refusal for the first half, so it must not place the second half beside theirs."""
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    _hold(monkeypatch, HERE)
    pk, sk = _FakeMldsa.generate_keypair()
    carried = {
        CUSTODY_ED: _wrapped(Ed25519PrivateKey.generate(), SOURCE),
        CUSTODY_ML: signing.seal_mldsa_key(pk, sk, SOURCE.encode()),
    }
    staged, live = _stage(tmp_path, carried, SOURCE)
    theirs = _wrapped(Ed25519PrivateKey.generate(), HERE)
    real = merge._reseal_key

    def a_signer_starts_while_the_pair_is_resealed(kind, local, raw, candidates, held):
        out = real(kind, local, raw, candidates, held)
        if kind == "ml_dsa":
            (live / CUSTODY_ED).parent.mkdir(parents=True, exist_ok=True)
            (live / CUSTODY_ED).write_bytes(theirs)
        return out

    monkeypatch.setattr(merge, "_reseal_key", a_signer_starts_while_the_pair_is_resealed)
    out = merge.merge_side_files(staged)["keys"]
    assert out["kept_local"] == [CUSTODY_ED] and out["restored"] == [], out
    assert [e["name"] for e in out["not_placed"]] == [CUSTODY_ML]
    assert (live / CUSTODY_ED).read_bytes() == theirs
    assert not (live / CUSTODY_ML).exists(), "the source's ML-DSA key would have signed beside the new Ed25519 key"


def test_the_local_half_counts_even_when_the_backup_does_not_carry_that_half(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {CUSTODY_ED: _wrapped(Ed25519PrivateKey.generate(), SOURCE)}, SOURCE)
    (live / "keys").mkdir()
    (live / CUSTODY_ML).write_bytes(b"this install's own ML-DSA key")
    out = merge.merge_side_files(staged)["keys"]
    assert out["kept_local"] == [CUSTODY_ED] and out["restored"] == [], out
    assert not (live / CUSTODY_ED).exists()


@posix_only
def test_a_dangling_link_at_the_other_half_counts_as_a_local_half(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {CUSTODY_ED: _wrapped(Ed25519PrivateKey.generate(), SOURCE)}, SOURCE)
    (live / "keys").mkdir()
    (live / CUSTODY_ML).symlink_to(live / "keys" / "nowhere")
    out = merge.merge_side_files(staged)["keys"]
    assert out["kept_local"] == [CUSTODY_ED], out
    assert not (live / CUSTODY_ED).exists()


def test_a_key_slot_needs_a_name_before_its_suffix():
    assert merge._key_slot("custody_ed25519.pem") == ("custody", "ed25519")
    assert merge._key_slot("annotations_ml_dsa_65.key") == ("annotations", "ml_dsa")
    assert merge._key_slot("_ed25519.pem") is None
    assert merge._key_slot("notes.txt") is None


def test_a_sealed_copy_that_cannot_be_read_back_at_all_is_called_so(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), SOURCE)}, SOURCE)
    monkeypatch.setattr(signing, "seal_ed25519_key", lambda _key, _passphrase: b"not a key file")
    out = merge.merge_side_files(staged)["keys"]
    assert [e["name"] for e in out["not_placed"]] == [EVIDENCE], out
    assert "did not read back as the same key" in out["not_placed"][0]["reason"]
    assert not (live / EVIDENCE).exists()


def test_without_the_library_a_moved_mldsa_key_that_does_not_read_back_is_not_written(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {CUSTODY_ML: signing.seal_mldsa_key(os.urandom(140), b"", SOURCE.encode())}, SOURCE)
    real_seal = signing.seal_mldsa_key
    monkeypatch.setattr(signing, "seal_mldsa_key", lambda _pk, _sk, passphrase: real_seal(os.urandom(140), b"", passphrase))
    out = merge.merge_side_files(staged)["keys"]
    assert [e["name"] for e in out["not_placed"]] == [CUSTODY_ML], out
    assert "did not read back as the same key" in out["not_placed"][0]["reason"]
    assert not (live / CUSTODY_ML).exists()


def test_no_passphrase_or_key_byte_reaches_a_log_an_exception_or_the_report_on_the_failure_paths(tmp_path, monkeypatch, caplog):
    """The passphrase rule on every way the step can end badly: a key no passphrase opens, a read-back that fails, a
    pair half refused, and a write that raises. Nothing the step logs, raises or reports holds a passphrase or key bytes."""
    import logging
    import traceback

    from src.backup.import_reports import render_import_report_markdown
    from src.custody import keyfile

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    _hold(monkeypatch, HERE)
    ed = Ed25519PrivateKey.generate()
    ml = os.urandom(140)
    carried = {
        EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), "a-passphrase-nobody-gave-the-restore"),
        CUSTODY_ED: _wrapped(ed, SOURCE),
        CUSTODY_ML: os.urandom(200),  # refused, so its pair half is refused too
    }
    staged, _live = _stage(tmp_path, carried, SOURCE, BACKUP)
    report = merge.merge_side_files(staged)
    texts = [json.dumps(report, default=str), render_import_report_markdown({"outcome": "ok", "side_files": report}), caplog.text]

    staged2, _live2 = _stage(tmp_path / "second", {"keys/annotations_ml_dsa_65.key": signing.seal_mldsa_key(ml, b"", SOURCE.encode())}, SOURCE)

    def the_disk_refuses(path, data):
        raise OSError(28, "No space left on device", str(path))

    monkeypatch.setattr(keyfile, "create_new", the_disk_refuses)
    with pytest.raises(OSError) as raised:
        merge.merge_side_files(staged2)
    texts.append("".join(traceback.format_exception(raised.value)))

    # nothing held and a PLAINTEXT key carried: the bytes handed to the write are the key itself, the worst case
    plain = Ed25519PrivateKey.generate()
    staged3, _live3 = _stage(tmp_path / "third", {"keys/annotations_ed25519.pem": _plain_pem(plain)}, SOURCE)
    monkeypatch.delenv("OO_KEY_PASSPHRASE")
    with pytest.raises(OSError) as raised:
        merge.merge_side_files(staged3)
    texts.append("".join(traceback.format_exception(raised.value)))
    texts.append(caplog.text)

    secrets = [SOURCE, BACKUP, HERE, "a-passphrase-nobody-gave-the-restore"]
    key_bytes = [_seed(ed), ml, _seed(plain)]
    pem_body = [line for line in _plain_pem(plain).decode().splitlines() if not line.startswith("-----")]
    for text in texts:
        for secret in secrets:
            assert secret not in text
        for kb in key_bytes:
            assert kb.hex() not in text and repr(kb)[2:-1] not in text
        for line in pem_body:
            assert line not in text


# --------------------------------------------------------------------------- #
#  The independent security read (Steward 3) and ruling R613 (2026-11-08).
# --------------------------------------------------------------------------- #
def _pkcs8_encrypted(key: Ed25519PrivateKey, passphrase: str) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(passphrase.encode())
    )


@pytest.mark.parametrize("pqc", [True, False])
def test_a_plaintext_install_never_ends_up_with_a_decrypted_copy_of_a_carried_key(tmp_path, monkeypatch, pqc):
    """R613: every encrypted form a backup can carry (the custody wrap, a password-protected PKCS8 PEM, a wrapped ML-DSA
    key, with and without the post-quantum library) is opened with the backup's passphrase and placed exactly as
    carried. No file anywhere under the data directory, the private copies included, holds the key in the clear."""
    if pqc:
        monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", pqc)
    evidence, custody = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    pk, sk = _FakeMldsa.generate_keypair()
    carried = {
        EVIDENCE: _wrapped(evidence, SOURCE),
        CUSTODY_ED: _pkcs8_encrypted(custody, SOURCE),
        CUSTODY_ML: signing.seal_mldsa_key(pk, sk, SOURCE.encode()),
    }
    staged, live = _stage(tmp_path, carried, SOURCE, BACKUP)
    keys = merge.merge_side_files(staged)["keys"]
    assert sorted(keys["still_encrypted"]) == sorted(carried) and keys["resealed"] == [] and keys["not_placed"] == [], keys
    for name, body in carried.items():
        assert (live / name).read_bytes() == body, name
    clear = [_seed(evidence), _seed(custody), pk + sk, sk, b"-----BEGIN PRIVATE KEY-----"]
    clear += [_seed(evidence).hex().encode(), _seed(custody).hex().encode()]
    files = [f for f in live.rglob("*") if f.is_file()]
    assert files, "the restore placed files"
    for f in files:
        body = f.read_bytes()
        for secret in clear:
            assert secret not in body, f"{f} holds a carried key in the clear"


def test_a_pair_the_disk_refuses_halfway_leaves_neither_half(tmp_path, monkeypatch):
    """The Ed25519 half is placed, the ML-DSA half meets a full disk: the stage fails AND takes its first half back, so
    the next signer does not complete half the backup's identity with a key of its own."""
    from src.custody import keyfile

    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    _hold(monkeypatch, HERE)
    pk, sk = _FakeMldsa.generate_keypair()
    carried = {CUSTODY_ED: _wrapped(Ed25519PrivateKey.generate(), SOURCE), CUSTODY_ML: signing.seal_mldsa_key(pk, sk, SOURCE.encode())}
    staged, live = _stage(tmp_path, carried, SOURCE)
    real = keyfile.create_new
    calls: list[str] = []

    def the_second_create_meets_a_full_disk(path, data):
        calls.append(path.name)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(path, data)

    monkeypatch.setattr(keyfile, "create_new", the_second_create_meets_a_full_disk)
    with pytest.raises(OSError, match="No space left"):
        merge.merge_side_files(staged)
    assert len(calls) == 2, calls
    assert not (live / CUSTODY_ED).exists() and not (live / CUSTODY_ML).exists()
    assert not list((live / "keys").glob(".pending/*"))


def test_a_half_another_caller_replaced_meanwhile_is_not_taken_back(tmp_path, monkeypatch):
    """Only the file this restore made is removed: one that has since become another file (another inode) is theirs."""
    from src.custody import keyfile

    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    _hold(monkeypatch, HERE)
    pk, sk = _FakeMldsa.generate_keypair()
    carried = {CUSTODY_ED: _wrapped(Ed25519PrivateKey.generate(), SOURCE), CUSTODY_ML: signing.seal_mldsa_key(pk, sk, SOURCE.encode())}
    staged, live = _stage(tmp_path, carried, SOURCE)
    real = keyfile.create_new
    theirs = _wrapped(Ed25519PrivateKey.generate(), HERE)
    calls: list[str] = []

    def a_signer_rewraps_the_first_half_then_the_disk_fills(path, data):
        calls.append(path.name)
        if len(calls) == 2:
            fresh = live / "keys" / "rewrap.tmp"
            fresh.write_bytes(theirs)
            os.replace(fresh, live / CUSTODY_ED)  # a new inode under the same name, as replace_in_place makes
            raise OSError(5, "Input/output error")
        return real(path, data)

    monkeypatch.setattr(keyfile, "create_new", a_signer_rewraps_the_first_half_then_the_disk_fills)
    with pytest.raises(OSError, match="Input/output"):
        merge.merge_side_files(staged)
    assert (live / CUSTODY_ED).read_bytes() == theirs
    assert not (live / CUSTODY_ML).exists()


def test_a_manifest_name_cannot_write_markdown_into_the_import_report():
    from src.backup.import_reports import render_import_report_markdown

    hostile = "keys/x`\n## Everything restored fine\n`"
    keys = {
        "not_placed": [{"name": hostile, "reason": "a fixed reason"}],
        "still_encrypted": [hostile],
        "identities": [{"name": hostile, "ed25519_public_key": "ab`\ncd"}],
    }
    md = render_import_report_markdown({"outcome": "ok", "side_files": {"keys": keys}})
    assert "\n## Everything restored fine" not in md, "a name never starts a heading of its own"
    assert md.count("`keys/x\\u0060\\u000a## Everything restored fine\\u000a\\u0060`") == 3, md
    for line in md.splitlines():
        if "Everything restored fine" in line:
            assert line.startswith("- "), line


def test_the_import_report_names_the_signing_identity_taken_from_the_backup(tmp_path, monkeypatch):
    from src.backup.import_reports import render_import_report_markdown

    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    _hold(monkeypatch, HERE)
    ed, ev = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    pk, sk = _FakeMldsa.generate_keypair()
    carried = {
        EVIDENCE: _wrapped(ev, SOURCE),
        CUSTODY_ED: _wrapped(ed, SOURCE),
        CUSTODY_ML: signing.seal_mldsa_key(pk, sk, SOURCE.encode()),
    }
    staged, _live = _stage(tmp_path, carried, SOURCE)
    keys = merge.merge_side_files(staged)["keys"]
    assert sorted((e["name"], e["ed25519_public_key"]) for e in keys["identities"]) == sorted(
        [(CUSTODY_ED, _pub(ed).hex()), (EVIDENCE, _pub(ev).hex())]
    ), keys
    md = render_import_report_markdown({"outcome": "ok", "side_files": {"keys": keys}})
    assert "## Signing identity taken from the backup" in md
    assert f"- `{CUSTODY_ED}`: Ed25519 public key `{_pub(ed).hex()}`" in md
    assert f"- `{EVIDENCE}`: Ed25519 public key `{_pub(ev).hex()}`" in md


def test_a_key_this_install_keeps_is_not_called_an_identity_taken_from_the_backup(tmp_path, monkeypatch):
    from src.backup.import_reports import render_import_report_markdown

    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), SOURCE)}, SOURCE)
    (live / "keys").mkdir()
    (live / EVIDENCE).write_bytes(_wrapped(Ed25519PrivateKey.generate(), HERE))
    keys = merge.merge_side_files(staged)["keys"]
    assert keys["identities"] == [] and keys["kept_local"] == [EVIDENCE], keys
    md = render_import_report_markdown({"outcome": "ok", "side_files": {"keys": keys}})
    assert "Signing identity" not in md
