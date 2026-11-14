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


@pqc
@pytest.mark.parametrize("change", ["re-created", "turned off", "turned on"])
def test_a_change_of_the_ml_dsa_half_alone_writes_a_record_and_verifies_pinned(tmp_path, change):
    db = str(tmp_path / "c.db")
    before = _signer(tmp_path, "k", use_pqc=change != "turned on")
    after = {"re-created": _signer(tmp_path, "k", ml="k2"), "turned off": _signer(tmp_path, "k", use_pqc=False),
             "turned on": _signer(tmp_path, "k")}[change]
    with CustodyLog(db_path=db, signer=before) as log:
        _record(log, 3)
    with CustodyLog(db_path=db, signer=after) as log:
        _record(log, 2, 3)
        bundle = log.export()
        item = log.export(item_id="article:0")
        in_app = log.verify_report()
    rot = _rotations(bundle)
    assert len(rot) == 1 and rot[0]["seq"] == 4
    md = rot[0]["metadata"]
    assert md["previous_ed25519_pub"] == md["ed25519_pub"] and md["endorsement"] is None
    assert md["note"] == ML_DSA_ONLY_ROTATION_NOTE
    assert md["previous_ml_dsa_pub"] == before.public_identity().ml_dsa_pub
    assert md["ml_dsa_pub"] == after.public_identity().ml_dsa_pub
    # Accepted without --accept-unendorsed-rotation: the Ed25519 key that signed the entries before signs the record.
    report = verify_export_report(bundle, require_signer=True)
    assert report["verified"], report["issues"]
    assert any(ML_DSA_ONLY_ROTATION_NOTE in n for n in report["notes"])
    assert verify_export(item, require_signer=True) == (True, [])
    assert in_app["verified"] and any(ML_DSA_ONLY_ROTATION_NOTE in n for n in in_app["notes"])


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
