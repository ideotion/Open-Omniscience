"""Findings of the security and code reads of PR #2032 (custody rows 42-46, R714, R716, R717), each pinned.

1. Someone holding the Ed25519 key alone re-signed a genuine hybrid bundle's head under a signer that names no ML-DSA
   key (cutting entries off its end too): it verified with exit 0. The signer must now name the ML-DSA key the last
   entries show.
2. A log built with the Ed25519 key alone read as "verified against your keys" on an installation whose identity has an
   ML-DSA half.
3. Turning post-quantum signing on (a record that only adds the ML-DSA half) made the operator's own bundle read as
   "signer not yours".
4. With post-quantum signing wanted and its library missing, a re-created Ed25519 key wrote an unendorsed rotation and
   signed with the Ed25519 half alone (R717: nothing is signed).
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.custody import signing
from src.custody.log import (
    VERDICT_NOT_YOURS,
    VERDICT_YOURS,
    CustodyAction,
    CustodyLog,
    _bundle_head,
    describe_export,
    verify_export_report,
)
from src.custody.signing import HybridSigner, PostQuantumUnavailable, canonical_bytes

pqc = pytest.mark.skipif(not signing.PQC_AVAILABLE, reason="pqcrypto/ML-DSA not installed")


@pytest.fixture(autouse=True)
def _data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))


def _signer(tmp_path: Path, ed: str, ml: str | None = None, use_pqc: bool = True) -> HybridSigner:
    return HybridSigner(ed25519_path=tmp_path / f"{ed}.pem", mldsa_path=tmp_path / f"{ml or ed}.key", use_pqc=use_pqc)


def _record(log: CustodyLog, n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        log.record(f"article:{i % 2}", "a" * 64, CustodyAction.INGEST, actor="pipeline")


def _rehead(bundle: dict, signer: HybridSigner, keep: int | None = None) -> dict:
    """The bundle's head re-signed by ``signer`` under a signer field naming only its own identity."""
    b = copy.deepcopy(bundle)
    from src.custody.log import CustodyEntry

    if keep is not None:
        b["entries"] = b["entries"][:keep]
    entries = [CustodyEntry.from_dict(d) for d in b["entries"]]
    b["head"] = _bundle_head(b.get("item_id"), entries, bundle_format=b["head"].get("bundle_format", 1))
    b["entry_count"] = len(entries)
    b["head_signature"] = signer.sign(canonical_bytes(b["head"]))
    ident = signer.public_identity()
    b["signer"] = {"ed25519_pub": ident.ed25519_pub, "ml_dsa_variant": ident.ml_dsa_variant, "ml_dsa_pub": ident.ml_dsa_pub}
    return b


@pqc
@pytest.mark.parametrize("item", [None, "article:0"])
@pytest.mark.parametrize("keep", [None, 3])
def test_a_hybrid_bundle_re_headed_with_the_ed25519_key_alone_is_refused(tmp_path, item, keep):
    with CustodyLog(db_path=str(tmp_path / "c.db"), signer=_signer(tmp_path, "k")) as log:
        _record(log, 6)
        genuine = log.export(item_id=item) if item else log.export()
    assert verify_export_report(genuine)["verified"]
    forged = _rehead(genuine, _signer(tmp_path, "k", "none", use_pqc=False), keep=keep if not item else None)
    for pin in (False, True):
        r = verify_export_report(forged, require_signer=pin)
        assert not r["verified"] and "the bundle's signer does not name" in r["issues"][0], r
    # Before any 0.5.1 record it is what turning post-quantum off before 0.5.1 leaves in a one-item bundle: by name only.
    r = verify_export_report(forged, accept_unendorsed_rotation=True)
    assert r["verified"] and r["accepted_unendorsed"]


@pqc
def test_a_log_made_with_the_ed25519_key_alone_is_not_called_yours(tmp_path):
    with CustodyLog(db_path=str(tmp_path / "real.db"), signer=_signer(tmp_path, "k")) as log:
        _record(log, 1)
    local = _signer(tmp_path, "k").public_identity()
    with CustodyLog(db_path=str(tmp_path / "forged.db"), signer=_signer(tmp_path, "k", "none", use_pqc=False)) as log:
        _record(log, 3)
        bundles = [log.export(), log.export(item_id="article:0")]
    for b in bundles:
        d = describe_export(b, local=local)
        assert d["verified"] and d["verdict"] == VERDICT_NOT_YOURS and not any(s["yours"] for s in d["signed_by"])


