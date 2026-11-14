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
    assert report["verified"] and report["notes"] and "accepted on the record's word" in report["notes"][1]
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
    old_pub, new_pub = old.public_identity().ed25519_pub, bundle["signer"]["ed25519_pub"]
    # The line of keys is printed in full: an endorsement proves something only to a reader who knows one of them.
    assert report["notes"] == [
        f"the chain starts on key {old_pub}; compare any key you already know with this line of keys",
        f"seq 4: the signing key changed from {old_pub} to {new_pub}, endorsed by the previous key",
    ]
    assert verify_export(bundle, require_signer=True) == (True, [])
    # A one-item export carries every key-rotation record, so its key change can be followed to the head's key.
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
        assert r["verified"] is True and "record's word" in r["notes"][1]
    p = tmp_path / "b.json"
    p.write_text(json.dumps(bundle), encoding="utf-8")
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


# --- found by the delta read of the fixes ----------------------------------------------------------------------------


@pytest.mark.parametrize("endorsed", [True, False])
def test_an_item_untouched_since_a_rotation_verifies(tmp_path, endorsed):
    """Its entries all carry the old key; the bundle carries the later rotations, so they lead to the signer key."""
    db = str(tmp_path / "c.db")
    old, new = _signer(tmp_path, "old"), _signer(tmp_path, "new")
    with CustodyLog(db_path=db, signer=old) as log:
        log.record("a:1", "a" * 64, CustodyAction.INGEST)
    with CustodyLog(db_path=db, signer=new) as log:
        if endorsed:
            log.rotate_signing_key(old)
        log.record("a:2", "b" * 64, CustodyAction.INGEST)
        bundle = log.export(item_id="a:1")
    assert [e["item_id"] for e in bundle["entries"]] == ["a:1", ROTATION_ITEM]
    report = verify_export_report(bundle, require_signer=True, accept_unendorsed_rotation=not endorsed)
    assert report["verified"], report["issues"]


def test_a_whole_log_cannot_open_with_a_rotation_record(tmp_path):
    """A real log never does; one that did could name the real signer's key as 'previous' and hand on to any key."""
    db = str(tmp_path / "c.db")
    real, atk = _signer(tmp_path, "real"), _signer(tmp_path, "atk")
    with CustodyLog(db_path=db, signer=atk) as log:
        _record(log, 1)
        rot = log._insert_rotation(log._last(), previous_signer=None)
    from src.custody.log import CustodyEntry, _key_lineage

    e = CustodyEntry.from_dict(rot.to_dict())
    e.metadata = {**e.metadata, "previous_ed25519_pub": real.public_identity().ed25519_pub}
    e.seq = 1
    problem, _ = _key_lineage([e], atk.public_identity().ed25519_pub, True)
    assert problem and "opens the log" in problem


def test_an_export_after_a_key_change_records_the_rotation_first(tmp_path):
    """Restore onto a new machine, then export before anything new is logged: the head's new key is recorded first."""
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "old")) as log:
        _record(log, 3)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        whole, item = log.export(), log.export(item_id="article:0")
        assert [e.action for e in log.all_entries()].count("key_rotation") == 1  # once, not once per export
    for bundle in (whole, item):
        assert not verify_export(bundle)[0]  # unendorsed: still refused unless accepted on the record's word
        report = verify_export_report(bundle, require_signer=True, accept_unendorsed_rotation=True)
        assert report["verified"], report["issues"]


def test_a_long_lived_log_follows_its_key_file_instead_of_rotating_back_and_forth(tmp_path):
    """A collection pass keeps one log open; the key folder is re-created meanwhile and other logs sign with the new key."""
    db = str(tmp_path / "c.db")
    keys = tmp_path / "keys"
    keys.mkdir()

    def signer() -> HybridSigner:
        return HybridSigner(ed25519_path=keys / "k.pem", mldsa_path=keys / "k.key")

    batch = CustodyLog(db_path=db, signer=signer())
    try:
        _record(batch, 2)
        for p in keys.iterdir():  # the key folder is lost and re-created
            p.unlink()
        with CustodyLog(db_path=db, signer=signer()) as other:
            _record(other, 1, 2)
        _record(batch, 1, 3)  # the batch reloads the new key rather than signing with the one the folder lost
        with CustodyLog(db_path=db, signer=signer()) as other:
            _record(other, 1, 4)
        _record(batch, 1, 5)
        entries = batch.all_entries()
        assert [e.action for e in entries].count("key_rotation") == 1
        assert batch.verify_report()["verified"]
    finally:
        batch.close()


