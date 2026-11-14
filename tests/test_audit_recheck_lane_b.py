"""Audit recheck items for the backup and custody code (lane B, 2026-11-13): P3, P5, P11 (R681), P16.

Each test fails on the code before the fix: the restore preflight read only the archive's size, the folder
manifest was written in place, a bundle signed by someone else's keys answered a bare ``verified: true``, and
restore state files shared one fixed ``<name>.tmp``."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.backup import artifact, folder_backup, merge
from src.custody.log import CustodyAction, CustodyLog
from src.custody.signing import HybridSigner
from tests.os_scope import scope_os

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- P3
def _bomb(size: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("corpus.db", b"\0" * size, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def test_the_restore_preflight_counts_what_the_members_inflate_to_not_the_archive(tmp_path, monkeypatch):
    blob = _bomb(8 * 1024 * 1024)
    assert len(blob) < 64 * 1024, "the archive is small; what it inflates to is not"
    free = 1024 * 1024  # room for the archive, not for what is inside it
    monkeypatch.setattr(folder_backup, "free_bytes", lambda _p: free)
    with pytest.raises(artifact.BackupSpaceError):
        artifact.read_artifact(blob, staging_root=tmp_path)
    assert not list(tmp_path.glob(".restore-*/corpus.db")), "nothing was inflated before the refusal"
    assert not list(tmp_path.glob(".restore-*")), "the staging dir is removed"


class _Lying:
    """A zip member that yields more bytes than it declares."""

    def __init__(self, declared: int, actual: int):
        self.info = zipfile.ZipInfo("corpus.db")
        self.info.file_size = declared
        self._data = io.BytesIO(b"x" * actual)

    def infolist(self):
        return [self.info]

    def open(self, _info):
        return self._data


def test_a_member_that_yields_more_than_it_declares_is_refused_at_its_declared_size(tmp_path):
    z = _Lying(declared=10, actual=5000)
    with pytest.raises(artifact.ArtifactError, match="larger than the size it declares"):
        artifact._safe_extract(z, tmp_path)  # type: ignore[arg-type]
    assert (tmp_path / "corpus.db").stat().st_size <= 10


def test_an_honest_archive_still_extracts_whole(tmp_path):
    blob = _bomb(300_000)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        artifact._safe_extract(zf, tmp_path)
    assert (tmp_path / "corpus.db").stat().st_size == 300_000
    assert (tmp_path / "manifest.json").read_text(encoding="utf-8") == "{}"


def test_each_member_and_each_level_of_its_path_is_charged_beyond_its_bytes(tmp_path, monkeypatch):
    """Empty members nested deep declare almost nothing and still cost a block and an inode per level."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(20):
            zf.writestr(f"d{i}/" + "a/" * 40 + "f", b"")
    monkeypatch.setattr(folder_backup, "free_bytes", lambda _p: 1024 * 1024)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        assert sum(i.file_size for i in zf.infolist()) == 0
        with pytest.raises(artifact.BackupSpaceError):
            artifact._safe_extract(zf, tmp_path)
    assert list(tmp_path.iterdir()) == [], "nothing was written before the refusal"


def test_a_path_deeper_than_any_backup_is_refused(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/" * (artifact._MAX_DEPTH + 1) + "f", b"")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf, pytest.raises(artifact.ArtifactError, match="levels deep"):
        artifact._safe_extract(zf, tmp_path)


def test_more_members_than_any_backup_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact, "_MAX_MEMBERS", 3)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(4):
            zf.writestr(f"m{i}", b"")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf, pytest.raises(artifact.ArtifactError, match="members"):
        artifact._safe_extract(zf, tmp_path)


# --------------------------------------------------------------------------- P5
def test_the_folder_manifest_is_written_through_a_temp_file_and_a_rename(tmp_path, monkeypatch):
    target = tmp_path / folder_backup.MANIFEST_NAME
    target.write_text("previous", encoding="utf-8")

    def boom(_src, _dst):
        raise OSError("disk went away")

    scope_os(monkeypatch, folder_backup, replace=boom)
    with pytest.raises(OSError):
        folder_backup._write_manifest_atomically(target, '{"new": true}')
    assert target.read_text(encoding="utf-8") == "previous", "a failed write leaves the previous manifest whole"
    assert [p.name for p in tmp_path.iterdir()] == [folder_backup.MANIFEST_NAME], "and no temp file behind"


def test_the_backup_pass_writes_its_manifest_through_the_atomic_helper():
    src = (ROOT / "src/backup/folder_backup.py").read_text("utf-8")
    assert "(root / MANIFEST_NAME).write_text(" not in src
    assert "_write_manifest_atomically(root / MANIFEST_NAME," in src


