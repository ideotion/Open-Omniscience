"""The custody reads make nothing (R694, R278 finding F2).

Before, ``GET /api/custody/settings``, ``GET /api/custody/{item_id}`` and ``/verify`` each built the signer (which creates
``keys/custody_ed25519.pem`` and, with post-quantum signing on, the ML-DSA pair) and opened the log (which creates
``custody_log.db``): a page anywhere could make an install mint its signing key with an ``<img src>``. The export, which signs, is a
POST now; the reads open only what exists, report "no key yet" or 404, and never rewrite a key file.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    with TestClient(app) as c:
        yield c


def _made(tmp_path) -> set[str]:
    names = {"custody_log.db", "custody_log.db-wal", "custody_log.db-shm"}
    found = {n for n in names if (tmp_path / n).exists()}
    if (tmp_path / "keys").exists():
        found |= {"keys/" + p.name for p in (tmp_path / "keys").iterdir()} or {"keys/"}
    return found


def test_a_fresh_install_reads_custody_and_makes_nothing(client, tmp_path):
    s = client.get("/api/custody/settings")
    assert s.status_code == 200, s.text
    body = s.json()
    assert body["keys_created"] is False
    assert body["signer"] is None and body["key_protection"] is None
    assert body["pqc_effective"] is False  # nothing has been signed, so nothing is claimed
    assert client.get("/api/custody/article:1").status_code == 404
    v = client.get("/api/custody/article:1/verify")
    assert v.status_code == 404 and v.json()["detail"] == "no custody entries for that item"
    assert _made(tmp_path) == set()


def test_the_export_is_a_post_and_a_get_does_nothing(client, tmp_path):
    # A GET of /export now matches the item read, /{item_id} with the id "export": no log, so 404, and nothing is made.
    assert client.get("/api/custody/export").status_code == 404
    assert _made(tmp_path) == set()
    r = client.post("/api/custody/export")
    assert r.status_code == 200 and r.json()["entry_count"] == 0
    assert "keys/custody_ed25519.pem" in _made(tmp_path)  # the export signs its head: the explicit act makes the key


def test_after_the_first_entry_the_reads_report_the_real_signer(client, tmp_path):
    r = client.post("/api/custody/log", json={"item_id": "article:3", "item_hash": "d" * 64, "action": "ingest"})
    assert r.status_code == 200, r.text
    body = client.get("/api/custody/settings").json()
    assert body["keys_created"] is True
    assert body["signer"]["ed25519_pub"]
    assert body["key_protection"] == "plaintext-0600"  # no passphrase in this test
    assert client.get("/api/custody/article:3").json()["entry_count"] == 1
    assert client.get("/api/custody/article:3/verify").json()["verified"] is True
    assert client.get("/api/custody/article:4").status_code == 404


def test_a_reader_never_rewraps_a_key_file(tmp_path, monkeypatch):
    # A key written in the clear, then a passphrase held: the next SIGNER wraps it in place; a reader leaves the bytes alone and says
    # what the file holds.
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    from src.custody.signing import HybridSigner

    HybridSigner(use_pqc=False)
    pem = tmp_path / "keys" / "custody_ed25519.pem"
    before = pem.read_bytes()
    monkeypatch.setenv("OO_KEY_PASSPHRASE", "a test passphrase that is long enough")
    reader = HybridSigner(use_pqc=False, create=False)
    assert reader.key_protection == "plaintext-0600"
    assert pem.read_bytes() == before
    assert HybridSigner(use_pqc=False).key_protection == "aes256gcm-scrypt"  # the signer still wraps it
    assert pem.read_bytes() != before


def test_a_reader_with_no_key_raises_and_makes_no_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.custody.log import CustodyLog
    from src.custody.signing import HybridSigner

    with pytest.raises(FileNotFoundError):
        HybridSigner(create=False)
    with pytest.raises(FileNotFoundError):
        CustodyLog(create=False)
    assert _made(tmp_path) == set()


def test_a_reader_log_refuses_to_sign(tmp_path, monkeypatch):
    # A reader loads no signer: one that signed would do it Ed25519-only and leave a legacy key unwrapped, so it is refused by name.
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.custody.log import CustodyLog

    with CustodyLog() as writer:
        writer.record("article:1", "e" * 64, writer_action())
    with CustodyLog(create=False) as reader:
        assert len(reader.entries_for("article:1")) == 1
        with pytest.raises(RuntimeError, match="opened to read cannot sign"):
            reader.export()


def writer_action():
    from src.custody.log import CustodyAction

    return CustodyAction("ingest")


def test_a_log_whose_key_was_lost_says_so(client, tmp_path):
    client.post("/api/custody/log", json={"item_id": "article:5", "item_hash": "f" * 64, "action": "ingest"})
    for p in (tmp_path / "keys").iterdir():
        p.unlink()
    body = client.get("/api/custody/settings").json()
    assert body["keys_created"] is False and body["log_exists"] is True  # the tab says "keys: missing", not "none yet"
    assert not any((tmp_path / "keys").iterdir())


def test_an_unreadable_key_is_reported_not_a_500(client, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_KEY_PASSPHRASE", "the first passphrase, long enough")
    client.post("/api/custody/log", json={"item_id": "article:6", "item_hash": "0" * 64, "action": "ingest"})
    monkeypatch.setenv("OO_KEY_PASSPHRASE", "another passphrase, also long enough")
    r = client.get("/api/custody/settings")
    assert r.status_code == 200, r.text
    assert r.json()["key_protection"] == "unreadable" and r.json()["keys_created"] is True
