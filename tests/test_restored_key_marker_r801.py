"""R801: a key a restore placed counts as ANOTHER installation's until this one makes its own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ATTACK (security reads of row 339). An install that has only ever imported has no evidence key, and a restore places
the key a backup carries (R448). Crafted backup 1 plants a key; crafted backup 2, signed with it, then read as "signed
by this installation", and every trust flag it carried applied with no click. Now the restore writes a marker beside
the key BEFORE placing it, and while the marker exists :func:`src.reporting.evidence.is_this_installations_key` says
"another installation". Only :func:`load_or_create_signing_key` making a NEW key removes it. Cost, stated in the
release note: your own backup restored on a fresh machine gets the one-click offer until a new key exists.
"""

from __future__ import annotations

import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.backup import merge
from src.reporting import evidence as ev
from tests.backup_helper import staged_artifact

EVIDENCE = "keys/evidence_ed25519.pem"
MARKER = EVIDENCE + ev.RESTORED_KEY_MARKER_SUFFIX


@pytest.fixture(autouse=True)
def _plaintext_install(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "live"))
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr(connect, "_passphrase", None)
    (tmp_path / "live").mkdir()


def _pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _restore(tmp_path, members: dict[str, bytes], name: str = "staging"):
    staging = tmp_path / name
    for n, body in members.items():
        (staging / n).parent.mkdir(parents=True, exist_ok=True)
        (staging / n).write_bytes(body)
    staged = staged_artifact(staging, members=[{"name": n, "role": "keys"} for n in members])
    return merge.merge_side_files(staged)["keys"]


def test_a_planted_key_never_reads_as_this_installations(tmp_path):
    attacker = Ed25519PrivateKey.generate()
    out = _restore(tmp_path, {EVIDENCE: _pem(attacker)})
    live = tmp_path / "live"
    assert out["restored"] == [EVIDENCE]
    assert (live / MARKER).exists(), "the marker is written with the key"
    assert ev.existing_public_key_hex(live / EVIDENCE) == ev.public_key_hex(attacker)  # R448 restores it as before
    assert ev.is_this_installations_key(ev.public_key_hex(attacker)) is False


def test_the_marker_is_written_before_the_key(tmp_path, monkeypatch):
    seen = []
    real = merge._place_key_file

    def look(local, data):
        seen.append((local.name, (local.parent / (local.name + ev.RESTORED_KEY_MARKER_SUFFIX)).exists()))
        return real(local, data)

    monkeypatch.setattr(merge, "_place_key_file", look)
    _restore(tmp_path, {EVIDENCE: _pem(Ed25519PrivateKey.generate())})
    assert seen == [("evidence_ed25519.pem", True)]


def test_a_new_key_of_this_installations_own_removes_the_marker(tmp_path):
    live = tmp_path / "live"
    (live / "keys").mkdir()
    (live / MARKER).write_text("left behind")  # a marker with no key (a restore that failed after writing it)
    key = ev.load_or_create_signing_key()
    assert not (live / MARKER).exists()
    assert ev.is_this_installations_key(ev.public_key_hex(key)) is True


def test_loading_the_restored_key_keeps_the_marker(tmp_path):
    attacker = Ed25519PrivateKey.generate()
    _restore(tmp_path, {EVIDENCE: _pem(attacker)})
    ev.load_or_create_signing_key()  # an export signs with it: that is not this installation making its own
    assert (tmp_path / "live" / MARKER).exists()
    assert ev.is_this_installations_key(ev.public_key_hex(attacker)) is False


@pytest.mark.parametrize("form", ["link", "dangling-link", "folder", "unreadable", "empty"])
def test_any_marker_counts_as_present(tmp_path, form):
    key = ev.load_or_create_signing_key()
    m = tmp_path / "live" / MARKER
    if form == "link":
        (tmp_path / "elsewhere").write_text("x")
        os.symlink(tmp_path / "elsewhere", m)
    elif form == "dangling-link":
        os.symlink(tmp_path / "nowhere", m)
    elif form == "folder":
        m.mkdir()
    elif form == "unreadable":
        m.write_text("{}")
        m.chmod(0)
    else:
        m.write_bytes(b"")
    assert ev.is_this_installations_key(ev.public_key_hex(key)) is False