# --------------------------------------------------------------------------- P11 / R681
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def _foreign_bundle(tmp_path: Path) -> dict:
    other = tmp_path / "someone-else"
    other.mkdir()
    signer = HybridSigner(other / "ed.pem", other / "ml.key", use_pqc=False)
    log = CustodyLog(db_path=str(other / "custody.db"), signer=signer, anchoring_mode="local")
    try:
        log.record("article:9", "d" * 64, CustodyAction.INGEST)
        return log.export()
    finally:
        log.close()


def test_a_bundle_signed_by_your_keys_says_so(client):
    client.post("/api/custody/log", json={"item_id": "article:7", "item_hash": "c" * 64, "action": "ingest"})
    bundle = client.get("/api/custody/export").json()
    v = client.post("/api/custody/verify", json={"bundle": bundle}).json()
    assert v["verified"] is True
    assert v["verdict"] == "verified-against-your-keys"
    assert v["signer_is_yours"] is True
    assert [s["entries"] for s in v["signed_by"]] == [1]
    assert v["signed_by"][0]["ed25519_pub"] == bundle["signer"]["ed25519_pub"]


def test_a_bundle_signed_by_other_keys_is_never_called_verified_without_saying_by_whom(client, tmp_path):
    client.post("/api/custody/log", json={"item_id": "article:7", "item_hash": "c" * 64, "action": "ingest"})
    bundle = _foreign_bundle(tmp_path)
    v = client.post("/api/custody/verify", json={"bundle": bundle}).json()
    assert v["verified"] is True, "the signatures are valid: that stays true"
    assert v["verdict"] == "signatures-valid-signer-not-yours"
    assert v["signer_is_yours"] is False
    assert v["signed_by"] == [{"ed25519_pub": bundle["signer"]["ed25519_pub"], "ml_dsa_pub": None, "entries": 1, "yours": False,
                            "earlier_key": False}]
    assert "not who the signer is" in v["verdict_text"]


def test_a_bundle_mixing_signers_lists_each_of_them(client, tmp_path):
    client.post("/api/custody/log", json={"item_id": "article:7", "item_hash": "c" * 64, "action": "ingest"})
    mine = client.get("/api/custody/export").json()
    theirs = _foreign_bundle(tmp_path)
    # Their entry re-chained after mine would break the chain; listing signers needs no valid chain.
    mixed = {**mine, "entries": mine["entries"] + theirs["entries"]}
    v = client.post("/api/custody/verify", json={"bundle": mixed}).json()
    assert v["verified"] is False and v["verdict"] == "not-verified"
    assert sorted(s["yours"] for s in v["signed_by"]) == [False, True]


def test_a_verify_never_creates_signing_keys(client, tmp_path):
    bundle = _foreign_bundle(tmp_path)
    v = client.post("/api/custody/verify", json={"bundle": bundle}).json()
    assert v["verdict"] == "signatures-valid-your-keys-unreadable"
    assert v["signer_is_yours"] is None
    assert not list(tmp_path.rglob("custody_ed25519.pem")), "a verify is a read"


def test_a_key_claimed_by_a_bad_signature_is_never_said_to_be_yours(client):
    """Otherwise any caller could ask whether a key is this installation's by posting it with a junk signature."""
    client.post("/api/custody/log", json={"item_id": "article:7", "item_hash": "c" * 64, "action": "ingest"})
    bundle = client.get("/api/custody/export").json()
    entry = dict(bundle["entries"][0])
    entry["signature"] = {**entry["signature"], "ed25519": {**entry["signature"]["ed25519"], "sig": "00"}}
    v = client.post("/api/custody/verify", json={"bundle": {**bundle, "entries": [entry]}}).json()
    assert v["verified"] is False
    assert [s["yours"] for s in v["signed_by"]] == [None]


def test_an_empty_bundle_is_not_verified(client):
    client.post("/api/custody/log", json={"item_id": "article:7", "item_hash": "c" * 64, "action": "ingest"})
    v = client.post("/api/custody/verify", json={"bundle": {"entries": []}}).json()
    assert v["verified"] is False and v["verdict"] == "not-verified"
    assert any("no entries" in i for i in v["issues"])


def test_a_hybrid_half_this_install_does_not_hold_is_not_yours():
    from src.custody.log import _is_yours
    from src.custody.signing import PublicIdentity

    local = PublicIdentity("ab" * 32, None, None)
    assert _is_yours(("ab" * 32, None), local) is True
    assert _is_yours(("ab" * 32, "cd" * 40), local) is False


