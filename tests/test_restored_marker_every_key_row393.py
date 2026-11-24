"""Row 393 (R816): the R801 restored-key marker covers every signing key a restore can place.

R801 marked only the evidence key a restore placed, so a custody or annotation key carried in a backup from another
computer read as this installation's own. Now the restore writes the marker beside the Ed25519 key of each pair it places,
before placing it, under the lock the signer makes its own key under; a marker that cannot be written places no pair
(fail closed); a pair that is not placed takes its marker back; a signer that makes a NEW key drops the marker; and the
custody chain checks (GET /api/custody/{item}/verify and POST /api/custody/verify) never call a restored key this
installation's. Erase and the keys-folder ownership check treat the markers as the app's own names.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.backup import merge
from src.custody import signing
from src.reporting import evidence as ev
from src.safety import data_scope
from tests.backup_helper import staged_artifact
from tests.test_restore_key_rewrap import _FakeMldsa

SUFFIX = ev.RESTORED_KEY_MARKER_SUFFIX


@pytest.fixture(autouse=True)
def _plaintext_install(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "live"))
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr(connect, "_passphrase", None)
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    (tmp_path / "live").mkdir()


def _pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _pair(who: str) -> dict[str, bytes]:
    pk, sk = _FakeMldsa.generate_keypair()
    return {f"keys/{who}_ed25519.pem": _pem(Ed25519PrivateKey.generate()), f"keys/{who}_ml_dsa_65.key": pk + sk}


def _restore(tmp_path: Path, members: dict[str, bytes]) -> dict:
    staging = tmp_path / "staging"
    for n, body in members.items():
        (staging / n).parent.mkdir(parents=True, exist_ok=True)
        (staging / n).write_bytes(body)
    staged = staged_artifact(staging, members=[{"name": n, "role": "keys"} for n in members])
    return merge.merge_side_files(staged)["keys"]


def _keys(tmp_path: Path) -> Path:
    return tmp_path / "live" / "keys"


@pytest.mark.parametrize("who", ["custody", "annotations"])
def test_a_restored_pair_gets_its_marker_and_reads_as_another_installations(tmp_path, who):
    members = _pair(who)
    out = _restore(tmp_path, members)
    assert sorted(out["restored"]) == sorted(members), out
    keys = _keys(tmp_path)
    assert (keys / f"{who}_ed25519.pem{SUFFIX}").is_file()
    pub = next(i["ed25519_public_key"] for i in out["identities"] if i["name"] == f"keys/{who}_ed25519.pem")
    assert ev.is_this_installations_key(pub, keys / f"{who}_ed25519.pem") is False  # never "this installation"
    assert data_scope.keys_folder_state(keys) == "app"  # the markers are the app's own names (R806)


def test_a_pair_kept_because_one_is_here_gets_no_marker(tmp_path):
    signing.HybridSigner()  # this installation's own custody pair
    out = _restore(tmp_path, _pair("custody"))
    assert sorted(out["kept_local"]) == ["keys/custody_ed25519.pem", "keys/custody_ml_dsa_65.key"]
    assert not (_keys(tmp_path) / f"custody_ed25519.pem{SUFFIX}").exists()


def test_a_marker_that_cannot_be_written_places_no_pair(tmp_path, monkeypatch):
    real = ev.mark_key_as_restored

    def refuse(path=None, *, backup_key=None):
        if path is not None and path.name == "custody_ed25519.pem":
            raise PermissionError("no write")
        return real(path, backup_key=backup_key)

    monkeypatch.setattr(ev, "mark_key_as_restored", refuse)
    members = _pair("custody")
    out = _restore(tmp_path, members)
    assert out["restored"] == [], out
    assert sorted(n["name"] for n in out["not_placed"]) == sorted(members)
    assert {n["reason"] for n in out["not_placed"]} == {merge._KEY_MARKER_UNWRITTEN}
    assert all(n.get("reason_i18n") for n in out["not_placed"])
    assert not (_keys(tmp_path) / "custody_ed25519.pem").exists()
    assert not (_keys(tmp_path) / "custody_ml_dsa_65.key").exists()


def test_a_pair_that_fails_to_place_takes_its_marker_back(tmp_path, monkeypatch):
    real = merge._place_key_file
    calls = []

    def fail_second(local, data):
        calls.append(local.name)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(local, data)

    monkeypatch.setattr(merge, "_place_key_file", fail_second)
    with pytest.raises(OSError):
        _restore(tmp_path, _pair("custody"))
    keys = _keys(tmp_path)
    assert not (keys / f"custody_ed25519.pem{SUFFIX}").exists()
    assert not (keys / "custody_ed25519.pem").exists() and not (keys / "custody_ml_dsa_65.key").exists()


def test_a_pair_raced_by_a_signer_takes_its_marker_back(tmp_path, monkeypatch):
    """The Ed25519 half is placed, then a signer makes the ML-DSA half itself: the restore takes its Ed25519 half back,
    and then its marker, since no Ed25519 key is left at that name."""
    real = merge._place_key_file
    theirs = _FakeMldsa.generate_keypair()

    def a_signer_makes_the_second_half(local, data):
        if local.name.endswith("_ml_dsa_65.key"):
            local.write_bytes(theirs[0] + theirs[1])
            return False
        return real(local, data)

    monkeypatch.setattr(merge, "_place_key_file", a_signer_makes_the_second_half)
    out = _restore(tmp_path, _pair("annotations"))
    keys = _keys(tmp_path)
    assert out["restored"] == [] and out["kept_local"] == ["keys/annotations_ml_dsa_65.key"], out
    assert not (keys / "annotations_ed25519.pem").exists()
    assert not (keys / f"annotations_ed25519.pem{SUFFIX}").exists()


def test_a_restored_half_that_could_not_be_taken_back_keeps_its_marker(tmp_path, monkeypatch):
    """The marker outlives the key: when the Ed25519 half stays (another caller rewrapped it meanwhile, or its removal
    failed), its marker stays with it, so it never reads as this installation's own."""
    real = merge._place_key_file

    def full_disk_on_the_second_half(local, data):
        if local.name.endswith("_ml_dsa_65.key"):
            raise OSError(28, "No space left on device")
        return real(local, data)

    def nothing_can_be_removed(made):
        return None

    monkeypatch.setattr(merge, "_place_key_file", full_disk_on_the_second_half)
    monkeypatch.setattr(merge, "_take_back_key_files", nothing_can_be_removed)
    with pytest.raises(OSError):
        _restore(tmp_path, _pair("custody"))
    keys = _keys(tmp_path)
    assert (keys / "custody_ed25519.pem").exists()
    assert (keys / f"custody_ed25519.pem{SUFFIX}").exists()


