"""
Tests for signed evidence bundles (Action Plan Phase 5).

Proves the chain-of-custody is REAL: a bundle built from articles verifies; any
tampering with an item's content hash breaks the Merkle root; tampering with the
manifest or using the wrong key breaks the Ed25519 signature; and the standalone
verifier (scripts/verify_evidence.py) confirms a bundle with no DB/app.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source
from src.database.session import get_db
from src.reporting.evidence import (
    build_signed_bundle,
    load_or_create_signing_key,
    verify_bundle,
)


class _Art:
    """Lightweight stand-in with the attributes build_manifest reads."""

    def __init__(self, id, content, title="t"):
        self.id = id
        self.url = f"https://e/{id}"
        self.canonical_url = f"https://e/{id}"
        self.source_id = 1
        self.title = title
        self.published_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.hash = f"{id:064d}"
        self.content = content


def test_bundle_verifies(tmp_path):
    key = load_or_create_signing_key(tmp_path / "k.pem")
    bundle = build_signed_bundle([_Art(1, "alpha"), _Art(2, "beta")], key, case_name="Case A")
    ok, reason = verify_bundle(bundle)
    assert ok, reason
    assert bundle["manifest"]["merkle_root"]
    assert bundle["algorithm"] == "ed25519"


def test_tampered_content_hash_breaks_merkle(tmp_path):
    key = load_or_create_signing_key(tmp_path / "k.pem")
    bundle = build_signed_bundle([_Art(1, "alpha"), _Art(2, "beta")], key)
    bundle["manifest"]["items"][0]["content_sha256"] = "0" * 64  # tamper
    ok, reason = verify_bundle(bundle)
    assert not ok
    assert "merkle" in reason.lower()


def test_tampered_manifest_breaks_signature(tmp_path):
    key = load_or_create_signing_key(tmp_path / "k.pem")
    bundle = build_signed_bundle([_Art(1, "alpha")], key)
    # Change a field that is NOT a merkle leaf, so only the signature should fail.
    bundle["manifest"]["case_name"] = "forged"
    ok, reason = verify_bundle(bundle)
    assert not ok
    assert "signature" in reason.lower()


def test_wrong_key_fails(tmp_path):
    key = load_or_create_signing_key(tmp_path / "k.pem")
    bundle = build_signed_bundle([_Art(1, "alpha")], key)
    other = load_or_create_signing_key(tmp_path / "other.pem")
    from src.reporting.evidence import public_key_hex
    bundle["public_key"] = public_key_hex(other)
    ok, _ = verify_bundle(bundle)
    assert not ok


def test_key_persists(tmp_path):
    p = tmp_path / "k.pem"
    k1 = load_or_create_signing_key(p)
    k2 = load_or_create_signing_key(p)
    from src.reporting.evidence import public_key_hex
    assert public_key_hex(k1) == public_key_hex(k2)


def test_standalone_verifier_script(tmp_path):
    key = load_or_create_signing_key(tmp_path / "k.pem")
    bundle = build_signed_bundle([_Art(1, "alpha")], key)
    bundle_file = tmp_path / "bundle.json"
    bundle_file.write_text(json.dumps(bundle))
    repo = Path(__file__).resolve().parents[1]
    res = subprocess.run(
        [sys.executable, str(repo / "scripts" / "verify_evidence.py"), str(bundle_file)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "VERIFIED       : True" in res.stdout
    # tamper -> nonzero exit
    bundle["manifest"]["items"][0]["content_sha256"] = "f" * 64
    bundle_file.write_text(json.dumps(bundle))
    res2 = subprocess.run(
        [sys.executable, str(repo / "scripts" / "verify_evidence.py"), str(bundle_file)],
        capture_output=True, text=True,
    )
    assert res2.returncode == 1


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))  # signing key under tmp
    engine = create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="S", domain="s.example"))
        s.flush()
        s.add(Article(url="https://s/1", canonical_url="https://s/1", source_id=1,
                      title="leak", content="a leaked memo", hash="1".rjust(64, "0")))
        s.commit()

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_export_and_verify_via_api(client):
    r = client.post("/api/reports/evidence", json={"article_ids": [1], "case_name": "Memo"})
    assert r.status_code == 200, r.text
    bundle = r.json()
    assert bundle["manifest"]["item_count"] == 1
    # round-trip through the verify endpoint
    v = client.post("/api/reports/evidence/verify", json=bundle)
    assert v.json()["verified"] is True


def test_export_requires_selection(client):
    assert client.post("/api/reports/evidence", json={}).status_code == 400