@pqc
def test_turning_post_quantum_on_keeps_the_operators_bundle_theirs(tmp_path):
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", use_pqc=False)) as log:
        _record(log, 3)
    on = _signer(tmp_path, "k")
    with CustodyLog(db_path=db, signer=on) as log:
        _record(log, 2, 3)
        bundles = [log.export(), log.export(item_id="article:0")]
    for b in bundles:
        d = describe_export(b, local=on.public_identity())
        assert d["verdict"] == VERDICT_YOURS, d
        assert all(s["yours"] and not s["earlier_key"] for s in d["signed_by"])  # one key throughout, never "earlier"


@pqc
def test_turning_post_quantum_off_with_the_library_keeps_the_operators_bundle_theirs(tmp_path):
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        _record(log, 3)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", use_pqc=False)) as log:
        _record(log, 2, 3)
        bundle = log.export()
    # The old ML-DSA key file stays in the folder, so the installation's identity still names it.
    d = describe_export(bundle, local=_signer(tmp_path, "k").public_identity())
    assert d["verified"] and d["verdict"] == VERDICT_YOURS, d


@pqc
def test_a_re_created_ed25519_key_without_the_library_signs_nothing_and_writes_no_record(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        _record(log, 2)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k2")) as log:
        with pytest.raises(PostQuantumUnavailable):
            _record(log, 1, 2)
        with pytest.raises(PostQuantumUnavailable):
            log.export()
        assert [e.seq for e in log.all_entries()] == [1, 2]


@pqc
def test_the_item_verify_route_names_an_accepted_key_change(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api import custody as api
    from src.api.main import app

    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "old")) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:
        _record(log, 1, 2)
    monkeypatch.setattr(api, "_read_log", lambda: CustodyLog(db_path=db, create=False))
    r = TestClient(app).get("/api/custody/article:0/verify").json()
    assert r["verified"] and r["accepted_unendorsed"] and r["accepted_unendorsed_note"]


# --- the delta reads of the fixes above ------------------------------------------------------------------------------


@pqc
def test_a_log_with_the_installations_ed25519_key_and_another_ml_dsa_key_is_not_yours(tmp_path):
    """The attacker holds K only, makes its own ML-DSA key M', signs with (K, M'), then turns post-quantum off: the drop
    record is endorsed by (K, M'), never by this installation's (K, M)."""
    local = _signer(tmp_path, "k").public_identity()
    db = str(tmp_path / "forged.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", "other")) as log:
        _record(log, 3)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", "other", use_pqc=False)) as log:
        _record(log, 3, 3)
        bundles = [log.export(), log.export(item_id="article:0")]
    for b in bundles:
        for pin in (False, True):
            d = describe_export(b, local=local, require_signer=pin)
            assert d["verdict"] == VERDICT_NOT_YOURS and not any(s["yours"] for s in d["signed_by"]), d


@pqc
@pytest.mark.parametrize("flips", [("on", "off"), ("on", "off", "on")])
def test_the_operators_one_item_bundle_stays_theirs_across_post_quantum_changes(tmp_path, flips):
    db = str(tmp_path / "c.db")
    n = 0
    for flip in flips:
        with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", use_pqc=flip == "on")) as log:
            _record(log, 2, n)
            n += 2
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", use_pqc=flips[-1] == "on")) as log:
        bundles = [log.export(), log.export(item_id="article:0")]
    for b in bundles:
        d = describe_export(b, local=_signer(tmp_path, "k").public_identity())
        assert d["verified"] and d["verdict"] == VERDICT_YOURS, d


@pqc
def test_a_bundle_that_does_not_verify_calls_no_ed25519_only_entry_yours(tmp_path):
    with CustodyLog(db_path=str(tmp_path / "c.db"), signer=_signer(tmp_path, "k")) as log:
        _record(log, 2)
        b = log.export()
    with CustodyLog(db_path=str(tmp_path / "f.db"), signer=_signer(tmp_path, "k", "none", use_pqc=False)) as log:
        _record(log, 2)
        forged = log.export()
    b["entries"] = forged["entries"] + b["entries"][1:]
    d = describe_export(b, local=_signer(tmp_path, "k").public_identity())
    assert not d["verified"]
    assert not any(s["yours"] for s in d["signed_by"] if s["ml_dsa_pub"] is None)