def test_a_signer_that_makes_a_new_key_drops_a_left_over_marker(tmp_path):
    keys = _keys(tmp_path)
    keys.mkdir()
    marker = keys / f"custody_ed25519.pem{SUFFIX}"
    marker.write_text("{}", encoding="utf-8")  # left by a restore whose key is gone
    signer = signing.HybridSigner()
    assert not marker.exists()
    pub = signer.public_identity().ed25519_pub
    assert ev.is_this_installations_key(pub, keys / "custody_ed25519.pem") is True


def test_a_signer_that_loads_an_existing_key_keeps_its_marker(tmp_path):
    _restore(tmp_path, _pair("custody"))
    signing.HybridSigner()  # loads the restored key, makes none
    assert (_keys(tmp_path) / f"custody_ed25519.pem{SUFFIX}").exists()


def test_an_unreadable_marker_state_is_never_this_installations(tmp_path, monkeypatch):
    signer = signing.HybridSigner()
    pub = signer.public_identity().ed25519_pub
    real_lstat = os.lstat

    def odd(p, *a, **k):
        if str(p).endswith(SUFFIX):
            raise PermissionError("cannot look")
        return real_lstat(p, *a, **k)

    monkeypatch.setattr(ev.os, "lstat", odd)
    assert ev.is_this_installations_key(pub, _keys(tmp_path) / "custody_ed25519.pem") is False


# --- the custody chain checks ---------------------------------------------------------------------------------------------- #
@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _log_two(client) -> None:
    for action in ("ingest", "access"):
        r = client.post("/api/custody/log", json={"item_id": "article:1", "item_hash": "a" * 64, "action": action})
        assert r.status_code == 200, r.text


def test_both_checks_call_a_restored_custody_key_another_installations(client, tmp_path):
    _log_two(client)
    bundle = client.post("/api/custody/export").json()
    mine = client.post("/api/custody/verify", json={"bundle": bundle}).json()
    assert mine["verified"] is True and mine["signer_is_yours"] is True
    # what a restore leaves: this installation's custody key now has the marker beside it
    (_keys(tmp_path) / f"custody_ed25519.pem{SUFFIX}").write_text("{}", encoding="utf-8")
    after = client.post("/api/custody/verify", json={"bundle": bundle}).json()
    assert after["verified"] is True  # what the bundle is accepted as is unchanged
    assert after["signer_is_yours"] is False and after["verdict"] == "signatures-valid-signer-not-yours"
    assert all(s["yours"] is False for s in after["signed_by"])
    from src.custody.log import RESTORED_CUSTODY_KEY_NOTE

    assert RESTORED_CUSTODY_KEY_NOTE in after["notes"]
    v = client.get("/api/custody/article:1/verify").json()
    assert v["verified"] is True and v["signed_by"] == "another-installation"


def test_an_erase_reads_the_markers_as_the_apps_own_and_leaves_none(tmp_path, monkeypatch):
    from src import paths
    from src.safety import crypto_erase

    data = tmp_path / "OOS data"  # a data folder the app chose, so the erase judges keys by its content (R806)
    data.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    _restore(tmp_path, {**_pair("custody"), **_pair("annotations"), "keys/evidence_ed25519.pem": _pem(Ed25519PrivateKey.generate())})
    keys = data / "keys"
    assert {f"{w}_ed25519.pem{SUFFIX}" for w in ("custody", "annotations", "evidence")} <= set(os.listdir(keys))
    assert data_scope.keys_folder_state(keys) == "app"
    out = crypto_erase.quick_crypto_erase(confirm=True)
    assert out["keys_folder"] == "app" and out["folder_kept_foreign"] is False and out["kept_items"] == 0, out
    assert out["removed"] is True and not data.exists(), out  # nothing left, markers included
