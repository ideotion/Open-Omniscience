"""The post-quantum (ML-DSA) half of the custody signing identity is followed like the Ed25519 half (rows 42-44).

Row 42: a change of the ML-DSA half alone (post-quantum signing turned on or off, its key re-created) writes a
key-rotation record, so a pinned check follows it instead of refusing an honest log. Row 43: a record names the previous
identity's ML-DSA half, its endorsement binds it, and the entry before the record must carry it. Row 44: under ``--pin``,
a signer that names an ML-DSA key must sign its head with both halves, and in a stretch a full record introduced an
Ed25519-only entry signature is refused.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.custody import signing
from src.custody.log import (
    ML_DSA_ONLY_ROTATION_NOTE,
    ML_DSA_UNENDORSED_ROTATION_NOTE,
    ROTATION_ITEM,
    CustodyAction,
    CustodyLog,
    verify_export,
    verify_export_report,
)
from src.custody.signing import HybridSigner, canonical_bytes

pqc = pytest.mark.skipif(not signing.PQC_AVAILABLE, reason="pqcrypto/ML-DSA not installed")


def _signer(tmp_path: Path, name: str, ml: str | None = None, use_pqc: bool = True) -> HybridSigner:
    return HybridSigner(ed25519_path=tmp_path / f"{name}.pem", mldsa_path=tmp_path / f"{ml or name}.key",
                        use_pqc=use_pqc)


def _record(log: CustodyLog, n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        log.record(f"article:{i % 2}", "a" * 64, CustodyAction.INGEST, actor="pipeline")


def _rotations(bundle: dict) -> list[dict]:
    return [e for e in bundle["entries"] if e["item_id"] == ROTATION_ITEM]


def _ed_only(sig: dict) -> dict:
    """A hybrid signature with its post-quantum half stripped off: its Ed25519 half still verifies."""
    return {"algorithm": "ed25519", "ed25519": sig["ed25519"]}


def _resign(entry: dict, signer: HybridSigner) -> None:
    entry["signature"] = signer.sign(canonical_bytes({k: v for k, v in entry.items()
                                                      if k not in ("entry_hash", "signature")}))


# --- row 42: a change of the ML-DSA half alone is recorded ----------------------------------------------------------


def _change(tmp_path: Path, change: str) -> tuple[HybridSigner, HybridSigner, dict, dict, dict]:
    db = str(tmp_path / "c.db")
    before = _signer(tmp_path, "k", use_pqc=change != "turned on")
    after = {"re-created": _signer(tmp_path, "k", ml="k2"), "turned off": _signer(tmp_path, "k", use_pqc=False),
             "turned on": _signer(tmp_path, "k")}[change]
    with CustodyLog(db_path=db, signer=before) as log:
        _record(log, 3)
    with CustodyLog(db_path=db, signer=after) as log:
        _record(log, 2, 3)
        bundle, item, in_app = log.export(), log.export(item_id="article:0"), log.verify_report()
    return before, after, bundle, item, in_app


@pqc
@pytest.mark.parametrize("change", ["re-created", "turned off", "turned on"])
def test_a_change_of_the_ml_dsa_half_alone_writes_a_record(tmp_path, change):
    before, after, bundle, item, in_app = _change(tmp_path, change)
    rot = _rotations(bundle)
    assert len(rot) == 1 and rot[0]["seq"] == 4
    md = rot[0]["metadata"]
    assert md["previous_ed25519_pub"] == md["ed25519_pub"]
    assert md["previous_ml_dsa_pub"] == before.public_identity().ml_dsa_pub
    assert md["ml_dsa_pub"] == after.public_identity().ml_dsa_pub
    # The operator's own store accepts every one of them, named.
    assert in_app["verified"], in_app["issues"]
    assert any("seq 4: the signing identity changed" in n or "seq 4: the signing key changed" in n
               for n in in_app["notes"])


@pqc
@pytest.mark.parametrize("change", ["turned off", "turned on"])
def test_turning_post_quantum_signing_on_or_off_verifies_pinned_without_a_flag(tmp_path, change):
    """On: nothing is weakened, the Ed25519 key's word suffices. Off: the ML-DSA key is still in the folder, so the
    previous identity, both halves, endorses the record."""
    before, _after, bundle, item, _ = _change(tmp_path, change)
    md = _rotations(bundle)[0]["metadata"]
    if change == "turned on":
        assert md["endorsement"] is None and md["note"] == ML_DSA_ONLY_ROTATION_NOTE
    else:
        assert md["endorsement"]["ml_dsa"]["pub"] == before.public_identity().ml_dsa_pub
    report = verify_export_report(bundle, require_signer=True)
    assert report["verified"], report["issues"]
    assert verify_export(item, require_signer=True)[0]


@pqc
def test_a_re_created_ml_dsa_key_is_an_unendorsed_rotation(tmp_path):
    _before, _after, bundle, item, _ = _change(tmp_path, "re-created")
    md = _rotations(bundle)[0]["metadata"]
    assert md["endorsement"] is None and md["note"] == ML_DSA_UNENDORSED_ROTATION_NOTE
    for b in (bundle, item):
        ok, issues = verify_export(b, require_signer=True)
        assert not ok and issues[0].startswith("the post-quantum (ML-DSA) key changes at seq 4 with no endorsement")
        report = verify_export_report(b, require_signer=True, accept_unendorsed_rotation=True)
        assert report["verified"] and any(ML_DSA_UNENDORSED_ROTATION_NOTE in n for n in report["notes"])


@pqc
@pytest.mark.parametrize("evil_ml", [None, "evil"])
def test_a_holder_of_the_ed25519_key_alone_cannot_drop_the_post_quantum_half_unseen(tmp_path, evil_ml):
    """Security read A, finding 1: a copy of an honest hybrid log, opened with its Ed25519 key and no ML-DSA key (or
    one of the forger's own), and signed on: refused, under the pin too, unless accepted by name."""
    import shutil

    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        _record(log, 3)
    shutil.copy(db, tmp_path / "copy.db")
    forger = (HybridSigner(ed25519_path=tmp_path / "k.pem", mldsa_path=tmp_path / "absent.key", use_pqc=False)
              if evil_ml is None else _signer(tmp_path, "k", ml=evil_ml))
    with CustodyLog(db_path=str(tmp_path / "copy.db"), signer=forger) as log:
        _record(log, 1, 3)
        bundle = log.export()
    assert not (tmp_path / "absent.key").exists()  # nothing created
    for pin in (False, True):
        ok, issues = verify_export(bundle, require_signer=pin)
        assert not ok and "with no endorsement by the previous ML-DSA key" in issues[0]


@pqc
def test_rotate_signing_key_endorses_a_change_of_the_ml_dsa_half(tmp_path):
    db = str(tmp_path / "c.db")
    old = _signer(tmp_path, "k")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", ml="k2")) as log:
        rec = log.rotate_signing_key(old)
        bundle = log.export()
    assert rec.metadata["endorsement"]["ml_dsa"]["pub"] == old.public_identity().ml_dsa_pub
    report = verify_export_report(bundle, require_signer=True)
    assert report["verified"], report["issues"]
    assert any("endorsed by the previous key" in n for n in report["notes"])


def test_rotating_to_the_same_whole_identity_is_still_refused(tmp_path):
    db = str(tmp_path / "c.db")
    old = _signer(tmp_path, "k")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 1)
        with pytest.raises(ValueError, match="same as the previous one"):
            log.rotate_signing_key(old)
        # Nothing changed, so nothing is recorded on the next entry or export either.
        _record(log, 1, 1)
        assert not _rotations(log.export())