def test_the_in_app_check_follows_the_key_and_names_its_rotations(tmp_path):
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "old")) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        _record(log, 1, 2)
        report = log.verify_report()
        assert report["verified"] and any("accepted on the record's word" in n for n in report["notes"])
    db2 = str(tmp_path / "legacy.db")
    with CustodyLog(db_path=db2, signer=_signer(tmp_path, "old")) as log:
        _record(log, 2)
    with CustodyLog(db_path=db2, signer=_signer(tmp_path, "new")) as log:
        # What a log written before this version holds: the re-created key signed on with no record in between.
        log._insert(log._last(), "article:0", "a" * 64, "ingest", "pipeline", {}, None)
        report = log.verify_report()
        # The operator's own store: a key change with no record (all a log written before these records can show) is
        # named, not refused -- the log could never be given the record. An exported bundle is still refused.
        assert report["verified"], report["issues"]
        assert any("with no key-rotation record" in n and "before 0.5.1" in n for n in report["notes"])
        ok, issues = verify_export(log.export(), accept_unendorsed_rotation=True)
        assert not ok and "with no key-rotation record" in issues[0]


def test_the_cli_refuses_an_unknown_option(tmp_path):
    bundle = tmp_path / "b.json"
    bundle.write_text("{}", encoding="utf-8")
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_custody.py"), str(bundle), "--pinn"],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 2 and "unknown option" in out.stderr


def _forge(bundle: dict, at: int, edit, record_signer: HybridSigner, tail_signer: HybridSigner) -> dict:
    """Edit the metadata of entry ``at``, then re-hash, re-sign and re-link it and every later entry, and re-sign the
    head: a forger holding ``record_signer``/``tail_signer`` does all of that, so only the key lineage can refuse it."""
    from hashlib import sha256

    from src.custody.log import CustodyEntry, _bundle_head, _entry_digest

    b = copy.deepcopy(bundle)
    entries = [CustodyEntry.from_dict(d) for d in b["entries"]]
    edit(entries[at].metadata)
    for i in range(at, len(entries)):
        e = entries[i]
        if i > at:
            e.prev_entry_hash = entries[i - 1].entry_hash
        partial = {k: v for k, v in e.signable_core().items() if k != "timestamp"}
        e.timestamp = {**e.timestamp, "digest": sha256(canonical_bytes(partial)).hexdigest()}
        e.entry_hash = _entry_digest(e.signable_core())
        e.signature = (record_signer if i == at else tail_signer).sign(canonical_bytes(e.signable_core()))
    b["entries"] = [e.to_dict() for e in entries]
    b["signer"] = tail_signer.public_identity().to_dict()
    b["head"] = _bundle_head(b.get("item_id"), entries)
    b["head_signature"] = tail_signer.sign(canonical_bytes(b["head"]))
    return b


