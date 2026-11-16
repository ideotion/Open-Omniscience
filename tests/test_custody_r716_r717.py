"""R716 and R717, each condition pinned.

R716: a log whose key change nothing vouches for (keys re-created, post-quantum signing turned off before 0.5.1) needs
--accept-unendorsed-rotation offline; with it the checker never reads as a plain "verified" -- its output says the
change was unendorsed and what accepting it does not prove; the in-app check names it. R717: with post-quantum signing on
and its library missing, nothing is signed, the entry stays owed, the routes answer 503 (tested in
test_custody_pqc_rotation.py), the app shows the reason and the fix, owed entries are signed once the library is back
with no loss or reordering, and nothing else is blocked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.custody import signing
from src.custody.log import (
    ACCEPTED_UNENDORSED_NOTE,
    CustodyAction,
    CustodyLog,
    verify_export_report,
)
from src.custody.signing import HybridSigner

ROOT = Path(__file__).resolve().parents[1]
pqc = pytest.mark.skipif(not signing.PQC_AVAILABLE, reason="pqcrypto/ML-DSA not installed")


@pytest.fixture(autouse=True)
def _data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")


def _signer(tmp_path: Path, name: str, **kw) -> HybridSigner:
    return HybridSigner(ed25519_path=tmp_path / f"{name}.pem", mldsa_path=tmp_path / f"{name}.key", **kw)


def _re_created_key_bundle(tmp_path: Path) -> tuple[dict, dict]:
    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "old")) as log:
        log.record("a:1", "a" * 64, CustodyAction.INGEST)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "new")) as log:  # the key folder was lost
        log.record("a:2", "b" * 64, CustodyAction.INGEST)
        return log.export(), log.verify_report()


def test_r716_the_report_and_the_route_never_call_an_unendorsed_acceptance_plainly_verified(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    bundle, in_app = _re_created_key_bundle(tmp_path)
    assert not verify_export_report(bundle)["verified"]
    report = verify_export_report(bundle, accept_unendorsed_rotation=True)
    assert report["verified"] and report["accepted_unendorsed"]
    assert not verify_export_report({**bundle}, accept_unendorsed_rotation=False)["accepted_unendorsed"]
    # The in-app check names it (R716), and says it was accepted on the record's word.
    assert in_app["verified"] and in_app["accepted_unendorsed"]
    assert any("accepted on the record's word" in n for n in in_app["notes"])
    r = TestClient(app).post("/api/custody/verify", json={"bundle": bundle, "accept_unendorsed_rotation": True},
                             headers={"Sec-Fetch-Site": "same-origin"})
    body = r.json()
    assert r.status_code == 200 and body["verified"] and body["accepted_unendorsed"]
    assert body["accepted_unendorsed_note"] == ACCEPTED_UNENDORSED_NOTE
    assert "proves nothing about who signed after it" in ACCEPTED_UNENDORSED_NOTE


def test_r716_the_cli_says_unendorsed_and_exits_4_never_a_plain_verified(tmp_path):
    bundle, _ = _re_created_key_bundle(tmp_path)
    path = tmp_path / "b.json"
    path.write_text(json.dumps(bundle))
    cli = [sys.executable, str(ROOT / "scripts" / "verify_custody.py"), str(path)]
    refused = subprocess.run(cli, capture_output=True, text=True, cwd=ROOT)
    assert refused.returncode == 1 and "--accept-unendorsed-rotation" not in refused.stderr
    accepted = subprocess.run(cli + ["--accept-unendorsed-rotation"], capture_output=True, text=True, cwd=ROOT)
    assert accepted.returncode == 4, accepted.stdout + accepted.stderr
    line = next(ln for ln in accepted.stdout.splitlines() if ln.startswith("VERIFIED"))
    assert "UNENDORSED KEY CHANGE ACCEPTED" in line and ACCEPTED_UNENDORSED_NOTE in line


def test_r716_the_verify_instructions_name_the_flag_when_and_what_it_does_not_prove():
    doc = (ROOT / "scripts" / "verify_custody.py").read_text(encoding="utf-8")
    assert "4 = verified only by accepting an unendorsed key change" in doc
    assert "post-quantum\nsigning turned off before 0.5.1" in doc or "post-quantum signing turned off before 0.5.1" in doc
    assert "proves NOTHING about who made that change" in doc
    for name in ("docs/SECURITY.md", "docs/USER_MANUAL.md", "docs/QUICKSTART.md"):
        assert "--accept-unendorsed-rotation" in (ROOT / name).read_text(encoding="utf-8"), name


def test_r716_the_in_app_check_shows_a_warning_not_a_plain_verified():
    js = (ROOT / "src" / "static" / "app-ai-tools.js").read_text(encoding="utf-8")
    assert "d.verified && d.accepted_unendorsed" in js and "_custT(CUST_ACCEPTED_UNENDORSED)" in js


def test_r717_settings_shows_the_reason_and_the_fix_in_every_language():
    js = (ROOT / "src" / "static" / "app-ai-tools.js").read_text(encoding="utf-8")
    assert "s.pqc_enabled && !s.pqc_available" in js and "_custT(CUST_PQC_LIBRARY_MISSING)" in js
    start = js.index('const CUST_PQC_LIBRARY_MISSING = "')
    english = "".join(part.split('"')[1] for part in js[start:js.index(";", start)].split("+"))
    assert "install the library first and then turn the setting off" in english
    for lang in ("en", "fr", "de", "es", "pt", "ru", "id", "ja", "zh", "hi", "bn", "ar"):
        table = json.loads((ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        assert table.get(english), lang


@pqc
def test_r717_owed_entries_are_signed_once_the_library_is_back_in_order_with_none_lost(tmp_path, monkeypatch):
    from src.custody import pending
    from src.custody.settings import CustodySettings

    db = str(tmp_path / "c.db")
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        log.record("article:1", "1" * 64, CustodyAction.INGEST)
    for aid in (2, 3, 4):
        assert pending.note_failed(aid, item_hash=str(aid) * 64, url=f"https://x.example/{aid}", error="test")
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    out = pending.drain(prefs=CustodySettings(), log_factory=lambda: CustodyLog(db_path=db, signer=_signer(tmp_path, "k")))
    assert out["recorded"] == 0 and out["still_pending"] == 3
    assert out["pqc_unavailable"] == 3  # the drain stops at the first refusal and says why (the reads of #2032)
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        assert [e.item_id for e in log.all_entries()] == ["article:1"]
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    out = pending.drain(prefs=CustodySettings(), log_factory=lambda: CustodyLog(db_path=db, signer=_signer(tmp_path, "k")))
    assert out["recorded"] == 3 and out["still_pending"] == 0
    with CustodyLog(db_path=db, signer=_signer(tmp_path, "k")) as log:
        entries = log.all_entries()
        report = log.verify_report()
    assert [e.item_id for e in entries] == ["article:1", "article:2", "article:3", "article:4"]
    assert [e.item_hash for e in entries[1:]] == ["2" * 64, "3" * 64, "4" * 64]
    assert all(e.signature["algorithm"] == "hybrid" for e in entries)
    assert report["verified"] and not report["accepted_unendorsed"]  # no record, no gap: the same identity throughout
