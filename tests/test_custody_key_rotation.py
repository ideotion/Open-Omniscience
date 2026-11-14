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


# --- found by the two security reads of the first version ------------------------------------------------------------


@pytest.mark.parametrize("endorsed", [True, False])
def test_an_item_first_recorded_after_a_rotation_verifies(tmp_path, endorsed):
    """Its bundle starts with the rotation record, whose previous key signed nothing in the bundle."""
    db = str(tmp_path / "c.db")
    old, new = _signer(tmp_path, "old"), _signer(tmp_path, "new")
    with CustodyLog(db_path=db, signer=old) as log:
        log.record("a:1", "a" * 64, CustodyAction.INGEST)
    with CustodyLog(db_path=db, signer=new) as log:
        if endorsed:
            log.rotate_signing_key(old)
        log.record("a:2", "b" * 64, CustodyAction.INGEST)
        bundle = log.export(item_id="a:2")
    assert [e["item_id"] for e in bundle["entries"]] == [ROTATION_ITEM, "a:2"]
    report = verify_export_report(bundle, require_signer=True, accept_unendorsed_rotation=not endorsed)
    assert report["verified"], report["issues"]
    if not endorsed:
        assert not verify_export(bundle)[0]  # still refused unless accepted on the record's word


def test_rotation_records_cannot_be_written_from_outside(tmp_path):
    """One posted through record() or the log route would name keys of the caller's choosing and break every later
    export for good, the log being append-only."""
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        log.record("a:1", "a" * 64, CustodyAction.INGEST)
        with pytest.raises(ValueError):
            log.record(ROTATION_ITEM, "a" * 64, CustodyAction.KEY_ROTATION, metadata={"previous_ed25519_pub": "x"})
        with pytest.raises(ValueError):
            log.record(ROTATION_ITEM, "a" * 64, CustodyAction.INGEST)
        with pytest.raises(ValueError):
            log.record("a:2", "a" * 64, "key_rotation")
        assert len(log.all_entries()) == 1


def test_the_log_route_refuses_rotation_records(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        for body in ({"item_id": ROTATION_ITEM, "item_hash": "a" * 64, "action": "key_rotation"},
                     {"item_id": "a:1", "item_hash": "a" * 64, "action": "key_rotation"},
                     {"item_id": ROTATION_ITEM, "item_hash": "a" * 64, "action": "ingest"}):
            r = c.post("/api/custody/log", json=body)
            assert r.status_code == 400, r.text
        r = c.post("/api/custody/log", json={"item_id": "a:1", "item_hash": "a" * 64, "action": "nonsense"})
        assert r.status_code == 400 and "key_rotation" not in r.json()["detail"]


def test_entries_that_end_on_another_key_than_the_signer_are_refused(tmp_path):
    """A whole bundle signed by key A, given a head and a signer of key B: no entry carries B."""
    db = str(tmp_path / "c.db")
    a, b = _signer(tmp_path, "a"), _signer(tmp_path, "b")
    with CustodyLog(db_path=db, signer=a) as log:
        _record(log, 3)
        bundle = log.export()
    forged = copy.deepcopy(bundle)
    forged["signer"] = b.public_identity().to_dict()
    forged["head_signature"] = b.sign(canonical_bytes(forged["head"]))
    ok, issues = verify_export(forged, accept_unendorsed_rotation=True)
    assert not ok and issues == ["the entries end on a different key from the bundle's signer key"]


def test_the_scope_line_says_when_the_key_changed(tmp_path):
    from src.custody.log import ITEM_SCOPE_NOTE, WHOLE_LOG_SCOPE, scope_note

    db = str(tmp_path / "c.db")
    old = _signer(tmp_path, "old")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
        plain = log.export()
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        log.rotate_signing_key(old)
        _record(log, 2, 2)
        rotated, rotated_item = log.export(), log.export(item_id="article:0")
    assert scope_note(plain, verify_export_report(plain)["notes"]) == WHOLE_LOG_SCOPE
    for b, unrotated in ((rotated, WHOLE_LOG_SCOPE), (rotated_item, ITEM_SCOPE_NOTE)):
        report = verify_export_report(b)
        assert report["verified"] and report["notes"]
        note = scope_note(b, report["notes"])
        assert note != unrotated and "rotation" in note


def test_exporting_the_rotation_item_lists_each_record_once(tmp_path):
    db = str(tmp_path / "c.db")
    old = _signer(tmp_path, "old")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        log.rotate_signing_key(old)
        _record(log, 1, 2)
        bundle = log.export(item_id=ROTATION_ITEM)
    assert [e["seq"] for e in bundle["entries"]] == [3]


def test_segment_pins_follow_each_rotation():
    from src.custody.log import CustodyEntry, _segment_pins
    from src.custody.signing import PublicIdentity

    def entry(seq, action="ingest", md=None):
        return CustodyEntry.from_dict({"seq": seq, "item_id": ROTATION_ITEM if action == "key_rotation" else "a:1",
                                       "item_hash": "a", "action": action, "actor": None, "metadata": md or {},
                                       "prev_entry_hash": "p", "entry_hash": "h",
                                       "signature": {"ed25519": {"pub": "k"}}, "timestamp": {}})

    signer = PublicIdentity(ed25519_pub="K3", ml_dsa_variant="v", ml_dsa_pub="M3")
    rot2 = {"ed25519_pub": "K2", "ml_dsa_variant": "v", "ml_dsa_pub": "M2"}
    rot3 = {"ed25519_pub": "K3", "ml_dsa_variant": None, "ml_dsa_pub": None}
    pins = _segment_pins([entry(1), entry(2, "key_rotation", rot2), entry(3), entry(4, "key_rotation", rot3), entry(5)],
                         signer)
    assert pins[1] is None  # before the first rotation: its Ed25519 key only, held by the lineage
    assert pins[2] == pins[3] == PublicIdentity(ed25519_pub="K2", ml_dsa_variant="v", ml_dsa_pub="M2")
    assert pins[4] is signer and pins[5] is signer


@pytest.mark.skipif(not __import__("src.custody.signing", fromlist=["x"]).PQC_AVAILABLE,
                    reason="pqcrypto/ML-DSA not installed")
def test_a_pinned_bundle_refuses_a_middle_entry_with_another_ml_dsa_half(tmp_path):
    """Same Ed25519 key, another ML-DSA key: the lineage cannot see it, the stretch's pin can."""
    db = str(tmp_path / "c.db")
    old, new, newer = _signer(tmp_path, "old"), _signer(tmp_path, "new"), _signer(tmp_path, "newer")
    new_other_ml = HybridSigner(ed25519_path=tmp_path / "new.pem", mldsa_path=tmp_path / "other.key")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=new) as log:
        log.rotate_signing_key(old)
    with CustodyLog(db_path=db, signer=new_other_ml) as log:
        _record(log, 1, 2)
    with CustodyLog(db_path=db, signer=newer) as log:
        log.rotate_signing_key(new)
        _record(log, 1, 3)
        bundle = log.export()
    assert verify_export(bundle)[0]
    ok, issues = verify_export(bundle, require_signer=True)
    assert not ok and any("ml-dsa public key does not match" in i for i in issues)
