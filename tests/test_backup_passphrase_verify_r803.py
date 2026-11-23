"""R803 (row 349): the backup VERIFY screen names a passphrase wrong only when the list of volumes is this installation's.

The verify check opened the ``key_check`` token stored in the volume list, and a failure always read "the passphrase does
not match this volume set". That token is protected only by the list's signature, and the list carries the key it was
signed with, so anyone who changes the set can write a token of their own and re-sign the list: the right passphrase then
read as wrong. Now the definite verdict is given only through R795's one shared helper (the list is signed, validly, by
this installation's own key); every other case says the passphrase could not be checked, with R795's reason, and the set
is never reported intact. What is accepted does not change.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.backup.stream_backup import (
    REASON_BAD_SIGNATURE,
    REASON_OTHER_INSTALLATION,
    REASON_OWN_KEY_UNREADABLE,
    REASON_UNSIGNED,
    UNCHECKED_REASONS,
    UNCHECKED_VERIFY_PASSPHRASE,
    _key_check,
    _manifest_signature_state,
    verify_stream_backup,
)
from tests.test_backup_passphrase_trust_r795 import (  # noqa: F401 - own_key is a fixture
    _manifest,
    _sign_with,
    _stream_set,
    _three_step_swap,
    _write_manifest,
    own_key,
)

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "src" / "static" / "app-backup.js"


def _codes(rep: dict) -> list[str]:
    return [c["code"] for c in rep["problem_codes"]]


def _pass_codes(rep: dict) -> list[str]:
    # the shared fixture deletes its parity volumes, so "bad-parity" rides along in every report
    return [c for c in _codes(rep) if c.startswith("passphrase-")]


def test_own_key_and_a_wrong_passphrase_says_does_not_match(tmp_path, own_key):  # noqa: F811
    dest = _stream_set(tmp_path)
    assert own_key.exists()
    rep = verify_stream_backup(dest, passphrase="not the words")
    assert rep["ok"] is False and rep["decrypted"] is False
    assert _pass_codes(rep) == ["passphrase-mismatch"]
    assert "the passphrase does not match this volume set" in rep["problems"]


def test_the_right_passphrase_on_its_own_backup_verifies(tmp_path, own_key):  # noqa: F811
    dest = _stream_set(tmp_path)
    rep = verify_stream_backup(dest, passphrase="pw")
    assert rep["decrypted"] is True and _pass_codes(rep) == []


def test_a_swapped_first_volume_re_signed_by_another_key_could_not_be_checked(tmp_path, own_key):  # noqa: F811
    dest = _stream_set(tmp_path)
    _three_step_swap(dest, tmp_path)
    rep = verify_stream_backup(dest, passphrase="not the words")
    assert rep["ok"] is False
    assert "passphrase-mismatch" not in _codes(rep)
    i = _codes(rep).index("passphrase-unchecked")
    assert rep["problem_codes"][i]["params"] == {"reason": REASON_OTHER_INSTALLATION}
    assert rep["problems"][i] == UNCHECKED_VERIFY_PASSPHRASE.format(
        reason=REASON_OTHER_INSTALLATION
    )


def test_a_token_rewritten_and_re_signed_never_makes_the_right_passphrase_wrong(tmp_path, own_key):  # noqa: F811
    """The attack itself: the stored check is replaced with one for other words, the list re-signed by another key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    dest = _stream_set(tmp_path)
    m = _manifest(dest)
    m["key_check"] = _key_check("someone else's words")
    _write_manifest(dest, _sign_with(m, Ed25519PrivateKey.generate()))
    assert (
        _manifest_signature_state(_manifest(dest)) == "verified"
    )  # a valid signature, just not ours
    rep = verify_stream_backup(dest, passphrase="pw")
    assert rep["ok"] is False and rep["decrypted"] is False  # never reported intact
    assert "passphrase-mismatch" not in _codes(rep)
    i = _codes(rep).index("passphrase-unchecked")
    assert rep["problem_codes"][i]["params"] == {"reason": REASON_OTHER_INSTALLATION}
    assert not any("does not match this volume set" in p for p in rep["problems"])


def test_a_list_changed_without_re_signing_could_not_be_checked(tmp_path, own_key):  # noqa: F811
    dest = _stream_set(tmp_path)
    m = _manifest(dest)
    m["key_check"] = _key_check("someone else's words")  # the signature is left as it was
    _write_manifest(dest, m)
    rep = verify_stream_backup(dest, passphrase="pw")
    assert rep["ok"] is False and "passphrase-mismatch" not in _codes(rep)
    i = _codes(rep).index("passphrase-unchecked")
    assert rep["problem_codes"][i]["params"] == {"reason": REASON_BAD_SIGNATURE}


def test_an_unreadable_own_key_could_not_be_checked_and_no_key_is_made(tmp_path, own_key):  # noqa: F811
    dest = _stream_set(tmp_path)
    own_key.write_bytes(b"not a key at all")
    rep = verify_stream_backup(dest, passphrase="not the words")
    assert "passphrase-mismatch" not in _codes(rep)
    i = _codes(rep).index("passphrase-unchecked")
    assert rep["problem_codes"][i]["params"] == {"reason": REASON_OWN_KEY_UNREADABLE}
    assert own_key.read_bytes() == b"not a key at all"


def test_an_unsigned_list_could_not_be_checked(tmp_path, own_key):  # noqa: F811
    dest = _stream_set(tmp_path)
    m = _manifest(dest)
    m.pop("signature", None)
    _write_manifest(dest, m)
    rep = verify_stream_backup(dest, passphrase="not the words")
    assert rep["ok"] is False
    assert "passphrase-mismatch" not in _codes(rep)
    i = _codes(rep).index("passphrase-unchecked")
    assert rep["problem_codes"][i]["params"] == {"reason": REASON_UNSIGNED}


def test_the_panel_knows_r795s_four_reasons_and_says_the_same_sentence():
    src = JS.read_text(encoding="utf-8")
    blk = src[src.index("const BACKUP_PASS_REASONS = [") :]
    blk = blk[: blk.index("];")]
    assert tuple(re.findall(r'^\s*"(.*)",$', blk, re.M)) == tuple(UNCHECKED_REASONS)
    frame = re.search(r'"passphrase-unchecked": "(.*)",$', src, re.M).group(1)
    server = UNCHECKED_VERIFY_PASSPHRASE
    assert frame == server[0].upper() + server[1:] + "."
    for f in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert "{reason}" in d[frame], f.name
        for r in UNCHECKED_REASONS:
            assert d.get(r), f"{f.name} lacks R795's reason {r[:30]}"


def test_the_panel_helper():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(
        ["node", str(ROOT / "tests" / "backup_problems_row348_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