def test_a_record_written_before_rows_42_43_must_still_change_the_ed25519_key(tmp_path):
    """A record with no previous ML-DSA field (written before 0.5.1) naming one Ed25519 key twice is refused."""
    from tests.test_custody_key_rotation import _forge

    db = str(tmp_path / "c.db")
    old, new = _signer(tmp_path, "old"), _signer(tmp_path, "new")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=new) as log:
        log.rotate_signing_key(old)
        bundle = log.export()

    def old_style_same_key(md: dict) -> None:
        md.pop("previous_ml_dsa_variant"), md.pop("previous_ml_dsa_pub")
        md["previous_ed25519_pub"] = md["ed25519_pub"]

    ok, issues = verify_export(_forge(bundle, 2, old_style_same_key, new, new), accept_unendorsed_rotation=True)
    assert not ok and "does not name two different keys" in issues[0]


# --- row 43: the previous ML-DSA half is bound ----------------------------------------------------------------------


@pqc
def test_an_endorsement_with_another_or_no_ml_dsa_half_is_refused(tmp_path):
    from tests.test_custody_key_rotation import _forge

    db = str(tmp_path / "c.db")
    old, new = _signer(tmp_path, "old"), _signer(tmp_path, "new")
    with CustodyLog(db_path=db, signer=old) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=new) as log:
        log.rotate_signing_key(old)
        _record(log, 1, 2)
        bundle = log.export()
    assert verify_export(bundle, require_signer=True) == (True, [])
    # The holder of the previous Ed25519 key alone (a quantum forger), with an ML-DSA key of their own.
    half = _signer(tmp_path, "old", ml="attacker")

    def foreign_ml_half(md: dict) -> None:
        from src.custody.log import rotation_payload

        ident = {k: md[k] for k in ("ed25519_pub", "ml_dsa_variant", "ml_dsa_pub")}
        payload = rotation_payload(md["previous_ed25519_pub"], ident, bundle["entries"][2]["prev_entry_hash"],
                                   (md["previous_ml_dsa_variant"], md["previous_ml_dsa_pub"]))
        md["endorsement"] = half.sign(canonical_bytes(payload))

    ok, issues = verify_export(_forge(bundle, 2, foreign_ml_half, new, new))
    assert not ok and "carries an endorsement not made by the previous key" in issues[0]

    def stripped(md: dict) -> None:
        md["endorsement"] = _ed_only(md["endorsement"])

    ok, issues = verify_export(_forge(bundle, 2, stripped, new, new))
    assert not ok and "carries an endorsement not made by the previous key" in issues[0]


