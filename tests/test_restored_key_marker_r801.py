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
    (live / MARKER).write_text("left behind", encoding="utf-8")  # a marker with no key (a restore that failed after writing it)
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
        (tmp_path / "elsewhere").write_text("x", encoding="utf-8")
        os.symlink(tmp_path / "elsewhere", m)
    elif form == "dangling-link":
        os.symlink(tmp_path / "nowhere", m)
    elif form == "folder":
        m.mkdir()
    elif form == "unreadable":
        m.write_text("{}", encoding="utf-8")
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


def test_an_import_report_never_marks_a_key(tmp_path):
    """Security reads of R801: import reports travel in backups, so a report naming this installation's public key
    (which every bundle it shares carries) must not demote its own key; R801 (5) is answered "not recognisable"."""
    key = ev.load_or_create_signing_key()
    reports = tmp_path / "live" / "import_reports"
    reports.mkdir()
    (reports / "restore-x.json").write_text(json.dumps({"side_files": {"keys": {"identities": [
        {"name": EVIDENCE, "ed25519_public_key": ev.public_key_hex(key)}]}}}), encoding="utf-8")
    assert ev.is_this_installations_key(ev.public_key_hex(key)) is True
    assert not (tmp_path / "live" / MARKER).exists()


@pytest.mark.parametrize("spelling", ["keys/EVIDENCE_ed25519.pem", "keys/Evidence_ED25519.PEM",
                                      "keys/evidence_ed25519.pem.", "keys/evidence_ed25519.pem ",
                                      "keys/EVIDENCE_ED25519.PEM.RESTORED-FROM-BACKUP",
                                      "keys/CUSTODY_ed25519.pem", "keys/Annotations_ML_DSA_65.key"])
def test_another_spelling_of_a_key_or_the_marker_is_never_placed(tmp_path, spelling):
    """Security reads of R801: on a filesystem that ignores case (macOS, Windows) or trailing dots (Windows), these
    ARE the evidence key or its marker; placed by name they skipped the marker."""
    out = _restore(tmp_path, {spelling: _pem(Ed25519PrivateKey.generate())})
    assert out["restored"] == [] and out["not_placed"][0]["name"] == spelling
    assert list((tmp_path / "live" / "keys").iterdir()) == []  # no key, and the up-front marker taken back


def test_a_key_that_lands_on_the_evidence_name_by_any_route_keeps_the_marker(tmp_path, monkeypatch):
    """The marker is settled by whether an evidence key exists after this restore placed something, never by the
    name a member was carried under: a carried file that a filesystem aliases onto the key still leaves it marked."""
    real = merge._place_key_file
    key = Ed25519PrivateKey.generate()

    def aliasing(local, data):
        # what a case-insensitive or short-name filesystem would do with another spelling (since R808 only the app's own
        # names are placed, so the carried file is another of them)
        if local.name == "annotations_ed25519.pem":
            return real(local.parent / "evidence_ed25519.pem", _pem(key))
        return real(local, data)

    monkeypatch.setattr(merge, "_place_key_file", aliasing)
    _restore(tmp_path, {"keys/annotations_ed25519.pem": _pem(Ed25519PrivateKey.generate())})
    assert (tmp_path / "live" / MARKER).exists()
    assert ev.is_this_installations_key(ev.public_key_hex(key)) is False


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


def test_a_file_beside_the_key_that_is_no_key_is_not_placed(tmp_path):
    """R808 (row 379) replaced "carried as it is": only the key files this app creates are placed."""
    out = _restore(tmp_path, {"keys/evidence_ed25519.pem.bak": b"an operator's copy", "keys/OLD_ed25519.pem": b"x"})
    assert out["restored"] == [] and out["not_app_keys"]["count"] == 2
    assert {n["name"]: n["reason"] for n in out["not_placed"]} == {
        "keys/evidence_ed25519.pem.bak": merge._KEY_NOT_APP,
        "keys/OLD_ed25519.pem": merge._KEY_NOT_APP,  # not one of the app's names (its case differs from none of them)
    }
    assert not (tmp_path / "live" / "keys" / "evidence_ed25519.pem.bak").exists()
    assert not (tmp_path / "live" / MARKER).exists()  # no evidence key was placed


def test_a_key_an_export_makes_while_the_restore_looks_never_gets_the_marker(tmp_path, monkeypatch):
    """Security re-read of R801: an export making this installation's key between the restore's look and its marker
    write left the marker on the installation's OWN key, for good. Both now run under the key-file lock."""
    import threading

    real = ev.mark_key_as_restored
    made = {}

    def an_export_tries_meanwhile(*a, **k):
        t = threading.Thread(target=lambda: made.setdefault("key", ev.load_or_create_signing_key()))
        t.start()
        t.join(timeout=0.5)
        assert t.is_alive(), "the export waits for the restore's look and write"
        out = real(*a, **k)
        made["thread"] = t
        return out

    monkeypatch.setattr(ev, "mark_key_as_restored", an_export_tries_meanwhile)
    _restore(tmp_path, {"keys/notes.txt": b"x"})
    made["thread"].join(timeout=10)
    assert ev.is_this_installations_key(ev.public_key_hex(made["key"])) is True
    assert not (tmp_path / "live" / MARKER).exists()


def test_two_restores_run_one_after_the_other(tmp_path, monkeypatch):
    """Security re-reads of R801: two restores at once could let one take back the marker the other relied on."""
    import threading

    order = []
    real = merge._restore_key_members_now

    def slow(staged, base):
        order.append("start")
        out = real(staged, base)
        order.append("end")
        return out

    monkeypatch.setattr(merge, "_restore_key_members_now", slow)
    attacker = Ed25519PrivateKey.generate()
    staging = tmp_path / "s1"
    (staging / "keys").mkdir(parents=True)
    (staging / EVIDENCE).write_bytes(_pem(attacker))
    staged = staged_artifact(staging, members=[{"name": EVIDENCE, "role": "keys"}])
    threads = [threading.Thread(target=merge._restore_key_members, args=(staged, tmp_path / "live")) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert order == ["start", "end"] * 4
    assert (tmp_path / "live" / MARKER).exists()
    assert ev.is_this_installations_key(ev.public_key_hex(attacker)) is False
