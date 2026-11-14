"""A custody log verifies across a change of signing key, and a forged tail stays refused.

When the key that signs now is not the one that signed the tail (keys re-created after a restore, a lost key folder),
the log writes a KEY-ROTATION record before the new key signs anything: unendorsed, it says in plain words that the
previous key was not available; written by ``rotate_signing_key`` with the old key at hand, the old key endorses the
new one and this place in the chain. The checker follows an endorsed rotation, refuses an unendorsed one unless asked
to accept it on the record's word, and refuses any key change with no record.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from src.custody.log import (
    ROTATION_ITEM,
    UNENDORSED_ROTATION_NOTE,
    CustodyAction,
    CustodyLog,
    verify_export,
    verify_export_report,
)
from src.custody.signing import HybridSigner, canonical_bytes

ROOT = Path(__file__).resolve().parents[1]


def _signer(tmp_path: Path, name: str) -> HybridSigner:
    return HybridSigner(ed25519_path=tmp_path / f"{name}.pem", mldsa_path=tmp_path / f"{name}.key")


def _record(log: CustodyLog, n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        log.record(f"article:{i % 2}", "a" * 64, CustodyAction.INGEST, actor="pipeline")


def test_a_re_created_key_writes_an_unendorsed_rotation_record_first(tmp_path):
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "old")) as log:
        _record(log, 3)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:  # the key folder was lost
        _record(log, 2, 3)
        entries = log.all_entries()
        bundle = log.export()
    rot = entries[3]
    assert rot.action == "key_rotation" and rot.item_id == ROTATION_ITEM
    assert rot.metadata["endorsement"] is None and rot.metadata["note"] == UNENDORSED_ROTATION_NOTE
    assert [e.seq for e in entries] == [1, 2, 3, 4, 5, 6]
    # The chain itself is whole: the record is an ordinary link.
    assert log_verify_ok(db, tmp_path)
    ok, issues = verify_export(bundle)
    assert not ok and issues[0].startswith("the signing key changes at seq 4 with no endorsement")
    report = verify_export_report(bundle, accept_unendorsed_rotation=True)
    assert report["verified"] and report["notes"] and "accepted on the record's word" in report["notes"][0]
    assert verify_export_report(bundle, require_signer=True, accept_unendorsed_rotation=True)["verified"]


def log_verify_ok(db: str, tmp_path: Path) -> bool:
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        return log.verify()[0]


def test_an_endorsed_rotation_verifies_with_and_without_a_pin(tmp_path):
    db = str(tmp_path / "c.db")
    old = _signer(tmp_path, "old")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 3)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        log.rotate_signing_key(old)
        _record(log, 2, 3)
        bundle = log.export()
        item = log.export(item_id="article:0")
    report = verify_export_report(bundle)
    assert report["verified"], report["issues"]
    assert report["notes"] == ["seq 4: the signing key changed, endorsed by the previous key"]
    assert verify_export(bundle, require_signer=True) == (True, [])
    # A one-item export carries the rotation records up to its last entry, so its key change can be followed.
    assert any(e["item_id"] == ROTATION_ITEM for e in item["entries"])
    assert verify_export(item, require_signer=True) == (True, [])


def test_rotate_refuses_a_key_that_did_not_sign_the_tail_and_the_same_key(tmp_path):
    db = str(tmp_path / "c.db")
    old = _signer(tmp_path, "old")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 1)
        with pytest.raises(ValueError, match="same"):
            log.rotate_signing_key(old)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log, pytest.raises(ValueError, match="not signed"):
        log.rotate_signing_key(_signer(tmp_path, "stranger"))


def test_a_forged_tail_with_a_forged_endorsed_rotation_is_refused(tmp_path):
    """The attacker cuts a genuine log, writes a rotation record 'endorsed' with a key of their own and signs the tail."""
    db_real = str(tmp_path / "real.db")
    with CustodyLog(db_path=db_real, signer=_signer(tmp_path, "old")) as log:
        _record(log, 4)
    # The forger copies entries 1-2 into a fresh store, then rotates from a key they hold.
    from src.custody.log import CustodyEntry

    db_f = str(tmp_path / "forged.db")
    with CustodyLog(db_path=db_real, signer=_signer(tmp_path, "old")) as real:
        kept = real.all_entries()[:2]
    attacker_old = _signer(tmp_path, "atk-old")
    with CustodyLog(db_path=db_f, signer=_signer(tmp_path, "atk-new")) as forged:
        for e in kept:
            forged.conn.execute(
                "INSERT INTO custody_entries (seq, item_id, item_hash, action, actor, metadata_json, prev_entry_hash,"
                " entry_hash, signature_json, timestamp_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (e.seq, e.item_id, e.item_hash, e.action, e.actor, __import__("json").dumps(e.metadata, sort_keys=True),
                 e.prev_entry_hash, e.entry_hash, __import__("json").dumps(e.signature),
                 __import__("json").dumps(e.timestamp)),
            )
        forged.conn.commit()
        with pytest.raises(ValueError):  # the API itself will not endorse from a key that did not sign the tail
            forged.rotate_signing_key(attacker_old)
        # So the forger writes the record by hand: previous = the REAL key, endorsement by their own key.
        prev = forged._last()
        assert isinstance(prev, CustodyEntry)
        rot = forged._insert_rotation(prev, previous_signer=attacker_old)
        _record(forged, 1, 2)
        bundle = forged.export()
    assert rot.metadata["previous_ed25519_pub"] != attacker_old.public_identity().ed25519_pub
    ok, issues = verify_export(bundle, accept_unendorsed_rotation=True)
    assert not ok and "endorsement not made by the previous key" in issues[0]


@pytest.mark.parametrize("edit", [
    lambda md: md.__setitem__("ed25519_pub", "00" * 32),             # names a key that did not sign it
    lambda md: md.__setitem__("previous_ed25519_pub", "11" * 32),    # names a previous key that signed nothing
    lambda md: md["endorsement"]["ed25519"].__setitem__("sig", "00" * 64),  # endorsement does not verify
])
def test_a_tampered_rotation_record_is_refused(tmp_path, edit):
    db = str(tmp_path / "c.db")
    old = _signer(tmp_path, "old")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        log.rotate_signing_key(old)
        _record(log, 1, 2)
        bundle = log.export()
    b = copy.deepcopy(bundle)
    edit(b["entries"][2]["metadata"])
    ok, issues = verify_export(b, accept_unendorsed_rotation=True)
    assert not ok and issues


def test_an_endorsement_cannot_be_lifted_to_another_place_in_the_chain(tmp_path):
    """The endorsement covers prev_entry_hash; a record moved elsewhere fails, even re-hashed and re-signed."""
    from hashlib import sha256

    from src.custody.log import CustodyEntry, _entry_digest

    db = str(tmp_path / "c.db")
    old, new = _signer(tmp_path, "old"), _signer(tmp_path, "new")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=new) as log:
        rot = log.rotate_signing_key(old)
    e = CustodyEntry.from_dict(rot.to_dict())
    e.prev_entry_hash = "f" * 64  # as if spliced after another entry
    partial = {k: v for k, v in e.signable_core().items() if k != "timestamp"}
    e.timestamp = {**e.timestamp, "digest": sha256(canonical_bytes(partial)).hexdigest()}
    e.entry_hash = _entry_digest(e.signable_core())
    e.signature = new.sign(canonical_bytes(e.signable_core()))
    from src.custody.log import _key_lineage

    with CustodyLog(db_path=db, signer=new) as log:
        first_two = log.all_entries()[:2]
    problem, _ = _key_lineage([*first_two, e], new.public_identity().ed25519_pub, False)
    assert problem and "invalid endorsement" in problem


def test_the_route_and_the_cli_name_the_rotation(tmp_path):
    import json

    from fastapi.testclient import TestClient

    from src.api.main import app

    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "old")) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        _record(log, 1, 2)
        bundle = log.export()
    with TestClient(app) as c:
        r = c.post("/api/custody/verify", json={"bundle": bundle}).json()
        assert r["verified"] is False and "no endorsement" in r["issues"][0] and r["notes"] == []
        r = c.post("/api/custody/verify", json={"bundle": bundle, "accept_unendorsed_rotation": True}).json()
        assert r["verified"] is True and "record's word" in r["notes"][0]
    p = tmp_path / "b.json"
    p.write_text(json.dumps(bundle))
    cli = [sys.executable, str(ROOT / "scripts/verify_custody.py"), str(p)]
    assert subprocess.run(cli, capture_output=True, text=True).returncode == 1
    out = subprocess.run([*cli, "--accept-unendorsed-rotation"], capture_output=True, text=True)
    assert out.returncode == 0 and "key rotation   : seq 3" in out.stdout