def _rotated_bundle(tmp_path: Path, *, endorsed: bool) -> tuple[dict, HybridSigner, HybridSigner]:
    """A log signed by ``old``, then by ``new`` across a key-rotation record (#2005)."""
    old = HybridSigner(tmp_path / "old.pem", tmp_path / "old.key")
    new = HybridSigner(tmp_path / "new.pem", tmp_path / "new.key")
    db = str(tmp_path / "rotated.db")
    with CustodyLog(db_path=db, signer=old, anchoring_mode="local") as log:
        log.record("article:1", "a" * 64, CustodyAction.INGEST)
        log.record("article:2", "b" * 64, CustodyAction.INGEST)
    with CustodyLog(db_path=db, signer=new, anchoring_mode="local") as log:
        if endorsed:
            log.rotate_signing_key(old)
        log.record("article:3", "c" * 64, CustodyAction.INGEST)
        return log.export(), old, new


def test_a_log_this_install_rotated_its_own_key_on_is_still_yours(tmp_path):
    """A rotation gives a bundle several signers by design: the key that endorsed this install's key is this install's."""
    from src.custody.log import VERDICT_YOURS, describe_export

    bundle, old, new = _rotated_bundle(tmp_path, endorsed=True)
    out = describe_export(bundle, local=new.public_identity(), require_signer=True)
    assert out["verified"] is True, out["issues"]
    assert out["verdict"] == VERDICT_YOURS and out["signer_is_yours"] is True
    by_key = {s["ed25519_pub"]: s for s in out["signed_by"]}
    assert set(by_key) == {old.public_identity().ed25519_pub, new.public_identity().ed25519_pub}
    assert by_key[old.public_identity().ed25519_pub]["earlier_key"] is True
    assert by_key[new.public_identity().ed25519_pub]["earlier_key"] is False
    assert all(s["yours"] for s in out["signed_by"])
    assert any("endorsed by the previous key" in n for n in out["notes"]), "the change of key is named"


def test_keys_before_an_unendorsed_rotation_are_not_called_yours(tmp_path):
    """An unendorsed record is also what restoring another install's log and re-creating keys writes."""
    from src.custody.log import VERDICT_NOT_YOURS, describe_export

    bundle, old, new = _rotated_bundle(tmp_path, endorsed=False)
    refused = describe_export(bundle, local=new.public_identity())
    assert refused["verified"] is False, "unendorsed is refused unless asked to accept it"
    out = describe_export(bundle, local=new.public_identity(), accept_unendorsed_rotation=True)
    assert out["verified"] is True and out["verdict"] == VERDICT_NOT_YOURS
    by_key = {s["ed25519_pub"]: s["yours"] for s in out["signed_by"]}
    assert by_key == {old.public_identity().ed25519_pub: False, new.public_identity().ed25519_pub: True}


def test_a_rotated_log_ending_on_another_installs_key_is_not_yours(tmp_path):
    from src.custody.log import VERDICT_NOT_YOURS, describe_export

    bundle, old, _new = _rotated_bundle(tmp_path, endorsed=True)
    out = describe_export(bundle, local=old.public_identity())  # this install holds only the key that handed over
    assert out["verified"] is True and out["verdict"] == VERDICT_NOT_YOURS
    assert {s["earlier_key"] for s in out["signed_by"]} == {False}


def test_an_earlier_key_is_held_to_the_ml_dsa_half_its_endorsement_names(tmp_path):
    from src.custody.log import CustodyEntry, _own_positions

    bundle, old, new = _rotated_bundle(tmp_path, endorsed=True)
    entries = [CustodyEntry.from_dict(d) for d in bundle["entries"]]
    owns = _own_positions(entries, new.public_identity())
    assert [w.ed25519_pub for w in owns] == [old.public_identity().ed25519_pub] * 2 + [new.public_identity().ed25519_pub] * 2
    assert owns[0].ml_dsa_pub == old.public_identity().ml_dsa_pub


def _relinked(entries: list[dict], signers: list[HybridSigner]) -> list[dict]:
    """Re-hash, re-link and re-sign each entry with its signer: what a forger holding those keys can do."""
    from hashlib import sha256

    from src.custody.log import CustodyEntry, _entry_digest
    from src.custody.signing import canonical_bytes

    out = [CustodyEntry.from_dict(d) for d in entries]
    for i, e in enumerate(out):
        if i:
            e.seq = out[i - 1].seq + 1
            e.prev_entry_hash = out[i - 1].entry_hash
        partial = {k: v for k, v in e.signable_core().items() if k != "timestamp"}
        e.timestamp = {**e.timestamp, "digest": sha256(canonical_bytes(partial)).hexdigest()}
        e.entry_hash = _entry_digest(e.signable_core())
        e.signature = signers[i].sign(canonical_bytes(e.signable_core()))
    return [e.to_dict() for e in out]