def test_a_backup_never_places_a_marker_of_its_own(tmp_path):
    out = _restore(tmp_path, {MARKER: b"{}"})
    assert out["restored"] == [] and out["not_placed"][0]["name"] == MARKER
    assert not (tmp_path / "live" / MARKER).exists()


def test_a_backup_never_removes_or_replaces_the_marker(tmp_path):
    _restore(tmp_path, {EVIDENCE: _pem(Ed25519PrivateKey.generate())})
    marker = tmp_path / "live" / MARKER
    before = marker.read_bytes()
    _restore(tmp_path, {EVIDENCE: _pem(Ed25519PrivateKey.generate()), MARKER: b"x"}, name="staging2")
    assert marker.read_bytes() == before


def test_the_marker_does_not_stick_to_a_key_this_install_made_while_the_restore_ran(tmp_path, monkeypatch):
    real = merge._reseal_key
    made = {}

    def an_export_makes_its_key_meanwhile(kind, local, raw, candidates, held):
        out = real(kind, local, raw, candidates, held)
        made["key"] = ev.load_or_create_signing_key(local)
        return out

    monkeypatch.setattr(merge, "_reseal_key", an_export_makes_its_key_meanwhile)
    out = _restore(tmp_path, {EVIDENCE: _pem(Ed25519PrivateKey.generate())})
    assert out["kept_local"] == [EVIDENCE]
    assert not (tmp_path / "live" / MARKER).exists()
    assert ev.is_this_installations_key(ev.public_key_hex(made["key"])) is True


def test_a_key_an_older_build_restored_is_recognised_from_its_import_report(tmp_path):
    key = ev.load_or_create_signing_key()
    reports = tmp_path / "live" / "import_reports"
    reports.mkdir()
    (reports / "restore-20261101T000000Z-1.json").write_text(json.dumps({"side_files": {"keys": {"identities": [
        {"name": EVIDENCE, "ed25519_public_key": ev.public_key_hex(key)}]}}}))
    assert ev.is_this_installations_key(ev.public_key_hex(key)) is False
    assert (tmp_path / "live" / MARKER).exists(), "marked once, so deleting the report changes nothing"
    (reports / "restore-20261101T000000Z-1.json").unlink()
    assert ev.is_this_installations_key(ev.public_key_hex(key)) is False


def test_a_report_naming_another_key_changes_nothing(tmp_path):
    key = ev.load_or_create_signing_key()
    reports = tmp_path / "live" / "import_reports"
    reports.mkdir()
    (reports / "restore-x.json").write_text(json.dumps({"side_files": {"keys": {"identities": [
        {"name": EVIDENCE, "ed25519_public_key": "ab" * 32}]}}}))
    (reports / "broken.json").write_text("{not json")
    assert ev.is_this_installations_key(ev.public_key_hex(key)) is True
    assert not (tmp_path / "live" / MARKER).exists()


def test_every_reader_asks_the_one_check(tmp_path, monkeypatch):
    """R801 (2): the backup list's signer relation (row 340) and the early passphrase verdict (R795) both say
    "another installation" for a key a restore placed, because both ask is_this_installations_key."""
    from src.backup import artifact
    from src.backup import stream_backup as sb

    attacker = Ed25519PrivateKey.generate()
    _restore(tmp_path, {EVIDENCE: _pem(attacker)})
    pub = ev.public_key_hex(attacker)
    assert artifact.signer_relation(pub, artifact.this_installation_key()) == "another-installation"
    m = {"kind": "x", "volumes": []}
    sig = attacker.sign(ev.canonical_bytes(m)).hex()
    m["signature"] = {"public_key": pub, "signature": sig}
    assert sb._manifest_signature_state(m) == "verified"
    assert sb._why_the_volume_list_is_not_ours(m) == sb.REASON_OTHER_INSTALLATION
    (tmp_path / "live" / MARKER).unlink()  # what only a new key of this installation's own does
    assert artifact.signer_relation(pub, artifact.this_installation_key()) == "this-installation"
    assert sb._why_the_volume_list_is_not_ours(m) is None


def test_no_reader_compares_keys_itself():
    """R801 (2): the comparison lives in evidence.is_this_installations_key alone."""
    import inspect

    from src.backup import artifact
    from src.backup import stream_backup as sb

    for fn in (artifact._is_this_installations_key, sb._why_the_volume_list_is_not_ours):
        src = inspect.getsource(fn)
        assert "is_this_installations_key(" in src and "fromhex" not in src and "key ==" not in src, fn.__name__
