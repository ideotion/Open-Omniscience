"""Row 382 (R800): GET /api/custody/{item}/verify says WHO signed the chain it verified.

A chain verifies against the keys its own entries carry, which proves only that it is unchanged since they signed it.
The anchor key (the last entry's Ed25519 key) is compared with this installation's custody key, read without creating
anything, through R801's one comparison point; the reply carries ``signed_by`` and ``signer_key``. What a chain is
accepted as does not change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.reporting.evidence import RESTORED_KEY_MARKER_SUFFIX

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def _log_two(client) -> None:
    for action in ("ingest", "access"):
        r = client.post("/api/custody/log", json={"item_id": "article:1", "item_hash": "a" * 64, "action": action})
        assert r.status_code == 200, r.text


def _custody_pub(client) -> str:
    entries = client.get("/api/custody/article:1").json()["entries"]
    return entries[-1]["signature"]["ed25519"]["pub"]


def test_a_chain_this_installation_signed_says_so(client):
    _log_two(client)
    v = client.get("/api/custody/article:1/verify").json()
    assert v["verified"] is True
    assert v["signed_by"] == "this-installation"
    assert v["signer_key"] == _custody_pub(client)


def test_a_chain_signed_with_another_key_says_another_installation_and_is_still_verified(client, tmp_path):
    _log_two(client)
    anchor = _custody_pub(client)
    key = tmp_path / "keys" / "custody_ed25519.pem"
    key.unlink()
    from src.custody.signing import HybridSigner

    HybridSigner(use_pqc=False, create=True)  # a key of its own, as on another computer
    assert key.exists()
    v = client.get("/api/custody/article:1/verify").json()
    assert v["verified"] is True  # what the chain is accepted as is unchanged
    assert v["signed_by"] == "another-installation"
    assert v["signer_key"] == anchor


def _swap_custody_key(tmp_path) -> None:
    from src.custody.signing import HybridSigner

    (tmp_path / "keys" / "custody_ed25519.pem").unlink()
    HybridSigner(use_pqc=False, create=True)


def test_the_answer_is_about_the_item_not_the_last_entry_of_the_log(client, tmp_path):
    """Security reads A and B: an item signed by another key stays another installation's after this installation's
    next append (which writes an unendorsed rotation to its own key), and an item signed after it is this one's."""
    _log_two(client)
    _swap_custody_key(tmp_path)
    r = client.post("/api/custody/log", json={"item_id": "article:2", "item_hash": "b" * 64, "action": "ingest"})
    assert r.status_code == 200, r.text
    old = client.get("/api/custody/article:1/verify").json()
    new = client.get("/api/custody/article:2/verify").json()
    assert old["verified"] is True and new["verified"] is True
    assert old["signed_by"] == "another-installation"
    assert new["signed_by"] == "this-installation"
    assert old["signer_key"] != new["signer_key"]


def test_an_item_signed_partly_here_and_partly_elsewhere_is_not_called_either(client, tmp_path):
    _log_two(client)
    _swap_custody_key(tmp_path)
    r = client.post("/api/custody/log", json={"item_id": "article:1", "item_hash": "a" * 64, "action": "access"})
    assert r.status_code == 200, r.text
    v = client.get("/api/custody/article:1/verify").json()
    assert v["verified"] is True
    assert v["signed_by"] == "not-compared"


def test_the_signer_is_taken_from_the_entries_that_were_verified(client, monkeypatch):
    """One read of the log: the anchor never comes from a second read an append could have changed."""
    _log_two(client)
    from src.custody import log as custody_log

    calls = []
    real = custody_log.CustodyLog.all_entries

    def counting(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(custody_log.CustodyLog, "all_entries", counting)
    assert client.get("/api/custody/article:1/verify").json()["signed_by"] == "this-installation"
    assert len(calls) == 1


def test_with_no_custody_key_here_the_signer_is_not_compared_and_no_key_is_made(client, tmp_path):
    _log_two(client)
    key = tmp_path / "keys" / "custody_ed25519.pem"
    key.unlink()
    v = client.get("/api/custody/article:1/verify").json()
    assert v["verified"] is True
    assert v["signed_by"] == "not-compared"
    assert re.fullmatch(r"[0-9a-f]{64}", v["signer_key"])
    assert not key.exists()  # a verify is a read: it never creates the key it compares with


def test_a_restore_marker_beside_the_custody_key_reads_as_another_installation(client, tmp_path):
    _log_two(client)
    key = tmp_path / "keys" / "custody_ed25519.pem"
    key.with_name(key.name + RESTORED_KEY_MARKER_SUFFIX).write_text("{}", encoding="utf-8")
    v = client.get("/api/custody/article:1/verify").json()
    assert v["signed_by"] == "another-installation"


def test_a_chain_that_does_not_verify_names_no_signer(client, tmp_path, monkeypatch):
    _log_two(client)
    from src.custody import log as custody_log

    monkeypatch.setattr(custody_log.CustodyLog, "verify_report",
                        lambda self, entries=None: {"verified": False, "issues": ["broken"], "notes": [], "accepted_unendorsed": False})
    v = client.get("/api/custody/article:1/verify").json()
    assert v["verified"] is False
    assert v["signed_by"] is None and v["signer_key"] is None


def test_the_view_shows_the_r800_labels_and_only_for_a_verified_chain():
    src = (ROOT / "src/static/app-ai-tools.js").read_text(encoding="utf-8")
    body = src[src.index("function custodySignerWords"):src.index("async function exportCustody")]
    for label in ("Signed by this installation, key {fp}", "Signed by another installation, key {fp}", "Signed by key {fp}"):
        assert f'"{label}"' in body
    assert "d.verified ? custodySignerWords(d.signed_by, d.signer_key)" in body
    assert "esc(signer)" in body  # plain text, escaped where it is written
