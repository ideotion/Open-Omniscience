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


def test_encrypted_backup_roundtrip(live_db):
    from src.safety import make_encrypted_backup, restore_encrypted_backup

    blob = make_encrypted_backup("pw1234")
    from src.safety.crypto import _MAGIC
    assert blob.startswith(_MAGIC)
    report = restore_encrypted_backup(blob, "pw1234")
    assert report["restored"] is True and report["validated_rows"] >= 0


def test_restore_wrong_passphrase(live_db):
    from src.safety import make_encrypted_backup, restore_encrypted_backup
    blob = make_encrypted_backup("pw1234")
    with pytest.raises(EncryptionError):
        restore_encrypted_backup(blob, "nope")


def test_restore_rejects_non_oo_payload(live_db):
    from src.backup.sqlite_backup import BackupError
    from src.safety import restore_encrypted_backup
    # A correctly-encrypted but non-database payload must NOT overwrite the corpus.
    blob = encrypt_bytes(b"this is not a sqlite database", "pw")
    with pytest.raises(BackupError):
        restore_encrypted_backup(blob, "pw")


# --- panic ------------------------------------------------------------------ #
def test_panic_requires_confirm(tmp_path):
    (tmp_path / "a.db").write_bytes(b"x" * 100)
    with pytest.raises(PermissionError):
        panic_wipe(tmp_path)


def test_panic_wipes(tmp_path):
    (tmp_path / "a.db").write_bytes(b"x" * 100)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.json").write_text("{}")
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
    ok = client.put("/api/safety/settings",
                    json={"fetch_mode": "protected", "http_proxy": "socks5://127.0.0.1:9050"})
    assert ok.status_code == 200 and ok.json()["fetch_mode"] == "protected"


def test_api_encrypted_backup_then_restore(client):
    blob = client.post("/api/safety/backup/encrypted", json={"passphrase": "pw"}).content
    assert blob[:8] == b"OOENC1\x00\x00"
    # restore via multipart
    r = client.post("/api/safety/restore/encrypted",
                    files={"file": ("b.ooenc", blob, "application/octet-stream")},
                    data={"passphrase": "pw"})
    assert r.status_code == 200 and r.json()["restored"] is True
    # wrong passphrase -> 400
    bad = client.post("/api/safety/restore/encrypted",
                      files={"file": ("b.ooenc", blob, "application/octet-stream")},
                      data={"passphrase": "WRONG"})
    assert bad.status_code == 400


def test_api_panic_requires_confirm(client):
    assert client.post("/api/safety/panic", json={"confirm": False}).status_code == 400
