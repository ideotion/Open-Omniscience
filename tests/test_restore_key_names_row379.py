"""R808 (row 379): a restore places only the key files this app creates, by the exact names an erase uses.

An erase treats the data folder's ``keys`` as the app's only while it holds nothing but
``src.safety.data_scope.APP_KEY_NAMES`` (R806/R807). A restore used to place any file the backup's keys folder carried,
"carried as it is", so a backup could leave the folder holding names the app never makes. Now everything else is not
written, is counted, stays in the backup, and is listed (up to a cap) by a name made printable and cut.
"""

from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.backup import merge
from src.reporting import evidence as ev
from src.safety import data_scope
from tests.backup_helper import staged_artifact

EVIDENCE = "keys/evidence_ed25519.pem"


@pytest.fixture(autouse=True)
def _plaintext_install(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "live"))
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr(connect, "_passphrase", None)
    (tmp_path / "live").mkdir()


def _pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _restore(tmp_path, members: dict[str, bytes]):
    staging = tmp_path / "staging"
    for n, body in members.items():
        (staging / n).parent.mkdir(parents=True, exist_ok=True)
        (staging / n).write_bytes(body)
    staged = staged_artifact(staging, members=[{"name": n, "role": "keys"} for n in members])
    return merge.merge_side_files(staged)["keys"]


def test_the_restore_places_from_the_erase_list():
    marker = "evidence_ed25519.pem" + ev.RESTORED_KEY_MARKER_SUFFIX
    assert merge._APP_KEY_FILES == data_scope.APP_KEY_NAMES - {marker}
    assert all(merge._key_slot(n) is not None for n in merge._APP_KEY_FILES)
    # row 385: only names the app actually writes; the evidence signer has no ML-DSA key
    assert "evidence_ml_dsa_65.key" not in data_scope.APP_KEY_NAMES and len(merge._APP_KEY_FILES) == 5


@pytest.mark.parametrize(
    "name",
    [
        "keys/notes.txt",
        "keys/foreign_ed25519.pem",  # key-shaped, but no signer of this app is called "foreign"
        "keys/evidence_ed25519.pem.bak",
        "keys/x_ml_dsa_65.key",
        "keys/evidence_ml_dsa_65.key",  # row 385: no version of the app wrote it
        "keys/.hidden",
    ],
)
def test_a_name_the_app_does_not_create_is_not_placed_and_counted(tmp_path, name):
    body = _pem(Ed25519PrivateKey.generate()) if name.endswith(".pem") else b"x" * 32
    out = _restore(tmp_path, {name: body, EVIDENCE: _pem(Ed25519PrivateKey.generate())})
    assert out["restored"] == [EVIDENCE], out
    assert out["not_placed"] == [{"name": name, "reason": merge._KEY_NOT_APP, "reason_i18n": out["not_placed"][0]["reason_i18n"]}]
    assert out["not_app_keys"] == {"count": 1, "listed": 1}
    live_keys = tmp_path / "live" / "keys"
    assert not (tmp_path / "live" / name).exists()
    assert set(os.listdir(live_keys)) <= data_scope.APP_KEY_NAMES | {data_scope.KEYS_PENDING}
    assert data_scope.keys_folder_state(live_keys) == "app"  # what an erase reads it as (R806)


def test_every_one_is_counted_and_only_the_first_ones_listed(tmp_path):
    n = merge._KEY_NOT_APP_LISTED + 7
    out = _restore(tmp_path, {f"keys/extra{i:03d}.txt": b"x" for i in range(n)})
    assert out["not_app_keys"] == {"count": n, "listed": merge._KEY_NOT_APP_LISTED}
    assert len(out["not_placed"]) == merge._KEY_NOT_APP_LISTED
    from src.backup.import_reports import render_import_report_markdown

    md = render_import_report_markdown({"outcome": "ok", "side_files": {"keys": out}})
    assert f"and 7 more files that are not keys this app creates ({n} in all)" in md


def test_a_shown_name_is_printable_and_cut():
    shown = merge._shown_key_name("keys/a\nVERIFIED : True‮" + "z" * 500)
    assert "\n" not in shown and "‮" not in shown
    assert "\\x0a" in shown and "\\u202e" in shown
    assert shown.endswith("more characters)") and len(shown) < merge._KEY_NAME_SHOWN_MAX + 40


def test_the_reason_is_translated_in_every_locale():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    for f in sorted(root.glob("*.json")):
        assert merge._KEY_NOT_APP in json.loads(f.read_text(encoding="utf-8")), f.name


@pytest.mark.parametrize(
    "names",
    [
        [f"keys/d{i}/x" for i in range(merge._KEY_NOT_APP_LISTED + 3)],  # outside keys/: refused as unsafe
        [f"keys/a{i}\u202e.restored-from-backup" for i in range(merge._KEY_NOT_APP_LISTED + 3)],  # marker spellings
    ],
)
def test_every_name_refusal_is_counted_capped_and_shown_printable(tmp_path, names):
    out = _restore(tmp_path, {n: b"x" for n in names})
    assert out["not_app_keys"] == {"count": len(names), "listed": merge._KEY_NOT_APP_LISTED}
    assert len(out["not_placed"]) == merge._KEY_NOT_APP_LISTED
    assert all("\u202e" not in e["name"] for e in out["not_placed"])


@pytest.mark.parametrize("name", ["keys/./evidence_ed25519.pem", "keys//evidence_ed25519.pem"])
def test_another_spelling_of_a_path_is_refused(tmp_path, name):
    out = _restore(tmp_path, {name: _pem(Ed25519PrivateKey.generate())})
    assert out["restored"] == [] and out["not_placed"][0]["reason"] == merge._KEY_UNSAFE_NAME, out
