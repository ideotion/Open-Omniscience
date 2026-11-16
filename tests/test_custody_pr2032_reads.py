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
5. With post-quantum signing off the verdict lost the ML-DSA key the folder still holds: a bundle exported before the
   change read "not yours", a foreign ML-DSA key under the installation's Ed25519 key read "yours", and an unreadable
   settings store held the verdict to the Ed25519 key alone.
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


def _held(folder: Path, ml: str = "k") -> str | None:
    """The ML-DSA key a folder holds, read as the verify route reads it (``_held_ml_dsa_pub``)."""
    return HybridSigner(ed25519_path=folder / "k.pem", mldsa_path=folder / f"{ml}.key", use_pqc=True,
                        create=False).public_identity().ml_dsa_pub


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
    # The old ML-DSA key file stays in the folder; the installation's identity as it signs now has no ML-DSA half.
    now = _signer(tmp_path, "k", use_pqc=False).public_identity()
    assert now.ml_dsa_pub is None
    # The route passes the ML-DSA key the folder still holds: the hybrid entries before the change are held to it.
    d = describe_export(bundle, local=now, held_ml_dsa_pub=_held(tmp_path))
    assert d["verified"] and d["verdict"] == VERDICT_YOURS, d
    assert all(s["yours"] for s in d["signed_by"])  # the hybrid entries before the change too


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
        local = _signer(tmp_path, "k", use_pqc=flips[-1] == "on").public_identity()
        d = describe_export(b, local=local, held_ml_dsa_pub=None if local.ml_dsa_pub else _held(tmp_path))
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


@pqc
def test_a_replayed_post_quantum_off_record_lends_nothing_once_post_quantum_is_back_on(tmp_path):
    """Third-round read: the install went on, off, on. A forger holding K alone takes a copy of the log from the off
    period and signs new entries with the Ed25519 key alone after the genuine drop record."""
    import shutil

    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        _record(log, 2)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k", use_pqc=False)) as log:
        _record(log, 2, 2)
    shutil.copy(db, tmp_path / "snapshot.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        _record(log, 1, 4)
    with CustodyLog(db_path=str(tmp_path / "snapshot.db"), signer=_signer(tmp_path, "k", "nope", use_pqc=False)) as log:
        log.record("article:FORGED", "f" * 64, CustodyAction.INGEST, actor="forger")
        bundles = [log.export(), log.export(item_id="article:FORGED")]
    now = _signer(tmp_path, "k").public_identity()  # post-quantum is on again here
    for b in bundles:
        d = describe_export(b, local=now)
        assert d["verdict"] != VERDICT_YOURS, d


def test_the_verify_route_holds_the_verdict_to_the_identity_as_it_signs_now(tmp_path, monkeypatch):
    from src.api import custody as api

    monkeypatch.setattr(api, "load_settings", lambda: type("S", (), {"pqc_enabled": False})())
    seen = {}

    class _Spy:
        def __init__(self, *, use_pqc, create):
            seen.update(use_pqc=use_pqc, create=create)

        def public_identity(self):
            return None

    monkeypatch.setattr(api, "HybridSigner", _Spy)
    api._local_identity()
    assert seen == {"use_pqc": False, "create": False}


@pqc
def test_pin_with_an_accepted_change_and_no_rotation_record_never_crashes(tmp_path):
    """Third-round read B: a re-headed bundle with no rotation record, pinned and accepted, raised StopIteration."""
    import json
    import subprocess
    import sys

    with CustodyLog(db_path=str(tmp_path / "c.db"), signer=_signer(tmp_path, "k")) as log:
        _record(log, 3)
        genuine = log.export()
    forged = _rehead(genuine, _signer(tmp_path, "k", "none", use_pqc=False))
    r = verify_export_report(forged, require_signer=True, accept_unendorsed_rotation=True)
    assert isinstance(r["verified"], bool)
    path = tmp_path / "b.json"
    path.write_text(json.dumps(forged), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, str(root / "scripts/verify_custody.py"), str(path), "--pin",
                          "--accept-unendorsed-rotation"], capture_output=True, text=True)
    assert out.returncode in (1, 4) and "Traceback" not in out.stderr, out.stderr


def _yours(d: dict) -> list[tuple[int, bool]]:
    return [(s["entries"], bool(s["yours"])) for s in d["signed_by"]]


@pqc
@pytest.mark.parametrize("item", [None, "article:0"])
def test_a_bundle_exported_while_post_quantum_was_on_stays_yours_once_it_is_off(tmp_path, item):
    """Fourth-round Opus read: with post-quantum signing off the verdict lost the ML-DSA key the folder still holds, so
    a bundle exported before the change (no record in it) read "signer not yours". It is held to that key."""
    with CustodyLog(db_path=str(tmp_path / "c.db"), signer=_signer(tmp_path, "k")) as log:
        _record(log, 3)
        bundle = log.export(item_id=item)
    off = _signer(tmp_path, "k", use_pqc=False).public_identity()
    held = _held(tmp_path)
    d = describe_export(bundle, local=off, held_ml_dsa_pub=held)
    assert d["verified"] and d["verdict"] == VERDICT_YOURS, d
    # Without the key it holds, the verdict cannot say so (the honest answer when the folder has none).
    assert describe_export(bundle, local=off)["verdict"] == VERDICT_NOT_YOURS