@pqc
def test_a_record_naming_another_previous_ml_dsa_key_than_the_entry_before_is_refused(tmp_path):
    from tests.test_custody_key_rotation import _forge

    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "old")) as log:
        _record(log, 2)
    new = _signer(tmp_path, "new")
    with CustodyLog(db_path=db, signer=new) as log:  # unendorsed: the old key is gone
        _record(log, 1, 2)
        bundle = log.export()
    assert verify_export(bundle, require_signer=True, accept_unendorsed_rotation=True) == (True, [])

    def other_previous(md: dict) -> None:
        md["previous_ml_dsa_pub"] = _signer(tmp_path, "x").public_identity().ml_dsa_pub

    ok, issues = verify_export(_forge(bundle, 2, other_previous, new, new), accept_unendorsed_rotation=True)
    assert not ok and "names a previous ML-DSA key the entry before it was not signed with" in issues[0]


# --- row 44: a stripped post-quantum half under --pin ---------------------------------------------------------------


@pqc
def test_a_head_stripped_to_ed25519_is_refused_under_the_pin(tmp_path):
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        _record(log, 2)
        bundle = log.export()
    forged = copy.deepcopy(bundle)
    forged["head_signature"] = _ed_only(forged["head_signature"])
    ok, issues = verify_export(forged, require_signer=True)
    assert not ok and "its post-quantum half was removed" in issues[0]


@pqc
def test_an_entry_stripped_to_ed25519_after_a_full_record_is_refused_under_the_pin(tmp_path):
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", use_pqc=False)) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:  # post-quantum signing turned on: recorded
        _record(log, 2, 2)
        bundle = log.export()
    assert verify_export(bundle, require_signer=True) == (True, [])
    forged = copy.deepcopy(bundle)
    forged["entries"][4]["signature"] = _ed_only(forged["entries"][4]["signature"])
    assert verify_export(forged)[0]  # the Ed25519 half still verifies on its own
    ok, issues = verify_export(forged, require_signer=True)
    assert not ok and issues[0].startswith("signature invalid at seq 5") and "post-quantum half was removed" in issues[0]
    # The entries before the record were signed with Ed25519 only, honestly: they stay accepted.
    assert all(e["signature"]["algorithm"] == "ed25519" for e in bundle["entries"][:2])


@pqc
def test_a_stretch_after_a_full_record_naming_no_ml_dsa_key_is_held_to_none(tmp_path):
    """Post-quantum signing turned off is recorded, so a hybrid signature after it is not the identity in use."""
    db = str(tmp_path / "c.db")
    on = _signer(tmp_path, "k")
    with CustodyLog(db_path=db, signer=on) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", use_pqc=False)) as log:
        _record(log, 2, 2)
        bundle = log.export()
    assert verify_export(bundle, require_signer=True) == (True, [])
    forged = copy.deepcopy(bundle)
    _resign(forged["entries"][3], on)
    ok, issues = verify_export(forged, require_signer=True)
    assert not ok and any("ml-dsa public key does not match" in i for i in issues)


@pqc
def test_a_middle_stretch_whose_full_record_names_no_ml_dsa_key_is_pinned_too(tmp_path):
    """Before rows 42-43 a stretch whose record named no ML-DSA key was left unpinned unless it was the last one."""
    db = str(tmp_path / "c.db")
    on = _signer(tmp_path, "k")
    with CustodyLog(db_path=db, signer=on) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", use_pqc=False)) as log:
        _record(log, 2, 2)  # record at seq 3, entries 4-5 Ed25519 only
    with CustodyLog(db_path=db, signer=on) as log:
        _record(log, 1, 4)  # record at seq 6, entry 7 hybrid again
        bundle = log.export()
    assert len(_rotations(bundle)) == 2
    assert verify_export(bundle, require_signer=True) == (True, [])
    forged = copy.deepcopy(bundle)
    _resign(forged["entries"][3], on)  # seq 4, in the middle stretch, given an ML-DSA half
    assert verify_export(forged)[0]
    ok, issues = verify_export(forged, require_signer=True)
    assert not ok and any("seq 4" in i and "ml-dsa public key does not match" in i for i in issues)


