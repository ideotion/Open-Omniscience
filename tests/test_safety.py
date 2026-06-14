"""
Tests for at-risk-user safety (Theme 2): crypto, encrypted backup, panic, fetch-mode.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honest-crypto checks: a wrong passphrase or a tampered file fails loudly (never returns
garbage); a non-OO payload cannot overwrite the corpus; panic actually deletes; protected
mode sets the proxy + a generic UA. No network is touched.
"""

from __future__ import annotations

import pytest

from src.safety import panic_wipe
from src.safety.crypto import EncryptionError, decrypt_bytes, encrypt_bytes


# --- crypto ----------------------------------------------------------------- #
def test_encrypt_roundtrip():
    blob = encrypt_bytes(b"top secret corpus", "correct horse battery staple")
    assert blob != b"top secret corpus"
    assert decrypt_bytes(blob, "correct horse battery staple") == b"top secret corpus"


def test_wrong_passphrase_fails_loudly():
    blob = encrypt_bytes(b"x" * 100, "right")
    with pytest.raises(EncryptionError):
        decrypt_bytes(blob, "wrong")


def test_tampered_ciphertext_rejected():
    blob = bytearray(encrypt_bytes(b"data", "pw"))
    blob[-1] ^= 0x01  # flip a bit in the GCM tag
    with pytest.raises(EncryptionError):
        decrypt_bytes(bytes(blob), "pw")


def test_not_an_oo_encrypted_file():
    with pytest.raises(EncryptionError):
        decrypt_bytes(b"not our format", "pw")


def test_empty_passphrase_refused():
    with pytest.raises(EncryptionError):
        encrypt_bytes(b"x", "")


# --- encrypted backup / restore -------------------------------------------- #
@pytest.fixture()
def live_db(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.database.session import init_db

    init_db()
    return tmp_path


def test_make_encrypted_backup_creates_a_valid_encrypted_snapshot(live_db):
    """Backup CREATION still works (and stays): the blob is encrypted and decrypts
    to a real SQLite snapshot. The destructive restore_encrypted_backup (which
    REPLACED the corpus) was removed 2026-06-13 — restore is additive-only now,
    exclusively via the merge engine (covered by the torture suite). The guard in
    tests/test_additive_restore_only.py asserts no replace path comes back."""
    from src.safety import make_encrypted_backup
    from src.safety.crypto import _MAGIC, decrypt_bytes

    blob = make_encrypted_backup("pw1234")
    assert blob.startswith(_MAGIC)  # encrypted envelope
    plaintext = decrypt_bytes(blob, "pw1234")
    assert plaintext.startswith(b"SQLite format 3\x00")  # a genuine SQLite snapshot
    with pytest.raises(EncryptionError):  # wrong passphrase is refused loudly
        decrypt_bytes(blob, "nope")


# --- panic ------------------------------------------------------------------ #
def test_panic_requires_confirm(tmp_path):
    (tmp_path / "a.db").write_bytes(b"x" * 100)
    with pytest.raises(PermissionError):
        panic_wipe(tmp_path)


def test_panic_wipes(tmp_path):
    (tmp_path / "a.db").write_bytes(b"x" * 100)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.json").write_text("{}", encoding="utf-8")
    report = panic_wipe(tmp_path, confirm=True)
    assert report["files_seen"] == 2 and report["files_wiped"] == 2
    assert not tmp_path.exists()
    assert "SSD" in report["limit"]  # honest about the limit


# --- fetch mode / protected fetch ------------------------------------------ #
def test_make_fetcher_transparent_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_FETCH_MODE", raising=False)
    monkeypatch.delenv("OO_HTTP_PROXY", raising=False)
    from src.ingest import DEFAULT_USER_AGENT
    from src.safety.fetcher import make_fetcher

    f = make_fetcher()
    assert f.proxy is None
    assert f.user_agent == DEFAULT_USER_AGENT


def test_make_fetcher_protected_uses_proxy_and_generic_ua(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_FETCH_MODE", "protected")
    monkeypatch.setenv("OO_HTTP_PROXY", "socks5://127.0.0.1:9050")
    from src.safety.fetcher import make_fetcher

    f = make_fetcher()
    assert f.proxy == "socks5://127.0.0.1:9050"
    assert f.session.proxies.get("https") == "socks5://127.0.0.1:9050"
    assert "OpenOmniscience" not in f.user_agent  # generic UA, does not name the tool


def test_protected_mode_requires_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_FETCH_MODE", raising=False)
    monkeypatch.delenv("OO_HTTP_PROXY", raising=False)
    from src.safety.settings import SafetySettingsError, save_settings

    with pytest.raises(SafetySettingsError):
        save_settings({"fetch_mode": "protected", "http_proxy": ""})


# --- safety API ------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_api_settings_get_and_protected_requires_proxy(client):
    assert client.get("/api/safety/settings").json()["fetch_mode"] == "transparent"
    bad = client.put("/api/safety/settings", json={"fetch_mode": "protected", "http_proxy": ""})
    assert bad.status_code == 400
    ok = client.put(
        "/api/safety/settings",
        json={"fetch_mode": "protected", "http_proxy": "socks5://127.0.0.1:9050"},
    )
    assert ok.status_code == 200 and ok.json()["fetch_mode"] == "protected"


def test_api_encrypted_backup_create_works_and_replace_restore_is_gone(client):
    # Backup CREATION still works and stays.
    blob = client.post("/api/safety/backup/encrypted", json={"passphrase": "pw"}).content
    assert blob[:8] == b"OOENC1\x00\x00"
    # The destructive replace-restore endpoint was REMOVED (additive-only ruling,
    # 2026-06-13): restoring is exclusively the additive merge at
    # /api/database/v2/restore. The old route no longer exists.
    r = client.post(
        "/api/safety/restore/encrypted",
        files={"file": ("b.ooenc", blob, "application/octet-stream")},
        data={"passphrase": "pw"},
    )
    assert r.status_code == 404


def test_api_panic_requires_confirm(client):
    assert client.post("/api/safety/panic", json={"confirm": False}).status_code == 400