@pqc
@pytest.mark.parametrize("item", [None, "article:0"])
def test_with_post_quantum_off_a_foreign_ml_dsa_key_under_the_installations_ed25519_key_is_never_yours(tmp_path, item):
    """Fourth-round reads A and B: someone holding the Ed25519 key alone signed with an ML-DSA key of their own, then
    turned post-quantum off (a record they can endorse). With the installation's post-quantum signing off, their
    ML-DSA key was listed as the installation's. It is checked against the key the folder holds."""
    victim, thief = tmp_path / "v", tmp_path / "t"
    victim.mkdir()
    thief.mkdir()
    with CustodyLog(db_path=str(victim / "c.db"), signer=_signer(victim, "k")) as log:
        _record(log, 2)
    (thief / "k.pem").write_bytes((victim / "k.pem").read_bytes())  # the Ed25519 key alone
    with CustodyLog(db_path=str(thief / "c.db"), signer=_signer(thief, "k", "x")) as log:
        _record(log, 3)
        log.signer = _signer(thief, "k", "x", use_pqc=False)
        _record(log, 1, start=3)
        forged = log.export(item_id=item)
    off = _signer(victim, "k", use_pqc=False).public_identity()
    held = _held(victim)
    for h in (held, None):
        d = describe_export(forged, local=off, held_ml_dsa_pub=h)
        assert not any(s["yours"] for s in d["signed_by"] if s["ml_dsa_pub"]), d


def test_the_verify_route_holds_an_unreadable_settings_store_to_every_key(tmp_path, monkeypatch):
    """Fourth-round read B: an unreadable settings store answers with defaults (post-quantum off) rather than raising,
    so the verdict was held to the Ed25519 key alone and credited a forgery signed with it."""
    from src.api import custody as api

    monkeypatch.setattr(api, "load_settings",
                        lambda: type("S", (), {"pqc_enabled": False, "store_unreadable": True})())
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)  # the library-missing case is its own test below
    seen = {}

    class _Spy:
        def __init__(self, *, use_pqc, create):
            seen.update(use_pqc=use_pqc, create=create)

        def public_identity(self):
            return None

    monkeypatch.setattr(api, "HybridSigner", _Spy)
    api._local_identity()
    assert seen == {"use_pqc": True, "create": False}
    monkeypatch.setattr(api, "load_settings", lambda: (_ for _ in ()).throw(RuntimeError("unreadable")))
    api._local_identity()
    assert seen["use_pqc"] is True


def test_the_verify_route_reads_no_identity_with_post_quantum_on_and_its_library_missing(monkeypatch):
    """Fifth-round read B: with post-quantum on and the library missing, the identity fell back to the Ed25519 key
    alone, so a forgery signed with that key alone read "verified against your keys". It is unread instead."""
    from src.api import custody as api

    monkeypatch.setattr(api, "load_settings", lambda: type("S", (), {"pqc_enabled": True, "store_unreadable": False})())
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    monkeypatch.setattr(api, "HybridSigner", lambda **kw: pytest.fail("no key is read"))
    assert api._local_identity() is None


@pytest.mark.parametrize("own_ml, asked", [(None, True), ("ab" * 8, False)])
def test_the_verify_route_passes_the_held_ml_dsa_key_only_while_signing_without_post_quantum(monkeypatch, own_ml, asked):
    """Fifth-round Opus read: the route reads the ML-DSA key in the folder only when the identity as it signs now has
    none, and hands it to the verdict."""
    from src.api import custody as api
    from src.custody.signing import PublicIdentity

    local = PublicIdentity(ed25519_pub="cd" * 32, ml_dsa_variant="ml_dsa_65" if own_ml else None, ml_dsa_pub=own_ml)
    monkeypatch.setattr(api, "_local_identity", lambda: local)
    calls = []
    monkeypatch.setattr(api, "_held_ml_dsa_pub", lambda: calls.append(1) or "ef" * 8)
    seen = {}

    def _describe(bundle, **kw):
        seen.update(kw)
        return {"verified": False, "notes": [], "accepted_unendorsed": False}

    monkeypatch.setattr(api, "describe_export", _describe)
    api.verify_bundle(api.VerifyBundleRequest(bundle={}))
    assert bool(calls) is asked
    assert seen["held_ml_dsa_pub"] == ("ef" * 8 if asked else None) and seen["local"] is local