def test_an_old_style_record_after_a_full_one_is_refused(tmp_path):
    """Security read A, finding 2: a record naming no previous ML-DSA key after one that does would put its stretch
    back under the old rules."""
    from tests.test_custody_key_rotation import _forge

    db = str(tmp_path / "c.db")
    a, b, c = _signer(tmp_path, "a"), _signer(tmp_path, "b"), _signer(tmp_path, "c")
    with CustodyLog(db_path=db, signer=a) as log:
        _record(log, 1)
    with CustodyLog(db_path=db, signer=b) as log:
        log.rotate_signing_key(a)
        _record(log, 1, 1)
    with CustodyLog(db_path=db, signer=c) as log:
        log.rotate_signing_key(b)
        bundle = log.export()
    assert verify_export(bundle)[0]

    def old_style(md: dict) -> None:
        md.pop("previous_ml_dsa_variant"), md.pop("previous_ml_dsa_pub")

    assert [e["seq"] for e in _rotations(bundle)] == [2, 4]
    ok, issues = verify_export(_forge(bundle, 3, old_style, c, c), accept_unendorsed_rotation=True)
    assert not ok and "names no previous ML-DSA key, though the record at seq 2 before it does" in issues[0]


@pqc
def test_each_full_record_leaves_the_identity_the_one_before_introduced(tmp_path):
    """Checked in a one-item bundle too, which holds every record but not the entries before them."""
    from tests.test_custody_key_rotation import _forge

    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        _record(log, 2)
    off = _signer(tmp_path, "k", use_pqc=False)
    with CustodyLog(db_path=db, signer=off) as log:
        _record(log, 1, 2)  # record at seq 3, endorsed
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        log.record("other:1", "b" * 64, CustodyAction.INGEST)  # record at seq 5
        item = log.export(item_id="article:0")
    assert [e["seq"] for e in _rotations(item)] == [3, 5]
    assert verify_export(item, require_signer=True)[0]

    def claims_another_previous(md: dict) -> None:
        md["previous_ml_dsa_pub"] = _signer(tmp_path, "x").public_identity().ml_dsa_pub

    at = [e["seq"] for e in item["entries"]].index(5)
    ok, issues = verify_export(_forge(item, at, claims_another_previous, off, _signer(tmp_path, "k")),
                               accept_unendorsed_rotation=True)
    assert not ok and "other than the one the record at seq 3 introduced" in issues[0]


@pqc
def test_a_machine_without_the_post_quantum_library_signs_nothing_and_writes_no_record(tmp_path, monkeypatch):
    """Security reads A (finding 3) and B: nobody changed the key, so no permanent record says so, and nothing is signed
    with the Ed25519 half alone; the entry stays owed and the routes answer 503 in plain words."""
    from fastapi.testclient import TestClient

    from src.api import custody as api
    from src.api.main import app
    from src.custody.signing import PostQuantumUnavailable

    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        _record(log, 2)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    missing = _signer(tmp_path, "k")
    assert missing.pqc_unavailable_but_requested and not missing.is_hybrid
    with CustodyLog(db_path=db, signer=missing) as log:
        with pytest.raises(PostQuantumUnavailable, match="install the 'pqc' extra"):
            _record(log, 1, 2)
        with pytest.raises(PostQuantumUnavailable):
            log.export()
        assert [e.seq for e in log.all_entries()] == [1, 2]
    monkeypatch.setattr(api, "_log", lambda: CustodyLog(db_path=db, signer=_signer(tmp_path, "k")))
    client = TestClient(app)
    r = client.get("/api/custody/export", headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 503 and "post-quantum library is not installed" in r.json()["detail"]
    r = client.post("/api/custody/log", json={"item_id": "a:1", "item_hash": "a" * 64, "action": "ingest"},
                    headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 503 and "post-quantum library is not installed" in r.json()["detail"]


def test_an_endorsing_signer_never_creates_a_post_quantum_key(tmp_path):
    """Security read B: the previous identity is only ever LOADED to endorse a change, never created."""
    s = HybridSigner(ed25519_path=tmp_path / "k.pem", mldsa_path=tmp_path / "k.key", use_pqc=False)
    assert s.with_existing_post_quantum_key() is None
    assert not (tmp_path / "k.key").exists()