def test_a_leaked_earlier_key_cannot_vouch_for_what_it_signs_after_handing_over(tmp_path):
    """Second security read, must-fix: the old key P leaked, which is why it was rotated to L. A forger holding P replays
    the genuine endorsed P->L record, forges an unendorsed L->P after it and signs a new entry with P. P's earlier
    stretch was this installation's; what P signs after handing over never is."""
    import copy

    from src.custody.log import (
        ROTATION_ITEM,
        UNENDORSED_ROTATION_NOTE,
        VERDICT_NOT_YOURS,
        _bundle_head,
        describe_export,
    )
    from src.custody.log import CustodyEntry as _E
    from src.custody.signing import canonical_bytes

    bundle, old, new = _rotated_bundle(tmp_path, endorsed=True)
    genuine = next(d for d in bundle["entries"] if d["item_id"] == ROTATION_ITEM)
    back = copy.deepcopy(genuine)
    p_id = old.public_identity()
    back["metadata"].update(
        previous_ed25519_pub=new.public_identity().ed25519_pub,
        ed25519_pub=p_id.ed25519_pub,
        ml_dsa_variant=p_id.ml_dsa_variant,
        ml_dsa_pub=p_id.ml_dsa_pub,
        endorsement=None,
        note=UNENDORSED_ROTATION_NOTE,
    )
    item = copy.deepcopy(next(d for d in bundle["entries"] if d["item_id"] == "article:3"))
    item["item_id"], item["item_hash"] = "article:9", "f" * 64
    forged_tail = _relinked([genuine, back, item], [new, old, old])
    forged_tail[0] = genuine  # the replayed record stays byte-identical: it is the user's own
    forged = {
        **bundle,
        "item_id": "article:9",
        "entries": forged_tail,
        "signer": p_id.to_dict(),
    }
    forged["head"] = _bundle_head("article:9", [_E.from_dict(d) for d in forged_tail])
    forged["head_signature"] = old.sign(canonical_bytes(forged["head"]))
    out = describe_export(forged, local=new.public_identity(), accept_unendorsed_rotation=True)
    assert out["verified"] is True, out["issues"]  # the chain itself is well formed: the verdict is what must not lie
    assert out["verdict"] == VERDICT_NOT_YOURS and out["signer_is_yours"] is False
    by_key = {s["ed25519_pub"]: s["yours"] for s in out["signed_by"]}
    assert by_key[p_id.ed25519_pub] is False


def test_a_bundle_whose_entries_are_not_a_list_is_an_answer_not_a_crash(client):
    for junk in (5, True, "x", {"a": 1}):
        r = client.post("/api/custody/verify", json={"bundle": {"entries": junk}})
        assert r.status_code == 200 and r.json()["verdict"] == "not-verified"


# --------------------------------------------------------------------------- P16
def test_restore_state_files_are_replaced_through_a_unique_temp_that_never_outlives_a_failure(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    merge._replace_file_bytes(target, b"one")
    assert target.read_bytes() == b"one"

    def boom(_src, _dst):
        raise OSError("no")

    scope_os(monkeypatch, merge, replace=boom)
    with pytest.raises(OSError):
        merge._replace_file_bytes(target, b"two")
    assert target.read_bytes() == b"one"
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_merge_has_no_fixed_tmp_name_left():
    src = (ROOT / "src/backup/merge.py").read_text("utf-8")
    assert 'name + ".tmp")' not in src
    assert 'with_suffix(".tmp")' not in src


def test_a_signer_key_that_is_not_a_string_is_an_answer_not_a_crash(client):
    """A posted bundle is untrusted JSON: a list or a number where a key belongs must read as not verified, never a 500."""
    client.post("/api/custody/log", json={"item_id": "article:7", "item_hash": "c" * 64, "action": "ingest"})
    client.post("/api/custody/log", json={"item_id": "article:8", "item_hash": "d" * 64, "action": "ingest"})
    bundle = client.get("/api/custody/export").json()
    first, second = (dict(e) for e in bundle["entries"][:2])
    first["signature"] = {**first["signature"], "ed25519": {**first["signature"]["ed25519"], "pub": ["ab"]}}
    second["signature"] = {**second["signature"], "ed25519": {**second["signature"]["ed25519"], "pub": 7}}
    r = client.post("/api/custody/verify", json={"bundle": {**bundle, "entries": [first, second]}})
    assert r.status_code == 200
    assert r.json()["verified"] is False
