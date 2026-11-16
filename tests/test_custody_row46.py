"""Open-on-main row 46 (Lane F's part): a lone surrogate is refused by name, and nothing unsigned in a bundle can say
other than its signed head."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.custody.log import CustodyAction, CustodyLog, verify_export
from src.custody.signing import HybridSigner

ROOT = Path(__file__).resolve().parents[1]


def _bundle(tmp_path: Path) -> dict:
    with CustodyLog(db_path=str(tmp_path / "c.db"),
                    signer=HybridSigner(ed25519_path=tmp_path / "k.pem", mldsa_path=tmp_path / "k.key")) as log:
        log.record("a:1", "a" * 64, CustodyAction.INGEST)
        log.record("a:2", "b" * 64, CustodyAction.INGEST)
        return log.export()


def test_a_lone_surrogate_is_refused_by_name_and_writes_nothing(tmp_path, monkeypatch):
    from src.api import custody as api
    from src.api.main import app

    db = str(tmp_path / "c.db")
    signer = HybridSigner(ed25519_path=tmp_path / "k.pem", mldsa_path=tmp_path / "k.key")
    with CustodyLog(db_path=db, signer=signer) as log, pytest.raises(ValueError, match="lone surrogate"):
        log.record("a:\ud800", "a" * 64, CustodyAction.INGEST)
    monkeypatch.setattr(api, "_log", lambda: CustodyLog(db_path=db, signer=signer))
    body = '{"item_id": "a:\\ud800", "item_hash": "' + "a" * 64 + '", "action": "ingest"}'
    r = TestClient(app).post("/api/custody/log", content=body,
                             headers={"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 400 and "lone surrogate" in r.json()["detail"]
    with CustodyLog(db_path=db, signer=signer) as log:
        assert log.all_entries() == []


@pytest.mark.parametrize("field,value", [("entry_count", 99), ("log_version", "oo-custody-9"), ("bundle_format", 1)])
def test_an_unsigned_top_level_field_that_disagrees_with_the_head_is_refused(tmp_path, field, value):
    bundle = _bundle(tmp_path)
    assert verify_export(bundle) == (True, [])
    forged = copy.deepcopy(bundle)
    forged[field] = value
    ok, issues = verify_export(forged)
    assert not ok and f"unsigned {field}" in issues[0]
    # Absent is fine: only the signed head is read.
    del forged[field]
    assert verify_export(forged)[0]


def test_the_printed_signer_must_be_the_heads_both_halves(tmp_path):
    bundle = _bundle(tmp_path)
    forged = copy.deepcopy(bundle)
    forged["signer"] = {**forged["signer"], "ml_dsa_variant": "ml_dsa_65", "ml_dsa_pub": "ab" * 32}
    ok, issues = verify_export(forged)
    assert not ok and "names another post-quantum (ML-DSA) key than the one its head was signed with" in issues[0]


def test_the_cli_prints_the_signed_heads_fields(tmp_path):
    bundle = _bundle(tmp_path)
    path = tmp_path / "b.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_custody.py"), str(path)],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "entry_count    : 2" in out.stdout