def test_a_re_signed_forged_rotation_is_refused_by_the_key_lineage(tmp_path):
    """Each check in the key lineage pinned by a forgery the hashes and signatures cannot catch (re-signed throughout)."""
    from src.custody.log import rotation_payload

    db = str(tmp_path / "c.db")
    old, new = _signer(tmp_path, "old"), _signer(tmp_path, "new")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=new) as log:
        log.rotate_signing_key(old)
        _record(log, 1, 2)
        bundle = log.export()
    assert verify_export(bundle, require_signer=True) == (True, [])
    rot = bundle["entries"][2]
    attacker = _signer(tmp_path, "attacker")
    ident = new.public_identity().to_dict()

    # (1) The record names a previous key of the forger's (which endorses it), not the key that signed the entries.
    def own_previous(md: dict) -> None:
        a = attacker.public_identity().ed25519_pub
        md["previous_ed25519_pub"] = a
        md["endorsement"] = attacker.sign(canonical_bytes(rotation_payload(a, ident, rot["prev_entry_hash"])))

    forged = _forge(bundle, 2, own_previous, new, new)
    ok, issues = verify_export(forged, accept_unendorsed_rotation=True)
    assert not ok and "names a previous key that did not sign the entries before it" in issues[0]

    # (2) The record introduces one key and is signed by another.
    def other_new_key(md: dict) -> None:
        md["ed25519_pub"] = attacker.public_identity().ed25519_pub

    ok, issues = verify_export(_forge(bundle, 2, other_new_key, new, new), accept_unendorsed_rotation=True)
    assert not ok and "is not signed by the key it introduces" in issues[0]

    # (3) The endorsement is the previous key's, over something else (here: another new key).
    def stale_endorsement(md: dict) -> None:
        other = {**ident, "ed25519_pub": attacker.public_identity().ed25519_pub}
        md["endorsement"] = old.sign(canonical_bytes(rotation_payload(md["previous_ed25519_pub"], other,
                                                                      rot["prev_entry_hash"])))

    ok, issues = verify_export(_forge(bundle, 2, stale_endorsement, new, new), accept_unendorsed_rotation=True)
    assert not ok and "has an invalid endorsement" in issues[0]

    # (4) The endorsement is made by a key other than the previous one.
    def foreign_endorsement(md: dict) -> None:
        md["endorsement"] = attacker.sign(canonical_bytes(rotation_payload(md["previous_ed25519_pub"], ident,
                                                                           rot["prev_entry_hash"])))

    ok, issues = verify_export(_forge(bundle, 2, foreign_endorsement, new, new), accept_unendorsed_rotation=True)
    assert not ok and "carries an endorsement not made by the previous key" in issues[0]

    # The helper itself forges nothing when nothing is edited: the genuine record re-signed still verifies.
    assert verify_export(_forge(bundle, 2, lambda md: None, new, new))[0]


def test_a_key_folder_moved_aside_for_a_moment_writes_no_rotation(tmp_path):
    """A reload only loads: a key file that is briefly gone is not replaced by a new key under a long-lived log."""
    import shutil

    db = str(tmp_path / "c.db")
    keys = tmp_path / "keys"
    keys.mkdir()
    log = CustodyLog(db_path=db, signer=HybridSigner(ed25519_path=keys / "k.pem", mldsa_path=keys / "k.key"))
    try:
        _record(log, 1)
        shutil.move(str(keys), str(tmp_path / "aside"))
        _record(log, 1, 1)  # still signs with the key it holds
        shutil.move(str(tmp_path / "aside"), str(keys))
        _record(log, 1, 2)
        assert [e.action for e in log.all_entries()].count("key_rotation") == 0
        # No orphan key was created while the folder was away: it holds what it held before.
        assert not (tmp_path / "aside").exists() and {p.name for p in keys.iterdir()} <= {"k.pem", "k.key"}
        assert len({e.signature["ed25519"]["pub"] for e in log.all_entries()}) == 1
    finally:
        log.close()


def test_export_answers_503_when_the_key_cannot_be_read(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api import custody as api
    from src.api.main import app
    from src.custody.signing import SigningError

    def refuse():
        raise SigningError("unreadable")

    monkeypatch.setattr(api, "_log", refuse)
    r = TestClient(app).post("/api/custody/export")  # a POST since R694
    assert r.status_code == 503 and "could not be read" in r.json()["detail"]


@pytest.mark.skipif(not __import__("src.custody.signing", fromlist=["x"]).PQC_AVAILABLE,
                    reason="pqcrypto/ML-DSA not installed")
def test_the_last_stretch_is_pinned_to_its_rotation_and_the_signer_must_agree(tmp_path):
    db = str(tmp_path / "c.db")
    old = _signer(tmp_path, "old")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        log.rotate_signing_key(old)
    # Post-quantum signing turned off after the rotation: the honest log still verifies pinned.
    off = HybridSigner(ed25519_path=tmp_path / "new.pem", mldsa_path=tmp_path / "new.key", use_pqc=False)
    with CustodyLog(db_path=db, signer=off) as log:
        _record(log, 1, 2)
        assert verify_export(log.export(), require_signer=True) == (True, [])
    # The ML-DSA key alone replaced, with no record: the printed signer is not the identity the stretch is held to.
    other_ml = HybridSigner(ed25519_path=tmp_path / "new.pem", mldsa_path=tmp_path / "other.key")
    with CustodyLog(db_path=db, signer=other_ml) as log:
        ok, issues = verify_export(log.export(), require_signer=True)
    assert not ok and "names an ML-DSA key other than the one the key-rotation record at seq 3 introduced" in issues[0]
